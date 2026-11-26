"""Build an offline HTML report and its validated eda_summary.json sidecar."""

import argparse
import ast
import base64
from contextlib import contextmanager
from decimal import Decimal
import errno
from fractions import Fraction
from hashlib import sha256
from html import escape
from io import BytesIO, StringIO
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
from shutil import copy2
from string import Template
import sys
from tempfile import NamedTemporaryFile, TemporaryDirectory
import time
import tokenize

try:
    import fcntl
except ImportError:
    fcntl = None

try:
    import msvcrt
except ImportError:
    msvcrt = None

sys.path.insert(0, str(Path(__file__).resolve().parent))

SKILL_DIR = Path(__file__).resolve().parents[1]
SCHEMA_PATH = SKILL_DIR / "references" / "eda_summary.schema.json"
SCHEMA_VERSION = "1.0.0"
TEMPLATE_PATH = SKILL_DIR / "templates" / "report.html"
PLOT_METADATA = ("type", "source_columns", "n_used", "n_excluded", "exclusion_reason")
CHART_NOTES = (
    ("observation", "Observation", "관찰"),
    ("domain_interpretation", "Domain interpretation", "도메인 해석"),
    ("hypothesis", "Hypothesis", "가설"),
    ("next_check", "Next check", "다음 확인"),
)
SUMMARY_FIELDS = ("headline", "kpis", "key_charts", "insights")
BANNED_PHRASE = re.compile(r"이\s+보고서는|본\s+보고서|살펴보겠|\b(?:in\s+)?this\s+report\b", re.I)
KOREAN_FIELDS = {
    "metric": {
        "definition": "정의", "numerator": "분자", "denominator": "분모",
        "condition": "조건", "depends_on_ambiguity_ids": "관련 모호성 ID", "source_refs": "근거 위치",
    },
    "data_overview": {
        "datasets": "데이터 세트", "row_grain": "행 단위", "format_evidence": "형식 판단 근거",
    },
    "datasets": {
        "id": "ID", "format": "형식", "read_ranges": "읽은 범위", "unread": "읽지 못한 범위",
        "rows": "행 수", "columns": "열 수",
    },
    "ambiguity_log": {
        "id": "ID", "checklist_item": "확인 항목", "question": "질문", "file_evidence": "파일 근거",
        "candidates": "후보 답변", "status": "상태", "answer": "답변", "affects": "영향 범위",
    },
    "reproducibility": {
        "filters": "필터", "exclusions": "제외 내역", "transforms": "변환 단계",
        "sample_sizes": "표본 크기", "source_locators": "원본 위치",
    },
    "exclusions": {"scope": "적용 범위", "source_refs": "근거 위치", "reason": "사유"},
    "transforms": {
        "input": "입력", "transform": "변환", "output": "결과", "before": "변환 전", "after": "변환 후",
    },
}
KOREAN_STATUSES = {
    "resolved": "해결", "user_assumed": "사용자 가정", "unresolved": "미해결", "not_applicable": "해당 없음",
}
LOCAL_PATH_PREFIX = r"(?:file://)?(?:/(?![/\s])|[A-Za-z]:[/\\]|\\\\)"
PATH_FIELDS = {"file", "path", "file_path", "image_path", "input_path", "output_path", "source_path"}
ABSOLUTE_PATH = re.compile(
    rf"""(?P<quote>['"\x60])(?P<quoted>{LOCAL_PATH_PREFIX}(?:(?!(?P=quote))[^\r\n])+)(?P=quote)"""
    rf"""|(?<![\w./~\\$'")\]}}<-])(?P<bare>{LOCAL_PATH_PREFIX}[^\s'"\x60:;,()\[\]{{}}<>]+)"""
)
PYTHON_STRING = re.compile(r"""([rRuUfFbB]*)('''|\"\"\"|'|\")""")
FSTRING_MIDDLE = getattr(tokenize, "FSTRING_MIDDLE", None)
LOCK_WAIT_SECONDS = 30
LOCK_RETRY_SECONDS = 0.05
LOCK_STALE_SECONDS = 300


class ReportResult(tuple):
    """The two output paths, with build warnings available as an attribute."""

    def __new__(cls, paths, warnings=()):
        result = super().__new__(cls, paths)
        result.warnings = list(warnings)
        return result


def shorten_path(text, directory, *, embedded=False):
    if not isinstance(text, str):
        return text
    local = text.removeprefix("file://")
    windows_path = PureWindowsPath(local)
    windows = windows_path.is_absolute()
    path = windows_path if windows else PurePosixPath(local)
    if not path.is_absolute() or not path.name:
        return text
    home = Path.home()
    under_home = path.is_relative_to(home)
    parts = path.parts[1:]
    has_home_prefix = len(parts) >= 2 and (
        parts[0].casefold() == "users" if windows else parts[0] in ("Users", "home")
    )
    trailing_separator = local.endswith("/") or (windows and local.endswith("\\"))
    if embedded and not (under_home or has_home_prefix):
        if len(parts) < 2 or not path.suffix or trailing_separator:
            return text

    if under_home:
        display = (Path("~") / path.relative_to(home)).as_posix()
    elif embedded and has_home_prefix and len(parts) == 2:
        display = "~"
    elif path.is_relative_to(directory):
        display = path.relative_to(directory).as_posix()
    else:
        display = path.name
    return f"{display}/" if embedded and trailing_separator else display


