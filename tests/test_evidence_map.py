import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


EVALS = Path(__file__).resolve().parents[1] / "evals"
sys.path.insert(0, str(EVALS))

import cleaning_check
import grade_run
import numeric_check


def load_mapper():
    assert (EVALS / "evidence_map.py").is_file(), "The evidence mapper is missing"
    import evidence_map
    return evidence_map


def write_json(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def summary(run, name="eda_summary.json", **extra):
    write_json(run / name, {
        "datasets": [], "row_counts": [], "metrics": [], "ambiguity_log": [],
        "charts": [], "exclusions": [], **extra,
    })


def transcript(run, *messages):
    (run / "transcript.jsonl").write_text(
        "".join(json.dumps({"speaker": speaker, "text": text}) + "\n"
                for speaker, text in messages), encoding="utf-8",
    )


def baseline(run, metrics, *, dates=(), tolerance=0, **flow_fields):
    flow = {"metrics": metrics, **flow_fields}
    expected = {"absolute_tolerance": tolerance, "flows": {"B": flow}, "dates_in_order": dates}
    selected = numeric_check.summary_path(run)
    numeric = numeric_check.check_run(run, "B", expected, selected, numeric_check.report_path(run, selected))
    assert numeric["missing"] or numeric["unparsed"]
    return numeric, flow


def location(raw, *, file="eda_summary.json", path=None, quote=None, unit=None, period=None,
             conditional=False, **components):
    return {"file": file, "json_path": path, "quote": quote, "raw": raw, "unit": unit,
            "period": period, "conditional": conditional, **components}


def response(target, *locations, found=True):
    return {"id": target["id"], "found": found, "locations": list(locations)}


def update(mapper, run, numeric, flow, locate, *, dates=()):
    targets = mapper.build_targets(numeric, flow)
    payload = {"metrics": [locate(target) for target in targets["metrics"]], "columns": []}
    mapping = mapper.resolve_evidence_map(run, targets, call=lambda prompt: json.dumps(payload))
    return mapper.update_numeric(run, numeric, flow, dates, targets, mapping)


@pytest.mark.parametrize(("raw", "value", "bucket"), [
    ("1,234", "1,234", "matched"),
    ("1,239", "1,239", "mismatched"),
    ("1,234", "1,239", "unverified"),
])
def test_json_path_is_reread_and_compared(tmp_path, raw, value, bucket):
    mapper = load_mapper()
    summary(tmp_path, observations={"remaining stock": value})
    numeric, flow = baseline(tmp_path, [{"name": "Ending inventory", "value": 1234}])
    result = update(mapper, tmp_path, numeric, flow,
                    lambda target: response(target, location(raw, path='$["observations"]["remaining stock"]')))
    [entry] = result[bucket]
    assert entry["name"] == "Ending inventory"
    assert not result["missing"]
    assert json.loads((tmp_path / "numeric_check.json").read_text()) == result


@pytest.mark.parametrize(("quote", "raw", "bucket"), [
    ("Net gain: −1,234", "−1,234", "matched"),
    ("Net gain: −1,235", "−1,235", "unverified"),
    ("Net gain: −1,234", "1,234", "unverified"),
    ("Net gain: −1,234", "234", "unverified"),
])
def test_text_quote_and_numeric_token_are_verified(tmp_path, quote, raw, bucket):
    mapper = load_mapper()
    transcript(tmp_path, ("analyst", "Net gain:\t\n−1,234"))
    numeric, flow = baseline(tmp_path, [{"name": "Stock change", "value": -1234}])
    result = update(mapper, tmp_path, numeric, flow,
                    lambda target: response(target, location(raw, file="transcript.jsonl", quote=quote)))
    assert [entry["name"] for entry in result[bucket]] == ["Stock change"]


def test_found_false_keeps_missing(tmp_path):
    mapper = load_mapper()
    numeric, flow = baseline(tmp_path, [{"name": "Ending inventory", "value": 20}])
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(target, found=False))
    assert result["missing"] == numeric["missing"]
    assert result["unverified"] == []


