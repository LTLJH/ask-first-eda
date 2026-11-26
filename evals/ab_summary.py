"""Summarize EDA runs and compare skill and noskill by case and flow."""

import argparse
from collections import defaultdict
import getpass
from html import escape
import json
import math
import os
from pathlib import Path
import re
import shlex
import sys


sys.path.insert(0, str(Path(__file__).resolve().parent))
from numeric_check import artifact_paths
from run_case import ROOT


MISSING = "—"
QUESTION_END = re.compile(r"""[?？]["'”’»）)\]*`*_]*(?=\s|$)""")
COLUMNS = (
    "Overall", "Numbers verdict", "Critical failures", "Mismatched", "Analyst questions",
    "Turns", "Wall time (s)", "Tokens", "Report", "Charts",
)
ANALYST_COST_COLUMNS = {
    "commands": "Commands", "input_tokens": "Input", "cached_input_tokens": "Cached input",
    "uncached_input_tokens": "Uncached input", "output_tokens": "Output",
    "analyst_seconds": "Analyst time (s)", "source_reads": "Source reads",
}
SOURCE_READERS = {"cat", "sed", "head", "tail", "less", "nl", "rg", "grep", "awk", "bat", "more"}
PATTERN_READERS = {"sed", "rg", "grep", "awk"}
SKILL_SCRIPT = re.compile(r"(?:^|/)(?:ask-first-eda|eda-skill)/scripts/[^/]+\.py\Z")
ANALYST_LOG = re.compile(r"[0-9]{2,}-analyst\.jsonl")


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
    seen_commands = set()
    for path in sorted((run / "raw").glob("*-analyst.jsonl")):
        if not ANALYST_LOG.fullmatch(path.name):
            continue
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


def summarize(run):
    meta = read_object(run / "meta.json")
    grade = read_object(run / "grade.json")
    numeric = read_object(run / "numeric_check.json")
    transcript = run / "transcript.jsonl"
    analyst_turns = set()
    questions = set()
    for index, event in enumerate(events(transcript)):
        if event.get("speaker") != "analyst":
            continue
        turn = event.get("turn")
        key = ("turn", turn) if type(turn) is int else ("message", index)
        analyst_turns.add(key)
        if isinstance(event.get("text"), str) and QUESTION_END.search(event["text"]):
            questions.add(key)

    reports = artifact_paths(run, "*.[hH][tT][mM][lL]") or artifact_paths(run, "*.[hH][tT][mM]")
    primary = run / "eda_summary.json"
    summaries = artifact_paths(run, "eda_summary.json")
    summary = (read_object(primary) if primary in summaries
               else read_object(summaries[0]) if len(summaries) == 1 else {})
    turns = meta.get("turns")
    wall_time = meta.get("wall_time_s")
    return (
        verdict(grade.get("overall")),
        verdict(grade.get("numbers_verdict")),
        list_count(grade.get("critical_failures")),
        list_count(numeric.get("mismatched")),
        len(questions) if transcript.is_file() else MISSING,
        turns if type(turns) is int and turns >= 0 else len(analyst_turns),
        wall_time if type(wall_time) in (int, float) and 0 <= wall_time < math.inf else MISSING,
        count_tokens(run),
        "yes" if reports else "no",
        list_count(summary.get("charts")),
    ), meta


def table_row(values):
    return "| " + " | ".join(map(str, values)) + " |"


def render(runs):
    usernames = {name for name in (Path.home().name, getpass.getuser(), os.getenv("USER"),
                                  os.getenv("LOGNAME"), os.getenv("USERNAME")) if name}
    lines = [
        "# EDA A/B summary", "",
        table_row(("Run ID", "Case", "Flow", "Condition", *COLUMNS)),
        table_row(["---"] * (4 + len(COLUMNS))),
    ]
    cost_columns = ("Run ID", "Case", "Flow", "Condition", *ANALYST_COST_COLUMNS.values())
    cost_lines = ["", "## Analyst cost", "", table_row(cost_columns), table_row(["---"] * len(cost_columns))]
    pairs = defaultdict(lambda: {"skill": [], "noskill": []})
    for run in runs:
        values, meta = summarize(run)
        run_id = safe_label(run.resolve().name, usernames)
        raw_case = meta.get("case")
        case = safe_label(raw_case, usernames)
        flow = meta.get("flow")
        condition = meta.get("condition")
        flow = flow if flow in ("A", "B", "C") else MISSING
        condition = condition if condition in ("skill", "noskill") else MISSING
        lines.append(table_row((run_id, case, flow, condition, *values)))
        metrics = analyst_metrics(run)
        cost_lines.append(table_row((run_id, case, flow, condition,
                                     *(metrics[key] for key in ANALYST_COST_COLUMNS))))
        if case != MISSING and flow != MISSING and condition != MISSING:
            source = meta.get("case_dir")
            if not isinstance(source, str) or not source:
                source = f"evals/cases/{raw_case}"
            identity = os.path.normpath(ROOT / source)
            pairs[case, flow, identity][condition].append((run_id, *values))

    lines.extend(cost_lines)
    lines.extend([
        "", "## Skill vs noskill", "",
        "Each comparison shows skill / noskill. Commas separate repeated runs.", "",
        table_row(("Case", "Flow", "Skill run IDs", "Noskill run IDs", *COLUMNS)),
        table_row(["---"] * (4 + len(COLUMNS))),
    ])
    for (case, flow, _), runs_by_condition in sorted(pairs.items()):
        skill, noskill = runs_by_condition["skill"], runs_by_condition["noskill"]

        def cell(group, index):
            return ", ".join(str(run[index]) for run in group) or MISSING

        comparison = [f"{cell(skill, index)} / {cell(noskill, index)}"
                      for index in range(1, len(COLUMNS) + 1)]
        lines.append(table_row((case, flow, cell(skill, 0), cell(noskill, 0), *comparison)))
    lines.extend(["", "These 4 pairs are an exploratory sample, too small to draw statistical conclusions.", ""])
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", nargs="+", required=True, type=Path)
    parser.add_argument("--out", type=Path, default=Path(__file__).with_suffix(".md"))
    args = parser.parse_args()
    for run in args.runs:
        if not run.is_dir():
            parser.error("Every --runs argument must be an existing directory")
    try:
        args.out.write_text(render(args.runs), encoding="utf-8")
    except (OSError, ValueError):
        parser.exit(1, "Could not read run data or write the summary.\n")


if __name__ == "__main__":
    main()
