import csv
import importlib
import json
import subprocess
import sys
import zipfile

from openpyxl import Workbook
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from conftest import SCRIPTS


@pytest.fixture
def api():
    try:
        return importlib.import_module("inspect_data")
    except ModuleNotFoundError as error:
        pytest.fail(str(error))


@pytest.mark.parametrize(("name", "fmt", "encoding", "delimiter"), [
    ("plain.csv", "csv", "utf-8", ","),
    ("bom.csv", "csv", "utf-8-sig", ","),
    ("korean.csv", "csv", "cp949", ","),
    ("tab.tsv", "tsv", "utf-8", "\t"),
    ("semi.csv", "csv", "utf-8", ";"),
])
def test_text_detection(api, inputs, name, fmt, encoding, delimiter):
    report = api.inspect_data(inputs[name])
    assert report["detected_format"] == fmt
    assert report["encoding"] == encoding
    assert report["delimiter"] == delimiter
    assert report["header_present"] is True
    assert report["conflict"] is False
    if name == "korean.csv":
        assert report["tables"][0]["columns"][0]["name"] == "이름"
        assert api.load_table(inputs[name]).frame["이름"].tolist() == ["가나다", "라마바"]
        assert not report.get("encoding_ambiguous", False)


def test_cp1252_degree_units_do_not_look_like_korean(api, tmp_path):
    path = tmp_path / "units.csv"
    path.write_bytes(b"Inlet(\xb0C),Outlet(\xb0C)\n21,13\n")

    report = api.inspect_data(path)

    assert report["encoding"] == "cp1252"
    assert report["tables"][0]["source_headers"] == ["Inlet(°C)", "Outlet(°C)"]
    assert not report.get("encoding_ambiguous", False)


def test_mixed_cp949_evidence_reports_both_header_readings(api, tmp_path):
    path = tmp_path / "mixed.csv"
    header = "값".encode("cp949") + b"(\xb0C),count"
    path.write_bytes(header + b"\nA,1\n")

    report = api.inspect_data(path)

    assert report["encoding_ambiguous"] is True
    candidates = {entry["encoding"]: entry for entry in report["encoding_candidates"]}
    assert set(candidates) == {"cp949", "cp1252"}
    assert report["encoding"] in candidates
    warning = next(warning for warning in report["warnings"] if "encoding" in warning.lower())
    for encoding, candidate in candidates.items():
        assert candidate["confidence_note"]
        assert candidate["header_preview"] == header.decode(encoding)
        assert encoding in warning and candidate["header_preview"] in warning


def test_ragged_rows_and_position(api, inputs):
    report = api.inspect_data(inputs["ragged.csv"])
    assert [(row["line"], row["field_count"]) for row in report["irregular_rows"]] == [(3, 3), (4, 1)]
    assert report["read_extent"]["rows_read"] == 4
    table = api.load_table(inputs["ragged.csv"])
    assert list(table.row_refs) == [2, 3, 4, 5]
    assert table.frame.iloc[1, 2] == "extra"
    assert table.frame.iloc[2, 1] is None


def test_id_spaces_and_empty_string(api, inputs):
    table = api.load_table(inputs["ids.csv"])
    assert table.frame["id"].tolist() == ["00123", "00456"]
    assert table.frame["label"].tolist() == ["  literal  ", "NA"]
    assert table.frame["value"].tolist() == ["", "0"]
    fields = api.inspect_data(inputs["ids.csv"])["tables"][0]["columns"]
    assert fields[0]["inferred_type"] == "string"
    assert fields[2]["n_empty_string"] == 1


def test_multiline_and_headerless_use_source_lines(api, inputs):
    table = api.load_table(inputs["plain.csv"])
    assert list(table.row_refs) == [2, 4]
    assert table.frame.iloc[0, 0] == "two\nlines"
    report = api.inspect_data(inputs["no_header.csv"])
    assert report["header_present"] is False
    assert report["read_extent"]["rows_read"] == 2


def test_malformed_record_does_not_claim_total(api, inputs):
    report = api.inspect_data(inputs["partial.csv"])
    assert report["read_extent"]["rows_read"] == 1
    assert report["read_extent"]["rows_total_or_unknown"] == "unknown"
    assert report["read_extent"]["unread"][0]["line_range"] == [3, 4]


