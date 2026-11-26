import ast
from concurrent.futures import ThreadPoolExecutor, wait
from copy import deepcopy
from dataclasses import dataclass, field
from hashlib import sha256
import importlib
import json
from html import unescape
from html.parser import HTMLParser
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import subprocess
import sys
from threading import Event

import pandas as pd
from PIL import Image
import pytest

from conftest import ROOT, SCRIPTS


EXAMPLE_SPEC = SCRIPTS.parent / "references" / "report_spec.example.json"
REPORT_FIELDS = ("headline", "kpis", "key_charts", "insights")


def legacy_example_spec():
    spec = json.loads(EXAMPLE_SPEC.read_text(encoding="utf-8"))
    spec.setdefault("summary", spec.get("headline"))
    for key in REPORT_FIELDS:
        spec.pop(key, None)
    return spec


def feature(name):
    try:
        return importlib.import_module(name)
    except ModuleNotFoundError as error:
        pytest.fail(str(error))


@dataclass
class Element:
    tag: str
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)

    def find(self, tag=None, *, class_name=None, **attrs):
        for child in self.children:
            if isinstance(child, str):
                continue
            if ((tag is None or child.tag == tag)
                    and (class_name is None or class_name in child.attrs.get("class", "").split())
                    and all(child.attrs.get(key) == value for key, value in attrs.items())):
                yield child
            yield from child.find(tag, class_name=class_name, **attrs)

    def text(self, *, collapsed=False):
        children = self.children
        if collapsed and self.tag == "details" and "open" not in self.attrs:
            children = [child for child in children
                        if isinstance(child, Element) and child.tag == "summary"]
        return " ".join(" ".join(
            child if isinstance(child, str) else child.text(collapsed=collapsed)
            for child in children
        ).split())


class Tags(HTMLParser):
    void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
            "meta", "param", "source", "track", "wbr"}

    def __init__(self, html):
        super().__init__()
        self.root = Element("document")
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        element = Element(tag, dict(attrs))
        self.stack[-1].children.append(element)
        if tag not in self.void:
            self.stack.append(element)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def one(element, tag=None, **attrs):
    matches = list(element.find(tag, **attrs))
    assert len(matches) == 1, f"Expected one {tag or 'element'} with {attrs}, found {len(matches)}"
    return matches[0]


def panels(document):
    return one(document, "section", id="summary-panel"), one(document, "section", id="details-panel")


def media_rules(css, query):
    return "\n".join(re.findall(rf"@media\s+{query}\s*\{{((?:[^{{}}]|\{{[^{{}}]*\}})*)\}}", css))


def css_declarations(css):
    for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        properties = {name.strip(): value.strip()
                      for name, value in re.findall(r"([^:;]+):([^;]+)", declarations)}
        for selector in selectors.split(","):
            yield re.sub(r"\s*([+~])\s*", r" \1 ", selector.strip()), properties


@pytest.fixture
def report_template():
    path = SCRIPTS.parent / "templates" / "report.html"
    return Tags(path.read_text(encoding="utf-8")).root


@pytest.fixture
def report_css(report_template):
    return re.sub(r"/\*.*?\*/", "", one(report_template, "style").text(), flags=re.S)


def test_report_template_supports_focus_motion_print_and_mobile(report_css):
    assert any(":focus-visible" in selector for selector, _ in css_declarations(report_css))
    assert media_rules(report_css, r"\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)").strip()
    assert media_rules(report_css, "print").strip()
    assert (
        media_rules(report_css, r"\(\s*max-width\s*:[^)]+\)").strip()
        or any("clamp(" in rules.get("font-size", "") for _, rules in css_declarations(report_css))
    )


def test_report_template_uses_tabular_numbers_for_kpis_and_tables(report_css):
    tabular_selectors = {selector for selector, rules in css_declarations(report_css)
                         if "tabular-nums" in rules.get("font-variant-numeric", "").split()}
    missing = {".metric-value", "table"} - tabular_selectors
    assert not missing, f"Missing tabular numerals for {sorted(missing)}"


def test_report_template_uses_compact_kpi_units(report_css):
    rules = dict(css_declarations(report_css))
    assert ".kpi-unit" in rules, "Missing typography for KPI units"
    value_size = rules[".metric-value"]["font-size"]
    unit_size = rules[".kpi-unit"]["font-size"]
    assert value_size.endswith("rem") and unit_size.endswith("rem")
    assert float(unit_size[:-3]) < float(value_size[:-3])
    assert rules[".kpi-unit"]["line-height"] == "normal"


def test_report_headings_use_the_system_sans_stack(report_css):
    for heading in ("h1", "h2"):
        for selector, rules in css_declarations(report_css):
            if selector == heading:
                font = " ".join(rules.get(name, "") for name in ("font", "font-family"))
                assert not re.search(r"(?<![\w-])(?:ui-)?serif\b", font, re.I), font


def test_report_template_is_self_contained_and_uses_system_fonts(report_template, report_css):
    assert not re.search(r"@import\b|https?:", report_css, re.I)
    for url in re.findall(r"\burl\s*\(([^)]*)\)", report_css, re.I):
        assert url.strip().strip("\"'").startswith(("data:", "#")), f"External CSS resource: {url}"
    for node in report_template.find():
        for attr in {"href", "src", "srcset", "poster"} & node.attrs.keys():
            assert node.attrs[attr].strip().startswith(("data:", "#")), f"External {node.tag} {attr}"
    families = next((rules["font-family"] for selector, rules in css_declarations(report_css)
                     if selector == ":root" and "font-family" in rules), "")
    assert re.search(r"\bsystem-ui\b.*?,.*?\bsans-serif\b", families, re.I)


def relative_luminance(color):
    channels = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
              for channel in channels]
    return sum(channel * weight for channel, weight in zip(linear, (0.2126, 0.7152, 0.0722)))


@pytest.mark.parametrize("theme", ["light", "dark"])
def test_report_template_text_tokens_meet_aa_contrast(report_css, theme):
    if theme == "dark":
        css = media_rules(report_css, r"\(\s*prefers-color-scheme\s*:\s*dark\s*\)")
    else:
        css = re.sub(r"@media[^{}]*\{(?:[^{}]|\{[^{}]*\})*\}", "", report_css)
    tokens = dict(css_declarations(css)).get(":root", {})
    for name in ("--paper", "--ink", "--muted", "--accent"):
        assert re.fullmatch(r"#[0-9a-f]{6}", tokens.get(name, ""), re.I), f"Missing {theme} hex token {name}"
    paper = relative_luminance(tokens["--paper"])
    for name in ("--ink", "--muted", "--accent"):
        low, high = sorted((paper, relative_luminance(tokens[name])))
        contrast = (high + 0.05) / (low + 0.05)
        assert contrast >= 4.5, f"{theme} {name} on --paper has {contrast:.2f}:1 contrast"


def test_report_is_offline_escaped_and_has_conditional_metrics(tmp_path):
    plots = feature("plots")
    report = feature("build_report")
    png = tmp_path / "hist.png"
    metadata = plots.histogram(pd.DataFrame({"value": [1, 2, None]}), "value", png)
    assert (metadata["n_used"], metadata["n_excluded"]) == (2, 1)
    spec = legacy_example_spec()
    injection = '<script>alert(1)</script><img src="https://example.invalid/x">'
    spec["title"] = "한국어 " + injection
    spec["language"] = "ko"
    spec["charts"][0].update(metadata, image_path=str(png), observation=injection)
    spec["ambiguity_log"][0]["status"] = "unresolved"
    spec["metrics"][0]["condition"] = "All rows"
    spec["metrics"][1]["condition"] = "Open rows only"
    spec["summary"] = "Both estimates are conditional on the selected rows."
    output, sidecar = report.build_report(spec, tmp_path / "out")
    html = output.read_text(encoding="utf-8")
    assert '<img src="data:image/png;base64,' in html
    assert injection not in html
    assert injection in unescape(html)
    assert "&lt;script&gt;" in html
    assert "한국어" in html and "조건부 · A01" in html
    document = Tags(html).root
    tags = list(document.find())
    assert all(node.tag not in {"script", "link", "iframe"} for node in tags)
    assert all(not attrs[key].startswith(("http:", "https:", "//"))
               for attrs in (node.attrs for node in tags)
               for key in {"href", "src", "srcset"} & attrs.keys())
    summary = json.loads(sidecar.read_text(encoding="utf-8"))
    report.validate_summary(summary)
    assert summary["datasets"] == spec["data_overview"]["datasets"]
    assert summary["metrics"] == spec["metrics"]
    broken = deepcopy(summary)
    broken["datasets"][0]["rows"] = True
    with pytest.raises(ValueError, match="rows"):
        report.validate_summary(broken)
    broken = deepcopy(spec)
    broken["metrics"][0]["condition"] = None
    with pytest.raises(ValueError, match="condition"):
        report.build_report(broken, tmp_path / "invalid")
    broken["metrics"][0]["depends_on_ambiguity_ids"] = ["unknown"]
    with pytest.raises(ValueError, match="unknown ambiguity"):
        report.build_report(broken, tmp_path / "invalid")

    _, details = panels(document)
    assert "분자" in details.text()
    assert any(label in details.text() for label in ("근거 위치", "출처"))
    assert any("A01" in row.text() and "미해결" in row.text() for row in details.find("tr"))
    for metric in spec["metrics"]:
        assert any(metric["name"] in row.text() and metric["condition"] in row.text()
                   for row in details.find("tr"))


