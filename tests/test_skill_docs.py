from decimal import Decimal
from hashlib import sha256
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path
from unicodedata import normalize

import pytest


ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "skills" / "ask-first-eda"
REQUIREMENTS = ROOT / "docs" / "requirements.md"


@pytest.fixture
def skill_doc():
    return (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")


def test_ask_first_eda_skill_identity():
    skill = ROOT / "skills" / "ask-first-eda" / "SKILL.md"
    old_directory = ROOT / "skills" / "eda"
    assert not old_directory.exists(), f"Remove the old skill directory: {old_directory}"
    assert skill.is_file(), f"Missing {skill.relative_to(ROOT)}"
    contents = skill.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\n(.*?)\n---[ \t]*(?:\n|$)", contents, re.S)
    assert frontmatter, "SKILL.md must start with frontmatter"
    assert re.search(r"^name:[ \t]+ask-first-eda[ \t]*$", frontmatter[1], re.M)


def test_tracked_files_use_the_new_skill_name():
    gallery_reports = [
        f":!{path.relative_to(ROOT).as_posix()}"
        for path in (ROOT / "docs" / "gallery").glob("*.html")
        if path.name != "index.html"
    ]
    result = subprocess.run(
        [
            "git", "grep", "-n", "-I", "-E", r"/e[d]a([^[:alnum:]_]|$)", "--",
            ":!evals/ab_summary.md", ":!evals/runs/**",
            ":(exclude,icase,glob)**/changelog*", *gallery_reports,
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode in {0, 1}, result.stderr
    assert result.returncode == 1, "Old skill references found:\n" + result.stdout


@pytest.mark.parametrize("readme", ["README.md", "README.ko.md"])
def test_readme_uses_ask_first_eda_name(readme):
    contents = (ROOT / readme).read_text(encoding="utf-8")
    assert "Ask First EDA" in contents.splitlines()[0]
    assert re.search(r"/ask-first-eda\b", contents)
    assert re.search(r"\bskills/ask-first-eda\b", contents)


@pytest.fixture(params=["README.md", "README.ko.md"])
def readme_text(request):
    return (ROOT / request.param).read_text(encoding="utf-8")


def test_readme_opens_with_example_question_preview_and_install(readme_text):
    title, value, rest = readme_text.strip().split("\n\n", 2)
    assert re.fullmatch(r"# [^\n]+", title)
    assert re.fullmatch(r"[^#!|>\n].+[.!]", value)
    table = re.search(r"^\|[^\n]+\|\n\|[-: |]+\|\n((?:\|[^\n]+\|\n)+)", rest, re.M)
    assert table and len(table[1].splitlines()) == 4, "Expected a four-row example"
    question = re.search(r"^[^\n|]+\?$", rest, re.M)
    preview = re.search(r"!\[[^\]]*\]\([^)]*report-preview\.png\)", rest)
    install = re.search(r"^## (?:Install|설치)$", rest, re.M)
    assert question and preview and install
    assert table.end() <= question.start() < preview.start() < install.start()


def test_readme_links_to_pages_and_release_in_opening(readme_text):
    opening = readme_text.split("\n## ", 1)[0]
    after_table = opening.rsplit("\n|", 1)[1]
    pages = "https://ltljh.github.io/ask-first-eda/gallery/"
    assert f"]({pages}support_tickets.html)" in after_table
    assert f"]({pages}index.html)" in after_table
    assert "](https://github.com/LTLJH/ask-first-eda/releases/latest)" in after_table


@pytest.fixture
def evaluation(readme_text):
    return re.split(r"^## (?:Evaluation|평가)$", readme_text, flags=re.M)[1].split("\n## ")[0]


def test_readme_evaluation_links_current_and_earlier_results(evaluation):
    links = re.findall(r"\]\(([^)]+)\)", evaluation)
    assert links == ["evals/abc_summary.md", "evals/ab_summary.md"]
    assert all((ROOT / link).is_file() for link in links)
    assert not any(value in evaluation for value in ("4.54", "29.1%", "1.8%"))


def test_readme_evaluation_reports_scores_missed_question_and_cost(evaluation):
    assert "18/24" in evaluation and "24/24" in evaluation
    assert re.search(r"denominator|분모", evaluation, re.I)
    assert re.search(r"none asked|no condition asked|묻지 않", evaluation, re.I)
    assert re.search(r"time|시간", evaluation, re.I)
    assert re.search(r"tokens|토큰", evaluation, re.I)
    assert re.search(r"twice|2배", evaluation, re.I)


def test_abc_summary_distinguishes_correct_numbers_from_confirmed_values():
    summary = ROOT / "evals/abc_summary.md"
    assert summary.is_file()
    rows = [line.split("|")[2:-1] for line in summary.read_text(encoding="utf-8").splitlines()
            if line.startswith(("| Correct numeric", "| Confirmed final"))]
    assert [[cell.strip() for cell in row] for row in rows] == [
        ["18/24", "24/24", "24/24"],
        ["14/24", "18/24", "18/24"],
    ]


def test_contributing_documents_case_reports_and_development_workflow():
    path = ROOT / "CONTRIBUTING.md"
    assert path.is_file()
    contents = path.read_text(encoding="utf-8")
    assert ".github/ISSUE_TEMPLATE/case_report.md" in contents
    for phrase in (
        "synthetic",
        "anonymized",
        "business question",
        "ambiguous definitions",
        "expected",
        "actual",
        "client",
        "version",
        "python -m pip install -r requirements.txt -r requirements-dev.txt",
        "python -m pytest -q",
        "ln -sf ../../scripts/hooks/pre-commit .git/hooks/pre-commit",
        "red",
        "green",
    ):
        assert phrase.lower() in contents.lower()
    assert "personal paths" in contents.lower()
    assert "company data" in contents.lower()
    assert "source text" in contents.lower()


def test_readmes_cross_link_and_link_to_contributing():
    english = (ROOT / "README.md").read_text(encoding="utf-8")
    korean = (ROOT / "README.ko.md").read_text(encoding="utf-8")
    assert re.search(r"\]\(README\.ko\.md\)", english)
    assert re.search(r"\]\(README\.md\)", korean)
    for contents in (english, korean):
        assert re.search(r"\]\(CONTRIBUTING\.md\)", contents)


def test_case_report_template_collects_reproduction_details():
    path = ROOT / ".github" / "ISSUE_TEMPLATE" / "case_report.md"
    assert path.is_file()
    contents = path.read_text(encoding="utf-8")
    frontmatter = re.match(r"\A---\n(.*?)\n---\n", contents, re.S)
    assert frontmatter
    for key in ("name", "about"):
        assert re.search(rf"^{key}:[ \t]+\S", frontmatter[1], re.M)
    body = contents[frontmatter.end():].lower()
    for field in ("anonymized input", "business question", "ambiguous definitions",
                  "expected result", "actual result", "environment"):
        assert field in body
    environment = body.split("environment", 1)[1]
    for field in ("client", "version", "os", "python"):
        assert re.search(rf"\b{field}\b", environment)


def test_skill_has_clean_step(skill_doc):
    assert re.search(r"^#{1,6}[ \t]+(?:Step\b[^\n]*\b)?Clean\b", skill_doc, re.M), (
        "SKILL.md must have a Clean step heading"
    )


def documented_script_commands(text):
    command_pattern = re.compile(
        r'''(?:^|`+)[ \t]*(python3[ \t]+-I[ \t]+"\$SKILL_DIR/scripts/[^/"`\n]+\.py"'''
        r'''(?=[ \t`<>|&]|$)[^`\n]*)''',
        re.M,
    )
    # Match whole shell words so quoted operators stay literal and 2> ends the command before 2.
    shell_tokens = re.compile(
        r'''(?P<end>\#|[0-9]*[<>]|[|&])|(?:'[^']*'|"(?:\\.|[^"\\])*"|\\.|[^\s'"\\<>|&])+'''
    )
    commands = []
    for match in command_pattern.finditer(re.sub(r"\\\r?\n", "", text)):
        command = match[1]
        end = next((token.start() for token in shell_tokens.finditer(command) if token["end"]), len(command))
        _, _, script, *args = shlex.split(command[:end])
        commands.append((Path(script).name, args))
    return commands


def check_commands(text):
    try:
        commands = documented_script_commands(text)
    except ValueError as error:
        return [f"Could not parse a documented script command: {error}"]
    if not commands:
        return ["No documented script commands found in SKILL.md"]

    options_by_script = {}
    audit_options = []
    for script, args in commands:
        options = {arg.split("=", 1)[0] for arg in args if arg.startswith("--")}
        options_by_script.setdefault(script, set()).update(options)
        if script == "audit_clean.py":
            audit_options.append(options)

    failures = []
    required_options = {"--cleaned", "--excluded"}
    if not audit_options:
        failures.append("SKILL.md must show a Python command that runs audit_clean.py")
    elif not any(required_options <= options for options in audit_options):
        failures.append("The audit_clean.py command must include --cleaned and --excluded together")

    for script, options in options_by_script.items():
        script_path = SKILL_DIR / "scripts" / script
        if not script_path.is_file():
            failures.append(f"Missing script documented in SKILL.md: {script}")
            continue
        help_result = subprocess.run(
            [sys.executable, "-I", "-B", script_path, "--help"],
            capture_output=True,
            text=True,
        )
        if help_result.returncode != 0:
            failures.append(f"{script} --help exited with {help_result.returncode}: {help_result.stderr.strip()}")
            continue
        help_options = set(re.findall(r"(?<!\S)--[\w-]+(?=[\s,=]|$)", help_result.stdout))
        missing = sorted(options - help_options)
        if missing:
            failures.append(f"Options missing from {script} --help: {', '.join(missing)}")
    return failures


def test_documented_script_options_exist(skill_doc):
    failures = check_commands(skill_doc)
    assert not failures, "\n".join(failures)


def test_skill_has_a_version_file():
    version_file = SKILL_DIR / "VERSION"
    assert version_file.is_file(), "The skill version must be recorded in skills/ask-first-eda/VERSION"
    assert re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version_file.read_text(encoding="utf-8").strip())


AUDIT_COMMAND = 'python3 -I "$SKILL_DIR/scripts/audit_clean.py" "$INPUT"'
VALID_AUDIT_COMMAND = AUDIT_COMMAND + ' --cleaned "$CLEANED" --excluded "$WORK/excluded.csv"'
INSPECT_COMMAND = 'python3 -I "$SKILL_DIR/scripts/inspect_data.py" "$INPUT"'


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        pytest.param(
            f"```sh\n{AUDIT_COMMAND} \\\n  --cleaned \"$CLEANED\" \\\n"
            '  --excluded="$WORK/excluded.csv"\n```',
            [],
            id="fenced-command-with-continuations",
        ),
        pytest.param(
            f"Run `{VALID_AUDIT_COMMAND.replace('--cleaned', '--cleand')}`.",
            ["--cleand", "--cleaned and --excluded together"],
            id="misspelled-option",
        ),
        pytest.param(
            f'{VALID_AUDIT_COMMAND} --delimiter "," --header no --encoding=cp949\n'
            f'{VALID_AUDIT_COMMAND} --sheet Sales --header-row 3\n'
            f'{VALID_AUDIT_COMMAND} --table-id sheet:Sales\n'
            f"{VALID_AUDIT_COMMAND} --json-record-path '$'",
            [],
            id="audit-table-selection-options",
        ),
        pytest.param(
            f'Run `{AUDIT_COMMAND} --cleaned "$CLEANED"`.',
            ["--cleaned and --excluded together"],
            id="missing-excluded",
        ),
        pytest.param(
            f'{AUDIT_COMMAND} --cleaned "$CLEANED"\n{AUDIT_COMMAND} --excluded "$WORK/excluded.csv"',
            ["--cleaned and --excluded together"],
            id="required-options-split-across-commands",
        ),
        pytest.param("No command here.", ["No documented script commands found"], id="no-commands"),
        pytest.param(f"Run `{INSPECT_COMMAND}`.", ["runs audit_clean.py"], id="no-audit-command"),
        pytest.param(
            f'Run `{VALID_AUDIT_COMMAND} > "$WORK/x.json" --ignored` and then '
            '`python3 -I "$WORK/clean.py" --ignored`.',
            [],
            id="ignore-redirect-tail-and-external-script",
        ),
        pytest.param(
            f'Run `{VALID_AUDIT_COMMAND}` and `{INSPECT_COMMAND} --not-an-inspector-option`.',
            ["inspect_data.py --help", "--not-an-inspector-option"],
            id="unknown-option-in-second-inline-command",
        ),
        pytest.param(
            f'{VALID_AUDIT_COMMAND}\npython3 -I "$SKILL_DIR/scripts/missing.py"',
            ["Missing script", "missing.py"],
            id="missing-script",
        ),
    ],
)
def test_check_commands(text, expected):
    failures = check_commands(text)
    if expected:
        details = "\n".join(failures)
        for message in expected:
            assert message in details
    else:
        assert failures == []