def test_delivery_name_variant_goes_through_mapper(tmp_path):
    mapper = load_mapper()
    (tmp_path / "delivery").mkdir()
    write_json(tmp_path / "meta.json", {"condition": "skill"})
    write_json(tmp_path / "delivery/results.json", {
        "metrics": [{"name": "widget count", "value": 17, "unit": "count"}],
    })
    claim = "widget count: 17 count"
    transcript(tmp_path, ("analyst", claim))
    numeric, flow = baseline(tmp_path, [{"name": "total widget count", "value": 17, "unit": "count"}])

    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location("17", file="transcript.jsonl", quote=claim, unit="count")))

    [entry] = result["matched"]
    assert entry["source"] == "evidence_map"


@pytest.mark.parametrize(("raw", "bucket"), [
    ("84.48%", "matched"), ("84%", "mismatched"), (84.48, "mismatched"),
])
def test_mapped_non_schema_results_precede_transcript(tmp_path, raw, bucket):
    mapper = load_mapper()
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    write_json(delivery / "results.json", {"seat_use": {"value": raw, "unit": "%"}})
    claim = "Seat use: 30%"
    transcript(tmp_path, ("analyst", claim))
    numeric, flow = baseline(tmp_path, [{"name": "Utilization", "value": 84.4827, "unit": "%"}])

    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location("30%", file="transcript.jsonl", quote=claim),
        location(raw, file="delivery/results.json", path="/seat_use/value")))

    [entry] = result[bucket]
    assert entry["source"] == "evidence_map"
    assert entry["actual"]["value"] == (84 if raw == "84%" else 84.48)


@pytest.mark.parametrize("file", ["transcript.jsonl", "delivery/report.html"])
def test_mapped_quotation_uses_display_precision(tmp_path, file):
    mapper = load_mapper()
    claim = "Seat use: 84.48%"
    if file == "transcript.jsonl":
        transcript(tmp_path, ("analyst", claim))
    else:
        report = tmp_path / file
        report.parent.mkdir()
        report.write_text(f"<p>{claim}</p>")
    numeric, flow = baseline(tmp_path, [{"name": "Utilization", "value": 84.4827, "unit": "%"}])

    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location("84.48%", file=file, quote=claim)))

    assert result["matched"][0]["actual"]["value"] == 84.48


@pytest.mark.parametrize(("reference_unit", "unit", "bucket"), [
    ("초/건", "초", "matched"), ("초/건", "초/t", "mismatched"), ("kg/event", "초", "mismatched"),
])
def test_mapped_average_compares_count_notation_and_dimensions(tmp_path, reference_unit, unit, bucket):
    mapper = load_mapper()
    metric = {"name": "평균 작업시간", "value": 6, "numerator": 18, "denominator": 3, "unit": reference_unit}
    summary(tmp_path, observations={**metric, "name": "Cycle time", "unit": unit})
    numeric, flow = baseline(tmp_path, [metric])
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location(6, path="/observations/value", unit=unit)))

    [entry] = result[bucket]
    if bucket == "mismatched":
        assert entry["differences"] == {"unit": {"expected": reference_unit, "actual": unit}}


