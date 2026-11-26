"""Check the cleaned artifacts from a completed EDA run against a case key."""

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from decimal import Context, Decimal, DecimalException, MAX_EMAX, MIN_EMIN, ROUND_CEILING
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from zoneinfo import ZoneInfo


# Support direct execution with Python's isolated mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from numeric_check import read_json
from evidence_map import build_targets, load_mapping, resolve_evidence_map
from run_case import DELIVERY_DIR, ROOT, case_inputs, file_sha256, input_fingerprints

SCRIPTS = ROOT / "skills/ask-first-eda/scripts"
sys.path.insert(0, str(SCRIPTS))
from audit_clean import read_references
from eda_io import emit_json, neutralize_formula


AUDIT_VALUE_OPTIONS = {
    "--table-id", "--sheet", "--json-record-path", "--header-row", "--delimiter",
    "--header", "--encoding", "--sheets", "--passthrough",
}
ADDRESS_COLUMNS = {"_source_row", "_source_sheet"}
DEFAULT_TOLERANCE = Decimal("1e-9")
INVALID = object()
KST = ZoneInfo("Asia/Seoul")
VALUE_COLUMN_REVIEW = "Expected exactly one matching value column."
TUPLE_COLUMN_REVIEW = "Expected exactly one key column and one value column."


def read_key(path):
    def reject_constant(token):
        raise ValueError(f"Invalid JSON constant: {token}")

    return json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal, parse_constant=reject_constant)


def validate_audit_args(args):
    if not isinstance(args, list) or not all(isinstance(arg, str) for arg in args):
        raise ValueError("audit_args must be a list of strings.")
    tokens = iter(args)
    for token in tokens:
        option, equals, _ = token.partition("=")
        if token == "--expand":
            continue
        if option not in AUDIT_VALUE_OPTIONS:
            raise ValueError(f"Disallowed audit_args option: {token!r}.")
        if not equals:
            value = next(tokens, None)
            if value is None or value.startswith("--"):
                raise ValueError(f"audit_args requires a value for {option}.")


def find_artifacts(run, artifacts):
    # Match recorded artifacts only and keep their paths inside the run.
    files = set()
    recorded_logs = set()
    for entry in artifacts:
        relative = Path(entry)
        if relative.is_absolute() or ".." in relative.parts:
            continue
        if relative.name == "excluded.csv":
            recorded_logs.add(relative)
        path = run / relative
        if path.is_file() and path.resolve() == path:
            files.add(relative)

    candidates = []
    for path in files:
        delivery = DELIVERY_DIR.fullmatch(path.parent.name)
        if delivery and path.name.startswith("cleaned_") and path.suffix == ".csv":
            log = path.parent.parent / "excluded.csv"
            excluded = log if log in files else None
            rank = (excluded is not None, int(delivery[1] or 1), delivery[1] is not None, path.as_posix())
            candidates.append((rank, path, excluded))
    if not candidates:
        return None, None, []
    if len(candidates) == 1:
        _, cleaned, excluded = candidates[0]
        distinct = [cleaned]
    else:
        # For byte-identical copies, keep the highest-ranked path and its own log.
        unique = {}
        for _, path, excluded in sorted(candidates, reverse=True):
            unique.setdefault(file_sha256(run / path), (path, excluded))
        cleaned, excluded = next(iter(unique.values()))
        distinct = [path for path, _ in unique.values()]

    if excluded is None and len(recorded_logs) == 1:
        [log] = recorded_logs
        if log in files:
            excluded = log
    return cleaned, excluded, distinct


def rerun_audit(source, cleaned, excluded, args):
    with TemporaryDirectory(prefix="cleaning-check-") as scratch:
        if excluded is None:
            excluded = Path(scratch) / "excluded.csv"
            excluded.write_text("_source_row,reason\n", encoding="utf-8")
        process = subprocess.run(
            [sys.executable, "-I", str(SCRIPTS / "audit_clean.py"), str(source),
             "--cleaned", str(cleaned), "--excluded", str(excluded), *args],
            capture_output=True, encoding="utf-8", check=False,
        )
    if process.returncode == 2:
        raise ValueError(f"Invalid audit_args: {process.stderr.strip()}")
    try:
        audit = json.loads(process.stdout)
    except ValueError as error:
        raise ValueError(f"Audit produced no JSON result: {process.stderr.strip()}") from error
    if (process.returncode, audit["status"]) not in {(0, "pass"), (1, "fail")}:
        raise ValueError(f"Unexpected audit exit code and status: {process.returncode}, {audit['status']!r}.")
    return audit


