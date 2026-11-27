import csv
from decimal import Decimal
import json
from pathlib import Path
import re
import subprocess
import sys

from openpyxl import Workbook
import pytest

import audit_clean
from audit_clean import audit


SCRIPT = Path(__file__).resolve().parents[1] / "skills" / "ask-first-eda" / "scripts" / "audit_clean.py"


def write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def write_excluded(path, rows=()):
    return write_csv(path, ("_source_sheet", "_source_row", "reason"), rows)


def run_audit_cli(source, cleaned, excluded, *selection):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(SCRIPT), str(source), "--cleaned", str(cleaned),
         "--excluded", str(excluded), *selection],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )


@pytest.fixture
def csv_files(tmp_path):
    # The first data record spans lines 2 and 3, so later records start at 4 and 5.
    source = write_csv(
        tmp_path / "source.csv", ("item", "quantity"),
        [("paper\nrecycled", 8), ("pencil", 3), ("folder", 5)],
    )
    return source, tmp_path / "cleaned.csv", write_excluded(tmp_path / "excluded.csv")


def test_all_source_rows_are_in_cleaned_csv(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "quantity"), [(2, 8), (4, 3), (5, 5)])

    assert audit(source, cleaned, excluded) == {
        "status": "pass", "unexplained": [], "errors": [],
    }


def test_cli_fails_on_formula_cells_and_reports_cleaned_csv_lines(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(
        cleaned, ("_source_row", "memo", "quantity"),
        [(2, "paper\nrecycled", -5), (4, "=1", "@SUM(1)"), (5, "\r=1", "+3.2")],
    )

    completed = run_audit_cli(source, cleaned, excluded)

    assert completed.returncode == 1, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == {
        "status": "fail", "unexplained": [], "errors": [],
        "formula_cells": [
            {"row": 4, "column": "memo"}, {"row": 4, "column": "quantity"},
            {"row": 5, "column": "memo"},
        ],
    }


def test_audit_accepts_neutralized_and_numeric_cells_and_ignores_excluded_text(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "memo", "quantity"), [(2, "'=1", -5), (5, "'@SUM(1)'", "+3.2")])
    write_excluded(excluded, [("", 4, "=1")])

    assert audit(source, cleaned, excluded) == {
        "status": "pass", "unexplained": [], "errors": [],
    }


def test_audit_checks_formula_cells_in_cleaned_csv_headers(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "=1"), [(2, 8), (4, 3), (5, 5)])

    assert audit(source, cleaned, excluded) == {
        "status": "fail", "unexplained": [], "errors": [],
        "formula_cells": [{"row": 1, "column": "=1"}],
    }


def test_missing_source_row_is_reported(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "quantity"), [(2, 8), (5, 5)])

    result = audit(source, cleaned, excluded)

    assert result["status"] == "fail"
    assert result["unexplained"] == [{"sheet": "", "row": 4}]


@pytest.mark.parametrize("kept_row", [(6, "note"), (2, "good")], ids=["markdown-row", "valid-row"])
def test_audit_fails_on_unread_csv_source_rows(tmp_path, kept_row):
    source = tmp_path / "damaged.csv"
    source.write_text('id,memo\n1,good\n2,"break\n| id | memo |\n| --- | --- |\n| 3 | note |\n',
                      encoding="utf-8")
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "memo"), [kept_row])
    excluded = write_excluded(tmp_path / "excluded.csv")

    result = audit(source, cleaned, excluded)

    assert result["status"] == "fail"
    assert any("Malformed delimited record" in error for error in result["errors"])


def test_excluded_row_with_reason_counts_as_explained(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "quantity"), [(2, 8), (5, 5)])
    write_excluded(excluded, [("", 4, "Outside the reporting scope")])

    assert audit(source, cleaned, excluded) == {
        "status": "pass", "unexplained": [], "errors": [],
    }


def test_cleaned_csv_requires_source_row_column(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("quantity",), [(8,), (3,), (5,)])

    result = audit(source, cleaned, excluded)

    assert result["status"] == "fail"
    assert any("_source_row" in error for error in result["errors"])


