"""Compare numbers reported in an EDA run with the selected flow's answer key."""

import argparse
from decimal import Decimal
from fractions import Fraction
from html.parser import HTMLParser
from itertools import chain
import json
from pathlib import Path
import re
import sys
from typing import NamedTuple


# Support direct execution with Python's isolated mode.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from run_case import DELIVERY_DIR, ROOT, case_inputs, case_path, input_fingerprints, json_text


NUMBER = r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
NUMBER_IN_TEXT = re.compile(rf"(?<![a-zA-Z0-9_.,]){NUMBER}(?![\d_]|[.,]\d)")
FORMULA = re.compile(rf"^({NUMBER})\s*[/÷]\s*({NUMBER})\s*=\s*({NUMBER})(?![\d.])")
ARITHMETIC_IN_TEXT = re.compile(rf"{NUMBER}\s*[-+*/÷×−]\s*{NUMBER}\s*=\s*{NUMBER}")
VALUE_PREDICATE = re.compile(
    r"(?:\b(?:is|are|was|were|be|reached|hit|averaged|total(?:ed|led)|equals?|"
    r"came\s+to|stood\s+at|works?\s+out\s+to|estimated\s+at|reported\s+as|measured\s+at|"
    r"calculated\s+as|computed\s+as|equal\s+to|estimate\s+of|of)\s+"
    r"(?:(?:about|around|approximately|roughly)\s+)?"
    r"|(?:약|총|평균|시간당|일당)\s*)$",
    re.IGNORECASE,
)
VALUE_FOR_METRIC = re.compile(r"\b(?:for|as)\s+(?:the\s+)?$", re.IGNORECASE)
CONDITIONAL = re.compile(r"\b(?:if|when|assuming|provided that)\b|경우|(?<!무)조건|가정|라면|이면"
                         r"|(?<=[가-힣])\s+시(?=\W|$)", re.IGNORECASE)
CLAUSE_BREAK = re.compile(r"[;；。！]|[.!](?=\s|$)|(?<=[?？])")
UNITS = {
    alias: (dimension, factor, offset)
    for aliases, dimension, factor, offset in (
        (("%", "pct", "percent", "per cent", "퍼센트"), "ratio", Fraction(1, 100), 0),
        (("ratio",), "ratio", 1, 0),
        (("%p",), "percentage_point", 1, 0),
        (("kg",), "mass", 1000, 0),
        (("g",), "mass", 1, 0),
        (("t", "톤"), "mass", 1_000_000, 0),
        (("l",), "volume", 1000, 0),
        (("ml",), "volume", 1, 0),
        (("h", "hr", "hrs", "hour", "hours", "시간"), "time", 3600, 0),
        (("min", "분"), "time", 60, 0),
        (("s", "초"), "time", 1, 0),
        (("개", "건", "units", "count"), "count", 1, 0),
        (("°c",), "temperature", 1, 0),
        (("°f",), "temperature", Fraction(5, 9), Fraction(-160, 9)),
    )
    for alias in aliases
}
UNSCALED = (("tuple", 1, 0),)
PERCENT_TO_RATIO = ("percent_to_ratio", Fraction(1, 100), 0)
RATIO_TO_PERCENT = ("ratio_to_percent", 100, 0)
COUNT_DENOMINATORS = {"건", "회", "개", "명", "셀", "교대", "count", "item", "event"}
RATIO_WORD = re.compile(r"\b(?:fraction|share|proportion|ratio)\b|비중|비율")
AVERAGE_WORD = re.compile(r"\b(?:avg|average|mean)\b|평균")
DIVISION_WORD = re.compile(r"\b(?:divided by|ratio of)\b|÷|나눈|나누")
AGGREGATE_WORD = re.compile(r"\b(?:count|sum|total)\b|건수|개수|합계|합산|총합|누적|고유[^.]*?\s수\b"
                            r"|(?:^|\s)총(?=\s)")
UNIT_WORD = r"(?:(?i:per[ \t]+cent)(?!\w)|%[^\W\d_]*|°?[^\W\d_]+)"
HOUR_QUALIFIER = r"(?:logged|operating|elapsed|recorded|active)"
QUALIFIED_HOUR = re.compile(rf"{HOUR_QUALIFIER}\s+(hours?|hrs?|h)")
UNIT_SUFFIX = re.compile(
    rf"\s*({UNIT_WORD}(?:(?:\s*/\s*|\s+(?i:per)\s+)(?:(?i:{HOUR_QUALIFIER})\s+)?{UNIT_WORD})*)(?![\w/])"
)
UNIT_END = re.compile(r"[\s*\x60_)|]*$")
KOREAN_UNIT_ENDING = re.compile(r"(?:입니다|이다|이며|이고|으로|로|과|와|을|를|은|는|이|가)$")
DAY_QUALIFIER = re.compile(r"\d{1,2}\s*일\s+[^\W\d_]")
SCOPE_EXCLUSIONS = {"name", "unit", "value", "values", "scale", "numerator", "numerators",
                    "denominator", "denominators", "source_refs", "condition", "conditional",
                    "depends_on_ambiguity_ids", "keywords"}
METRIC_TEXT_FIELDS = ("name", "definition", "condition")
METRIC_DATE_FIELDS = ("date", "month")
METRIC_CONTEXT_DATE_FIELDS = ("definition", "condition")
METRIC_DATE_SOURCES = (METRIC_DATE_FIELDS, ("name",), METRIC_CONTEXT_DATE_FIELDS)
CONFLICTING_DATES = object()
MONTH_NAMES = ("january", "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december")
MONTH_NUMBERS = {name: number for number, month in enumerate(MONTH_NAMES, 1)
                 for name in (month, month[:3])}
MONTH_WORD = "|".join(MONTH_NUMBERS)
MONTH_NUMBER = r"0[1-9]|1[0-2]"
DAY_NUMBER = r"0[1-9]|[12][0-9]|3[01]"
LOCAL_MONTH = rf"[1-9]|{MONTH_NUMBER}"
LOCAL_DAY = rf"[1-9]|{DAY_NUMBER}"
DATE_SCOPE = re.compile(
    rf"(?<![\d/-])(?P<iso_year>\d{{4}})-(?P<iso_month>{MONTH_NUMBER})"
    rf"(?:-(?P<iso_day>{DAY_NUMBER}))?(?![\d/-])"
    rf"|(?<!\d)(?:(?P<ko_year>\d{{4}})\s*년\s*)?(?P<ko_month>{LOCAL_MONTH})\s*월"
    rf"(?:\s*(?P<ko_day>{LOCAL_DAY})\s*일)?"
    rf"|(?<![^\W_])(?:(?P<day_first>{LOCAL_DAY})\s+)?(?P<en_month>{MONTH_WORD})(?![^\W_])"
    rf"(?(day_first)|\s+(?P<en_day>{LOCAL_DAY})(?!\w|\.\d))?(?:,?\s+(?P<en_year>\d{{4}})(?!\d))?",
    re.IGNORECASE,
)
SHORT_DAY = re.compile(rf"(?<![\d/-])({MONTH_NUMBER})-({DAY_NUMBER})(?![\d/-])")
ISO_DAY = rf"\d{{4}}-(?:{MONTH_NUMBER})-(?:{DAY_NUMBER})"
DATE_RANGE = re.compile(rf"(?<![\d/-])({ISO_DAY})\s*(?:[~∼～–—]|\.\.)\s*({ISO_DAY})(?![\d/-])")


