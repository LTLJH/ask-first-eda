"""Read supported sources without changing values or losing source coordinates."""

from __future__ import annotations

import argparse
import base64
import codecs
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import Decimal, DecimalException
import io
from itertools import chain
import json
import math
from numbers import Real
from pathlib import Path
import re
from statistics import mode
import sys
from tempfile import NamedTemporaryFile
import zipfile


def check_python(version_info):
    if version_info[:2] < (3, 10):
        print("Python 3.10 or later is required.", file=sys.stderr)
        raise SystemExit(2)


def missing_dependency(module, feature=None):
    requirements = Path(__file__).resolve().parent.parent / "requirements.txt"
    context = f" for {feature}" if feature else ""
    print(f'Missing dependency: {module}{context}. Run pip install -r "{requirements}" '
          "(ask the user before installing).", file=sys.stderr)
    raise SystemExit(2)


check_python(sys.version_info)

try:
    from charset_normalizer import from_bytes
except ImportError:
    missing_dependency("charset_normalizer")

try:
    import pandas as pd
except ImportError as error:
    missing_dependency(error.name or getattr(error.__cause__, "name", None) or "pandas")


FORMATS = {
    ".csv": "csv", ".tsv": "tsv", ".xlsx": "xlsx", ".xls": "xls",
    ".json": "json", ".jsonl": "jsonl", ".ndjson": "jsonl", ".parquet": "parquet",
    ".md": "markdown", ".markdown": "markdown",
}
SEPARATORS = ",\t;|"
NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")
GROUPED_NUMBER = re.compile(r"[+-]?[0-9]{1,3}(?:,[0-9]{3})+(?:\.[0-9]*)?(?:[eE][+-]?[0-9]+)?")
LEADING_ZERO = re.compile(r"[+-]?0[0-9]")
ISO_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}(?:[T ].*)?")
IDENTIFIER = re.compile(r"[^\W\d]\w*")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]")
UNKNOWN = "unknown"
MAX_TABLE_CELLS = 20_000_000


@dataclass
class Table:
    id: str
    locator: dict
    frame: pd.DataFrame
    row_refs: list
    details: dict = field(default_factory=dict)
    header_uncertain: bool = False


@dataclass
class Source:
    report: dict
    tables: list[Table] = field(default_factory=list)
    document: object = None


def is_missing(value):
    return value is None or value is pd.NA or value is pd.NaT or (
        isinstance(value, Real) and not isinstance(value, int) and math.isnan(value)
    )


def is_empty(value):
    return isinstance(value, str) and value == ""


def neutralize_formula(value):
    """Prefix formula-like CSV text with an apostrophe."""
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@", "\t", "\r")):
        if not NUMBER.fullmatch(value.strip()):
            return "'" + value
    return value


def numeric_value(value):
    decimal = numeric_decimal(value)
    if decimal is None:
        return None
    number = float(decimal)
    return number if math.isfinite(number) and (number != 0 or decimal == 0) else None


