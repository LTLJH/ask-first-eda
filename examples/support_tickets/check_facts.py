"""Recalculate the recorded facts from tickets.jsonl using only the standard library."""

from bisect import bisect_left
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path


HERE = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
START = datetime(2025, 4, 1, tzinfo=KST)
END = datetime(2025, 7, 1, tzinfo=KST)
HOLIDAYS = {date(2025, 5, 5), date(2025, 6, 6)}
SLA_HOURS = {"P1": 1, "P2": 4, "P3": 8, "P4": 24}
TRANSITIONS = {
    "new": {"assigned"},
    "assigned": {"waiting_customer", "resolved"},
    "waiting_customer": {"assigned"},
    "resolved": {"reopened", "closed"},
    "reopened": {"assigned"},
    "closed": set(),
}


def require(condition, message):
    if not condition:
        raise SystemExit(f"FAIL: {message}")


def parse(value):
    if value is None:
        return None
    stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(stamp.tzinfo is not None and stamp.second == stamp.microsecond == 0,
            f"expected minute-aligned timestamps with offsets: {value}")
    return stamp.astimezone(KST)


def read_tickets(path):
    tickets = []
    zones = Counter()
    date_shifts = 0
    with path.open(encoding="utf-8") as source:
        for line in source:
            row = json.loads(line)
            stamp = row["created_at"]
            zone = "Z" if stamp.endswith("Z") else stamp[-6:]
            zones[zone] += 1
            row["created_at"] = parse(stamp)
            date_shifts += row["created_at"].date().isoformat() != stamp[:10]
            row["first_response_at"] = parse(row["first_response_at"])
            row["resolved_at"] = parse(row["resolved_at"])
            row["events"] = [(parse(event["at"]), event["status"]) for event in row["events"]]
            tickets.append(row)
    return tickets, dict(zones), date_shifts


def validate(tickets):
    by_id = {row["ticket_id"]: row for row in tickets}
    require(len(by_id) == len(tickets) == 1500, "expected 1,500 distinct ticket IDs")
    for ticket_id, row in by_id.items():
        created = row["created_at"]
        response = row["first_response_at"]
        resolved = row["resolved_at"]
        events = row["events"]
        rating = row["csat"]
        original_id = row.get("duplicate_of")
        require(ticket_id.startswith("T0") and len(ticket_id) == 7 and ticket_id[1:].isdigit(),
                f"invalid ticket ID: {ticket_id}")
        require(START <= created < END and events[0] == (created, "new"), ticket_id)
        require(all(a < b and s2 in TRANSITIONS[s1]
                    for (a, s1), (b, s2) in zip(events, events[1:])), ticket_id)
        require(events[-1][0] < END, ticket_id)
        require(response is None or (
            len(events) > 1 and events[1][0] <= response < END
            and (resolved is None or response <= resolved)
        ), ticket_id)
        require(resolved == next((at for at, status in events if status == "resolved"), None),
                f"resolved_at must match the first resolution: {ticket_id}")
        require(resolved is None or response is not None, ticket_id)
        require(rating is None or (resolved is not None and type(rating) is int and 1 <= rating <= 5),
                f"invalid CSAT: {ticket_id}")
        if original_id is not None:
            original = by_id.get(original_id)
            require(original is not None and "duplicate_of" not in original
                    and original["created_at"] < created
                    and all(row[key] == original[key] for key in ("customer_tier", "product_area")),
                    f"invalid duplicate link: {ticket_id}")


def business_minutes():
    """Index each staffed minute independently of the generator's daily intersections."""
    staffed = []
    for day_index in range((END - START).days):
        midnight = START + timedelta(days=day_index)
        if midnight.weekday() < 5 and midnight.date() not in HOLIDAYS:
            staffed.extend(midnight + timedelta(minutes=minute) for minute in range(9 * 60, 18 * 60))
    return lambda start, end: bisect_left(staffed, end) - bisect_left(staffed, start)


def clock_facts(tickets, minutes_between):
    met = late = pending = 0
    for row in tickets:
        response = row["first_response_at"]
        minutes = minutes_between(row["created_at"], response or END)
        within_target = minutes <= 60 * SLA_HOURS[row["priority"]]
        if not within_target:
            late += 1
        elif response is None:
            pending += 1
        else:
            met += 1
    return {"met": met, "breached": late, "pending": pending, "denominator": met + late,
            "compliance_pct": round(100 * met / (met + late), 4)}


def hours(delta):
    return delta.total_seconds() / 3600


def average(values):
    return round(sum(values) / len(values), 4)


def resolution_facts(solved):
    elapsed, active, first, last = [], [], [], []
    for row in solved:
        created, resolved = row["created_at"], row["resolved_at"]
        elapsed.append(hours(resolved - created))
        events = row["events"]
        paused = sum(hours(min(end, resolved) - start)
                     for (start, status), (end, _) in zip(events, events[1:])
                     if status == "waiting_customer" and start < resolved)
        active.append(elapsed[-1] - paused)
        if any(status == "reopened" for _, status in events):
            require(events[-1][1] == "closed", f"reopened ticket without closure: {row['ticket_id']}")
            first.append(elapsed[-1])
            last.append(hours(events[-1][0] - created))
    return {"resolved_denominator": len(solved), "mean_elapsed_hours": average(elapsed),
            "mean_excluding_waiting_customer_hours": average(active), "reopened_tickets": len(first),
            "reopened_mean_to_first_resolved_hours": average(first),
            "reopened_mean_to_final_closed_hours": average(last)}


