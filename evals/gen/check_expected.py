"""Recompute the evaluation metrics directly from the saved input files."""

from collections import defaultdict
import csv
from datetime import datetime, timedelta
from fractions import Fraction
import json
from pathlib import Path
import re
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter
from openpyxl.utils.exceptions import InvalidFileException


CASES = Path(__file__).resolve().parents[1] / "cases"
RATE_UNIT = "kg steam/t product"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"), parse_float=Fraction)


def throughput(path):
    with path.open(encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, strict=True)
        if reader.fieldnames != ["hour_start", "line_status", "units_produced"]:
            raise ValueError("unexpected throughput CSV header")
        records = []
        for line, row in enumerate(reader, start=2):
            start = datetime.fromisoformat(row["hour_start"])
            status = row["line_status"]
            units = int(row["units_produced"])
            if reader.line_num != line or None in row or status not in ("open", "closed"):
                raise ValueError(f"invalid throughput record at CSV line {line}")
            if records and start - records[-1][1] != timedelta(hours=1):
                raise ValueError(f"nonconsecutive hour at CSV line {line}")
            records.append((line, start, status, units))

    def rate(name, rows, conditional):
        numerator = sum(row[3] for row in rows)
        denominator = len(rows)
        lines = [row[0] for row in rows]
        return {
            "name": f"{name}_hour_throughput",
            "conditional": conditional,
            "numerator": numerator,
            "denominator": denominator,
            "value": Fraction(numerator, denominator),
            "unit": "units/h",
            "numerator_rows": lines,
            "denominator_rows": lines,
        }

    operating = [row for row in records if row[2] == "open"]
    resolved = {"denominator_status": "resolved", "metrics": [rate("operating", operating, False)]}
    return {}, {
        "A": resolved,
        "B": resolved,
        "C": {
            "denominator_status": "unresolved",
            "metrics": [rate("elapsed", records, True), rate("operating", operating, True)],
        },
    }


def daily_orders(path):
    order_paths = defaultdict(list)
    item_paths = defaultdict(list)
    quantities = defaultdict(int)
    order_ids = set()
    text_id = None
    for index, order in enumerate(read_json(path)):
        order_id = order["order_id"]
        if type(order_id) is not str or order_id in order_ids:
            raise ValueError(f"invalid or duplicate order ID at $[{index}]")
        order_ids.add(order_id)
        day = order["order_date"]
        order_paths[day].append(f"$[{index}]")
        if order_id.isdecimal() and order_id.startswith("0") and len(order_id) > 1:
            text_id = f"$[{index}].order_id"
        for item_index, item in enumerate(order["items"]):
            if type(item["qty"]) is not int or type(item["sku"]) is not str:
                raise ValueError(f"invalid item at $[{index}].items[{item_index}]")
            item_paths[day].append(f"$[{index}].items[{item_index}]")
            quantities[day] += item["qty"]

    dates = sorted(order_paths)
    order_refs = [f"orders_day{index}" for index in range(1, len(dates) + 1)]
    item_refs = [f"items_day{index}" for index in range(1, len(dates) + 1)]
    refs = {"text_id": text_id}
    for day, order_ref, item_ref in zip(dates, order_refs, item_refs):
        refs[order_ref] = order_paths[day]
        refs[item_ref] = item_paths[day]

    def metric(name, unit, values, source_refs, condition=None):
        change = values[-1] - values[0]
        if change > 0:
            trend = "increase"
        elif change < 0:
            trend = "decrease"
        else:
            trend = "unchanged"
        result = {
            "name": name, "unit": unit, "values": values, "denominator": None,
            "change": change, "trend": trend, "conditional": condition is not None,
            "source_refs": source_refs,
        }
        if condition is not None:
            result["condition"] = f"If volume means {condition}"
        return result

    orders = [len(order_paths[day]) for day in dates]
    items = [len(item_paths[day]) for day in dates]
    pieces = [quantities[day] for day in dates]
    return {"dates_in_order": dates, "source_refs": refs}, {
        "B": {"metrics": [metric("daily_orders", "orders", orders, order_refs)]},
        "C": {
            "metrics": [
                metric("daily_orders", "orders", orders, order_refs, "order count"),
                metric("daily_item_lines", "item lines", items, item_refs, "item-line count"),
            ],
            "optional_metrics": [
                metric("daily_pieces", "pieces", pieces, item_refs, "sum of qty"),
            ],
        },
    }