class DateRange(NamedTuple):
    start: tuple
    end: tuple


MONTH_PREPOSITION = re.compile(
    r"(?<![^\W_])(?:in|on|during|for|from|through|until|since|by|of|to|before|after)[\s_]+$",
    re.IGNORECASE,
)
HTML_PATTERNS = ("*.[hH][tT][mM][lL]", "*.[hH][tT][mM]")
HTML_TEXT_LIMIT = 16_000


def read_json(path):
    def reject_constant(constant):
        raise ValueError(f"Invalid JSON constant: {constant}")

    return json.loads(path.read_text(encoding="utf-8"), parse_constant=reject_constant)


def load_expected(run):
    meta = read_json(run / "meta.json")
    case = ROOT / meta["case_dir"] if "case_dir" in meta else case_path(meta["case"])
    if "input_sha256" in meta:
        if not case.is_dir() or input_fingerprints(case_inputs(case)) != meta["input_sha256"]:
            raise ValueError(f"Case inputs changed since the run: {case}")
    flow = meta["flow"]
    expected = read_json(case / "expected.json")
    if flow not in expected["flows"]:
        raise ValueError(f"No expected results for flow {flow}")
    return case, flow, {**expected, "flows": {flow: expected["flows"][flow]}}


def artifact_paths(run, pattern):
    paths = []
    for path in run.rglob(pattern):
        parts = path.relative_to(run).parts
        if (parts[0] not in {"raw", "ask-first-eda", "eda-skill"} and not path.name.startswith(".")
                and not path.is_symlink() and path.is_file()):
            paths.append(path)
    return sorted(paths)


def summary_path(run):
    primary = run / "eda_summary.json"
    if primary.is_file() and not primary.is_symlink():
        return primary
    summaries = artifact_paths(run, "eda_summary.json")
    if len(summaries) > 1:
        content = summaries[0].read_bytes()
        if any(summary.read_bytes() != content for summary in summaries[1:]):
            raise ValueError("Multiple eda_summary.json files found without a top-level summary")
    if summaries:
        return summaries[0]
    if path := delivery_results_path(run):
        try:
            validate_sidecar(read_json(path))
        except (OSError, ValueError):
            return None
        return path
    return None


def report_path(run, summary):
    if summary is not None:
        report = summary.with_name("report.html")
        return report if report.is_file() and not report.is_symlink() else None

    reports = []
    for report in artifact_paths(run, "report.html"):
        if delivery := DELIVERY_DIR.fullmatch(report.parent.name):
            revision = int(delivery[1] or 1)
            reports.append((revision, report.stat().st_mtime_ns, report))
    if not reports:
        return None
    selected = max(reports)[2]
    if selected == reports[0][2]:
        return selected
    content = selected.read_bytes()
    return next(report for _, _, report in reports if report == selected or report.read_bytes() == content)


def validate_sidecar(summary):
    skill = ROOT / "skills/ask-first-eda"
    schema = read_json(skill / "references/eda_summary.schema.json")
    json.dumps(summary, allow_nan=False)
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        scripts = str(skill / "scripts")
        if scripts not in sys.path:
            sys.path.insert(0, scripts)
        from build_report import fallback_validate
        fallback_validate(summary, schema, schema)
    else:
        error = next(Draft202012Validator(schema).iter_errors(summary), None)
        if error is not None:
            raise ValueError(f"{error.json_path}: {error.message}")


def metric_list(value):
    if not isinstance(value, list) or any(
        not isinstance(item, dict) or not isinstance(item.get("name"), str)
        or not item["name"].strip() for item in value
    ):
        raise ValueError("Metrics must be a list of objects with non-empty names")
    return value


def metric_name(metric):
    name = DATE_RANGE.sub(" ", metric["name"])
    name = DATE_SCOPE.sub(lambda match: " " if is_date_mention(match) else match[0], name)
    name = SHORT_DAY.sub(" ", name)
    return " ".join(re.findall(r"[^\W_]+", name.casefold()))


def is_date_mention(match):
    return (not match["en_month"] or any(match[key] for key in ("day_first", "en_day", "en_year"))
            or MONTH_PREPOSITION.search(match.string[:match.start()]) is not None)


def period_parts(match):
    if match["iso_month"]:
        year, month, day = match["iso_year"], match["iso_month"], match["iso_day"]
    elif match["ko_month"]:
        year, month, day = match["ko_year"], match["ko_month"], match["ko_day"]
    else:
        year, month = match["en_year"], MONTH_NUMBERS[match["en_month"].casefold()]
        day = match["en_day"] or match["day_first"]
    return year, int(month), int(day) if day else None


def parse_period(text):
    if isinstance(text, str):
        text = text.strip()
        if match := DATE_RANGE.fullmatch(text):
            start, end = map(parse_period, match.groups())
            return DateRange(start, end) if start < end else None
        if match := DATE_SCOPE.fullmatch(text):
            return period_parts(match)
    return None


def periods_compatible(left, right):
    return all(a is None or b is None or a == b for a, b in zip(left, right))


def metric_date_mentions(metric, fields):
    for field in fields:
        text = metric.get(field)
        if not isinstance(text, str):
            continue
        if field in METRIC_DATE_FIELDS:
            if match := DATE_SCOPE.fullmatch(text.strip()):
                yield match
        else:
            yield from (match for match in DATE_SCOPE.finditer(text) if is_date_mention(match))


def context_month(mentions):
    label, month = None, None
    for match in mentions:
        observed = (*period_parts(match)[:2], None)
        if month is not None and not periods_compatible(month, observed):
            return None, CONFLICTING_DATES
        if month is None or month[0] is None and observed[0] is not None:
            label, month = match[0], observed
    return label, month


def metric_date(metric, *, expected_month=None):
    for fields in METRIC_DATE_SOURCES:
        texts = [metric[field] for field in fields if isinstance(metric.get(field), str)]
        ranges = [match[0] for text in texts for match in DATE_RANGE.finditer(text)]
        if ranges:
            other_dates = any(DATE_SCOPE.search(DATE_RANGE.sub(" ", text)) for text in texts)
            if len(set(ranges)) == 1 and not other_dates and (period := parse_period(ranges[0])):
                return ranges[0], period
            return None, CONFLICTING_DATES
        if next(metric_date_mentions(metric, fields), None):
            break
    label, period = None, None
    for fields in METRIC_DATE_SOURCES:
        identifying = period is None
        if fields == METRIC_CONTEXT_DATE_FIELDS:
            definition = list(metric_date_mentions(metric, ("definition",)))
            condition = list(metric_date_mentions(metric, ("condition",)))
            definition_label, definition_month = context_month(definition)
            if definition_month is CONFLICTING_DATES:
                if identifying:
                    return None, CONFLICTING_DATES
                definition = []
            if identifying and expected_month is not None:
                # A day in explanatory text can identify its month.
                if definition_month is not None and periods_compatible(expected_month, definition_month):
                    return definition_label, definition_month
                for match in condition:
                    month = (*period_parts(match)[:2], None)
                    if periods_compatible(expected_month, month):
                        return match[0], month
                return None, CONFLICTING_DATES if definition or condition else None
            mentions = chain(definition, condition)
        else:
            mentions = metric_date_mentions(metric, fields)
        for match in mentions:
            observed = period_parts(match)
            if period is None:
                label, period = match[0], observed
            elif identifying:
                if not periods_compatible(period, observed):
                    return None, CONFLICTING_DATES
                period = tuple(a if a is not None else b for a, b in zip(period, observed))
            else:
                # Keep the identifying precision and complete its year from compatible text.
                same_precision = (period[2] is None) == (observed[2] is None)
                if not same_precision and period[1] != observed[1]:
                    continue
                if not periods_compatible(period if same_precision else period[:2], observed):
                    return None, CONFLICTING_DATES
                if period[0] is None:
                    period = observed[0], *period[1:]
    return label, period