def test_workbook_metadata_and_explicit_sheet(api, inputs):
    report = api.inspect_data(inputs["book.xlsx"])
    assert report["detected_format"] == "xlsx"
    assert [item["name"] for item in report["sheets"]] == ["Sales", "Other"]
    sales = report["sheets"][0]
    assert sales["used_range"] == "A1:C2"
    assert sales["merged_ranges"] == ["B1:C1"]
    assert sales["header_candidates"][0] == 1
    assert sales["formula_count"] == sales["uncached_formula_count"] == 1
    assert sales["formulas"][0]["coordinate"] == "B2"
    with pytest.raises(ValueError, match="table|sheet"):
        api.load_table(inputs["book.xlsx"])
    table = api.load_table(inputs["book.xlsx"], sheet="Sales")
    assert table.frame.iloc[0, :2].tolist() == ["A", "=1+1"]
    assert list(table.row_refs) == [2]


def test_nested_json_requires_explicit_path(api, inputs):
    path = inputs["nested.json"]
    report = api.inspect_data(path)
    assert report["detected_format"] == "json"
    assert report["top_level_type"] == "object"
    assert report["tables"] == []
    with pytest.raises(ValueError, match="json_record_path"):
        api.load_table(path)
    candidates = {entry["path"]: entry for entry in report["record_candidates"]}
    orders = candidates["$.days[*].orders"]
    assert [(row["path"], row["n_rows"]) for row in orders["occurrences"]] == [
        ("$.days[0].orders", 2), ("$.days[1].orders", 3)]
    items = candidates["$.days[*].orders[*].items"]
    assert sum(row["n_rows"] for row in items["occurrences"] if "[0].orders" in row["path"]) == 4
    assert sum(row["n_rows"] for row in items["occurrences"] if "[1].orders" in row["path"]) == 3
    assert items["predicted_rows"] == 7
    assert "$.days[*].orders[*].items[*].qty" in report["nested_field_paths"]
    assert api.load_table(path, table_id=orders["id"]).frame["id"].tolist() == [
        "a1", "a2", "b1", "b2", "b3"]
    table = api.load_table(path, json_record_path=items["path"])
    assert table.frame["qty"].tolist() == [1, 2, 3, 4, 5, 6, 7]
    assert table.row_refs[-1] == "$.days[1].orders[2].items[0]"
    assert api.load_table(inputs["spaced.json"], json_record_path='$["odd.key"]').frame.iloc[0, 0] == 7


def test_jsonl_records_failed_lines(api, inputs):
    report = api.inspect_data(inputs["rows.jsonl"])
    assert report["detected_format"] == "jsonl"
    assert report["failed_lines"] == [2]
    assert report["read_extent"]["rows_read"] == 2
    assert list(api.load_table(inputs["rows.jsonl"]).row_refs) == [1, 3]


def test_parquet_metadata(api, inputs):
    report = api.inspect_data(inputs["rows.parquet"])
    assert report["detected_format"] == "parquet"
    assert report["row_group_count"] == 2
    assert report["read_extent"]["rows_total_or_unknown"] == 2
    assert [field["name"] for field in report["schema"]] == ["id", "x"]
    assert list(api.load_table(inputs["rows.parquet"]).row_refs) == [1, 2]


def test_markdown_tables_and_escaped_pipe(api, inputs):
    path = inputs["tables.md"]
    report = api.inspect_data(path)
    assert report["detected_format"] == "markdown"
    assert report["table_count"] == 2
    first, second = report["tables"]
    assert first["locator"]["line_range"] == [3, 6]
    assert second["locator"]["line_range"] == [10, 12]
    assert first["irregular_rows"][0]["line"] == 6
    assert api.load_table(path, table_id=first["id"]).frame.iloc[0, 1] == "left | right"


def test_conflict_and_unsupported_excel(api, inputs):
    report = api.inspect_data(inputs["mismatch.csv"])
    assert (report["extension"], report["extension_format"], report["detected_format"], report["conflict"]) == (
        ".csv", "csv", "json", True)
    assert report["evidence"]
    report = api.inspect_data(inputs["legacy.xls"])
    assert report["detected_format"] == "xls"
    assert "unsupported: convert to xlsx" in report["warnings"]