def test_excluded_row_requires_reason(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "quantity"), [(2, 8), (5, 5)])
    write_excluded(excluded, [("", 4, "")])

    assert audit(source, cleaned, excluded)["status"] == "fail"


@pytest.fixture
def repeated_csv_rows(tmp_path):
    source = write_csv(tmp_path / "source.csv", ("value",), [(8,), (3,)])
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "value"), [(2, 800), (2, 800), (3, 3)])
    return source, cleaned, write_excluded(tmp_path / "excluded.csv")


def test_duplicate_cleaned_source_row_fails_by_default(repeated_csv_rows):
    completed = run_audit_cli(*repeated_csv_rows)

    assert completed.returncode == 1, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "fail"
    assert result["unexplained"] == []
    assert any(re.search(r"duplicate.*row 2.*2 times", error, re.I) for error in result["errors"])


def test_expand_allows_duplicates_without_a_value_check(repeated_csv_rows):
    completed = run_audit_cli(*repeated_csv_rows, "--expand")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == {"status": "pass", "unexplained": [], "errors": []}


def test_expand_still_checks_each_passthrough_value(repeated_csv_rows):
    completed = run_audit_cli(*repeated_csv_rows, "--expand", "--passthrough", "value=value")

    assert completed.returncode == 1, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "fail"
    assert result["unexplained"] == []
    assert len(result["errors"]) == 2
    assert all(re.search(r"row 2.*\bvalue\b.*\b8\b.*\b800\b", error) for error in result["errors"])


def test_wide_to_long_preserves_passthrough_values(tmp_path):
    source = write_csv(
        tmp_path / "source.csv", ("item", "morning", "afternoon", "total"),
        [("paper", 3, 5, 8), ("pencil", 1, 2, 3), ("folder", 4, 1, 5)],
    )
    cleaned = write_csv(
        tmp_path / "cleaned.csv", ("_source_row", "period", "quantity", "total"),
        [(2, "morning", 3, 8), (2, "afternoon", 5, 8),
         (3, "morning", 1, 3), (3, "afternoon", 2, 3),
         (4, "morning", 4, 5), (4, "afternoon", 1, 5)],
    )
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--expand", "--passthrough", "total=total")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == {"status": "pass", "unexplained": [], "errors": []}


def test_passthrough_compares_numbers_and_trimmed_text_by_source_address(tmp_path):
    source = write_csv(tmp_path / "source.csv", ("value", "label"), [(8, " note "), ("1,200", " ")])
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "amount", "label"),
                        [(3, "1200", ""), (2, " 8.0 ", "note")])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--passthrough", "amount=value",
                              "--passthrough", "label=label")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == {"status": "pass", "unexplained": [], "errors": []}


@pytest.mark.parametrize("mapping, side", [("missing=value", "cleaned"), ("value=missing", "source")])
def test_passthrough_rejects_unknown_columns(repeated_csv_rows, mapping, side):
    completed = run_audit_cli(*repeated_csv_rows, "--expand", "--passthrough", mapping)

    assert completed.returncode == 1, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "fail"
    assert any(side in error.lower() and "'missing'" in error for error in result["errors"])


def test_passthrough_requires_an_equals_separator(repeated_csv_rows):
    completed = run_audit_cli(*repeated_csv_rows, "--passthrough", "value")

    assert completed.returncode == 2
    assert "--passthrough" in completed.stderr
    assert "CLEANED_COL=SOURCE_COL" in completed.stderr


def test_passthrough_limits_details_and_counts_all_mismatches(tmp_path):
    source = write_csv(tmp_path / "source.csv", ("value",), [("9007199254740992",)] * 22)
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "amount"),
                        [(row, "9007199254740993") for row in range(2, 24)])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--passthrough", "amount=value")

    assert completed.returncode == 1, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    details = [error for error in result["errors"] if "9007199254740993" in error]
    assert result["status"] == "fail"
    assert len(details) == 20
    assert [int(re.search(r"\brow (\d+)\b", error)[1]) for error in details] == list(range(2, 22))
    assert any(re.search(r"\b22\b.*mismatch", error, re.I) for error in result["errors"])