def normalize_text_paths(text, directory):
    from eda_io import JSON_PATH

    if JSON_PATH.fullmatch(text):
        return text

    def shorten(match):
        if match["quoted"] is not None:
            display = shorten_path(match["quoted"], directory, embedded=True)
            return f'{match["quote"]}{display}{match["quote"]}'
        bare = match["bare"]
        candidate = bare.rstrip(".!?")
        return shorten_path(candidate, directory, embedded=True) + bare[len(candidate):]

    return ABSOLUTE_PATH.sub(shorten, text)


def normalize_code_string(source, directory):
    opening = PYTHON_STRING.match(source)
    if opening is None:
        return source
    prefix, quote = opening.groups()
    if "f" in prefix.lower():
        # Before Python 3.12, tokenize returns the whole f-string as one token.
        body = source[opening.end():-len(quote)]
        shortened = normalize_text_paths(body, directory)
        if shortened == body:
            return source
        replacement = f"{opening[0]}{shortened}{quote}"
        try:
            ast.parse(replacement, mode="eval")
        except SyntaxError:
            return source
        return replacement

    try:
        value = ast.literal_eval(source)
    except (SyntaxError, ValueError):
        return source
    is_bytes = isinstance(value, bytes)
    text = value.decode("utf-8", errors="surrogateescape") if is_bytes else value
    shortened = text
    if re.fullmatch(rf"{LOCAL_PATH_PREFIX}[^\r\n]*", text):
        shortened = shorten_path(text, directory, embedded=True)
    if shortened == text:
        shortened = normalize_text_paths(text, directory)
    if shortened == text:
        return source
    if shortened.isprintable() and (not is_bytes or shortened.isascii()) and (
        quote[0] not in shortened and "\\" not in shortened
    ):
        return f"{opening[0]}{shortened}{quote}"
    if is_bytes:
        return repr(shortened.encode("utf-8", errors="surrogateescape"))
    return repr(shortened)


def normalize_code_paths(code, directory):
    """Rewrite paths in text tokens without touching Python operators."""
    line_starts = [0, *(match.end() for match in re.finditer(r"\r\n?|\n", code))]
    parts = []
    cursor = 0
    try:
        for token in tokenize.generate_tokens(StringIO(code, newline=None).readline):
            if token.type == tokenize.STRING:
                replacement = normalize_code_string(token.string, directory)
            elif token.type in (tokenize.COMMENT, FSTRING_MIDDLE):
                replacement = normalize_text_paths(token.string, directory)
            else:
                continue
            if replacement == token.string:
                continue
            start = line_starts[token.start[0] - 1] + token.start[1]
            end = line_starts[token.end[0] - 1] + token.end[1]
            parts.extend((code[cursor:start], replacement))
            cursor = end
    except (SyntaxError, tokenize.TokenError):
        # A reproduction excerpt may be incomplete.
        pass
    parts.append(code[cursor:])
    return "".join(parts)


def normalize_report_paths(value, directory, field=None):
    """Shorten local paths without changing the input spec."""
    if isinstance(value, dict):
        normalized = {}
        for key, item in value.items():
            shortened = label = shorten_path(key, directory)
            if shortened != key:
                # Different source paths can share the same display name.
                suffix = 2
                while label in value or label in normalized:
                    label = f"{shortened} ({suffix})"
                    suffix += 1
            if field == "reproducibility" and key == "code" and isinstance(item, str):
                normalized[label] = normalize_code_paths(item, directory)
            else:
                normalized[label] = normalize_report_paths(item, directory, key)
        return normalized
    if isinstance(value, list):
        return [normalize_report_paths(item, directory, field) for item in value]
    if not isinstance(value, str):
        return value
    if field in PATH_FIELDS:
        return shorten_path(value, directory)
    return normalize_text_paths(value, directory)


def fallback_validate(value, rule, schema, path="$"):
    """Validate the keywords used by the bundled Draft 2020-12 schema."""
    if "$ref" in rule:
        ref = rule["$ref"]
        if not ref.startswith("#/$defs/"):
            raise ValueError(f"{path}: unsupported schema reference {ref!r}.")
        fallback_validate(value, schema["$defs"][ref.removeprefix("#/$defs/")], schema, path)
    checks = {
        "object": lambda: isinstance(value, dict),
        "array": lambda: isinstance(value, list),
        "string": lambda: isinstance(value, str),
        "null": lambda: value is None,
        "integer": lambda: type(value) is int or (
            type(value) is float and math.isfinite(value) and value.is_integer()),
        "number": lambda: type(value) is int or (type(value) is float and math.isfinite(value)),
    }
    types = rule.get("type", [])
    if isinstance(types, str):
        types = [types]
    if types and not any(checks[kind]() for kind in types):
        raise ValueError(f"{path}: expected {' or '.join(types)}.")
    if "enum" in rule and value not in rule["enum"]:
        raise ValueError(f"{path}: expected one of {rule['enum']!r}.")
    if isinstance(value, str) and "pattern" in rule and not re.search(rule["pattern"], value):
        raise ValueError(f"{path}: must match {rule['pattern']!r}.")
    if value is not None and "minimum" in rule and value < rule["minimum"]:
        raise ValueError(f"{path}: must be at least {rule['minimum']}.")
    if "exclusiveMinimum" in rule and value <= rule["exclusiveMinimum"]:
        raise ValueError(f"{path}: must be greater than {rule['exclusiveMinimum']}.")
    if isinstance(value, dict):
        for required in rule.get("required", []):
            if required not in value:
                raise ValueError(f"{path}.{required}: required property is missing.")
        properties = rule.get("properties", {})
        additional = rule.get("additionalProperties")
        if additional is False and (extra := value.keys() - properties.keys()):
            raise ValueError(f"{path}: unexpected properties {sorted(extra)!r}.")
        for key, child_rule in properties.items():
            if key in value:
                fallback_validate(value[key], child_rule, schema, f"{path}.{key}")
        if isinstance(additional, dict):
            for key, item in value.items():
                if key not in properties:
                    fallback_validate(item, additional, schema, f"{path}.{key}")
    if isinstance(value, list):
        if "minItems" in rule and len(value) < rule["minItems"]:
            raise ValueError(f"{path}: expected at least {rule['minItems']} item(s).")
        if "items" in rule:
            for index, entry in enumerate(value):
                fallback_validate(entry, rule["items"], schema, f"{path}[{index}]")


