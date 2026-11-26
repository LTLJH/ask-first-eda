import importlib
import json
import subprocess
import sys

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
