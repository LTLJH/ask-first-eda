"""Render descriptive PNG charts. Paths in a chart spec are relative to the spec."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from functools import lru_cache
import io
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eda_io
from eda_io import (
    atomic_write,
    datetime_value,
    emit_json,
    is_missing,
    json_value,
    load_table,
    numeric_value,
    refuse_source_output,
    value_key,
)

try:
    import numpy as np
except ImportError:
    eda_io.missing_dependency("numpy", "rendering charts")

try:
    import matplotlib as mpl
    from matplotlib import font_manager, ft2font
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.colors import LinearSegmentedColormap
    from matplotlib.figure import Figure
except ImportError:
    eda_io.missing_dependency("matplotlib", "rendering charts")


# Okabe–Ito palette shared by the charts.
BLUE, SKY, VERMILION = "#0072B2", "#56B4E9", "#D55E00"
FONT_PRIORITY = (
    "AppleGothic", "Apple SD Gothic Neo", "Malgun Gothic", "Noto Sans KR",
    "Noto Sans CJK", "NanumGothic",
)
CHART_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
NUMERIC_EXCLUSION = "Missing, non-finite, or non-numeric values in a required numeric column."


@lru_cache(maxsize=1)
def font_family():
    installed = sorted({font.name for font in font_manager.fontManager.ttflist})
    for preferred in FONT_PRIORITY:
        choices = [name for name in installed if name.casefold().startswith(preferred.casefold())]
        if preferred == "Noto Sans CJK":
            choices.sort(key=lambda name: ("KR" not in name, name))
        if choices:
            return choices[0]
    return "DejaVu Sans"


def missing_glyphs(texts, families):
    characters = {char for text in texts for char in text if not char.isspace()}
    if not characters:
        return []

    supported = set()
    try:
        for family in families:
            properties = font_manager.FontProperties(family=[family])
            path = font_manager.findfont(properties, fallback_to_default=False)
            supported.update(ft2font.FT2Font(path).get_charmap())
    except Exception:
        # A font lookup failure should not prevent rendering.
        return []
    return sorted(char for char in characters if ord(char) not in supported)


def with_unit(label, unit):
    return f"{label} ({unit})" if unit else label


def render(frame, output, kind, columns, used, reason, draw, *, chart_id=None,
           title=None, x_label=None, y_label=None, x_unit=None, y_unit=None, labels):
    output = Path(output)
    plot_title = kind.replace("_", " ").capitalize() if title is None else title
    families = list(dict.fromkeys((font_family(), "DejaVu Sans")))
    drawn = {}
    with mpl.rc_context({
        "font.family": families,
        "axes.unicode_minus": False, "text.usetex": False,
        "text.parse_math": False, "figure.facecolor": "#ffffff", "axes.facecolor": "#ffffff",
        "axes.spines.top": False, "axes.spines.right": False, "axes.axisbelow": True,
        "grid.alpha": 0.24, "savefig.facecolor": "#ffffff",
    }):
        figure = Figure(figsize=(8.4, 4.8), dpi=130, layout="constrained")
        FigureCanvasAgg(figure)
        axis = figure.subplots()
        axis.set_title(f"{plot_title}\nn = {used:,}", loc="left", pad=12)
        axis.set_xlabel(with_unit(labels[0] if x_label is None else x_label, x_unit))
        axis.set_ylabel(with_unit(labels[1] if y_label is None else y_label, y_unit))
        if used or kind == "corr_heatmap":
            drawn = draw(axis, figure) or {}
        else:
            axis.text(0.5, 0.5, "No usable rows", ha="center", va="center", transform=axis.transAxes)
        with io.BytesIO() as image:
            figure.savefig(image, format="png")
            atomic_write(output, image.getvalue())
        texts = [axis.get_title(loc="left")]
        for chart_axis in figure.axes:
            texts.extend((chart_axis.get_xlabel(), chart_axis.get_ylabel()))
            texts.extend(label.get_text() for label in chart_axis.get_xticklabels(which="both"))
            texts.extend(label.get_text() for label in chart_axis.get_yticklabels(which="both"))
        missing = missing_glyphs(texts, families)
        figure.clear()
    excluded = len(frame) - used
    return {
        "id": output.stem if chart_id is None else chart_id, "type": kind, "source_columns": list(columns),
        "n_used": used, "n_excluded": excluded, "exclusion_reason": reason if excluded else None,
        "image_path": str(output.resolve()), "missing_glyphs": missing, **drawn,
    }


def numbers(series):
    return [numeric_value(value) for value in series]


def histogram(frame, column, output, *, bins="auto", **options):
    values = [value for value in numbers(frame[column]) if value is not None]
    reason = NUMERIC_EXCLUSION
    if values and np.ndim(bins) > 0:
        edges = np.histogram_bin_edges(values, bins=bins)
        in_range = [value for value in values if edges[0] <= value <= edges[-1]] if len(edges) >= 2 else []
        if len(in_range) < len(values):
            reason = "Values outside the histogram bin range."
            if len(values) < len(frame):
                reason = f"{NUMERIC_EXCLUSION} {reason}"
        values = in_range

    def draw(axis, _figure):
        axis.hist(values, bins=bins, color=BLUE, edgecolor="white")
        axis.grid(axis="y")

    return render(frame, output, "histogram", [column], len(values), reason, draw,
                  labels=(column, "Rows"), **options)


def boxplot(frame, column, output, **options):
    values = [value for value in numbers(frame[column]) if value is not None]

    def draw(axis, _figure):
        axis.boxplot(values, patch_artist=True, tick_labels=[column],
                     boxprops={"facecolor": SKY}, medianprops={"color": VERMILION, "linewidth": 2})
        axis.grid(axis="y")

    return render(frame, output, "boxplot", [column], len(values), NUMERIC_EXCLUSION, draw,
                  labels=("", column), **options)


def category(value):
    if is_missing(value):
        return ("missing",), "(missing)"
    if isinstance(value, str):
        return ("value", value_key(value)), repr(value)
    return ("value", value_key(value)), json.dumps(json_value(value), ensure_ascii=False)


def bar_counts(frame, column, output, *, top=None, orientation="h", category_label=None,
               value_label=None, category_unit=None, value_unit=None, **options):
    if top is not None and (isinstance(top, bool) or not isinstance(top, int) or top < 1):
        raise ValueError("top must be a positive integer.")
    if orientation not in ("h", "v"):
        raise ValueError("orientation must be 'h' or 'v'.")
    horizontal = orientation == "h"
    category_axis, value_axis = ("y", "x") if horizontal else ("x", "y")
    defaults = {category_axis: column, value_axis: "Rows"}
    for axis_name, label, unit in ((category_axis, category_label, category_unit),
                                   (value_axis, value_label, value_unit)):
        if label is not None:
            options[f"{axis_name}_label"] = label
        if unit is not None:
            options[f"{axis_name}_unit"] = unit

    counts = Counter(category(value) for value in frame[column])
    shown = counts.most_common(top)
    used = sum(count for _, count in shown)

    def draw(axis, _figure):
        labels = [label for (_, label), _ in shown]
        counts = [count for _, count in shown]
        positions = range(len(shown))
        if horizontal:
            axis.barh(positions, counts, color=BLUE)
            axis.set_yticks(positions, labels=labels)
            axis.invert_yaxis()
        else:
            axis.bar(positions, counts, color=BLUE)
            axis.set_xticks(positions, labels=labels)
        axis.grid(axis=value_axis)

    return render(frame, output, "bar_counts", [column], used, "Category outside the requested top categories.",
                  draw, labels=(defaults["x"], defaults["y"]), **options)


def scatter(frame, x, y, output, **options):
    points = [(first, second) for first, second in zip(numbers(frame[x]), numbers(frame[y]), strict=True)
              if first is not None and second is not None]

    def draw(axis, _figure):
        horizontal, vertical = zip(*points)
        axis.scatter(horizontal, vertical, color=BLUE, alpha=0.7)
        axis.grid()

    return render(frame, output, "scatter", [x, y], len(points), NUMERIC_EXCLUSION, draw,
                  labels=(x, y), **options)


def corr_heatmap(frame, columns, output, **options):
    if not isinstance(columns, (list, tuple)) or not columns or len(set(columns)) != len(columns):
        raise ValueError("Correlation requires a nonempty list of distinct source columns.")
    matrix = np.column_stack([np.asarray(numbers(frame[column]), dtype=float) for column in columns])
    finite = np.isfinite(matrix)
    # Rows on the diagonal contribute to the displayed sample counts too.
    used = int(finite.any(axis=1).sum())
    size = len(columns)
    counts = np.zeros((size, size), dtype=int)
    correlations = np.full((size, size), np.nan)
    for i in range(size):
        for j in range(i, size):
            pairs = finite[:, i] & finite[:, j]
            count = int(pairs.sum())
            counts[i, j] = counts[j, i] = count
            if count >= 2:
                first, second = matrix[pairs, i], matrix[pairs, j]
                if first.min() != first.max() and second.min() != second.max():
                    # Scaling avoids intermediate overflow for very large values.
                    corr = np.corrcoef(first / np.max(np.abs(first)),
                                       second / np.max(np.abs(second)))[0, 1]
                    correlations[i, j] = correlations[j, i] = corr

    def draw(axis, figure):
        color_map = LinearSegmentedColormap.from_list("correlation", [VERMILION, "#fafafa", BLUE])
        color_map.set_bad("#ededed")
        image = axis.imshow(correlations, cmap=color_map, vmin=-1, vmax=1)
        axis.set_xticks(range(size), labels=columns, rotation=30, ha="right")
        axis.set_yticks(range(size), labels=columns)
        if size <= 10:
            for i in range(size):
                for j in range(size):
                    value = correlations[i, j]
                    coefficient = f"{value:.2f}" if np.isfinite(value) else "NA"
                    axis.text(j, i, f"{coefficient}\nn={counts[i, j]}", ha="center", va="center",
                              color="white" if np.isfinite(value) and abs(value) > 0.65 else "#202020")
        figure.colorbar(image, ax=axis, label="Pearson r")
        return {"pairwise_n": {first: {second: int(counts[i, j]) for j, second in enumerate(columns)}
                               for i, first in enumerate(columns)}}

    return render(frame, output, "corr_heatmap", columns, used,
                  "No usable numeric value in the selected columns.",
                  draw, labels=("", ""), **options)


def grouped_boxplot(frame, group, value, output, **options):
    groups = defaultdict(list)
    for label, number in zip(frame[group], numbers(frame[value]), strict=True):
        if number is not None:
            groups[category(label)].append(number)
    used = sum(len(values) for values in groups.values())

    def draw(axis, _figure):
        axis.boxplot(list(groups.values()), patch_artist=True,
                     tick_labels=[f"{label}\nn={len(values)}" for (_, label), values in groups.items()],
                     boxprops={"facecolor": SKY}, medianprops={"color": VERMILION, "linewidth": 2})
        axis.grid(axis="y")

    return render(frame, output, "grouped_boxplot", [group, value], used, NUMERIC_EXCLUSION,
                  draw, labels=(group, value), **options)


def line_time(frame, time, value, output, **options):
    observed = [(stamp, number) for label, number in zip(frame[time], numbers(frame[value]), strict=True)
                if (stamp := datetime_value(label)) is not None]
    modes = {stamp.tzinfo is not None for stamp, _ in observed}
    if len(modes) > 1:
        raise ValueError("Normalize mixed timezone-aware and naive timestamps before plotting.")
    labels = (f"{time} (UTC)" if True in modes and "x_label" not in options else time, value)
    if True in modes:
        observed = [(stamp.tz_convert("UTC"), number) for stamp, number in observed]
    observed.sort(key=lambda point: point[0])
    used = sum(number is not None for _, number in observed)

    def draw(axis, _figure):
        stamps, values = zip(*observed)
        axis.plot(stamps, [number if number is not None else np.nan for number in values],
                  color=BLUE, marker="o", markersize=4)
        axis.grid(axis="y")
        axis.tick_params(axis="x", labelrotation=25)

    return render(frame, output, "line_time", [time, value], used,
                  "Invalid or missing timestamp, or missing, non-finite, or non-numeric measure.",
                  draw, labels=labels, **options)


CHARTS = {
    "histogram": histogram, "boxplot": boxplot, "bar_counts": bar_counts, "scatter": scatter,
    "corr_heatmap": corr_heatmap, "grouped_boxplot": grouped_boxplot, "line_time": line_time,
}


def render_spec(spec_path, outdir, *, encoding=None, allowed_inputs=()):
    spec = json.loads(spec_path.read_text(encoding="utf-8-sig"))
    source = dict(spec["source"])
    try:
        spec_dir = spec_path.parent.resolve()
        path = (spec_dir / source.pop("path")).resolve()
        allowed = path.is_relative_to(spec_dir) or any(
            path == Path(input_path).resolve() for input_path in allowed_inputs
        )
    except (OSError, RuntimeError) as error:
        raise ValueError(f"Could not resolve source.path or --input: {error}") from error
    if not allowed:
        raise ValueError("source.path must resolve inside the plot spec directory or match a file passed via --input.")
    if encoding is not None:
        source["encoding"] = encoding
    charts = spec["charts"]
    if not isinstance(charts, list):
        raise ValueError("charts must be an array.")
    planned = []
    used_ids = set()
    for chart in charts:
        options = dict(chart)
        chart_id = options.pop("id")
        kind = options.pop("type")
        if not isinstance(chart_id, str) or not CHART_ID.fullmatch(chart_id) or chart_id.casefold() in used_ids:
            raise ValueError(f"Invalid or duplicate chart id: {chart_id!r}.")
        used_ids.add(chart_id.casefold())
        if kind not in CHARTS:
            raise ValueError(f"Unknown chart type: {kind!r}.")
        output = outdir / f"{chart_id}.png"
        refuse_source_output(output, path, spec_path)
        planned.append((CHARTS[kind], chart_id, output, options))
    table = load_table(path, **source)
    scope = {"source_table_id": table.id, "source_locator": table.locator,
             "read_extent": table.details["coverage"], "source_warnings": table.details["warnings"]}
    return [{**function(table.frame, output=output, chart_id=chart_id, **options), **scope}
            for function, chart_id, output, options in planned]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog=(
            "See references/plot_spec.example.json and its adjacent plot_example.csv. "
            f"Supported chart types: {', '.join(CHARTS)}. "
            "Each chart writes one PNG. The JSON array on stdout includes n_used, "
            "n_excluded and missing_glyphs for each chart."
        ),
    )
    parser.add_argument("--spec", type=Path, required=True, help="JSON containing source and charts.")
    parser.add_argument("--input", type=Path, action="append", default=[], metavar="PATH",
                        help="Allow this source file outside the spec directory. May be repeated.")
    parser.add_argument("--outdir", type=Path, required=True, help="Directory for rendered PNGs.")
    parser.add_argument("--encoding", help="Explicit source text encoding for strict decoding.")
    args = parser.parse_args()
    try:
        emit_json(render_spec(args.spec, args.outdir, encoding=args.encoding, allowed_inputs=args.input))
    except (OSError, TypeError, ValueError, KeyError) as error:
        parser.exit(1, f"Error: {error}\n")


if __name__ == "__main__":
    main()
