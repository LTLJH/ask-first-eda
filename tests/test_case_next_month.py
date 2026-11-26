import json
import subprocess
import sys
from pathlib import Path

from openpyxl import load_workbook


ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "examples" / "messy_production_report"
CASE_INPUT = ROOT / "evals" / "cases" / "production_next_month" / "input.xlsx"
GALLERY_SUMMARY = ROOT / "docs" / "gallery" / "messy_production_report.summary.json"


def run_script(script, *args, cwd):
    result = subprocess.run(
        [sys.executable, "-I", script, *args],
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return result.stdout


def workbook_contents(path):
    book = load_workbook(path)
    try:
        return [
            (sheet.title, list(sheet.values), {str(merged) for merged in sheet.merged_cells.ranges})
            for sheet in book
        ]
    finally:
        book.close()


def test_default_generation_preserves_example(tmp_path):
    output = tmp_path / "daily_report.xlsx"
    run_script(EXAMPLE / "make_data.py", "--out", output, cwd=tmp_path)
    assert workbook_contents(output) == workbook_contents(EXAMPLE / "daily_report.xlsx")


def test_may_generation_reproduces_case_input(tmp_path):
    output = tmp_path / "input.xlsx"
    run_script(EXAMPLE / "make_data.py", "--months", "5", "--out", output, cwd=tmp_path)
    generated = workbook_contents(output)
    assert [name for name, _, _ in generated] == ["5월"]
    assert CASE_INPUT.is_file(), f"Missing case input: {CASE_INPUT}"
    assert generated == workbook_contents(CASE_INPUT)


def test_case_headers_match_gallery_structures():
    assert CASE_INPUT.is_file(), f"Missing case input: {CASE_INPUT}"
    summary = json.loads(GALLERY_SUMMARY.read_text(encoding="utf-8"))
    header_rows = [4, 5]
    book = load_workbook(CASE_INPUT)
    try:
        sheet = book["5월"]
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
    finally:
        book.close()

    assert summary["datasets"]
    for dataset in summary["datasets"]:
        structure = dataset["structure"]
        assert structure["header_rows"] == header_rows
        assert structure["column_names"] == column_names


def test_expected_metrics_check_includes_next_month():
    output = run_script(ROOT / "evals" / "gen" / "check_expected.py", cwd=ROOT)
    assert "production_next_month" in output, output