def dates_match(expected, actual):
    if isinstance(expected, DateRange) or isinstance(actual, DateRange):
        return expected == actual
    return (expected is not None and actual is not None
            and (expected[2] is None) == (actual[2] is None)
            and periods_compatible(expected, actual))


def candidate_for_period(row, expected):
    if (expected is None or expected is CONFLICTING_DATES or isinstance(expected, DateRange)
            or expected[2] is not None or isinstance(row[3], DateRange) or metric_short_days(row[1])):
        return row
    index, metric, observed, _, name = row
    _, period = metric_date(metric, expected_month=expected)
    return index, metric, observed, period, name


def metric_short_days(metric):
    return {tuple(map(int, match.groups())) for field in (*METRIC_DATE_FIELDS, "name")
            if isinstance(text := metric.get(field), str) for match in SHORT_DAY.finditer(text)}


def submitted_period(metric, evaluation_days):
    period = metric_date(metric)[1]
    short_days = metric_short_days(metric)
    if not short_days or period is CONFLICTING_DATES:
        return period
    if len(short_days) != 1 or isinstance(period, DateRange):
        return CONFLICTING_DATES
    candidates = {day for day in evaluation_days if day[1:] in short_days}
    if len(candidates) != 1:
        return CONFLICTING_DATES
    day = candidates.pop()
    return day if period is None or periods_compatible(day, period) else CONFLICTING_DATES


def normalized_text(text):
    return "".join(text.casefold().split())


def scope_matches(reference, metric, date, actual_date, *, allow_undated=False, mapped_evidence=False):
    if date is CONFLICTING_DATES or actual_date is CONFLICTING_DATES:
        return False
    if isinstance(date, DateRange) or isinstance(actual_date, DateRange) and date is not None:
        if date != actual_date:
            return False
    if date is not None and actual_date is None:
        if not allow_undated or any(metric.get(key) is not None for key in METRIC_DATE_FIELDS):
            return False
        actual_date = date
    texts = [metric[field] for field in METRIC_TEXT_FIELDS
             if isinstance(metric.get(field), str)]
    for key, value in reference.items():
        if (key in SCOPE_EXCLUSIONS or mapped_evidence and key == "definition"
                or key.startswith(("numerator_", "numerators_", "denominator_", "denominators_"))):
            continue
        if type(value) in (int, float, bool) and key not in METRIC_DATE_FIELDS:
            if key in metric and metric[key] != value:
                return False
            continue
        if not isinstance(value, str) or not value.strip():
            continue
        if key in METRIC_DATE_FIELDS:
            if (parse_period(value) is None or not dates_match(date, actual_date)
                    or key in metric and parse_period(metric[key]) is None
                    and not (isinstance(metric[key], str) and SHORT_DAY.fullmatch(metric[key].strip()))):
                return False
        elif key in metric:
            if not isinstance(metric[key], str) or normalized_text(value) != normalized_text(metric[key]):
                return False
        elif period := parse_period(value):
            if not dates_match(period, actual_date):
                return False
        else:
            scope = normalized_text(value)
            if len(scope) == 1 and scope.isascii() and scope.isalnum():
                token = rf"(?<![a-z0-9]){re.escape(scope)}(?![a-z0-9])"
                if not any(re.search(token, text.casefold()) for text in texts):
                    return False
            elif not any(scope in normalized_text(text) for text in texts):
                return False
    return True


def comparable_fields(metric):
    fields = {}
    if "values" in metric or "value" in metric:
        fields["value"] = metric["values"] if "values" in metric else metric["value"]
    for field in ("numerator", "denominator"):
        if field in metric:
            fields[field] = metric[field]
        else:
            for key, quantity in metric.items():
                if key == field + "s" or key.startswith((field + "_", field + "s_")):
                    fields[field] = quantity
                    break
    if "condition" in metric:
        condition = metric["condition"]
        fields["conditional"] = isinstance(condition, str) and bool(condition.strip())
    elif "conditional" in metric:
        fields["conditional"] = metric["conditional"]
    return fields


def is_aggregate(metric):
    name = metric_name(metric)
    definition = metric.get("definition") or ""
    if not isinstance(definition, str) or DIVISION_WORD.search(definition.casefold()):
        return False
    unit = metric.get("unit")
    parts = unit_parts(unit)
    return (isinstance(unit, str) and bool(unit.strip()) and len(parts) == 1
            and parts[0] not in (UNITS["%"], UNITS["ratio"], UNITS["%p"])
            and not re.search(r"[%‰]", unit)
            and not (AVERAGE_WORD.search(name) or RATIO_WORD.search(name)
                     or re.search(r"\b(?:rate|per|percent|percentage)\b|률(?:\s|$)|당(?:\s|$)", name))
            and bool(AGGREGATE_WORD.search(name) or AGGREGATE_WORD.search(definition.casefold())))


def agrees(expected, actual, tolerance, scale=1, offset=0, *, direction=1):
    if isinstance(expected, list):
        return (isinstance(actual, list) and len(expected) == len(actual)
                and all(agrees(a, b, tolerance, scale, offset, direction=direction)
                        for a, b in zip(expected, actual)))
    if type(expected) in (float, int) and type(actual) in (float, int):
        reference, observed = Decimal(str(expected)), Decimal(str(actual))
        if not reference.is_finite() or not observed.is_finite():
            return False
        if scale != 1 or offset or direction != 1:
            reference = Fraction(reference)
            observed = Fraction(observed) * scale + offset
            if direction == 0:
                return abs(abs(reference) - abs(observed)) <= tolerance
            return abs(reference - direction * observed) <= tolerance
        return abs(reference - observed) <= tolerance
    return (direction == 1 and scale == 1 and not offset
            and type(expected) is type(actual) and expected == actual)


def combine_fields(entries, expected_fields):
    combined = {}
    for field, reference in expected_fields.items():
        if all(field in row for row in entries):
            values = [row[field] for row in entries]
            combined[field] = values[0] if (
                not isinstance(reference, list)
                and all(type(value) is type(values[0]) and value == values[0] for value in values)
            ) else values
    return combined


def unit_labels(unit):
    return tuple(" ".join(part.split()) for part in str(unit or "").casefold().split("/"))


def unit_parts(unit):
    label = re.sub(r"\s+per\s+", "/", str(unit or "").strip().casefold())
    head = re.split(r"\bof\b", label, maxsplit=1)[0]
    if "/" not in head and RATIO_WORD.search(head):
        return (UNITS["ratio"],)
    parts = unit_labels(label)
    if len(parts) == 1:
        return (UNITS.get(parts[0]),)
    # Compound units may qualify each physical unit with the material measured.
    return tuple(UNITS["h"] if QUALIFIED_HOUR.fullmatch(part)
                 else UNITS.get(part) or UNITS.get(part.partition(" ")[0]) for part in parts)