def test_excel_addresses_include_the_sheet_for_passthrough_and_duplicates(tmp_path):
    source = tmp_path / "source.xlsx"
    workbook = Workbook()
    workbook.active.title = "First"
    workbook.create_sheet("Second")
    for name, value in [("First", 8), ("Second", 3)]:
        workbook[name].append(["value"])
        workbook[name].append([value])
    workbook.save(source)
    workbook.close()
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "value"),
                        [("First", 2, 8), ("Second", 2, 3)])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--header-row", "1", "--passthrough", "value=value")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == {"status": "pass", "unexplained": [], "errors": []}


@pytest.mark.parametrize("excluded_rows, status, unexplained", [
    ([("4월", 5, "Outside the reporting scope")], "pass", []),
    ([], "fail", [{"sheet": "4월", "row": 5}]),
], ids=["both-sheets-explained", "april-row-missing"])
def test_excel_audits_each_referenced_sheet_below_header(
    tmp_path, excluded_rows, status, unexplained,
):
    source = tmp_path / "source.xlsx"
    workbook = Workbook()
    march = workbook.active
    march.title = "3월"
    april = workbook.create_sheet("4월")
    for sheet in (march, april):
        sheet.append(["월별 집계"])
        sheet.append(["문구 재고"])
        sheet.append(["품목", "수량"])
        sheet.append(["종이", 8])
        sheet.append(["연필", 3])
    workbook.save(source)
    workbook.close()

    cleaned = write_csv(
        tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "수량"),
        [("3월", 4, 8), ("3월", 5, 3), ("4월", 4, 8)],
    )
    excluded = write_excluded(tmp_path / "excluded.csv", excluded_rows)

    result = audit(source, cleaned, excluded, header_row=3)

    assert result["status"] == status
    assert result["unexplained"] == unexplained


def test_cleaned_csv_rejects_row_outside_source_range(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "quantity"), [(2, 8), (4, 3), (5, 5), (6, 9)])

    assert audit(source, cleaned, excluded)["status"] == "fail"


@pytest.mark.parametrize("cleaned_rows, exit_code, status, unexplained", [
    ([(2, 8), (5, 5)], 1, "fail", [{"sheet": "", "row": 4}]),
    ([(2, 8), (4, 3), (5, 5)], 0, "pass", []),
], ids=["fail", "pass"])
def test_cli_reports_json_and_exit_code(csv_files, cleaned_rows, exit_code, status, unexplained):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "quantity"), cleaned_rows)

    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--cleaned", str(cleaned),
         "--excluded", str(excluded)],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )

    assert completed.returncode == exit_code, completed.stderr
    result = json.loads(completed.stdout)
    assert result["status"] == status
    assert result["unexplained"] == unexplained


@pytest.fixture
def excel_files_with_only_sheet_a_cleaned(tmp_path):
    source = tmp_path / "source.xlsx"
    workbook = Workbook()
    sheet_a = workbook.active
    sheet_a.title = "A"
    sheet_b = workbook.create_sheet("B")
    for sheet in (sheet_a, sheet_b):
        sheet.append(["Monthly totals"])
        sheet.append(["Stationery inventory"])
        sheet.append(["item", "quantity"])
        sheet.append(["paper", 8])
        sheet.append(["pencil", 3])
    workbook.save(source)
    workbook.close()

    cleaned = write_csv(
        tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "quantity"),
        [("A", 4, 8), ("A", 5, 3)],
    )
    excluded = write_excluded(tmp_path / "excluded.csv")
    return source, cleaned, excluded


@pytest.mark.parametrize("sheet_scope", [{}, {"sheets": ["A", "B"]}],
                         ids=["default-all-sheets", "explicit-both-sheets"])
def test_excel_reports_all_rows_from_an_unreferenced_sheet(
    excel_files_with_only_sheet_a_cleaned, sheet_scope,
):
    source, cleaned, excluded = excel_files_with_only_sheet_a_cleaned
    result = audit(source, cleaned, excluded, header_row=3, **sheet_scope)

    assert result["status"] == "fail"
    assert result["unexplained"] == [{"sheet": "B", "row": 4}, {"sheet": "B", "row": 5}]


