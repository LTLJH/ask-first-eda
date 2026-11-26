"""Summarize EDA runs by condition and optional case group."""

import argparse
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from glob import escape as glob_escape, glob, has_magic
import getpass
from html import escape
import json
import math
import os
from pathlib import Path
import re
import shlex
from statistics import median
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent))
from grade_run import numeric_verdict
from numeric_check import DATE_SCOPE, HTML_PATTERNS, NUMBER, artifact_paths, is_date_mention
from run_case import CONDITIONS, ROOT


MISSING = "—"
COLUMNS = (
    "Overall", "Numbers verdict", "Critical failures", "Mismatched", "Analyst questions",
    "Turns", "Wall time (s)", "Tokens", "Report", "Charts",
)
ANALYST_COST_COLUMNS = {
    "commands": "Commands", "input_tokens": "Input", "cached_input_tokens": "Cached input",
    "uncached_input_tokens": "Uncached input", "output_tokens": "Output",
    "analyst_seconds": "Analyst time (s)", "source_reads": "Source reads",
}
CLEANING_STATUSES = ("pass", "review", "fail", "incomplete", "not_applicable", MISSING)
CONDITION_COLUMNS = (
    "Condition", "Runs", "Numeric pass / review / fail", "Complete", "Analyst turns",
    "Question turns", "Median first result turn", "Wall time (s)",
    "Uncached input + output tokens", "Commands", "Cleaning status", "Unsupported assumptions",
)
SOURCE_READERS = {"cat", "sed", "head", "tail", "less", "nl", "rg", "grep", "awk", "bat", "more"}
PATTERN_READERS = {"sed", "rg", "grep", "awk"}
SKILL_SCRIPT = re.compile(r"(?:^|/)(?:ask-first-eda|eda-skill)/scripts/[^/]+\.py\Z")
ANALYST_LOG = re.compile(r"[0-9]{2,}-analyst\.jsonl")
RESULT_NUMBER = re.compile(rf"(?<![a-zA-Z0-9_.,])(?:{NUMBER}|[+-]?\.\d+(?:[eE][+-]?\d+)?)(?![\d_]|[.,]\d)")


def read_object(path):
    if not path.is_file() or path.is_symlink():
        return {}
    with path.open(encoding="utf-8") as stream:
        value = json.load(stream)
    return value if isinstance(value, dict) else {}


def events(path):
    if not path.is_file() or path.is_symlink():
        return
    with path.open(encoding="utf-8", errors="replace") as stream:
        for line in stream:
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                yield value


def count_tokens(run):
    totals = []
    for path in sorted((run / "raw").rglob("*.jsonl")):
        log_totals = []
        for event in events(path):
            if event.get("type") not in ("turn.completed", "usage", "result"):
                continue
            usage = event.get("usage", event)
            if not isinstance(usage, dict):
                continue
            total = usage.get("total_tokens")
            if type(total) is not int or total < 0:
                parts = [usage.get(key) for key in ("input_tokens", "output_tokens")]
                if event.get("type") == "result":
                    parts.extend(usage.get(key, 0) for key in
                                 ("cache_creation_input_tokens", "cache_read_input_tokens"))
                if any(type(part) is not int or part < 0 for part in parts):
                    continue
                # Codex cached input tokens are already included in input_tokens.
                total = sum(parts)
            if event.get("type") == "result":
                # A Claude result's usage is cumulative for that invocation.
                log_totals = [total]
                break
            log_totals.append(total)
        totals.extend(log_totals)
    return sum(totals) if totals else MISSING


def reads_skill_source(command):
    if not isinstance(command, str):
        return False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
        lexer.whitespace = " \t\r"
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return False

    segment = []
    for word in (*words, ";"):
        if not re.fullmatch(r"[();|&\n]+", word):
            segment.append(word)
            continue
        if segment:
            program, *args = segment
            program = Path(program).name
            if (program in {"sh", "bash", "zsh"} and len(args) >= 2 and args[0] in {"-c", "-lc", "-cl"}
                    and reads_skill_source(args[1])):
                return True
            if program in SOURCE_READERS and "--help" not in args:
                operands = [arg for arg in args if not arg.startswith("-")]
                if program in PATTERN_READERS and not any(arg.startswith("--regexp=") for arg in args):
                    operands = operands[1:]
                if any(SKILL_SCRIPT.search(arg) for arg in operands):
                    return True
        segment.clear()
    return False