def test_content_can_override_a_json_extension(api, tmp_path):
    path = tmp_path / "text.json"
    path.write_text("name,value\nA,1\nB,2\n", encoding="utf-8")
    report = api.inspect_data(path)
    assert report["detected_format"] == "csv"
    assert report["conflict"] is True
    assert report["read_extent"]["rows_read"] == 2


def test_jsonl_detection_can_recover_past_an_invalid_first_line(api, tmp_path):
    path = tmp_path / "lines.csv"
    path.write_text('broken\n{"x":1}\n{"x":2}\n', encoding="utf-8")
    report = api.inspect_data(path)
    assert report["detected_format"] == "jsonl"
    assert report["conflict"] is True
    assert report["failed_lines"] == [1]


def test_json_selection_reports_branches_without_the_selected_array(api, tmp_path):
    path = tmp_path / "branches.json"
    path.write_text('{"groups":[{"items":[{"x":1}]},{}]}', encoding="utf-8")
    table = api.load_table(path, json_record_path="$.groups[*].items")
    assert table.row_refs == ["$.groups[0].items[0]"]
    assert table.details["coverage"]["unread"][0]["json_path"] == "$.groups[1].items"


def test_one_column_padded_identifiers_keep_their_header_and_values(api, tmp_path):
    path = tmp_path / "identifiers.csv"
    path.write_text("id\n00123\n00456\n", encoding="utf-8")
    assert api.load_table(path).frame["id"].tolist() == ["00123", "00456"]


@pytest.mark.parametrize("header", ["PKG,amount", "[group],amount", "PAR1,amount"])
def test_plain_text_headers_do_not_match_container_signatures(api, tmp_path, header):
    path = tmp_path / "prefix.csv"
    path.write_text(f"{header}\nA,1\n", encoding="utf-8")
    assert api.inspect_data(path)["detected_format"] == "csv"
    assert api.load_table(path).row_refs == [2]


def test_markdown_link_before_a_table_stays_plain_text(api, tmp_path):
    path = tmp_path / "link.md"
    path.write_text("[More](https://example.invalid)\n\n| id | value |\n| --- | --- |\n| a | 1 |\n",
                    encoding="utf-8")
    report = api.inspect_data(path)
    assert report["detected_format"] == "markdown"
    assert report["tables"][0]["locator"]["line_range"] == [3, 5]


def test_markdown_table_after_a_paragraph_starting_with_a_quote(api, tmp_path):
    path = tmp_path / "notes.md"
    path.write_text('" is the double quote character.\n\n| item | count |\n| --- | --- |\n| A | 1 |\n',
                    encoding="utf-8")

    report = api.inspect_data(path)

    assert report["detected_format"] == "markdown"
    assert report["read_extent"]["rows_read"] == 1
    assert report["tables"][0]["n_rows"] == 1


def test_inspect_keeps_csv_prefix_before_damage_and_a_markdown_table(api, tmp_path):
    path = tmp_path / "damaged.csv"
    path.write_text('id,memo\n1,good\n2,"break\n| id | memo |\n| --- | --- |\n| 3 | note |\n',
                    encoding="utf-8")

    report = api.inspect_data(path)

    assert report["detected_format"] == "csv"
    assert report["read_extent"]["rows_read"] == 1
    unread, = report["read_extent"]["unread"]
    assert unread["line_range"] == [3, 6]
    assert unread["reason"].strip()
    table = api.load_table(path)
    assert table.row_refs == [2]
    assert table.frame.to_dict("records") == [{"id": "1", "memo": "good"}]
    assert table.details["coverage"]["unread"] == [unread]


def test_invalid_worksheet_does_not_hide_healthy_sheet(api, inputs, tmp_path):
    path = tmp_path / "damaged.xlsx"
    with zipfile.ZipFile(inputs["book.xlsx"]) as original, zipfile.ZipFile(path, "w") as damaged:
        for part in original.namelist():
            damaged.writestr(part, b"<bad" if part == "xl/worksheets/sheet2.xml" else original.read(part))
    report = api.inspect_data(path)
    assert [sheet["name"] for sheet in report["sheets"]] == ["Sales", "Other"]
    assert report["read_extent"]["rows_read"] == 1
    assert report["read_extent"]["rows_total_or_unknown"] == "unknown"
    assert report["read_extent"]["unread"][0]["sheet"] == "Other"
    assert api.load_table(path, sheet="Sales").frame.iloc[0, 0] == "A"


