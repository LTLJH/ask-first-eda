"""Check join key multiplicities, row counts, and control totals."""

import argparse
from collections import Counter
from decimal import Decimal, Inexact, localcontext
from itertools import repeat
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eda_io import (
    GROUPED_NUMBER,
    add_table_args,
    emit_json,
    is_missing,
    load_table,
    numeric_decimal,
    refuse_source_output,
)


SIDES = ("left", "right")


def key_rows(table, columns, normalize):
    keys, changed = [], set()
    for values in table.frame[columns].itertuples(index=False, name=None):
        raw = tuple("" if is_missing(value) else str(value) for value in values)
        key = tuple(value.strip() for value in raw) if "trim" in normalize else raw
        if "casefold" in normalize:
            key = tuple(value.casefold() for value in key)
        keys.append(key if all(key) else None)
        if keys[-1] is not None and key != raw:
            changed.add(key)
    return keys, changed


def row_examples(refs):
    count, examples = 0, []
    for ref in refs:
        count += 1
        if len(examples) < 10:
            examples.append(ref)
    return {"count": count, "example_rows": examples}


def amounts(table, side, column):
    result = []
    for value, ref in zip(table.frame[column], table.row_refs, strict=True):
        if isinstance(value, str):
            value = value.strip()
            if GROUPED_NUMBER.fullmatch(value):
                value = value.replace(",", "")
        number = Decimal(0) if is_missing(value) or value == "" else numeric_decimal(value)
        if number is None:
            raise ValueError(f"{side}:{column} has a non-numeric value at row {ref}.")
        result.append(number)
    return result


def amount_sum(values, weights=None):
    terms = [(value, weight) for value, weight in zip(
        values, repeat(1, len(values)) if weights is None else weights, strict=True,
    ) if value and weight]
    if not terms:
        return Decimal(0)
    lowest = min(value.as_tuple().exponent for value, _ in terms)
    highest = max(value.adjusted() for value, _ in terms)
    # Allow room for every input digit and the carry from the weighted sum.
    carry = len(str(sum(weight for _, weight in terms)))
    with localcontext() as context:
        context.prec = max(context.prec, highest - lowest + 1 + carry)
        context.traps[Inexact] = True
        return sum((value * weight for value, weight in terms), Decimal(0))


def check_join(tables, left_key, right_key, how, normalize, total_specs):
    result = {"how": how, "unmatched": {}, "totals": {}}
    keys, counts, changed = {}, {}, {}
    for side, columns in zip(SIDES, (left_key, right_key), strict=True):
        table = tables[side]
        keys[side], changed[side] = key_rows(table, columns, normalize)
        counts[side] = Counter(key for key in keys[side] if key is not None)
        result[side] = {
            "rows": len(keys[side]),
            "null_key_rows": row_examples(ref for key, ref in zip(keys[side], table.row_refs, strict=True)
                                          if key is None),
            "duplicate_keys": sum(count > 1 for count in counts[side].values()),
            "max_multiplicity": max(counts[side].values(), default=0),
        }

    matching = counts["left"].keys() & counts["right"].keys()
    expected = sum(counts["left"][key] * counts["right"][key] for key in matching)
    for side in SIDES:
        unmatched = row_examples(ref for key, ref in zip(keys[side], tables[side].row_refs, strict=True)
                                 if key not in matching)
        result["unmatched"][side] = unmatched
        if how in (side, "outer"):
            expected += unmatched["count"]

    result["expected_rows"] = expected
    result["relationship"] = "-to-".join(
        "many" if result[side]["duplicate_keys"] else "one" for side in SIDES
    )
    if normalize:
        result["normalized_matches"] = len(matching & (changed["left"] | changed["right"]))

    joined = tables.get("joined")
    result["joined_rows"] = len(joined.frame) if joined is not None else None
    failed = joined is not None and result["joined_rows"] != expected
    for spec in total_specs:
        side, _, column = spec.partition(":")
        if side not in SIDES or not column:
            raise ValueError("--total requires left:COL or right:COL.")
        other = "right" if side == "left" else "left"
        preserve = int(how in (side, "outer"))
        source = amounts(tables[side], side, column)
        weights = (counts[other].get(key, preserve) for key in keys[side])
        expected_total = amount_sum(source, weights)
        actual = amount_sum(amounts(joined, "joined", column)) if joined is not None else None
        result["totals"][spec] = {"source": str(amount_sum(source)), "expected": str(expected_total),
                                  "actual": str(actual) if actual is not None else None}
        failed |= actual is not None and actual != expected_total

    warned = result["relationship"] == "many-to-many" or any(result[side]["null_key_rows"]["count"] for side in SIDES)
    result["status"] = "fail" if failed else "warn" if warned else "pass"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, epilog="Delimited inputs have headers by default.")
    for side in SIDES:
        parser.add_argument(side, type=Path)
        parser.add_argument(f"--{side}-key", required=True, help="Comma-separated key columns.")
    parser.add_argument("--how", choices=("inner", "left", "right", "outer"), default="inner")
    parser.add_argument("--joined", type=Path, help="Joined table to verify.")
    parser.add_argument("--total", action="append", default=[], metavar="SIDE:COL")
    parser.add_argument("--normalize", metavar="TRIM,CASEFOLD", help="Comma-separated trim and/or casefold.")
    parser.add_argument("--out", type=Path, help="Write JSON to this file instead of stdout.")
    add_table_args(parser, select_table=False)
    parser.set_defaults(header="yes")
    for side in (*SIDES, "joined"):
        selection = parser.add_mutually_exclusive_group()
        selection.add_argument(f"--{side}-sheet")
        selection.add_argument(f"--{side}-table-id")
        selection.add_argument(f"--{side}-json-record-path")
        parser.add_argument(f"--{side}-header-row", type=int)
    args = parser.parse_args()

    try:
        paths = {side: getattr(args, side) for side in (*SIDES, "joined") if getattr(args, side) is not None}
        if args.out is not None:
            try:
                refuse_source_output(args.out, *paths.values())
            except ValueError as error:
                raise ValueError(f"refuse_source_output: {error}") from error
        normalize = {part.strip() for part in args.normalize.split(",")} if args.normalize is not None else set()
        if normalize - {"trim", "casefold"}:
            raise ValueError("--normalize accepts trim and/or casefold.")
        left_key, right_key = ([name.strip() for name in key.split(",")] for key in (args.left_key, args.right_key))
        if not all(left_key + right_key) or len(left_key) != len(right_key):
            raise ValueError("Provide the same number of nonempty key columns on each side.")
        tables = {}
        for side, path in paths.items():
            table = load_table(path, sheet=getattr(args, f"{side}_sheet"), table_id=getattr(args, f"{side}_table_id"),
                               json_record_path=getattr(args, f"{side}_json_record_path"),
                               header_row=getattr(args, f"{side}_header_row"),
                               delimiter=args.delimiter, header=args.header == "yes", encoding=args.encoding)
            if table.details["coverage"]["rows_total_or_unknown"] != len(table.frame):
                raise ValueError(f"{side}: selected table has incomplete row coverage.")
            tables[side] = table
        result = check_join(tables, left_key, right_key, args.how, normalize, args.total)
        emit_json(result, args.out)
    except KeyError as error:
        parser.exit(1, f"Error: Unknown column {error.args[0]}.\n")
    except (ArithmeticError, OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")
    if result["status"] == "fail":
        parser.exit(1, "Error: Joined row count or control totals differ from expectations.\n")


if __name__ == "__main__":
    main()