@pytest.mark.parametrize("redirect", [' > "$WORK/x.json"', '>>"$WORK/x.json"', ' | cat', ' 2>errors'])
def test_documented_script_commands_stops_at_shell_operators(redirect):
    text = f'Run `{INSPECT_COMMAND} --out "x > y.json"{redirect} --ignored`.'
    assert documented_script_commands(text) == [("inspect_data.py", ["$INPUT", "--out", "x > y.json"])]


def test_skill_documents_clean_outputs_and_lineage(skill_doc):
    patterns = {
        "cleaned_": r"cleaned_",
        "clean.py": r"(?<![\w.-])clean\.py(?![\w-]|\.\w)",
        "_source_row": r"(?<!\w)_source_row(?!\w)",
    }
    missing = [name for name, pattern in patterns.items() if not re.search(pattern, skill_doc)]
    assert not missing, f"Missing from SKILL.md: {', '.join(missing)}"


def skill_section(skill_doc, title, *, allow_suffix=False):
    title_pattern = r"[ \t]+".join(map(re.escape, title.split()))
    suffix = r"\b[^\n]*" if allow_suffix else r"(?:[ \t]+#+)?[ \t]*$"
    heading = re.search(rf"^ {{0,3}}##[ \t]+{title_pattern}{suffix}", skill_doc, re.I | re.M)
    assert heading, f"SKILL.md must have a level-2 {title} heading"
    body = re.split(r"^ {0,3}#{1,2}(?:[ \t]+|$)", skill_doc[heading.end() :], maxsplit=1, flags=re.M)[0]
    return heading.start(), body