def validate_summary(summary):
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    # JSON Schema assumes JSON values. Check this before either validator.
    json.dumps(summary, allow_nan=False)
    try:
        from jsonschema import Draft202012Validator
    except ImportError:
        fallback_validate(summary, schema, schema)
    else:
        error = next(Draft202012Validator(schema).iter_errors(summary), None)
        if error is not None:
            raise ValueError(f"{error.json_path}: {error.message}")


def validate_dependencies(summary):
    ambiguities = {}
    for entry in summary["ambiguity_log"]:
        identifier = entry["id"]
        if not identifier.strip() or identifier in ambiguities:
            raise ValueError(f"Empty or duplicate ambiguity id: {identifier!r}.")
        ambiguities[identifier] = entry["status"]
    identifiers = set()
    for chart in summary["charts"]:
        identifier = chart["id"]
        if not identifier.strip() or identifier in identifiers:
            raise ValueError(f"Empty or duplicate chart id: {identifier!r}.")
        identifiers.add(identifier)
    for metric in summary["metrics"]:
        dependencies = metric["depends_on_ambiguity_ids"]
        unknown = set(dependencies) - ambiguities.keys()
        if unknown:
            raise ValueError(f"Metric {metric['name']!r} references unknown ambiguity ids: {sorted(unknown)!r}.")
        if any(ambiguities[identifier] == "unresolved" for identifier in dependencies):
            if not metric["condition"] or not metric["condition"].strip():
                raise ValueError(f"Metric {metric['name']!r} requires a condition for unresolved ambiguity.")
    return ambiguities


def validate_metric_values(summary):
    """Check that reported rates match their unrounded results within numerical tolerance."""
    for metric in summary["metrics"]:
        numerator, denominator, value = (metric[key] for key in ("numerator", "denominator", "value"))
        if type(denominator) in (int, float) and denominator == 0:
            if value is not None:
                raise ValueError(f"Metric {metric['name']!r}: expected null for a zero denominator, got {value!r}.")
            continue
        if any(type(component) not in (int, float) for component in (numerator, denominator, value)):
            continue

        scale = metric.get("scale", 100 if metric["unit"] == "%" else 1)
        reported = Fraction(str(value))
        expected = Fraction(str(numerator)) * Fraction(str(scale)) / Fraction(str(denominator))
        tolerance = abs(expected) / 10**9
        if abs(reported - expected) > tolerance:
            expected_decimal = Decimal(expected.numerator) / Decimal(expected.denominator)
            raise ValueError(f"Metric {metric['name']!r}: expected {expected_decimal:.16g}, got {value!r}.")


def check_metric_sources(metrics, kpis):
    warnings = []
    for index, metric in enumerate(metrics):
        if not metric["source_refs"]:
            message = f"Metric {metric['name']!r} has empty source_refs."
            if index in kpis:
                raise ValueError(message)
            warnings.append(message)
    return warnings


def merge_plot_results(charts, results):
    if not isinstance(results, list):
        raise ValueError("plot-results must be a JSON array of chart objects.")
    chart_ids = {chart["id"] for chart in charts}
    by_id = {}
    for entry in results:
        identifier = entry.get("id") if isinstance(entry, dict) else None
        if not isinstance(identifier, str) or not identifier.strip():
            raise ValueError("Each plot-results entry must have a nonempty chart id.")
        if identifier in by_id:
            raise ValueError(f"Chart {identifier!r} appears more than once in plot-results.")
        if identifier not in chart_ids:
            raise ValueError(f"Chart {identifier!r} in plot-results is missing from the report spec.")
        by_id[identifier] = entry

    merged = []
    for chart in charts:
        identifier = chart["id"]
        rendered = by_id.get(identifier)
        if rendered is None:
            if not chart.get("image_path"):
                raise ValueError(f"Chart {identifier!r} is missing from plot-results and has no direct image_path.")
            merged.append(chart)
            continue

        for field in PLOT_METADATA:
            if field in chart and (
                field not in rendered or isinstance(rendered[field], bool) or chart[field] != rendered[field]
            ):
                raise ValueError(f"Chart {identifier!r}: {field} differs between the report spec and plot-results.")
        reason = rendered.get("exclusion_reason")
        if reason is not None and not isinstance(reason, str):
            raise ValueError(f"Chart {identifier!r}: plot-results exclusion_reason must be a string or null.")
        combined = {field: rendered[field] for field in PLOT_METADATA if field in rendered}
        combined.update(chart)
        if rendered.get("image_path"):
            combined["image_path"] = rendered["image_path"]
        elif not combined.get("image_path"):
            raise ValueError(f"Chart {identifier!r} has no image_path in the report spec or plot-results.")
        merged.append(combined)
    return merged