def analyst_metrics(run):
    metrics = dict.fromkeys(ANALYST_COST_COLUMNS, 0)
    for path in sorted((run / "raw").glob("*-analyst.jsonl")):
        if not ANALYST_LOG.fullmatch(path.name):
            continue
        seen_commands = set()
        for event in events(path):
            if event.get("type") == "turn.completed":
                usage = event.get("usage")
                if isinstance(usage, dict):
                    for key in ("input_tokens", "cached_input_tokens", "output_tokens"):
                        value = usage.get(key)
                        if type(value) is int and value >= 0:
                            metrics[key] += value
            elif event.get("type") == "item.completed":
                item = event.get("item")
                if not isinstance(item, dict) or item.get("type") != "command_execution":
                    continue
                item_id = item.get("id")
                if isinstance(item_id, str):
                    if item_id in seen_commands:
                        continue
                    seen_commands.add(item_id)
                metrics["commands"] += 1
                metrics["source_reads"] += int(reads_skill_source(item.get("command")))

    metrics["uncached_input_tokens"] = metrics["input_tokens"] - metrics["cached_input_tokens"]
    for message in events(run / "transcript.jsonl"):
        duration = message.get("duration_s")
        if message.get("speaker") == "analyst" and type(duration) in (int, float) and 0 <= duration < math.inf:
            metrics["analyst_seconds"] += duration
    return metrics


def safe_label(value, usernames):
    if (not isinstance(value, str) or not value.strip() or not value.isprintable()
            or "/" in value or "\\" in value):
        return MISSING
    for username in usernames:
        value = re.sub(rf"(?<![^\W_]){re.escape(username)}(?![^\W_])",
                       "[redacted]", value, flags=re.IGNORECASE)
    return escape(value).replace("|", "&#124;").replace("`", "&#96;").replace("[", "&#91;")


def verdict(value):
    return value if value in ("pass", "fail", "review", "skipped", "not_applicable", "unverified") else MISSING


def list_count(value):
    return len(value) if isinstance(value, list) else MISSING


def result_values(numeric):
    values = set()
    for bucket in ("matched", "mismatched"):
        entries = numeric.get(bucket)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            actual = entry.get("actual")
            value = actual.get("value") if isinstance(actual, dict) else actual
            items = value if isinstance(value, list) else [value]
            for item in items:
                if type(item) in (int, float):
                    number = Decimal(str(item))
                    if number.is_finite():
                        values.add(number)
    return values


def mentions_result(message, values):
    text = DATE_SCOPE.sub(lambda match: " " if is_date_mention(match) else match[0], message)
    for token in RESULT_NUMBER.finditer(text.replace("−", "-")):
        try:
            number = Decimal(token[0].replace(",", ""))
        except InvalidOperation:
            continue
        if number in values:
            return True
    return False


def summarize(run):
    meta = read_object(run / "meta.json")
    grade = read_object(run / "grade.json")
    numeric = read_object(run / "numeric_check.json")
    transcript = run / "transcript.jsonl"
    analyst_turns = set()
    questions = set()
    first_result = MISSING
    values = result_values(numeric)
    for index, event in enumerate(events(transcript)):
        if event.get("speaker") != "analyst":
            continue
        turn = event.get("turn")
        key = ("turn", turn) if type(turn) is int else ("message", index)
        analyst_turns.add(key)
        message = event.get("text")
        if not isinstance(message, str):
            continue
        if any(mark in message[-400:] for mark in "?？"):
            questions.add(key)
        if values and first_result == MISSING and mentions_result(message, values):
            first_result = turn if type(turn) is int else len(analyst_turns)

    reports = artifact_paths(run, HTML_PATTERNS[0]) or artifact_paths(run, HTML_PATTERNS[1])
    primary = run / "eda_summary.json"
    summaries = artifact_paths(run, "eda_summary.json")
    summary = (read_object(primary) if primary in summaries
               else read_object(summaries[0]) if len(summaries) == 1 else {})
    turns = meta.get("turns")
    turns = turns if type(turns) is int and turns >= 0 else len(analyst_turns)
    wall_time = meta.get("wall_time_s")
    wall_time = wall_time if type(wall_time) in (int, float) and 0 <= wall_time < math.inf else MISSING
    question_turns = len(questions) if transcript.is_file() and not transcript.is_symlink() else MISSING
    legacy = (
        verdict(grade.get("overall")),
        verdict(grade.get("numbers_verdict")),
        list_count(grade.get("critical_failures")),
        list_count(numeric.get("mismatched")),
        question_turns,
        turns,
        wall_time,
        count_tokens(run),
        "yes" if reports else "no",
        list_count(summary.get("charts")),
    )
    cleaning = read_object(run / "cleaning_check.json").get("status")
    assumptions = grade.get("unsupported_assumptions")
    cost = analyst_metrics(run)
    has_numeric_check = all(isinstance(numeric.get(bucket), list)
                            for bucket in ("missing", "mismatched", "unparsed", "unverified"))
    outcome = {
        "numeric": numeric_verdict(numeric, [])[0] if has_numeric_check else MISSING,
        "complete": bool(any(report.name == "report.html" for report in reports)
                         and (summaries or artifact_paths(run, "results.json"))),
        "turns": turns,
        "questions": question_turns,
        "first_result": first_result,
        "wall_time": wall_time,
        "tokens": cost["uncached_input_tokens"] + cost["output_tokens"],
        "commands": cost["commands"],
        "cleaning": cleaning if cleaning in CLEANING_STATUSES else MISSING,
        "assumptions": assumptions if type(assumptions) is int and assumptions >= 0 else MISSING,
    }
    return meta, legacy, cost, outcome