def test_excel_audits_only_selected_sheets(excel_files_with_only_sheet_a_cleaned):
    source, cleaned, excluded = excel_files_with_only_sheet_a_cleaned

    assert audit(source, cleaned, excluded, header_row=3, sheets=["A"]) == {
        "status": "pass", "unexplained": [], "errors": [],
    }


def test_excel_rejects_a_selected_sheet_missing_from_the_workbook(
    excel_files_with_only_sheet_a_cleaned,
):
    source, cleaned, excluded = excel_files_with_only_sheet_a_cleaned
    result = audit(source, cleaned, excluded, header_row=3, sheets=["A", "없는시트"])

    assert result["status"] == "fail"
    assert any("없는시트" in error for error in result["errors"])


@pytest.mark.parametrize("reference_file", ["cleaned", "excluded"])
def test_excel_rejects_references_outside_selected_sheets(
    excel_files_with_only_sheet_a_cleaned, reference_file,
):
    source, cleaned, excluded = excel_files_with_only_sheet_a_cleaned
    if reference_file == "cleaned":
        with cleaned.open("a", encoding="utf-8", newline="") as stream:
            csv.writer(stream).writerow(("B", 4, 8))
    else:
        write_excluded(excluded, [("B", 4, "Outside the reporting scope")])

    result = audit(source, cleaned, excluded, header_row=3, sheets=["A"])

    assert result["status"] == "fail"
    assert any("outside" in error.lower() and "sheet" in error.lower() for error in result["errors"])


def test_csv_rejects_a_sheet_selection(csv_files):
    source, cleaned, excluded = csv_files
    write_csv(cleaned, ("_source_row", "quantity"), [(2, 8), (4, 3), (5, 5)])
    result = audit(source, cleaned, excluded, sheets=["A"])

    assert result["status"] == "fail"
    assert result["errors"]


@pytest.mark.parametrize("sheet_args, exit_code, status, unexplained", [
    ([], 1, "fail", [{"sheet": "B", "row": 4}, {"sheet": "B", "row": 5}]),
    (["--sheets", "A"], 0, "pass", []),
    (["--sheets", "A,B"], 1, "fail", [{"sheet": "B", "row": 4}, {"sheet": "B", "row": 5}]),
], ids=["default-all-sheets", "one-sheet", "comma-separated-sheets"])
def test_cli_reports_json_and_exit_code_for_sheet_scope(
    excel_files_with_only_sheet_a_cleaned, sheet_args, exit_code, status, unexplained,
):
    source, cleaned, excluded = excel_files_with_only_sheet_a_cleaned
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), str(source), "--cleaned", str(cleaned),
         "--excluded", str(excluded), "--header-row", "3", *sheet_args],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )

    assert completed.returncode == exit_code, completed.stderr
    assert json.loads(completed.stdout) == {
        "status": status, "unexplained": unexplained, "errors": [],
    }


def test_cli_help_lists_sheets_option():
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--help"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--sheets" in completed.stdout


def test_cli_help_lists_expansion_and_passthrough_options():
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(SCRIPT), "--help"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--expand" in completed.stdout
    assert "--passthrough" in completed.stdout


@pytest.mark.parametrize("first_record, cleaned_rows, exit_code, status, unexplained", [
    ("apple,3", [(2, "pear", 5)], 1, "fail", [{"sheet": "", "row": 1}]),
    ("apple,3", [(1, "apple", 3), (2, "pear", 5)], 0, "pass", []),
    ("item,quantity", [(2, "pear", 5)], 1, "fail", [{"sheet": "", "row": 1}]),
], ids=["first-row-missing", "both-rows-kept", "first-row-looks-like-header"])
def test_audit_counts_the_first_record_of_headerless_csv(
    tmp_path, first_record, cleaned_rows, exit_code, status, unexplained,
):
    source = tmp_path / "source.csv"
    source.write_text(f"{first_record}\npear,5\n", encoding="utf-8")
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "item", "quantity"), cleaned_rows)
    excluded = write_excluded(tmp_path / "excluded.csv")
    expected = {"status": status, "unexplained": unexplained, "errors": []}

    completed = run_audit_cli(source, cleaned, excluded, "--header", "no")

    assert completed.returncode == exit_code, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == expected
    assert audit(source, cleaned, excluded, header=False) == expected