def unknown_unit_mismatch(expected_unit, actual_unit):
    return (bool(str(expected_unit or "").strip() and str(actual_unit or "").strip())
            and unit_labels(expected_unit) != unit_labels(actual_unit)
            and not (all(unit_parts(expected_unit)) and all(unit_parts(actual_unit))))


def comparison_units(expected_unit, actual_unit):
    left, right = unit_labels(expected_unit), unit_labels(actual_unit)
    if len(left) == 2 and left[1] in COUNT_DENOMINATORS and len(right) == 1 and right[0]:
        return left[0], actual_unit
    if len(right) == 2 and right[1] in COUNT_DENOMINATORS and len(left) == 1 and left[0]:
        return expected_unit, right[0]
    return expected_unit, actual_unit


def unit_methods(reference, metric, *, allow_count_notation=True):
    expected_unit, actual_unit = reference.get("unit"), metric.get("unit")
    if allow_count_notation:
        expected_unit, actual_unit = comparison_units(expected_unit, actual_unit)
    expected, actual = unit_parts(expected_unit), unit_parts(actual_unit)
    ratio, percent = (UNITS["ratio"],), (UNITS["%"],)
    expected_absent = not str(expected_unit or "").strip()
    actual_absent = not str(actual_unit or "").strip()
    if expected_unit is None:
        # Older answer keys omit units even for scaled values.
        if actual_absent:
            return (*UNSCALED, PERCENT_TO_RATIO, RATIO_TO_PERCENT)
        if actual == ratio:
            return (*UNSCALED, RATIO_TO_PERCENT)
        if actual == percent:
            return (*UNSCALED, PERCENT_TO_RATIO)
    if unknown_unit_mismatch(expected_unit, actual_unit):
        return ()
    if (expected == ratio or expected_absent) and actual == percent:
        return (PERCENT_TO_RATIO,)
    if expected == percent and (actual == ratio or (actual_unit is not None and actual_absent)):
        return (RATIO_TO_PERCENT,)
    if not any(expected) or not any(actual) or expected == actual:
        return UNSCALED
    if len(expected) != len(actual) and all(expected) and all(actual):
        return ()
    scale = Fraction(1)
    offset = 0
    for index, (reference_part, observed_part) in enumerate(zip(expected, actual)):
        if reference_part is None or observed_part is None:
            continue
        reference_dimension, reference_factor, reference_offset = reference_part
        observed_dimension, observed_factor, observed_offset = observed_part
        if reference_dimension != observed_dimension:
            return ()
        factor = Fraction(observed_factor) / reference_factor
        if len(expected) == len(actual) == 1:
            offset = Fraction(observed_offset - reference_offset) / reference_factor
        elif reference_offset != observed_offset:
            return ()
        scale = scale * factor if index == 0 else scale / factor
    return UNSCALED if scale == 1 and not offset else (("unit_conversion", scale, offset),)


def match_value(expected, actual, tolerance, methods, *, direction=1):
    return next((method for method, scale, offset in methods
                 if agrees(expected, actual, tolerance, scale, offset, direction=direction)), None)


def display_half_step(metric):
    places = metric.get("_display_decimals")
    return 0 if places is None else Fraction(1, 2 * 10 ** places)


def claims_agree(reference, metric, value, other, other_value, tolerance):
    pair_methods = unit_methods(metric, other)
    left, right = Decimal(str(value)), Decimal(str(other_value))
    if not pair_methods or not left.is_finite() or not right.is_finite():
        return False
    if any(unit_parts(reference.get("unit"))):
        left_methods, right_methods = unit_methods(reference, metric), unit_methods(reference, other)
    else:
        left_methods, right_methods = UNSCALED, pair_methods
    left, right = Fraction(left), Fraction(right)
    left_step, right_step = display_half_step(metric), display_half_step(other)
    return any(abs(left * scale + offset - (right * other_scale + other_offset))
               <= max(tolerance, left_step * abs(scale), right_step * abs(other_scale))
               for _, scale, offset in left_methods
               for _, other_scale, other_offset in right_methods)


def conflicting_text_claims(reference, rows, text_rows, tolerance, *, allow_undated,
                            against_summary=False, mapped_evidence=False):
    date = metric_date(reference)[1]
    expected_parts = unit_parts(reference.get("unit"))
    for row in rows:
        index, metric, observed, period, name = candidate_for_period(row, date)
        if allow_undated and period is None:
            period = date
        value = observed.get("value")
        conditional = bool(observed.get("conditional")) if against_summary else False
        anchor = ((metric, value) if type(value) in (int, float)
                  and (against_summary or not observed.get("conditional")) else None)
        if against_summary and anchor is None:
            continue
        names = {name, metric_name(reference)} if against_summary else {name}
        for other_row in text_rows:
            if index == other_row[0] or other_row[4] not in names:
                continue
            _, other, other_fields, other_period, _ = candidate_for_period(other_row, date)
            if "value" not in other_fields or bool(other_fields.get("conditional")) != conditional:
                continue
            claim_parts = unit_parts(other.get("unit"))
            if all(expected_parts) and all(claim_parts) and (
                tuple(part[0] for part in expected_parts) != tuple(part[0] for part in claim_parts)
            ):
                continue
            if not scope_matches(reference, other, date, other_period, allow_undated=allow_undated,
                                 mapped_evidence=mapped_evidence):
                continue
            if against_summary:
                mentions = [period_parts(match) for match in metric_date_mentions(other, ("definition",))]
                if any(not periods_compatible(left, right)
                       for i, left in enumerate(mentions) for right in mentions[i + 1:]):
                    continue
            if against_summary and conditional:
                condition = reference.get("condition") or metric.get("condition")
                if condition and normalized_text(condition) not in normalized_text(other.get("definition", "")):
                    continue
            if allow_undated and other_period is None:
                other_period = date
            if period != other_period and not dates_match(period, other_period):
                continue
            other_value = other_fields["value"]
            if anchor is None:
                anchor = other, other_value
                continue
            metric, value = anchor
            if against_summary and any(
                unknown_unit_mismatch(*comparison_units(left.get("unit"), other.get("unit")))
                for left in (reference, metric)
            ):
                continue
            if not claims_agree(reference, metric, value, other, other_value, tolerance):
                return [{"value": value, "unit": metric.get("unit")},
                        {"value": other_value, "unit": other.get("unit")}]
    return []


def omitted_components(fields, observed, *, same_identity=True):
    if "value" not in fields:
        return ()
    denominator = fields.get("denominator")
    if "denominator" in fields and denominator is None:
        return ("numerator",) if observed.get("numerator") is None else ()
    if not same_identity or type(denominator) not in (int, float) or denominator != 1:
        return ()
    if "denominator" not in observed:
        return ()
    submitted = observed["denominator"]
    if submitted is not None and (type(submitted) not in (int, float) or submitted != 1):
        return ()
    return ("denominator", "numerator") if observed.get("numerator") is None else ("denominator",)


def tuple_match(reference, fields, metric, observed, tolerance, *, check_units=True, direction=1,
                same_identity):
    numeric_fields = {key: value for key, value in fields.items() if key != "conditional"}
    if not numeric_fields:
        return None
    methods = unit_methods(reference, metric, allow_count_notation=same_identity) if check_units else UNSCALED
    if not methods:
        return None
    omitted = omitted_components(fields, observed, same_identity=same_identity)
    if any(key not in observed or not agrees(value, observed[key], tolerance)
           for key, value in numeric_fields.items() if key != "value" and key not in omitted):
        return None
    if "value" in fields and "value" not in observed:
        return None
    if "value" not in fields:
        return methods[0][0]
    return match_value(fields["value"], observed["value"], tolerance, methods, direction=direction)