@pytest.fixture
def report_spec(tmp_path):
    spec = legacy_example_spec()
    spec["metrics"] = spec["metrics"][:2]
    chart = spec["charts"][0]
    chart.update(
        hypothesis="Interval duration may explain the spread in all records.",
        next_check="Compare the duration of every recorded interval.",
    )
    spec["charts"] = [chart]
    for name in ("Eligible rows", "Closed rows", "Intervals measured"):
        spec["metrics"].append({
            "name": name, "definition": f"Count of {name.lower()}.",
            "numerator": None, "denominator": None, "value": 1, "unit": "rows",
            "depends_on_ambiguity_ids": [], "condition": None, "source_refs": ["counts.csv line 2"],
        })
    for name in ("open-shifts", "closed-shifts"):
        spec["charts"].append({
            **chart, "id": name, "question": f"How many {name} were measured?",
            "observation": f"The chart uses the records for {name}.",
            "domain_interpretation": f"The counts describe activity during {name}.",
            "hypothesis": f"Interval duration may explain the spread for {name}.",
            "next_check": f"Compare interval durations for {name}.",
        })
    Image.new("RGB", (2, 2), "white").save(tmp_path / chart["image_path"])
    spec.update(
        language="en",
        summary="Previous summary should not be displayed.",
        headline="Total volume was 18 units across three intervals.",
        kpis=[spec["metrics"][1]["name"]],
        key_charts=[spec["charts"][1]["id"]],
        insights=[{"text": "The two open intervals contributed 15 units.", "source": "counts.csv line 3"}],
    )
    return spec


def build_page(spec, tmp_path):
    out = tmp_path / "delivery"
    feature("build_report").build_report(spec, out, base_dir=tmp_path)
    return Tags((out / "report.html").read_text(encoding="utf-8")).root


@pytest.mark.parametrize(("unit", "display"), [
    ("kg", "inline"),
    ("%", "inline"),
    ("units / hour", "inline"),
    ("items per day", "block"),
    ("items counted per scheduled day", "block"),
])
def test_report_lays_out_kpi_unit_by_length(tmp_path, report_spec, report_css, unit, display):
    metric = report_spec["metrics"][2]
    metric.update(value=42, unit=unit)
    report_spec["kpis"] = [metric["name"]]

    summary, _ = panels(build_page(report_spec, tmp_path))
    tile = one(summary, class_name="kpi")
    value_node = one(tile, class_name="kpi-value")
    unit_node = one(tile, class_name="kpi-unit")
    assert value_node.text() == "42"
    assert unit_node.text() == unit
    assert value_node.tag == unit_node.tag == "span"
    classes = unit_node.attrs["class"].split()
    unit_display = "inline"
    for selector, rules in css_declarations(report_css):
        if selector.startswith(".") and all(name in classes for name in selector[1:].split(".")):
            unit_display = rules.get("display", unit_display)
    assert unit_display == display


def test_report_puts_summary_and_evidence_in_separate_panels(tmp_path, report_spec):
    spec = report_spec
    metric = spec["metrics"][1]
    metric.update(numerator=15, denominator=1, source_refs=["metric-proof.csv line 17"])
    ambiguity = spec["ambiguity_log"][0]
    ambiguity["question"] = "Which intervals belong to the agreed scope?"
    document = build_page(spec, tmp_path)
    summary, details = panels(document)

    assert one(document, "h1").text() == spec["title"]
    assert not list(summary.find("table"))
    assert not list(summary.find("pre"))
    assert not list(summary.find(class_name="needs-confirmation"))
    assert spec["headline"] in summary.text()
    assert spec["summary"] not in summary.text()
    kpi = one(summary, class_name="kpi")
    for value in (metric["name"], metric["definition"], "15", metric["unit"]):
        assert value in kpi.text()
    assert spec["metrics"][0]["name"] not in summary.text()
    key_chart = one(summary, "figure", class_name="key-chart")
    chart = spec["charts"][1]
    assert one(key_chart, "img").attrs["src"].startswith("data:image/png;base64,")
    assert len(list(summary.find("img"))) == 1
    assert chart["domain_interpretation"] in key_chart.text()
    insight = one(summary, "li", class_name="insight")
    for value in spec["insights"][0].values():
        assert value in insight.text()

    metric_table = one(one(details, "section", id="details-metrics"), "table")
    for item in spec["metrics"]:
        assert item["name"] in metric_table.text()
    row = next(row for row in metric_table.find("tr") if metric["name"] in row.text())
    for value in (metric["definition"], "15", "1", metric["source_refs"][0]):
        assert value in row.text()
    charts = one(details, "section", id="details-charts")
    assert len(list(charts.find("img"))) == len(spec["charts"])
    for chart_index, chart in enumerate(spec["charts"]):
        for key in ("question", "observation", "domain_interpretation", "hypothesis", "next_check"):
            assert chart[key] in charts.text()
        assert chart["observation"] not in summary.text()
        if chart_index != 1:
            assert chart["domain_interpretation"] not in summary.text()

    ambiguity_table = one(one(details, "section", id="details-ambiguity"), "table")
    row = next(row for row in ambiguity_table.find("tr") if ambiguity["id"] in row.text())
    cells = [cell.text(collapsed=True).casefold() for cell in row.children
             if isinstance(cell, Element) and cell.tag in ("td", "th")]
    for key in ("id", "checklist_item", "status", "answer"):
        assert any(ambiguity[key].casefold() in cell for cell in cells)
    evidence = one(row, "details")
    assert "open" not in evidence.attrs
    for value in [ambiguity["question"], *ambiguity["file_evidence"], *ambiguity["candidates"]]:
        assert value in evidence.text()
        assert value not in row.text(collapsed=True)
    overview = spec["data_overview"]["row_grain"]
    limitation, = spec["assumptions_limitations"]
    assert overview in one(details, "section", id="details-overview").text()
    assert limitation in one(details, "section", id="details-limitations").text()
    reproduction = one(details, "section", id="details-reproducibility")
    code = one(reproduction, "code")
    assert "histogram(frame" in code.text()
    assert not list(reproduction.find("details"))
    for item in spec["reproducibility"]["filters"]:
        assert item in reproduction.text()
    for value in (overview, limitation, ambiguity["answer"], metric["source_refs"][0]):
        assert value not in summary.text()


def test_report_defaults_to_summary_with_labeled_css_radio_tabs(tmp_path, report_spec):
    document = build_page(report_spec, tmp_path)
    tabs = list(document.find("input", type="radio", name="tab"))
    assert len(tabs) == 2
    labels = []
    for tab in tabs:
        assert "hidden" not in tab.attrs and "disabled" not in tab.attrs
        assert int(tab.attrs.get("tabindex", "0")) >= 0
        label = next((label for label in document.find("label")
                      if (tab.attrs.get("id") and label.attrs.get("for") == tab.attrs["id"])
                      or any(node is tab for node in label.find("input"))), None)
        assert label is not None
        labels.append(label.text().casefold())
    assert len({label for label in labels}) == 2
    checked, = [label for label, tab in zip(labels, tabs) if "checked" in tab.attrs]
    assert "summary" in checked
    assert any("details" in label for label in labels if label != checked)
    assert ":checked" in "".join(style.text() for style in document.find("style"))


def test_report_prints_both_panels(tmp_path, report_spec):
    document = build_page(report_spec, tmp_path)
    css = "\n".join(style.text() for style in document.find("style"))
    print_css = media_rules(css, "print")
    assert print_css, "Report must have print CSS"
    display_selectors = [
        selector.strip()
        for selectors, declarations in re.findall(r"([^{}]+)\{([^{}]*)\}", print_css)
        if re.search(r"(?:^|;)\s*display\s*:\s*(?!none\b)[\w-]+", declarations)
        for selector in selectors.split(",")
    ]
    for panel in panels(document):
        identifier = panel.attrs["id"]
        targets = {f"#{identifier}", "section", "*"}
        targets.update(f".{name}" for name in panel.attrs.get("class", "").split())
        compounds = (re.split(r"[\s>+~]+", selector)[-1] for selector in display_selectors)
        matched = (set(re.findall(r"[#.][\w-]+|^[\w-]+|^\*", compound)) for compound in compounds)
        assert any(parts and parts <= targets for parts in matched), f"No print display rule for {identifier}"


def test_report_orders_details_sections_and_opens_only_charts(tmp_path, report_spec):
    _, details = panels(build_page(report_spec, tmp_path))
    sections = [child for child in details.children
                if isinstance(child, Element) and child.tag == "section"]
    assert [section.attrs.get("id") for section in sections] == [
        "details-charts", "details-limitations", "details-ambiguity",
        "details-overview", "details-metrics", "details-reproducibility",
    ]
    for section, title in zip(sections, [
        "Charts", "Assumptions & limitations", "Ambiguity log", "Data overview",
        "Metrics", "Reproducibility",
    ], strict=True):
        toggle = one(section, "input", class_name="section-toggle", type="checkbox")
        body = one(section, class_name="section-body")
        heading = one(section, class_name="section-heading")
        label = one(heading, "label", **{"for": toggle.attrs["id"]})
        assert [child for child in section.children if isinstance(child, Element)] == [
            toggle, heading, body,
        ]
        assert one(heading, "h2").text() == label.text() == title
        assert ("checked" in toggle.attrs) == (section.attrs["id"] == "details-charts")
        assert toggle.attrs["aria-controls"] == body.attrs["id"]


def test_report_switches_section_body_visibility_and_expands_for_print(tmp_path, report_spec):
    document = build_page(report_spec, tmp_path)
    css = one(document, "style").text()
    print_css = media_rules(css, "print")
    screen_rules = dict(css_declarations(re.split(r"@media\s+print\b", css, maxsplit=1)[0]))
    print_rules = dict(css_declarations(print_css))

    collapsed = ".section-toggle:not(:checked) ~ .section-body"
    expanded = ".section-toggle:checked ~ .section-body"
    assert screen_rules.get(collapsed, {}).get("display") == "none"
    assert screen_rules.get(expanded, {}).get("display") == "block"
    assert print_rules.get(collapsed, {}).get("display") == "block"