@pytest.fixture
def ambiguous_header_files(tmp_path, request):
    source = tmp_path / f"source.{request.param}"
    rows = [("Longname", "Longcategory"), ("A", "X"), ("B", "Y")]
    sheet = "" if request.param == "csv" else "A"
    if sheet:
        workbook = Workbook()
        workbook.active.title = sheet
        for row in rows:
            workbook.active.append(row)
        workbook.save(source)
        workbook.close()
    else:
        write_csv(source, rows[0], rows[1:])
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "item"),
                        [(sheet, 2, "A"), (sheet, 3, "B")])
    return source, cleaned, write_excluded(tmp_path / "excluded.csv"), sheet


@pytest.mark.parametrize("ambiguous_header_files, selection", [
    ("csv", ()), ("xlsx", ()), ("xlsx", ("--sheet", "A")), ("xlsx", ("--sheets", "A")),
], indirect=["ambiguous_header_files"], ids=["csv", "workbook", "selected-sheet", "sheet-scope"])
def test_audit_requires_explicit_selection_for_an_uncertain_header(ambiguous_header_files, selection):
    source, cleaned, excluded, sheet = ambiguous_header_files
    option = "--header-row" if sheet else "--header"

    completed = run_audit_cli(source, cleaned, excluded, *selection)

    assert completed.returncode == 1, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "fail"
    assert any("header" in error.lower() and option in error for error in result["errors"])


@pytest.mark.parametrize("ambiguous_header_files", ["csv", "xlsx"], indirect=True)
def test_audit_counts_first_row_when_uncertain_header_is_declared_absent(ambiguous_header_files):
    source, cleaned, excluded, sheet = ambiguous_header_files
    selection = ("--header-row", "0") if sheet else ("--header", "no")

    completed = run_audit_cli(source, cleaned, excluded, *selection)

    assert completed.returncode == 1, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == {
        "status": "fail", "unexplained": [{"sheet": sheet, "row": 1}], "errors": [],
    }


@pytest.mark.parametrize("ambiguous_header_files", ["csv", "xlsx"], indirect=True)
def test_audit_accepts_an_explicitly_confirmed_header(ambiguous_header_files):
    source, cleaned, excluded, sheet = ambiguous_header_files
    selection = ("--header-row", "1") if sheet else ("--header", "yes")

    completed = run_audit_cli(source, cleaned, excluded, *selection)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == {"status": "pass", "unexplained": [], "errors": []}


@pytest.mark.parametrize("selector", [(), ("--sheet", "A")], ids=["workbook", "selected-sheet"])
@pytest.mark.parametrize("option, value", [("--header", "no"), ("--delimiter", ","),
                                          ("--encoding", "not-a-codec")])
@pytest.mark.parametrize("ambiguous_header_files", ["xlsx"], indirect=True)
def test_audit_rejects_text_options_for_excel(ambiguous_header_files, selector, option, value):
    source, cleaned, excluded, _ = ambiguous_header_files

    completed = run_audit_cli(source, cleaned, excluded, *selector, "--header-row", "1", option, value)

    assert completed.returncode == 1, completed.stderr or completed.stdout
    result = json.loads(completed.stdout)
    assert result["status"] == "fail"
    assert any(option in error for error in result["errors"])
    if option == "--header":
        assert any("--header " in error and "--header-row" in error for error in result["errors"])


@pytest.mark.parametrize("filename, delimiter", [
    ("source.csv", ";"), ("source.tsv", "\t"),
], ids=["semicolon-csv", "tsv"])
def test_audit_uses_multiline_record_start_rows(tmp_path, filename, delimiter):
    source = tmp_path / filename
    source.write_text(
        f'item{delimiter}quantity\n"two\nlines"{delimiter}3\nlast{delimiter}5\n',
        encoding="utf-8",
    )
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "quantity"), [(2, 3), (4, 5)])
    excluded = write_excluded(tmp_path / "excluded.csv")
    expected = {"status": "pass", "unexplained": [], "errors": []}

    completed = run_audit_cli(source, cleaned, excluded, "--delimiter", delimiter)

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == expected
    assert audit(source, cleaned, excluded, delimiter=delimiter, header=True) == expected

    wrong_delimiter = run_audit_cli(source, cleaned, excluded, "--delimiter", ",")
    assert wrong_delimiter.returncode == 1, wrong_delimiter.stderr or wrong_delimiter.stdout
    result = json.loads(wrong_delimiter.stdout)
    assert result["status"] == "fail"
    assert result["errors"]