def incident_facts(tickets, start_day):
    cohort = [row for row in tickets if date(2025, 6, start_day) <= row["created_at"].date()
              < date(2025, 6, start_day + 3)]
    solved = [row for row in cohort if row["resolved_at"] is not None]
    means = {}
    for priority in SLA_HOURS:
        durations = [hours(row["resolved_at"] - row["created_at"]) for row in solved
                     if row["priority"] == priority]
        means[priority] = average(durations) if durations else None
    return {"tickets": len(cohort), "p1_tickets": sum(row["priority"] == "P1" for row in cohort),
            "resolved_tickets": len(solved), "mean_elapsed_hours": average([
                hours(row["resolved_at"] - row["created_at"]) for row in solved
            ]), "mean_elapsed_hours_by_priority": means,
            "resolved_tickets_by_priority": dict(Counter(row["priority"] for row in solved))}


def calculate(tickets, zones, date_shifts):
    originals = [row for row in tickets if "duplicate_of" not in row]
    solved = [row for row in originals if row["resolved_at"] is not None]
    ratings = [row for row in originals if row["csat"] is not None]
    days = sorted({row["created_at"].date().isoformat() for row in originals})
    return {
        "rows": len(tickets), "created_date_range_kst": [days[0], days[-1]],
        "created_at_by_timezone": zones, "created_at_date_shifts_to_kst": date_shifts,
        "duplicate_rows": len(tickets) - len(originals),
        "unresolved_rows": sum(row["resolved_at"] is None for row in tickets),
        "unresolved_originals": len(originals) - len(solved),
        "missing_customer_tier_rows": sum(row["customer_tier"] is None for row in tickets),
        "unanswered_originals": sum(row["first_response_at"] is None for row in originals),
        "first_response_sla": {
            "business_hours": clock_facts(originals, business_minutes()),
            "elapsed_time": clock_facts(originals, lambda start, end: 60 * hours(end - start)),
        },
        "resolution": resolution_facts(solved),
        "incident_comparison": {"previous_week": incident_facts(originals, 9),
                                "incident": incident_facts(originals, 16)},
        "csat": {"rated_resolved": sum(row["resolved_at"] is not None for row in ratings),
                 "rated_unresolved": sum(row["resolved_at"] is None for row in ratings),
                 "missing_originals": len(originals) - len(ratings)},
    }


def main():
    data_path = HERE / "tickets.jsonl"
    facts_path = HERE / "expected_facts.json"
    require(data_path.is_file() and facts_path.is_file(), "tickets.jsonl and expected_facts.json are required")
    tickets, zones, date_shifts = read_tickets(data_path)
    validate(tickets)
    actual = calculate(tickets, zones, date_shifts)
    expected = json.loads(facts_path.read_text(encoding="utf-8"))
    for key in sorted(actual.keys() | expected.keys()):
        require(key in actual and key in expected and actual[key] == expected[key],
                f"{key}: expected {expected.get(key)!r}, recalculated {actual.get(key)!r}")

    sla = actual["first_response_sla"]
    business, elapsed = sla["business_hours"], sla["elapsed_time"]
    resolution = actual["resolution"]
    previous = actual["incident_comparison"]["previous_week"]
    incident = actual["incident_comparison"]["incident"]
    require(actual["created_date_range_kst"] == ["2025-04-01", "2025-06-30"], "wrong quarter")
    require(set(zones) == {"+09:00", "Z"} and zones["+09:00"] > zones["Z"] > 0 and date_shifts > 0,
            "missing mixed timestamps or KST date shifts")
    require(0 < actual["duplicate_rows"] < 50 and actual["missing_customer_tier_rows"] > 0,
            "missing a small duplicate cohort or missing customer tiers")
    require(0 < business["pending"] < actual["unanswered_originals"]
            and business["denominator"] < elapsed["denominator"]
            and business["compliance_pct"] - elapsed["compliance_pct"] >= 20,
            "SLA clock change must affect the denominator and raise compliance by at least 20 points")
    require(actual["unresolved_originals"] > 0 and
            resolution["mean_excluding_waiting_customer_hours"] < resolution["mean_elapsed_hours"],
            "missing unresolved tickets or an effect from waiting_customer")
    require(0 < resolution["reopened_tickets"] and
            resolution["reopened_mean_to_first_resolved_hours"] < resolution["reopened_mean_to_final_closed_hours"],
            "missing reopened tickets or an effect from using final closure")
    require(incident["p1_tickets"] / incident["tickets"] >= 0.6
            and previous["p1_tickets"] / previous["tickets"] <= 0.2
            and incident["mean_elapsed_hours"] > previous["mean_elapsed_hours"],
            "missing the incident priority mix or increase in aggregate resolution time")
    reweighted = sum(previous["mean_elapsed_hours_by_priority"][priority] * count
                     for priority, count in incident["resolved_tickets_by_priority"].items())
    reweighted /= incident["resolved_tickets"]
    mix_effect = reweighted - previous["mean_elapsed_hours"]
    require(mix_effect >= 5 and mix_effect > abs(incident["mean_elapsed_hours"] - reweighted),
            "the priority mix must explain most of the shift in mean resolution time")
    require(actual["csat"]["rated_resolved"] > 0 and actual["csat"]["rated_unresolved"] == 0
            and actual["csat"]["missing_originals"] > (len(tickets) - actual["duplicate_rows"]) / 2,
            "CSAT should be sparse and limited to resolved tickets")
    print(f"OK: {len(actual)} fact groups match expected_facts.json; all 8 scenario traps verified.")
    print(f"First-response SLA: business {business['met']}/{business['denominator']} "
          f"({business['compliance_pct']:.4f}%), elapsed {elapsed['met']}/{elapsed['denominator']} "
          f"({elapsed['compliance_pct']:.4f}%).")


if __name__ == "__main__":
    main()
