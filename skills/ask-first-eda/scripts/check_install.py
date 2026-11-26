"""Check the EDA installation by building and validating a sample report."""

import argparse
from importlib import import_module
from importlib.metadata import version
import json
import os
from pathlib import Path
from platform import python_version
import re
from shutil import copyfile
import sys
from tempfile import TemporaryDirectory
import warnings


SCRIPTS = Path(__file__).resolve().parent
DEPENDENCIES = ("pandas", "matplotlib", "openpyxl", "pyarrow", "charset-normalizer")
GLYPH_WARNING = re.compile(r"Glyph (\d+) .* missing from font")


def run_smoke(work):
    """Write and validate a sample report in an existing scratch directory."""
    from build_report import build_report, validate_summary
    from inspect_data import inspect_data
    from plots import render_spec

    source = work / "sample.csv"
    copyfile(SCRIPTS.parent / "references" / "plot_example.csv", source)
    table, = inspect_data(source)["tables"]
    rows = table["n_rows"]
    delivery = work / "delivery"
    plot_spec = work / "plot-spec.json"
    # Korean labels exercise glyph coverage on the installed fonts.
    plot_spec.write_text(json.dumps({
        "source": {"path": source.name, "table_id": table["id"]},
        "charts": [{"id": "sample", "type": "grouped_boxplot", "group": "batch",
                    "value": "mass_kg", "title": "\uadf8\ub8f9\ubcc4 \uc9c8\ub7c9",
                    "y_label": "\uc9c8\ub7c9"}],
    }), encoding="utf-8")
    with warnings.catch_warnings(record=True) as emitted:
        warnings.filterwarnings("always", message=GLYPH_WARNING.pattern, category=UserWarning)
        chart, = render_spec(plot_spec, delivery / "figures")
    plot_results = work / "plot-results.json"
    plot_results.write_text(json.dumps([chart]), encoding="utf-8")
    missing = set(chart["missing_glyphs"])
    for warning in emitted:
        if match := GLYPH_WARNING.match(str(warning.message)):
            missing.add(chr(int(match[1])))
        else:
            warnings.showwarning(warning.message, warning.category, warning.filename, warning.lineno)

    spec = {
        "title": "EDA installation check",
        "language": "en",
        "headline": f"The sample has {rows} recorded observations.",
        "kpis": [],
        "key_charts": [chart["id"]],
        "insights": [],
        "data_overview": {"datasets": [{
            "id": "sample", "format": "csv", "read_ranges": [f"{source.name} lines 1–{rows + 1}"],
            "unread": [], "rows": rows, "columns": table["n_cols"],
        }]},
        "ambiguity_log": [],
        "charts": [{"id": chart["id"], "question": "How does mass vary by group?",
                    "observation": "The chart shows the distribution of the sample values.",
                    "domain_interpretation": "Each value is a recorded batch mass."}],
        "metrics": [],
        "assumptions_limitations": [],
        "reproducibility": {"filters": [], "exclusions": [], "transforms": [],
                            "sample_sizes": {chart["id"]: rows}, "source_locators": [], "code": ""},
    }
    html, sidecar = build_report(spec, delivery, base_dir=work, plot_results=plot_results, input_paths=(source,))
    page = html.read_text(encoding="utf-8")
    if not page.startswith("<!doctype html>") or 'src="data:image/png;base64,' not in page:
        raise ValueError("The generated HTML does not contain an embedded chart.")
    summary = json.loads(sidecar.read_text(encoding="utf-8"))
    validate_summary(summary)
    recorded, = summary["charts"]
    if rows <= 0 or (recorded["id"], recorded["n_used"], recorded["n_excluded"]) != (chart["id"], rows, 0):
        raise ValueError("The generated JSON does not account for every sample row.")
    return sorted(missing)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    print(f"Python {python_version()}")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(SCRIPTS))

    try:
        with TemporaryDirectory(prefix="eda-check-") as temporary:
            work = Path(temporary)
            os.environ["MPLCONFIGDIR"] = str(work / "matplotlib")
            from eda_io import missing_dependency

            for package in DEPENDENCIES:
                try:
                    import_module(package.replace("-", "_"))
                    installed = version(package)
                except ImportError as error:
                    missing_dependency(error.name or package, "the installation check")
                print(f"{package} {installed}")
            missing = run_smoke(work)
    except (KeyError, OSError, RuntimeError, TypeError, ValueError) as error:
        parser.exit(1, f"Installation check failed: {error}\n")

    if missing:
        codepoints = ", ".join(f"U+{ord(char):04X}" for char in missing)
        print(f"Korean glyphs: missing {codepoints}. Install a Korean-capable font for Korean chart labels.")
    else:
        print("Korean glyphs: all sample glyphs available.")
    print("inspect/plots/build_report OK")


if __name__ == "__main__":
    main()