def json_evidence(value):
    if isinstance(value, list):
        return [json_evidence(item) for item in value]
    if isinstance(value, Decimal):
        approximate = float(value)
        # Use text if a JSON float would lose digits from the case key.
        return approximate if Decimal(str(approximate)) == value else str(value)
    return value


def check(name, status, reason, *, address=None, expected=None, actual=None):
    return {
        "name": name, "status": status, "reason": reason,
        "address": address, "expected": json_evidence(expected), "actual": actual,
    }


def address_key(address):
    # Cleaned sheet names may have been neutralized before export to CSV.
    sheet, row = address["sheet"], address["row"]
    if not isinstance(sheet, str) or not isinstance(row, str):
        raise ValueError("Source addresses require string sheet and row fields.")
    return neutralize_formula(sheet), row


def select_columns(headers, aliases, mapped):
    columns = [(index, name) for index, name in enumerate(headers)
               if name not in ADDRESS_COLUMNS and name in aliases]
    if len(columns) != 1 and isinstance(mapped, str) and mapped not in ADDRESS_COLUMNS:
        exact = [(index, name) for index, name in enumerate(headers) if name == mapped]
        if len(exact) == 1:
            return exact
    return columns


def blank(value):
    return value is None or isinstance(value, str) and value.strip().lower() in {"", "nan"}


def normalize_value(value, kind):
    if kind == "empty":
        return None if blank(value) else INVALID
    if kind == "text":
        return value.strip() if isinstance(value, str) else INVALID
    if kind == "number":
        try:
            number = Decimal(str(value))
        except DecimalException:
            return INVALID
        return number if number.is_finite() else INVALID
    if kind in {"date", "datetime"}:
        if not isinstance(value, str):
            return INVALID
        text = value.strip()
        if kind == "datetime" and "T" not in text and " " not in text:
            return INVALID
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
            if kind == "date":
                return parsed.date().isoformat()
            if parsed.tzinfo is not None:
                parsed = parsed.astimezone(KST).replace(tzinfo=None)
            return parsed.isoformat(timespec="minutes")
        except (ValueError, OverflowError):
            return INVALID
    raise ValueError(f"Unknown comparison kind: {kind!r}.")


def within_tolerance(value, options, tolerance):
    if value is INVALID:
        return False
    # Round the nonnegative distance up at a precision that represents the
    # tolerance exactly. This preserves the inclusive boundary.
    arithmetic = Context(prec=len(tolerance.as_tuple().digits), rounding=ROUND_CEILING,
                         Emin=MIN_EMIN, Emax=MAX_EMAX, traps=[])
    return any(arithmetic.subtract(max(value, option), min(value, option)) <= tolerance for option in options)


def compare_value(entry, rows, headers, mapped):
    address, choices = entry["source"], entry["any_of"]
    fields = {"address": address, "expected": choices}
    if len(rows) > 1:
        return check("values", "fail", "Expected one cleaned row at this address.", actual=len(rows), **fields)
    columns = select_columns(headers, entry["column_aliases"], mapped.get("column"))
    if len(columns) != 1:
        return check("values", "review", VALUE_COLUMN_REVIEW,
                     actual=[name for _, name in columns], **fields)
    if not rows:
        return check("values", "review", "No cleaned row at this address.", **fields)
    selected = columns[0]
    result = compare_value_at(entry, rows[0], selected)
    if result["status"] == "fail" and selected[1] in entry["column_aliases"]:
        alternate = select_columns(headers, (), mapped.get("column"))
        if alternate and alternate[0] != selected:
            result = compare_value_at(entry, rows[0], alternate[0])
            result.update(alias_column=selected[1], mapped_column=alternate[0][1])
    return result


def compare_value_at(entry, row, selected):
    address, choices, kind = entry["source"], entry["any_of"], entry["kind"]
    index, column = selected
    actual = row[index]
    value = normalize_value(actual, kind)
    options = [normalize_value(option, kind) for option in choices]
    if not options or any(option is INVALID for option in options):
        raise ValueError(f"Invalid any_of values for {kind!r} at {address!r}.")
    if kind == "number":
        tolerance = normalize_value(entry.get("tolerance", DEFAULT_TOLERANCE), "number")
        if tolerance is INVALID or tolerance < 0:
            raise ValueError(f"Invalid numeric tolerance at {address!r}.")
        matches = within_tolerance(value, options, tolerance)
    else:
        matches = value in options
    status = "pass" if matches else "fail"
    reason = "Matched an expected value" if matches else "No expected value matched"
    result = check("values", status, f"{reason} in {column!r}.", actual=actual,
                   address=address, expected=choices)
    return {**result, "column": column}