def table_row(values):
    return "| " + " | ".join(map(str, values)) + " |"


def condition_table(title, outcomes):
    lines = ["", f"## {title}", "", table_row(CONDITION_COLUMNS),
             table_row(["---"] * len(CONDITION_COLUMNS))]
    for condition in CONDITIONS:
        rows = [outcome for label, outcome in outcomes if label == condition]
        if not rows:
            continue

        def recorded(key):
            return [row[key] for row in rows if row[key] != MISSING]

        def total(key):
            values = recorded(key)
            return sum(values) if values else MISSING

        verdicts = Counter(row["numeric"] for row in rows)
        counts = " / ".join(str(verdicts[status]) for status in ("pass", "review", "fail"))
        completed = sum(row["complete"] for row in rows)
        completion = f"{completed}/{len(rows)} ({completed / len(rows):.1%})"
        first_results = recorded("first_result")
        wall_time = total("wall_time")
        cleaning = Counter(row["cleaning"] for row in rows)
        lines.append(table_row((
            condition, len(rows), counts, completion, total("turns"), total("questions"),
            f"{median(first_results):g}" if first_results else MISSING,
            f"{wall_time:.6f}".rstrip("0").rstrip(".") if wall_time != MISSING else MISSING,
            total("tokens"), total("commands"),
            ", ".join(f"{status} {cleaning[status]}" for status in CLEANING_STATUSES if cleaning[status]),
            total("assumptions"),
        )))
    lines.extend([
        "",
        "A question turn has a `?` or `？` within the last 400 characters of an analyst message.",
        "The first result turn is the first analyst turn containing a numeric value from a matched "
        "or mismatched metric's actual value. The median uses runs with a recorded first result.",
        "Numeric counts come from `numeric_check.json`. Runs without a numeric check show `—` in Run outcomes.",
        "Completion requires both `report.html` and a JSON artifact (`eda_summary.json` or `results.json`).",
        "Time, turns, tokens, commands, and unsupported assumptions are summed across recorded values. "
        "Token and command counts cover analyst logs.",
    ])
    return lines


