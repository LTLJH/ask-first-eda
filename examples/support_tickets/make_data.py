"""Generate a deterministic, fictional second-quarter support ticket snapshot."""

from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
import json
from pathlib import Path
import random


HERE = Path(__file__).resolve().parent
SEED = 20250630
KST = timezone(timedelta(hours=9))
START = date(2025, 4, 1)
SNAPSHOT = datetime(2025, 7, 1, tzinfo=KST)
HOLIDAYS = {date(2025, 5, 5), date(2025, 6, 6)}
INCIDENT_DAYS = {date(2025, 6, day) for day in range(16, 19)}
SLA_MINUTES = {"P1": 60, "P2": 240, "P3": 480, "P4": 1440}
ACTIVE_HOURS = {"P1": (40, 56), "P2": (6, 18), "P3": (3, 13), "P4": (2, 9)}


def shift(day):
    if day.weekday() >= 5 or day in HOLIDAYS:
        return None
    return datetime.combine(day, time(9), KST), datetime.combine(day, time(18), KST)


def minutes(delta):
    return int(delta.total_seconds()) // 60


def after_business_minutes(start, delay):
    day = start.date()
    while True:
        staffed = shift(day)
        if staffed:
            opens, closes = staffed
            begins = max(start, opens)
            available = max(0, minutes(closes - begins))
            if delay <= available:
                return begins + timedelta(minutes=delay)
            delay -= available
        day += timedelta(days=1)


def business_minutes(start, end):
    total = 0
    for offset in range((end.date() - start.date()).days + 1):
        staffed = shift(start.date() + timedelta(days=offset))
        if staffed:
            opens, closes = staffed
            total += max(0, minutes(min(end, closes) - max(start, opens)))
    return total


