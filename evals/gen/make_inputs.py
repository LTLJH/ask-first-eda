"""Write the hand-set evaluation fixtures without using expected.json."""

import csv
from datetime import datetime
from io import BytesIO
import json
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from openpyxl import Workbook


CASES = Path(__file__).resolve().parents[1] / "cases"
FIXED_TIME = datetime(2026, 1, 1)
EXCEL_TIME_FORMAT = "yyyy-mm-dd hh:mm"


def verify_throughput(path):
    expected_rows = [
        ["hour_start", "line_status", "units_produced"],
        ["2026-03-02 08:00", "open", "20"],
        ["2026-03-02 09:00", "open", "0"],
        ["2026-03-02 10:00", "closed", "0"],
        ["2026-03-02 11:00", "open", "40"],
    ]
    with path.open(encoding="utf-8", newline="") as source:
        lines = source.readlines()
    if len(lines) != len(expected_rows) or list(csv.reader(lines)) != expected_rows:
        raise ValueError(f"{path}: CSV rows differ from gen_spec.md")


def write_orders(path):
    orders = [
        ("00123", "2026-01-01", [("S1", 2)]),
        ("a2", "2026-01-01", [("S2", 1), ("S3", 2), ("S4", 1)]),
        ("b1", "2026-01-02", [("S2", 2)]),
        ("b2", "2026-01-02", [("S3", 1)]),
        ("b3", "2026-01-02", [("S1", 3)]),
    ]
    records = [
        {"order_id": order_id, "order_date": day,
         "items": [{"sku": sku, "qty": quantity} for sku, quantity in items]}
        for order_id, day, items in orders
    ]
    path.write_bytes((json.dumps(records, indent=2, ensure_ascii=False) + "\n").encode("utf-8"))


def add_rows(sheet, groups, headers, records, timestamp_columns):
    for span, title in groups:
        sheet.merge_cells(span)
        sheet[span.split(":")[0]] = title
    sheet.append(headers)
    for row_number, record in enumerate(records, start=3):
        sheet.append(record)
        for column in timestamp_columns:
            cell = sheet.cell(row_number, column)
            cell.value = datetime.fromisoformat(f"2026-{cell.value}")
            cell.number_format = EXCEL_TIME_FORMAT


def write_workbook(path):
    workbook = Workbook()
    workbook.properties.created = FIXED_TIME
    workbook.properties.modified = FIXED_TIME
    batches = workbook.active
    batches.title = "batches"
    add_rows(
        batches,
        [("A1:B1", "Batch"), ("C1:D1", "Interval"), ("E1:G1", "Production")],
        ["batch_id", "product", "start_at", "end_at", "status", "production", "production_unit"],
        [
            ("B-0012", "L", "01-01 01:00", "01-01 03:00", "running", 2000, "kg"),
            ("B-0013", "L", "01-01 04:00", "01-01 05:00", "running", 1, "t"),
            ("B-0014", "H", "01-01 06:00", "01-01 07:00", "running", 500, "kg"),
            ("B-0015", "NONE", "01-01 16:00", "01-01 17:00", "shutdown", 0, "kg"),
            ("B-0016", "L", "01-01 23:00", "01-02 01:00", "running", 1, "t"),
            ("B-0017", "L", "01-02 02:00", "01-02 03:00", "running", 1000, "kg"),
            ("B-0018", "L", "01-02 04:00", "01-02 06:00", "running", 3, "t"),
            ("B-0019", "H", "01-02 07:00", "01-02 08:00", "running", 0.5, "t"),
            ("B-0020", "H", "01-02 09:00", "01-02 22:00", "running", 9500, "kg"),
            ("B-0019", "H", "01-02 07:00", "01-02 08:00", "running", 0.5, "t"),
        ],
        (3, 4),
    )
    add_rows(
        workbook.create_sheet("meter_readings"),
        [("A1:B1", "Identifiers"), ("C1:D1", "Meter")],
        ["reading_id", "batch_id", "reading_at", "steam_kg"],
        [
            ("R01", "B-0012", "01-01 02:00", 80),
            ("R02", "B-0012", "01-01 03:00", 120),
            ("R03", "B-0013", "01-01 05:00", 100),
            ("R04", "B-0014", "01-01 07:00", 200),
            ("R05", "B-0015", "01-01 17:00", 0),
            ("R06", "B-0016", "01-02 01:00", 0),
            ("R07", "B-0017", "01-02 03:00", 0),
            ("R08", "B-0018", "01-02 06:00", 300),
            ("R09", "B-0019", "01-02 08:00", 200),
            ("R10", "B-0020", "01-02 22:00", 3800),
        ],
        (3,),
    )

    raw = BytesIO()
    workbook.save(raw)
    with ZipFile(raw) as source, ZipFile(path, "w") as destination:
        for name in source.namelist():
            data = source.read(name)
            if name == "docProps/core.xml":
                # openpyxl sets the modified property to the current time on save.
                properties = ElementTree.fromstring(data)
                modified = properties.find("{http://purl.org/dc/terms/}modified")
                # Preserve the XML prefixes used in xsi:type attribute values.
                old_timestamp = modified.text.encode("ascii")
                fixed_timestamp = (FIXED_TIME.isoformat() + "Z").encode("ascii")
                data = data.replace(old_timestamp, fixed_timestamp)
            entry = ZipInfo(name, FIXED_TIME.timetuple()[:6])
            destination.writestr(entry, data, compress_type=ZIP_DEFLATED)


def main():
    verify_throughput(CASES / "throughput_hourly" / "input.csv")
    write_orders(CASES / "orders_nested_json" / "input.json")
    write_workbook(CASES / "utility_batches_excel" / "input.xlsx")


if __name__ == "__main__":
    main()
