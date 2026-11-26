import json
from pathlib import Path
import subprocess
import sys

from openpyxl import load_workbook

from build_report import validate_summary


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "messy_production_report"
INSPECT = ROOT / "skills" / "ask-first-eda" / "scripts" / "inspect_data.py"


def run(script, *args, cwd):
    result = subprocess.run(
        [sys.executable, "-I", str(script), *args],
        cwd=cwd, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def generate(folder):
    path = folder / "daily_report.xlsx"
    run(EXAMPLE / "make_data.py", "--out", path, cwd=folder)
    return path


def cell_values(path):
    book = load_workbook(path, read_only=True)
    try:
        return [(sheet.title, list(sheet.values)) for sheet in book]
    finally:
        book.close()


def test_generated_report_matches_facts(tmp_path):
    path = generate(tmp_path)
    output = run(EXAMPLE / "check_facts.py", "--path", path, cwd=tmp_path)
    assert output.strip() == "Fact check passed."


def test_repeated_generation_has_identical_cells(tmp_path):
    first = generate(tmp_path)
    second_folder = tmp_path / "second"
    second_folder.mkdir()
    second = generate(second_folder)
    assert cell_values(first) == cell_values(second)


def test_inspect_reports_both_sheets_and_header_merges(tmp_path):
    path = generate(tmp_path)
    report = json.loads(run(INSPECT, path, cwd=tmp_path))
    assert [sheet["name"] for sheet in report["sheets"]] == ["3월", "4월"]
    for sheet in report["sheets"]:
        assert set(sheet["merged_ranges"]) == {"B4:C4", "D4:E4"}


def test_gallery_summary_structures_match_confirmed_headers_across_months():
    summary_path = ROOT / "docs" / "gallery" / "messy_production_report.summary.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    header_rows = [4, 5]
    book = load_workbook(EXAMPLE / "daily_report.xlsx")
    comparable_structures = []
    try:
        assert {dataset["id"] for dataset in summary["datasets"]} == set(book.sheetnames)
        for dataset in summary["datasets"]:
            sheet = book[dataset["id"]]
            merged_values = {}
            for merged in sheet.merged_cells.ranges:
                row = merged.min_row
                if row in header_rows and row == merged.max_row:
                    value = sheet.cell(row, merged.min_col).value
                    for column in range(merged.min_col, merged.max_col + 1):
                        merged_values[row, column] = value

            column_names = []
            for cells in sheet.iter_cols(min_row=header_rows[0], max_row=header_rows[-1]):
                values = [merged_values.get((cell.row, cell.column), cell.value) for cell in cells]
                column_names.append(" / ".join(str(value) for value in values if value not in (None, "")))

            assert "structure" in dataset, f"Missing structure for sheet {sheet.title!r}"
            structure = dataset["structure"]
            assert structure["sheet"] == sheet.title
            assert structure["header_rows"] == header_rows
            assert structure["column_names"] == column_names
            assert structure["record_path"] is None
            comparable_structures.append({key: value for key, value in structure.items() if key != "sheet"})
    finally:
        book.close()

    march_structure, april_structure = comparable_structures
    assert march_structure == april_structure
    validate_summary(summary)
