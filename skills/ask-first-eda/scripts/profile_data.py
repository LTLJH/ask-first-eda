"""Profile a single selected table and keep findings tied to source rows."""

from collections import Counter
from decimal import Decimal, localcontext
from pathlib import Path
import argparse
import math
import re
from statistics import mean, stdev
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eda_io import (
    add_table_args,
    column_info,
    datetime_value,
    emit_json,
    is_empty,
    is_missing,
    json_value,
    load_table,
    numeric_decimal,
    refuse_source_output,
    value_key,
)
import pandas as pd


UNIT_TOKEN = r"[%A-Za-zµμ°가-힣][%A-Za-zµμ°가-힣0-9²³/·^-]*"
UNIT_SUFFIX = re.compile(rf"^\s*[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\s*({UNIT_TOKEN})\s*$")
UNIT_NAME = re.compile(rf"(?:\(({UNIT_TOKEN})\)|\[({UNIT_TOKEN})\])\s*$")
UNIT_AFTER_UNDERSCORE = re.compile(
    r"_(kg|g|mg|t|lb|ml|L|kWh|Wh|mm|cm|km|m|ms|s|min|h|pct|rpm|psi|kPa|bar)$"
)


def statistic_value(value):
    if value is None:
        return None
    if value == value.to_integral_value() and value.adjusted() < 4000:
        return int(value)
    number = float(value)
    if not math.isfinite(number) or number == 0 or abs(number) >= 2**53:
        return str(value)
    return number


def numeric_summary(values, refs):
    positions = [(ref, number) for ref, value in zip(refs, values, strict=True)
                 if (number := numeric_decimal(value)) is not None]
    numbers = sorted(number for _, number in positions)

    def quartile(part):
        lower, remainder = divmod((len(numbers) - 1) * part, 4)
        first = numbers[lower]
        return first + (numbers[lower + 1] - first) * remainder / 4 if remainder else first

    stats = dict.fromkeys(("mean", "median", "std", "q1", "q3", "iqr", "lower_fence", "upper_fence"))
    if any(abs(value.as_tuple().exponent) > 10_000 for value in numbers):
        return {**stats, "count": len(numbers), "min": statistic_value(numbers[0]),
                "max": statistic_value(numbers[-1]), "outlier_count": None, "outlier_rows": [],
                "arithmetic_note": "A decimal exponent is outside the supported summary range."}
    with localcontext() as context:
        context.prec = max(34, min(4096, max(len(value.as_tuple().digits) for value in numbers) + 8))
        q1, median, q3 = (quartile(part) for part in (1, 2, 3))
        iqr = q3 - q1
        margin = Decimal("1.5") * iqr
        low, high = q1 - margin, q3 + margin
        outliers = [ref for ref, number in positions if number < low or number > high]
        stats.update(mean=mean(numbers), median=median, std=stdev(numbers) if len(numbers) > 1 else None,
                     min=numbers[0], q1=q1, q3=q3, max=numbers[-1], iqr=iqr, lower_fence=low, upper_fence=high)
        return {**{key: statistic_value(value) for key, value in stats.items()}, "count": len(numbers),
                "outlier_count": len(outliers), "outlier_rows": outliers}


def categorical_summary(values):
    labels = {}
    frequencies = Counter()
    for value in values:
        key = ("missing",) if is_missing(value) else ("value", value_key(value))
        labels.setdefault(key, json_value(value))
        frequencies[key] += 1
    return {"top": [{"value": labels[key], "count": count}
                    for key, count in frequencies.most_common(10)]}