@pytest.mark.parametrize(("left", "right", "numerator", "value", "differences"), [
    pytest.param(1, None, None, 17, set(), id="null-components"),
    pytest.param(1, 1, None, 17, set(), id="unit-denominator-null-numerator"),
    pytest.param(1, None, 17, 17, set(), id="matching-numerator"),
    pytest.param(1, None, None, 18, {"value"}, id="wrong-value"),
    pytest.param(1, None, 16, 17, {"numerator"}, id="wrong-numerator"),
    pytest.param(22, None, None, 17, {"denominator", "numerator"}, id="average-null-components"),
    pytest.param(None, 24, 17, 17, set(), id="expected-null-denominator"),
])
def test_mapped_unit_denominator_compares_value_and_present_components(tmp_path, left, right,
                                                                      numerator, value, differences):
    mapper = load_mapper()
    metric = {"name": "Measurement", "value": 17, "numerator": 17, "denominator": left, "unit": "kg"}
    summary(tmp_path, observations={**metric, "name": "Reported quantity", "definition": "Mean of measurements",
                                    "value": value, "numerator": numerator, "denominator": right})
    numeric, flow = baseline(tmp_path, [metric])
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location(value, path="/observations/value", unit="kg")))

    [entry] = result["mismatched" if differences else "matched"]
    assert entry["source"] == "evidence_map"
    assert set(entry.get("differences", ())) == differences


def test_mapped_unit_denominator_compares_independently_of_source_ref_text(tmp_path):
    mapper = load_mapper()
    metric = {"name": "Widgets", "value": 17, "numerator": 17, "denominator": 1,
              "unit": "건", "source_refs": ["2", "3"]}
    summary(tmp_path, observations={**metric, "name": "Reported quantity", "denominator": None,
                                    "source_refs": ["8", "9"]})
    numeric, flow = baseline(tmp_path, [metric])
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location(17, path="/observations/value", unit="건")))

    [entry] = result["matched"]
    assert entry["source"] == "evidence_map"


def test_percent_in_report_uses_existing_ratio_conversion(tmp_path):
    mapper = load_mapper()
    summary(tmp_path)
    (tmp_path / "report.html").write_text("<table><tr><td>Losses</td><td>11.11%</td></tr></table>")
    numeric, flow = baseline(tmp_path, [{"name": "Waste share", "value": 0.1111, "unit": "ratio"}],
                             tolerance=0.00001)
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location("11.11%", file="report.html", quote="Losses 11.11%")))
    [entry] = result["matched"]
    assert entry["actual"]["value"] == 11.11
    assert entry["matched_via"] == "percent_to_ratio"


def test_dates_cannot_be_swapped_or_relabelled(tmp_path):
    mapper = load_mapper()
    days = ["2026-01-01", "2026-01-02"]
    summary(tmp_path, observations=[{"date": days[0], "value": 20}, {"date": days[1], "value": 10}])
    numeric, flow = baseline(tmp_path, [
        {"name": "Ending inventory", "date": days[0], "value": 10},
        {"name": "Ending inventory", "date": days[1], "value": 20},
    ], dates=days)

    def locate(target):
        day = days.index(target["date"])
        return response(target, location([10, 20][day], path=f"/observations/{1 - day}/value", period=days[day]))

    result = update(mapper, tmp_path, numeric, flow, locate, dates=days)
    assert not result["matched"]
    assert sorted(entry["date"] for entry in result["unverified"]) == days


def test_mapped_components_and_condition_go_through_tuple_comparison(tmp_path):
    mapper = load_mapper()
    summary(tmp_path, observations={"value": 4, "numerator": 8, "denominator": 2, "condition": "if provisional"})
    numeric, flow = baseline(tmp_path, [{"name": "Ending inventory", "value": 4,
                                         "numerator": 12, "denominator": 3, "conditional": False}])
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(target, location(
        4, path="$.observations.value", numerator=12, denominator=3, conditional=False)))
    [entry] = result["mismatched"]
    assert entry["actual"] == {"value": 4, "numerator": 8, "denominator": 2, "conditional": True}
    assert set(entry["differences"]) == {"numerator", "denominator", "conditional"}


def test_mapped_series_uses_sign_agnostic_check(tmp_path):
    mapper = load_mapper()
    summary(tmp_path, observations=[3, 4])
    numeric, flow = baseline(tmp_path, [{"name": "Stock change", "values": [-3, -4]}],
                             sign_agnostic_metrics=["Stock change"])
    result = update(mapper, tmp_path, numeric, flow,
                    lambda target: response(target, location([3, 4], path="/observations")))
    assert result["matched"][0]["matched_via"].endswith("+sign_reversed")