def numeric_decimal(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not NUMBER.fullmatch(value) or LEADING_ZERO.match(value):
            return None
    elif not isinstance(value, (Real, Decimal)):
        return None
    try:
        number = value if isinstance(value, Decimal) else Decimal(str(value))
    except DecimalException:
        return None
    return number if number.is_finite() else None


def datetime_value(value):
    if isinstance(value, str):
        if not ISO_DATE.fullmatch(value):
            return None
    elif not isinstance(value, (date, datetime)) or value is pd.NaT:
        return None
    try:
        return pd.Timestamp(value)
    except (ValueError, OverflowError):
        return None


def column_info(values):
    present = [value for value in values if not is_missing(value) and not is_empty(value)]
    convertible = {
        "numeric": sum(numeric_decimal(value) is not None for value in present),
        "datetime": sum(datetime_value(value) is not None for value in present),
    }
    if not present:
        kind = "empty"
    elif convertible["numeric"] == len(present):
        kind = "numeric"
    elif convertible["datetime"] == len(present):
        kind = "datetime"
    elif all(isinstance(value, bool) for value in present):
        kind = "boolean"
    elif all(isinstance(value, str) for value in present):
        kind = "string"
    elif all(isinstance(value, (list, dict)) for value in present):
        kind = "nested"
    else:
        kind = "mixed"
    empty = sum(map(is_empty, values))
    examples = []
    seen = set()
    for value in values:
        if not is_missing(value):
            key = value_key(value)
            if key not in seen:
                seen.add(key)
                examples.append(json_value(value))
                if len(examples) == 3:
                    break
    return {
        "inferred_type": kind,
        "n_missing": empty + sum(is_missing(value) for value in values),
        "n_empty_string": empty,
        "example_values": examples,
        "conversion_candidates": {**convertible, "non_missing": len(present)},
    }


def json_value(value):
    if is_missing(value):
        return None
    if isinstance(value, dict):
        return {str(key): json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    if isinstance(value, (date, datetime, time, timedelta)):
        return value.isoformat() if hasattr(value, "isoformat") else str(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"base64": base64.b64encode(value).decode("ascii")}
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    if isinstance(value, (str, bool, int, float)):
        return value
    if hasattr(value, "tolist"):
        return json_value(value.tolist())
    return str(value)


def typed_value(value):
    if isinstance(value, dict):
        content = {str(key): typed_value(item) for key, item in value.items()}
    elif isinstance(value, (list, tuple)):
        content = [typed_value(item) for item in value]
    else:
        content = json_value(value)
    return [type(value).__name__, content]


def value_key(value):
    return json.dumps(typed_value(value), sort_keys=True, ensure_ascii=True)


def unique_names(headers, width):
    names = []
    used = set()
    for index in range(width):
        original = headers[index] if index < len(headers) else None
        base = str(original) if original is not None and str(original) else f"column_{index + 1}"
        name = base
        suffix = 2
        while name in used:
            name = f"{base}__{suffix}"
            suffix += 1
        used.add(name)
        names.append(name)
    return names


def make_table(table_id, locator, rows, refs, headers, *, header_uncertain=False, **details):
    width = max([len(headers), *(len(row) for row in rows)])
    padded = [list(row) + [None] * (width - len(row)) for row in rows]
    # csv.reader already returns strings. Object storage leaves absent fields
    # as None, and keeps explicit empty strings and native values intact.
    frame = pd.DataFrame(padded, columns=unique_names(headers, width), dtype=object)
    return Table(table_id, locator, frame, list(refs), details, header_uncertain=header_uncertain)


def extent(source, rows, total, unread=()):
    source.report["read_extent"] = {
        "rows_read": rows, "rows_total_or_unknown": total, "unread": list(unread),
    }


def detect(source, fmt, message):
    report = source.report
    report["detected_format"] = fmt
    report["evidence"].append(message)
    expected = report["extension_format"]
    report["conflict"] = bool(expected and fmt != UNKNOWN and expected != fmt)
    if report["conflict"]:
        report["warnings"].append(f"Extension indicates {expected}; content indicates {fmt}.")


def fail(source, reason, **locator):
    source.report["warnings"].append(reason)
    extent(source, 0, UNKNOWN, [{**locator, "reason": reason}])


def decode_printable(raw, encoding):
    try:
        text = raw.decode(encoding)
    except UnicodeDecodeError:
        return None
    return None if CONTROL.search(text) else text


def cp949_pair_counts(raw):
    # Strict CP949 decoding has already validated each lead and trail byte.
    pairs = extended = standard_hangul = 0
    for match in re.finditer(rb"[\x81-\xfe].", raw):
        lead, trail = match.group()
        pairs += 1
        if trail <= 0xA0:  # Valid extension trails are 0x41–0x5A, 0x61–0x7A and 0x81–0xA0.
            extended += 1
        elif 0xB0 <= lead <= 0xC8:  # KS X 1001 Hangul rows.
            standard_hangul += 1
    return pairs, extended, standard_hangul


def select_legacy_encoding(report, candidates):
    encoding, text, note = candidates[0]
    report["encoding"] = encoding
    report["evidence"].append(note)
    if any(decoded != text for _, decoded, _ in candidates[1:]):
        entries = []
        for codec, decoded, confidence_note in candidates:
            lines = io.StringIO(decoded, newline="")
            preview = next((line.rstrip("\r\n") for line in lines if line.strip()), "")[:240]
            entries.append({"encoding": codec, "confidence_note": confidence_note, "header_preview": preview})
        report.update(encoding_ambiguous=True, encoding_candidates=entries)
        previews = " / ".join(f"{entry['encoding']} {entry['header_preview']!r}" for entry in entries)
        if len({entry["header_preview"] for entry in entries}) == 1:
            lines_by_codec = [io.StringIO(decoded, newline="") for _, decoded, _ in candidates]
            differing = next((lines for lines in zip(*lines_by_codec) if len(set(lines)) > 1), ())
            if differing:
                previews = " / ".join(f"{codec} {line.rstrip()[:240]!r}"
                                      for (codec, _, _), line in zip(candidates, differing))
        report["warnings"].append(f"Ambiguous text encoding. Confirm the text interpretation ({previews}).")
    return text


def decode_text(raw, report, encoding=None):
    if encoding is not None:
        decoded = raw.decode(encoding, errors="strict")
        report["encoding"] = encoding
        report["evidence"].append(f"Explicit {encoding} strict decode.")
        return decoded

    signatures = (
        (codecs.BOM_UTF32_LE, "utf-32"), (codecs.BOM_UTF32_BE, "utf-32"),
        (codecs.BOM_UTF8, "utf-8-sig"),
        (codecs.BOM_UTF16_LE, "utf-16"), (codecs.BOM_UTF16_BE, "utf-16"),
    )
    bom = next((encoding for marker, encoding in signatures if raw.startswith(marker)), None)
    try:
        decoded = raw.decode(bom or "utf-8")
    except UnicodeDecodeError as error:
        if bom:
            raise
        report["evidence"].append(f"Strict UTF-8 rejected bytes [{error.start}, {error.end}).")
    else:
        if not CONTROL.search(decoded):
            encoding = bom or "utf-8"
            report["encoding"] = encoding
            report["evidence"].append(f"{encoding} {'BOM' if bom else 'strict decode'}.")
            return decoded
        raise ValueError("Unexpected binary control bytes in text.")

    western = decode_printable(raw, "cp1252")
    western_candidate = ("cp1252", western, "Strict Windows-1252 decode yields printable text.")
    korean = decode_printable(raw, "cp949")
    if korean is not None:
        pairs, extended, standard = cp949_pair_counts(raw)
        note = (f"Strict CP949 decode has {extended}/{pairs} UHC extension trails "
                f"and {standard}/{pairs} KS X 1001 Hangul pairs.")
        korean_candidate = ("cp949", korean, note)
        if western is not None:
            # Parenthesized units in a header distinguish otherwise ASCII Western text.
            western_lines = io.StringIO(western, newline="")
            western_header = next((line for line in western_lines if line.strip()), "")
            if re.sub(r"\(°[CF]\)", "", western_header).isascii() and western_lines.read().isascii():
                return select_legacy_encoding(report, [(
                    "cp1252", western, "Strict Windows-1252 decode has recognizable header units.",
                )])
        korean_lines = io.StringIO(korean, newline="")
        korean_header = next((line for line in korean_lines if line.strip()), "")
        header_hangul = sum("\uac00" <= char <= "\ud7a3" for char in korean_header)
        if standard >= 2 and standard * 4 >= pairs * 3 and (western is None or header_hangul >= 2):
            return select_legacy_encoding(report, [korean_candidate])
        if western is not None:
            candidates = [western_candidate, korean_candidate]
            if standard > extended:
                candidates.reverse()
            return select_legacy_encoding(report, candidates)
        if western is None:
            hangul = sum("\uac00" <= char <= "\ud7a3" for char in korean)
            non_ascii = sum(ord(char) > 127 for char in korean)
            if hangul >= 2 and hangul * 2 > non_ascii:
                return select_legacy_encoding(report, [korean_candidate])

    candidates = []
    for match in from_bytes(raw, enable_fallback=False):
        decoded = decode_printable(raw, match.encoding)
        if decoded is None or (candidates and decoded == candidates[0][1]):
            continue
        candidates.append((match.encoding, decoded, f"charset-normalizer estimates {match.encoding}."))
        if len(candidates) == 2:
            break
    if not candidates and western is not None:
        candidates.append(western_candidate)
    if not candidates:
        raise ValueError("No supported encoding decoded the text bytes reliably.")
    return select_legacy_encoding(report, candidates)


def parse_records(text, delimiter, quotechar='"', doublequote=True):
    reader = csv.reader(io.StringIO(text, newline=""), delimiter=delimiter, quotechar=quotechar,
                        doublequote=doublequote, skipinitialspace=False, strict=True)
    records = []
    while True:
        first = reader.line_num + 1
        try:
            row = next(reader)
        except StopIteration:
            return records, None
        except csv.Error as error:
            return records, {"line_range": [first, max(reader.line_num, first)], "reason": str(error)}
        records.append((first, reader.line_num, row))


def sniff_dialect(text, preferred):
    lines = io.StringIO(text, newline="").readlines()
    sample = "".join(lines[:100])
    sniffed = {}
    for prefix in (sample, "".join(lines[:10]), lines[0] if lines else ""):
        try:
            dialect = csv.Sniffer().sniff(prefix, delimiters=SEPARATORS)
        except csv.Error:
            continue
        sniffed.setdefault(dialect.delimiter, dialect)
    ranked = []
    for separator in SEPARATORS:
        dialect = sniffed.get(separator)
        # CSV and TSV conventionally use double quotes. Allow single quotes
        # when Sniffer actually found a single-quoted field.
        quote = dialect.quotechar if dialect else '"'
        records, _ = parse_records(sample, separator, quote)
        widths = [len(row) for _, _, row in records if row]
        if not widths or max(widths) < 2:
            continue
        counts = Counter(widths)
        width, consistent = counts.most_common(1)[0]
        first = widths[0]
        score = (width > 1, consistent / len(widths), first > 1)
        ranked.append((score, separator, quote))
    if not ranked:
        return preferred, '"', []
    best = max(score for score, _, _ in ranked)
    tied = [(sep, quote) for score, sep, quote in ranked if score == best]
    separator, quote = max(tied, key=lambda choice: (choice[0] in sniffed, choice[0] == preferred))
    return separator, quote, [sep for sep, _ in tied]


def header_inference(records, delimiter, quotechar):
    nonempty = [row for _, _, row in records if row]
    if not nonempty:
        return False, "No nonempty records.", False
    first = nonempty[0]
    comparable = [row for row in nonempty[1:21] if len(row) == len(first)]
    def data_like(value):
        stripped = value.strip()
        return bool(NUMBER.fullmatch(stripped) or GROUPED_NUMBER.fullmatch(stripped)) or datetime_value(value) is not None

    if any(data_like(value) for value in first):
        return False, "First record contains numeric or date values.", False
    if comparable and any(
        value and all(data_like(row[index]) or row[index] == "" for row in comparable)
        and any(row[index] != "" for row in comparable)
        for index, value in enumerate(first)
    ):
        return True, "First record labels fields with number-like or date data below.", False
    if comparable:
        stream = io.StringIO(newline="")
        csv.writer(stream, delimiter=delimiter, quotechar=quotechar).writerows([first, *comparable])
        try:
            if csv.Sniffer().has_header(stream.getvalue()):
                return True, "csv.Sniffer suggests a header.", True
        except csv.Error:
            pass
    return False, "Header presence is uncertain; retaining the first record as data.", True


def irregular_rows(records, width):
    return [{"line": first, "line_range": [first, last], "field_count": len(row),
             "expected_field_count": width}
            for first, last, row in records if len(row) != width]


def read_delimited(source, text, dialect, *, delimiter=None, header=None, parsed=None):
    if delimiter is not None and (len(delimiter) != 1 or delimiter in '\r\n"'):
        raise ValueError("Delimiter must be one character other than a newline or double quote.")
    guessed, quote, alternatives = dialect
    separator = delimiter if delimiter is not None else guessed
    if separator != guessed:
        quote = '"'
    fmt = "tsv" if separator == "\t" else "csv"
    evidence = "Delimited text" if alternatives or delimiter else "Text read as one-column delimited records"
    detect(source, fmt, f"{evidence}; delimiter {separator!r}, quote character {quote!r}.")
    ambiguous_dialect = delimiter is None and len(alternatives) > 1
    if ambiguous_dialect:
        source.report["warnings"].append(f"Competing delimiters: {alternatives!r}; confirm with --delimiter.")
    records, error = parsed if parsed is not None else parse_records(text, separator, quote)
    guessed_header, reason, uncertain = header_inference(records, separator, quote)
    header_uncertain = uncertain and header is None
    has_header = guessed_header if header is None else header
    if header is not None:
        reason = "Header presence explicitly specified."
    elif header_uncertain:
        source.report["warnings"].append("Header presence is uncertain; confirm with --header.")
    header_index = next((index for index, (_, _, row) in enumerate(records) if row), None)
    header_record = records.pop(header_index) if has_header and header_index is not None else None
    headers = header_record[2] if header_record else []
    widths = [len(row) for _, _, row in records if row]
    width = len(headers) if header_record else mode(widths) if widths else 0
    ragged = irregular_rows(records, width)
    if ragged:
        source.report["warnings"].append("Irregular records retained; inspect field counts before using column totals.")
    last_read = max([header_record[1] if header_record else 0, *(last for _, last, _ in records)])
    locator = {"line_range": [1, last_read] if last_read else None,
               "header_line_range": list(header_record[:2]) if header_record else None}
    source.tables.append(make_table(
        "text:1", locator, [row for _, _, row in records], [first for first, _, _ in records],
        headers, header_uncertain=header_uncertain, irregular_rows=ragged, source_headers=headers,
        record_line_ranges=[[first, last] for first, last, _ in records],
    ))
    unread = []
    if error:
        last_line = len(io.StringIO(text, newline="").readlines())
        unread.append({"line_range": [error["line_range"][0], last_line],
                       "reason": f"Malformed delimited record: {error['reason']}"})
        source.report["warnings"].append(unread[0]["reason"])
    source.report.update(delimiter=separator, quotechar=quote, delimiter_candidates=alternatives,
                         header_present=bool(header_record), header_evidence=reason,
                         irregular_rows=ragged)
    unknown_total = error or ambiguous_dialect or (header_uncertain and bool(records))
    extent(source, len(records), UNKNOWN if unknown_total else len(records), unread)


def markdown_cells(line):
    cells = [""]
    has_pipe = False
    for char in line.strip():
        if char == "|":
            backslashes = len(cells[-1]) - len(cells[-1].rstrip("\\"))
            if backslashes % 2:
                cells[-1] = cells[-1][:-1] + "|"
            else:
                cells.append("")
                has_pipe = True
        else:
            cells[-1] += char
    if not has_pipe:
        return None
    if cells[0] == "":
        cells.pop(0)
    if cells[-1] == "":
        cells.pop()
    return [cell.strip() for cell in cells]


def read_markdown(source, text, quoted_lines):
    lines = [line.rstrip("\r\n") for line in io.StringIO(text, newline="")]
    used_lines = set()
    index = 0
    fence = None
    while index + 1 < len(lines):
        if index + 1 in quoted_lines:
            index += 1
            continue
        marker = re.match(r"^\s{0,3}(\x60{3,}|~{3,})", lines[index])
        if marker:
            token = marker.group(1)
            if fence is None:
                fence = token
            elif token[0] == fence[0] and len(token) >= len(fence) and not lines[index][marker.end():].strip():
                fence = None
            index += 1
            continue
        if fence or index + 2 in quoted_lines:
            index += 1
            continue
        headers = markdown_cells(lines[index])
        rule = markdown_cells(lines[index + 1])
        if not headers or not rule or not all(re.fullmatch(r":?-{3,}:?", cell) for cell in rule):
            index += 1
            continue
        start = index + 1
        index += 2
        records = []
        while index < len(lines):
            cells = markdown_cells(lines[index])
            if cells is None or re.match(r"^\s{0,3}(?:#|\x60{3,}|~{3,})", lines[index]):
                break
            if index + 1 < len(lines):
                next_rule = markdown_cells(lines[index + 1])
                if next_rule and all(re.fullmatch(r":?-{3,}:?", cell) for cell in next_rule):
                    break
            records.append((index + 1, index + 1, cells))
            index += 1
        ragged = irregular_rows(records, len(headers))
        if len(headers) != len(rule):
            ragged.insert(0, {"line": start + 1, "line_range": [start + 1, start + 1],
                              "field_count": len(rule), "expected_field_count": len(headers)})
        used_lines.update(range(start, index + 1))
        locator = {"line_range": [start, index], "header_line_range": [start, start]}
        source.tables.append(make_table(
            f"markdown:{len(source.tables) + 1}", locator, [row for _, _, row in records],
            [line for line, _, _ in records], headers, irregular_rows=ragged,
            source_headers=headers, delimiter_column_count=len(rule),
        ))
    if not source.tables:
        return False
    detect(source, "markdown", "Pipe-delimited headers and Markdown alignment rows.")
    source.report["table_count"] = len(source.tables)
    unread = []
    for line in range(1, len(lines) + 1):
        if line in used_lines:
            continue
        if unread and unread[-1]["line_range"][1] == line - 1:
            unread[-1]["line_range"][1] = line
        else:
            unread.append({"line_range": [line, line], "reason": "Outside detected Markdown tables."})
    if any(table.details["irregular_rows"] for table in source.tables):
        source.report["warnings"].append("Irregular Markdown table rows retained.")
    rows = sum(len(table.frame) for table in source.tables)
    extent(source, rows, rows, unread)
    return True


def reject_constant(token):
    raise ValueError(f"Nonstandard JSON constant: {token}.")


def unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError(f"Duplicate JSON object key: {key!r}.")
        obj[key] = value
    return obj


def parse_json(text):
    return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant,
                      parse_float=Decimal)


def key_path(key):
    return "." + key if IDENTIFIER.fullmatch(key) else "[" + json.dumps(key, ensure_ascii=True) + "]"


def walk_json(value, pattern, path, arrays, fields):
    if isinstance(value, list):
        if arrays is not None:
            arrays[pattern].append({"path": path, "n_rows": len(value)})
        for index, item in enumerate(value):
            walk_json(item, pattern + "[*]", f"{path}[{index}]", arrays, fields)
    elif isinstance(value, dict):
        for key, item in value.items():
            part = key_path(key)
            fields.add(pattern + part)
            walk_json(item, pattern + part, path + part, arrays, fields)


def describe_json(source, document):
    arrays = defaultdict(list)
    fields = set()
    walk_json(document, "$", "$", arrays, fields)
    candidates = [{"id": f"json:{path}", "path": path,
                   "predicted_rows": sum(item["n_rows"] for item in occurrences),
                   "occurrences": occurrences} for path, occurrences in arrays.items()]
    source.document = document
    type_names = {dict: "object", list: "array", str: "string", int: "number", float: "number",
                  Decimal: "number", bool: "boolean", type(None): "null"}
    source.report.update(top_level_type=type_names[type(document)], record_candidates=candidates,
                         nested_field_paths=sorted(fields), record_unit="unselected")
    extent(source, 0, UNKNOWN, [{"json_path": "$", "reason": "Record path not selected; document parsed structurally."}])


def json_table(records, table_id, locator):
    headers = list(dict.fromkeys(key for _, record in records if isinstance(record, dict) for key in record))
    scalar = any(not isinstance(record, dict) for _, record in records)
    scalar_name = unique_names([*headers, "value"], len(headers) + 1)[-1] if scalar else None
    if scalar:
        headers.append(scalar_name)
    rows, absent_fields = [], {}
    names = unique_names(headers, len(headers))
    for ref, record in records:
        if isinstance(record, dict):
            rows.append([record.get(key) if key != scalar_name else None for key in headers])
            absent = [name for key, name in zip(headers, names, strict=True)
                      if key == scalar_name or key not in record]
        else:
            rows.append([None] * (len(headers) - 1) + [record])
            absent = names[:-1]
        if absent:
            absent_fields[ref] = absent
    return make_table(table_id, locator, rows, [ref for ref, _ in records], headers,
                      source_headers=headers, absent_fields=absent_fields)


def read_jsonl(source, text):
    lines = io.StringIO(text, newline="").readlines()
    records = []
    unread = []
    for number, line in enumerate(lines, 1):
        try:
            records.append((number, parse_json(line)))
        except (ValueError, DecimalException, RecursionError) as error:
            unread.append({"line_range": [number, number], "reason": str(error)})
    detect(source, "jsonl", "Decoded records evaluated one JSON value per physical line.")
    if unread:
        source.report["warnings"].append("Invalid JSONL lines are reported and excluded from the parsed subset.")
    fields = set()
    for number, value in records:
        walk_json(value, "$", f"line:{number}", None, fields)
    source.report.update(failed_lines=[entry["line_range"][0] for entry in unread],
                         record_unit="one JSON value per line", nested_field_paths=sorted(fields))
    source.tables.append(json_table(records, "jsonl:1", {"line_range": [1, len(lines)] if lines else None}))
    extent(source, len(records), UNKNOWN if unread else len(records), unread)


def read_text(source, raw, *, delimiter=None, header=None, encoding=None, quotechar=None):
    try:
        text = decode_text(raw, source.report, encoding)
    except (LookupError, ValueError) as error:
        offset = [error.start, error.end] if isinstance(error, UnicodeDecodeError) else None
        codec = f" with encoding {encoding!r}" if encoding is not None else ""
        fail(source, f"Text decode failed{codec}: {error}", byte_range=[0, len(raw)], error_byte_range=offset)
        return
    expected = source.report["extension_format"]
    preferred = "\t" if expected == "tsv" else ","
    if quotechar is not None:
        read_delimited(source, text, (delimiter or preferred, quotechar, []),
                       delimiter=delimiter, header=header)
        return
    dialect = sniff_dialect(text, preferred)
    if delimiter is not None:
        read_delimited(source, text, dialect, delimiter=delimiter, header=header)
        return

    separator, quote, dialects = dialect
    quoted_lines = set()
    parsed = None
    if quote in text:
        parsed = parse_records(text, separator, quote)
        records, error = parsed
        for first, last, _ in records:
            if first < last:
                quoted_lines.update(range(first, last + 1))
        if error:
            # A malformed record can contain other format markers. Trust the
            # quote only after a consistent header and data record are plausible.
            widths = [len(row) for _, _, row in records if row]
            if len(widths) >= 2 and widths[0] > 1 and len(set(widths)) == 1:
                first, last = error["line_range"]
                quoted_lines.update(range(first, last + 1))
    lines = [line.lstrip() for number, line in enumerate(io.StringIO(text, newline=""), 1)
             if number not in quoted_lines and line.strip()]
    json_looking = any(line.startswith(("{", "[")) for line in lines)
    if json_looking or expected in {"json", "jsonl"}:
        try:
            document = parse_json(text)
        except (ValueError, DecimalException, RecursionError) as error:
            valid_lines = structured_lines = 0
            for line in lines:
                try:
                    value = parse_json(line)
                except (ValueError, DecimalException, RecursionError):
                    continue
                valid_lines += 1
                structured_lines += isinstance(value, (dict, list))
            if structured_lines >= 2 or (expected == "json" and valid_lines == len(lines) >= 2):
                read_jsonl(source, text)
                return
            if read_markdown(source, text, quoted_lines):
                return
            if expected == "jsonl" and (valid_lines or not dialects):
                read_jsonl(source, text)
                return
            if ((json_looking and (expected == "json" or not dialects))
                    or (expected == "json" and not dialects)):
                detect(source, "json", "JSON-like text or extension; document parsing failed.")
                fail(source, f"JSON parsing failed: {error}",
                     line=getattr(error, "lineno", None), column=getattr(error, "colno", None),
                     json_path="$")
                return
        else:
            if expected == "jsonl" and len(lines) <= 1:
                read_jsonl(source, text)
                return
            detect(source, "json", "Text parses as one complete JSON document.")
            describe_json(source, document)
            return
    if read_markdown(source, text, quoted_lines):
        return
    read_delimited(source, text, dialect, header=header, parsed=parsed)


def excel_cells(reader, part, *, data_only):
    from openpyxl.worksheet._reader import WorkSheetParser

    with reader.archive.open(part) as member:
        parser = WorkSheetParser(member, reader.shared_strings, data_only=data_only,
                                 epoch=reader.wb.epoch, date_formats=reader.wb._date_formats,
                                 timedelta_formats=reader.wb._timedelta_formats)
        cells = {(cell["row"], cell["column"]): cell for _, row in parser.parse() for cell in row
                 if cell["value"] is not None or cell["data_type"] == "inlineStr"}
    return cells, parser


class ExcelTableTooLargeError(ValueError):
    def __init__(self, sheet, cell_range, cell_count):
        self.cell_range = cell_range
        super().__init__(
            f"Sheet {sheet!r} range {cell_range} contains {cell_count:,} cells, "
            f"exceeding the limit of {MAX_TABLE_CELLS:,}. "
            "Copy a smaller range to a new workbook or export that range to CSV."
        )


def excel_table(name, cells, merged, header_row):
    from openpyxl.utils.cell import get_column_letter

    top = min(chain((row for row, _ in cells), (span.min_row for span in merged)), default=1)
    left = min(chain((col for _, col in cells), (span.min_col for span in merged)), default=1)
    bottom = max(chain((row for row, _ in cells), (span.max_row for span in merged)), default=0)
    right = max(chain((col for _, col in cells), (span.max_col for span in merged)), default=0)

    def cell_range(first, last):
        return f"{get_column_letter(left)}{first}:{get_column_letter(right)}{last}" if last else None

    cell_count = (bottom - top + 1) * (right - left + 1)
    if cell_count > MAX_TABLE_CELLS:
        raise ExcelTableTooLargeError(name, cell_range(top, bottom), cell_count)

    by_row = defaultdict(list)
    values = {}
    for position, cell in cells.items():
        value = cell["value"]
        by_row[position[0]].append(cell)
        if cell["data_type"] == "f" and not isinstance(value, str):
            expression = getattr(value, "text", None)
            value = expression if expression is not None else dict(value)
        if cell["data_type"] == "inlineStr" and value is None:
            value = ""
        values[position] = value

    candidates = [row for row in sorted(by_row)[:10]
                  if all(isinstance(cell["value"], str) and cell["data_type"] != "f"
                         for cell in by_row[row])]
    chosen = top if top in candidates else None
    uncertain_header = header_row is None and chosen is not None and not any(
        row > chosen and (chosen, col) in cells and (
            cell["data_type"] == "f" or cell["value"] is not None and not isinstance(cell["value"], str)
        )
        for (row, col), cell in cells.items()
    )
    if uncertain_header:
        chosen = None
    if header_row is not None:
        if header_row and not top <= header_row <= bottom:
            raise ValueError(f"Header row {header_row} is outside sheet {name!r}.")
        chosen = header_row or None

    def read_row(row):
        return [values.get((row, col)) for col in range(left, right + 1)]

    refs = list(range(chosen + 1 if chosen is not None else top, bottom + 1))
    headers = read_row(chosen) if chosen is not None else [None] * max(0, right - left + 1)
    locator = {"sheet": name, "range": cell_range(top, bottom),
               "data_range": cell_range(refs[0], refs[-1]) if refs else None, "header_row": chosen}
    table = make_table(f"sheet:{name}", locator, [read_row(row) for row in refs], refs, headers,
                       header_uncertain=uncertain_header,
                       source_headers=[json_value(value) for value in headers])
    unread = ({"sheet": name, "row_range": [top, chosen - 1],
               "reason": "Rows precede the explicitly selected header."}
              if chosen is not None and chosen > top else None)
    return table, candidates, unread


def read_excel(source, path, selected_sheet=None, header_row=None):
    try:
        from openpyxl.reader.excel import ExcelReader, apply_stylesheet
        from openpyxl.utils.cell import get_column_letter
    except ImportError:
        missing_dependency("openpyxl", "reading Excel files")

    detect(source, "xlsx", "ZIP container with an Excel workbook part.")
    sheets, unread = [], []
    source.report["sheets"] = sheets
    warnings = source.report["warnings"]
    sheet_errors = (OSError, ValueError, TypeError, KeyError, IndexError, SyntaxError, zipfile.BadZipFile)
    with path.open("rb") as binary:
        # Parse sheet parts separately so a damaged worksheet does not hide
        # other sheets. Reading the cells does not bind hyperlinks or drawings.
        reader = ExcelReader(binary, read_only=True, keep_links=False)
        try:
            reader.read_manifest()
            reader.read_strings()
            reader.read_workbook()
            apply_stylesheet(reader.archive, reader.wb)
            for sheet in reader.parser.sheets:
                name = sheet.name
                metadata = {"name": name, "state": sheet.state, "used_range": None, "read_range": None,
                            "merged_ranges": [], "header_candidates": []}
                sheets.append(metadata)
                part = None
                unread_start = len(unread)
                scoped_out = selected_sheet is not None and name != selected_sheet
                try:
                    relation = reader.parser.rels[sheet.id]
                    part = relation.target
                    if not relation.Type.endswith("/worksheet"):
                        raise ValueError("This sheet does not contain a supported worksheet.")
                    if scoped_out:
                        unread.append({"sheet": name, "part": part, "reason": "Sheet outside requested table scope."})
                        continue
                    cells, parser = excel_cells(reader, part, data_only=False)
                    merged = [span for span in parser.merged_cells.mergeCell] if parser.merged_cells else []
                    table, candidates, preamble = excel_table(name, cells, merged, header_row)
                except sheet_errors as error:
                    if isinstance(error, ExcelTableTooLargeError):
                        metadata["used_range"] = error.cell_range
                        reason = str(error)
                    else:
                        reason = f"Could not read sheet {name!r}: {error}"
                    warnings.append(reason)
                    unread.append({"sheet": name, "part": part,
                                   "range": metadata["used_range"] or UNKNOWN, "reason": reason})
                    continue
                if preamble:
                    unread.append(preamble)
                if table.header_uncertain:
                    warnings.append(f"Sheet {name!r}: header_inferred_without_type_evidence. Confirm with --header-row.")
                formula_cells = [(pos, cell["value"]) for pos, cell in sorted(cells.items())
                                 if cell["data_type"] == "f"]
                cache = {}
                caches_read = True
                if formula_cells:
                    try:
                        cache, _ = excel_cells(reader, part, data_only=True)
                    except sheet_errors as error:
                        reason = f"Could not read formula caches for sheet {name!r}: {error}"
                        warnings.append(reason)
                        unread.append({"sheet": name, "range": table.locator["range"],
                                       "scope": "formula caches", "reason": reason})
                        caches_read = False
                entries = []
                for (row, col), value in formula_cells:
                    cached = cache.get((row, col), {}).get("value")
                    expression = value if isinstance(value, str) else getattr(value, "text", None)
                    formula = {"coordinate": f"{get_column_letter(col)}{row}", "formula": expression,
                               "cached_value": json_value(cached),
                               "cache_missing": cached is None if caches_read else None}
                    if not isinstance(value, str):
                        formula["attributes"] = dict(value)
                    entries.append(formula)
                missing_cache_count = sum(entry["cache_missing"] for entry in entries) if caches_read else None
                protected = bool(getattr(getattr(parser, "protection", None), "sheet", False))
                metadata.update(used_range=table.locator["range"], read_range=table.locator["data_range"],
                                header_candidates=candidates, selected_header_row=table.locator["header_row"],
                                merged_ranges=sorted(str(span) for span in merged), protected=protected,
                                formula_count=len(entries), formulas=entries, uncached_formula_count=missing_cache_count)
                if missing_cache_count:
                    warnings.append(f"Sheet {name!r} contains formulas without cached values.")
                if protected:
                    warnings.append(f"Sheet {name!r} is marked protected.")
                rows = len(table.frame)
                table.details["coverage"] = {
                    "rows_read": rows, "rows_total_or_unknown": UNKNOWN if table.header_uncertain else rows,
                    "unread": unread[unread_start:],
                }
                source.tables.append(table)
        finally:
            reader.archive.close()
    rows = sum(len(table.frame) for table in source.tables)
    uncertain_total = unread or any(
        table.details["coverage"]["rows_total_or_unknown"] == UNKNOWN for table in source.tables
    )
    extent(source, rows, UNKNOWN if uncertain_total else rows, unread)


def read_parquet(source, path, has_header, has_footer):
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        missing_dependency("pyarrow", "reading Parquet files")

    markers = "PAR1 file magic." if has_header else "PAR1 file magic missing."
    markers += " PAR1 footer magic." if has_footer else " PAR1 footer magic missing."
    detect(source, "parquet", markers)
    rows, refs, unread, groups = [], [], [], []
    with path.open("rb") as binary, pq.ParquetFile(binary) as reader:
        schema = reader.schema_arrow
        report = source.report
        report.update(schema=[{"name": field.name, "type": str(field.type), "nullable": field.nullable}
                              for field in schema], row_group_count=reader.num_row_groups,
                      metadata_row_count=reader.metadata.num_rows, row_groups=groups)
        offset = 0
        for index in range(reader.num_row_groups):
            count = reader.metadata.row_group(index).num_rows
            locations = {"row_group": index, "row_range": [offset + 1, offset + count] if count else None}
            try:
                arrow = reader.read_row_group(index)
                columns = [column.to_pylist() for column in arrow.columns]
                rows.extend(zip(*columns, strict=True) if columns else [[] for _ in range(count)])
                refs.extend(range(offset + 1, offset + count + 1))
                groups.append({**locations, "columns_read": schema.names, "rows_read": count})
            except (pa.ArrowException, OSError, ValueError, NotImplementedError, OverflowError) as error:
                unread.append({**locations, "columns": schema.names, "reason": str(error)})
                groups.append({**locations, "columns_read": [], "rows_read": 0})
            offset += count
        source.tables.append(make_table("parquet:1", {"row_groups": [group["row_group"] for group in groups
                                                                      if group["columns_read"] or not schema.names]},
                                        rows, refs, schema.names, source_headers=schema.names))
        extent(source, len(rows), reader.metadata.num_rows, unread)
        if unread:
            report["warnings"].append("Some Parquet row groups could not be read.")


def read_source(path, *, sheet=None, header_row=None, delimiter=None, header=None, encoding=None,
                quotechar=None):
    path = Path(path)
    extension = path.suffix.lower()
    source = Source({
        "path": str(path), "extension": extension, "extension_format": FORMATS.get(extension),
        "detected_format": UNKNOWN, "evidence": [], "conflict": False,
        "encoding": None, "warnings": [],
    })
    try:
        with path.open("rb") as binary:
            start = binary.read(8)
            if start.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
                with zipfile.ZipFile(binary) as container:
                    workbook = "xl/workbook.xml" in container.namelist()
                if workbook:
                    read_excel(source, path, sheet, header_row)
                else:
                    detect(source, "zip", "ZIP container without an Excel workbook part.")
                    fail(source, "Unsupported ZIP container.", range=UNKNOWN)
            elif start == b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
                detect(source, "xls", "OLE2 compound file signature.")
                fail(source, "unsupported: convert to xlsx", range=UNKNOWN)
            else:
                binary.seek(-4 if len(start) >= 4 else 0, io.SEEK_END)
                end = binary.read(4)
                has_header = start.startswith(b"PAR1")
                has_footer = end == b"PAR1"
                binary_header = has_header and CONTROL.search(start[4:].decode("latin-1"))
                parquet_extension = extension == ".parquet" and (has_header or has_footer)
                if (has_header and has_footer) or binary_header or parquet_extension:
                    read_parquet(source, path, has_header, has_footer)
                else:
                    binary.seek(0)
                    read_text(source, binary.read(), delimiter=delimiter, header=header,
                              encoding=encoding, quotechar=quotechar)
    except (OSError, ValueError, KeyError, SyntaxError, RecursionError, zipfile.BadZipFile) as error:
        fail(source, f"Could not read source: {error}", range=UNKNOWN)
    return source


JSON_PATH_KEY = r'"(?:[^"\\\x00-\x1f]|\\(?:["\\/bfnrt]|u[0-9A-Fa-f]{4}))*"'
PATH_TOKEN = re.compile(rf'\.({IDENTIFIER.pattern})|\[(\*|[0-9]+|{JSON_PATH_KEY})\]')
JSON_PATH = re.compile(rf'\$(?:{PATH_TOKEN.pattern})*')


def select_json(document, record_path):
    if not isinstance(record_path, str) or not record_path.startswith("$"):
        raise ValueError("JSON record path must start with '$'.")
    tokens = []
    end = 1
    while end < len(record_path):
        match = PATH_TOKEN.match(record_path, end)
        if not match:
            raise ValueError(f"Invalid JSON record path at character {end}: {record_path!r}.")
        tokens.append(match.groups())
        end = match.end()
    matches = [("$", document)]
    unread = []
    for attribute, bracket in tokens:
        selected = []
        for ref, value in matches:
            if attribute or bracket.startswith('"'):
                key = attribute or json.loads(bracket)
                target = ref + key_path(key)
                if isinstance(value, dict) and key in value:
                    selected.append((target, value[key]))
                else:
                    unread.append({"json_path": target, "reason": "Selected field is absent in this branch."})
            elif isinstance(value, list):
                indices = range(len(value)) if bracket == "*" else [int(bracket)]
                selected.extend((f"{ref}[{index}]", value[index]) for index in indices if index < len(value))
                if bracket != "*" and int(bracket) >= len(value):
                    unread.append({"json_path": f"{ref}[{bracket}]", "reason": "Selected index is out of range."})
            else:
                unread.append({"json_path": ref, "reason": "Array selector reached a non-array value."})
        matches = selected
    arrays = []
    for ref, value in matches:
        if isinstance(value, list):
            arrays.append((ref, value))
        else:
            unread.append({"json_path": ref, "reason": "Record path reached a non-array value."})
    if not arrays:
        raise ValueError(f"JSON record path must resolve to at least one array: {record_path!r}.")
    return [(f"{ref}[{index}]", record) for ref, values in arrays for index, record in enumerate(values)], unread


def load_table(path, *, table_id=None, sheet=None, json_record_path=None,
               header_row=None, delimiter=None, header=None, encoding=None, quotechar=None):
    if sum(option is not None for option in (table_id, sheet, json_record_path)) > 1:
        raise ValueError("Select one of table_id, sheet, or json_record_path.")
    selected_sheet = table_id[6:] if table_id and table_id.startswith("sheet:") else sheet
    if header_row is not None and selected_sheet is None:
        raise ValueError("An explicit header row requires a selected sheet.")
    source = read_source(path, sheet=selected_sheet, header_row=header_row, delimiter=delimiter,
                         header=header, encoding=encoding, quotechar=quotechar)
    fmt = source.report["detected_format"]
    if encoding is not None and fmt == UNKNOWN and source.report["encoding"] is None:
        raise ValueError(" ".join(source.report["warnings"]))
    if fmt == "json" and "record_candidates" in source.report:
        candidate_ids = {item["id"]: item["path"] for item in source.report["record_candidates"]}
        if table_id is not None:
            if table_id not in candidate_ids:
                raise ValueError(f"Unknown JSON table id: {table_id!r}.")
            json_record_path = candidate_ids[table_id]
        if json_record_path is None:
            raise ValueError("JSON requires an explicit json_record_path or candidate table id.")
        locator = {"json_path": json_record_path}
        if json_record_path == "$" and isinstance(source.document, dict):
            records, unread = [("$", source.document)], []
        else:
            records, unread = select_json(source.document, json_record_path)
        table = json_table(records, f"json:{json_record_path}", locator)
        coverage = {"rows_read": len(records), "rows_total_or_unknown": UNKNOWN if unread else len(records),
                    "unread": unread}
        if unread:
            source.report["warnings"].append("The record path could not be read in every branch.")
    else:
        if fmt in {"csv", "tsv"} and delimiter is None and len(source.report["delimiter_candidates"]) > 1:
            raise ValueError(f"Competing delimiters {source.report['delimiter_candidates']!r}; select --delimiter.")
        if json_record_path is not None:
            raise ValueError("A JSON record path requires a readable JSON document.")
        if sheet is not None and fmt != "xlsx":
            raise ValueError("A sheet selector requires an Excel workbook.")
        tables = source.tables if table_id is None else [table for table in source.tables if table.id == table_id]
        if len(tables) != 1:
            details = " ".join(source.report["warnings"])
            if len(tables) > 1:
                raise ValueError(f"Multiple tables; select a table id: {[table.id for table in tables]!r}.")
            raise ValueError(f"No readable table for the requested selection. {details}")
        table = tables[0]
        coverage = dict(source.report["read_extent"])
        coverage["rows_read"] = len(table.frame)
        if fmt == "markdown":
            scoped_out = [{"line_range": other.locator["line_range"], "reason": "Table outside requested scope."}
                          for other in source.tables if other is not table]
            coverage.update(rows_total_or_unknown=len(table.frame), unread=coverage["unread"] + scoped_out)
        elif fmt == "xlsx":
            coverage["rows_total_or_unknown"] = table.details["coverage"]["rows_total_or_unknown"]
            table.details["sheet_names"] = [entry["name"] for entry in source.report["sheets"]]
    table.details.update(detected_format=fmt, coverage=coverage, warnings=source.report["warnings"],
                         conflict=source.report["conflict"])
    return table


def add_table_args(parser: argparse.ArgumentParser, *, select_table=True):
    if select_table:
        selectors = parser.add_mutually_exclusive_group()
        selectors.add_argument("--table-id", help="Table or record-candidate id from inspect_data.py.")
        selectors.add_argument("--sheet", help="Excel sheet name.")
        selectors.add_argument("--json-record-path", help="JSON array path, e.g. $.days[*].orders, or '$' for a root object.")
        parser.add_argument("--header-row", type=int, help="Excel header row; use 0 for no header.")
    parser.add_argument("--delimiter", help="Explicit delimiter character.")
    parser.add_argument("--header", choices=("yes", "no"), help="Explicit delimited-text header presence.")
    parser.add_argument("--encoding", help="Explicit text encoding for strict decoding.")


def refuse_source_output(output, *sources):
    output = Path(output)
    for entry in sources:
        source = Path(entry)
        if output.resolve() == source.resolve() or (
            output.exists() and source.exists() and output.samefile(source)
        ):
            raise ValueError(f"Output would overwrite a source file: {output}.")


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
        temp_path = Path(temporary.name)
        try:
            temporary.write(data)
            temporary.close()
            temp_path.replace(path)
        finally:
            temp_path.unlink(missing_ok=True)


def emit_json(payload, out=None):
    serialized = json.dumps(payload, allow_nan=False, ensure_ascii=True, indent=2)
    if out is None:
        print(serialized)
    else:
        atomic_write(out, (serialized + "\n").encode("utf-8"))