def file_sha256(path):
    digest = sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_provenance(input_paths, figures):
    skill_version = (SKILL_DIR / "VERSION").read_text(encoding="utf-8").strip()
    return {
        "inputs": [{"name": path.name, "sha256": file_sha256(path)} for path in input_paths],
        "skill_version": skill_version,
        "schema_version": SCHEMA_VERSION,
        "builder": f"build_report.py@{skill_version}",
        "outputs": [{"path": path, "sha256": digest} for path, digest in figures.items()],
    }


def make_summary(spec):
    overview = spec["data_overview"]
    reproduction = spec["reproducibility"]
    optional_fields = ("n_used", "n_excluded", "exclusion_reason", "pairwise_n")
    return {
        "datasets": overview["datasets"] if isinstance(overview, dict) else overview,
        "row_counts": reproduction["transforms"],
        "metrics": spec["metrics"],
        "ambiguity_log": spec["ambiguity_log"],
        "charts": [{"id": chart["id"], "question": chart["question"],
                    "type": chart.get("type", "unknown"), "source_columns": chart.get("source_columns", []),
                    **{key: chart[key] for key in optional_fields if key in chart}}
                   for chart in spec["charts"]],
        "exclusions": reproduction["exclusions"],
    }


def check_limit(value, field, limit, unit):
    if len(value) > limit:
        raise ValueError(
            f"{field}: {len(value)} {unit} exceeds the limit of {limit} by {len(value) - limit}."
        )


def prepare_summary_panel(spec):
    missing = [field for field in SUMMARY_FIELDS if field not in spec]
    warnings = [f"Legacy report defaults used for {', '.join(missing)}."] if missing else []
    metric_names = [metric["name"] for metric in spec["metrics"]]
    chart_ids = [chart["id"] for chart in spec["charts"]]
    headline = spec.get("headline")
    if "headline" in missing:
        if "summary" not in spec:
            raise ValueError("headline is required unless a legacy summary is supplied.")
        headline = spec["summary"]
        if isinstance(headline, list) and all(isinstance(item, str) for item in headline):
            headline = " ".join(headline)
        if not isinstance(headline, str):
            raise ValueError("Legacy summary must be a string or a list of strings.")
    else:
        if not isinstance(headline, str) or not headline.strip():
            raise ValueError("headline must be a nonempty string.")
        check_limit(headline, "headline", 300, "characters")

    panel = {
        "headline": headline,
        "kpis": spec.get("kpis", metric_names[:4]),
        "key_charts": spec.get("key_charts", chart_ids[:2]),
        "insights": spec.get("insights", []),
    }
    for field, limit in (("kpis", 4), ("key_charts", 2), ("insights", 3)):
        selections = panel[field]
        if not isinstance(selections, list):
            raise ValueError(f"{field} must be a list.")
        check_limit(selections, field, limit, "entries")
    for field, names in (("kpis", metric_names), ("key_charts", chart_ids)):
        known = {}
        for index, name in enumerate(names):
            if field == "kpis" and name in known:
                raise ValueError(f"Duplicate metric name: {name!r}.")
            known[name] = index
        selected = []
        for name in panel[field]:
            if not isinstance(name, str) or name not in known:
                raise ValueError(f"{field} contains an unknown reference: {name!r}.")
            index = known[name]
            if index in selected:
                raise ValueError(f"{field} contains a duplicate reference: {name!r}.")
            selected.append(index)
        panel[field] = selected

    authored = {"headline": headline}
    for index, insight in enumerate(panel["insights"]):
        label = f"insights[{index}]"
        if not isinstance(insight, dict):
            raise ValueError(f"{label} must be an object with text and source.")
        for key in ("text", "source"):
            if not isinstance(insight.get(key), str) or not insight[key].strip():
                raise ValueError(f"{label}.{key} must be a nonempty string.")
        check_limit(insight["text"], f"{label}.text", 200, "characters")
        authored[f"{label}.text"] = insight["text"]
    for index, chart in enumerate(spec["charts"]):
        authored[f"charts[{index}].domain_interpretation"] = chart["domain_interpretation"]

    seen_sentences = {}
    for field, value in authored.items():
        text = value.casefold()
        for phrase in dict.fromkeys(BANNED_PHRASE.findall(text)):
            warnings.append(f"{field}: avoid the report phrase {phrase!r}.")
        sentences = re.split(r"[。！？]+|[.!?]+(?=\s|$)|\n+", text)
        for sentence in (" ".join(part.split()) for part in sentences):
            if not sentence:
                continue
            previous = seen_sentences.get(sentence)
            if previous is None:
                seen_sentences[sentence] = field
            elif previous == field:
                warnings.append(f"Repeated sentence in {field}.")
            else:
                warnings.append(f"Repeated sentence in {previous} and {field}.")
    return panel, list(dict.fromkeys(warnings))


def safe(value):
    return escape(str(value), quote=True)


