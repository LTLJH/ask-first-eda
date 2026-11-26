"""Generate the 2025 daily production reports defined in the spec."""

import argparse
from calendar import monthrange
from datetime import date
from pathlib import Path

from openpyxl import Workbook


YEAR = 2025
WEEKDAYS = "월화수목금"
DAILY_VALUES = {
    3: (
        ("12,340 kg", 18, "10,200 kg", 16),
        ("12.3 t", 19, "10,500 kg", 17),
        ("11,860 kg", 18, "10,800 kg", 18),
        ("12,600 kg", 20, "10.9 t", 18),
        ("12,400 kg", 19, "10,600 kg", 17),
    ),
    4: (
        ("12,640 kg", 18, "10,400 kg", 16),
        ("12.6 t", 19, "10,700 kg", 17),
        ("12,160 kg", 18, "11,000 kg", 18),
        ("12,900 kg", 20, "11.1 t", 18),
        ("12,700 kg", 19, "10,800 kg", 17),
    ),
    5: (
        ("12,480 kg", 18, "10,650 kg", 17),
        ("12.7 t", 19, "10,850 kg", 18),
        ("12,350 kg", 18, "11,050 kg", 18),
        ("12,950 kg", 20, "11.2 t", 19),
        ("12,800 kg", 19, "10,950 kg", 17),
    ),
}
MAINTENANCE = {
    (3, 12): ("11,860 kg", 18, "-", "-", "B라인 정기 보전"),
    (4, 8): ("-", "-", "10,700 kg", 17, "A라인 정기 보전"),
    (5, 13): ("-", "-", "10,850 kg", 18, "A라인 정기 보전"),
    (5, 21): ("12,350 kg", 18, "0 kg", 0, "B라인 설비 고장"),
}
WEEKLY_SUBTOTALS = {
    3: {
        7: ("61,500 kg", 94, "53,000 kg", 86),
        # Overstated by 1,000 kg as specified.
        14: ("62,500 kg", 94, "42,200 kg", 68),
        21: ("61,500 kg", 94, "53,000 kg", 86),
        28: ("61,500 kg", 94, "53,000 kg", 86),
    },
    4: {
        4: ("50,360 kg", 76, "43,600 kg", 70),
        11: ("50,400 kg", 75, "54,000 kg", 86),
        18: ("63,000 kg", 94, "54,000 kg", 86),
        25: ("63,000 kg", 94, "54,000 kg", 86),
    },
    5: {
        2: ("25,750 kg", 39, "22,150 kg", 36),
        # Overstated by 600 kg as specified.
        9: ("63,880 kg", 94, "54,700 kg", 89),
        16: ("50,580 kg", 75, "54,700 kg", 89),
        23: ("63,280 kg", 94, "43,650 kg", 71),
        30: ("63,280 kg", 94, "54,700 kg", 89),
    },
}
MONTHLY_TOTALS = {
    3: ("258,340 kg", 394, "211,400 kg", 342),
    4: ("264,160 kg", 394, "237,700 kg", 379),
    5: ("266,170 kg", 396, "229,900 kg", 374),
}


def write_month(sheet, month):
    sheet.title = f"{month}월"
    sheet.append((f"○○공장 생산 일보 ({YEAR}년 {month}월)",))
    sheet.append(("결재 담당 / 검토 / 승인",))
    sheet.append(())
    sheet.append(("일자", "A라인", None, "B라인", None, "비고"))
    sheet.append((None, "생산량", "가동시간", "생산량", "가동시간"))
    sheet.merge_cells("B4:C4")
    sheet.merge_cells("D4:E4")

    for day in range(1, monthrange(YEAR, month)[1] + 1):
        weekday = date(YEAR, month, day).weekday()
        if weekday >= len(WEEKDAYS):
            continue
        values = MAINTENANCE.get((month, day), DAILY_VALUES[month][weekday])
        sheet.append((f"{month}월 {day}일({WEEKDAYS[weekday]})", *values))
        if day in WEEKLY_SUBTOTALS[month]:
            sheet.append(("주간 소계", *WEEKLY_SUBTOTALS[month][day]))

    sheet.append(("월 합계", *MONTHLY_TOTALS[month]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_name("daily_report.xlsx"))
    parser.add_argument("--months", default="3,4", help="Comma-separated list of months (3, 4, 5)")
    args = parser.parse_args()

    try:
        months = [int(month) for month in args.months.split(",")]
    except ValueError:
        parser.error("--months requires comma-separated month numbers.")
    if any(month not in DAILY_VALUES for month in months):
        parser.error("--months supports only 3, 4, and 5.")

    book = Workbook()
    write_month(book.active, months[0])
    for month in months[1:]:
        write_month(book.create_sheet(), month)
    book.save(args.out)


if __name__ == "__main__":
    main()