def test_report_zooms_each_key_chart_without_repeating_the_image(tmp_path, report_spec):
    for index, chart in enumerate(report_spec["charts"]):
        chart["image_path"] = f"chart-{index}.png"
        Image.new("RGB", (2, 2), (index, 0, 0)).save(tmp_path / chart["image_path"])
    report_spec["key_charts"] = [chart["id"] for chart in report_spec["charts"][:2]]

    document = build_page(report_spec, tmp_path)
    summary, details = panels(document)
    html = (tmp_path / "delivery" / "report.html").read_text(encoding="utf-8")
    figures = list(summary.find("figure", class_name="key-chart"))
    assert len(figures) == 2
    ids = set()
    for figure in figures:
        toggle = one(figure, "input", class_name="zoom-toggle", type="checkbox")
        assert "checked" not in toggle.attrs
        identifier = toggle.attrs["id"]
        assert identifier and identifier not in ids
        ids.add(identifier)
        label = one(figure, "label", **{"for": identifier})
        children = [child for child in figure.children if isinstance(child, Element)]
        assert children[:2] == [toggle, label]
        image = one(label, "img")
        uri = image.attrs["src"]
        assert uri.startswith("data:image/png;base64,")
        assert len(list(details.find("img", src=uri))) == 1
        assert html.count(f'"{uri}"') == 2


@pytest.mark.parametrize(("language", "close_text"), [("ko", "닫기"), ("en", "Close")])
def test_report_shows_localized_close_hint_when_zoomed(tmp_path, report_spec, language, close_text):
    report_spec["language"] = language
    document = build_page(report_spec, tmp_path)
    summary, _ = panels(document)
    toggle = one(summary, "input", class_name="zoom-toggle")
    label = one(summary, "label", **{"for": toggle.attrs["id"]})
    assert close_text in label.text()
    assert close_text.casefold() in toggle.attrs["aria-label"].casefold()

    hint = one(label, "span")
    hint_selector = f'.{hint.attrs["class"]}'
    rules = dict(css_declarations(one(document, "style").text()))
    assert rules[hint_selector]["display"] == "none"
    screen_css = media_rules(one(document, "style").text(), "screen")
    assert any(selector.startswith(".zoom-toggle:checked + label")
               and selector.endswith(f" {hint_selector}")
               and properties.get("display") not in (None, "none")
               for selector, properties in css_declarations(screen_css))


def test_report_positions_the_checked_zoom_image_in_an_overlay(tmp_path, report_spec):
    css = one(build_page(report_spec, tmp_path), "style").text()
    screen_rules = css_declarations(re.split(r"@media\s+print\b", css, maxsplit=1)[0])
    assert any(selector.startswith(".zoom-toggle:checked + label") and selector.endswith(" img")
               and properties.get("position") == "fixed"
               for selector, properties in screen_rules)


def test_report_keeps_checkbox_controls_keyboard_accessible(tmp_path, report_spec):
    document = build_page(report_spec, tmp_path)
    css = one(document, "style").text()
    screen_css = re.split(r"@media\s+print\b", css, maxsplit=1)[0]
    screen_rules = list(css_declarations(screen_css))
    for name in ("section-toggle", "zoom-toggle"):
        toggles = list(document.find("input", class_name=name, type="checkbox"))
        assert toggles
        for toggle in toggles:
            assert "hidden" not in toggle.attrs and "disabled" not in toggle.attrs
            assert int(toggle.attrs.get("tabindex", "0")) >= 0
        assert any(selector == f".{name}" and properties.get("clip-path") == "inset(50%)"
                   for selector, properties in screen_rules)
        assert not any(selector.startswith(f".{name}") and properties.get("display") == "none"
                       and not selector.endswith(".section-body")
                       for selector, properties in screen_rules)
        assert any(selector.startswith(f".{name}:focus-visible") and "label" in selector
                   and properties.get("outline")
                   for selector, properties in screen_rules)
    motion_rules = css_declarations(media_rules(css, r"\(prefers-reduced-motion\s*:\s*reduce\)"))
    assert any(properties.get("transition") == "none" for _, properties in motion_rules)


def test_report_keeps_the_offline_csp(tmp_path, report_spec):
    document = build_page(report_spec, tmp_path)
    csp = one(document, "meta", **{"http-equiv": "Content-Security-Policy"})
    assert {part.strip() for part in csp.attrs["content"].split(";") if part.strip()} == {
        "default-src 'none'", "img-src data:", "style-src 'unsafe-inline'",
        "base-uri 'none'", "form-action 'none'",
    }
    assert not list(document.find("script"))
    assert "<script" not in (tmp_path / "delivery" / "report.html").read_text(encoding="utf-8").lower()


def test_report_omits_empty_fields_but_keeps_zero_false_and_authored_values(tmp_path, report_spec):
    spec = report_spec
    zero = spec["metrics"][1]
    zero.update(numerator=0, denominator=1, value=0)
    missing_rate = spec["metrics"][-1]
    missing_rate.update(
        unit="%", numerator=0, denominator=0, value=None,
        definition="Rate unavailable because the denominator is zero.",
    )
    spec["kpis"].append(missing_rate["name"])
    spec["data_overview"].update(
        NULL_FIELD=None, EMPTY_TEXT="", EMPTY_LIST=[], Observed=False, Notation="—",
    )
    summary, details = panels(build_page(spec, tmp_path))
    tiles = list(summary.find(class_name="kpi"))
    zero_tile = next(tile for tile in tiles if zero["name"] in tile.text())
    assert re.search(r"\b0\b", zero_tile.text())
    assert re.search(r"\bObserved[\s:]+false\b", details.text(), re.I)
    assert re.search(r"\bNotation[\s:]+—", details.text())
    assert details.text().count("—") == 1
    assert "—" not in summary.text()
    for label in ("NULL_FIELD", "EMPTY_TEXT", "EMPTY_LIST"):
        assert label not in details.text()
    assert missing_rate["definition"] in details.text()


@pytest.mark.parametrize(("count", "language", "overflow"), [
    (6, "en", None), (8, "en", r"\+\s*2\s+more\b"), (8, "ko", r"외\s*2\s*개"),
], ids=["six-sources", "english-overflow", "korean-overflow"])
def test_report_folds_only_source_lists_longer_than_six(
    tmp_path, report_spec, count, language, overflow,
):
    report_spec["language"] = language
    metric = report_spec["metrics"][0]
    refs = [f"source-{index:02}.csv line 10" for index in range(count)]
    metric["source_refs"] = refs
    _, details = panels(build_page(report_spec, tmp_path))
    metrics = one(details, "section", id="details-metrics")
    row = next(row for row in metrics.find("tr") if metric["name"] in row.text())
    preview = row.text(collapsed=True)
    positions = [preview.index(ref) for ref in refs[:6]]
    assert positions == sorted(positions)
    complete_lists = [section for section in row.find("details")
                      if all(ref in section.text() for ref in refs)]
    if overflow is None:
        assert not complete_lists
        assert not re.search(r"(?:\+\s*\d+\s+more|외\s*\d+\s*개)", preview, re.I)
    else:
        fold, = complete_lists
        assert "open" not in fold.attrs
        assert all(ref not in preview for ref in refs[6:])
        assert re.search(overflow, preview, re.I)


def test_report_groups_all_alternative_kpis_for_an_unresolved_condition(tmp_path, report_spec):
    spec = report_spec
    alternative_a, alternative_b = spec["metrics"][:2]
    spec["kpis"] = [alternative_a["name"], spec["metrics"][2]["name"]]
    unrelated = spec["metrics"][2]
    alternative_a["condition"] = "When closed intervals count"
    alternative_b["condition"] = "When only open intervals count"
    ambiguity = spec["ambiguity_log"][0]
    ambiguity.update(status="unresolved", answer=None, question="Do closed intervals count?")
    summary, _ = panels(build_page(spec, tmp_path))
    group = one(summary, class_name="kpi-group")
    assert ambiguity["id"] in group.text()
    for metric in (alternative_a, alternative_b):
        for value in (metric["name"], metric["condition"], str(metric["value"])):
            assert value in group.text()
        assert summary.text().count(metric["name"]) == 1
    assert unrelated["name"] in summary.text()
    assert unrelated["name"] not in group.text()
    assert ambiguity["question"] in one(summary, class_name="needs-confirmation").text()


def test_report_accepts_absent_or_empty_optional_chart_fields(tmp_path, report_spec):
    chart = report_spec["charts"][0]
    del chart["hypothesis"], chart["next_check"]
    report_spec["charts"][1].update(hypothesis=None, next_check="")
    report_spec["charts"][2].update(hypothesis="Check the grouping assumption.", next_check="Review tomorrow's counts.")
    _, details = panels(build_page(report_spec, tmp_path))
    assert details.text().casefold().count("hypothesis") == 1
    assert details.text().casefold().count("next check") == 1
    for chart in report_spec["charts"]:
        assert chart["observation"] in details.text()
        assert chart["domain_interpretation"] in details.text()
    assert report_spec["charts"][2]["hypothesis"] in details.text()
    assert report_spec["charts"][2]["next_check"] in details.text()