def fields(value, korean=False, group=None):
    if isinstance(value, dict):
        labels = KOREAN_FIELDS.get(group, {}) if korean else {}
        entries = []
        for key, item in value.items():
            content = fields(item, korean, key)
            if content:
                entries.append(f"<dt>{safe(labels.get(key, key))}</dt><dd>{content}</dd>")
        return f"<dl>{''.join(entries)}</dl>" if entries else ""
    if isinstance(value, list):
        entries = [f"<li>{content}</li>" for item in value if (content := fields(item, korean, group))]
        return f"<ul>{''.join(entries)}</ul>" if entries else ""
    if value is None or (isinstance(value, str) and not value.strip()):
        return ""
    if isinstance(value, bool):
        if korean:
            return "참" if value else "거짓"
        return "true" if value else "false"
    if not isinstance(value, str):
        return safe(value)
    if korean and group == "status":
        value = KOREAN_STATUSES.get(value, value)
    return f'<span class="prose">{safe(value)}</span>'


def metric_value(metric, korean, *, kpi=False):
    value = metric["value"]
    if value is None and type(metric["denominator"]) in (int, float) and metric["denominator"] == 0:
        value = "계산 불가 (분모 0)" if korean else "Undefined (zero denominator)"
    if type(value) is float:
        value = f"{value:,.2f}".rstrip("0").rstrip(".") if abs(value) >= 1 else f"{value:.4g}"
    elif type(value) is int:
        value = f"{value:,}"
    display = fields(value, korean)
    unit = fields(metric["unit"], korean)
    if kpi:
        if display:
            display = f'<span class="kpi-value">{display}</span>'
        if unit:
            unit_class = "kpi-unit"
            if len(str(metric["unit"]).strip()) > 12:
                unit_class += " kpi-unit--long"
            return f'{display} <span class="{unit_class}">{unit}</span>'.lstrip()
        return display
    return f"{display} <small>{unit}</small>".lstrip() if unit else display


def render_kpis(metrics, selection, ambiguities, korean):
    unresolved = [
        {identifier for identifier in metric["depends_on_ambiguity_ids"]
         if ambiguities[identifier] == "unresolved"}
        for metric in metrics
    ]
    groups = []
    for selected in selection:
        ids = unresolved[selected]
        members = {selected} | {index for index, other in enumerate(unresolved) if ids & other}
        position = len(groups)
        for index in reversed(range(len(groups))):
            group_members, group_ids = groups[index]
            if members & group_members:
                members |= group_members
                ids = ids | group_ids
                position = index
                groups.pop(index)
        groups.insert(position, (members, ids))

    parts = []
    conditional = "조건부" if korean else "Conditional"
    for members, ids in groups:
        tiles = []
        for index in sorted(members):
            metric = metrics[index]
            tile = [f'<h3>{safe(metric["name"])}</h3>']
            for css, content in (
                ("metric-value", metric_value(metric, korean, kpi=True)),
                ("muted", fields(metric["definition"], korean)),
                ("kpi-condition", fields(metric["condition"], korean)),
            ):
                if content:
                    tile.append(f'<p class="{css}">{content}</p>')
            tiles.append(f'<article class="kpi">{"".join(tile)}</article>')
        markup = "".join(tiles)
        if ids:
            badge = f'<span class="badge">{conditional} · {safe(", ".join(sorted(ids)))}</span>'
            markup = f'<div class="kpi-group">{badge}<div class="kpi-grid">{markup}</div></div>'
        parts.append(markup)
    return f'<div class="kpi-grid">{"".join(parts)}</div>' if parts else ""


def render_table(headers, rows):
    if not rows:
        return ""
    head = "".join(f'<th scope="col">{safe(label)}</th>' for label in headers)
    body = "".join(
        f'<tr><th scope="row">{first}</th>{"".join(f"<td>{cell}</td>" for cell in rest)}</tr>'
        for first, *rest in rows
    )
    return (f'<div class="table-wrap" tabindex="0"><table><thead><tr>{head}</tr></thead>'
            f'<tbody>{body}</tbody></table></div>')


def render_sources(refs, korean):
    refs = [ref for ref in refs if ref.strip()]
    preview = fields(refs[:6], korean)
    if len(refs) <= 6:
        return preview
    overflow = len(refs) - 6
    label = f"외 {overflow}개" if korean else f"+{overflow} more"
    return f"{preview}<details><summary>{label}</summary>{fields(refs, korean)}</details>"


def render_metrics(metrics, ambiguities, korean):
    labels = KOREAN_FIELDS["metric"]
    columns = ("definition", "numerator", "denominator", "condition")
    headers = (["지표", "값", *(labels[key] for key in columns), labels["source_refs"]] if korean else
               ["Metric", "Value", "Definition", "Numerator", "Denominator", "Condition", "Sources"])
    rows = []
    for metric in metrics:
        dependencies = metric["depends_on_ambiguity_ids"]
        condition = fields(metric["condition"], korean)
        if dependencies:
            conditional = any(ambiguities[identifier] == "unresolved" for identifier in dependencies)
            label = ("조건부" if korean else "Conditional") if conditional else (
                labels["depends_on_ambiguity_ids"] if korean else "Ambiguity IDs")
            condition += f'<div class="muted">{label} · {safe(", ".join(dependencies))}</div>'
        rows.append([
            safe(metric["name"]), metric_value(metric, korean), fields(metric["definition"], korean),
            *(f"{count:,}" if type(count) in (int, float) else fields(count, korean)
              for count in (metric["numerator"], metric["denominator"])),
            condition, render_sources(metric["source_refs"], korean),
        ])
    return render_table(headers, rows)