def test_step_5_build_command_passes_plot_results_and_input(skill_doc):
    _, section = skill_section(skill_doc, "Step 5", allow_suffix=True)
    commands = [args for script, args in documented_script_commands(section) if script == "build_report.py"]
    required = {"--plot-results", "--input"}
    assert any(required <= {arg.split("=", 1)[0] for arg in args} for args in commands), (
        "Step 5 must pass --plot-results and --input together to build_report.py"
    )


def markdown_sentences(section):
    return re.split(
        r"(?<=[.!?])[`\"'’”\)\]]*\s+|\n[ \t]*(?:\n|[-+*][ \t]+|\d+[.)][ \t]+)",
        section,
    )


@pytest.mark.parametrize("terms", [
    pytest.param(("current working directory", "eda-work/", "next", "eda-work-2/"), id="work-folder"),
    pytest.param(("data folder", "home", "desktop", "system folder", "unwritable",
                  "ask once", "before", "documents"), id="ask-before-creation"),
    pytest.param(("windows", "`python3`", "`python`", "bash", "powershell"), id="windows"),
    pytest.param(("download", "output", "copy", "delivery/", "contents", "location", "final line"),
                 id="download-copy"),
])
def test_portable_setup_instructions(skill_doc, terms):
    _, setup = skill_section(skill_doc, "Setup")
    sentences = markdown_sentences(" ".join(setup.casefold().split()))
    assert any(all(term in sentence for term in terms) for sentence in sentences), terms


def test_portable_setup_removes_unspecified_location(skill_doc):
    assert "user-visible location" not in " ".join(skill_doc.casefold().split())


def test_portable_setup_word_budget(skill_doc):
    original_words = 3298
    assert len(skill_doc.split()) <= original_words + 60


def test_worked_micro_example_omits_eval_input_sequence(skill_doc):
    _, section = skill_section(skill_doc, "Worked micro-example")
    numbers = [Decimal(token) for token in re.findall(r"\b\d+(?:\.\d+)?\b", section)]
    eval_sequence = [20, 0, 0, 40]

    assert not any(
        numbers[index : index + len(eval_sequence)] == eval_sequence
        for index in range(len(numbers))
    ), "The worked example repeats the throughput evaluation input sequence"


def test_worked_micro_example_omits_eval_rate_pair(skill_doc):
    _, section = skill_section(skill_doc, "Worked micro-example")
    plain = re.sub(r"[*`]", "", section)
    rates = {
        Decimal(value)
        for value in re.findall(r"\b(\d+(?:\.\d+)?)\s+units\s*/\s*h\b", plain)
    }

    assert not {15, 20} <= rates, "The worked example repeats both throughput evaluation rates"


def test_worked_micro_example_compares_two_conditionally_labeled_denominators(skill_doc):
    _, section = skill_section(skill_doc, "Worked micro-example")
    number = r"(\d+(?:\.\d+)?)"
    pattern = re.compile(
        rf"\b(?:if|when)\s+([^,:\n]+)[,:].*?{number}\s*/\s*{number}\s*=\s*{number}",
        re.I,
    )
    candidates = [
        match.groups()
        for sentence in markdown_sentences(section)
        for match in pattern.finditer(re.sub(r"[*`]", "", sentence))
    ]
    assert len({label.strip().casefold() for label, *_ in candidates}) >= 2, (
        "Label each candidate calculation with its condition"
    )
    assert len({Decimal(denominator) for _, _, denominator, _ in candidates}) >= 2, (
        "Show calculations for two different denominators"
    )
    assert len({Decimal(value) for _, _, _, value in candidates}) >= 2, (
        "Show how the denominator choice changes the result"
    )
    for label, numerator, denominator, value in candidates:
        divisor = Decimal(denominator)
        assert divisor > 0, label
        result = Decimal(value)
        rounding_tolerance = Decimal("0.5").scaleb(result.as_tuple().exponent)
        assert abs(Decimal(numerator) / divisor - result) <= rounding_tolerance, label