def sheet_records(sheet):
    rows = sheet.values
    next(rows)
    headers = next(rows)
    return [(line, dict(zip(headers, values))) for line, values in enumerate(rows, start=3)]


def utility_batches(path):
    workbook = load_workbook(path, read_only=True)
    try:
        batch_records = sheet_records(workbook["batches"])
        meter_records = sheet_records(workbook["meter_readings"])
    finally:
        workbook.close()

    batches = {}
    replays = []
    for line, row in batch_records:
        key = row["batch_id"]
        if key in batches:
            first_line, first_row = batches[key]
            if row != first_row:
                raise ValueError(f"conflicting batch records for {key}: rows {first_line}, {line}")
            replays.append(f"batches!A{line}:G{line} repeats batches!A{first_line}:G{first_line}")
        else:
            batches[key] = (line, row)

    readings = set()
    meter_by_batch = defaultdict(list)
    for line, row in meter_records:
        reading_id = row["reading_id"]
        if reading_id in readings:
            raise ValueError(f"duplicate meter reading {reading_id} on row {line}")
        readings.add(reading_id)
        meter_by_batch[row["batch_id"]].append((line, Fraction(str(row["steam_kg"]))))

    dates = sorted({row["start_at"].date().isoformat() for _, row in batches.values()})
    day_numbers = {day: number for number, day in enumerate(dates, start=1)}
    groups_by_day = defaultdict(dict)
    pairs = {}
    for key, (line, row) in batches.items():
        if key not in meter_by_batch:
            continue
        meters = meter_by_batch[key]
        pairs[key] = [line, [meter_line for meter_line, _ in meters]]
        day = row["start_at"].date().isoformat()
        group = "shutdown" if row["status"] == "shutdown" else row["product"]
        ref = f"day{day_numbers[day]}_{group}"
        steam = sum(amount for _, amount in meters)
        production = Fraction(str(row["production"]))
        tonnes = production / {"kg": 1000, "t": 1}[row["production_unit"]]
        groups_by_day[day].setdefault(ref, {})[key] = (steam, tonnes)

    group_members = {
        ref: list(group)
        for groups in groups_by_day.values()
        for ref, group in groups.items()
    }
    plant = []
    means = []
    differences = []
    h_shares = []
    product_rates = {product: [] for product in ("L", "H")}
    for day in dates:
        groups = groups_by_day[day]
        prefix = f"day{day_numbers[day]}"
        refs = list(groups)
        # Report the shutdown group last, after the production groups.
        refs.sort(key=lambda ref: ref.endswith("_shutdown"))
        totals = [pair for group in groups.values() for pair in group.values()]
        steam = sum(amount for amount, _ in totals)
        tonnes = sum(production for _, production in totals)
        batch_rates = [amount / production for amount, production in totals if production > 0]
        defined_refs = [
            ref for ref in refs if any(production > 0 for _, production in groups[ref].values())
        ]
        plant.append({
            "name": "plant_rate", "date": day, "numerator_kg": steam,
            "denominator_t": tonnes, "value": steam / tonnes, "source_refs": refs,
        })
        means.append({
            "name": "mean_defined_batch_rate", "date": day,
            "numerator_sum_of_rates": sum(batch_rates), "denominator_batches": len(batch_rates),
            "value": sum(batch_rates) / len(batch_rates), "source_refs": defined_refs,
        })
        differences.append(means[-1]["value"] - plant[-1]["value"])
        for product, rates in product_rates.items():
            ref = f"{prefix}_{product}"
            product_steam = sum(amount for amount, _ in groups[ref].values())
            product_tonnes = sum(production for _, production in groups[ref].values())
            rates.append((product_steam, product_tonnes, ref))
        h_shares.append(product_rates["H"][-1][1])

    plant_refs = [ref for day in plant for ref in day["source_refs"]]
    mean_refs = [ref for day in means for ref in day["source_refs"]]
    plant_tonnes = [day["denominator_t"] for day in plant]
    metrics = [*plant, *means, {
        "name": "mean_batch_minus_plant", "unit": RATE_UNIT, "values": differences,
        "source_refs": plant_refs,
    }]
    for product, rates in product_rates.items():
        metrics.append({
            "name": f"{product}_rate", "numerators_kg": [steam for steam, _, _ in rates],
            "denominators_t": [tonnes for _, tonnes, _ in rates],
            "values": [steam / tonnes for steam, tonnes, _ in rates],
            "source_refs": [ref for _, _, ref in rates],
        })
    metrics.append({
        "name": "H_share_of_production", "unit": "fraction of tonnes",
        "numerators_t": h_shares, "denominators_t": plant_tonnes,
        "values": [share / tonnes for share, tonnes in zip(h_shares, plant_tonnes)],
        "source_refs": plant_refs,
    })

    steam_total = sum(day["numerator_kg"] for day in plant)
    rate_sum = sum(day["numerator_sum_of_rates"] for day in means)
    batch_count = sum(day["denominator_batches"] for day in means)
    row_counts = {
        "batch_records": len(batch_records),
        "distinct_batches": len(batches),
        "meter_records": len(meter_records),
        "distinct_readings": len(readings),
        "batch_level_meter_totals": len(meter_by_batch),
        "joined_batches": len(pairs),
        "unmatched_on_either_side": len(batches.keys() ^ meter_by_batch.keys()),
        "joined_by_day": [sum(map(len, groups_by_day[day].values())) for day in dates],
        "defined_batch_rates_by_day": [day["denominator_batches"] for day in means],
    }
    return {
        "dates_in_order": dates,
        "rate_unit": RATE_UNIT,
        "references": {"pairs": pairs, "group_members": group_members, "replay": "; ".join(replays)},
    }, {
        "B": {
            "row_counts": row_counts,
            "metrics": metrics,
            "optional_metrics": [
                {
                    "name": "both_days_plant_rate", "unit": RATE_UNIT, "numerator_kg": steam_total,
                    "denominator_t": sum(plant_tonnes), "value": steam_total / sum(plant_tonnes),
                    "source_refs": plant_refs,
                },
                {
                    "name": "both_days_mean_defined_batch_rate", "unit": RATE_UNIT,
                    "numerator_sum_of_rates": rate_sum, "denominator_batches": batch_count,
                    "value": rate_sum / batch_count, "source_refs": mean_refs,
                },
            ],
        },
    }