def render_ambiguities(entries, korean):
    labels = KOREAN_FIELDS["ambiguity_log"]
    columns = ("id", "checklist_item", "status", "answer")
    headers = [labels[key] for key in columns] if korean else ["ID", "Item", "Status", "Answer"]
    rows = []
    for entry in entries:
        row = [fields(entry[key], korean, key) for key in columns]
        evidence = fields({key: entry[key] for key in ("question", "file_evidence", "candidates", "affects")},
                          korean, "ambiguity_log")
        if evidence:
            label = "근거와 후보" if korean else "Evidence and options"
            row[-1] += f"<details><summary>{label}</summary>{evidence}</details>"
        rows.append(row)
    return render_table(headers, rows)


def require_image_module():
    try:
        from PIL import Image
    except ImportError:
        from eda_io import missing_dependency

        missing_dependency("PIL", "building reports")
    return Image


def png_uri(data):
    image_module = require_image_module()
    with image_module.open(BytesIO(data), formats=("PNG",)) as image:
        image.verify()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def render_charts(charts, images, korean):
    parts = []
    for chart, image in zip(charts, images, strict=True):
        question = safe(chart["question"])
        notes = "".join(
            f"<dt>{label_ko if korean else label}</dt><dd>{content}</dd>"
            for key, label, label_ko in CHART_NOTES
            if (content := fields(chart.get(key), korean))
        )
        sample = f'<p class="muted">{safe(chart["id"])}'
        if used := fields(chart.get("n_used"), korean):
            sample += f' · n = {used}'
        sample += "</p>"
        if excluded := fields(chart.get("n_excluded"), korean):
            excluded_label = "제외" if korean else "Excluded"
            sample += f'<p class="muted">{excluded_label} {excluded}'
            if content := fields(chart.get("exclusion_reason"), korean):
                sample += f' · {content}'
            sample += "</p>"
        parts.append(f'<article class="chart"><h3>{question}</h3>{sample}'
                     f'<img src="{image}" alt="{question}"><dl>{notes}</dl></article>')
    return "".join(parts)


def render_summary_panel(spec, ambiguities, images, korean):
    parts = []
    if headline := fields(spec["headline"], korean):
        parts.append(f'<p class="headline">{headline}</p>')
    parts.append(render_kpis(spec["metrics"], spec["kpis"], ambiguities, korean))
    figures = []
    zoom_label = "차트 확대 또는 닫기" if korean else "Enlarge or close chart"
    close_label = "닫기" if korean else "Close"
    for index in spec["key_charts"]:
        chart = spec["charts"][index]
        toggle_id = f'zoom-chart-{index}'
        question = safe(chart["question"])
        figures.append(f'<figure class="key-chart">'
                       f'<input type="checkbox" class="zoom-toggle" id="{toggle_id}" '
                       f'aria-label="{zoom_label} · {question}">'
                       f'<label class="zoom-label" for="{toggle_id}">'
                       f'<img src="{images[index]}" alt="{question}">'
                       f'<span class="zoom-close" aria-hidden="true">{close_label}</span></label>'
                       f'<figcaption>{fields(chart["domain_interpretation"], korean)}</figcaption></figure>')
    if figures:
        parts.append(f'<div class="key-charts">{"".join(figures)}</div>')
    if spec["insights"]:
        insights = "".join(
            f'<li class="insight">{fields(insight["text"], korean)} '
            f'<small class="muted">({safe(insight["source"])})</small></li>'
            for insight in spec["insights"]
        )
        parts.append(f'<ul class="insights">{insights}</ul>')
    pending = [
        f'{entry["id"]} · {(entry["question"] or "").strip() or entry["checklist_item"]}'
        for entry in spec["ambiguity_log"] if entry["status"] == "unresolved"
    ]
    if pending:
        label = "확인 필요" if korean else "Needs confirmation"
        parts.append(f'<aside class="needs-confirmation"><h3>{label}</h3>{fields(pending, korean)}</aside>')
    return "\n".join(parts)


def render_detail_section(name, heading, content):
    section_id = f"details-{name}"
    toggle_id = f"{section_id}-toggle"
    body_id = f"{section_id}-body"
    checked = " checked" if name == "charts" else ""
    title = safe(heading)
    return (
        f'<section id="{section_id}">'
        f'<input type="checkbox" class="section-toggle" id="{toggle_id}" aria-controls="{body_id}"{checked}>'
        f'<div class="section-heading"><h2>{title}</h2>'
        f'<label class="section-title" for="{toggle_id}">'
        f'<span class="section-title-text">{title}</span></label></div>'
        f'<div class="section-body" id="{body_id}">{content}</div></section>'
    )