def render(runs, groups=(), *, anonymize=False):
    usernames = {name for name in (Path.home().name, getpass.getuser(), os.getenv("USER"),
                                  os.getenv("LOGNAME"), os.getenv("USERNAME")) if name}
    lines = [
        "# EDA A/B/C summary", "",
        table_row(("Run ID", "Case", "Flow", "Condition", *COLUMNS)),
        table_row(["---"] * (4 + len(COLUMNS))),
    ]
    cost_columns = ("Run ID", "Case", "Flow", "Condition", *ANALYST_COST_COLUMNS.values())
    cost_lines = ["", "## Analyst cost", "", table_row(cost_columns), table_row(["---"] * len(cost_columns))]
    outcome_columns = ("Run ID", "Case", "Flow", "Condition", "Numeric verdict", "Complete",
                       "First result turn", "Cleaning status", "Unsupported assumptions")
    outcome_lines = ["", "## Run outcomes", "", table_row(outcome_columns),
                     table_row(["---"] * len(outcome_columns))]
    pairs = defaultdict(lambda: {"skill": [], "noskill": []})
    outcomes = {}
    cases = {}
    for index, run in enumerate(runs, 1):
        meta, values, cost, outcome = summarize(run)
        raw_case = meta.get("case")
        source = meta.get("case_dir")
        if not isinstance(source, str) or not source:
            source = f"evals/cases/{raw_case}"
        identity = os.path.normpath(ROOT / source)
        if anonymize:
            run_id = f"R{index:02}"
            case = cases.setdefault(identity, f"case-{len(cases) + 1}")
        else:
            run_id = safe_label(run.resolve().name, usernames)
            case = safe_label(raw_case, usernames)
        flow = meta.get("flow")
        condition = meta.get("condition")
        flow = flow if flow in ("A", "B", "C") else MISSING
        condition = condition if condition in CONDITIONS else MISSING
        labels = (run_id, case, flow, condition)
        lines.append(table_row((*labels, *values)))
        cost_lines.append(table_row((*labels, *(cost[key] for key in ANALYST_COST_COLUMNS))))
        outcome_lines.append(table_row((
            *labels, outcome["numeric"], "yes" if outcome["complete"] else "no",
            outcome["first_result"], outcome["cleaning"], outcome["assumptions"],
        )))
        outcomes[run] = condition, outcome
        if case != MISSING and flow != MISSING and condition in ("skill", "noskill"):
            pairs[case, flow, identity][condition].append((run_id, *values))

    lines.extend(cost_lines)
    if outcomes and all(condition != "prompted" for condition, _ in outcomes.values()):
        lines.extend(pair_table(pairs))
    lines.extend(outcome_lines)
    lines.extend(condition_table("All runs by condition", outcomes.values()))
    for title, pattern in groups:
        lines.extend(condition_table(title, group_outcomes(outcomes, pattern)))
    return "\n".join(lines) + "\n"


def pair_table(pairs):
    lines = [
        "", "## Skill vs noskill", "",
        "Each comparison shows skill / noskill. Commas separate repeated runs.", "",
        table_row(("Case", "Flow", "Skill run IDs", "Noskill run IDs", *COLUMNS)),
        table_row(["---"] * (4 + len(COLUMNS))),
    ]
    for (case, flow, _), runs_by_condition in sorted(pairs.items()):
        skill, noskill = runs_by_condition["skill"], runs_by_condition["noskill"]

        def cell(group, index):
            return ", ".join(str(run[index]) for run in group) or MISSING

        comparison = [f"{cell(skill, index)} / {cell(noskill, index)}"
                      for index in range(1, len(COLUMNS) + 1)]
        lines.append(table_row((case, flow, cell(skill, 0), cell(noskill, 0), *comparison)))
    return lines


def resolve_runs(specification):
    path = Path(specification).expanduser()
    candidates = (path,) if path.is_absolute() else (path, ROOT / "evals/runs" / path)
    for candidate in candidates:
        if candidate.is_dir():
            return [candidate.resolve()]
    for candidate in candidates:
        pattern = str(candidate)
        if not has_magic(specification):
            pattern = glob_escape(pattern) + "*"
        matches = sorted(Path(match).resolve() for match in glob(pattern, recursive=True)
                         if (Path(match) / "meta.json").is_file())
        if matches:
            return matches
    raise ValueError(f"No run directories matched {specification!r}")


def group_outcomes(outcomes, pattern):
    if Path(pattern).name == pattern:
        return [outcome for run, outcome in outcomes.items() if run.match(pattern)]
    try:
        matches = set(resolve_runs(pattern))
    except ValueError:
        return []
    return [outcome for run, outcome in outcomes.items() if run in matches]


def case_group(value):
    label, separator, pattern = value.partition("=")
    if not separator or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", label) or not pattern:
        raise argparse.ArgumentTypeError("Expected GROUP=GLOB")
    return label, str(Path(pattern).expanduser())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True, help="Run directories, prefixes, or quoted globs")
    parser.add_argument("--group", action="append", type=case_group, default=[],
                        help="Show a separate condition table for GROUP=GLOB among the selected runs")
    parser.add_argument("--anonymize", action="store_true", help="Replace run IDs and case names")
    parser.add_argument("--out", type=Path, default=Path(__file__).with_suffix(".md"))
    args = parser.parse_args()
    try:
        runs = list(dict.fromkeys(run for specification in args.runs for run in resolve_runs(specification)))
    except ValueError as error:
        parser.error(str(error))
    try:
        args.out.write_text(render(runs, args.group, anonymize=args.anonymize), encoding="utf-8")
    except (OSError, ValueError):
        parser.exit(1, "Could not read run data or write the summary.\n")


if __name__ == "__main__":
    main()
