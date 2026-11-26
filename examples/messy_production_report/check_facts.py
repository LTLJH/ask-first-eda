"""Check actuals computed from dated rows against recorded subtotals and monthly totals."""

import argparse
import calendar
from contextlib import closing
from datetime import date
from decimal import Decimal
import difflib
import json
from pathlib import Path
import re
import sys
from zipfile import BadZipFile

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException


HERE = Path(__file__).resolve().parent
LINES = ("A라인", "B라인")
PLAN_HOURS = 20


def read_pair(amount, hours, location, *, daily):
    if daily and (amount, hours) == ("-", "-"):
        return None, 0
    match = re.fullmatch(r"(\d{1,3}(?:,\d{3})*|\d+)(\.\d+)? (kg|t)", str(amount))
    if not match or (not daily and match[3] != "kg"):
        raise ValueError(f"{location} invalid production quantity: {amount!r}")
    kg = Decimal(match[1].replace(",", "") + (match[2] or ""))
    if match[3] == "t":
        kg *= 1000
    if kg != int(kg):
        raise ValueError(f"{location} cannot convert to a whole number of kilograms: {amount!r}")
    if type(hours) not in (float, int) or hours < 0:
        raise ValueError(f"{location} invalid operating hours: {hours!r}")
    return int(kg), hours


def totals(records):
    return (sum(kg for kg, _ in records if kg is not None),
            sum(hours for _, hours in records))


def sheet_facts(sheet, mismatches):
    name = sheet.title
    month = {"3월": 3, "4월": 4}[name]
    dates = []
    for day in range(1, calendar.monthrange(2025, month)[1] + 1):
        weekday = date(2025, month, day).weekday()
        if weekday < 5:
            dates.append(f"{name} {day}일({'월화수목금'[weekday]})")

    records = {line: [] for line in LINES}
    observed_dates = []
    subtotal_rows = []
    week_start = 0
    monthly_rows = []
    for row, (label, a, ah, b, bh) in enumerate(
        sheet.iter_rows(min_row=6, max_col=5, values_only=True), start=6
    ):
        daily = label not in ("주간 소계", "월 합계")
        for line, column, amount, hours in zip(LINES, "BD", (a, b), (ah, bh)):
            cell = f"{column}{row}"
            location = f"{name}!{cell}"
            pair = read_pair(amount, hours, location, daily=daily)
            if daily:
                records[line].append(pair)
                continue
            period = records[line][week_start:] if label == "주간 소계" else records[line]
            kg, runtime = totals(period)
            if pair[1] != runtime or (label == "월 합계" and pair[0] != kg):
                raise ValueError(f"{location} {label} lists {pair}, but dated rows sum to {(kg, runtime)}")
            if pair[0] != kg:
                mismatches.append({
                    "sheet": name, "row": row, "cell": cell, "line": line,
                    "actual_kg": kg, "reported_kg": pair[0], "difference_kg": pair[0] - kg,
                })
        if daily:
            observed_dates.append(label)
        elif label == "주간 소계":
            subtotal_rows.append(row)
            week_start = len(observed_dates)
        else:
            monthly_rows.append(row)

    if observed_dates != dates:
        raise ValueError(f"{name} dated rows do not match the month's weekdays")
    if monthly_rows != [sheet.max_row]:
        raise ValueError(f"{name} requires one monthly total on the last row")

    lines = {}
    for line, pairs in records.items():
        kg, runtime = totals(pairs)
        planned = PLAN_HOURS * len(pairs)
        lines[line] = {"production_kg": kg, "operating_hours": runtime,
                       "planned_hours": planned, "utilization": round(runtime / planned, 8)}
    return {
        "date_rows": len(observed_dates),
        "long_rows": sum(map(len, records.values())),
        "inactive_line_days": sum(kg is None for pairs in records.values() for kg, _ in pairs),
        "subtotal_rows": subtotal_rows,
        "lines": lines,
    }


def calculate(book):
    if book.sheetnames != ["3월", "4월"]:
        raise ValueError(f"Unexpected sheets: {book.sheetnames}")
    mismatches = []
    sheets = {sheet.title: sheet_facts(sheet, mismatches) for sheet in book}
    return {
        "sheets": sheets,
        "long_rows": sum(sheet["long_rows"] for sheet in sheets.values()),
        "inactive_line_days": sum(sheet["inactive_line_days"] for sheet in sheets.values()),
        "subtotal_mismatches": mismatches,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", type=Path, default=HERE / "daily_report.xlsx")
    args = parser.parse_args()
    try:
        expected = json.loads((HERE / "expected_facts.json").read_text(encoding="utf-8"))
        with closing(load_workbook(args.path, read_only=True)) as book:
            actual = calculate(book)
    except (OSError, ValueError, InvalidFileException, BadZipFile) as error:
        parser.exit(1, f"{error}\n")
    if actual != expected:
        def pretty(facts):
            return json.dumps(facts, indent=2, ensure_ascii=False, sort_keys=True).splitlines(True)

        sys.stderr.writelines(difflib.unified_diff(
            pretty(expected), pretty(actual), fromfile="expected_facts.json", tofile=str(args.path),
        ))
        return 1
    print("Fact check passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