@pytest.fixture
def excel_with_sparse_sheet(tmp_path):
    path = tmp_path / "sheets.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Sparse"
    sheet["B2"] = "count"
    sheet["B5"] = 3
    sheet["D5"] = 4
    workbook.create_sheet("Summary").append([7])
    workbook.save(path)
    workbook.close()
    return path


def test_load_excel_rejects_sheet_above_cell_limit(api, excel_with_sparse_sheet, monkeypatch):
    eda_io = importlib.import_module("eda_io")
    monkeypatch.setattr(eda_io, "MAX_TABLE_CELLS", 12, raising=False)
    assert api.load_table(excel_with_sparse_sheet, sheet="Sparse").frame.shape == (3, 3)

    monkeypatch.setattr(eda_io, "MAX_TABLE_CELLS", 11, raising=False)
    with pytest.raises(ValueError, match=r"Sparse.*B2:D5.*\b12 cells\b") as error:
        api.load_table(excel_with_sparse_sheet, sheet="Sparse")
    assert "smaller range" in str(error.value)
    assert "CSV" in str(error.value)


def test_inspect_excel_reports_cell_limit_and_reads_next_sheet(excel_with_sparse_sheet):
    script = """
import json
import sys

sys.path.insert(0, sys.argv[1])
import eda_io
from inspect_data import inspect_data

try:
    import resource
    limit = resource.RLIMIT_AS
    soft, hard = resource.getrlimit(limit)
    cap = 1536 * 1024**2
    if soft == resource.RLIM_INFINITY or soft > cap:
        resource.setrlimit(limit, (cap, hard))
except (ImportError, AttributeError, OSError, ValueError):
    # Some systems do not support setting an address-space limit.
    pass

eda_io.MAX_TABLE_CELLS = 11
print(json.dumps(inspect_data(sys.argv[2])))
"""
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", script, str(SCRIPTS), str(excel_with_sparse_sheet)],
        capture_output=True, text=True, encoding="utf-8", timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert [table["id"] for table in report["tables"]] == ["sheet:Summary"]
    assert report["read_extent"]["rows_read"] == 1
    unread, = report["read_extent"]["unread"]
    assert unread["sheet"] == "Sparse"
    assert unread["range"] == "B2:D5"
    assert "12 cells" in unread["reason"]
    assert "smaller range" in unread["reason"]
    assert "CSV" in unread["reason"]


def test_jsonl_reports_nested_fields(api, tmp_path):
    path = tmp_path / "objects.jsonl"
    path.write_text('{"attributes":{"code":"a"}}\n{"attributes":{"code":"b"}}\n', encoding="utf-8")
    report = api.inspect_data(path)
    assert "$.attributes.code" in report["nested_field_paths"]


def test_competing_csv_dialects_require_selection_for_loading(api, tmp_path):
    path = tmp_path / "ambiguous.csv"
    path.write_text("a,b|c\n1,2|x\n3,4|z\n", encoding="utf-8")
    report = api.inspect_data(path)
    assert set(report["delimiter_candidates"]) == {",", "|"}
    assert report["read_extent"]["rows_total_or_unknown"] == "unknown"
    with pytest.raises(ValueError, match="Competing delimiters"):
        api.load_table(path)
    assert api.load_table(path, delimiter=",", header=True).frame["b|c"].tolist() == ["2|x", "4|z"]


def test_parquet_bad_group_keeps_prior_groups_and_coverage(api, tmp_path):
    path = tmp_path / "dates.parquet"
    dates = pa.array([0, 2147483647], type=pa.date32())
    pq.write_table(pa.table({"day": dates}), path, row_group_size=1)
    report = api.inspect_data(path)
    assert report["read_extent"]["rows_read"] == 1
    assert report["read_extent"]["rows_total_or_unknown"] == 2
    assert report["read_extent"]["unread"][0]["row_range"] == [2, 2]
    assert api.load_table(path).row_refs == [1]


@pytest.fixture(params=[
    pytest.param("\n| key | value |\n| --- | --- |\n| A | 1 |", id="markdown-table"),
    pytest.param("\n[1]\n[2]\n", id="json-arrays"),
    pytest.param("\n{}\n{}\n", id="json-objects"),
])
def csv_with_quoted_format_fragment(tmp_path, request):
    note = request.param
    path = tmp_path / "notes.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        csv.writer(stream).writerows([("id", "note"), (1, note), (2, "plain")])
    return path, note