def field_differences(expected, observed, tolerance, *, tuple_matched=False, omitted=()):
    differences = {}
    for field, value in expected.items():
        if (tuple_matched and field != "conditional") or field in omitted:
            continue
        if field not in observed:
            differences[field] = {"expected": value, "reason": "field_missing"}
        elif not agrees(value, observed[field], tolerance):
            differences[field] = {"expected": value, "actual": observed[field]}
            if field == "conditional":
                differences[field]["reason"] = "conditional_mismatch"
    return differences


def select_tuple(reference, fields, date, candidates, tolerance, *, match_condition,
                 check_units=True, direction=1):
    name = metric_name(reference)
    matches = []
    for index, metric, observed, actual_date, actual_name in candidates:
        if date and actual_date and not dates_match(date, actual_date):
            continue
        if (not check_units and name != actual_name and not unit_methods(reference, metric, allow_count_notation=False)
                and not unknown_unit_mismatch(reference.get("unit"), metric.get("unit"))):
            continue
        method = tuple_match(reference, fields, metric, observed, tolerance,
                             check_units=check_units, direction=direction, same_identity=name == actual_name)
        if method is None:
            continue
        if match_condition and field_differences(fields, observed, tolerance, tuple_matched=True):
            continue
        rank = (date is not None and actual_date is None, method != "tuple", name != actual_name)
        matches.append((rank, index, observed, method))
    if not matches:
        return None
    _, index, observed, method = min(matches, key=lambda match: match[:2])
    return index, observed, method


def select_daily_tuples(reference, fields, dates, candidates, tolerance, *, match_condition,
                        direction, check_units):
    if not dates or not isinstance(fields.get("value"), list):
        return None
    if any(len(value) != len(dates) for value in fields.values() if isinstance(value, list)):
        return None
    indices, entries, methods = [], [], []
    for day, date in enumerate(dates):
        day_fields = {key: value[day] if isinstance(value, list) else value
                      for key, value in fields.items()}
        match = select_tuple(reference, day_fields, parse_period(date),
                             (row for row in candidates if row[0] not in indices), tolerance,
                             match_condition=match_condition, check_units=check_units, direction=direction)
        if match is None:
            return None
        index, observed, method = match
        indices.append(index)
        entries.append(observed)
        methods.append(method)
    conversions = sorted(set(methods) - {"tuple"})
    matched_via = "daily_tuple" + "".join(f"+{method}" for method in conversions)
    return indices, combine_fields(entries, fields), matched_via


def select_metric_tuple(reference, entry, date, dates, candidates, tolerance, *, match_condition,
                        direction=1, check_units=True):
    fields = entry["expected"]
    if match := select_tuple(reference, fields, date, candidates, tolerance,
                             match_condition=match_condition, check_units=check_units, direction=direction):
        index, observed, method = match
        return [index], observed, method
    if "date" not in entry:
        return select_daily_tuples(reference, fields, dates, candidates, tolerance,
                                   match_condition=match_condition, check_units=check_units, direction=direction)
    return None


def last_analyst_text(run, *, strict=True):
    transcript = run / "transcript.jsonl"
    if not transcript.is_file():
        return ""
    text = ""
    with transcript.open(encoding="utf-8", errors="strict" if strict else "replace") as stream:
        for line in stream:
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    if strict:
                        raise
                    continue
                if isinstance(row, dict) and row.get("speaker") == "analyst" and isinstance(row.get("text"), str):
                    text = row["text"]
    return text


class ReportText(HTMLParser):
    IGNORED = {"head", "script", "style", "svg", "template", "noscript"}
    BLOCKS = {"br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p",
              "pre", "section", "td", "th", "tr"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
            "param", "source", "track", "wbr"}
    HIDDEN_STYLE = re.compile(r"(?:^|;)\s*(?:display\s*:\s*none|visibility\s*:\s*hidden)"
                              r"\s*(?:!important\s*)?(?:;|$)", re.IGNORECASE)

    def __init__(self, limit, *, skip_code_blocks=False):
        super().__init__()
        self.ignored = []
        self.parts = []
        self.remaining = limit
        self.skip_code_blocks = skip_code_blocks
        self.in_preformatted = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        code_block = self.skip_code_blocks and self.in_preformatted and tag == "code"
        if (self.ignored or tag in self.IGNORED or code_block or "hidden" in attrs
                or self.HIDDEN_STYLE.search(attrs.get("style") or "")):
            if tag not in self.VOID:
                self.ignored.append(tag)
        elif tag in self.BLOCKS:
            if tag == "pre":
                self.in_preformatted = True
            self.handle_data("\n")

    def handle_endtag(self, tag):
        if self.ignored:
            if tag in self.ignored:
                while self.ignored.pop() != tag:
                    pass
        elif tag in self.BLOCKS:
            if tag == "pre":
                self.in_preformatted = False
            self.handle_data("\n")

    def handle_data(self, data):
        if not self.ignored and self.remaining != 0:
            part = data[:self.remaining]
            self.parts.append(part)
            if self.remaining is not None:
                self.remaining -= len(part)

    def text(self):
        return "".join(self.parts).strip()


def reports_text(run, report, *, for_grader=True):
    if report is None:
        return "(No HTML report supplied.)" if for_grader else ""

    header = report.relative_to(run).as_posix() + "\n" if for_grader else ""
    parser = ReportText(HTML_TEXT_LIMIT - len(header) if for_grader else None,
                        skip_code_blocks=not for_grader)
    with report.open(encoding="utf-8", errors="replace") as stream:
        while parser.remaining != 0 and (chunk := stream.read(65_536)):
            parser.feed(chunk)
    parser.close()
    return header + parser.text()


def parse_number(text):
    text = text.replace(",", "")
    return float(text) if re.search(r"[.eE]", text) else int(text)


def text_clauses(text):
    return [clause for line in text.splitlines() for clause in CLAUSE_BREAK.split(line)
            if clause.strip() and not clause.rstrip().endswith(("?", "？"))]


def metric_label_pattern(name, *, allow_particles=False):
    label = r"[\W_]+".join(map(re.escape, name.split()))
    if allow_particles and re.search(r"[가-힣]$", name):
        label += r"(?:으로|에서|은|는|이|가|을|를|의|로|에)?"
    return re.compile(r"(?<![^\W_])" + label + r"(?![^\W_])", re.IGNORECASE)


