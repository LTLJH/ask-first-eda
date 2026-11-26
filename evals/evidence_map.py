"""Find analyst evidence for unresolved checks and verify it before comparison."""

from collections import defaultdict
import csv
from decimal import Decimal
from itertools import islice
import json
import math
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory, mkdtemp

from numeric_check import (
    CLAUSE_BREAK, CONDITIONAL, DATE_RANGE, DATE_SCOPE, DISPLAY_QUANTITY, FORMULA, NUMBER, SHORT_DAY, UNIT_SUFFIX,
    DateRange, allows_undated, comparable_fields, compare_metrics, delivery_results_path, display_decimals,
    last_analyst_text, metric_date, parse_number, parse_period, read_json, report_path, reports_text, summary_path,
    transcript_metrics, unit_parts,
)
from run_case import ROOT, call_codex, fresh_codex, json_text, make_role_home, role

SCRIPTS = str(ROOT / "skills/ask-first-eda/scripts")
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)
from eda_io import atomic_write


MAP_FILE = "evidence_map.json"
TRANSCRIPT = "transcript.jsonl"
PENDING_BUCKETS = ("missing", "unparsed")
TARGET_FIELDS = ("name", "definition", "unit", "date", "month", "period")
RAW_NUMBER = NUMBER.replace("[+-]", "[+−-]")
QUOTED_QUANTITY = re.compile(
    rf"(?<![a-zA-Z0-9_.,+−-])({RAW_NUMBER})(?:\s*(%)(?!\w))?(?![\d_]|%(?!\w)|[.,]\d|[eE][+−-]?\d|-\d)"
)
JSON_NUMBER = re.compile(r"-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?")
JSON_PATH_STEP = re.compile(r'\.([^.[\]\s]+)|\[(0|[1-9]\d*|"(?:[^"\\]|\\.)*")\]')


def pending_metrics(numeric, expected_flow):
    pending = [(bucket, item) for bucket in PENDING_BUCKETS for item in numeric.get(bucket, ())
               if item["required"]]
    for index, reference in enumerate(expected_flow["metrics"]):
        label = metric_date(reference)[0]
        for i, (bucket, item) in enumerate(pending):
            if (item["name"] == reference["name"] and item.get("date") == label
                    and item["expected"] == comparable_fields(reference)):
                yield f"metric:{index}", reference, bucket, item
                pending.pop(i)
                break


def build_targets(numeric, expected_flow, cleaning=None):
    metrics = []
    if not numeric.get("summary_error"):
        for identifier, reference, _, _ in pending_metrics(numeric, expected_flow):
            target = {field: reference[field] for field in TARGET_FIELDS if isinstance(reference.get(field), str)}
            if "month" in target:
                target.setdefault("period", target.pop("month"))
            metrics.append({"id": identifier, **target})
    columns = []
    for item in cleaning or ():
        hints = {field: item[field] for field in ("column_aliases", "key_aliases", "value_aliases") if field in item}
        if item.get("reason") == "alias_value_mismatch":
            hints.update(reason="alias_value_mismatch", alias_column=item["alias_column"])
        columns.append({"id": item["id"], "source": {field: item["source"][field] for field in ("sheet", "row")},
                        **hints})
    return {"metrics": metrics, "columns": columns}


def analyst_sources(run, *, for_prompt=False):
    summary = summary_path(run)
    results = delivery_results_path(run)
    report = report_path(run, summary)
    sources = {}
    for path, kind in ((summary, "json"), (results if results != summary else None, "results_json"),
                       (report, "html"), (run / TRANSCRIPT, "message")):
        if path is None or not path.is_file() or path.resolve() != path:
            continue
        file = path.relative_to(run).as_posix()
        if kind in ("json", "results_json"):
            text = path.read_text(encoding="utf-8", errors="replace")
        elif kind == "html":
            text = reports_text(run, path, for_grader=for_prompt)
            if for_prompt:
                text = text.partition("\n")[2]
        else:
            text = last_analyst_text(run, strict=False)
        sources[file] = (kind, text)
    return sources


def cleaned_excerpt(run):
    meta = run / "meta.json"
    if not meta.is_file() or meta.is_symlink():
        return None
    if not (artifacts := read_json(meta).get("artifacts")):
        return None
    from cleaning_check import find_artifacts

    cleaned, _, _ = find_artifacts(run, artifacts)
    if cleaned is None:
        return None
    with (run / cleaned).open(encoding="utf-8-sig", errors="replace", newline="") as stream:
        rows = list(islice(csv.reader(stream), 6))
    return {"file": cleaned.as_posix(), "rows": rows}