@pytest.mark.parametrize("option, value", [("--sheet", "A"), ("--table-id", "sheet:A")])
def test_audit_selects_one_excel_table(excel_files_with_only_sheet_a_cleaned, option, value):
    source, cleaned, excluded = excel_files_with_only_sheet_a_cleaned
    expected = {"status": "pass", "unexplained": [], "errors": []}

    completed = run_audit_cli(source, cleaned, excluded, option, value, "--header-row", "3")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == expected
    selection = {option.removeprefix("--").replace("-", "_"): value}
    assert audit(source, cleaned, excluded, header_row=3, **selection) == expected


def test_audit_rejects_a_row_both_kept_and_excluded(tmp_path):
    source = write_csv(tmp_path / "source.csv", ("item", "quantity"), [("paper", 8), ("pencil", 3)])
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "quantity"), [(2, 8), (3, 3)])
    excluded = write_excluded(tmp_path / "excluded.csv", [("", 2, "out of scope")])

    result = audit(source, cleaned, excluded)

    assert result["status"] == "fail"
    assert result["unexplained"] == []
    assert any(re.search(r"\b2\b", error) for error in result["errors"])


@pytest.mark.parametrize("cleaned_rows, exit_code, status, unexplained", [
    ([("$[0]", 1), ("$[1]", 2)], 0, "pass", []),
    ([("$[0]", 1)], 1, "fail", [{"sheet": "", "row": "$[1]"}]),
], ids=["both-records-kept", "second-record-missing"])
def test_audit_uses_json_record_references(tmp_path, cleaned_rows, exit_code, status, unexplained):
    source = tmp_path / "source.json"
    source.write_text('[{"n":1},{"n":2}]', encoding="utf-8")
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "n"), cleaned_rows)
    excluded = write_excluded(tmp_path / "excluded.csv")
    expected = {"status": status, "unexplained": unexplained, "errors": []}

    completed = run_audit_cli(source, cleaned, excluded, "--json-record-path", "$")

    assert completed.returncode == exit_code, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == expected
    assert audit(source, cleaned, excluded, json_record_path="$") == expected


def test_audit_applies_explicit_source_encoding(tmp_path, monkeypatch):
    source = tmp_path / "source.csv"
    source.write_bytes("id,name\n1,똠\n".encode("cp949"))
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_row", "name"), [(2, "똠")])
    excluded = write_excluded(tmp_path / "excluded.csv")
    expected = {"status": "pass", "unexplained": [], "errors": []}
    decoded_sources = []
    load_table = audit_clean.load_table

    def record_loaded_names(path, **selection):
        table = load_table(path, **selection)
        if Path(path) == source:
            decoded_sources.append((selection.get("encoding"), table.frame["name"].tolist()))
        return table

    completed = run_audit_cli(source, cleaned, excluded, "--encoding", "cp949")

    assert completed.returncode == 0, completed.stderr or completed.stdout
    assert json.loads(completed.stdout) == expected

    wrong_encoding = run_audit_cli(source, cleaned, excluded, "--encoding", "utf-8")
    assert wrong_encoding.returncode == 1, wrong_encoding.stderr or wrong_encoding.stdout
    result = json.loads(wrong_encoding.stdout)
    assert result["status"] == "fail"
    assert result["errors"]

    # The audit output contains row addresses only. Observe the source values from the real loader.
    monkeypatch.setattr(audit_clean, "load_table", record_loaded_names)
    assert audit(source, cleaned, excluded, encoding="cp949") == expected
    assert ("cp949", ["똠"]) in decoded_sources


@pytest.fixture
def reconcile_csv_files(tmp_path):
    source = write_csv(tmp_path / "source.csv", ("value", "units"), [(8, 2), (3, 1)])
    return source, tmp_path / "cleaned.csv", write_excluded(tmp_path / "excluded.csv")