def datetime_summary(values, refs):
    observed = [(stamp, ref) for value, ref in zip(values, refs, strict=True)
                if (stamp := datetime_value(value)) is not None]
    timezone_modes = {stamp.tzinfo is not None for stamp, _ in observed}
    if len(timezone_modes) > 1:
        return {"count": len(observed), "min": None, "max": None, "interval_distribution": [],
                "missing_intervals": [],
                "interval_note": "Naive and timezone-aware timestamps cannot share an inferred timeline."}
    observed.sort(key=lambda item: item[0])
    span = {"count": len(observed), "min": observed[0][0].isoformat(),
            "max": observed[-1][0].isoformat()}
    try:
        gaps = [(after - before, before, after, first, last)
                for (before, first), (after, last) in zip(observed, observed[1:])]
        distribution = Counter(gap for gap, *_ in gaps)
        positive = sorted(gap for gap in distribution if gap > pd.Timedelta(0))
        candidate = positive[0] if len(gaps) >= 2 and positive else None
        if candidate is not None and any(gap % candidate != pd.Timedelta(0) for gap in positive):
            candidate = None
        missing = [
            {"after": before.isoformat(), "before": after.isoformat(), "after_row": first,
             "before_row": last, "missing_count": int(gap // candidate) - 1}
            for gap, before, after, first, last in gaps if candidate is not None and gap > candidate
        ]
    except (ValueError, ArithmeticError):
        return {**span, "interval_distribution": [], "missing_intervals": [],
                "interval_note": "Timestamp differences are outside the supported timedelta range."}
    return {
        **span,
        "interval_distribution": [{"seconds": gap.total_seconds(), "count": count}
                                  for gap, count in sorted(distribution.items())],
        "candidate_interval_seconds": candidate.total_seconds() if candidate is not None else None,
        "missing_intervals": missing,
        "interval_note": "Gaps are conditional on a grid at the shortest observed positive interval."
        if candidate is not None else "The observed spacings do not establish a candidate regular grid.",
    }


def unit_summary(name, values):
    suffixes = Counter()
    for value in values:
        if isinstance(value, str) and numeric_decimal(value) is None and (match := UNIT_SUFFIX.fullmatch(value)):
            suffixes[match[1]] += 1
    annotated = UNIT_NAME.search(name)
    underscored = UNIT_AFTER_UNDERSCORE.search(name)
    name_unit = next(group for group in annotated.groups() if group) if annotated else (
        underscored[1] if underscored else None
    )
    return {
        "column_name_unit": name_unit,
        "suffix_counts": dict(suffixes),
        "mixed_suffixes": sorted(suffixes) if len(suffixes) > 1 else [],
        "suffixes_differing_from_column_name": sorted(unit for unit in suffixes if name_unit and unit != name_unit),
    }


def missing_patterns(frame, refs, columns):
    # Pattern summaries count the literal NA alongside blanks and nulls.
    missing = frame.isna() | frame.isin(["", "NA"])
    counts = missing.sum()
    incomplete = counts[counts > 0]
    selected = incomplete.nlargest(50)
    patterns = {name: {"by_group": [], "by_period": None, "co_missing": []} for name in selected.index}
    result = {"columns": patterns, "truncated_columns": len(incomplete) - len(selected)}
    if not patterns:
        return result

    targets = missing[selected.index]
    for info in columns:
        name = info["name"]
        present = len(frame) - counts[name]
        if not present:
            continue
        labels = frame[name].where(~missing[name])
        is_date = info["conversion_candidates"]["datetime"] == present
        if is_date:
            # ISO values and native dates both start with their local calendar month.
            labels = labels.astype("string").str.slice(0, 7)
        elif info["inferred_type"] not in {"string", "boolean"} or not 2 <= labels.nunique() <= 20:
            continue

        rates_by_target = targets.groupby(labels).mean()
        if len(rates_by_target) < 2:
            continue
        for target, rates in rates_by_target.items():
            if target == name:
                continue
            worst, best = rates.idxmax(), rates.idxmin()
            high, low = float(rates[worst]), float(rates[best])
            summary = {"max_rate": high, "min_rate": low, "spread": high - low}
            if is_date:
                previous = patterns[target]["by_period"]
                if previous is None or summary["spread"] > previous["spread"]:
                    patterns[target]["by_period"] = {
                        "date_col": name, "worst_period": worst, "best_period": best, **summary,
                    }
            else:
                patterns[target]["by_group"].append({"group_col": name, "worst_group": json_value(worst), **summary})

    source_rows = pd.Series(refs, index=frame.index)
    for name, pattern in patterns.items():
        groups = sorted(pattern["by_group"], key=lambda group: group["spread"], reverse=True)[:3]
        for group in groups:
            in_group = frame[group["group_col"]].eq(group["worst_group"])
            group["worst_rows"] = source_rows[targets[name] & in_group].head(10).tolist()
        pattern["by_group"] = groups

        both = targets.loc[targets[name]].sum().drop(name)
        both = both[both > 0]
        union = selected[both.index] + selected[name] - both
        scores = (both / union).nlargest(3)
        pattern["co_missing"] = [
            {"column": other, "both_missing": int(both[other]), "jaccard": score}
            for other, score in scores.items()
        ]
    return result


def profile_data(path, **selection):
    table = load_table(path, **selection)
    frame, refs = table.frame, table.row_refs
    absent = {ref: set(names) for ref, names in table.details.get("absent_fields", {}).items()}
    columns, keys, key_candidates = [], [], []
    for name, series in frame.items():
        values = series.tolist()
        info = column_info(values)
        missing = info["n_missing"]
        row_keys = [("absent",) if name in absent.get(ref, ()) else
                    ("missing",) if is_missing(value) else ("value", value_key(value))
                    for ref, value in zip(refs, values, strict=True)]
        if "absent_fields" in table.details:
            info["n_absent"] = row_keys.count(("absent",))
        unique = len({key for key, value in zip(row_keys, values, strict=True)
                      if not is_missing(value) and not is_empty(value)})
        info.update(name=name, missing_ratio=missing / len(frame) if len(frame) else None,
                    n_unique=unique, units=unit_summary(name, values))
        kind = info["inferred_type"]
        if kind == "numeric":
            info["numeric"] = numeric_summary(values, refs)
        elif kind == "datetime":
            info["datetime"] = datetime_summary(values, refs)
        else:
            info["categorical"] = categorical_summary(values)
        if len(frame) and not missing and unique == len(frame) and kind not in {"nested", "mixed"}:
            key_candidates.append(name)
        keys.append(row_keys)
        columns.append(info)

    seen, examples = set(), []
    duplicates = 0
    for ref, key in zip(refs, zip(*keys, strict=True) if keys else [()] * len(refs), strict=True):
        if key in seen:
            duplicates += 1
            if len(examples) < 10:
                examples.append(ref)
        seen.add(key)
    return {
        "path": str(path), "table_id": table.id, "locator": table.locator,
        "detected_format": table.details["detected_format"], "conflict": table.details["conflict"],
        "read_extent": table.details["coverage"], "warnings": table.details["warnings"],
        "irregular_rows": table.details.get("irregular_rows", []),
        "n_rows": len(frame), "n_cols": len(frame.columns), "row_refs": refs, "columns": columns,
        "duplicate_rows": {"count": duplicates, "example_rows": examples}, "key_candidates": key_candidates,
        "missing_patterns": missing_patterns(frame, refs, columns),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("--out", type=Path, help="Write JSON to this file instead of stdout.")
    add_table_args(parser)
    args = parser.parse_args()
    try:
        if args.out:
            refuse_source_output(args.out, args.path)
        header = None if args.header is None else args.header == "yes"
        result = profile_data(args.path, table_id=args.table_id, sheet=args.sheet,
                              json_record_path=args.json_record_path, header_row=args.header_row,
                              delimiter=args.delimiter, header=header, encoding=args.encoding)
        emit_json(result, args.out)
    except (OSError, TypeError, ValueError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