def build_prompt(run, targets):
    excerpts = [f"## {file}\n{text}" for file, (_, text) in analyst_sources(run.resolve(), for_prompt=True).items()]
    if cleaned := cleaned_excerpt(run.resolve()):
        excerpts.append(f"## {cleaned['file']}\n" + json_text(cleaned["rows"]))
    instructions = role("evidence-mapper")
    if any(item.get("reason") == "alias_value_mismatch" for item in targets["columns"]):
        instructions += ("\n\nFor alias_value_mismatch, the alias_column was already checked and did not match. "
                         "Identify a different header only if the excerpts support it as the cleaned or converted "
                         "field for this target. Otherwise leave the column null.")
    return "\n\n".join((instructions, "Targets\n" + json_text(targets),
                       "Analyst excerpts", *excerpts))


def parse_mapping(text):
    mapping = json.loads(text)
    json.dumps(mapping, allow_nan=False, ensure_ascii=False).encode("utf-8")
    if not isinstance(mapping, dict):
        raise ValueError("Expected a mapping object")
    if mapping.get("status") == "error" and isinstance(mapping.get("reason"), str):
        return {"status": "error", "reason": mapping["reason"]}
    for group in ("metrics", "columns"):
        entries = mapping.get(group)
        if (not isinstance(entries, list) or any(
                not isinstance(entry, dict) or not isinstance(entry.get("id"), str)
                for entry in entries)):
            raise ValueError(f"Expected a list of {group} mappings with string IDs")
        if len({entry["id"] for entry in entries}) != len(entries):
            raise ValueError(f"Repeated ID in {group}")
    if any(type(entry.get("found")) is not bool or not isinstance(entry.get("locations"), list)
           for entry in mapping["metrics"]):
        raise ValueError("Expected a found flag and locations list for each metric")
    return mapping


def load_mapping(run):
    path = run / MAP_FILE
    if not path.exists() and not path.is_symlink():
        return None
    try:
        if path.is_symlink():
            raise ValueError("Mapping must be a regular file")
        return parse_mapping(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, RecursionError):
        return {"status": "error", "reason": "Saved evidence map could not be read as mapping JSON."}


def call_mapper(run, prompt):
    raw = run / "raw"
    raw.mkdir(mode=0o700, exist_ok=True)
    logs = Path(mkdtemp(prefix="evidence-map-", dir=raw))
    with TemporaryDirectory(prefix="eda-mapper-") as directory:
        scratch = Path(directory)
        workspace = scratch / "workspace"
        workspace.mkdir()
        env = make_role_home(scratch, "evidence-mapper")
        args = fresh_codex("gpt-6.2-sol", "medium", "read-only", workspace)
        args.extend(["--ephemeral", "--disable", "shell_tool", "--disable", "unified_exec",
                     "--disable", "apps", "-c", 'web_search="disabled"', "-c", 'approval_policy="never"'])
        return call_codex(args, workspace, logs / "mapper.jsonl", prompt,
                          prompt_on_stdin=True, allow_empty=True, env_extra=env).text


def resolve_evidence_map(run, targets, *, remap=False, call=None, fill_missing=False):
    cached = None if remap else load_mapping(run)
    if fill_missing and cached is not None and cached.get("status") == "error":
        cached = None
    if cached is not None:
        if not fill_missing:
            return cached
        known = {"metrics": {item["id"] for item in cached["metrics"]}, "columns": set()}
        for item in cached["columns"]:
            identifier = item["id"]
            fields = {"column"} if identifier.startswith("values:") else {"key_column", "value_column"}
            if fields <= item.keys():
                known["columns"].add(identifier)
        targets = {group: [item for item in entries if item["id"] not in known[group]]
                   for group, entries in targets.items()}
    if not any(targets.values()):
        return cached

    try:
        prompt = build_prompt(run, targets)
        for attempt in range(2):
            reply = call(prompt) if call is not None else call_mapper(run, prompt)
            try:
                mapping = parse_mapping(reply)
                if mapping.get("status") == "error":
                    raise ValueError("Expected model mapping")
                break
            except (TypeError, ValueError, RecursionError):
                if attempt == 1:
                    mapping = {"status": "error", "reason": "Invalid evidence mapper JSON after two attempts."}
                else:
                    prompt += "\n\nReturn only a valid JSON object with metrics and columns arrays."
    except (OSError, RuntimeError, ValueError, RecursionError) as error:
        mapping = {"status": "error", "reason": f"Evidence mapper could not run ({type(error).__name__})."}

    if cached is not None:
        if mapping.get("status") == "error":
            return {**cached, **mapping}
        for group, entries in targets.items():
            requested = {item["id"] for item in entries}
            updates = [item for item in mapping[group] if item["id"] in requested]
            updated = {item["id"] for item in updates}
            mapping[group] = [item for item in cached[group] if item["id"] not in updated] + updates

    # Replace the cache in one step so readers never see an incomplete reply.
    atomic_write(run / MAP_FILE, (json_text(mapping) + "\n").encode("utf-8"))
    return mapping