def tuple_pair(pair, key_kind, value_kind):
    key, value = pair
    key = normalize_value(key, key_kind)
    if value is None or (value_kind != "text" and blank(value)):
        return key, None
    value = normalize_value(value, value_kind)
    return key, None if value == "" else value


def compare_tuples(entry, rows, headers, mapped):
    expected = entry["expected"]
    fields = {"address": entry["source"], "expected": expected}
    keys = select_columns(headers, entry["key_aliases"], mapped.get("key_column"))
    values = select_columns(headers, entry["value_aliases"], mapped.get("value_column"))
    if mapped and len(keys) == len(values) == 1 and keys[0] == values[0]:
        return compare_tuples(entry, rows, headers, {})
    if len(keys) != 1 or len(values) != 1:
        return check("tuples", "review", TUPLE_COLUMN_REVIEW,
                     actual={"key_columns": [name for _, name in keys],
                             "value_columns": [name for _, name in values]}, **fields)
    key_index, key_name = keys[0]
    value_index, value_name = values[0]
    actual = [[row[key_index], row[value_index]] for row in rows]
    key_kind, value_kind = entry["key_kind"], entry["value_kind"]
    expected_pairs = [tuple_pair(pair, key_kind, value_kind) for pair in expected]
    if any(INVALID in pair for pair in expected_pairs):
        raise ValueError(f"Invalid expected tuples at {entry['source']!r}.")
    actual_pairs = [tuple_pair(pair, key_kind, value_kind) for pair in actual]
    matches = Counter(expected_pairs) == Counter(actual_pairs)
    status = "pass" if matches else "fail"
    reason = "Tuple counts matched" if matches else "Tuple counts differed"
    return check("tuples", status, f"{reason} for {key_name!r} and {value_name!r}.", actual=actual, **fields)


def check_cleaned(cleaned, excluded, key, *, mappings=None, targets=None):
    references, table, _ = read_references(cleaned, excluded=False, errors=[], sheets=set())
    if excluded is not None:
        _, log, _ = read_references(excluded, excluded=True, errors=[], sheets=set())
        if log is not None and log.details["detected_format"] != "csv":
            yield check("excluded_format", "fail", "Expected a CSV exclusion log.",
                        expected="csv", actual=log.details["detected_format"])
    if table is None:
        return
    if table.details["detected_format"] != "csv":
        yield check("cleaned_format", "fail", "Expected a cleaned CSV.",
                    expected="csv", actual=table.details["detected_format"])
        return
    headers = table.details["source_headers"]
    by_address = defaultdict(list)
    for position, row in enumerate(table.frame.itertuples(index=False, name=None)):
        if position in references:
            by_address[references[position]].append(row)

    expected_count = key.get("cleaned_rows")
    if expected_count is not None:
        if type(expected_count) is not int or expected_count < 0:
            raise ValueError("cleaned_rows must be a nonnegative integer or null.")
        actual_count = len(table.frame)
        if actual_count == expected_count:
            yield check("cleaned_rows", "pass", "Row count matched.", expected=expected_count, actual=actual_count)
        else:
            yield check("cleaned_rows", "fail", "Row count differed.", expected=expected_count, actual=actual_count)

    for address in key.get("must_not_keep", []):
        actual = len(by_address.get(address_key(address), ()))
        status, reason = ("fail", "Forbidden source row was kept.") if actual else ("pass", "Source row was absent.")
        yield check("must_not_keep", status, reason, address=address, expected=0, actual=actual)
    for name, compare, column_review, hints in (
        ("values", compare_value, VALUE_COLUMN_REVIEW, ("column_aliases",)),
        ("tuples", compare_tuples, TUPLE_COLUMN_REVIEW, ("key_aliases", "value_aliases")),
    ):
        for index, entry in enumerate(key.get(name, [])):
            identifier = f"{name}:{index}"
            rows = by_address.get(address_key(entry["source"]), ())
            result = compare(entry, rows, headers, (mappings or {}).get(identifier, {}))
            if targets is not None:
                target = {"id": identifier, "source": entry["source"],
                          **{field: entry[field] for field in hints}}
                if result["reason"] == column_review:
                    targets.append(target)
                elif name == "values" and result["status"] == "fail" and "column" in result:
                    targets.append({**target, "reason": "alias_value_mismatch", "alias_column": result["column"]})
            yield result


def collect_targets(run, case, flow, meta):
    """Find unresolved column checks for the shared grading mapper call."""
    key_path = case / "cleaning_expected.json"
    if not key_path.is_file() or key_path.is_symlink():
        return []
    cleaned, _, _ = find_artifacts(run, meta.get("artifacts", []))
    if cleaned is None:
        return []
    key = read_key(key_path)
    if key.get("flow", flow) != flow or key.get("cleaning_required") is False:
        return []
    targets = []
    list(check_cleaned(run / cleaned, None, key, targets=targets))
    return targets