def unparsed_excerpt(reference, date, clauses, *, allow_undated):
    keywords = reference.get("keywords", [])
    if isinstance(keywords, str):
        keywords = [keywords]
    elif not isinstance(keywords, list):
        keywords = []
    names = {metric_name(reference)}
    names.update(metric_name({"name": word}) for word in keywords if isinstance(word, str))
    labels = [metric_label_pattern(name, allow_particles=True) for name in sorted(names - {""})]
    for source, clause in clauses:
        mentions = [match for label in labels for match in label.finditer(clause)]
        if not mentions:
            continue
        metric = {"name": mentions[0][0], "definition": clause}
        month = (date if date and date is not CONFLICTING_DATES
                 and not isinstance(date, DateRange) and date[2] is None else None)
        period = metric_date(metric, expected_month=month)[1]
        if not scope_matches(reference, metric, date, period, allow_undated=allow_undated):
            continue
        excluded = mentions + [match for match in DATE_SCOPE.finditer(clause) if is_date_mention(match)]
        for number in NUMBER_IN_TEXT.finditer(clause):
            if any(number.start() < match.end() and match.start() < number.end() for match in excluded):
                continue
            tail = clause[number.end():]
            if re.match(r"[a-zA-Z]", tail):
                unit = UNIT_SUFFIX.match(tail)
                if not unit or not all(unit_parts(unit[1])):
                    continue
            for mention in mentions:
                between = clause[mention.end():number.start()]
                follows_label = number.start() >= mention.end() and (
                    not between.strip(" \t*\x60_(),:=|") or VALUE_PREDICATE.search(between)
                )
                precedes_label = number.end() <= mention.start() and VALUE_FOR_METRIC.search(
                    clause[number.end():mention.start()]
                )
                if follows_label or precedes_label or ARITHMETIC_IN_TEXT.match(clause[number.start():]):
                    start = max(0, min(mention.start(), number.start()) - 20, number.end() - 180)
                    return {"source": source, "excerpt": clause[start:start + 200].strip()}
    return None


def transcript_metrics(text, expected_metrics, *, is_report=False):
    """Read explicitly named numeric evidence from transcript or report text."""
    claims = {}
    scanned = set()
    clauses = text_clauses(text)
    for reference in expected_metrics:
        name = metric_name(reference)
        if not name or name in scanned:
            continue
        scanned.add(name)
        label = metric_label_pattern(name)
        for clause_index, clause in enumerate(clauses):
            for match in label.finditer(clause):
                remainder = clause[match.end():]
                tail = remainder.lstrip(" \t*`_(:=|")
                delimiter = remainder[:len(remainder) - len(tail)]
                short_date = SHORT_DAY.match(tail)
                if date_range := DATE_RANGE.match(tail):
                    tail = tail[date_range.end():]
                elif short_date:
                    tail = tail[short_date.end():]
                elif (date := DATE_SCOPE.match(tail)) and is_date_mention(date):
                    tail = tail[date.end():]
                tail = tail.lstrip(" \t*`_():=|")
                if "(" in delimiter and DAY_QUALIFIER.match(tail):
                    continue
                found = {
                    "name": match[0],
                    "definition": clause,
                    "conditional": bool(CONDITIONAL.search(clause)),
                }
                if short_date:
                    found["date"] = short_date[0]
                prefix = clause[:match.start()].rstrip(" \t*`_(:=|")
                if prefix_day := next((day for day in SHORT_DAY.finditer(prefix) if day.end() == len(prefix)), None):
                    found["name"] = f"{prefix_day[0]} {found['name']}"
                if formula := FORMULA.match(tail):
                    value_text = formula[3]
                    for field, value in zip(("numerator", "denominator", "value"), formula.groups()):
                        found[field] = parse_number(value)
                elif number := re.match(NUMBER, tail):
                    value_text = number[0]
                    found["value"] = parse_number(value_text)
                    for field in ("numerator", "denominator"):
                        component = re.search(rf"\b{field}\s*[:=]\s*({NUMBER})", tail, re.IGNORECASE)
                        if component:
                            found[field] = parse_number(component[1])
                else:
                    continue
                if is_report:
                    mantissa = re.split(r"[eE]", value_text, maxsplit=1)[0]
                    found["_display_decimals"] = len(mantissa.partition(".")[2])
                numeric_end = (formula or number).end()
                unit_tail = tail[numeric_end:].lstrip(" \t*`_")
                if unit := UNIT_SUFFIX.match(unit_tail):
                    label_unit = unit[1]
                    if not all(unit_parts(label_unit)):
                        label_unit = KOREAN_UNIT_ENDING.sub("", label_unit)
                    if any(unit_parts(label_unit)):
                        found["unit"] = label_unit
                    elif any(mark in delimiter for mark in ":=|") and UNIT_END.fullmatch(unit_tail[unit.end():]):
                        found["unit"] = unit[1]
                claim = (clause_index, len(clause) - len(tail) + numeric_end)
                previous = claims.get(claim)
                if previous is None or len(found["name"]) > len(previous["name"]):
                    claims[claim] = found
    return list(claims.values())


def displayed_value_rows(rows, dates):
    for index, metric, fields, period, name in rows:
        value = fields.get("value")
        if isinstance(value, list) and len(value) == len(dates):
            for day, day_value in zip(dates, value):
                if day_period := parse_period(day):
                    yield index, metric, {**fields, "value": day_value}, day_period, name
        else:
            yield index, metric, fields, period, name


def delivery_results_path(run):
    path = run / "delivery/results.json"
    if path.is_file() and not path.is_symlink() and not path.parent.is_symlink():
        return path
    return None


def delivery_evidence(run, references):
    path = delivery_results_path(run)
    meta = run / "meta.json"
    if path is None or not meta.is_file() or read_json(meta).get("condition") != "skill":
        return [], []
    try:
        data = read_json(path)
        json.dumps(data, allow_nan=False)
    except (OSError, ValueError):
        return [], []
    if not isinstance(data, dict):
        return [], []

    names = {metric_name(reference) for reference in references}
    rows, text = [], []

    def add_metric(metric):
        if (isinstance(metric, dict) and isinstance(metric.get("name"), str)
                and metric["name"].strip()
                and type(comparable_fields(metric).get("value")) in (int, float, list)
                and (metric.get("unit") is None or isinstance(metric["unit"], str))):
            rows.append(metric)

    def add_claims(section):
        if isinstance(section, str):
            text.append(section)
        elif isinstance(section, list):
            for item in section:
                if isinstance(item, str):
                    text.append(item)
                else:
                    add_metric(item)
        elif isinstance(section, dict):
            for name, value in section.items():
                if metric_name({"name": name}) not in names:
                    continue
                if isinstance(value, str):
                    text.append(f"{name}: {value}")
                elif isinstance(value, dict):
                    add_metric({**value, "name": name})
                elif type(value) in (int, float):
                    add_metric({"name": name, "value": value})

    if isinstance(data.get("metrics"), list):
        add_claims(data["metrics"])
    for field in ("summary", "findings", "results"):
        add_claims(data.get(field))
    add_claims(data)
    return rows, transcript_metrics("\n".join(text), references)


def conflicting_delivery_rows(reference, rows, delivery_rows, tolerance, *, allow_undated,
                              mapped_evidence=False):
    expected = comparable_fields(reference)
    for index, metric, fields, period, name in rows:
        left = fields | {key: expected[key] for key in omitted_components(expected, fields) if key in expected}
        for other_index, other, observed, other_period, other_name in delivery_rows:
            if (other_index == index or name != other_name or period != other_period
                    or metric.get("condition") != other.get("condition")
                    or not scope_matches(reference, other, metric_date(reference)[1], other_period,
                                         allow_undated=allow_undated, mapped_evidence=mapped_evidence)):
                continue
            right = observed | {key: expected[key] for key in omitted_components(expected, observed)
                                if key in expected}
            if (not match_value(fields["value"], observed["value"], tolerance, unit_methods(metric, other))
                    or any(not agrees(left[key], right[key], tolerance)
                           for key in ("numerator", "denominator") if key in left and key in right)):
                return [fields, observed]
    return []