def json_path_parts(path):
    if path.startswith("/"):
        if re.search(r"~(?![01])", path):
            raise ValueError("Invalid JSON Pointer escape")
        return [part.replace("~1", "/").replace("~0", "~") for part in path[1:].split("/")]
    if not path.startswith("$"):
        raise ValueError("Expected a JSON path")
    parts = []
    offset = 1
    while offset < len(path):
        match = JSON_PATH_STEP.match(path, offset)
        if match is None:
            raise ValueError("Unsupported JSON path")
        key, bracket = match.groups()
        parts.append(key if key is not None else str(json.loads(bracket)))
        offset = match.end()
    return parts


def same_raw(source, raw):
    if isinstance(source, list) and isinstance(raw, list):
        return len(source) == len(raw) and all(same_raw(left, right) for left, right in zip(source, raw))
    if type(source) in (int, Decimal) and type(raw) in (int, float, str):
        token = str(raw)
        return bool(JSON_NUMBER.fullmatch(token)) and source == Decimal(token)
    return type(source) is type(raw) and source == raw


def quantity(raw):
    if isinstance(raw, list):
        items = [quantity(item) for item in raw]
        units = {percent for _, percent, _ in items}
        if len(units) > 1:
            raise ValueError("Expected a single representation for a numeric series")
        return [value for value, _, _ in items], True in units, None
    match = DISPLAY_QUANTITY.fullmatch(str(raw).strip())
    if match is None:
        raise ValueError("Expected a numeric token")
    token, percent = match.groups()
    value = parse_number(token.replace("−", "-"))
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Expected a finite quantity")
    return value, bool(percent), display_decimals(token)


def json_claim(data, path, location):
    parts = json_path_parts(path)
    node, contexts = data, []
    for i, part in enumerate(parts):
        if isinstance(node, dict):
            contexts.append((node, parts[i:]))
            node = node[part]
        elif isinstance(node, list) and re.fullmatch(r"0|[1-9]\d*", part):
            node = node[int(part)]
        else:
            raise ValueError("JSON path does not exist")
    if not same_raw(node, location.get("raw")):
        raise ValueError("JSON path does not match raw")
    value, percent, places = quantity(node)
    dated_keys = [part for part in parts if parse_period(part) or SHORT_DAY.fullmatch(part)]
    label = next((part for part in reversed(parts)
                  if part not in ("value", "values", *dated_keys) and not part.isdigit()), "")
    metric = {"name": label, "value": value}
    if isinstance(node, str):
        metric["_display_decimals"] = places
    for context, _ in contexts:
        for field, content in context.items():
            if (not field.startswith("_") and isinstance(content, str)
                    and field not in ("name", "value", "values", "numerator", "denominator",
                                      "conditional", "condition")):
                metric[field] = content
        if isinstance(context.get("name"), str):
            metric["name"] = context["name"]
        if type(context.get("conditional")) is bool or "condition" in context:
            metric["conditional"] = comparable_fields(context)["conditional"]
            metric.pop("condition", None)
            if "condition" in context:
                metric["condition"] = context["condition"]
    if dated_keys:
        metric["name"] = " ".join((metric["name"], *dated_keys))
    if "conditional" not in metric:
        metric["conditional"] = any(
            CONDITIONAL.search(metric.get(field, "")) for field in ("name", "definition")
        )
        if location["conditional"] and not metric["conditional"]:
            raise ValueError("Condition is absent from the structured evidence")

    if contexts:
        context, tail = contexts[-1]
        periods = {content for content in context.values() if isinstance(content, str) and parse_period(content)}
        period = location.get("period")
        if isinstance(period, str) and periods == {period}:
            metric.setdefault("period", period)
        unit = location.get("unit")
        if isinstance(unit, str) and unit.strip() and (
            any(unit == content for content in context.values())
            or any(re.search(rf"(?<![^\W_]){re.escape(unit)}(?![^\W_])", part) for part in parts)
        ):
            metric.setdefault("unit", unit)
        for field, component in comparable_fields(context).items():
            if field not in ("numerator", "denominator"):
                continue
            if isinstance(component, list) and len(tail) == 2 and tail[0] in ("value", "values"):
                if not tail[1].isdigit() or int(tail[1]) >= len(component):
                    continue
                component = component[int(tail[1])]
            if component is None:
                metric[field] = None
            else:
                try:
                    metric[field] = quantity(component)[0]
                except ValueError:
                    continue
    if (period := metric.get("period")) and "date" not in metric and (parse_period(period) or SHORT_DAY.fullmatch(period)):
        metric["date"] = period
    if percent:
        metric["unit"] = "%"
    return metric, tuple(parts)