def render_html(spec, summary, ambiguities, images, *, legacy=False):
    korean = spec["language"].lower().split("-")[0] == "ko"
    overview = spec["data_overview"]
    overview_group = "data_overview" if isinstance(overview, dict) else "datasets"
    datasets = [
        {key: value for key, value in dataset.items() if key != "structure"}
        for dataset in summary["datasets"]
    ]
    overview = {**overview, "datasets": datasets} if isinstance(overview, dict) else datasets
    reproduction = spec["reproducibility"]
    reproduction_fields = {key: reproduction[key] for key in (
        "filters", "exclusions", "transforms", "sample_sizes", "source_locators")}
    reproduction_html = fields(reproduction_fields, korean, "reproducibility")
    code = reproduction["code"]
    if not isinstance(code, str):
        raise ValueError("reproducibility.code must be a string.")
    if code.strip():
        reproduction_html += f'<h3>{"재현 코드" if korean else "Code"}</h3><pre><code>{safe(code)}</code></pre>'
    blocks = (
        ("charts", "Charts", "차트", render_charts(spec["charts"], images, korean)),
        ("limitations", "Assumptions & limitations", "가정과 한계", fields(spec["assumptions_limitations"], korean)),
        ("ambiguity", "Ambiguity log", "모호성 기록", render_ambiguities(spec["ambiguity_log"], korean)),
        ("overview", "Data overview", "데이터 개요", fields(overview, korean, overview_group)),
        ("metrics", "Metrics", "지표", render_metrics(summary["metrics"], ambiguities, korean)),
        ("reproducibility", "Reproducibility", "재현 절차", reproduction_html),
    )
    template = Template(TEMPLATE_PATH.read_text(encoding="utf-8"))
    return template.substitute(
        title=safe(spec["title"]), language=safe(spec["language"]),
        summary_label="요약" if korean else "Summary",
        details_label="세부" if korean else "Details",
        summary=render_summary_panel(spec, ambiguities, images, korean),
        details="\n".join(
            render_detail_section(name, ko if korean else en, content)
            for name, en, ko, content in blocks if content or (legacy and name != "metrics")
        ),
    )


def lock_owner_exited(owner):
    if os.name == "posix":
        try:
            os.kill(owner, 0)
        except ProcessLookupError:
            return True
        except (PermissionError, OverflowError):
            pass
    elif os.name == "nt":
        # Check process liveness without sending a signal on Windows.
        try:
            import _winapi
        except ImportError:
            return False
        try:
            process = _winapi.OpenProcess(_winapi.SYNCHRONIZE, False, owner)
        except OSError as error:
            return error.winerror == 87  # ERROR_INVALID_PARAMETER for an absent PID.
        try:
            return _winapi.WaitForSingleObject(process, 0) == _winapi.WAIT_OBJECT_0
        finally:
            _winapi.CloseHandle(process)
    return False


def stale_lock_owner(lock, state):
    try:
        owner = int(lock.read(32))
    except ValueError:
        owner = 0
    if 0 < owner <= 0x7FFFFFFF:
        return lock_owner_exited(owner)
    # An empty file may belong to a process still recording its PID.
    return time.time() - state.st_mtime >= LOCK_STALE_SECONDS


def create_exclusive_lock(path):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as lock:
            lock.write(f"{os.getpid()}\n".encode("ascii"))
    except BaseException:
        path.unlink()
        raise


def remove_stale_lock(path):
    try:
        with path.open("rb") as lock:
            state = os.fstat(lock.fileno())
            if not stale_lock_owner(lock, state):
                return False
    except FileNotFoundError:
        return True

    # Serialize stale removals for this generation. Another contender may have
    # replaced the lock between the owner check and taking the recovery claim.
    claim = path.with_name(f".eda-build.{state.st_ino}.{state.st_mtime_ns}.reaping")
    try:
        create_exclusive_lock(claim)
    except FileExistsError:
        # A recovery process can itself exit before it releases the claim.
        return remove_stale_lock(claim)
    try:
        current = path.stat()
        if os.path.samestat(state, current) and state.st_mtime_ns == current.st_mtime_ns:
            path.unlink()
            return True
        return False
    except FileNotFoundError:
        return True
    finally:
        claim.unlink()


@contextmanager
def exclusive_file_lock(path):
    deadline = time.monotonic() + LOCK_WAIT_SECONDS
    while True:
        try:
            create_exclusive_lock(path)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f"Timed out waiting for report lock: {path}") from None
            if not remove_stale_lock(path):
                time.sleep(LOCK_RETRY_SECONDS)
    try:
        yield
    finally:
        path.unlink()


@contextmanager
def report_lock(outdir):
    if fcntl is None and msvcrt is None:
        with exclusive_file_lock(outdir / ".eda-build.exclusive.lock"):
            yield
        return

    # Keep the native lock file so all writers open the same inode.
    with (outdir / ".eda-build.lock").open("a+b") as lock:
        if fcntl is not None:
            fcntl.flock(lock, fcntl.LOCK_EX)
            yield
            return

        lock.seek(0)
        descriptor = lock.fileno()
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for report lock: {lock.name}") from error
                time.sleep(LOCK_RETRY_SECONDS)
        try:
            yield
        finally:
            lock.seek(0)
            msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)


def publish_report_pair(outdir, files):
    outdir.mkdir(parents=True, exist_ok=True)
    with report_lock(outdir), TemporaryDirectory(dir=outdir) as temporary:
        staging = Path(temporary)
        prepared = {}
        for destination, contents in files:
            with NamedTemporaryFile(dir=staging, delete=False) as output:
                output.write(contents)
            prepared[destination] = Path(output.name)

        backups = {}
        for destination, _ in files:
            if destination.exists() or destination.is_symlink():
                backup = staging / f"{destination.name}.bak"
                copy2(destination, backup, follow_symlinks=False)
                backups[destination] = backup

        installed = []
        try:
            for destination, _ in files:
                os.replace(prepared[destination], destination)
                installed.append(destination)
        except BaseException:
            try:
                for destination in reversed(installed):
                    if destination in backups:
                        os.replace(backups[destination], destination)
                    else:
                        destination.unlink()
            except BaseException:
                for destination, _ in files:
                    source = destination if os.path.lexists(destination) else prepared[destination]
                    source.rename(destination.with_name(f"{destination.name}.incomplete"))
                raise
            raise