def test_report_keeps_the_sidecar_contract_for_the_new_spec(tmp_path, report_spec):
    build_page(report_spec, tmp_path)
    sidecar = json.loads((tmp_path / "delivery" / "eda_summary.json").read_text(encoding="utf-8"))
    feature("build_report").validate_summary(sidecar)
    assert sidecar == {
        "datasets": report_spec["data_overview"]["datasets"],
        "row_counts": report_spec["reproducibility"]["transforms"],
        "metrics": report_spec["metrics"],
        "ambiguity_log": report_spec["ambiguity_log"],
        "charts": [
            {key: chart[key] for key in ("id", "question", "type", "source_columns",
                                         "n_used", "n_excluded", "exclusion_reason") if key in chart}
            for chart in report_spec["charts"]
        ],
        "exclusions": report_spec["reproducibility"]["exclusions"],
    }


@pytest.mark.parametrize(("field", "kind", "actual", "limit"), [
    pytest.param("headline", "length", 301, 300, id="headline-too-long"),
    pytest.param("insights", "count", 4, 3, id="too-many-insights"),
    pytest.param("insights", "length", 201, 200, id="insight-text-too-long"),
    pytest.param("kpis", "count", 5, 4, id="too-many-kpis"),
    pytest.param("key_charts", "count", 3, 2, id="too-many-key-charts"),
])
def test_report_gate_rejects_limits_before_writing(tmp_path, report_spec, field, kind, actual, limit):
    spec = report_spec
    if field == "headline":
        spec[field] = "가" * (actual - 1) + "."
    elif field == "insights" and kind == "length":
        spec[field][0]["text"] = "가" * (actual - 1) + "."
    elif field == "insights":
        spec[field] = [{"text": f"Finding number {index}.", "source": "counts.csv line 3"}
                       for index in range(actual)]
    else:
        collection, key = ("metrics", "name") if field == "kpis" else ("charts", "id")
        spec[field] = [entry[key] for entry in spec[collection][:actual]]

    out = tmp_path / "delivery"
    with pytest.raises(ValueError, match=field) as error:
        feature("build_report").build_report(spec, out, base_dir=tmp_path)
    numbers = {int(number) for number in re.findall(r"(?<!\[)\b\d+\b", str(error.value))}
    assert {actual, limit} <= numbers or actual - limit in numbers, str(error.value)
    assert not (out / "report.html").exists()
    assert not (out / "eda_summary.json").exists()


@pytest.mark.parametrize("case", [
    "missing-source", "empty-source", "null-source", "unknown-kpi", "duplicate-kpi",
    "unknown-key-chart", "duplicate-key-chart", "duplicate-metric-name",
])
def test_report_gate_rejects_invalid_references_before_writing(tmp_path, report_spec, case):
    spec = report_spec
    if case == "missing-source":
        del spec["insights"][0]["source"]
        field = "source"
    elif case in ("empty-source", "null-source"):
        spec["insights"][0]["source"] = "" if case == "empty-source" else None
        field = "source"
    elif case == "duplicate-metric-name":
        spec["metrics"][1]["name"] = spec["metrics"][0]["name"]
        spec["kpis"] = [spec["metrics"][0]["name"]]
        field = r"(?i)metric.*name|name.*metric"
    else:
        field = "kpis" if case.endswith("-kpi") else "key_charts"
        spec[field].append(spec[field][0] if case.startswith("duplicate") else "Missing reference")

    out = tmp_path / "delivery"
    with pytest.raises(ValueError, match=field):
        feature("build_report").build_report(spec, out, base_dir=tmp_path)
    assert not (out / "report.html").exists()
    assert not (out / "eda_summary.json").exists()


@pytest.mark.parametrize("location", ["parent-traversal", "absolute", "symlink", "inside"])
def test_report_confines_images_to_spec_directory(tmp_path, report_spec, location):
    spec_dir = tmp_path / "work" / "specs"
    spec_dir.mkdir(parents=True)
    chart = report_spec["charts"][1]
    png = tmp_path / chart["image_path"]
    inside = spec_dir / "chart.png"
    inside.write_bytes(png.read_bytes())
    for entry in report_spec["charts"]:
        entry["image_path"] = inside.name

    outside = tmp_path / "secret.png"
    outside.write_bytes(png.read_bytes())
    link = spec_dir / "linked.png"
    if location == "symlink":
        link.symlink_to(outside)
    chart["image_path"] = {
        "parent-traversal": "../../secret.png",
        "absolute": str(outside),
        "symlink": link.name,
        "inside": inside.name,
    }[location]

    out = tmp_path / "delivery"
    build = feature("build_report").build_report
    if location == "inside":
        build(report_spec, out, base_dir=spec_dir)
        assert (out / "report.html").is_file()
        assert (out / "eda_summary.json").is_file()
    else:
        with pytest.raises(ValueError, match=rf"{re.escape(chart['id'])}.*image_path"):
            build(report_spec, out, base_dir=spec_dir)
        assert not (out / "report.html").exists()
        assert not (out / "eda_summary.json").exists()


def test_report_accepts_limits_and_does_not_require_legacy_summary(tmp_path, report_spec):
    spec = report_spec
    del spec["summary"]
    spec.update(
        headline="가" * 299 + ".",
        kpis=[metric["name"] for metric in spec["metrics"][:4]],
        key_charts=[chart["id"] for chart in spec["charts"][:2]],
        insights=[{"text": letter * 199 + ".", "source": "counts.csv line 3"} for letter in "나다라"],
    )
    summary, _ = panels(build_page(spec, tmp_path))
    assert spec["headline"] in summary.text()
    assert len(list(summary.find(class_name="kpi"))) == 4
    assert len(list(summary.find("figure", class_name="key-chart"))) == 2
    assert len(list(summary.find("li", class_name="insight"))) == 3


def test_report_honors_empty_summary_selections(tmp_path, report_spec):
    report_spec.update(kpis=[], key_charts=[], insights=[])
    summary, details = panels(build_page(report_spec, tmp_path))
    for class_name in ("kpi", "key-chart", "insight"):
        assert not list(summary.find(class_name=class_name))
    assert len(list(details.find("img"))) == len(report_spec["charts"])


def run_build_cli(spec, tmp_path, *options):
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-I", "-B", SCRIPTS / "build_report.py",
         "--spec", spec_path, "--outdir", tmp_path / "delivery", *options],
        capture_output=True,
        text=True,
    )


def build_cli(spec, tmp_path):
    result = run_build_cli(spec, tmp_path)
    assert result.returncode == 0, result.stderr
    for filename in ("report.html", "eda_summary.json"):
        assert (tmp_path / "delivery" / filename).is_file()
    return result


def result_warnings(result):
    if isinstance(result, dict):
        return result.get("warnings")
    if isinstance(result, tuple):
        for entry in result:
            if isinstance(entry, dict) and "warnings" in entry:
                return entry["warnings"]
            if isinstance(entry, list):
                return entry
    return getattr(result, "warnings", None)


def build_with_warnings(spec, tmp_path):
    cli = build_cli(spec, tmp_path)
    assert cli.stderr.strip(), "A warning must be written to stderr"
    try:
        warnings = result_warnings(json.loads(cli.stdout))
    except json.JSONDecodeError:
        warnings = None
    if warnings is None:
        result = feature("build_report").build_report(spec, tmp_path / "api", base_dir=tmp_path)
        warnings = result_warnings(result)
    assert isinstance(warnings, list) and warnings, "Build result must record a warnings list"
    return warnings, cli.stderr


def set_authored_text(spec, field, text):
    if field == "headline":
        spec[field] = text
    elif field == "insights":
        spec[field][0]["text"] = text
    else:
        spec["charts"][-1]["domain_interpretation"] = text


@pytest.mark.parametrize(("phrase", "field"), [
    ("이 보고서는", "headline"),
    ("본 보고서", "insights"),
    ("살펴보겠", "chart"),
    ("In this report", "headline"),
    ("This report", "chart"),
])
def test_report_flags_each_banned_phrase(tmp_path, report_spec, phrase, field):
    set_authored_text(report_spec, field, f"{phrase} the interval counts.")
    build_with_warnings(report_spec, tmp_path)


@pytest.mark.parametrize(("first", "second"), [
    ("headline", "insights"), ("headline", "chart"), ("insights", "chart"),
])
def test_report_flags_a_repeated_authored_sentence(tmp_path, report_spec, first, second):
    duplicate = "Open intervals account for 15 units."
    set_authored_text(report_spec, first, duplicate)
    set_authored_text(report_spec, second, f"{duplicate} Three intervals were recorded.")
    build_with_warnings(report_spec, tmp_path)


def test_report_excludes_confirmation_and_detailed_evidence_from_repeat_checks(tmp_path, report_spec):
    spec = report_spec
    ambiguity = spec["ambiguity_log"][0]
    ambiguity.update(
        status="unresolved", answer=None, question=spec["headline"], file_evidence=[spec["headline"]],
    )
    for metric in spec["metrics"][:2]:
        metric["condition"] = spec["headline"]
    spec["charts"][0]["observation"] = spec["headline"]
    result = build_cli(spec, tmp_path)
    assert not result.stderr.strip()