def make_ticket(rng, number, created, priority, area, tier):
    events = []

    def record(at, status):
        events.append({"at": at, "status": status})

    record(created, "new")

    # 1. Responses follow staffing windows. Late and never-answered tickets also occur.
    target = SLA_MINUTES[priority]
    delay = rng.randint(max(2, target // 10), target * 9 // 10)
    if rng.random() < 0.10:
        delay = rng.randint(target + 1, 2 * target)
    planned_response = after_business_minutes(created, delay)
    assigned = min(created + timedelta(minutes=rng.randint(3, 45)), planned_response - timedelta(minutes=1))
    if assigned < SNAPSHOT:
        record(assigned, "assigned")

    response = resolved = csat = None
    if planned_response < SNAPSHOT and rng.random() >= 0.04:
        response = planned_response
        low, high = ACTIVE_HOURS[priority]
        active = timedelta(minutes=rng.randint(low * 60, high * 60))

        # 2. Customer replies pause the clock. A wait can still be open at the snapshot.
        resumed = response
        if rng.random() < 0.32:
            waiting = response + active / 2
            waiting = waiting.replace(second=0)
            resumed = waiting + timedelta(minutes=rng.randint(4 * 60, 30 * 60))
            active -= waiting - response
            if waiting < SNAPSHOT:
                record(waiting, "waiting_customer")
                if resumed < SNAPSHOT:
                    record(resumed, "assigned")

        # 4. Some tickets remain open for investigation, and quarter-end work is right-censored.
        planned_resolution = resumed + active
        if planned_resolution < SNAPSHOT and rng.random() >= 0.045:
            resolved = planned_resolution
            record(resolved, "resolved")

            # 3. Reopened tickets keep their first resolved time and close after a second fix.
            reopens = resolved + timedelta(hours=rng.randint(6, 30))
            second_fix = reopens + timedelta(hours=rng.randint(5, 22))
            closes = second_fix + timedelta(hours=rng.randint(2, 10))
            if rng.random() < 0.09 and closes < SNAPSHOT:
                record(reopens, "reopened")
                record(reopens + timedelta(minutes=30), "assigned")
                record(second_fix, "resolved")
                record(closes, "closed")
            elif reopens < SNAPSHOT:
                record(reopens, "closed")

            # 8. Only resolved tickets can have CSAT. Faster outcomes get more replies.
            fast = resolved - created < timedelta(hours=24)
            if rng.random() < (0.24 if fast else 0.10):
                weights = (2, 3, 10, 35, 50) if fast else (8, 12, 27, 35, 18)
                csat = rng.choices(range(1, 6), weights=weights)[0]

    return {
        "ticket_id": f"T{number:06d}", "created_at": created,
        "channel": rng.choices(("email", "chat", "phone"), weights=(62, 28, 10))[0],
        "priority": priority, "customer_tier": tier, "product_area": area,
        "assignee_team": {"login": "platform", "integrations": "technical_support",
                          "workspace": "product_support", "billing": "account_support"}[area],
        "events": events, "first_response_at": response, "resolved_at": resolved, "csat": csat,
    }


def generate(rng):
    tickets = []
    for offset in range((SNAPSHOT.date() - START).days):
        day = START + timedelta(days=offset)
        midnight = datetime.combine(day, time(), KST)
        # 6. The login outage adds P1 volume without changing P1's handling process.
        incident_volume = 40 if day in INCIDENT_DAYS else 0
        for index in range(15 + incident_volume):
            created = midnight + timedelta(minutes=rng.randrange(24 * 60))
            priority = rng.choices(list(SLA_MINUTES), weights=(9, 22, 38, 31))[0]
            area = rng.choice(("login", "integrations", "workspace", "billing"))
            tier = rng.choices(("enterprise", "standard", "free", None), weights=(25, 46, 22, 7))[0]
            if index >= 15:
                priority, area = "P1", "login"
            if day == date(2025, 6, 30) and index == 0:
                # After hours on the final day, this P1 is pending only on the business clock.
                created, priority = midnight + timedelta(hours=20, minutes=15), "P1"
            tickets.append(make_ticket(rng, len(tickets) + 1, created, priority, area, tier))

    # 7. Repeat contacts have their own handling histories. The link identifies the original.
    eligible = [row for row in tickets if row["created_at"].date() < min(INCIDENT_DAYS)]
    for original in rng.sample(eligible, 15):
        created = original["created_at"] + timedelta(minutes=rng.randint(10, 90))
        duplicate = make_ticket(rng, len(tickets) + 1, created, original["priority"],
                                original["product_area"], original["customer_tier"])
        duplicate["duplicate_of"] = original["ticket_id"]
        tickets.append(duplicate)
    return sorted(tickets, key=lambda row: (row["created_at"], row["ticket_id"]))


def response_facts(tickets, clock):
    results = Counter()
    for row in tickets:
        response = row["first_response_at"]
        spent = clock(row["created_at"], response or SNAPSHOT)
        if spent > SLA_MINUTES[row["priority"]]:
            results["breached"] += 1
        else:
            results["pending" if response is None else "met"] += 1
    denominator = results["met"] + results["breached"]
    return {**results, "denominator": denominator,
            "compliance_pct": round(results["met"] / denominator * 100, 4)}


def mean_hours(durations):
    return round(sum(durations) / (60 * len(durations)), 4) if durations else None


def resolution_minutes(row):
    return minutes(row["resolved_at"] - row["created_at"])


def waiting_minutes(row):
    total = 0
    for event, following in zip(row["events"], row["events"][1:]):
        if event["at"] >= row["resolved_at"]:
            break
        if event["status"] == "waiting_customer":
            total += minutes(following["at"] - event["at"])
    return total


def cohort_facts(tickets, days):
    cohort = [row for row in tickets if row["created_at"].date() in days]
    durations = {priority: [] for priority in SLA_MINUTES}
    for row in cohort:
        if row["resolved_at"] is not None:
            durations[row["priority"]].append(resolution_minutes(row))
    elapsed = [value for group in durations.values() for value in group]
    return {"tickets": len(cohort), "p1_tickets": sum(row["priority"] == "P1" for row in cohort),
            "resolved_tickets": len(elapsed), "mean_elapsed_hours": mean_hours(elapsed),
            "mean_elapsed_hours_by_priority": {key: mean_hours(group) for key, group in durations.items()},
            "resolved_tickets_by_priority": {key: len(group) for key, group in durations.items() if group}}


def summarize(tickets, zones, date_shifts):
    originals = [row for row in tickets if "duplicate_of" not in row]
    solved = [row for row in originals if row["resolved_at"] is not None]
    reopened = [row for row in solved if any(event["status"] == "reopened" for event in row["events"])]
    dates = [row["created_at"].date().isoformat() for row in originals]
    return {
        "rows": len(tickets), "created_date_range_kst": [min(dates), max(dates)],
        "created_at_by_timezone": dict(zones), "created_at_date_shifts_to_kst": date_shifts,
        "duplicate_rows": len(tickets) - len(originals),
        "unresolved_rows": sum(row["resolved_at"] is None for row in tickets),
        "unresolved_originals": len(originals) - len(solved),
        "missing_customer_tier_rows": sum(row["customer_tier"] is None for row in tickets),
        "unanswered_originals": sum(row["first_response_at"] is None for row in originals),
        "first_response_sla": {
            "business_hours": response_facts(originals, business_minutes),
            "elapsed_time": response_facts(originals, lambda start, end: minutes(end - start)),
        },
        "resolution": {
            "resolved_denominator": len(solved),
            "mean_elapsed_hours": mean_hours([resolution_minutes(row) for row in solved]),
            "mean_excluding_waiting_customer_hours": mean_hours([
                resolution_minutes(row) - waiting_minutes(row) for row in solved
            ]),
            "reopened_tickets": len(reopened),
            "reopened_mean_to_first_resolved_hours": mean_hours([resolution_minutes(row) for row in reopened]),
            "reopened_mean_to_final_closed_hours": mean_hours([
                minutes(row["events"][-1]["at"] - row["created_at"]) for row in reopened
            ]),
        },
        "incident_comparison": {
            "previous_week": cohort_facts(originals, {day - timedelta(days=7) for day in INCIDENT_DAYS}),
            "incident": cohort_facts(originals, INCIDENT_DAYS),
        },
        "csat": {
            "rated_resolved": sum(row["csat"] is not None for row in solved),
            "rated_unresolved": sum(row["csat"] is not None and row["resolved_at"] is None for row in originals),
            "missing_originals": sum(row["csat"] is None for row in originals),
        },
    }


def utc_stamp(at):
    return at.astimezone(timezone.utc).isoformat().removesuffix("+00:00") + "Z"


def main():
    rng = random.Random(SEED)
    tickets = generate(rng)
    zones = Counter()
    date_shifts = 0
    with (HERE / "tickets.jsonl").open("w", encoding="utf-8", newline="\n") as target:
        for row in tickets:
            # 5. Some records use UTC Z for every timestamp, including dates shifted by conversion.
            use_utc = rng.random() < 0.15
            zones["Z" if use_utc else "+09:00"] += 1
            if use_utc:
                at = row["created_at"]
                date_shifts += at.date() != at.astimezone(timezone.utc).date()
            target.write(json.dumps(row, default=utc_stamp if use_utc else datetime.isoformat) + "\n")
    facts = summarize(tickets, zones, date_shifts)
    (HERE / "expected_facts.json").write_text(json.dumps(facts, indent=2, sort_keys=True) + "\n",
                                               encoding="utf-8", newline="\n")


if __name__ == "__main__":
    main()
