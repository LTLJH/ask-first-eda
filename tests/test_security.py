import csv

import pytest

import eda_io
from conftest import ROOT


@pytest.mark.parametrize("value", [
    '=HYPERLINK("x")', "@SUM(1)", "+cmd", "-cmd|' /C calc'!A0", "\t=1", "\r=1",
])
def test_neutralize_formula_prefixes_risky_text(value):
    assert eda_io.neutralize_formula(value) == "'" + value


@pytest.mark.parametrize("value", [
    "-5", "+3.2", "-1e-3", "-0.5", "-007", -5, 3.2, None, "", "'=1", "plain text",
])
def test_neutralize_formula_preserves_other_values(value):
    assert eda_io.neutralize_formula(value) is value


def test_gallery_cleaned_csv_has_no_formula_cells():
    cleaned = ROOT / "docs/gallery/messy_production_report/cleaned_daily_report.csv"
    with cleaned.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.reader(stream)
        risky_cells = [
            (reader.line_num, column)
            for row in reader
            for column, value in enumerate(row, start=1)
            if eda_io.neutralize_formula(value) != value
        ]

    assert risky_cells == []