def production_next_month(path):
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = workbook.active
        sheet_name = sheet.title
        rows = list(sheet.iter_rows(values_only=True))
    finally:
        workbook.close()

    def production_kg(value):
        amount, unit = value.split()
        return Fraction(amount.replace(",", "")) * {"kg": 1, "t": 1000}[unit]

    def cell_range(column, start, end_column, end):
        return f"{sheet_name}!{column}{start}:{end_column}{end}"

    title_month = re.search(r"(\d{4})년\s+(\d{1,2})월", rows[0][0])
    if title_month is None:
        raise ValueError("production report title is missing a year and month")
    year, month = map(int, title_month.groups())
    report_month = f"{year:04d}-{month:02d}"

    column_names = ("date", "A_production", "A_hours", "B_production", "B_hours", "note")
    columns = {name: get_column_letter(index) for index, name in enumerate(column_names, 1)}
    lines = ("A", "B")
    daily_rows = []
    weekly_rows = []
    monthly_rows = []
    maintenance = []
    breakdowns = []
    discrepancies = []
    production = dict.fromkeys(lines, 0)
    weekly_production = dict.fromkeys(lines, 0)
    actual_hours = dict.fromkeys(lines, 0)
    defined_days = dict.fromkeys(lines, 0)
    planned_days = dict.fromkeys(lines, 0)
    exceptions = {line: [] for line in lines}
    week_start = None

    for row, (label, a_production, a_hours, b_production, b_hours, note) in enumerate(rows, 1):
        line_values = (("A", a_production, a_hours), ("B", b_production, b_hours))
        day = re.fullmatch(r"(\d{1,2})월\s+(\d{1,2})일(?:\([^()]+\))?", str(label))
        if day is not None:
            day_month, day_number = map(int, day.groups())
            if datetime(year, day_month, day_number).month != month:
                raise ValueError(f"date outside the report month on row {row}")
            daily_rows.append(row)
            if week_start is None:
                week_start = row
            for line, amount, hours in line_values:
                production_column = columns[f"{line}_production"]
                hours_column = columns[f"{line}_hours"]
                if (amount, hours) == ("-", "-"):
                    maintenance.extend([
                        cell_range(production_column, row, hours_column, row),
                        f"{sheet_name}!{columns['note']}{row}",
                    ])
                    exceptions[line].append("maintenance")
                else:
                    kilograms = production_kg(amount)
                    hours = Fraction(str(hours))
                    if kilograms == hours == 0 and f"{line}라인 설비 고장" in (note or ""):
                        breakdowns.append(cell_range(production_column, row, columns["note"], row))
                        exceptions[line].append("breakdown")
                        continue
                    production[line] += kilograms
                    weekly_production[line] += kilograms
                    actual_hours[line] += hours
                    defined_days[line] += 1
                planned_days[line] += 1
        elif label == "주간 소계":
            weekly_rows.append(row)
            if week_start is None:
                raise ValueError(f"weekly subtotal without date rows on row {row}")
            for line, amount, _ in line_values:
                recorded_kg = production_kg(amount)
                daily_sum_kg = weekly_production[line]
                if recorded_kg != daily_sum_kg:
                    column = columns[f"{line}_production"]
                    discrepancies.append({
                        "subtotal": f"{sheet_name}!{column}{row}",
                        "daily": cell_range(column, week_start, column, daily_rows[-1]),
                        "recorded_kg": recorded_kg,
                        "daily_sum_kg": daily_sum_kg,
                        "recorded_minus_daily_kg": recorded_kg - daily_sum_kg,
                    })
                weekly_production[line] = 0
            week_start = None
        elif label == "월 합계":
            monthly_rows.append(cell_range(columns["date"], row, columns["B_hours"], row))

    metrics = []
    for line in lines:
        line_exceptions = list(dict.fromkeys(exceptions[line]))
        planned_hours = planned_days[line] * 20
        metrics.extend([
            {
                "name": "production", "month": report_month, "line": line, "unit": "kg",
                "value": production[line],
                "source_refs": ["daily_rows", f"{line}_production", *line_exceptions],
            },
            {
                "name": "utilization", "month": report_month, "line": line, "unit": "%",
                "numerator_hours": actual_hours[line], "denominator_hours": planned_hours,
                "value": Fraction(actual_hours[line] * 100, planned_hours),
                "source_refs": ["daily_rows", "date", f"{line}_hours", *line_exceptions],
            },
        ])

    row_counts = {
        "sheet_rows": len(rows),
        "preamble_and_header_rows": daily_rows[0] - 1,
        "daily_rows": len(daily_rows),
        "weekly_subtotal_rows": len(weekly_rows),
        "monthly_total_rows": len(monthly_rows),
        "line_day_records": len(daily_rows) * len(lines),
        "defined_production_days": defined_days,
        "planned_days": planned_days,
    }
    return {
        "references": {
            "sheet": sheet_name,
            "prior_summary": "eda-work/delivery/eda_summary.json",
            "daily_rows": daily_rows,
            "columns_on_daily_rows": columns,
            "maintenance": maintenance,
            "breakdown": breakdowns[0] if len(breakdowns) == 1 else breakdowns,
            "weekly_rows": weekly_rows,
            "monthly_total": monthly_rows[0] if len(monthly_rows) == 1 else monthly_rows,
            "weekly_discrepancy": discrepancies[0] if len(discrepancies) == 1 else discrepancies,
        },
    }, {"B": {"metrics": metrics, "row_counts": row_counts}}


