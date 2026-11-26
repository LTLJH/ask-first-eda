import json
import re
import shutil
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest
from matplotlib import font_manager
from matplotlib.patches import Rectangle

import plots
from conftest import SCRIPTS


@pytest.fixture
def frame():
    return pd.DataFrame({
        "group": ["A", "B", "A"],
        "size": [10, 20, 30],
        "cost": [1, 3, 2],
        "date": ["2026-01-01", "2026-01-02", "2026-01-03"],
    })


@pytest.fixture
def axes_at_save(monkeypatch):
    snapshots = []
    original = plots.Figure.savefig

    def savefig(figure, *args, **kwargs):
        axis, *_ = figure.axes
        snapshots.append({
            "labels": (axis.get_xlabel(), axis.get_ylabel()),
            "ticks": ([tick.get_text() for tick in axis.get_xticklabels()],
                      [tick.get_text() for tick in axis.get_yticklabels()]),
            "bars": [(patch.get_width(), patch.get_height()) for patch in axis.patches
                     if isinstance(patch, Rectangle)],
            "titles": [axis.get_title(loc=loc) for loc in ("left", "center", "right")],
        })
        return original(figure, *args, **kwargs)

    monkeypatch.setattr(plots.Figure, "savefig", savefig)
    return snapshots


@pytest.mark.parametrize(("kind", "options", "expected"), [
    ("histogram", {"column": "size"}, ("size", "Rows")),
    ("boxplot", {"column": "size"}, ("", "size")),
    ("bar_counts", {"column": "group"}, ("Rows", "group")),
    ("scatter", {"x": "size", "y": "cost"}, ("size", "cost")),
    ("corr_heatmap", {"columns": ["size", "cost"]}, ("", "")),
    ("grouped_boxplot", {"group": "group", "value": "size"}, ("group", "size")),
    ("line_time", {"time": "date", "value": "cost"}, ("date", "cost")),
])
def test_axes_match_chart_inputs(kind, options, expected, frame, axes_at_save, tmp_path):
    chart = plots.CHARTS[kind](frame, output=tmp_path / "chart.png", **options)

    assert chart["n_used"] == 3
    assert axes_at_save[0]["labels"] == expected
    if kind == "corr_heatmap":
        assert axes_at_save[0]["ticks"] == (["size", "cost"], ["size", "cost"])


def test_histogram_counts_only_rows_within_explicit_bins(tmp_path, axes_at_save):
    frame = pd.DataFrame({"value": [1, 2, 10]})

    chart = plots.histogram(frame, "value", tmp_path / "histogram.png", bins=[0, 3])

    axis, = axes_at_save
    assert chart["n_used"] == sum(height for _, height in axis["bars"]) == 2
    assert chart["n_excluded"] == 1
    assert re.search(
        r"\b(?:outside|out[\s-]+of|beyond)\b.*\b(?:bins?|range|bounds|boundaries|edges|intervals?|limits?)\b"
        r"|\bbelow\b.*\babove\b",
        chart["exclusion_reason"] or "", re.I,
    )
    assert any(re.search(r"\bn = 2\b", title) for title in axis["titles"])


@pytest.mark.parametrize(("orientation", "labels", "category_axis", "value_dimension"), [
    ("h", ("Responses (rows)", "Group (code)"), 1, 0),
    ("v", ("Group (code)", "Responses (rows)"), 0, 1),
])
def test_count_bar_semantic_labels_follow_data(
    orientation, labels, category_axis, value_dimension, frame, axes_at_save, tmp_path,
):
    plots.bar_counts(frame, "group", tmp_path / "counts.png", orientation=orientation,
                     category_label="Group", category_unit="code", value_label="Responses", value_unit="rows")

    axis = axes_at_save[0]
    assert axis["labels"] == labels
    assert axis["ticks"][category_axis] == ["'A'", "'B'"]
    assert [bar[value_dimension] for bar in axis["bars"]] == [2, 1]


def test_count_bar_keeps_legacy_physical_axis_labels(frame, axes_at_save, tmp_path):
    plots.bar_counts(frame, "group", tmp_path / "counts.png", x_label="Responses", x_unit="rows",
                     y_label="Group", y_unit="code")

    assert axes_at_save[0]["labels"] == ("Responses (rows)", "Group (code)")


@pytest.mark.parametrize(("installed", "expected"), [
    ([], "DejaVu Sans"),
    (["Malgun Gothic"], "Malgun Gothic"),
    (["Noto Sans CJK JP", "Noto Sans CJK KR"], "Noto Sans CJK KR"),
    (["Apple SD Gothic Neo", "AppleGothic"], "AppleGothic"),
    (["Malgun Gothic", "Apple SD Gothic Neo"], "Apple SD Gothic Neo"),
    (["Noto Sans KR", "Malgun Gothic"], "Malgun Gothic"),
    (["Noto Sans CJK KR", "Noto Sans KR"], "Noto Sans KR"),
    (["NanumGothic", "Noto Sans CJK JP"], "Noto Sans CJK JP"),
    (["NanumGothic"], "NanumGothic"),
], ids=[
    "fallback", "windows", "cjk-kr-first", "applegothic-first", "apple-sd-before-malgun",
    "malgun-before-noto-kr", "noto-kr-before-cjk", "cjk-before-nanum", "nanum",
])
def test_font_family_priority(monkeypatch, installed, expected):
    fonts = [font_manager.FontEntry(name=name) for name in installed]
    monkeypatch.setattr(font_manager.fontManager, "ttflist", fonts)
    clear_cache = getattr(plots.font_family, "cache_clear", None)
    if clear_cache is not None:
        clear_cache()
    try:
        assert plots.font_family() == expected
    finally:
        if clear_cache is not None:
            clear_cache()