@pytest.mark.parametrize(("display", "bucket"), [("11.1%", "matched"), ("11.2%", "mismatched")])
def test_mapped_summary_and_report_still_check_conflicts(tmp_path, display, bucket):
    mapper = load_mapper()
    summary(tmp_path, observations={"value": 0.1111, "unit": "ratio"})
    (tmp_path / "report.html").write_text(f"<p>Losses {display}</p>")
    numeric, flow = baseline(tmp_path, [{"name": "Waste share", "value": 0.1111, "unit": "ratio"}])
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location(0.1111, path="/observations/value"),
        location(display, file="report.html", quote=f"Losses {display}")))
    [entry] = result[bucket]
    if bucket == "mismatched":
        assert "report_conflict" in entry["differences"]


def test_count_notation_still_checks_report_conflicts(tmp_path):
    mapper = load_mapper()
    summary(tmp_path, observations={"name": "Cycle time", "value": 6, "unit": "s"})
    claim = "Cycle time: 7 s/event"
    (tmp_path / "report.html").write_text(f"<p>{claim}</p>")
    numeric, flow = baseline(tmp_path, [{"name": "Average delay", "value": 6, "unit": "s/event"}])
    result = update(mapper, tmp_path, numeric, flow, lambda target: response(
        target, location(6, path="/observations/value", unit="s"),
        location("7", file="report.html", quote=claim, unit="s/event")))

    [entry] = result["mismatched"]
    assert "report_conflict" in entry["differences"]


def test_prompt_only_exposes_target_metadata_and_selected_artifacts(tmp_path):
    mapper = load_mapper()
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    summary(tmp_path, name="delivery/results.json", observations={"inventory": 28})
    (delivery / "report.html").write_text("<p>Shown in the HTML</p>" + "Z" * 17000 + "END-OF-HTML")
    transcript(tmp_path, ("analyst", "Older message"), ("user", "User message"),
               ("analyst", "Last message"))
    cleaned = delivery / "cleaned_items.csv"
    cleaned.write_text("item,availability\n" + "".join(f"row-{i},yes\n" for i in range(1, 7)))
    write_json(tmp_path / "meta.json", {"artifacts": ["delivery/cleaned_items.csv"]})
    numeric, flow = baseline(tmp_path, [{"name": "Ending inventory", "definition": "Stock remaining",
                                         "value": 987123, "numerator": 987456, "denominator": 987789}])
    targets = mapper.build_targets(numeric, flow)
    prompt = mapper.build_prompt(tmp_path, targets)
    for visible in ("Ending inventory", "Stock remaining", "Shown in the HTML", "Last message",
                    "delivery/results.json", '"inventory": 28', "item", "availability", "row-5"):
        assert visible in prompt
    for hidden in ("987123", "987456", "987789", "Older message", "User message", "row-6", "END-OF-HTML"):
        assert hidden not in prompt


def test_cached_result_is_reused_and_remap_replaces_it(tmp_path):
    mapper = load_mapper()
    numeric, flow = baseline(tmp_path, [{"name": "Ending inventory", "value": 20}])
    targets = mapper.build_targets(numeric, flow)
    [target] = targets["metrics"]
    old = {"metrics": [response(target, found=False)], "columns": []}
    write_json(tmp_path / "evidence_map.json", old)
    assert mapper.resolve_evidence_map(tmp_path, targets, call=lambda prompt: pytest.fail("unexpected call")) == old
    new = {"metrics": [response(target, location("20", quote="Remaining: 20", file="transcript.jsonl"))],
           "columns": []}
    assert mapper.resolve_evidence_map(tmp_path, targets, remap=True, call=lambda prompt: json.dumps(new)) == new
    assert json.loads((tmp_path / "evidence_map.json").read_text()) == new