@pytest.mark.parametrize("legacy_summary", [
    "Legacy conclusion for the supplied intervals.",
    ["Legacy first sentence.", "Legacy second sentence."],
], ids=["string", "list"])
def test_legacy_report_builds_with_defaults_and_a_warning(tmp_path, report_spec, legacy_summary):
    spec = report_spec
    for key in REPORT_FIELDS:
        del spec[key]
    spec["summary"] = legacy_summary
    warnings, stderr = build_with_warnings(spec, tmp_path)
    assert "legacy" in stderr.casefold()
    assert any("legacy" in str(warning).casefold() for warning in warnings)

    html = (tmp_path / "delivery" / "report.html").read_text(encoding="utf-8")
    summary, details = panels(Tags(html).root)
    headline = " ".join(legacy_summary) if isinstance(legacy_summary, list) else legacy_summary
    assert headline in summary.text()
    tiles = list(summary.find(class_name="kpi"))
    assert len(tiles) == 4
    for tile, metric in zip(tiles, spec["metrics"][:4], strict=True):
        assert metric["name"] in tile.text()
    assert spec["metrics"][-1]["name"] not in summary.text()
    figures = list(summary.find("figure", class_name="key-chart"))
    assert len(figures) == 2
    for figure, chart in zip(figures, spec["charts"][:2], strict=True):
        assert chart["domain_interpretation"] in figure.text()
    assert not list(summary.find("li", class_name="insight"))
    assert spec["charts"][-1]["domain_interpretation"] in details.text()


