import csv
from decimal import Decimal
import json
import subprocess
import sys

from openpyxl import Workbook
import pytest

from conftest import SCRIPTS


SCRIPT = SCRIPTS / "check_join.py"


def write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(header)
        writer.writerows(rows)
    return path


def write_inputs(tmp_path, left_rows, right_rows):
    left = write_csv(tmp_path / "left.csv", ("id", "left_amount"), left_rows)
    right = write_csv(tmp_path / "right.csv", ("id", "right_amount"), right_rows)
    return left, right


def run_join_cli(left, right, *options, left_key="id", right_key="id"):
    return subprocess.run(
        [sys.executable, "-I", "-B", str(SCRIPT), str(left), str(right),
         "--left-key", left_key, "--right-key", right_key, *options],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )


def read_result(completed, exit_code=0):
    assert completed.returncode == exit_code, completed.stderr or completed.stdout
    return json.loads(completed.stdout, parse_float=Decimal)


def test_one_to_one_pass_writes_json_without_changing_inputs(tmp_path):
    left, right = write_inputs(tmp_path, [("a", 1), ("b", 2)], [("b", 3), ("a", 4)])
    original = (left.read_bytes(), right.read_bytes())
    output = tmp_path / "join-report.json"

    completed = run_join_cli(left, right, "--out", str(output))

    assert completed.returncode == 0, completed.stderr or completed.stdout
    result = json.loads(output.read_text(encoding="utf-8"))
    assert result["status"] == "pass"
    assert result["expected_rows"] == 2
    assert result["relationship"] == "one-to-one"
    for side in ("left", "right"):
        assert result[side]["rows"] == 2
        assert result[side]["null_key_rows"] == {"count": 0, "example_rows": []}
        assert result[side]["duplicate_keys"] == 0
        assert result[side]["max_multiplicity"] == 1
        assert result["unmatched"][side] == {"count": 0, "example_rows": []}
    assert (left.read_bytes(), right.read_bytes()) == original


def test_one_to_many_repeats_totals_by_the_other_sides_multiplicity(tmp_path):
    left, right = write_inputs(
        tmp_path, [("a", "1,200.10"), ("b", "0.20"), ("left-only", "2.00")],
        [("a", "0.10"), ("a", "0.20"), ("b", "0.30")],
    )
    joined = write_csv(
        tmp_path / "joined.csv", ("id", "left_amount", "right_amount"),
        [("a", "1,200.10", "0.10"), ("a", "1200.10", "0.20"), ("b", "0.20", "0.30")],
    )

    result = read_result(run_join_cli(
        left, right, "--joined", str(joined),
        "--total", "left:left_amount", "--total", "right:right_amount",
    ))

    assert result["status"] == "pass"
    assert result["relationship"] == "one-to-many"
    assert result["right"]["duplicate_keys"] == 1
    assert result["right"]["max_multiplicity"] == 2
    assert result["expected_rows"] == result["joined_rows"] == 3
    for total, source, expected in [
        ("left:left_amount", "1202.30", "2400.40"),
        ("right:right_amount", "0.60", "0.60"),
    ]:
        amounts = result["totals"][total]
        assert Decimal(amounts["source"]) == Decimal(source)
        assert Decimal(amounts["expected"]) == Decimal(amounts["actual"]) == Decimal(expected)


def test_many_to_one_passes(tmp_path):
    left, right = write_inputs(
        tmp_path, [("a", 1), ("a", 2), ("b", 3)], [("a", 4), ("b", 5)],
    )

    result = read_result(run_join_cli(left, right))

    assert result["status"] == "pass"
    assert result["relationship"] == "many-to-one"
    assert result["expected_rows"] == 3


def test_many_to_many_warns_and_counts_all_matching_pairs(tmp_path):
    left, right = write_inputs(
        tmp_path, [("a", 1), ("a", 2), ("b", 3)],
        [("a", 4), ("a", 5), ("a", 6), ("b", 7)],
    )

    result = read_result(run_join_cli(left, right))

    assert result["status"] == "warn"
    assert result["relationship"] == "many-to-many"
    assert result["expected_rows"] == 7
    assert result["left"]["duplicate_keys"] == result["right"]["duplicate_keys"] == 1
    assert result["left"]["max_multiplicity"] == 2
    assert result["right"]["max_multiplicity"] == 3


def test_null_composite_keys_warn_with_original_csv_line_numbers(tmp_path):
    left = write_csv(
        tmp_path / "left.csv", ("group", "code", "note", "amount"),
        [("g", "a", "two\nlines", 1)] + [("g", "", "missing", 2)] * 12,
    )
    right = write_csv(
        tmp_path / "right.csv", ("category", "item", "amount"),
        [("g", "a", 3), ("g", "b", 4), ("", "a", 5)],
    )

    result = read_result(run_join_cli(left, right, left_key="group,code", right_key="category,item"))

    assert result["status"] == "warn"
    assert result["expected_rows"] == 1
    assert result["left"]["rows"] == 13
    assert result["left"]["null_key_rows"] == {"count": 12, "example_rows": list(range(4, 14))}
    assert result["right"]["null_key_rows"] == {"count": 1, "example_rows": [4]}


@pytest.mark.parametrize("how, expected_rows", [("left", 5), ("right", 4), ("outer", 7)])
def test_join_mode_preserves_each_unmatched_row(tmp_path, how, expected_rows):
    left, right = write_inputs(
        tmp_path, [("a", 1), ("b", 2), ("b", 3), ("a", 4), ("c", 5)],
        [("d", 6), ("a", 7), ("d", 8)],
    )

    result = read_result(run_join_cli(left, right, "--how", how))

    assert result["expected_rows"] == expected_rows
    assert result["unmatched"] == {
        "left": {"count": 3, "example_rows": [3, 4, 6]},
        "right": {"count": 2, "example_rows": [2, 4]},
    }