def compare(expected, actual, path, tolerance, errors):
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(expected.keys() - actual.keys()):
            errors.append(f"{path}.{key}: missing calculation (expected {expected[key]!r})")
        for key in sorted(actual.keys() - expected.keys()):
            errors.append(f"{path}.{key}: missing from expected.json (computed {actual[key]!r})")
        for key in sorted(expected.keys() & actual.keys()):
            compare(expected[key], actual[key], f"{path}.{key}", tolerance, errors)
        return
    if isinstance(expected, list) and isinstance(actual, list):
        if len(expected) != len(actual):
            errors.append(f"{path}: expected {len(expected)} entries, computed {len(actual)}")
        for index, (left, right) in enumerate(zip(expected, actual)):
            compare(left, right, f"{path}[{index}]", tolerance, errors)
        return
    if type(expected) in (int, Fraction) and type(actual) in (int, Fraction):
        # Apply tolerance only to rate results. Counts, operands and locations are exact.
        field = path.rsplit(".", 1)[-1].split("[", 1)[0]
        limit = tolerance if field in ("value", "values") else 0
        if abs(expected - actual) <= limit:
            return
    elif type(expected) is type(actual) and expected == actual:
        return
    errors.append(f"{path}: expected {expected!r}, computed {actual!r}")


def check_case(case, filename, calculate, errors):
    before = len(errors)
    folder = CASES / case
    expected = read_json(folder / "expected.json")
    tolerance = expected["absolute_tolerance"]
    facts, flows = calculate(folder / filename)
    compare(expected["case_id"], case, f"{case}.case_id", 0, errors)
    compare(expected["source"], filename, f"{case}.source", 0, errors)
    for key, actual in facts.items():
        target = expected.get(key)
        if key == "references" and isinstance(target, dict):
            target = {field: value for field, value in target.items() if field != "locator"}
        compare(target, actual, f"{case}.{key}", tolerance, errors)

    expected_flows = {
        flow: {
            key: value for key, value in spec.items()
            if key in ("metrics", "optional_metrics", "row_counts", "denominator_status")
        }
        for flow, spec in expected["flows"].items()
    }
    compare(expected_flows, flows, f"{case}.flows", tolerance, errors)
    if len(errors) == before:
        for flow, result in flows.items():
            required = len(result["metrics"])
            optional = len(result.get("optional_metrics", []))
            print(f"OK {case} flow {flow}: {required} required + {optional} optional metrics")


def main():
    cases = [
        ("throughput_hourly", "input.csv", throughput),
        ("orders_nested_json", "input.json", daily_orders),
        ("utility_batches_excel", "input.xlsx", utility_batches),
        ("production_next_month", "input.xlsx", production_next_month),
    ]
    errors = []
    for case, filename, calculate in cases:
        try:
            check_case(case, filename, calculate, errors)
        except (OSError, ValueError, KeyError, TypeError, AttributeError, ZeroDivisionError,
                StopIteration, csv.Error, BadZipFile, InvalidFileException) as error:
            errors.append(f"{case}: {error}")

    if errors:
        print(f"FAIL: {len(errors)} discrepancies")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"All metrics matched across {len(cases)} cases.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