def check_run(run, *, map_missing=False, mapper_call=None):
    run = run.resolve()
    meta = read_json(run / "meta.json")
    case_dir = Path(meta["case_dir"])
    key_path = case_dir / "cleaning_expected.json"
    key = read_key(ROOT / key_path)
    if "flow" in meta and "flow" in key and key["flow"] != meta["flow"]:
        raise ValueError("The run flow does not match cleaning_expected.json.")
    audit_args = key.get("audit_args", [])
    validate_audit_args(audit_args)
    cleaning_required = key.get("cleaning_required") is not False
    cleaned, excluded, candidates = find_artifacts(run, meta.get("artifacts", []))
    files = {"expected": key_path.as_posix(), "source": None,
             "cleaned": cleaned.as_posix() if cleaned else None,
             "excluded": excluded.as_posix() if excluded else None}
    if cleaned is None:
        if not cleaning_required:
            decision = check("cleaning_not_required", "pass", "cleaning not required")
            return {"status": "pass", "checks": [decision], "audit": None, "files": files}
        end_reason = meta.get("end_reason")
        if end_reason == "simulator_end":
            status = "not_applicable"
            reason = "no cleaned CSV delivered; analysis-time filtering is graded by the grader"
        else:
            status = "incomplete" if end_reason in {"max_turns", "error"} else "fail"
            reason = "No recorded cleaned CSV was found."
        missing = check("missing_cleaned", status, reason,
                        expected="delivery/cleaned_*.csv", actual=end_reason)
        return {"status": status, "checks": [missing], "audit": None, "files": files}

    sources = case_inputs(ROOT / case_dir)
    if any(source.name.casefold() == key_path.name for source in sources):
        raise ValueError("cleaning_expected.json cannot be a case input.")
    if len(sources) != 1:
        raise ValueError("A cleaning key requires exactly one case input for source row addresses.")
    if "input_sha256" in meta and input_fingerprints(sources) != meta["input_sha256"]:
        raise ValueError(f"Case inputs changed since the run: {case_dir}")
    [source] = sources
    files["source"] = (case_dir / source.name).as_posix()
    checks = []
    if len(candidates) > 1:
        checks.append(check("cleaned_selection", "pass",
                            "Ranked distinct cleaned CSVs by exclusion log availability, then delivery revision.",
                            expected=[path.as_posix() for path in candidates], actual=files["cleaned"]))
    cleaned_path = run / cleaned
    excluded_path = run / excluded if excluded else None
    audit = rerun_audit(source, cleaned_path, excluded_path, audit_args)
    if not cleaning_required:
        checks.append(check("unnecessary_cleaning", "pass", "cleaned CSV found when cleaning was not required"))
        return {"status": "pass", "checks": checks, "audit": audit, "files": files, "unnecessary_cleaning": True}
    checks.append(check("audit", audit["status"], f"Source audit returned {audit['status']}.",
                        expected="pass", actual=audit["status"]))
    targets = []
    cleaned_checks = list(check_cleaned(cleaned_path, excluded_path, key, targets=targets))
    mapping = None
    if targets:
        if map_missing:
            mapping = resolve_evidence_map(run, build_targets({}, {"metrics": []}, targets),
                                           call=mapper_call, fill_missing=True)
        else:
            mapping = load_mapping(run)
        if mapping and mapping.get("columns"):
            columns = {entry["id"]: entry for entry in mapping["columns"]}
            cleaned_checks = list(check_cleaned(cleaned_path, excluded_path, key, mappings=columns))
    checks.extend(cleaned_checks)
    statuses = {entry["status"] for entry in checks}
    status = next(candidate for candidate in ("fail", "review", "pass") if candidate in statuses)
    result = {"status": status, "checks": checks, "audit": audit, "files": files}
    if mapping and mapping.get("status") == "error":
        result["evidence_map_error"] = mapping["reason"]
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--map", action="store_true", help="Allow a mapper call for unresolved columns.")
    args = parser.parse_args(argv)
    run = args.run.resolve()
    output = run / "cleaning_check.json"
    try:
        emit_json(check_run(run, map_missing=args.map), output)
    except (OSError, ValueError, KeyError, TypeError, DecimalException) as error:
        parser.exit(1, f"Cleaning check could not run: {error}\n")
    print(f"Cleaning check saved to {output}")


if __name__ == "__main__":
    main()