def normalize_spaces(text):
    return " ".join(text.split())


def enclosing_clause(text, offset):
    """Resolve an offset in whitespace-normalized text to its source clause."""
    for line in text.splitlines():
        line = normalize_spaces(line)
        if not line:
            continue
        if offset < len(line):
            start = 0
            for separator in CLAUSE_BREAK.finditer(line):
                if separator.start() >= offset:
                    return line[start:separator.start()], offset - start
                start = separator.end()
            return line[start:], offset - start
        offset -= len(line) + 1
    return "", 0


def quoted_claim(text, location, kind):
    quote, raw = location.get("quote"), location.get("raw")
    if not isinstance(quote, str) or type(raw) not in (str, int, float):
        raise ValueError("A quotation requires a raw numeric token")
    source, quote, raw = normalize_spaces(text), normalize_spaces(quote), normalize_spaces(str(raw))
    if not quote:
        raise ValueError("Quotation not found")
    # Dates provide context and cannot be the numeric claim itself.
    date_spans = [match.span() for pattern in (DATE_RANGE, DATE_SCOPE, SHORT_DAY) for match in pattern.finditer(quote)]
    numbers = [match for match in QUOTED_QUANTITY.finditer(quote)
               if not any(start <= match.start() < end for start, end in date_spans)]
    offset = source.find(quote)
    while offset >= 0:
        tokens = ((match, actual) for match in numbers if raw in (match[0], match[1])
                  and (actual := QUOTED_QUANTITY.match(source, offset + match.start())) and actual[1] == match[1])
        if located := next(tokens, None):
            break
        offset = source.find(quote, offset + 1)
    else:
        raise ValueError("Raw number not found in quoted evidence")
    token, actual = located
    value, percent, places = quantity(actual[0])
    context, at = enclosing_clause(text, actual.start())
    context_number = QUOTED_QUANTITY.match(context, at)
    context_label = context[:at] if context_number else ""
    label = (context_label.strip() or quote[:token.start()]).strip(" :|=\x60*")
    definition = context if quote in context else f"{quote} {context}".strip()
    conditional = bool(CONDITIONAL.search(definition))
    if not conditional and location["conditional"]:
        raise ValueError("Condition is absent from the quotation")
    metric = {"name": label, "definition": definition, "value": value, "conditional": conditional}
    if percent:
        metric["unit"] = "%"
    else:
        tail = context[context_number.end():] if context_number else quote[token.end():]
        suffix = UNIT_SUFFIX.match(tail)
        if suffix and any(unit_parts(suffix[1])):
            metric["unit"] = suffix[1]
        elif isinstance(unit := location.get("unit"), str) and unit.strip() and unit in definition:
            metric["unit"] = unit
    if isinstance(period := location.get("period"), str) and period in quote:
        if parse_period(period) or SHORT_DAY.fullmatch(period):
            # The quote remains available to the date check for contradictory dates.
            metric["date"] = period
        else:
            metric["period"] = period
    for number in numbers:
        formula = FORMULA.match(quote[number.start():])
        if formula and number.start() + formula.start(3) == token.start():
            metric.update(zip(("numerator", "denominator"), map(parse_number, formula.groups()[:2])))
            break
    for field in ("numerator", "denominator"):
        if component := re.search(rf"\b{field}\s*[:=]\s*({RAW_NUMBER})", quote, re.IGNORECASE):
            metric[field] = quantity(component[1])[0]
        elif field not in metric and type(hint := location.get(field)) in (str, int, float):
            if any(other != token and str(hint) == other[1] for other in numbers):
                metric[field] = quantity(hint)[0]
    if places or kind == "html":
        metric["_display_decimals"] = places
    return metric, actual.start()