def allows_undated(periods, dated_periods, evaluation_days):
    identified = set(periods) - {None}
    if len(identified) != 1 or CONFLICTING_DATES in identified:
        return False
    period = next(iter(identified))
    if evaluation_days and not isinstance(period, DateRange) and period[2] is not None:
        return len(dated_periods) == 1 and dates_match(period, next(iter(evaluation_days)))
    return None not in periods and len(dated_periods) <= 1


def compare_metrics(required, optional, actual, tolerance, dates, *, named_evidence=False,
                    report_metrics=None, report_source=None, sign_agnostic_metrics=(), allow_undated=None,
                    evidence_clauses=(), report_aliases=(), fallback_evidence=(), evidence_source=None,
                    mapped_evidence=False):
    results = {bucket: [] for bucket in ("matched", "missing", "mismatched", "unparsed", "unverified", "extra")}
    dated_periods = {period for day in dates if (period := parse_period(day))}
    evaluation_days = {period for period in dated_periods
                       if not isinstance(period, DateRange) and period[0] is not None and period[2] is not None}
    # The mapper supplies this group for a single reference. Keep the original
    # evidence name for date and scope checks, and use the target for identity.
    mapped_name = metric_name(required[0]) if mapped_evidence else None

    def evidence_row(index, metric):
        return (index, metric, comparable_fields(metric), submitted_period(metric, evaluation_days),
                mapped_name if mapped_evidence else metric_name(metric))

    available = {i: evidence_row(i, metric) for i, metric in enumerate(actual)}
    text_rows = tuple(available.values()) if named_evidence else ()
    delivery_source = evidence_source == "results.json"
    delivery_rows = tuple(available.values()) if (delivery_source or mapped_evidence) and not named_evidence else ()
    references = required + optional
    entries = []
    periods = []
    for i, reference in enumerate(references):
        entry = {"name": reference["name"], "expected": comparable_fields(reference),
                 "required": i < len(required)}
        label, period = metric_date(reference)
        if label:
            entry["date"] = label
        entries.append(entry)
        periods.append(period)
    if allow_undated is None:
        allow_undated = allows_undated(periods, dated_periods, evaluation_days)
    if report_metrics is not None:
        report_file, report_claims = report_metrics()
    else:
        report_file, report_claims = None, ()
    report_rows = (() if named_evidence and not (delivery_source or mapped_evidence) else
                   tuple(evidence_row(i, metric)
                         for i, metric in enumerate(chain(report_claims, report_aliases),
                                                    start=-len(report_claims) - len(report_aliases))))

    def record(reference, entry, indices, observed, method=None):
        entry["actual"] = observed
        rows = [available.pop(i) for i in indices]
        entry["actual_names"] = [row[1]["name"] for row in rows]
        if report_source is not None:
            entry.update(source="report_html", source_path=report_source)
        if evidence_source:
            entry["source"] = evidence_source
            if delivery_source:
                entry["source_path"] = "delivery/results.json"
        expected_unit = reference.get("unit")
        name = metric_name(reference)
        methods = []
        for _, metric, _, _, actual_name in rows:
            same_identity = name == actual_name
            allowed = unit_methods(reference, metric, allow_count_notation=same_identity)
            methods.append(allowed)
            actual_unit = metric.get("unit")
            units = comparison_units(expected_unit, actual_unit) if same_identity else (expected_unit, actual_unit)
            if not allowed and unknown_unit_mismatch(*units):
                entry.update(reason="unknown_unit", units={"expected": expected_unit, "actual": actual_unit})
                return "unverified"
        omitted = ()
        if method is None and len(rows) == 1:
            omitted = omitted_components(entry["expected"], observed, same_identity=rows[0][4] == name)
        differences = field_differences(entry["expected"], observed, tolerance,
                                        tuple_matched=method is not None, omitted=omitted)
        if method is None and any(not allowed for allowed in methods):
            entry_unit = next(row[1].get("unit") for row, allowed in zip(rows, methods) if not allowed)
            differences["unit"] = {"expected": expected_unit, "actual": entry_unit}
        elif method is None and "value" in entry["expected"] and "value" in observed:
            value = entry["expected"]["value"]
            if len(rows) == 1:
                values_match = match_value(value, observed["value"], tolerance, methods[0])
            else:
                values_match = len(value) == len(rows) and all(
                    match_value(expected, row[2]["value"], tolerance, allowed)
                    for expected, row, allowed in zip(value, rows, methods)
                )
            if values_match:
                differences.pop("value", None)
            else:
                differences["value"] = {"expected": value, "actual": observed["value"]}
        if text_rows and not entry["expected"].get("conditional"):
            if claims := conflicting_text_claims(reference, rows, text_rows, tolerance,
                                                 allow_undated=allow_undated, mapped_evidence=mapped_evidence):
                conflict = ("results_conflict" if delivery_source else "report_conflict"
                            if report_source is not None else "transcript_conflict")
                differences[conflict] = {"claims": claims}
        if delivery_rows and not differences:
            if claims := conflicting_delivery_rows(reference, rows, delivery_rows, tolerance,
                                                   allow_undated=allow_undated, mapped_evidence=mapped_evidence):
                differences["results_conflict"] = {"claims": claims}
        if report_rows and not differences:
            if claims := conflicting_text_claims(reference, displayed_value_rows(rows, dates), report_rows,
                                                 tolerance, allow_undated=allow_undated, against_summary=True,
                                                 mapped_evidence=mapped_evidence):
                entry.update(reason="report_conflict", source="report_html", source_path=report_file)
                differences["report_conflict"] = {"claims": claims}
        if differences:
            entry["differences"] = differences
            return "mismatched"
        entry["matched_via"] = method or "name"
        return "matched"

    outcomes = {}
    sign_agnostic = {i for i, entry in enumerate(entries)
                     if entry["name"] in sign_agnostic_metrics and isinstance(entry["expected"].get("value"), list)}

    def scoped_candidates(reference, date):
        name = metric_name(reference)
        is_series = isinstance(comparable_fields(reference).get("value"), list)

        def in_evaluation_range(row):
            period = row[3]
            if period is CONFLICTING_DATES:
                return False
            if period is None or date is not None:
                return True
            if not isinstance(period, DateRange):
                return (not dated_periods or is_series or not is_aggregate(row[1])
                        or len(dated_periods) == 1 and dates_match(next(iter(dated_periods)), period))
            if not (mapped_evidence or row[4] == name and is_aggregate(row[1])):
                return False
            return (not dated_periods or dated_periods == {period}
                    or evaluation_days == dated_periods and (min(evaluation_days), max(evaluation_days)) == period)

        candidates = (candidate_for_period(row, date) for row in available.values()
                      if row[4] == name or not (named_evidence or delivery_source))
        return [row for row in candidates if in_evaluation_range(row)
                and scope_matches(reference, row[1], date, row[3], allow_undated=allow_undated,
                                  mapped_evidence=mapped_evidence)]

    # Allocate complete tuples before using rows as evidence of a mismatch.
    for match_condition in (True, False):
        for direction in (1, -1):
            for i, (reference, entry) in enumerate(zip(references, entries)):
                if i in outcomes or (direction == -1 and i not in sign_agnostic):
                    continue
                date = periods[i]
                candidates = scoped_candidates(reference, date)
                match = select_metric_tuple(reference, entry, date, dates, candidates, tolerance,
                                            match_condition=match_condition, direction=direction)
                if match:
                    indices, observed, method = match
                    if direction == -1:
                        method += "+sign_reversed"
                    outcomes[i] = record(reference, entry, indices, observed, method)

    for i, (reference, entry) in enumerate(zip(references, entries)):
        if i not in outcomes:
            date = periods[i]
            name = metric_name(reference)
            names = {name}
            if isinstance(line := reference.get("line"), str) and (line_name := metric_name({"name": line})):
                names.update((f"{line_name} {name}", f"{name} {line_name}"))
            fields = entry["expected"]
            candidates = scoped_candidates(reference, date)
            named = [row for row in candidates if row[4] in names
                     and (date is None or row[3] is None or dates_match(date, row[3]))]
            if named:
                index, _, observed, _, _ = named[0]
                daily = []
                if isinstance(fields.get("value"), list) and not isinstance(observed.get("value"), list):
                    daily = [[row for row in named if dates_match(parse_period(day), row[3])]
                             for day in dates]
                if (daily and all(len(rows) == 1 for rows in daily)
                        and len({rows[0][0] for rows in daily}) == len(daily)):
                    rows = [matches[0] for matches in daily]
                    outcomes[i] = record(reference, entry, [row[0] for row in rows],
                                         combine_fields([row[2] for row in rows], fields))
                else:
                    outcomes[i] = record(reference, entry, [index], observed)
            elif i in sign_agnostic and (
                mixed := select_metric_tuple(reference, entry, date, dates, candidates, tolerance,
                                             match_condition=False, direction=0)
            ):
                # Equal magnitudes identify the series, but a mixed direction is a mismatch.
                indices, observed, _ = mixed
                outcomes[i] = record(reference, entry, indices, observed)
            elif reference.get("unit") is not None and (
                unscaled := select_metric_tuple(reference, entry, date, dates, candidates, tolerance,
                                                match_condition=False, check_units=False)
            ):
                indices, observed, _ = unscaled
                outcomes[i] = record(reference, entry, indices, observed)
        if i in outcomes:
            results[outcomes[i]].append(entry)

    if (fallback_evidence or report_metrics is not None) and len(outcomes) < len(references):
        pending = [reference for i, reference in enumerate(required) if i not in outcomes]
        pending_optional = [reference for i, reference in enumerate(optional, start=len(required))
                            if i not in outcomes]
        if fallback_evidence:
            (metrics, named, fallback_source), *remaining = fallback_evidence
            fallback = compare_metrics(pending, pending_optional, metrics, tolerance, dates,
                                       named_evidence=named, evidence_source=fallback_source,
                                       report_metrics=report_metrics, fallback_evidence=remaining,
                                       sign_agnostic_metrics=sign_agnostic_metrics,
                                       allow_undated=allow_undated, evidence_clauses=evidence_clauses)
        else:
            fallback = compare_metrics(pending, pending_optional, report_claims, tolerance, dates,
                                       named_evidence=True, report_source=report_file,
                                       sign_agnostic_metrics=sign_agnostic_metrics,
                                       allow_undated=allow_undated, evidence_clauses=evidence_clauses)
        for bucket in ("matched", "mismatched", "missing", "unparsed", "unverified"):
            results[bucket].extend(fallback[bucket])
    else:
        for i, reference in enumerate(required):
            if i in outcomes:
                continue
            entry = entries[i]
            if evidence := unparsed_excerpt(reference, periods[i], evidence_clauses,
                                            allow_undated=allow_undated):
                entry.update(evidence)
                results["unparsed"].append(entry)
            else:
                results["missing"].append(entry)
    results["extra"] = [row[1] for row in available.values()]
    return results


