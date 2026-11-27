import csv
import importlib
import json
import subprocess
import sys
from time import perf_counter

import pytest

from conftest import ROOT, SCRIPTS


@pytest.fixture
def profile_api():
    try:
        return importlib.import_module("profile_data")
    except ModuleNotFoundError as error:
        pytest.fail(str(error))


def test_outlier_is_flagged_without_row_loss(tmp_path, profile_api):
    path = tmp_path / "profile.csv"
    path.write_text("x,label\n1,a\n2,b\n3,b\n4,d\n100,e\n")
    profile = profile_api.profile_data(path)
    stats = profile["columns"][0]["numeric"]
    assert profile["n_rows"] == stats["count"] == 5
    assert stats["outlier_count"] == 1
    assert stats["outlier_rows"] == [6]
    assert stats["mean"] == 22
    assert profile["columns"][1]["categorical"]["top"][0] == {"value": "b", "count": 2}


def test_profile_original_references_and_units(tmp_path, profile_api):
    path = tmp_path / "profile.csv"
    path.write_text("day,weight (kg),code\n2026-01-01,2 kg,a\n2026-01-02,3 t,b\n"
                    "2026-01-02,3 t,b\n2026-01-04,,c\n")
    result = profile_api.profile_data(path)
    assert result["duplicate_rows"] == {"count": 1, "example_rows": [4]}
    assert result["columns"][0]["datetime"]["missing_intervals"][0]["missing_count"] == 1
    assert result["columns"][1]["units"]["column_name_unit"] == "kg"
    assert result["columns"][1]["units"]["mixed_suffixes"] == ["kg", "t"]
    assert result["columns"][1]["missing_ratio"] == 0.25
    assert result["key_candidates"] == []


def test_json_profile_table_id_and_index(inputs, profile_api):
    result = profile_api.profile_data(inputs["nested.json"], table_id="json:$.days[*].orders")
    assert result["n_rows"] == 5
    assert result["key_candidates"] == ["id"]
    assert result["row_refs"][2] == "$.days[1].orders[0]"


def test_throughput_cli_uses_all_four_rows():
    path = ROOT / "evals" / "cases" / "throughput_hourly" / "input.csv"
    for script in ("inspect_data.py", "profile_data.py"):
        run = subprocess.run([sys.executable, "-I", "-B", str(SCRIPTS / script), str(path)],
                             capture_output=True, text=True)
        assert run.returncode == 0, run.stderr
        result = json.loads(run.stdout)
        table = result["tables"][0] if script == "inspect_data.py" else result
        assert table["n_rows"] == 4
        assert all(column["n_missing"] == 0 for column in table["columns"])


def test_scientific_notation_is_not_a_unit_suffix(tmp_path, profile_api):
    path = tmp_path / "weights.csv"
    path.write_text("weight\n1e3\n2e3 kg\n", encoding="utf-8")
    units = profile_api.profile_data(path, header=True)["columns"][0]["units"]
    assert units["suffix_counts"] == {"kg": 1}


def test_json_null_and_absent_field_are_distinct_source_records(tmp_path, profile_api):
    path = tmp_path / "missing.json"
    path.write_text('[{"x":null},{}]', encoding="utf-8")
    profile = profile_api.profile_data(path, json_record_path="$")
    assert profile["columns"][0]["n_missing"] == 2
    assert profile["columns"][0]["n_absent"] == 1
    assert profile["duplicate_rows"]["count"] == 0


def test_profile_does_not_round_away_adjacent_large_integers(tmp_path, profile_api):
    path = tmp_path / "large.csv"
    path.write_text("value\n9007199254740992\n9007199254740993\n", encoding="utf-8")
    stats = profile_api.profile_data(path)["columns"][0]["numeric"]
    assert stats["min"] == 9007199254740992
    assert stats["max"] == 9007199254740993
    assert stats["std"] == pytest.approx(0.70710678)


def test_profile_distinguishes_nested_json_number_from_string(tmp_path, profile_api):
    path = tmp_path / "measurements.json"
    path.write_text('[{"meas":{"v":1.5}},{"meas":{"v":"1.5"}}]', encoding="utf-8")

    profile = profile_api.profile_data(path, json_record_path="$")

    assert profile["duplicate_rows"]["count"] == 0
    columns = {column["name"]: column for column in profile["columns"]}
    assert columns["meas"]["n_unique"] == 2


def test_profile_cli_uses_explicit_encoding(tmp_path):
    path = tmp_path / "source.csv"
    path.write_bytes("id,name\n1,똠\n".encode("cp949"))

    completed = subprocess.run(
        [sys.executable, "-I", "-B", str(SCRIPTS / "profile_data.py"), str(path),
         "--encoding", "cp949"],
        capture_output=True, text=True, encoding="utf-8", timeout=15,
    )

    assert completed.returncode == 0, completed.stderr
    profile = json.loads(completed.stdout)
    assert profile["columns"][1]["example_values"] == ["똠"]