def test_mapper_retries_twice_and_records_failure_without_changing_buckets(tmp_path):
    mapper = load_mapper()
    numeric, flow = baseline(tmp_path, [{"name": "Ending inventory", "value": 20}])
    targets = mapper.build_targets(numeric, flow)
    prompts = []

    def broken_json(prompt):
        prompts.append(prompt)
        return "{"

    mapping = mapper.resolve_evidence_map(tmp_path, targets, call=broken_json)
    result = mapper.update_numeric(tmp_path, numeric, flow, (), targets, mapping)
    assert len(prompts) == 2
    assert result["missing"] == numeric["missing"]
    assert result["unverified"] == []
    assert "JSON" in result["evidence_map_error"]
    assert json.loads((tmp_path / "evidence_map.json").read_text())["reason"] == result["evidence_map_error"]


@pytest.mark.parametrize(("column", "key_column", "expected_value", "expected_status", "tuple_status"), [
    ("Available", "Snapshot", 12, "pass", "pass"),
    ("Available", "Snapshot", 13, "fail", "pass"),
    ("available", "snapshot", 12, "review", "review"),
])
def test_cleaning_rechecks_only_with_exact_headers(tmp_path, monkeypatch,
                                                  column, key_column, expected_value, expected_status, tuple_status):
    mapper = load_mapper()
    run, case = tmp_path / "run", tmp_path / "case"
    (run / "delivery").mkdir(parents=True)
    case.mkdir()
    (case / "input.csv").write_text("date,qty\n2026-01-01,12\n")
    (run / "delivery/cleaned_data.csv").write_text("_source_row,Snapshot,Available,Raw count\n2,2026-01-01,12,13\n")
    write_json(run / "meta.json", {"case_dir": "case", "artifacts": ["delivery/cleaned_data.csv"]})
    address = {"sheet": "", "row": "2"}
    write_json(case / "cleaning_expected.json", {
        "audit_args": ["--header=yes"],
        "values": [{"source": address, "column_aliases": ["available", "Stock total"], "kind": "number",
                    "any_of": [expected_value]}],
        "tuples": [{"source": address, "key_aliases": ["snapshot"], "value_aliases": ["available"],
                    "key_kind": "date", "value_kind": "number", "expected": [["2026-01-01", 12]]}],
    })
    monkeypatch.setattr(cleaning_check, "ROOT", tmp_path)
    original = cleaning_check.check_run(run)
    assert [row["status"] for row in original["checks"] if row["name"] in {"values", "tuples"}] == [
        "review", "review",
    ]

    def propose(prompt):
        assert "Stock total" in prompt and "Snapshot" in prompt
        return json.dumps({"metrics": [], "columns": [
            {"id": "values:0", "column": column, "key_column": None, "value_column": None},
            {"id": "tuples:0", "column": None, "key_column": key_column, "value_column": column},
        ]})

    result = cleaning_check.check_run(run, map_missing=True, mapper_call=propose)
    cached = cleaning_check.check_run(run, map_missing=True, mapper_call=lambda prompt: pytest.fail("unexpected call"))
    assert result == cached == cleaning_check.check_run(run)
    assert [row["status"] for row in result["checks"] if row["name"] in {"values", "tuples"}] == [
        expected_status, tuple_status,
    ]


