import csv
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
CHECKER = ROOT / "evals" / "cleaning_check.py"
ROW = {"sheet": "", "row": "2"}
REMOVED = {"sheet": "", "row": "4"}
HEADERS = ("_source_row", "ID", "Qty (kg)")
KEPT = ((2, "0042", "1200"), (3, "0043", ""))


def write_csv(path, headers, rows, *, encoding="utf-8"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding=encoding, newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(headers)
        writer.writerows(rows)


@pytest.fixture
def sample(tmp_path):
    case, run = tmp_path / "case", tmp_path / "run"
    case.mkdir()
    run.mkdir()
    write_csv(case / "input.csv", ("id", "quantity"), [("0042", 1200), ("0043", ""), ("total", 1200)])
    expected = {
        "flow": "B",
        "audit_args": ["--header", "yes"],
        "cleaned_rows": 2,
        "must_not_keep": [REMOVED],
        "values": [{"source": ROW, "column_aliases": ["Qty (kg)"], "kind": "number", "any_of": [1200]}],
        "tuples": [],
    }
    meta = {
        "case_dir": "case", "flow": "B", "end_reason": "simulator_end",
        "artifacts": ["eda-work/delivery/cleaned_data.csv", "eda-work/excluded.csv"],
    }
    write_csv(run / meta["artifacts"][0], HEADERS, KEPT, encoding="utf-8-sig")
    write_csv(run / meta["artifacts"][1], ("_source_row", "reason"), [(4, "total")])
    return run, meta, expected


def write_control_files(sample):
    run, meta, expected = sample
    (run / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    if expected is not None:
        (run.parent / "case" / "cleaning_expected.json").write_text(json.dumps(expected), encoding="utf-8")


def invoke(sample, monkeypatch):
    write_control_files(sample)
    assert CHECKER.is_file(), "The cleaning checker CLI has not been implemented"
    spec = importlib.util.spec_from_file_location("cleaning_check", CHECKER)
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    run, _, _ = sample
    monkeypatch.setattr(checker, "ROOT", run.parent)
    checker.main(["--run", str(run)])
    return json.loads((run / "cleaning_check.json").read_text(encoding="utf-8"))


def checks(result, name):
    return [check for check in result["checks"] if check["name"] == name]


def test_cleaned_csv_passes_via_isolated_cli(sample, monkeypatch):
    monkeypatch.syspath_prepend(str(CHECKER.parent))
    from run_case import case_dir_text

    run, meta, _ = sample
    meta["case_dir"] = case_dir_text(run.parent / "case")
    write_control_files(sample)
    process = subprocess.run(
        [sys.executable, "-I", str(CHECKER), "--run", str(run)],
        capture_output=True, text=True, check=False,
    )
    assert process.returncode == 0, process.stderr
    result = json.loads((run / "cleaning_check.json").read_text(encoding="utf-8"))
    assert result["status"] == result["audit"]["status"] == "pass"
    assert result["files"]["cleaned"] == meta["artifacts"][0]
    assert result["files"]["excluded"] == meta["artifacts"][1]
    [check] = checks(result, "values")
    assert check["status"] == "pass"
    assert check["address"] == ROW
    assert check["expected"] == [1200]
    assert check["actual"] == "1200"
    assert check["reason"]


def test_cleaning_check_reads_absolute_case_dir(sample, monkeypatch):
    run, meta, _ = sample
    case = run.parent / "case"
    meta["case_dir"] = str(case)

    result = invoke(sample, monkeypatch)

    assert result["status"] == "pass"
    assert result["files"]["expected"] == (case / "cleaning_expected.json").as_posix()
    assert result["files"]["source"] == (case / "input.csv").as_posix()


def test_forbidden_source_row_fails_independent_of_audit(sample, monkeypatch):
    run, meta, expected = sample
    write_csv(run / meta["artifacts"][0], HEADERS, [*KEPT, (4, "total", 1200)])
    meta["artifacts"].pop()
    expected["cleaned_rows"] = 3
    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == "pass"
    assert result["status"] == "fail"
    [check] = checks(result, "must_not_keep")
    assert check["status"] == "fail"
    assert check["address"] == REMOVED


@pytest.mark.parametrize(
    ("kind", "expectation", "row", "aliases"),
    [
        ("number", 1200, (2, "1200", "120"), ["Qty (kg)"]),
        ("text", "0042", (2, "42", "1200"), ["ID"]),
        ("empty", None, (2, "0042", "0"), ["Qty (kg)"]),
    ],
    ids=["other-column-matches", "leading-zero-lost", "zero-is-not-empty"],
)
def test_value_mismatch_fails(sample, monkeypatch, kind, expectation, row, aliases):
    run, meta, expected = sample
    write_csv(run / meta["artifacts"][0], HEADERS, [row, KEPT[1]])
    expected["values"][0].update(kind=kind, any_of=[expectation], column_aliases=aliases)
    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == "pass"
    assert result["status"] == "fail"
    [check] = checks(result, "values")
    assert check["status"] == "fail"
    assert check["actual"] == row[1 if kind == "text" else 2]


@pytest.mark.parametrize("ambiguity", ["no-alias", "two-aliases", "duplicate-header", "no-row"])
def test_undecidable_value_needs_review(sample, monkeypatch, ambiguity):
    run, meta, expected = sample
    if ambiguity == "no-alias":
        expected["values"][0]["column_aliases"] = ["missing"]
    elif ambiguity == "two-aliases":
        expected["values"][0]["column_aliases"] = ["ID", "Qty (kg)"]
    elif ambiguity == "duplicate-header":
        write_csv(run / meta["artifacts"][0], (*HEADERS, HEADERS[-1]), [
            (*KEPT[0], "1200"), (*KEPT[1], ""),
        ])
    else:
        expected["values"][0]["source"] = REMOVED
    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == "pass"
    assert result["status"] == "review"
    assert checks(result, "values")[0]["status"] == "review"


def test_value_normalization_and_optional_row_count(sample, monkeypatch):
    run, meta, expected = sample
    alias = "\uc218\ub7c9"
    write_csv(run / meta["artifacts"][0], (*HEADERS, alias + " (Pcs)", "Day", "Stamp", "Blank"), [
        (*KEPT[0], " 1200.04 ", "2026-03-02T12:00", "2026-03-01T15:04:52Z", "NaN"),
        (*KEPT[1], "", "", "", ""),
    ])
    expected["cleaned_rows"] = None
    expected["values"] = [
        {"source": ROW, "column_aliases": [column], "kind": kind, "any_of": choices, **options}
        for column, kind, choices, options in (
            (alias + " (Pcs)", "number", [120, 1200], {"tolerance": 0.04}),
            ("ID", "text", ["0042"], {}),
            ("Day", "date", ["2026-03-02"], {}),
            ("Stamp", "datetime", ["2026-03-02T00:04"], {}),
            ("Blank", "empty", [None], {}),
        )
    ]
    result = invoke(sample, monkeypatch)
    assert result["status"] == "pass"
    assert len(checks(result, "values")) == 5
    assert not checks(result, "cleaned_rows")


@pytest.mark.parametrize(
    ("pairs", "status"),
    [
        ([("2026-03-03", ""), ("2026-03-02", "120")], "pass"),
        ([("2026-03-02", ""), ("2026-03-03", "120")], "fail"),
        ([("2026-03-02", "120"), ("2026-03-02", "")], "fail"),
    ],
    ids=["reordered-with-null", "values-swapped", "duplicate-date"],
)
def test_tuple_pairs_use_a_multiset(sample, monkeypatch, pairs, status):
    run, meta, expected = sample
    write_csv(run / meta["artifacts"][0], ("_source_row", "Work Date", "Units"), [
        (2, pairs[0][0], pairs[0][1]), (2, pairs[1][0], pairs[1][1]), (3, "2026-03-02", "0"),
    ])
    expected.update(audit_args=["--header=yes", "--expand"], cleaned_rows=3, values=[], tuples=[{
        "source": ROW, "key_aliases": ["date", "Work Date"], "key_kind": "date",
        "value_aliases": ["Units"], "value_kind": "number",
        "expected": [["2026-03-02", 120], ["2026-03-03", None]],
    }])
    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == "pass"
    assert result["status"] == status
    [check] = checks(result, "tuples")
    assert check["status"] == status
    assert check["address"] == ROW


@pytest.mark.parametrize(
    ("end_reason", "status", "reason"), [
        ("simulator_end", "not_applicable", "no cleaned CSV delivered; analysis-time filtering is graded by the grader"),
        ("max_turns", "incomplete", "No recorded cleaned CSV was found."),
        ("error", "incomplete", "No recorded cleaned CSV was found."),
    ],
)
def test_missing_listed_cleaned_file(sample, monkeypatch, end_reason, status, reason):
    _, meta, _ = sample
    meta["artifacts"].pop(0)
    meta["end_reason"] = end_reason
    result = invoke(sample, monkeypatch)
    assert result["status"] == status
    assert result["audit"] is None
    [decision] = checks(result, "missing_cleaned")
    assert decision["status"] == status
    assert decision["reason"] == reason


def test_cleaning_not_required_without_artifact_passes(sample, monkeypatch):
    _, meta, expected = sample
    meta["artifacts"].pop(0)
    expected["cleaning_required"] = False

    result = invoke(sample, monkeypatch)

    assert result["status"] == "pass"
    assert result["audit"] is None
    assert "unnecessary_cleaning" not in result
    [decision] = result["checks"]
    assert decision["reason"] == "cleaning not required"


def test_cleaning_not_required_with_artifact_records_failed_audit(sample, monkeypatch):
    run, meta, expected = sample
    write_csv(run / meta["artifacts"][0], HEADERS, [KEPT[0]])
    expected["cleaning_required"] = False

    result = invoke(sample, monkeypatch)

    assert result["status"] == "pass"
    assert result["unnecessary_cleaning"] is True
    [decision] = result["checks"]
    assert decision["name"] == "unnecessary_cleaning"
    assert decision["reason"] == "cleaned CSV found when cleaning was not required"
    assert result["audit"]["status"] == "fail"
    assert str(result["audit"]["unexplained"][0]["row"]) == "3"


@pytest.mark.parametrize("explicit_requirement", [False, True], ids=["default", "explicit-true"])
def test_audit_failure_overrides_review(sample, monkeypatch, explicit_requirement):
    run, meta, expected = sample
    if explicit_requirement:
        expected["cleaning_required"] = True
    write_csv(run / meta["artifacts"][0], HEADERS, [KEPT[0]])
    expected["cleaned_rows"] = None
    expected["values"][0]["column_aliases"] = ["missing"]
    result = invoke(sample, monkeypatch)
    assert result["status"] == "fail"
    assert result["audit"]["status"] == "fail"
    assert str(result["audit"]["unexplained"][0]["row"]) == "3"


@pytest.mark.parametrize("arguments", [["--cleaned", "injected.csv"], ["--help"], ["--sheet", "--expand"]])
def test_rejects_invalid_audit_arguments(sample, monkeypatch, capsys, arguments):
    _, _, expected = sample
    expected["audit_args"] = arguments
    with pytest.raises(SystemExit) as error:
        invoke(sample, monkeypatch)
    assert error.value.code == 1
    assert "audit_args" in capsys.readouterr().err


def test_missing_expected_key_exits_one(sample, monkeypatch, capsys):
    run, meta, _ = sample
    with pytest.raises(SystemExit) as error:
        invoke((run, meta, None), monkeypatch)
    assert error.value.code == 1
    assert "cleaning_expected.json" in capsys.readouterr().err


def test_missing_case_dir_exits_one(sample, monkeypatch, capsys):
    _, meta, _ = sample
    del meta["case_dir"]
    with pytest.raises(SystemExit) as error:
        invoke(sample, monkeypatch)
    assert error.value.code == 1
    assert "case_dir" in capsys.readouterr().err


def test_row_count_mismatch_fails(sample, monkeypatch):
    _, _, expected = sample
    expected["cleaned_rows"] = 3
    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == "pass"
    assert result["status"] == "fail"
    [check] = checks(result, "cleaned_rows")
    assert (check["expected"], check["actual"], check["status"]) == (3, 2, "fail")


def test_highest_delivery_pairs_with_excluded_in_its_work_root(sample, monkeypatch):
    run, meta, _ = sample
    case = run.parent / "case"
    (case / "input.csv").rename(case / "source.csv")
    (case / "case.md").write_text("inputs: source.csv\n\n## B\nInspect the data.\n", encoding="utf-8")
    meta["artifacts"].extend([
        "other-work/delivery-2/cleaned_data.csv", "other-work/delivery-10/cleaned_data.csv",
        "other-work/excluded.csv", "other-work/clean.py",
    ])
    for revision, rows in [(2, [KEPT[0]]), (10, KEPT), (11, [KEPT[1]])]:
        write_csv(run / f"other-work/delivery-{revision}/cleaned_data.csv", HEADERS, rows)
    write_csv(run / "eda-work/excluded.csv", ("_source_row", "reason"), [(2, "wrong work root")])
    write_csv(run / "other-work/excluded.csv", ("_source_row", "reason"), [(4, "total")])
    (run / "other-work/clean.py").write_text(
        'from pathlib import Path\nPath(__file__).with_name("executed").touch()\n', encoding="utf-8",
    )
    result = invoke(sample, monkeypatch)
    assert result["status"] == "pass"
    assert result["files"]["cleaned"] == "other-work/delivery-10/cleaned_data.csv"
    assert result["files"]["excluded"] == "other-work/excluded.csv"
    assert checks(result, "cleaned_selection")[0]["reason"]
    assert not (run / "other-work/executed").exists()


@pytest.mark.parametrize("has_log", [True, False], ids=["paired-copy", "missing-log"])
def test_identical_cleaned_copies_use_the_matching_exclusion_log(sample, monkeypatch, has_log):
    run, meta, _ = sample
    cleaned, excluded = meta["artifacts"]
    duplicate = "delivery/cleaned_data.csv"
    (run / duplicate).parent.mkdir()
    (run / duplicate).write_bytes((run / cleaned).read_bytes())
    meta["artifacts"].append(duplicate)
    if not has_log:
        (run / excluded).unlink()
        meta["artifacts"].remove(excluded)

    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == ("pass" if has_log else "fail")
    assert result["files"]["excluded"] == (excluded if has_log else None)
    assert not checks(result, "cleaned_selection")


def test_cleaned_with_log_outranks_higher_unpaired_revision(sample, monkeypatch):
    run, meta, _ = sample
    cleaned, excluded = meta["artifacts"]
    unpaired = "delivery-3/cleaned_data.csv"
    write_csv(run / unpaired, HEADERS, [KEPT[0]])
    meta["artifacts"].append(unpaired)

    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == "pass"
    assert result["files"]["cleaned"] == cleaned
    assert result["files"]["excluded"] == excluded
    [selection] = checks(result, "cleaned_selection")
    assert set(selection["expected"]) == {cleaned, unpaired}


@pytest.mark.parametrize(
    ("other_log", "status"),
    [(None, "pass"), ("present", "fail"), ("missing", "fail")],
    ids=["unique-log", "two-logs", "two-recorded-logs"],
)
def test_unpaired_cleaned_uses_only_a_unique_recorded_exclusion_log(sample, monkeypatch, other_log, status):
    run, meta, _ = sample
    cleaned, excluded = meta["artifacts"]
    top_level = "delivery/cleaned_data.csv"
    (run / top_level).parent.mkdir()
    (run / cleaned).rename(run / top_level)
    meta["artifacts"][0] = top_level
    if other_log:
        extra = "other-work/excluded.csv"
        meta["artifacts"].append(extra)
        if other_log == "present":
            write_csv(run / extra, ("_source_row", "reason"), [(4, "total")])

    result = invoke(sample, monkeypatch)
    assert result["audit"]["status"] == status
    assert result["files"]["cleaned"] == top_level
    assert result["files"]["excluded"] == (excluded if other_log is None else None)