@pytest.mark.parametrize("selection", [{}, {"delimiter": ","}], ids=["auto", "explicit-comma"])
def test_inspect_keeps_csv_with_quoted_format_fragment(api, csv_with_quoted_format_fragment, selection):
    path, note = csv_with_quoted_format_fragment

    report = api.inspect_data(path, **selection)

    assert report["detected_format"] == "csv"
    assert report["delimiter"] == ","
    assert report["read_extent"]["rows_read"] == 2
    assert report["tables"][0]["n_rows"] == 2
    assert report["tables"][0]["columns"][1]["example_values"] == [note, "plain"]


@pytest.mark.parametrize("selection", [{}, {"delimiter": ","}], ids=["auto", "explicit-comma"])
def test_load_keeps_csv_with_quoted_format_fragment(api, csv_with_quoted_format_fragment, selection):
    path, note = csv_with_quoted_format_fragment

    table = api.load_table(path, **selection)

    assert table.details["detected_format"] == "csv"
    assert table.row_refs == [2, 6]
    assert table.frame["note"].tolist() == [note, "plain"]


def test_explicit_comma_takes_precedence_over_markdown_detection(api, tmp_path):
    path = tmp_path / "table.txt"
    path.write_text("| item,note |\n| --- |\n| apple,fresh |\n", encoding="utf-8")
    assert api.inspect_data(path)["detected_format"] == "markdown"

    report = api.inspect_data(path, delimiter=",", header=True)
    table = api.load_table(path, delimiter=",", header=True)

    assert report["detected_format"] == "csv"
    assert report["delimiter"] == ","
    assert report["read_extent"]["rows_read"] == 2
    assert table.row_refs == [2, 3]


@pytest.mark.parametrize("rows", [
    [("Seoul",), ("Busan",)],
    [("North", "Active"), ("South", "Paused")],
], ids=["one-column", "two-columns"])
def test_inspect_warns_when_excel_header_lacks_type_evidence(api, tmp_path, rows):
    path = tmp_path / "source.xlsx"
    workbook = Workbook()
    for row in rows:
        workbook.active.append(row)
    workbook.save(path)
    workbook.close()

    report = api.inspect_data(path)

    assert any("header_inferred_without_type_evidence" in warning for warning in report["warnings"])
    assert report["tables"][0]["coverage"]["rows_total_or_unknown"] == "unknown"


def test_inspect_accepts_excel_header_with_type_evidence(api, tmp_path):
    path = tmp_path / "source.xlsx"
    workbook = Workbook()
    for row in [("count",), (3,), (5,)]:
        workbook.active.append(row)
    workbook.save(path)
    workbook.close()

    report = api.inspect_data(path)

    assert not any("header_inferred_without_type_evidence" in warning for warning in report["warnings"])
    assert report["tables"][0]["n_rows"] == 2


@pytest.fixture
def cp949_csv(tmp_path):
    path = tmp_path / "source.csv"
    path.write_bytes("id,name\n1,똠\n".encode("cp949"))
    return path


def test_inspect_reports_cp949_as_an_ambiguous_encoding_candidate(api, cp949_csv):
    report = api.inspect_data(cp949_csv)

    assert report.get("encoding_ambiguous") is True
    assert "cp949" in {candidate["encoding"] for candidate in report["encoding_candidates"]}


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_inspect_keeps_utf8_unambiguous(api, tmp_path, encoding):
    path = tmp_path / "source.csv"
    path.write_bytes("id,name\n1,똠\n".encode(encoding))

    report = api.inspect_data(path)

    assert report["encoding"] == encoding
    assert not report.get("encoding_ambiguous", False)


def test_inspect_cli_uses_explicit_encoding(cp949_csv):
    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(SCRIPTS / "inspect_data.py"), str(cp949_csv),
         "--encoding", "cp949"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    report = json.loads(completed.stdout)
    assert report["encoding"] == "cp949"
    assert report["tables"][0]["columns"][1]["example_values"] == ["똠"]


def test_load_table_uses_explicit_encoding(api, cp949_csv):
    table = api.load_table(cp949_csv, encoding="cp949")

    assert table.frame["name"].tolist() == ["똠"]