def reconcile_result(completed, status):
    assert completed.returncode == (0 if status == "pass" else 1), completed.stderr or completed.stdout
    result = json.loads(completed.stdout, parse_float=Decimal)
    assert result["status"] == status
    return result


def assert_reconcile_totals(group, *, source, kept, cleaned, excluded, difference):
    assert "group" in group
    assert Decimal(str(group["source_total"])) == source
    assert Decimal(str(group["kept_source_total"])) == kept
    assert Decimal(str(group["cleaned_total"])) == cleaned
    assert Decimal(str(group["excluded_total"])) == excluded
    assert abs(Decimal(str(group["difference"]))) == difference


def test_reconcile_passes_for_matching_totals_with_repeated_options(reconcile_csv_files):
    source, cleaned, excluded = reconcile_csv_files
    write_csv(cleaned, ("_source_sheet", "_source_row", "amount", "count"),
              [("", 3, 3, 1), ("", 2, 8, 2)])

    completed = run_audit_cli(source, cleaned, excluded, "--reconcile", "amount=value",
                              "--reconcile", "count=units")

    result = reconcile_result(completed, "pass")
    assert result["unexplained"] == []
    entries = result["reconcile"]
    assert len(entries) == 2
    by_mapping = {(entry["cleaned_col"], entry["source_col"]): entry for entry in entries}
    amount = by_mapping["amount", "value"]
    count = by_mapping["count", "units"]
    assert "group_col" in amount and "group_col" in count
    amount_group, = amount["groups"]
    count_group, = count["groups"]
    assert_reconcile_totals(amount_group, source=11, kept=11, cleaned=11, excluded=0, difference=0)
    assert_reconcile_totals(count_group, source=3, kept=3, cleaned=3, excluded=0, difference=0)


def test_reconcile_reports_difference_when_a_value_changes(reconcile_csv_files):
    source, cleaned, excluded = reconcile_csv_files
    write_csv(cleaned, ("_source_sheet", "_source_row", "amount"), [("", 2, 10), ("", 3, 3)])

    completed = run_audit_cli(source, cleaned, excluded, "--reconcile", "amount=value")

    result = reconcile_result(completed, "fail")
    assert result["unexplained"] == []
    entry, = result["reconcile"]
    group, = entry["groups"]
    assert_reconcile_totals(group, source=11, kept=11, cleaned=13, excluded=0, difference=2)


def test_reconcile_reports_a_difference_only_for_the_affected_source_group(tmp_path):
    source = tmp_path / "source.xlsx"
    workbook = Workbook()
    workbook.active.title = "First"
    workbook.create_sheet("Second")
    workbook.create_sheet("Outside")
    for sheet, team, value in [("First", "A", 8), ("Second", "B", 3), ("Outside", "A", 20)]:
        workbook[sheet].append(["team", "value"])
        workbook[sheet].append([team, value])
    workbook.save(source)
    workbook.close()
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "amount"),
                        [("Second", 2, 3), ("First", 2, 9)])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--header-row", "1", "--sheets", "First,Second",
                              "--reconcile", "amount=value@team")

    result = reconcile_result(completed, "fail")
    assert result["unexplained"] == []
    entry, = result["reconcile"]
    assert (entry["cleaned_col"], entry["source_col"], entry["group_col"]) == ("amount", "value", "team")
    assert len(entry["groups"]) == 2
    groups = {group["group"]: group for group in entry["groups"]}
    assert_reconcile_totals(groups["A"], source=8, kept=8, cleaned=9, excluded=0, difference=1)
    assert_reconcile_totals(groups["B"], source=3, kept=3, cleaned=3, excluded=0, difference=0)


def test_reconcile_includes_logged_exclusions_in_source_total(reconcile_csv_files):
    source, cleaned, excluded = reconcile_csv_files
    write_csv(cleaned, ("_source_sheet", "_source_row", "amount"), [("", 2, 8)])
    write_excluded(excluded, [("", 3, "Outside the reporting scope")])

    completed = run_audit_cli(source, cleaned, excluded, "--reconcile", "amount=value")

    result = reconcile_result(completed, "pass")
    assert result["unexplained"] == []
    entry, = result["reconcile"]
    group, = entry["groups"]
    assert_reconcile_totals(group, source=11, kept=8, cleaned=8, excluded=3, difference=0)