def build_report(spec, outdir, *, base_dir=None, source_spec=None, plot_results=None, input_paths=()):
    """Build report.html and eda_summary.json and return both paths with warnings.

    data_overview supplies datasets; reproducibility supplies row-count transforms
    and exclusions. plot_results is a path to renderer JSON. Supply input_paths
    to record provenance for the inputs and delivered figures.
    When base_dir or source_spec is provided, image paths must resolve within
    the spec directory. Without a spec location, relative paths use the current directory.
    """
    from eda_io import refuse_source_output

    for field in ("title", "language"):
        if not isinstance(spec[field], str) or not spec[field].strip():
            raise ValueError(f"{field} must be a nonempty string.")
    if plot_results is not None:
        plot_results = Path(plot_results)
        results = json.loads(plot_results.read_text(encoding="utf-8-sig"))
        spec = {**spec, "charts": merge_plot_results(spec["charts"], results)}
    for index, chart in enumerate(spec["charts"]):
        for field in ("question", "observation", "domain_interpretation"):
            if not isinstance(chart.get(field), str) or not chart[field].strip():
                raise ValueError(f"charts[{index}].{field} must be a nonempty string.")
    if base_dir is None and source_spec is not None:
        base_dir = Path(source_spec).parent
    directory = Path("." if base_dir is None else base_dir).absolute()
    image_root = directory.resolve()
    image_paths = []
    for chart in spec["charts"]:
        try:
            image_path = (image_root / chart["image_path"]).resolve()
        except (OSError, RuntimeError) as error:
            raise ValueError(f"Chart {chart['id']!r} image_path could not be resolved: {error}") from error
        if base_dir is not None and not image_path.is_relative_to(image_root):
            raise ValueError(f"Chart {chart['id']!r} image_path must resolve inside the report spec directory.")
        image_paths.append(image_path)
    normalized = normalize_report_paths(spec, directory)
    summary = make_summary(normalized)
    validate_summary(summary)
    ambiguities = validate_dependencies(summary)
    validate_metric_values(summary)
    panel, warnings = prepare_summary_panel(spec)
    warnings.extend(check_metric_sources(summary["metrics"], panel["kpis"] if "kpis" in spec else ()))
    normalized.update(normalize_report_paths(panel, directory))
    outdir = Path(outdir)
    html_path, summary_path = outdir / "report.html", outdir / "eda_summary.json"
    for output in (html_path, summary_path):
        if output.is_dir():
            raise IsADirectoryError(f"Report destination is a directory: {output}")
    input_paths = tuple(map(Path, input_paths))
    inputs = [*image_paths, *input_paths, SCHEMA_PATH, TEMPLATE_PATH]
    if source_spec is not None:
        inputs.append(source_spec)
    if plot_results is not None:
        inputs.append(plot_results)
    refuse_source_output(html_path, summary_path, *inputs)
    refuse_source_output(summary_path, *inputs)
    images = []
    figures = {}
    delivery = outdir.resolve()
    for path in image_paths:
        data = path.read_bytes()
        images.append(png_uri(data))
        if input_paths and path.is_relative_to(delivery / "figures") and path.suffix.lower() == ".png":
            figures[path.relative_to(delivery).as_posix()] = sha256(data).hexdigest()
    if input_paths:
        summary["provenance"] = make_provenance(input_paths, figures)
        validate_summary(summary)
    html = render_html(normalized, summary, ambiguities, images, legacy="headline" not in spec)
    sidecar = json.dumps(summary, allow_nan=False, ensure_ascii=True, indent=2) + "\n"
    publish_report_pair(outdir, (
        (html_path, html.encode("utf-8", errors="xmlcharrefreplace")),
        (summary_path, sidecar.encode("utf-8")),
    ))
    return ReportResult((html_path, summary_path), warnings)


def main():
    # Keep dependency diagnostics available even when the CLI only shows help.
    from eda_io import check_python

    check_python(sys.version_info)
    require_image_module()
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "See references/report_spec.example.json for a complete input. "
            "Required top-level fields: title, language, headline, data_overview, "
            "ambiguity_log, charts, metrics, assumptions_limitations, reproducibility. "
            "Optional summary selections: kpis (up to 4), key_charts (up to 2), "
            "insights (up to 3, each with text and source). "
            "Legacy summary can supply headline. Omitted selections use legacy defaults with a warning. "
            "Required chart prose: question, observation, domain_interpretation. "
            "Optional chart prose: hypothesis, next_check."
        ),
    )
    parser.add_argument("--spec", type=Path, required=True, help="Report specification JSON.")
    parser.add_argument("--outdir", type=Path, required=True, help="Destination directory.")
    parser.add_argument("--plot-results", type=Path, help="Renderer JSON to verify against the report charts.")
    parser.add_argument("--input", type=Path, action="append", default=[], metavar="PATH",
                        help="Original input file to hash for provenance. May be repeated.")
    args = parser.parse_args()
    try:
        spec = json.loads(args.spec.read_text(encoding="utf-8-sig"))
        result = build_report(
            spec, args.outdir, source_spec=args.spec, plot_results=args.plot_results, input_paths=args.input,
        )
        html, summary = result
        for warning in result.warnings:
            print(f"Warning: {warning}", file=sys.stderr)
        print(f"Wrote {html} and {summary}.")
    except (OSError, TypeError, ValueError, KeyError, SyntaxError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    sys.stdout.reconfigure(errors="backslashreplace")
    main()