def check_run(run, flow, expected, summary, report):
    definition = expected["flows"][flow]
    tolerance = expected["absolute_tolerance"]
    if type(tolerance) not in (float, int):
        raise ValueError("absolute_tolerance must be numeric")
    tolerance_decimal = Decimal(str(tolerance))
    if not tolerance_decimal.is_finite() or tolerance_decimal < 0:
        raise ValueError("absolute_tolerance must be finite and nonnegative")
    required = metric_list(definition["metrics"])
    optional = metric_list(definition.get("optional_metrics", []))
    summary_error = None
    results_as_summary = summary is not None and summary.name == "results.json"
    if summary:
        source = "results.json(summary)" if results_as_summary else "eda_summary.json"
        try:
            submitted = read_json(summary)
            validate_sidecar(submitted)
            actual = metric_list(submitted["metrics"])
        except (OSError, ValueError, KeyError, TypeError) as error:
            summary_error = f"Invalid {summary.name} schema or content: {error}"
            actual = []
    transcript = last_analyst_text(run, strict=summary is None) if not summary_error else ""
    fallback_evidence = []
    evidence_source = None
    named_evidence = summary is None
    if not summary_error and not results_as_summary:
        rows, claims = delivery_evidence(run, required + optional)
        fallback_evidence = [(metrics, named, "results.json") for metrics, named in ((rows, False), (claims, True))
                             if metrics]
    if not summary:
        actual = transcript_claims = transcript_metrics(transcript, required + optional)
        source = "transcript_text"
        if fallback_evidence:
            if actual:
                fallback_evidence.append((actual, True, "transcript_text"))
            actual, named_evidence, evidence_source = fallback_evidence.pop(0)

    evidence_clauses = [("transcript_text", clause) for clause in text_clauses(transcript)]
    from_report = None
    report_aliases = ()
    if report and not summary_error:
        text = reports_text(run, report, for_grader=False)
        report_file = report.relative_to(run).as_posix()
        report_claims = transcript_metrics(text, required + optional, is_report=True)
        if summary:
            names = {metric_name(metric) for metric in required + optional}
            aliases = [metric for metric in actual if metric_name(metric) not in names]
            report_aliases = transcript_metrics(text, aliases, is_report=True)
        evidence_clauses.extend(("report_html", clause) for clause in text_clauses(text))

        def from_report():
            return report_file, report_claims

    comparison = compare_metrics(required, optional, actual, tolerance_decimal,
                                 expected.get("dates_in_order", []), named_evidence=named_evidence,
                                 evidence_source=evidence_source, fallback_evidence=fallback_evidence,
                                 report_metrics=from_report, evidence_clauses=evidence_clauses,
                                 report_aliases=report_aliases,
                                 sign_agnostic_metrics=definition.get("sign_agnostic_metrics", ()))
    if not summary:
        evidence = {entry.get("source") for bucket in ("matched", "mismatched", "unparsed", "unverified")
                    for entry in comparison[bucket]}
        if "results.json" in evidence:
            source = "results.json"
        elif not transcript_claims and "report_html" in evidence:
            source = "report_html"
    result = {
        "source": source,
        "absolute_tolerance": tolerance,
        **comparison,
    }
    if summary_error:
        result["summary_error"] = summary_error
    (run / "numeric_check.json").write_text(json_text(result) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    run = parser.parse_args().run.resolve()
    try:
        _, flow, expected = load_expected(run)
        summary = summary_path(run)
        check_run(run, flow, expected, summary, report_path(run, summary))
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(1, f"Numeric check failed: {error}\n")
    print(f"Numeric check saved to {run / 'numeric_check.json'}")


if __name__ == "__main__":
    main()