def test_missing_pattern_by_group_ranks_spread_and_caps_source_rows(tmp_path, profile_api):
    path = tmp_path / "groups.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["value", "segment", "region", "channel", "batch", "item"])
        for row in range(40):
            missing = row < 20
            groups = [
                "a" if row % 20 < (cutoff if missing else 20 - cutoff) else "b"
                for cutoff in (16, 15, 14)
            ]
            value = ("NA" if row % 2 else "") if missing else "1"
            writer.writerow([value, *groups, f"batch-{row // 2}", f"item-{min(row, 20)}"])

    profile = profile_api.profile_data(path, header=True)
    groups = profile["missing_patterns"]["columns"]["value"]["by_group"]

    # Batch has 20 categories and item has 21. Both have a spread of 1.
    assert [group["group_col"] for group in groups] == ["batch", "segment", "region"]
    segment = groups[1]
    assert segment["max_rate"] == pytest.approx(0.8)
    assert segment["min_rate"] == pytest.approx(0.2)
    assert segment["spread"] == pytest.approx(0.6)
    assert segment["worst_group"] == "a"
    assert len(segment["worst_rows"]) == 10
    assert len(set(segment["worst_rows"])) == 10
    assert set(segment["worst_rows"]) <= set(range(2, 18))


def test_missing_pattern_by_period_compares_calendar_months(tmp_path, profile_api):
    path = tmp_path / "months.csv"
    path.write_text(
        "day,value\n"
        "2025-02-01,\n2025-02-02,NA\n2025-02-03,1\n"
        "2025-03-01,2\n2025-03-02,\n"
        "2026-02-01,3\n2026-02-02,4\n2026-02-03,5\n2026-02-04,\n",
        encoding="utf-8",
    )

    profile = profile_api.profile_data(path, header=True)
    period = profile["missing_patterns"]["columns"]["value"]["by_period"]

    assert period["worst_period"] == "2025-02"
    assert period["best_period"] == "2026-02"
    assert period["max_rate"] == pytest.approx(2 / 3)
    assert period["min_rate"] == pytest.approx(1 / 4)
    assert period["spread"] == pytest.approx(2 / 3 - 1 / 4)


def test_missing_pattern_co_missing_reports_top_three_jaccard_scores(tmp_path, profile_api):
    path = tmp_path / "overlap.csv"
    path.write_text(
        "value,close,partial,weak,rare\n"
        ",NA,,,NA\nNA,,,,1\n,,NA,1,2\nNA,,2,3,4\n1,NA,3,4,5\n2,3,4,5,6\n",
        encoding="utf-8",
    )

    profile = profile_api.profile_data(path, header=True)
    overlaps = profile["missing_patterns"]["columns"]["value"]["co_missing"]

    assert [overlap["column"] for overlap in overlaps] == ["close", "partial", "weak"]
    assert [overlap["both_missing"] for overlap in overlaps] == [4, 3, 2]
    assert [overlap["jaccard"] for overlap in overlaps] == pytest.approx([4 / 5, 3 / 4, 2 / 4])


def test_missing_pattern_omits_complete_columns(tmp_path, profile_api):
    path = tmp_path / "complete.csv"
    path.write_text("complete,blank,token\n0,,2\n1,3,NA\n", encoding="utf-8")

    profile = profile_api.profile_data(path, header=True)
    columns = profile["missing_patterns"]["columns"]

    assert set(columns) == {"blank", "token"}


def test_missing_pattern_truncates_to_fifty_highest_missing_rates(tmp_path, profile_api):
    path = tmp_path / "wide.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(f"value_{count}" for count in range(1, 53))
        for row in range(53):
            writer.writerow("" if row < count else "1" for count in range(1, 53))

    profile = profile_api.profile_data(path, header=True)
    patterns = profile["missing_patterns"]

    assert patterns["truncated_columns"] == 2
    assert set(patterns["columns"]) == {f"value_{count}" for count in range(3, 53)}


def test_missing_pattern_profile_finishes_within_ten_seconds(tmp_path, profile_api):
    path = tmp_path / "large_missing.csv"
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["day", "group", *(f"value_{col}" for col in range(10))])
        for row in range(60_000):
            day = f"2025-{row % 12 + 1:02d}-{row % 28 + 1:02d}"
            values = ["" if (row + col) % (col + 2) == 0 else row + col for col in range(10)]
            writer.writerow([day, f"group-{row % 8}", *values])

    started = perf_counter()
    profile = profile_api.profile_data(path, header=True)
    elapsed = perf_counter() - started

    assert profile["n_rows"] == 60_000
    assert len(profile["columns"]) == 12
    assert len(profile["missing_patterns"]["columns"]) == 10
    assert elapsed <= 10, f"profile_data took {elapsed:.2f} seconds"


def test_missing_pattern_has_no_mechanism_or_p_value_keys(tmp_path, profile_api):
    path = tmp_path / "observed.csv"
    path.write_text(
        "day,group,value,other\n2026-01-01,a,,NA\n2026-01-02,a,,1\n"
        "2026-02-01,b,2,3\n2026-02-02,b,4,\n",
        encoding="utf-8",
    )

    profile = profile_api.profile_data(path, header=True)
    assert profile["missing_patterns"]["columns"]["value"]

    def check_keys(obj):
        for key in obj:
            normalized = key.lower().replace("-", "_").replace(" ", "_")
            assert {"mcar", "mar", "mnar"}.isdisjoint(normalized.split("_")), key
            assert normalized != "p" and not normalized.replace("_", "").startswith("pval"), key
        return obj

    json.loads(json.dumps(profile), object_hook=check_keys)