def test_unmatched_examples_are_capped_but_the_count_is_complete(tmp_path):
    left, right = write_inputs(
        tmp_path, [("a", 1), ("b", 2)] + [(f"extra-{index}", index) for index in range(12)],
        [("a", 3), ("b", 4)],
    )

    result = read_result(run_join_cli(left, right))

    assert result["status"] == "pass"
    assert result["expected_rows"] == 2
    assert result["unmatched"]["left"] == {"count": 12, "example_rows": list(range(4, 14))}


def test_joined_row_count_mismatch_fails(tmp_path):
    left, right = write_inputs(tmp_path, [("a", 1), ("b", 2), ("c", 3)], [("a", 4), ("b", 5), ("c", 6)])
    joined = write_csv(tmp_path / "joined.csv", ("id", "left_amount"), [("a", 1), ("b", 2)])

    result = read_result(run_join_cli(left, right, "--joined", str(joined)), exit_code=1)

    assert result["status"] == "fail"
    assert result["expected_rows"] == 3
    assert result["joined_rows"] == 2


def test_joined_total_fails_on_a_decimal_difference_with_equal_row_counts(tmp_path):
    left, right = write_inputs(
        tmp_path, [("a", "9,007,199,254,740,992.00"), ("b", "0.10")], [("a", 3), ("b", 4)],
    )
    joined = write_csv(
        tmp_path / "joined.csv", ("id", "left_amount"),
        [("a", "9007199254740992.01"), ("b", "0.10")],
    )

    result = read_result(run_join_cli(
        left, right, "--joined", str(joined), "--total", "left:left_amount",
    ), exit_code=1)

    assert result["status"] == "fail"
    assert result["expected_rows"] == result["joined_rows"] == 2
    amounts = result["totals"]["left:left_amount"]
    assert Decimal(amounts["source"]) == Decimal(amounts["expected"]) == Decimal("9007199254740992.10")
    assert Decimal(amounts["actual"]) == Decimal("9007199254740992.11")


@pytest.mark.parametrize("normalize, expected_rows, changed_keys", [
    (None, 1, None),
    ("trim", 4, 2),
    ("casefold", 2, 1),
    ("trim,casefold", 6, 4),
], ids=["raw", "trim", "casefold", "both"])
def test_normalization_matches_keys_and_counts_each_changed_key_once(
    tmp_path, normalize, expected_rows, changed_keys,
):
    left, right = write_inputs(
        tmp_path, [("  alpha  ", 1), ("Straße", 2), ("  GaMmA  ", 3), ("same", 4), ("  delta  ", 5)],
        [("alpha", 6), ("STRASSE", 7), ("gamma", 8), ("same", 9), ("delta", 10), ("delta", 11)],
    )
    original = (left.read_bytes(), right.read_bytes())
    options = ("--normalize", normalize) if normalize else ()

    result = read_result(run_join_cli(left, right, *options))

    assert result["status"] == "pass"
    assert result["expected_rows"] == expected_rows
    if changed_keys is not None:
        assert result["normalized_matches"] == changed_keys
    assert (left.read_bytes(), right.read_bytes()) == original


def test_leading_zeros_are_significant_in_composite_text_keys(tmp_path):
    left = write_csv(
        tmp_path / "left.csv", ("region", "code", "amount"),
        [("east", "007", 1), ("east", "0007", 2), ("west", "007", 3)],
    )
    right = write_csv(
        tmp_path / "right.csv", ("area", "item", "amount"),
        [("east", "007", 4), ("east", "7", 5), ("north", "007", 6)],
    )

    result = read_result(run_join_cli(left, right, left_key="region,code", right_key="area,item"))

    assert result["status"] == "pass"
    assert result["expected_rows"] == 1
    assert result["unmatched"] == {
        "left": {"count": 2, "example_rows": [3, 4]},
        "right": {"count": 2, "example_rows": [3, 4]},
    }


def test_left_and_right_sheet_options_select_tables_independently(tmp_path):
    left = tmp_path / "left.xlsx"
    right = tmp_path / "right.xlsx"
    for path, sheet_name, first_amount in [(left, "Left data", 1), (right, "Right data", 3)]:
        workbook = Workbook()
        workbook.active.append(["unselected"])
        sheet = workbook.create_sheet(sheet_name)
        sheet.append(["id", "amount"])
        sheet.append(["a", first_amount])
        sheet.append(["b", first_amount + 1])
        workbook.save(path)
        workbook.close()

    result = read_result(run_join_cli(
        left, right, "--left-sheet", "Left data", "--right-sheet", "Right data",
    ))

    assert result["status"] == "pass"
    assert result["expected_rows"] == 2


@pytest.mark.parametrize("protected_input", ["left", "right", "joined"])
def test_out_refuses_to_overwrite_an_input(tmp_path, protected_input):
    left, right = write_inputs(tmp_path, [("a", 1), ("b", 2)], [("a", 3), ("b", 4)])
    joined = write_csv(tmp_path / "joined.csv", ("id", "amount"), [("a", 1), ("b", 2)])
    inputs = {"left": left, "right": right, "joined": joined}
    original = {path: path.read_bytes() for path in inputs.values()}

    completed = run_join_cli(left, right, "--joined", str(joined), "--out", str(inputs[protected_input]))

    assert completed.returncode != 0, completed.stdout
    assert "refuse_source_output" in completed.stdout + completed.stderr, completed.stderr or completed.stdout
    assert {path: path.read_bytes() for path in inputs.values()} == original