def test_clean_step_says_audit_reuses_inspection_selection(skill_doc):
    _, section = skill_section(skill_doc, "Step 3", allow_suffix=True)

    assert any(
        re.search(r"\baudit(?:_clean\.py)?\b", sentence, re.I)
        and re.search(r"\bsame\b", sentence, re.I)
        and re.search(r"\b(?:inspection|selection)\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "Step 3 must say to pass the same inspection selection options to the audit"


def test_clean_step_documents_expansion_and_passthrough(skill_doc):
    _, section = skill_section(skill_doc, "Step 3", allow_suffix=True)

    assert "--expand" in section
    assert "--passthrough" in section


@pytest.mark.parametrize(("step", "instruction"), [
    pytest.param(3, "If the detail table is ready to use, skip this step without asking.", id="skip"),
    pytest.param(3, "Perform confirmed cleaning in `clean.py`.", id="clean-script"),
    pytest.param(4, "When you produce a cleaned CSV, analyze only that file after it passes the audit.",
                 id="audited-input"),
    pytest.param(3, "Apply each confirmed rule to every row it covers "
                    "(detail rows and report tables as well as denominators).", id="rule-scope"),
    pytest.param(3, "Keep identifiers as text, preserving leading zeros and trimming only surrounding "
                    "whitespace.", id="identifiers"),
    pytest.param(3, "Merge category labels only as the user confirmed.", id="categories"),
    pytest.param(3, "Before delivery, check the cleaned CSV for unparsed numeric text and total or "
                    "subtotal rows, unless the user confirmed keeping them.", id="delivery-check"),
])
def test_cleaning_principles(skill_doc, step, instruction):
    _, section = skill_section(skill_doc, f"Step {step}", allow_suffix=True)
    assert instruction in " ".join(section.split())


def test_skill_omits_audit_warning_handling(skill_doc):
    for sentence in markdown_sentences(skill_doc.lower()):
        assert not re.search(r"\bflagged\s+data\b", sentence), sentence
        if "audit_clean.py" in sentence:
            assert not re.search(r"\bwarnings?\b", sentence), sentence


def test_skill_word_limit(skill_doc):
    words_before_question_policy = 3332
    assert len(skill_doc.split()) < words_before_question_policy


def test_clean_step_says_to_neutralize_and_report_formula_cells(skill_doc):
    _, section = skill_section(skill_doc, "Step 3", allow_suffix=True)
    sentences = markdown_sentences(section)

    assert any(
        re.search(r"\bneutralize_formula\b", sentence)
        and re.search(r"\btext cells\b", sentence, re.I)
        and re.search(r"\bbefore writing\b.*\bcleaned CSV\b", sentence, re.I)
        for sentence in sentences
    ), "Step 3 must apply neutralize_formula to text cells before writing the cleaned CSV"
    assert any(
        re.search(r"\bformula\b", sentence, re.I)
        and re.search(r"\b(?:count|number)\b", sentence, re.I)
        and re.search(r"\bdelivery\b", sentence, re.I)
        for sentence in sentences
    ), "Step 3 must report the formula cell count in the delivery note"


def test_skill_documents_reusing_a_previous_analysis(skill_doc):
    reuse, section = skill_section(skill_doc, "Reuse a previous analysis")
    setup, _ = skill_section(skill_doc, "Setup")
    step_1, _ = skill_section(skill_doc, "Step 1", allow_suffix=True)
    assert setup < reuse < step_1, "Reuse a previous analysis must be between Setup and Step 1"
    assert re.search(r"\beda_summary\.json\b", section, re.I), "Reuse must mention eda_summary.json"
    assert re.search(r"\bstructure\b", section, re.I), "Reuse must mention structure"
    assert re.search(r"\bstart\s+(?:fresh|over)\b", section, re.I), "Reuse must offer a fresh start"

    assert any(
        re.search(r"(?<![\w.-])clean\.py(?![\w-]|\.\w)", sentence, re.I)
        and re.search(r"\b(?:never|(?:do\s+)?not)\s+run\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "Reuse must mention clean.py and the rule against running it in the same sentence"


def test_reuse_applies_shared_rules_to_new_values(skill_doc):
    _, section = skill_section(skill_doc, "Reuse a previous analysis")
    for term in ("new value", "shared rule", "recorded zero", "denominator"):
        assert term in section.casefold()


def test_methods_documents_same_population_for_numerator_and_denominator():
    methods = (SKILL_DIR / "references" / "methods.md").read_text(encoding="utf-8")
    _, section = skill_section(methods, "Summaries and requested metrics")
    expected = ("numerator", "denominator", "same", "zero")
    assert any(
        all(re.search(rf"\b{word}\b", sentence, re.I) for word in expected)
        for sentence in markdown_sentences(section)
    ), "The Summaries and requested metrics section must mention numerator, denominator, same, and zero in one sentence"


def test_report_documents_unrounded_metric_value():
    reference = (SKILL_DIR / "references" / "report.md").read_text(encoding="utf-8")
    assert any(
        re.search(r"\bunrounded\b", line, re.I) and re.search(r"\bvalue\b", line, re.I)
        for line in reference.splitlines()
    ), "report.md must mention unrounded and value on the same line"


def test_architecture_documents_relative_rate_tolerance():
    architecture = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    _, section = skill_section(architecture, "Stage contracts")
    tolerance_prose = "\n".join(
        paragraph for paragraph in re.split(r"\n\s*\n", section)
        if re.search(r"\btolerance\b", paragraph, re.I)
    )
    assert not re.search(
        r"\b(?:last|final)\s+decimal\b|\b(?:displayed|reported)\s+(?:decimal\s+places?|digits?)\b",
        tolerance_prose, re.I,
    ), "Rate tolerance must not depend on the displayed decimal places"
    assert re.search(r"\b1e-9\b", tolerance_prose, re.I), "Rate tolerance must specify 1e-9"


def test_skill_documents_plain_text_report_path_on_final_line(skill_doc):
    paragraphs = re.split(r"\n[ \t]*\n", skill_doc)
    assert any(
        re.search(r"\bplain\s+text\b", paragraph, re.I)
        and re.search(r"\bnot\s+a\s+markdown\s+link\b", paragraph, re.I)
        and any(
            re.search(r"\breport\.html\b", sentence, re.I)
            and re.search(r"\b(?:final|last)\s+line\b", sentence, re.I)
            for sentence in markdown_sentences(paragraph)
        )
        for paragraph in paragraphs
    ), "The paragraph putting report.html on the final line must say plain text and not a Markdown link"


def test_skill_documents_after_delivery(skill_doc):
    after_delivery, section = skill_section(skill_doc, "After delivery")
    step_5, _ = skill_section(skill_doc, "Step 5", allow_suffix=True)
    hard_rules, _ = skill_section(skill_doc, "Hard rules")
    assert step_5 < after_delivery < hard_rules, "After delivery must be between Step 5 and Hard rules"
    assert re.search(r"\bdelivery-2\b", section, re.I), "After delivery must mention delivery-2"
    assert re.search(r"\bambiguity\s+log\b", section, re.I), "After delivery must mention the ambiguity log"


def test_step_2_names_items_under_review(skill_doc):
    _, section = skill_section(skill_doc, "Step 2", allow_suffix=True)
    assert re.search(r"\bitems\s+under\s+review\b", section, re.I), "Step 2 must mention items under review"


@pytest.mark.parametrize("path", [
    SKILL_DIR / "SKILL.md", SKILL_DIR / "references" / "interview.md", REQUIREMENTS,
])
def test_question_policy_omits_superseded_instructions(path):
    document = " ".join(path.read_text(encoding="utf-8").casefold().split())
    for phrase in (
        "even after", "one change per turn", "three to six questions", "cover all eight items",
        "continue with any unasked open item", "audit all eight entries",
        "stop normally when all items are settled", "stop when every item has a status",
    ):
        assert phrase not in document


def test_interview_questions_depend_on_impact(skill_doc):
    _, section = skill_section(skill_doc, "Step 2", allow_suffix=True)
    sentences = markdown_sentences(section.casefold())
    assert any(all(term in s for term in ("only", "unresolved definition", "result", "decision"))
               for s in sentences)
    assert any(all(term in s for term in ("record", "unresolved", "proceed")) for s in sentences)
    assert any(all(term in s for term in ("internal", "eight", "ambiguity log")) for s in sentences)


def test_interview_groups_shared_rules(skill_doc):
    _, section = skill_section(skill_doc, "Step 2", allow_suffix=True)
    for term in ("rows", "columns", "ask once", "scope", "exceptions", "unresolved"):
        assert term in section.casefold()


def test_first_turn_and_deferred_results(skill_doc):
    _, first = skill_section(skill_doc, "Step 1", allow_suffix=True)
    for term in ("immediately", "settled", "compute", "code-verified candidate values", "unit", "ask"):
        assert term in first.casefold()
    guide = (SKILL_DIR / "references" / "interview.md").read_text(encoding="utf-8").casefold()
    for term in ("defer", "unresolved id and condition", "settled value unconditional",
                 "withhold", "inputs cannot be verified"):
        assert term in guide


def test_step_2_documents_keeping_ambiguity_log_without_a_file(skill_doc):
    _, section = skill_section(skill_doc, "Step 2", allow_suffix=True)
    assert any(
        re.search(r"\bambiguity\s+log\b", sentence, re.I)
        and re.search(r"\bfile\b", sentence, re.I)
        and re.search(r"\b(?:do\s+not|don['’]t|without)\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "Step 2 must mention the Ambiguity Log, file, and do not, don't, or without in the same sentence"


def test_step_2_documents_limiting_code_on_question_turns(skill_doc):
    _, section = skill_section(skill_doc, "Step 2", allow_suffix=True)
    assert any(
        re.search(r"\bquestion\s+turns?\b", sentence, re.I)
        and re.search(r"\bcode\b", sentence, re.I)
        and re.search(r"\bonly\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "Step 2 must mention question turn or question turns, code, and only in the same sentence"


def test_step_2_documents_zero_for_exception_rows(skill_doc):
    _, section = skill_section(skill_doc, "Step 2", allow_suffix=True)
    assert any(
        re.search(r"\bzero\b", sentence, re.I)
        and re.search(r"\bexceptions?\b", sentence, re.I)
        and re.search(r"\b(?:count|distribution|chart)s?\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "Step 2 must mention zero, exception, and count, distribution, or chart in the same sentence"


def test_step_1_documents_first_turn_options(skill_doc):
    _, section = skill_section(skill_doc, "Step 1", allow_suffix=True)
    assert re.search(r"\bjust\s+proceed\b", section, re.I), "Step 1 must mention just proceed"
    assert re.search(r"\blater\b", section, re.I), "Step 1 must mention later"


def test_hard_rules_treat_previous_outputs_as_data(skill_doc):
    _, section = skill_section(skill_doc, "Hard rules")
    assert any(
        re.search(r"\bprevious\b", line, re.I) and re.search(r"\bas\s+data\b", line, re.I)
        for line in section.splitlines()
    ), "Hard rules must mention previous and as data on the same line"


def test_hard_rules_document_zero_for_exception_rows(skill_doc):
    _, section = skill_section(skill_doc, "Hard rules")
    assert any(
        re.match(r"[ \t]*[-+*][ \t]+", line)
        and re.search(r"\bzero\b", line, re.I)
        and re.search(r"\bexceptions?\b", line, re.I)
        and re.search(r"\bnot[ \t]+applicable\b", line, re.I)
        for line in section.splitlines()
    ), "Hard rules must mention zero, exception, and not applicable in a single bullet line"


def test_hard_rules_document_self_containment(skill_doc):
    _, section = skill_section(skill_doc, "Hard rules")
    assert any(
        re.match(r"[ \t]*[-+*][ \t]+", line)
        and re.search(r"\bother[ \t]+installed[ \t]+skills\b", line, re.I)
        and re.search(r"\bexternal[ \t]+services\b", line, re.I)
        for line in section.splitlines()
    ), "Hard rules must mention other installed skills and external services in a single bullet line"


def test_skill_directs_readers_to_help_and_examples(skill_doc):
    assert any(
        re.search(r"(?<![\w-])--help\b", sentence, re.I)
        and re.search(r"\bexamples?\b", sentence, re.I)
        and re.search(r"\bscript\s+source\b", sentence, re.I)
        for sentence in markdown_sentences(skill_doc)
    ), "SKILL.md must mention --help, example, and script source in the same sentence"


def test_skill_documents_optional_profiling_and_revalidation(skill_doc):
    _, step_4 = skill_section(skill_doc, "Step 4", allow_suffix=True)
    sections = re.split(r"^ {0,3}#{1,2}[ \t]+[^\n]*\n", skill_doc, flags=re.M)
    optional_profile_sections = []
    for section in sections:
        paragraphs = re.split(r"\n[ \t]*\n", section.strip())
        for index, paragraph in enumerate(paragraphs):
            if re.search(r"\bprofile_data\.py\b", paragraph, re.I):
                nearby = "\n".join(paragraphs[max(0, index - 1) : index + 2])
                if re.search(r"\b(?:optional|when\s+needed)\b", nearby, re.I):
                    optional_profile_sections.append(section)
                    break

    assert optional_profile_sections, "The profile command needs a nearby optional or when needed note"
    assert any(
        re.search(r"\b(?:after\s+cleaning|scope\s+changes)\b", sentence, re.I)
        and re.search(
            r"\b(?:re[- ]?(?:validat|check|run)\w*|verify|validat\w*|checks?|audit\w*|repeat)\b",
            sentence, re.I,
        )
        for section in [*optional_profile_sections, step_4]
        for sentence in markdown_sentences(section)
    ), "The profile section or Step 4 must require revalidation after cleaning or scope changes"


def test_step_4_documents_default_chart_count_and_raw_chart(skill_doc):
    _, section = skill_section(skill_doc, "Step 4", allow_suffix=True)
    chart_sentences = [
        sentence for sentence in markdown_sentences(section)
        if re.search(r"\b(?:charts?|figures?|plots?)\b", sentence, re.I)
    ]
    assert any(re.search(r"\braw\b", sentence, re.I) for sentence in chart_sentences), (
        "Step 4 must retain the raw-data figure"
    )
    assert any(
        re.search(r"\b(?:2\s*–\s*4|two\s+to\s+four)\b", sentence, re.I)
        and re.search(r"\b(?:default|typically|usually|normally|start\s+with|aim\s+for|use)\b", sentence, re.I)
        for sentence in chart_sentences
    ), "Step 4 must document a default of 2–4 charts"


def test_step_4_documents_same_axis_chart_for_headline_comparison(skill_doc):
    _, section = skill_section(skill_doc, "Step 4", allow_suffix=True)
    assert any(
        re.search(r"\b(?:headline|requested\s+comparison)\b", sentence, re.I)
        and re.search(r"\bsame\s+axis\b", sentence, re.I)
        and re.search(r"\b(?:chart|figure)\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "Step 4 must mention headline or requested comparison, same axis, and chart or figure in one sentence"


def test_step_4_documents_that_quality_is_always_required(skill_doc):
    _, section = skill_section(skill_doc, "Step 4", allow_suffix=True)
    assert any(
        re.search(r"\bquality\b", sentence, re.I) and re.search(r"\balways\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "Step 4 must say to always perform the quality stage"


def test_step_5_documents_evidence_writing_style(skill_doc):
    _, section = skill_section(skill_doc, "Step 5", allow_suffix=True)
    paragraphs = re.split(r"\n[ \t]*\n", section)
    assert any(
        re.search(r"\bsources?\b", paragraph, re.I)
        and re.search(r"\bmeta\b", paragraph, re.I)
        and re.search(r"\bevidence\b", paragraph, re.I)
        for paragraph in paragraphs
    ), "Step 5 must mention source or sources, meta, and evidence in the same paragraph"


def test_step_5_documents_both_report_tabs_and_summary_fields(skill_doc):
    _, section = skill_section(skill_doc, "Step 5", allow_suffix=True)
    expected = ("summary tab", "details tab", "headline", "insights")
    missing = [term for term in expected
               if not re.search(r"\b" + r"\s+".join(map(re.escape, term.split())) + r"\b", section, re.I)]
    assert not missing, f"Missing from SKILL.md Step 5: {', '.join(missing)}"


def test_step_5_says_to_avoid_repeating_facts(skill_doc):
    _, section = skill_section(skill_doc, "Step 5", allow_suffix=True)
    assert any(
        re.search(r"\brepeat(?:ing|ed|s)?\b", sentence, re.I)
        and re.search(r"\b(?:avoid|never|not|without)\b|\bdon['’]t\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "SKILL.md Step 5 must say to avoid repeating facts"


def test_step_5_keeps_the_five_to_eight_line_chat_handoff(skill_doc):
    _, section = skill_section(skill_doc, "Step 5", allow_suffix=True)
    assert any(
        re.search(r"\bchat\b", sentence, re.I)
        and re.search(r"(?:\b5\s*[-–—]\s*8|\bfive\s+to\s+eight)\s+lines\b", sentence, re.I)
        for sentence in markdown_sentences(section)
    ), "SKILL.md Step 5 must keep the 5–8 line chat handoff"


def test_report_guide_documents_both_tabs():
    guide = (SKILL_DIR / "references" / "report.md").read_text(encoding="utf-8")
    for tab in ("summary", "details"):
        assert re.search(rf"\b{tab}\s+tab\b", guide, re.I), f"Report guide must describe the {tab} tab"


def test_report_design_documents_the_template_rules():
    path = SKILL_DIR / "templates" / "DESIGN.md"
    assert path.is_file(), "Report template must have a DESIGN.md"
    design = path.read_text(encoding="utf-8")
    lines = design.splitlines()
    assert len(lines) <= 60
    headings = {heading.strip().casefold(): body for heading, body in re.findall(
        r"^#{1,6}[ \t]+([^\n]+)\n(.*?)(?=^#{1,6}[ \t]+|\Z)", design, re.M | re.S
    )}
    required = {"type scale", "spacing", "color tokens", "contrast", "interaction", "print"}
    assert required <= headings.keys(), f"Missing design sections: {sorted(required - headings.keys())}"
    for control in ("tab", "toggle", "zoom"):
        assert re.search(rf"\b{control}s?\b", headings["interaction"], re.I), f"Document the {control} behavior"
    assert any("Impeccable" in line and "Apache-2.0" in line for line in lines)


def test_skill_documents_missing_glyphs_for_fonts(skill_doc):
    assert any(
        re.search(r"\bmissing_glyphs\b", sentence, re.I)
        and re.search(r"\bfont\b", sentence, re.I)
        for sentence in markdown_sentences(skill_doc)
    ), "SKILL.md must mention missing_glyphs and font in the same sentence"


def test_readme_documents_korean_chart_font_requirement():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert any(
        re.search(r"\bKorean\b", line, re.I) and re.search(r"\bfont\b", line, re.I)
        for line in readme.splitlines()
    ), "README.md must mention Korean and font on the same line"


def test_cleaning_reference_pattern_table():
    reference = SKILL_DIR / "references" / "cleaning.md"
    assert reference.is_file(), "references/cleaning.md is missing"
    lines = reference.read_text(encoding="utf-8").splitlines()

    def cells(line):
        content = line.strip().removeprefix("|")
        content = re.sub(r"(?<!\\)\|$", "", content)
        return [cell.strip() for cell in re.split(r"(?<!\\)\|", content)]

    for index, line in enumerate(lines[:-1]):
        headings = cells(line.casefold())
        separators = cells(lines[index + 1])
        if len(headings) != len(separators) or not all(
            re.fullmatch(r":?-+:?", separator) for separator in separators
        ):
            continue
        questions = [i for i, heading in enumerate(headings) if re.search(r"\bquestion\b|질문", heading)]
        code = [i for i, heading in enumerate(headings) if re.search(r"\bcode\b|코드", heading)]
        if questions and code:
            break
    else:
        pytest.fail("cleaning.md must have a Markdown table with question and code columns")

    rows = []
    for line in lines[index + 2 :]:
        if not line.strip() or "|" not in line:
            break
        rows.append(cells(line))

    assert 1 <= len(rows) <= 8, f"Expected 1–8 cleaning patterns, found {len(rows)}"
    for row_number, row in enumerate(rows, start=1):
        assert len(row) == len(headings), f"Pattern row {row_number} has the wrong number of cells"
        assert row[questions[0]], f"Pattern row {row_number} has no question"
        assert re.search(r"`+[^`]*[^`\s][^`]*`+", row[code[0]]), (
            f"Pattern row {row_number} must contain nonempty backticked code"
        )


def test_cleaning_reference_lists_duplicate_and_implausible_patterns():
    reference = (SKILL_DIR / "references" / "cleaning.md").read_text(encoding="utf-8")
    table = re.search(
        r"^\|[ \t]*Pattern[ \t]*\|[^\n]*\n"
        r"^\|(?:[ \t]*:?-+:?[ \t]*\|)+[ \t]*\n"
        r"(?P<rows>(?:^\|[^\n]*\|[ \t]*(?:\n|$))*)",
        reference,
        re.I | re.M,
    )
    assert table, "cleaning.md must have a Markdown pattern table"

    rows = table["rows"].splitlines()
    matches = {
        keyword: {index for index, row in enumerate(rows) if re.search(rf"\b{keyword}\b", row, re.I)}
        for keyword in ("duplicate", "implausible")
    }
    missing = [keyword for keyword, matching_rows in matches.items() if not matching_rows]
    assert not missing, f"Missing cleaning pattern rows: {', '.join(missing)}"
    assert len(matches["duplicate"] | matches["implausible"]) >= 2, (
        "Duplicate and implausible values must have separate pattern rows"
    )


def test_clean_step_itemizes_result_changing_actions(skill_doc):
    _, section = skill_section(skill_doc, "Step 3", allow_suffix=True)
    plan = section.casefold().split("perform confirmed cleaning")[0]
    for term in ("numbered", "each", "unit conversion", "`-`", "`n/a`", "subtotal", "total",
                 "duplicate", "implausible", "category"):
        assert term in plan


def test_clean_step_honors_approval_of_list(skill_doc):
    _, section = skill_section(skill_doc, "Step 3", allow_suffix=True)
    sentences = markdown_sentences(section.casefold())
    assert any(all(term in s for term in ("all", "explicit list", "apply")) for s in sentences)
    assert any(all(term in s for term in ("only", "new change", "scope")) for s in sentences)


def test_skill_references_list_links_cleaning_guide(skill_doc):
    heading = re.search(r"^(#{1,6})[ \t]+References[ \t]*#*[ \t]*$", skill_doc, re.M)
    assert heading, "SKILL.md must have a References heading"
    level = len(heading.group(1))
    section = re.split(rf"^#{{1,{level}}}[ \t]+", skill_doc[heading.end() :], maxsplit=1, flags=re.M)[0]
    assert re.search(r"^[ \t]*[-+*][ \t]+.*\[[^\]\n]+\]\((?:\./)?references/cleaning\.md\)", section, re.M), (
        "The References list must link to references/cleaning.md"
    )


def test_requirements_do_not_prohibit_automatic_repairs():
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    assert not re.search(r"\bautomatic\s+repairs\s+are\s+prohibited\b", requirements, re.I), (
        'docs/requirements.md still says "automatic repairs are prohibited"'
    )


def public_text_files(root):
    tracked_extensions = {".md", ".py", ".json", ".yaml", ".yml", ".txt", ".toml", ".cfg", ".sh", ".html"}
    skill_extensions = {".md", ".rst", ".txt", ".html", ".json", ".yaml", ".yml"}
    tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root)
    paths = {root / os.fsdecode(name) for name in tracked.split(b"\0") if name}
    paths = {
        path for path in paths
        if path.suffix.lower() in tracked_extensions
        or (path.suffix.lower() == ".csv" and path.is_relative_to(root / "docs"))
    }
    paths.update(
        path for path in (root / "skills").rglob("*")
        if path.suffix.lower() in skill_extensions
    )
    paths.add(root / "docs" / "requirements.md")
    return sorted(path for path in paths if path.is_file())


# Each pair is a normalized character count and a SHA-256 digest of UTF-8 text.
FORBIDDEN_TERM_DIGESTS = (
    (4, "50ccd96dbaff55f76d2bcc9354c14cd0fc2c38d53b7fa8d2fc5f0e4e2fce1844"),
    (3, "f9e8b5fe56a7d8b81f4605274754daeae77a56d27f4548c7d8faf4228edc2505"),
    (10, "5fbad86bc48f2cae99e0a70733dd2c7a1adcf96fd5af9b0677989f654b4b9621"),
    (6, "334176732914de97dcef8b8150f1a70f386a74ec8d49a137a16e93d0076689a7"),
    (2, "53636f085f1a8b76ba97dcfa7665a026bea610eccd9394e6564abc9be735ed7b"),
    (7, "6bc636ff0103a2888fb38ca3c2bf3b1371110ceac5a104a519d85d39207732b0"),
    (7, "4165965349f1e2225982e25a4d45809c30008888263b156f09761e8248d37ec9"),
)

HTML_DATA_URI = re.compile(
    # Quoted base64 values can wrap across source lines.
    r'''(?P<quote>["'])data:[^,\s"'<>]*;base64,[a-z0-9+/=%\s]*'''
    r'''(?:[?#][^"'\s)<>]*)?(?P=quote)|data:[^"'\s)<>]+''',
    re.I,
)


def forbidden_term_locations(root, paths):
    digests_by_length = {}
    for length, digest in FORBIDDEN_TERM_DIGESTS:
        digests_by_length.setdefault(length, set()).add(bytes.fromhex(digest))

    hits = []
    for path in paths:
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".html":
            # Keep line numbers and prevent matches across the removed URI.
            text = HTML_DATA_URI.sub(lambda match: " " + "\n" * match[0].count("\n"), text)
        lines = normalize("NFC", text.lower()).split("\n")
        for line_number, line in enumerate(lines, start=1):
            if any(
                sha256(line[start:start + length].encode("utf-8")).digest() in digests
                for length, digests in digests_by_length.items()
                for start in range(len(line) - length + 1)
            ):
                hits.append(f"{path.relative_to(root)}:{line_number}")
    return hits


def test_public_docs_have_no_forbidden_terms():
    hits = forbidden_term_locations(ROOT, public_text_files(ROOT))
    if hits:
        pytest.fail("\n".join(hits), pytrace=False)


def test_forbidden_term_scan_includes_published_csv_files():
    published_csvs = set((ROOT / "docs").rglob("*.csv"))
    assert published_csvs
    assert published_csvs <= set(public_text_files(ROOT))


def test_forbidden_term_scan_normalizes_unicode_and_reports_location(tmp_path):
    term = bytes.fromhex("eb8db0ec9db4ec9b90").decode("utf-8")
    path = tmp_path / "sample.txt"
    path.write_text(f"first line\n{normalize('NFD', term)}\n", encoding="utf-8")

    assert forbidden_term_locations(tmp_path, [path]) == ["sample.txt:2"]


def test_forbidden_term_scan_skips_html_base64_and_preserves_lines(tmp_path):
    term = bytes.fromhex("41494345").decode("ascii").upper()
    path = tmp_path / "sample.html"
    path.write_text(
        f'<img src="data:image/png;base64,AAAA\n{term}AAAA">\n<p>{term}</p>\n',
        encoding="utf-8",
    )

    assert forbidden_term_locations(tmp_path, [path]) == ["sample.html:3"]


def test_forbidden_term_scan_skips_data_uris_in_html_attributes_and_css(tmp_path):
    term = "AI" + "CE"
    uri = f"data:image/png;base64,AAAA{term}AAAA#{term}"
    path = tmp_path / "sample.html"
    path.write_text(
        f'<img src="{uri}">\n'
        f'<style>.icon {{ background: url({uri}); }}</style>\n'
        f'<img srcset="{uri} 1x,\n'
        f'  /images/{term}.png 2x">\n'
        f'<a href="data:text/plain,{term}">Preview</a>\n'
        f'<p>{term}</p>\n',
        encoding="utf-8",
    )

    assert forbidden_term_locations(tmp_path, [path]) == ["sample.html:4", "sample.html:6"]


def test_skill_frontmatter_and_body_limits(skill_doc):
    frontmatter = re.match(r"\A---\n(?P<fields>.*?)\n---[ \t]*(?:\n|$)", skill_doc, re.S)
    assert frontmatter, "SKILL.md must start with a frontmatter block delimited by ---"
    fields = {}
    for line in frontmatter["fields"].splitlines():
        field = re.fullmatch(r"([a-z][a-z0-9_-]*):[ \t]+(.+)", line)
        assert field, f"Invalid frontmatter field: {line!r}"
        key, value = field.groups()
        assert key not in fields, f"Duplicate frontmatter field: {key}"
        value = re.split(r"\s+#", value.strip(), maxsplit=1)[0].rstrip()
        assert value and not re.search(r"^[!&*{}\[\],#|>@`%\"']|^[-?:](?:\s|$)|:(?:\s|$)", value), (
            f"Expected a plain, single-line scalar for frontmatter field {key}"
        )
        fields[key] = value

    description = fields.get("description", "")
    assert 0 < len(description) <= 200, f"Expected a 1–200 character description, found {len(description)}"
    body_lines = len(skill_doc[frontmatter.end() :].splitlines())
    assert body_lines <= 300, f"Expected at most 300 body lines, found {body_lines}"