def test_chart_cli_renders_all_types(tmp_path, inputs):
    spec = {"source": {"path": str(inputs["plain.csv"])}, "charts": [
        {"id": "a", "type": "histogram", "column": "value"},
        {"id": "b", "type": "boxplot", "column": "value"},
        {"id": "c", "type": "bar_counts", "column": "name",
         "category_label": "Response", "value_label": "Records"},
        {"id": "d", "type": "scatter", "x": "value", "y": "value"},
        {"id": "e", "type": "corr_heatmap", "columns": ["value", "name"]},
        {"id": "f", "type": "grouped_boxplot", "group": "name", "value": "value"},
        {"id": "g", "type": "line_time", "time": "name", "value": "value"},
    ]}
    spec_path = tmp_path / "charts.json"
    spec_path.write_text(json.dumps(spec), encoding="utf-8")
    output = tmp_path / "charts"
    result = subprocess.run([sys.executable, "-I", "-B", str(SCRIPTS / "plots.py"), "--spec",
                             str(spec_path), "--outdir", str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    metadata = json.loads(result.stdout)
    assert len(metadata) == 7
    assert metadata[4]["pairwise_n"] == {"value": {"value": 2, "name": 0},
                                        "name": {"value": 0, "name": 0}}
    assert metadata[4]["n_used"] == 2
    assert metadata[4]["read_extent"]["rows_read"] == 2
    assert metadata[6]["n_used"] == 0
    for chart in metadata:
        assert (output / f"{chart['id']}.png").read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_build_report_help_documents_example_and_required_fields():
    result = subprocess.run(
        [sys.executable, "-I", "-B", SCRIPTS / "build_report.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    expected = (
        "report_spec.example.json", "title", "language", *REPORT_FIELDS, "data_overview",
        "ambiguity_log", "charts", "metrics", "assumptions_limitations", "reproducibility",
    )
    missing = [name for name in expected if not re.search(rf"\b{re.escape(name)}\b", result.stdout)]
    assert not missing, f"Missing from build_report.py --help: {', '.join(missing)}"


def test_report_spec_example_code_avoids_nonexistent_io_module():
    spec = json.loads(EXAMPLE_SPEC.read_text(encoding="utf-8"))
    assert "skills.eda.scripts._io" not in spec["reproducibility"]["code"]


def test_report_spec_example_includes_the_new_summary_fields():
    spec = json.loads(EXAMPLE_SPEC.read_text(encoding="utf-8"))
    missing = set(REPORT_FIELDS) - spec.keys()
    assert not missing, f"Missing example fields: {sorted(missing)}"


def test_report_does_not_replace_html_when_sidecar_target_is_invalid(tmp_path):
    report = feature("build_report")
    spec = legacy_example_spec()
    spec["charts"] = []
    html = tmp_path / "report.html"
    html.write_text("existing report", encoding="utf-8")
    (tmp_path / "eda_summary.json").mkdir()
    with pytest.raises(OSError):
        report.build_report(spec, tmp_path)
    assert html.read_text(encoding="utf-8") == "existing report"


def test_report_restores_previous_pair_when_second_replacement_fails(tmp_path, monkeypatch):
    report = feature("build_report")
    spec = legacy_example_spec()
    spec["charts"] = []
    outdir = tmp_path / "delivery"
    previous = {path: path.read_bytes() for path in report.build_report(spec, outdir)}
    previous_paths = set(tmp_path.rglob("*"))
    spec["title"] = "Replacement report"
    spec["data_overview"]["datasets"][0]["rows"] += 1
    replace = os.replace
    replacements = 0

    def fail_second_replacement(source, destination, *args, **kwargs):
        nonlocal replacements
        if Path(destination) in previous:
            replacements += 1
            if replacements == 2:
                raise OSError("Injected failure on second report replacement")
        return replace(source, destination, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "replace", fail_second_replacement)
        with pytest.raises(OSError, match="Injected failure on second report replacement"):
            report.build_report(spec, outdir)

    assert set(tmp_path.rglob("*")) == previous_paths
    assert {path: path.read_bytes() for path in previous} == previous


def test_report_serializes_writers_to_the_same_directory(tmp_path, monkeypatch):
    report = feature("build_report")
    first = legacy_example_spec()
    first["charts"] = []
    second = deepcopy(first)
    first["title"] = "First writer"
    second["title"] = "Second writer"
    first["data_overview"]["datasets"][0]["rows"] = 11
    second["data_overview"]["datasets"][0]["rows"] = 22
    first_html_installed = Event()
    release_first_writer = Event()
    second_ready_to_publish = Event()
    replace = os.replace
    publish = report.publish_report_pair

    def pause_after_first_html(source, destination, *args, **kwargs):
        replace(source, destination, *args, **kwargs)
        if Path(destination) == tmp_path / "report.html" and not first_html_installed.is_set():
            first_html_installed.set()
            assert release_first_writer.wait(timeout=10)

    def observe_second_publication(outdir, files):
        if first_html_installed.is_set():
            second_ready_to_publish.set()
        return publish(outdir, files)

    monkeypatch.setattr(os, "replace", pause_after_first_html)
    monkeypatch.setattr(report, "publish_report_pair", observe_second_publication)
    with ThreadPoolExecutor(max_workers=2) as writers:
        writer_a = writers.submit(report.build_report, first, tmp_path)
        try:
            assert first_html_installed.wait(timeout=10)
            writer_b = writers.submit(report.build_report, second, tmp_path)
            assert second_ready_to_publish.wait(timeout=10)
            finished_while_a_paused = bool(wait([writer_b], timeout=0.5).done)
        finally:
            release_first_writer.set()
        writer_a.result(timeout=10)
        html, sidecar = writer_b.result(timeout=10)

    title = one(Tags(html.read_text(encoding="utf-8")).root, "title").text()
    rows = json.loads(sidecar.read_text(encoding="utf-8"))["datasets"][0]["rows"]
    assert (finished_while_a_paused, title, rows) in {
        (False, "First writer", 11), (False, "Second writer", 22),
    }


def test_report_quarantines_mixed_pair_when_restoration_fails(tmp_path, monkeypatch):
    report = feature("build_report")
    spec = legacy_example_spec()
    spec["charts"] = []
    previous = {path: path.read_bytes() for path in report.build_report(spec, tmp_path)}
    spec["title"] = "New title"
    spec["data_overview"]["datasets"][0]["rows"] += 1
    replace = os.replace
    html_replaced = False

    def fail_install_and_restore(source, destination, *args, **kwargs):
        nonlocal html_replaced
        if Path(destination) == tmp_path / "eda_summary.json":
            raise OSError("Injected sidecar installation failure")
        if Path(destination) == tmp_path / "report.html":
            if html_replaced:
                raise OSError("Injected HTML restoration failure")
            html_replaced = True
        return replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "replace", fail_install_and_restore)
    with pytest.raises(OSError, match="Injected"):
        report.build_report(spec, tmp_path)

    present = {path: path.read_bytes() for path in previous if path.exists()}
    assert present == previous or (
        not present and all(path.with_name(path.name + ".incomplete").is_file() for path in previous)
    )


@pytest.fixture
def spec_with_dataset_structure():
    spec = legacy_example_spec()
    spec["charts"] = []
    structure = {
        "sheet": None,
        "header_rows": [1],
        "record_path": None,
        "column_names": ["ZZ_MARKER_COL", "units"],
    }
    spec["data_overview"]["datasets"][0]["structure"] = structure
    return spec, structure


def test_report_preserves_dataset_structure_only_in_sidecar(tmp_path, spec_with_dataset_structure):
    report = feature("build_report")
    spec, structure = spec_with_dataset_structure
    expected = deepcopy(structure)

    html, sidecar = report.build_report(spec, tmp_path)

    summary = json.loads(sidecar.read_text(encoding="utf-8"))
    assert summary["datasets"][0]["structure"] == expected
    assert "ZZ_MARKER_COL" not in html.read_text(encoding="utf-8")


@pytest.mark.parametrize(("field", "value"), [
    pytest.param("column_names", "ZZ_MARKER_COL", id="column-names-string"),
    pytest.param("header_rows", [0], id="header-row-zero"),
    pytest.param("unexpected", "extra property", id="unknown-key"),
])
def test_report_rejects_invalid_dataset_structure_before_writing(
    tmp_path, spec_with_dataset_structure, field, value,
):
    report = feature("build_report")
    spec, structure = spec_with_dataset_structure
    structure[field] = value

    with pytest.raises(ValueError, match="structure"):
        report.build_report(spec, tmp_path)

    assert not (tmp_path / "report.html").exists()
    assert not (tmp_path / "eda_summary.json").exists()


def test_report_shortens_paths_in_both_deliverables(tmp_path, monkeypatch):
    report = feature("build_report")
    monkeypatch.setattr(report.Path, "home", lambda: PurePosixPath("/Users/example-account"))
    spec = legacy_example_spec()
    spec["charts"] = []
    home_source = "/Users/example-account/input/shift.csv"
    work_source = tmp_path / "data" / "second.csv"
    outside_source = "/mnt/other-account/third.csv"
    spaced_source = "/Users/example-account/input files/shift.csv"
    spec["data_overview"]["datasets"][0]["read_ranges"] = [f"{home_source} lines 2–4"]
    spec["metrics"][0]["source_refs"] = [
        f"See {work_source}:2", f"{outside_source} line 7", "inputs/fourth.csv line 8",
    ]
    spec["reproducibility"]["source_locators"] = [
        {"file": home_source, "json_path": "$.orders[0]"},
        f'"{spaced_source}" lines 2–4',
        f"file://{home_source} line 3",
        r"C:\Users\windows-account\input\windows.csv line 5",
    ]
    spec["reproducibility"]["code"] = (
        f"frame = load_table('{spaced_source}')\n"
        'ratio = frame["total"]/frame["hours"]\n'
        'delimiter, encoding = "/", "utf-8"\n'
        'reference = "https://example.invalid/data/shift.csv"'
    )
    original_spec = deepcopy(spec)

    output, sidecar = report.build_report(spec, tmp_path / "delivery", base_dir=tmp_path)

    html = unescape(output.read_text(encoding="utf-8"))
    serialized = sidecar.read_text(encoding="utf-8")
    for content in (html, serialized):
        for path in (home_source, str(work_source), outside_source, spaced_source):
            assert path not in content, "A report exposed an absolute input path."
    assert "~/input/shift.csv lines 2–4" in html
    assert '"~/input files/shift.csv" lines 2–4' in html
    assert "$.orders[0]" in html
    assert "~/input/shift.csv line 3" in html
    assert "windows.csv line 5" in html
    assert "windows-account" not in html
    assert "frame = load_table('~/input files/shift.csv')" in html
    assert 'frame["total"]/frame["hours"]' in html
    assert 'delimiter, encoding = "/", "utf-8"' in html
    assert "https://example.invalid/data/shift.csv" in html
    summary = json.loads(serialized)
    assert summary["datasets"][0]["read_ranges"] == ["~/input/shift.csv lines 2–4"]
    refs = ["See data/second.csv:2", "third.csv line 7", "inputs/fourth.csv line 8"]
    assert summary["metrics"][0]["source_refs"] == refs
    assert all(ref in html for ref in refs)
    assert spec == original_spec


def test_report_shortens_paths_under_windows_home(tmp_path, monkeypatch):
    report = feature("build_report")
    monkeypatch.setattr(report.Path, "home", lambda: PureWindowsPath(r"C:\Users\windows-account"))
    spec = legacy_example_spec()
    spec["charts"] = []
    spec["metrics"][0]["source_refs"] = [r"c:\users\WINDOWS-ACCOUNT\input\windows.csv line 5"]

    html, sidecar = report.build_report(spec, tmp_path)

    expected = "~/input/windows.csv line 5"
    assert expected in html.read_text(encoding="utf-8")
    assert json.loads(sidecar.read_text(encoding="utf-8"))["metrics"][0]["source_refs"] == [expected]


@pytest.mark.parametrize(("statement", "absolute_path"), [
    ('# input: /Users/sample/raw.csv', '/Users/sample/raw.csv'),
    ('path = f"/Users/sample/{name}.csv"', '/Users/sample/'),
    ('path = "/virtual/project/raw.csv"', '/virtual/project/raw.csv'),
])
def test_report_shortens_paths_in_reproduction_code(tmp_path, statement, absolute_path):
    spec = legacy_example_spec()
    spec["charts"] = []
    spec["reproducibility"]["code"] = f"{statement}\ny = x /2\nrate = units /3600"
    html, sidecar = feature("build_report").build_report(spec, tmp_path)

    document = Tags(html.read_text(encoding="utf-8")).root
    code = "".join(one(document, "code").children)
    ast.parse(code)
    assert absolute_path not in code
    assert absolute_path not in sidecar.read_text(encoding="utf-8")
    assert code.splitlines()[1:] == ["y = x /2", "rate = units /3600"]
    if "{name}" in statement:
        assert "{name}.csv" in code


def test_report_shortens_only_file_paths_in_free_text(tmp_path):
    spec = legacy_example_spec()
    spec["charts"] = []
    paths = [r"C:\Users\demo\x.csv", "/virtual/project/raw.csv", "/home/demo/cache"]
    preserved = ["Output /2 per shift", "Endpoint /api/sales", "Root file /raw.csv"]
    spec["metrics"][0]["source_refs"] = [*paths, *preserved]
    html, sidecar = feature("build_report").build_report(spec, tmp_path)

    page = unescape(html.read_text(encoding="utf-8"))
    refs = json.loads(sidecar.read_text(encoding="utf-8"))["metrics"][0]["source_refs"]
    assert all(path not in page and path not in refs for path in paths)
    assert refs[len(paths):] == preserved
    assert all(text in page for text in preserved)


def test_report_preserves_jsonpath_in_both_deliverables(tmp_path):
    spec = legacy_example_spec()
    spec["charts"] = []
    locators = ['$["/api/sales"][0]', '$["/home/demo/sales.csv"][0]']
    spec["metrics"][0]["source_refs"] = locators
    spec["reproducibility"]["code"] = f"locator = '{locators[1]}'"
    html, sidecar = feature("build_report").build_report(spec, tmp_path)

    document = Tags(html.read_text(encoding="utf-8")).root
    assert all(locator in document.text() for locator in locators)
    code = "".join(one(document, "code").children)
    assignment, = ast.parse(code).body
    assert ast.literal_eval(assignment.value) == locators[1]
    assert json.loads(sidecar.read_text(encoding="utf-8"))["metrics"][0]["source_refs"] == locators


def test_report_shortens_paths_in_dollar_prefixed_source_refs(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", "/Users/example-account")
    spec = legacy_example_spec()
    spec["charts"] = []
    locators = ['$["/api/sales"][0]', "$.items[0]"]
    spec["metrics"][0]["source_refs"] = ["$20 from /Users/sample/raw.csv", *locators]

    html, sidecar = feature("build_report").build_report(spec, tmp_path)

    page = unescape(html.read_text(encoding="utf-8"))
    serialized = sidecar.read_text(encoding="utf-8")
    for content in (page, serialized):
        assert "/Users/sample" not in content
    refs = ["$20 from raw.csv", *locators]
    assert json.loads(serialized)["metrics"][0]["source_refs"] == refs
    assert all(ref in page for ref in refs)


def test_report_preserves_python_division_in_reproduction_code(tmp_path):
    spec = legacy_example_spec()
    spec["charts"] = []
    statements = ["y = x /2", "rate = units /3600"]
    spec["reproducibility"]["code"] = "\n".join(statements)

    document = build_page(spec, tmp_path)

    code = "".join(one(document, "code").children)
    ast.parse(code)
    assert code.splitlines() == statements


def test_report_shortens_quoted_path_in_reproduction_code(tmp_path):
    spec = legacy_example_spec()
    spec["charts"] = []
    absolute_path = "/Users/someone/data/x.csv"
    spec["reproducibility"]["code"] = f'path = "{absolute_path}"'

    document = build_page(spec, tmp_path)

    code = "".join(one(document, "code").children)
    assignment, = ast.parse(code).body
    shortened = ast.literal_eval(assignment.value)
    assert not Path(shortened).is_absolute()
    assert Path(shortened).name == "x.csv"


def test_report_shortens_sample_size_keys_in_deliverables(tmp_path):
    report = feature("build_report")
    spec = legacy_example_spec()
    spec["charts"] = []
    absolute_path = "/Users/sample/raw.csv"
    spec["reproducibility"]["sample_sizes"] = {absolute_path: 3}

    output, sidecar = report.build_report(spec, tmp_path)

    html = output.read_text(encoding="utf-8")
    summary = json.loads(sidecar.read_text(encoding="utf-8"))
    assert absolute_path not in json.dumps(summary)
    assert absolute_path not in unescape(html)
    keys = [Path(term.text()) for term in Tags(html).root.find("dt")]
    assert any(key.name == "raw.csv" and not key.is_absolute() for key in keys)


@pytest.mark.parametrize("field", ["question", "observation", "domain_interpretation"])
def test_report_requires_chart_question_observation_and_interpretation(tmp_path, field):
    report = feature("build_report")
    spec = legacy_example_spec()
    spec["charts"][0][field] = None
    with pytest.raises(ValueError, match=field):
        report.build_report(spec, tmp_path)


def test_chart_insights_can_render_without_optional_plot_metadata(tmp_path):
    plots = feature("plots")
    report = feature("build_report")
    spec = legacy_example_spec()
    chart = spec["charts"][0]
    for field in ("type", "source_columns", "n_used", "n_excluded", "exclusion_reason"):
        del chart[field]
    plots.histogram(pd.DataFrame({"units": [3, 6, 9]}), "units", tmp_path / chart["image_path"])
    html, sidecar = report.build_report(spec, tmp_path / "out", base_dir=tmp_path)
    result = json.loads(sidecar.read_text(encoding="utf-8"))["charts"][0]
    assert result["type"] == "unknown" and result["source_columns"] == []
    assert "Excluded" not in html.read_text(encoding="utf-8")

    chart["n_excluded"] = 0
    for language in ("en", "fr"):
        spec["language"] = language
        html, _ = report.build_report(spec, tmp_path / "out", base_dir=tmp_path)
        page = html.read_text(encoding="utf-8")
        assert "Data overview" in Tags(page).root.text()
        assert "Excluded 0" in Tags(page).root.text()


@pytest.mark.parametrize("field", ["n_used", "n_excluded"])
@pytest.mark.parametrize("value", [
    pytest.param(-1, id="negative"),
    pytest.param(1.5, id="fractional"),
    pytest.param("2", id="string"),
])
def test_validate_summary_rejects_invalid_chart_counts(field, value):
    report = feature("build_report")
    summary = report.make_summary(legacy_example_spec())
    chart = summary["charts"][0]
    chart.update(n_used=2, n_excluded=1)
    report.validate_summary(summary)
    chart[field] = value

    with pytest.raises(ValueError, match=field):
        report.validate_summary(summary)


@pytest.mark.parametrize("fallback", [False, True], ids=["default", "fallback"])
@pytest.mark.parametrize("value", [
    pytest.param(-1, id="negative"),
    pytest.param(1.5, id="fractional"),
    pytest.param("2", id="string"),
])
def test_validate_summary_rejects_invalid_pairwise_counts(monkeypatch, fallback, value):
    if fallback:
        monkeypatch.setitem(sys.modules, "jsonschema", None)
    report = feature("build_report")
    summary = report.make_summary(legacy_example_spec())
    counts = {"units": {"units": 2, "hours": 0}}
    summary["charts"][0]["pairwise_n"] = counts
    report.validate_summary(summary)
    counts["units"]["hours"] = value

    with pytest.raises(ValueError, match="pairwise_n"):
        report.validate_summary(summary)


def metric_summary(**overrides):
    metric = {
        "name": "Completion rate",
        "numerator": 50,
        "denominator": 200,
        "value": 25,
        "unit": "%",
        **overrides,
    }
    return {"metrics": [metric]}


@pytest.mark.parametrize("overrides", [
    pytest.param({}, id="percent"),
    pytest.param({"unit": "ratio", "value": 0.25}, id="ratio"),
    pytest.param({"numerator": 1, "denominator": 1e13, "value": 1e-13, "unit": "ratio"},
                 id="tiny-ratio"),
    pytest.param({"numerator": 0, "denominator": 1e13, "value": 0, "unit": "ratio"},
                 id="zero-ratio"),
    pytest.param({"numerator": 1, "denominator": 3, "value": 33.333333333333336},
                 id="unrounded-one-third-percent"),
    pytest.param({"unit": "per 1,000", "scale": 1000, "value": 250}, id="per-thousand"),
    pytest.param({"scale": 1000, "value": 250}, id="scale-overrides-percent"),
    pytest.param({"numerator": 394, "denominator": 420, "value": 394 / 420 * 100},
                 id="unrounded-percent"),
    pytest.param({"numerator": 432737, "denominator": 251, "value": 1724.0517928286852,
                  "unit": "ratio"}, id="full-precision"),
    pytest.param({"numerator": 1, "denominator": 300_000, "value": 1 / 300_000,
                  "unit": "ratio"}, id="scientific-notation"),
    pytest.param({"numerator": 1_000_000_000, "denominator": 1, "value": 1_000_000_000.75,
                  "unit": "ratio"}, id="relative-tolerance"),
    pytest.param({"denominator": 0, "value": None}, id="zero-denominator-null-value"),
    pytest.param({"numerator": None}, id="null-numerator"),
    pytest.param({"denominator": None}, id="null-denominator"),
    pytest.param({"value": None}, id="null-value"),
    pytest.param({"numerator": "90"}, id="nonnumeric-numerator"),
    pytest.param({"denominator": "0"}, id="nonnumeric-denominator"),
    pytest.param({"value": "30"}, id="nonnumeric-value"),
])
def test_validate_metric_values_accepts_valid_metrics(overrides):
    feature("build_report").validate_metric_values(metric_summary(**overrides))


def test_validate_metric_values_reports_expected_and_actual_percent():
    report = feature("build_report")

    with pytest.raises(ValueError, match="Completion rate") as error:
        report.validate_metric_values(metric_summary(value=0.25))

    message = str(error.value)
    assert re.search(r"(?<![\d.])25(?:\.0+)?(?!\d|\.\d)", message)
    assert "0.25" in message


def test_validate_metric_values_reports_fractional_expected_percent_as_decimal():
    report = feature("build_report")

    with pytest.raises(ValueError, match="Completion rate") as error:
        report.validate_metric_values(metric_summary(numerator=394, denominator=420, value=93.7))

    message = str(error.value)
    assert "93.8" in message
    assert "/" not in message


@pytest.mark.parametrize("overrides", [
    pytest.param({"unit": "ratio"}, id="ratio-with-percent-value"),
    pytest.param({"numerator": 1, "denominator": 1e13, "value": 0, "unit": "ratio"},
                 id="tiny-ratio-reported-as-zero"),
    pytest.param({"numerator": 1, "denominator": 1e13, "value": -1e-13, "unit": "ratio"},
                 id="tiny-ratio-with-wrong-sign"),
    pytest.param({"numerator": 0, "denominator": 1e13, "value": 1e-13, "unit": "ratio"},
                 id="zero-ratio-reported-as-positive"),
    pytest.param({"numerator": 0, "denominator": 1e13, "value": -1e-13, "unit": "ratio"},
                 id="zero-ratio-reported-as-negative"),
    pytest.param({"numerator": 1, "denominator": 3, "value": 33.33},
                 id="rounded-one-third-percent"),
    pytest.param({"numerator": 394, "denominator": 420, "value": 93.81}, id="two-decimals"),
    pytest.param({"numerator": 394, "denominator": 420, "value": 93.8}, id="one-decimal"),
    pytest.param({"numerator": 394, "denominator": 420, "value": 94}, id="integer-rounding"),
    pytest.param({"numerator": 394, "denominator": 420, "value": 93.7}, id="outside-rounding-tolerance"),
    pytest.param({"numerator": 1, "denominator": 300_000, "value": 3.33e-6,
                  "unit": "ratio"}, id="rounded-scientific-notation"),
    pytest.param({"numerator": 1, "denominator": 300_000, "value": 3.32e-6,
                  "unit": "ratio"}, id="outside-scientific-rounding-tolerance"),
    pytest.param({"numerator": 1_000_000_000, "denominator": 1, "value": 1_000_000_001.25,
                  "unit": "ratio"}, id="outside-relative-tolerance"),
    pytest.param({"numerator": 1, "denominator": 1_000_000, "value": 1.0000005e-6,
                  "unit": "ratio"}, id="small-ratio-outside-relative-tolerance"),
    pytest.param({"numerator": 1, "denominator": 1_000_000, "value": 1.000002e-6,
                  "unit": "ratio"}, id="outside-absolute-tolerance"),
    pytest.param({"denominator": 0, "value": 3}, id="zero-denominator-numeric-value"),
    pytest.param({"numerator": None, "denominator": 0, "value": 3}, id="zero-denominator-null-numerator"),
])
def test_validate_metric_values_rejects_invalid_metrics(overrides):
    report = feature("build_report")
    with pytest.raises(ValueError, match="Completion rate"):
        report.validate_metric_values(metric_summary(**overrides))


@pytest.mark.parametrize(
    "summary_path", sorted((ROOT / "docs" / "gallery").glob("*.summary.json")),
    ids=lambda path: path.name,
)
def test_validate_metric_values_accepts_gallery_summary(summary_path):
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    feature("build_report").validate_metric_values(summary)


@pytest.fixture
def spec_with_rate():
    spec = legacy_example_spec()
    spec["charts"] = []
    metric = metric_summary()["metrics"][0]
    metric.update(
        definition="Share of records marked complete.",
        depends_on_ambiguity_ids=[],
        condition=None,
        source_refs=["counts.csv line 2"],
    )
    spec["metrics"].append(metric)
    return spec, metric


def test_report_rejects_inconsistent_metric_before_writing(tmp_path, spec_with_rate):
    report = feature("build_report")
    spec, metric = spec_with_rate
    metric["value"] = 30

    with pytest.raises(ValueError, match="Completion rate"):
        report.build_report(spec, tmp_path)

    assert not (tmp_path / "report.html").exists()
    assert not (tmp_path / "eda_summary.json").exists()


@pytest.mark.parametrize("overrides", [
    pytest.param({}, id="percent"),
    pytest.param({"unit": "per 1,000", "scale": 1000, "value": 250}, id="explicit-scale"),
])
def test_report_writes_consistent_metric_to_sidecar(tmp_path, spec_with_rate, overrides):
    report = feature("build_report")
    spec, metric = spec_with_rate
    metric.update(overrides)
    expected_metric = deepcopy(metric)

    html, sidecar = report.build_report(spec, tmp_path)

    assert html == tmp_path / "report.html" and html.is_file()
    assert sidecar == tmp_path / "eda_summary.json"
    summary = json.loads(sidecar.read_text(encoding="utf-8"))
    assert summary["metrics"][-1] == expected_metric


@pytest.mark.parametrize(("numerator", "denominator", "value", "display", "unrounded_prefix"), [
    pytest.param(394, 420, 394 / 420 * 100, "93.81", "93.8095", id="two-decimal-places"),
    pytest.param(60, 7854, 60 / 7854 * 100, "0.7639", None, id="four-significant-digits"),
    pytest.param(13, 70_000, 13 / 70_000 * 100, "0.01857", None, id="ignore-leading-zero"),
    pytest.param(-301, 25_000, -1.204, "-1.2", None, id="trim-trailing-zero-for-negative"),
    pytest.param(9, 10, 90.0, "90", None, id="whole-valued-float"),
    pytest.param(None, None, 123456789, "123,456,789", None, id="integer"),
])
def test_report_formats_metric_card_without_changing_sidecar_value(
    tmp_path, spec_with_rate, numerator, denominator, value, display, unrounded_prefix,
):
    report = feature("build_report")
    spec, metric = spec_with_rate
    metric.update(numerator=numerator, denominator=denominator, value=value)
    spec.update(headline="Completion is measured on eligible records.", kpis=[metric["name"]],
                key_charts=[], insights=[])

    html, sidecar = report.build_report(spec, tmp_path)

    summary = json.loads(sidecar.read_text(encoding="utf-8"))
    saved_value = summary["metrics"][-1]["value"]
    assert type(saved_value) is type(value)
    assert saved_value == value
    page = html.read_text(encoding="utf-8")
    summary_panel, _ = panels(Tags(page).root)
    tile = one(summary_panel, class_name="kpi")
    assert metric["name"] in tile.text()
    assert re.search(rf"(?<![\d.-]){re.escape(display)}(?![\d.])", tile.text())
    if unrounded_prefix is not None:
        assert unrounded_prefix not in page


@pytest.mark.parametrize("language", ["ko", "en"])
@pytest.mark.parametrize(("value", "display"), [(266170, "266,170"), (1234567.89, "1,234,567.89")])
def test_report_groups_thousands_in_kpi_and_metric_table(
    tmp_path, report_spec, language, value, display,
):
    metric = report_spec["metrics"][2]
    metric["value"] = value
    report_spec.update(language=language, kpis=[metric["name"]])
    summary, details = panels(build_page(report_spec, tmp_path))

    assert one(summary, "p", class_name="metric-value").text() == f"{display} {metric['unit']}"
    table = one(details, "section", id="details-metrics")
    row = next(row for row in one(table, "tbody").find("tr")
               if one(row, "th", scope="row").text() == metric["name"])
    assert next(row.find("td")).text() == f"{display} {metric['unit']}"

    sidecar = json.loads((tmp_path / "delivery" / "eda_summary.json").read_text(encoding="utf-8"))
    assert sidecar["metrics"][2]["value"] == value


def test_render_metrics_preserves_string_values(spec_with_rate):
    report = feature("build_report")
    _, metric = spec_with_rate
    metric["value"] = "001.2300"

    html = report.render_metrics([metric], {}, korean=False)

    assert re.search(r"(?<![\d.])001\.2300(?![\d.])", Tags(html).root.text())


def test_report_rejects_kpi_with_empty_source_refs(tmp_path, report_spec):
    metric = report_spec["metrics"][1]
    metric["source_refs"] = []

    result = run_build_cli(report_spec, tmp_path)

    assert result.returncode != 0
    assert metric["name"] in result.stderr and "source_refs" in result.stderr
    assert not (tmp_path / "delivery" / "report.html").exists()
    assert not (tmp_path / "delivery" / "eda_summary.json").exists()


def test_report_warns_about_empty_source_refs_for_non_kpi(tmp_path, report_spec):
    metric = report_spec["metrics"][2]
    metric["source_refs"] = []
    report_spec["headline"] = f"{metric['name']} was 1 for the selected interval."
    report_spec["insights"][0]["text"] = f"{metric['name']} reached 1 before closing."

    warnings, stderr = build_with_warnings(report_spec, tmp_path)

    assert any(metric["name"] in warning and "source_refs" in warning for warning in warnings)
    assert metric["name"] in stderr and "source_refs" in stderr


@pytest.fixture
def rendered_chart(tmp_path, report_spec):
    chart = report_spec["charts"][0]
    figure = tmp_path / "delivery" / "figures" / f"{chart['id']}.png"
    figure.parent.mkdir(parents=True)
    metadata = feature("plots").histogram(
        pd.DataFrame({"units": [3, 6, 9]}), "units", figure, chart_id=chart["id"],
    )
    chart["image_path"] = figure.relative_to(tmp_path).as_posix()
    return chart, metadata, figure


def write_plot_results(tmp_path, results):
    path = tmp_path / "plot-results.json"
    path.write_text(json.dumps(results), encoding="utf-8")
    return path


@pytest.mark.parametrize(("field", "value"), [
    ("type", "scatter"), ("source_columns", ["hours"]), ("n_used", 2),
    ("n_excluded", 1), ("exclusion_reason", "Missing values"),
])
def test_report_rejects_plot_metadata_mismatch(tmp_path, report_spec, rendered_chart, field, value):
    chart, metadata, _ = rendered_chart
    chart[field] = value
    results = write_plot_results(tmp_path, [metadata])

    result = run_build_cli(report_spec, tmp_path, "--plot-results", results)

    assert result.returncode != 0
    assert chart["id"] in result.stderr and field in result.stderr
    assert not (tmp_path / "delivery" / "eda_summary.json").exists()


@pytest.mark.parametrize("case", ["extra-result", "missing-result"])
def test_report_rejects_unmatched_rendered_chart(tmp_path, report_spec, rendered_chart, case):
    chart, metadata, _ = rendered_chart
    expected_id = "unlisted-chart" if case == "extra-result" else chart["id"]
    if case == "extra-result":
        entries = [metadata, {**metadata, "id": expected_id}]
    else:
        del chart["image_path"]
        entries = []
    results = write_plot_results(tmp_path, entries)

    result = run_build_cli(report_spec, tmp_path, "--plot-results", results)

    assert result.returncode != 0
    assert expected_id in result.stderr and "plot-results" in result.stderr


def test_report_matches_plot_metadata_and_allows_direct_images(tmp_path, report_spec, rendered_chart):
    chart, metadata, _ = rendered_chart
    del chart["image_path"], chart["source_columns"]
    results = write_plot_results(tmp_path, [metadata])

    result = run_build_cli(report_spec, tmp_path, "--plot-results", results)

    assert result.returncode == 0, result.stderr
    outdir = tmp_path / "delivery"
    assert 'src="data:image/png;base64,' in (outdir / "report.html").read_text(encoding="utf-8")
    summary = json.loads((outdir / "eda_summary.json").read_text(encoding="utf-8"))
    assert [entry["id"] for entry in summary["charts"]] == [entry["id"] for entry in report_spec["charts"]]
    assert summary["charts"][0]["source_columns"] == metadata["source_columns"]
    assert "provenance" not in summary


def test_report_plot_results_are_optional(tmp_path, report_spec, rendered_chart):
    chart, metadata, _ = rendered_chart
    chart["n_used"] = metadata["n_used"] - 1
    write_plot_results(tmp_path, [metadata])

    build_cli(report_spec, tmp_path)

    sidecar = tmp_path / "delivery" / "eda_summary.json"
    assert json.loads(sidecar.read_text(encoding="utf-8"))["charts"][0]["n_used"] == chart["n_used"]


def test_report_records_provenance_for_input_files_and_delivered_figures(tmp_path, report_spec, rendered_chart):
    _, metadata, figure = rendered_chart
    results = write_plot_results(tmp_path, [metadata])
    sources = [tmp_path / "source.csv", tmp_path / "supplement.json"]
    sources[0].write_bytes(b"units\n3\n6\n9\n")
    sources[1].write_bytes(b'{"closed": false}\n')

    result = run_build_cli(
        report_spec, tmp_path, "--plot-results", results, "--input", sources[0], "--input", sources[1],
    )

    assert result.returncode == 0, result.stderr
    outdir = tmp_path / "delivery"
    summary = json.loads((outdir / "eda_summary.json").read_text(encoding="utf-8"))
    provenance = summary["provenance"]
    assert set(provenance) == {"inputs", "skill_version", "schema_version", "builder", "outputs"}
    assert provenance["inputs"] == [
        {"name": source.name, "sha256": sha256(source.read_bytes()).hexdigest()} for source in sources
    ]
    assert provenance["outputs"] == [{
        "path": f"figures/{figure.name}", "sha256": sha256(figure.read_bytes()).hexdigest(),
    }]
    assert provenance["skill_version"] == (SCRIPTS.parent / "VERSION").read_text(encoding="utf-8").strip()
    assert provenance["schema_version"]
    assert "build_report" in provenance["builder"]
    assert str(tmp_path) not in json.dumps(provenance)
    feature("build_report").validate_summary(summary)


@pytest.mark.parametrize("fallback", [False, True], ids=["default", "fallback"])
@pytest.mark.parametrize(("record", "key", "value"), [
    ("provenance", "skill_version", ""),
    ("provenance", "schema_version", 1),
    ("provenance", "builder", "/tmp/build_report.py"),
    ("inputs", "name", "/tmp/source.csv"),
    ("inputs", "name", r"C:\data\source.csv"),
    ("inputs", "sha256", "g" * 64),
    ("outputs", "path", "/tmp/figure.png"),
    ("outputs", "path", "figures/../report.html"),
    ("outputs", "sha256", "a" * 63),
])
def test_summary_validates_provenance_format(monkeypatch, fallback, record, key, value):
    if fallback:
        monkeypatch.setitem(sys.modules, "jsonschema", None)
    report = feature("build_report")
    summary = report.make_summary(legacy_example_spec())
    provenance = {
        "skill_version": "0.4.0", "schema_version": "1.0.0", "builder": "build_report.py@0.4.0",
        "inputs": [{"name": "source.csv", "sha256": "a" * 64}],
        "outputs": [{"path": "figures/chart.png", "sha256": "b" * 64}],
    }
    summary["provenance"] = provenance
    report.validate_summary(summary)
    target = provenance if record == "provenance" else provenance[record][0]
    target[key] = value

    with pytest.raises(ValueError, match=key):
        report.validate_summary(summary)