def test_missing_glyphs_returns_empty_for_supported_text():
    assert plots.missing_glyphs(["abc"], ["DejaVu Sans"]) == []


@pytest.mark.filterwarnings("ignore:Glyph .* missing from font")
def test_count_bar_reports_missing_glyphs_from_rendered_text(monkeypatch, tmp_path):
    monkeypatch.setattr(plots, "font_family", lambda: "DejaVu Sans")
    frame = pd.DataFrame({"group": ["동가동", "동가동", "숨"]})

    chart = plots.bar_counts(
        frame, "group", tmp_path / "counts.png", top=1,
        title="제목", category_label="범주", value_label="건수",
    )

    assert chart["missing_glyphs"] == sorted("가동제목범주건수")


@pytest.mark.filterwarnings("ignore:Glyph .* missing from font")
def test_count_bar_renders_when_font_lookup_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(plots, "font_family", lambda: "DejaVu Sans")

    def unavailable_font(*args, **kwargs):
        raise OSError("Font lookup unavailable")

    # Keep Matplotlib's own font lookups working while it draws the chart.
    lookup = SimpleNamespace(**vars(font_manager))
    lookup.findfont = unavailable_font
    monkeypatch.setattr(plots, "font_manager", lookup)
    frame = pd.DataFrame({"group": ["가동"]})
    output = tmp_path / "counts.png"

    chart = plots.bar_counts(frame, "group", output)

    assert output.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert chart["missing_glyphs"] == []


def test_plot_spec_example_renders_every_chart_type(tmp_path):
    references = SCRIPTS.parent / "references"
    filenames = ("plot_spec.example.json", "plot_example.csv")
    missing = [name for name in filenames if not (references / name).is_file()]
    assert not missing, f"Missing plot example files: {', '.join(missing)}"

    example_dir = tmp_path / "references"
    example_dir.mkdir()
    for name in filenames:
        shutil.copyfile(references / name, example_dir / name)

    spec_path = example_dir / "plot_spec.example.json"
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert (example_dir / spec["source"]["path"]).resolve() == example_dir / "plot_example.csv"
    assert isinstance(spec["charts"], list)
    assert {chart["type"] for chart in spec["charts"]} == set(plots.CHARTS)
    assert len(spec["charts"]) == len(plots.CHARTS), "Use each supported chart type once"

    outdir = tmp_path / "figures"
    result = subprocess.run(
        [sys.executable, "-I", "-B", SCRIPTS / "plots.py", "--spec", spec_path, "--outdir", outdir],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    pngs = list(outdir.glob("*.png"))
    assert len(pngs) == len(plots.CHARTS)
    for png in pngs:
        assert png.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"), f"Invalid PNG: {png.name}"


@pytest.mark.parametrize(("source_path", "allowed_inputs", "accepted"), [
    pytest.param("../outside.csv", (), False, id="outside-without-input"),
    pytest.param("../outside.csv", ("outside.csv",), True, id="outside-with-input"),
    pytest.param("../outside.csv", ("other.csv", "outside.csv"), True, id="repeatable-input"),
    pytest.param("../outside.csv", ("other.csv",), False, id="different-input"),
    pytest.param("inside.csv", (), True, id="inside"),
    pytest.param("linked.csv", (), False, id="symlink-outside"),
])
def test_plots_confines_source_to_spec_directory_or_explicit_input(
    tmp_path, source_path, allowed_inputs, accepted,
):
    spec_dir = tmp_path / "specs"
    spec_dir.mkdir()
    outside = tmp_path / "outside.csv"
    for path in (outside, tmp_path / "other.csv", spec_dir / "inside.csv"):
        path.write_text("label,value\na,1\nb,2\n", encoding="utf-8")
    if source_path == "linked.csv":
        (spec_dir / "linked.csv").symlink_to(outside)

    spec_path = spec_dir / "plot-spec.json"
    spec_path.write_text(json.dumps({
        "source": {"path": source_path},
        "charts": [{"id": "counts", "type": "histogram", "column": "value"}],
    }), encoding="utf-8")

    outdir = tmp_path / "figures"
    input_args = [arg for path in allowed_inputs for arg in ("--input", path)]
    result = subprocess.run(
        [sys.executable, "-I", "-B", SCRIPTS / "plots.py", "--spec", spec_path,
         "--outdir", outdir, *input_args],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    if accepted:
        assert result.returncode == 0, result.stderr
        chart, = json.loads(result.stdout)
        assert chart["n_used"] == 2
        assert (outdir / "counts.png").is_file()
    else:
        assert result.returncode == 1, result.stderr
        assert "source.path" in result.stderr and "--input" in result.stderr
        assert not (outdir / "counts.png").exists()


def test_plots_help_documents_chart_types_example_and_metadata():
    result = subprocess.run(
        [sys.executable, "-I", "-B", SCRIPTS / "plots.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert re.search(r"(?<!\S)--input(?=[\s,=]|$)", result.stdout)
    expected = {*plots.CHARTS, "plot_spec.example.json", "n_used", "n_excluded", "missing_glyphs"}
    missing = sorted(name for name in expected if not re.search(rf"\b{re.escape(name)}\b", result.stdout))
    assert not missing, f"Missing from plots.py --help: {', '.join(missing)}"