def verify_location(sources, location):
    if not isinstance(location, dict) or type(location.get("conditional")) is not bool:
        return None
    file = location.get("file")
    if not isinstance(file, str) or file not in sources:
        return None
    kind, text = sources[file]
    path = location.get("json_path")
    try:
        if kind in ("json", "results_json"):
            if not isinstance(path, str) or location.get("quote") is not None:
                return None
            metric, position = json_claim(json.loads(text, parse_float=Decimal), path, location)
        else:
            if path is not None:
                return None
            metric, position = quoted_claim(text, location, kind)
    except (ValueError, TypeError, IndexError, KeyError, RecursionError, ArithmeticError):
        return None
    return (file, position), (kind, metric)


def mapped_result(reference, claims, report, tolerance, dates, allow_undated, sign_agnostic):
    report_name, report_text = report
    for kind in ("json", "results_json", "message", "html"):
        rows = [metric for source, metric in claims if source == kind]
        if not rows:
            continue
        report_metrics = None
        if report_name and kind != "html":
            report_rows = [metric for source, metric in claims if source == "html"]
            report_rows.extend(transcript_metrics(report_text, [reference, *rows], is_report=True))

            def report_metrics():
                return report_name, report_rows

        compared = compare_metrics(
            [reference], [], rows, tolerance, dates, named_evidence=kind in ("message", "html"),
            report_source=report_name if kind == "html" else None, report_metrics=report_metrics,
            sign_agnostic_metrics=sign_agnostic, allow_undated=allow_undated,
            evidence_source="evidence_map", mapped_evidence=True,
        )
        for bucket in ("matched", "mismatched", "unverified"):
            if compared[bucket]:
                return bucket, compared[bucket][0]
    return None


def update_numeric(run, numeric, expected_flow, dates, targets, mapping):
    if not mapping:
        return numeric
    result = dict(numeric)
    if mapping.get("status") == "error":
        result["evidence_map_error"] = mapping["reason"]
    elif targets["metrics"]:
        sources = analyst_sources(run.resolve())
        by_id = {entry["id"]: entry for entry in mapping["metrics"] if entry["found"]}
        verified = {}
        owners = defaultdict(set)
        for target in targets["metrics"]:
            identifier = target["id"]
            if identifier not in by_id:
                continue
            locations = by_id[identifier]["locations"]
            verified[identifier] = dict(item for location in locations if (item := verify_location(sources, location)))
            for position in verified[identifier]:
                owners[position].add(identifier)

        report = next(((file, text) for file, (kind, text) in sources.items() if kind == "html"), (None, ""))
        dated_periods = {period for day in dates if (period := parse_period(day))}
        evaluation_days = {period for period in dated_periods
                           if not isinstance(period, DateRange) and period[0] is not None and period[2] is not None}
        periods = [metric_date(reference)[1] for key in ("metrics", "optional_metrics")
                   for reference in expected_flow.get(key, ())]
        allow_undated = allows_undated(periods, dated_periods, evaluation_days)
        tolerance = Decimal(str(numeric["absolute_tolerance"]))
        sign_agnostic = expected_flow.get("sign_agnostic_metrics", ())
        for bucket in ("matched", "mismatched", "unverified", *PENDING_BUCKETS):
            result[bucket] = list(numeric[bucket])
        for identifier, reference, previous, item in pending_metrics(numeric, expected_flow):
            if identifier not in verified:
                continue
            claims = [claim for position, claim in verified[identifier].items() if len(owners[position]) == 1]
            outcome = mapped_result(reference, claims, report, tolerance, dates, allow_undated, sign_agnostic)
            bucket, entry = outcome or ("unverified", {**item, "source": "evidence_map", "reason":
                                        "no_comparable_location" if claims else "no_verified_location"})
            result[previous].remove(item)
            result[bucket].append(entry)

    if result != numeric:
        (run / "numeric_check.json").write_text(json_text(result) + "\n", encoding="utf-8")
    return result
