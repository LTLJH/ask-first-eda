"""Audit source row coverage, retained values, totals, and formula-like text in cleaned CSVs."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, DecimalException, Inexact, InvalidOperation, localcontext
from itertools import chain
from pathlib import Path
import sys
from zipfile import is_zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eda_io import (
    GROUPED_NUMBER, NUMBER, add_table_args, emit_json, is_missing, load_table, neutralize_formula,
    numeric_decimal, read_source, refuse_source_output,
)


MISMATCH_LIMIT = 20
RECONCILE_EXAMPLE_LIMIT = 10
RECONCILE_GROUP_LIMIT = 50
TOTAL_COLUMNS = ("source_total", "kept_source_total", "cleaned_total", "excluded_total")


def find_formula_cells(table):
    rows = zip(table.row_refs, table.frame.itertuples(index=False, name=None), strict=True)
    header = table.locator.get("header_line_range")
    if header:
        rows = chain([(header[0], table.details["source_headers"])], rows)
    return [
        {"row": line, "column": column}
        for line, values in rows
        for column, value in zip(table.frame.columns, values)
        if isinstance(value, str) and neutralize_formula(value) != value
    ]


def read_references(path, *, excluded, errors, sheets):
    references = {}
    try:
        # An apostrophe at the start of a cleaned field is literal text.
        table = load_table(path, delimiter=",", header=True, quotechar=None if excluded else '"')
    except ValueError as error:
        errors.append(f"{path}: {error}")
        return references, None, []
    errors.extend(f"{path}: {entry['reason']}" for entry in table.details["coverage"]["unread"])
    formula_cells = [] if excluded else find_formula_cells(table)
    required = {"_source_row", "reason"} if excluded else {"_source_row"}
    missing = required.difference(table.frame.columns)
    if missing:
        errors.append(f"{path}: Missing columns: {', '.join(sorted(missing))}.")
        return references, table, formula_cells

    rows = zip(table.row_refs, table.frame.to_dict("records"), strict=True)
    for position, (line, record) in enumerate(rows):
        sheet = record.get("_source_sheet") or ""
        sheets.add(sheet)
        value = record["_source_row"]
        try:
            row = str(int(value))
        except (TypeError, ValueError, OverflowError):
            if not isinstance(value, str) or not value.strip():
                errors.append(f"{path}:{line}: Invalid _source_row.")
                continue
            row = value
        if excluded and not (record["reason"] or "").strip():
            errors.append(f"{path}:{line}: Exclusion requires a reason.")
            continue
        references[position] = (sheet, row)
    return references, table, formula_cells


def resolve_cleaned_sheets(references, sheet_names, errors):
    aliases = {}
    for name in sheet_names:
        cleaned_name = neutralize_formula(name)
        aliases[cleaned_name] = None if cleaned_name in aliases else name
    if all(cleaned_name == original for cleaned_name, original in aliases.items()):
        return references

    resolved = {}
    for name, row in sorted(set(references.values())):
        original = aliases.get(name, name)
        if original is None:
            errors.append(f"Source sheet reference {name!r} at row {row} is ambiguous after formula neutralization.")
        else:
            resolved[name, row] = (original, row)
    return {position: resolved[address] for position, address in references.items() if address in resolved}


def source_address(sheet, row):
    address = f"source row {row}"
    return f"{address} in sheet {sheet!r}" if sheet else address


def passthrough_equal(cleaned_value, source_value):
    cleaned_text = "" if is_missing(cleaned_value) else str(cleaned_value).strip()
    source_text = "" if is_missing(source_value) else str(source_value).strip()
    if cleaned_text == source_text:
        return True
    if GROUPED_NUMBER.fullmatch(source_text):
        source_text = source_text.replace(",", "")
    if NUMBER.fullmatch(cleaned_text) and NUMBER.fullmatch(source_text):
        try:
            return Decimal(cleaned_text) == Decimal(source_text)
        except InvalidOperation:
            return False
    return False


def check_passthrough(cleaned, references, sources, mappings, errors):
    for column in dict.fromkeys(cleaned_column for cleaned_column, _ in mappings):
        if column not in cleaned.frame.columns:
            errors.append(f"Unknown cleaned column {column!r} for --passthrough.")

    source_columns = dict.fromkeys(source_column for _, source_column in mappings)
    kept_sheets = {sheet for sheet, _ in references.values()}
    kept_sources = {sheet: source for sheet, source in sources.items() if sheet in kept_sheets}
    if not kept_sources:
        available_columns = {column for source in sources.values() for column in source.frame.columns}
        for column in source_columns:
            if column not in available_columns:
                errors.append(f"Unknown source column {column!r} for --passthrough.")
        return

    comparisons = {}
    for sheet, source in kept_sources.items():
        scope = f" in sheet {sheet!r}" if sheet else ""
        for column in source_columns:
            if column not in source.frame.columns:
                errors.append(f"Unknown source column {column!r}{scope} for --passthrough.")
        pairs = [(left, right) for left, right in mappings
                 if left in cleaned.frame.columns and right in source.frame.columns]
        if pairs:
            positions = {str(row): index for index, row in enumerate(source.row_refs)}
            comparisons[sheet] = (source.frame, positions, pairs)

    mismatches = 0
    for position, (sheet, row) in references.items():
        if sheet not in comparisons:
            continue
        frame, positions, pairs = comparisons[sheet]
        if row not in positions:
            continue
        for cleaned_column, source_column in pairs:
            cleaned_value = cleaned.frame.at[position, cleaned_column]
            source_value = frame.at[positions[row], source_column]
            if not passthrough_equal(cleaned_value, source_value):
                mismatches += 1
                if mismatches <= MISMATCH_LIMIT:
                    errors.append(
                        f"Passthrough mismatch at {source_address(sheet, row)}: "
                        f"source column {source_column!r} has {source_value!r}, "
                        f"cleaned column {cleaned_column!r} has {cleaned_value!r}."
                    )
    if mismatches > MISMATCH_LIMIT:
        errors.append(f"{mismatches} passthrough mismatches in total (showing the first {MISMATCH_LIMIT}).")


def check_reconcile(cleaned, references, removed, sources, mappings, tolerance, errors):
    invalid_values = 0

    def read_number(value, column, address):
        nonlocal invalid_values
        if isinstance(value, str):
            value = value.strip()
            if GROUPED_NUMBER.fullmatch(value):
                value = value.replace(",", "")
        if is_missing(value) or value == "":
            return Decimal(0)
        number = numeric_decimal(value)
        if number is None:
            invalid_values += 1
            if invalid_values <= RECONCILE_EXAMPLE_LIMIT:
                errors.append(f"Non-numeric value in column {column!r} at {address} for --reconcile.")
            return Decimal(0)
        return number

    kept = set(references.values())
    entries = []
    for cleaned_column, source_column, group_column in mappings:
        entry = {"cleaned_col": cleaned_column, "source_col": source_column,
                 "group_col": group_column, "groups": []}
        entries.append(entry)
        error_count = len(errors)
        if cleaned_column not in cleaned.frame.columns:
            errors.append(f"Unknown cleaned column {cleaned_column!r} for --reconcile.")
        for sheet, source in sources.items():
            scope = f" in sheet {sheet!r}" if sheet else ""
            for column in dict.fromkeys((source_column, group_column)):
                if column is not None and column not in source.frame.columns:
                    errors.append(f"Unknown source column {column!r}{scope} for --reconcile.")
        if len(errors) != error_count or not sources:
            continue

        totals = defaultdict(lambda: dict.fromkeys(TOTAL_COLUMNS, Decimal(0)))
        if group_column is None:
            totals[None] = dict.fromkeys(TOTAL_COLUMNS, Decimal(0))
        kept_groups = {}
        for sheet, source in sources.items():
            labels = source.frame[group_column] if group_column is not None else (None for _ in source.row_refs)
            rows = zip(source.row_refs, source.frame[source_column], labels, strict=True)
            for row, value, label in rows:
                group = None if is_missing(label) or label == "" else str(label)
                address = (sheet, str(row))
                number = read_number(value, source_column, source_address(sheet, row))
                totals[group]["source_total"] += number
                if address in kept:
                    totals[group]["kept_source_total"] += number
                    kept_groups[address] = group
                if address in removed:
                    totals[group]["excluded_total"] += number

        for position, address in references.items():
            if address in kept_groups:
                group = kept_groups[address]
                value = cleaned.frame.at[position, cleaned_column]
                line = cleaned.row_refs[position]
                totals[group]["cleaned_total"] += read_number(value, cleaned_column, f"cleaned row {line}")

        mismatches = 0
        for group, sums in totals.items():
            difference = sums["cleaned_total"] - sums["kept_source_total"]
            if difference.copy_abs() > tolerance:
                mismatches += 1
            if len(entry["groups"]) < RECONCILE_GROUP_LIMIT:
                entry["groups"].append({"group": group, **{key: str(value) for key, value in sums.items()},
                                        "difference": str(difference)})
        if mismatches:
            errors.append(f"Reconcile difference exceeds tolerance in {mismatches} group(s) "
                          f"for {cleaned_column!r}={source_column!r}.")
        if len(totals) > RECONCILE_GROUP_LIMIT:
            entry["truncated_groups"] = len(totals) - RECONCILE_GROUP_LIMIT

    if invalid_values > RECONCILE_EXAMPLE_LIMIT:
        errors.append(f"{invalid_values} non-numeric values for --reconcile "
                      f"(showing the first {RECONCILE_EXAMPLE_LIMIT}).")
    return entries


def check_header(source, table, errors):
    if table.header_uncertain:
        sheet = table.locator.get("sheet")
        if sheet is None:
            errors.append(f"{source}: Header presence is uncertain; specify --header yes or --header no.")
        else:
            errors.append(f"{source}: Header is uncertain in sheet {sheet!r}; specify --header-row (0 for no header).")


def incompatible_options(fmt, *, header_row, delimiter, header, encoding):
    if header_row is not None and fmt != "xlsx":
        yield "--header-row requires an Excel workbook."
    if fmt not in {"csv", "tsv"}:
        if header is not None:
            context = "with --header-row" if header_row is not None else f"for {fmt} sources"
            yield f"--header cannot be used {context}; it requires delimited text."
        if delimiter is not None:
            yield f"--delimiter cannot be used for {fmt} sources."
    if encoding is not None and fmt in {"xlsx", "parquet", "xls", "zip"}:
        yield f"--encoding {encoding!r} cannot be used for {fmt} sources."


def audit(source, cleaned, excluded, *, table_id=None, sheet=None, json_record_path=None,
          header_row=None, delimiter=None, header=None, encoding=None, sheets=None,
          expand=False, passthrough=(), reconcile=(), reconcile_tolerance=Decimal(0)):
    reference_errors, referenced_sheets = [], set()
    kept_rows, cleaned_table, formula_cells = read_references(
        cleaned, excluded=False, errors=reference_errors, sheets=referenced_sheets,
    )
    removed_rows, _, _ = read_references(excluded, excluded=True, errors=reference_errors, sheets=referenced_sheets)
    errors = []
    source_tables = {}
    fmt = None
    sheet_names = set()
    sheet_scope = set(sheets) if sheets is not None else None
    selected_table = any(option is not None for option in (table_id, sheet, json_record_path))
    if not selected_table and (sheet_scope is not None or is_zipfile(source)):
        selections = (None,) if sheet_scope is None else sorted(sheet_scope)
        for selection in selections:
            workbook = read_source(source, sheet=selection, header_row=header_row,
                                   delimiter=delimiter, header=header, encoding=encoding)
            fmt = workbook.report["detected_format"]
            if fmt != "xlsx":
                errors.extend(f"{source}: {warning}" for warning in workbook.report["warnings"])
                break
            sheet_names.update(entry["name"] for entry in workbook.report["sheets"])
            if selection is not None and selection not in sheet_names:
                errors.append(f"{source}: Unknown sheet {selection!r}.")
            tables = {table.locator["sheet"]: table for table in workbook.tables}
            # Loaded tables already supply row addresses even if preamble or formula caches were skipped.
            for entry in workbook.report["read_extent"]["unread"]:
                name = entry.get("sheet")
                if name not in tables and (selection is None or name in (None, selection)):
                    errors.append(f"{source}: {entry['reason']}")
            for table in tables.values():
                check_header(source, table, errors)
            source_tables.update(tables)
    else:
        try:
            table = load_table(source, table_id=table_id, sheet=sheet, json_record_path=json_record_path,
                               header_row=header_row, delimiter=delimiter, header=header, encoding=encoding)
        except ValueError as error:
            errors.append(f"{source}: {error}")
        else:
            fmt = table.details["detected_format"]
            check_header(source, table, errors)
            name = table.locator["sheet"] if fmt == "xlsx" else ""
            if fmt == "xlsx":
                sheet_names.update(table.details["sheet_names"])
                if sheet_scope is not None and sheet_scope != {name}:
                    errors.append(f"{source}: --sheets must name only the selected sheet {name!r}.")
                sheet_scope = {name} if sheet_scope is None else sheet_scope & {name}
            elif fmt != "markdown":
                errors.extend(f"{source}: {entry['reason']}" for entry in table.details["coverage"]["unread"])
            if fmt != "xlsx" or name in sheet_scope:
                source_tables[name] = table

    expected = {(name, str(row)): row for name, table in source_tables.items() for row in table.row_refs}
    if fmt is not None:
        errors.extend(f"{source}: {error}" for error in incompatible_options(
            fmt, header_row=header_row, delimiter=delimiter, header=header, encoding=encoding,
        ))
    is_excel = fmt == "xlsx"
    if is_excel:
        kept_rows = resolve_cleaned_sheets(kept_rows, sheet_names, errors)
    kept = set(kept_rows.values())
    removed = set(removed_rows.values())
    if not expand:
        for (name, row), count in Counter(kept_rows.values()).items():
            if count > 1:
                errors.append(f"Duplicate cleaned reference to {source_address(name, row)} ({count} times).")
    if passthrough and cleaned_table is not None:
        check_passthrough(cleaned_table, kept_rows, source_tables, passthrough, errors)
    reconciled = []
    if reconcile and cleaned_table is not None:
        with localcontext() as context:
            context.traps[Inexact] = True
            reconciled = check_reconcile(cleaned_table, kept_rows, removed, source_tables,
                                         reconcile, reconcile_tolerance, errors)
    conflicts = [
        f"Source row {row} in sheet {name!r} is both kept and excluded."
        for name, row in sorted(kept & removed)
    ]
    explained = kept | removed
    if sheets is not None and not is_excel:
        errors.append("--sheets requires an Excel workbook.")
    if is_excel and "" in referenced_sheets:
        errors.append("Excel row references require _source_sheet.")
    for name, row in sorted(explained - expected.keys()):
        if is_excel and sheet_scope is not None and name and name not in sheet_scope:
            errors.append(f"Source row {row} in sheet {name!r} is outside the audit scope.")
        else:
            errors.append(f"Unknown source row {row} in sheet {name!r}.")
    unexplained = [{"sheet": name, "row": row} for name, row in sorted(
        (key[0], expected[key]) for key in expected.keys() - explained
    )]
    errors = reference_errors + conflicts + errors
    result = {
        "status": "fail" if errors or unexplained or formula_cells else "pass",
        "unexplained": unexplained,
        "errors": errors,
    }
    if formula_cells:
        result["formula_cells"] = formula_cells
    if reconcile:
        result["reconcile"] = reconciled
    return result


def parse_passthrough(argument):
    cleaned_column, _, source_column = argument.partition("=")
    if not cleaned_column or not source_column:
        raise argparse.ArgumentTypeError("expected CLEANED_COL=SOURCE_COL")
    return cleaned_column, source_column


def parse_reconcile(argument):
    message = "expected CLEANED_COL=SOURCE_COL[@GROUP]"
    try:
        cleaned_column, source_spec = parse_passthrough(argument)
    except argparse.ArgumentTypeError:
        raise argparse.ArgumentTypeError(message) from None
    source_column, separator, group_column = source_spec.partition("@")
    if not source_column or (separator and not group_column):
        raise argparse.ArgumentTypeError(message)
    return cleaned_column, source_column, group_column or None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--cleaned", required=True, type=Path)
    parser.add_argument("--excluded", required=True, type=Path)
    parser.add_argument("--out", type=Path, help="Write JSON to this file instead of stdout.")
    add_table_args(parser)
    parser.add_argument("--sheets", help="Comma-separated Excel sheet names (default: all sheets).")
    parser.add_argument("--expand", action="store_true", help="Allow multiple cleaned rows per source address.")
    parser.add_argument("--passthrough", action="append", type=parse_passthrough, default=[],
                        metavar="CLEANED_COL=SOURCE_COL", help="Audit values carried from a source column. Repeatable.")
    parser.add_argument("--reconcile", action="append", type=parse_reconcile, default=[],
                        metavar="CLEANED_COL=SOURCE_COL[@GROUP]", help="Compare sums by source group. Repeatable.")
    parser.add_argument("--reconcile-tolerance", default="0", help="Maximum absolute difference per group.")
    args = parser.parse_args()
    try:
        tolerance = numeric_decimal(args.reconcile_tolerance)
        if tolerance is None or tolerance < 0:
            raise ValueError("--reconcile-tolerance must be a finite non-negative number.")
        if args.out is not None:
            refuse_source_output(args.out, args.source, args.cleaned, args.excluded)
        sheets = args.sheets.split(",") if args.sheets is not None else None
        header = None if args.header is None else args.header == "yes"
        result = audit(args.source, args.cleaned, args.excluded, table_id=args.table_id, sheet=args.sheet,
                       json_record_path=args.json_record_path, header_row=args.header_row,
                       delimiter=args.delimiter, header=header, encoding=args.encoding, sheets=sheets,
                       expand=args.expand, passthrough=args.passthrough, reconcile=args.reconcile,
                       reconcile_tolerance=tolerance)
        emit_json(result, args.out)
    except DecimalException:
        parser.exit(1, "Error: Reconciliation exceeded Decimal precision or range.\n")
    except (OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    return int(result["status"] == "fail")


if __name__ == "__main__":
    sys.exit(main())