def test_reconcile_reports_unexplained_rows_even_when_kept_total_matches(reconcile_csv_files):
    source, cleaned, excluded = reconcile_csv_files
    write_csv(cleaned, ("_source_sheet", "_source_row", "amount"), [("", 2, 8)])

    completed = run_audit_cli(source, cleaned, excluded, "--reconcile", "amount=value")

    result = reconcile_result(completed, "fail")
    assert result["unexplained"] == [{"sheet": "", "row": 3}]


def test_reconcile_accepts_comma_formatted_numeric_text(tmp_path):
    source = write_csv(tmp_path / "source.csv", ("value",), [("1,234.10",), ("1005.20",)])
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "amount"),
                        [("", 2, "1234.1"), ("", 3, "1,005.2")])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--reconcile", "amount=value")

    result = reconcile_result(completed, "pass")
    entry, = result["reconcile"]
    group, = entry["groups"]
    total = Decimal("2239.30")
    assert_reconcile_totals(group, source=total, kept=total, cleaned=total, excluded=0, difference=0)


@pytest.mark.parametrize("mapping, last_amount, status, total, difference", [
    ("amount=value", 4, "pass", 11, 0),
    ("amount=value", 5, "fail", 12, 1),
    ("amount=value@team", 4, "pass", 11, 0),
], ids=["total-matches", "total-differs", "grouped-total-matches"])
def test_reconcile_with_expand_compares_totals(tmp_path, mapping, last_amount, status, total, difference):
    source = write_csv(tmp_path / "source.csv", ("team", "value"), [("A", 8), ("A", 3)])
    # The repeated address sums to 7, while the source row contains 8.
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "amount"),
                        [("", 2, 3), ("", 2, 4), ("", 3, last_amount)])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--expand", "--reconcile", mapping)

    result = reconcile_result(completed, status)
    assert result["unexplained"] == []
    entry, = result["reconcile"]
    group, = entry["groups"]
    if "@" in mapping:
        assert entry["group_col"] == "team"
        assert group["group"] == "A"
    assert_reconcile_totals(group, source=11, kept=11, cleaned=total, excluded=0, difference=difference)


@pytest.mark.parametrize("amount, status, difference", [
    ("0.30", "pass", "0.10"),
    ("0.2999", "fail", "0.1001"),
], ids=["at-tolerance", "beyond-tolerance"])
def test_reconcile_applies_decimal_tolerance_at_the_boundary(tmp_path, amount, status, difference):
    source = write_csv(tmp_path / "source.csv", ("value",), [("0.40",)])
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "amount"),
                        [("", 2, amount)])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--reconcile", "amount=value",
                              "--reconcile-tolerance", "0.10")

    result = reconcile_result(completed, status)
    entry, = result["reconcile"]
    group, = entry["groups"]
    assert_reconcile_totals(group, source=Decimal("0.40"), kept=Decimal("0.40"),
                            cleaned=Decimal(amount), excluded=0, difference=Decimal(difference))


def test_reconcile_limits_group_details_to_fifty(tmp_path):
    teams = [f"team-{number:02d}" for number in range(53)]
    source = write_csv(tmp_path / "source.csv", ("team", "value"), [(team, 1) for team in teams])
    cleaned = write_csv(tmp_path / "cleaned.csv", ("_source_sheet", "_source_row", "amount"),
                        [("", row, 1) for row in range(2, len(teams) + 2)])
    excluded = write_excluded(tmp_path / "excluded.csv")

    completed = run_audit_cli(source, cleaned, excluded, "--reconcile", "amount=value@team")

    result = reconcile_result(completed, "pass")
    entry, = result["reconcile"]
    assert len(entry["groups"]) == 50
    assert entry["truncated_groups"] == 3
    reported_teams = {group["group"] for group in entry["groups"]}
    assert len(reported_teams) == 50
    assert reported_teams <= set(teams)