@pytest.mark.parametrize(("cache", "column", "status"), [
    (cache, column, status)
    for cache in ("none", "complete", "partial")
    for column, status in (("Converted", "pass"), ("Raw", "fail"), (None, "fail"),
                           ("Other", "fail"), ("converted", "fail"))
] + [("malformed", "Converted", "pass"), ("error", "Converted", "pass")])
def test_cleaning_remaps_failed_alias_value(tmp_path, monkeypatch, column, status, cache):
    load_mapper()
    run, case = tmp_path / "run", tmp_path / "case"
    (run / "delivery").mkdir(parents=True)
    case.mkdir()
    (case / "input.csv").write_text("qty\n42\n")
    (run / "delivery/cleaned_data.csv").write_text("_source_row,Raw,Converted,Other\n2,42,1200,24\n")
    meta = {"case_dir": "case", "flow": "B", "artifacts": ["delivery/cleaned_data.csv"]}
    write_json(run / "meta.json", meta)
    address = {"sheet": "", "row": "2"}
    write_json(case / "cleaning_expected.json", {
        "audit_args": ["--header=yes"],
        "values": [{"source": address, "column_aliases": ["Raw"], "kind": "number", "any_of": [1200]}],
    })
    monkeypatch.setattr(cleaning_check, "ROOT", tmp_path)
    mapping = {"metrics": [], "columns": [{"id": "values:0", "column": column}]}
    existing = {"metrics": [{"id": "metric:0", "found": False, "locations": []}], "columns": []}
    if cache == "malformed":
        existing["columns"] = [{"id": "values:0"}]
    if cache == "error":
        existing = {"status": "error", "reason": "Temporary failure"}
    if cache != "none":
        write_json(run / "evidence_map.json", mapping if cache == "complete" else existing)
    calls = []

    def propose(prompt):
        before, _, _ = prompt.partition("Analyst excerpts")
        calls.append(json.loads(before.split("\n\nTargets\n", 1)[1]))
        return json.dumps(mapping)

    result = cleaning_check.check_run(run, map_missing=cache != "complete", mapper_call=propose)
    [entry] = [row for row in result["checks"] if row["name"] == "values"]
    assert entry["status"] == status
    target = {"id": "values:0", "source": address, "column_aliases": ["Raw"],
              "reason": "alias_value_mismatch", "alias_column": "Raw"}
    assert cleaning_check.collect_targets(run, case, "B", meta) == [target]
    assert calls == ([] if cache == "complete" else [{"metrics": [], "columns": [target]}])
    if cache in {"partial", "malformed"}:
        assert json.loads((run / "evidence_map.json").read_text())["metrics"] == existing["metrics"]
    if column in {"Converted", "Other"}:
        assert entry["alias_column"] == "Raw"
        assert entry["mapped_column"] == column
        assert entry["actual"] == ("1200" if status == "pass" else "24")
    else:
        assert entry["actual"] == "42"


def test_grade_updates_numeric_check_before_calling_grader(tmp_path, monkeypatch):
    summary(tmp_path, observations={"value": 20})
    transcript(tmp_path, ("analyst", "Analysis complete."))
    raw = tmp_path / "raw"
    raw.mkdir()
    write_json(tmp_path / "meta.json", {})
    (raw / "1-analyst.jsonl").write_text('{"type":"thread.started"}\n')
    expected = {"absolute_tolerance": 0, "flows": {"B": {"metrics": [{"name": "Ending inventory", "value": 20}]}}}
    monkeypatch.setattr(grade_run, "load_expected", lambda run: (tmp_path, "B", expected))
    from contextlib import nullcontext
    monkeypatch.setattr(grade_run, "grader_home", lambda run: nullcontext({}))

    def grader(args, cwd, log, prompt, **kwargs):
        numeric = json.loads((tmp_path / "numeric_check.json").read_text())
        assert numeric["matched"][0]["name"] == "Ending inventory"
        assert "numeric_check.json" in prompt
        return SimpleNamespace(text=json.dumps({"critical_failures": [], "quality_scores": {}, "evidence": [],
                                                "overall": "fail", "numbers_verdict": "fail"}))

    monkeypatch.setattr(grade_run, "call_codex", grader)
    grade_run.grade_run(tmp_path, False, mapper_call=lambda prompt: json.dumps({
        "metrics": [{"id": "metric:0", "found": True, "locations": [location(20, path="/observations/value")]}],
        "columns": [],
    }))
    assert json.loads((tmp_path / "grade.json").read_text())["numbers_verdict"] == "pass"
