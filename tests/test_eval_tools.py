from decimal import Decimal
from hashlib import sha256
import json
import os
from pathlib import Path, PureWindowsPath
import re
import runpy
import shutil
from stat import S_IMODE
import subprocess
import sys
import tempfile
import textwrap
import unittest

import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="The evaluation tools require POSIX fcntl")

ROOT = Path(__file__).resolve().parents[1]
GALLERY_SUMMARY = Path("docs/gallery/messy_production_report.summary.json")
STAGED_SUMMARY = "eda-work/delivery/eda_summary.json"
ANALYST_SUMMARY = "eda-work-2/delivery/eda_summary.json"
FOREIGN_SKILL_COMMAND = "cat ~/.agents/skills/x/SKILL.md"
DOMAIN_CARD_MARKERS = ("shared-fact", "private-selected-flow", "private-other-flow")
FAKE_CODEX = """\
#!/usr/bin/env -S python3 -I
import json
import os
from pathlib import Path
from stat import S_IMODE
import sys

args = sys.argv[1:]
prompt = sys.stdin.read() if args[-1] == "-" else args[-1]
cwd = Path.cwd()
log = Path(os.environ["FAKE_CALLS"])
previous = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
codex_home = Path(os.environ["CODEX_HOME"])
auth = codex_home / "auth.json"
stale_auth = os.environ.get("FAKE_STALE_AUTH")
with log.open("a") as stream:
    print(json.dumps({"args": args[:-1], "argv": args, "prompt": prompt, "cwd": str(cwd),
                      "home": os.environ["HOME"], "codex_home": str(codex_home),
                      "path": os.environ["PATH"],
                      "auth_mode": S_IMODE(auth.stat().st_mode) if auth.is_file() else None,
                      "stale_auth_exists": Path(stale_auth).exists() if stale_auth else None,
                      "files": sorted(str(p.relative_to(cwd)) for p in cwd.rglob("*"))}),
          file=stream)
assert args[0] == "exec"
if "resume" in args[:-1]:
    assert args[args.index("resume") + 1] == "analyst-thread"
    assert prompt == "Use the agreed scope."
    if os.environ.get("FAKE_FAIL_RESUME") == "1":
        sys.exit(42)
    (cwd / "results" / "nested").mkdir(parents=True)
    (cwd / "results" / "nested" / "eda_summary.json").write_text(json.dumps({"metrics": []}))
    for name in ("report.html", "chart.png", "analysis.py"):
        (cwd / "results" / name).parent.mkdir(exist_ok=True)
        (cwd / "results" / name).write_text("artifact")
    hidden = cwd / ".eda-work.test" / "delivery"
    hidden.mkdir(parents=True)
    for name in ("report.html", "chart.png"):
        (hidden / name).write_text("hidden artifact")
    (cwd / "results/nested/eda_summary.json").rename(hidden / "eda_summary.json")
    if (cwd / "ask-first-eda").exists():
        (cwd / "ask-first-eda/report.html").write_text("skill artifact")
    (cwd / "linked.py").symlink_to(cwd / "input.csv")
    message, thread = "Here is the final report.", "analyst-thread"
elif "gpt-6.2-astra" in args:
    if "Quality-only grading" in prompt:
        message = json.dumps({"critical_failures": [], "quality_scores": {"traceability": 1},
                              "evidence": ["report"]})
    elif "Return a valid JSON object" in prompt or os.environ.get("FAKE_GRADE_PASS") == "1":
        fence = chr(96) * 3
        grade = {"critical_failures": ["priority violation"] if "Critical fixture" in prompt else [],
                 "quality_scores": {"traceability": 1}, "evidence": ["report"],
                 "numbers_verdict": "pass", "overall": "pass"}
        message = f"{fence}json\\n{json.dumps(grade)}\\n{fence}\\nThe numbers agree."
    elif os.environ.get("FAKE_GRADE_EMPTY_FIRST") == "1":
        message = ""
    else:
        message = "Invalid JSON"
    thread = "grader-thread"
elif "read-only" in args:
    message = "[END]" if "Here is the final report." in prompt else "Use the agreed scope."
    thread = f"simulator-{len(previous)}"
else:
    assert sys.stdin.read() == ""
    if os.environ.get("FAKE_MODIFY_INPUT") == "1":
        staged = cwd / "input.csv"
        before = staged.stat()
        staged.write_bytes(b"quantity\\n9\\n")
        os.utime(staged, ns=(before.st_atime_ns, before.st_mtime_ns))
    if os.environ.get("FAKE_WRITE_CLEAN_CSV") == "1":
        (cwd / "delivery").mkdir()
        (cwd / "delivery/cleaned_x.csv").write_text("quantity\\n8\\n")
        (cwd / "delivery-2").mkdir()
        (cwd / "delivery-2/cleaned_sales.csv").write_text("quantity\\n10\\n")
        (cwd / "excluded.csv").write_text("_source_sheet,_source_row,reason\\n,3,subtotal\\n")
        (cwd / ".eda-work.test/delivery").mkdir(parents=True)
        (cwd / ".eda-work.test/delivery/cleaned_y.csv").write_text("quantity\\n9\\n")
        (cwd / ".eda-work.test/excluded.csv").write_text("_source_sheet,_source_row,reason\\n")
        for name in ("scratch.csv", "delivery/intermediate.csv", ".eda-work.test/cleaned_preview.csv"):
            (cwd / name).write_text("quantity\\n8\\n9\\n")
    if os.environ.get("FAKE_WRITE_NEW_SUMMARY") == "1":
        summary = cwd / "eda-work-2/delivery/eda_summary.json"
        summary.parent.mkdir(parents=True)
        summary.write_text(json.dumps({"datasets": [], "ambiguity_log": [], "source": "analyst"}))
    message, thread = "Which scope should I use?", "analyst-thread"

events = [
    {"type": "thread.started", "thread_id": thread},
    {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
    {"type": "turn.completed", "usage": {"input_tokens": 14, "output_tokens": 8}},
]
for event in events:
    print(json.dumps(event))
Path(args[args.index("-o") + 1]).write_text(message)
"""

FAKE_SMOKE_CLIENT = """\
#!/usr/bin/env -S python3 -I
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
client = Path(sys.argv[0]).name
if args == ["--version"]:
    print("codex-cli 0.171.0" if client == "codex" else "2.1.330 (Claude Code)")
    sys.exit()
if args == ["--help"]:
    print("--tools --permission-mode --setting-sources --strict-mcp-config --mcp-config "
          "--disallowedTools --max-turns")
    sys.exit()

cwd = Path.cwd()
if client == "codex":
    prompt = args[-1]
    skill = Path(".agents/skills/ask-first-eda/SKILL.md")
    assert args[0] == "exec" and "--json" in args and "read-only" in args
else:
    prompt = args[args.index("-p") + 1]
    skill = Path(".claude/skills/ask-first-eda/SKILL.md")
    assert "stream-json" in args and "--verbose" in args and "--max-turns" in args
    assert args[args.index("--tools") + 1] == "Read,Skill"
assert skill.is_file()
assert Path("sales.csv").is_file()
assert cwd.is_relative_to(Path.home() / ".cache/ask-first-eda-install" / client)

if "p-value" in prompt:
    # Mention of the manifest in a message or a failed command is not a read.
    print(json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": f"false && cat {skill} || true", "exit_code": 0,
    }}))
    print(json.dumps({"type": "item.completed", "item": {
        "type": "command_execution", "command": f"cat {skill}", "exit_code": 1,
    }}))
    event = {"type": "item.completed", "item": {"type": "agent_message", "text": str(skill)}}
elif "회귀" in prompt:
    event = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Skill", "input": {"skill": "other"}},
    ]}}
elif client == "codex":
    event = {"type": "item.completed", "item": {
        "type": "command_execution", "command": f"/bin/bash -lc 'cat {skill}'", "exit_code": 0,
    }}
elif "Run EDA" in prompt:
    event = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {"file_path": str(cwd / skill)}},
    ]}}
else:
    event = {"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Skill", "input": {"skill": "ask-first-eda"}},
    ]}}
with Path(os.environ["FAKE_CALLS"]).open("a") as log:
    print(client, file=log)
print(json.dumps(event))
print(json.dumps({"type": "turn.completed"} if client == "codex"
                 else {"type": "result", "subtype": "success", "is_error": False}))
"""


def write_jsonl(path, events):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(event) + "\n" for event in events), encoding="utf-8")


def command_event(command, *, item_id="item_0", event_type="item.completed"):
    return {"type": event_type, "item": {
        "id": item_id, "type": "command_execution", "command": command, "exit_code": 0,
    }}


class EvalToolsTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory()
        self.addCleanup(self.scratch.cleanup)
        parent = Path(self.scratch.name).resolve()
        self.repo = parent / "fixture repo"
        self.home = parent / "home"
        self.home.mkdir()
        self.case = self.repo / "evals/cases/demo"
        self.case.mkdir(parents=True)
        for name in ("run_case.py", "numeric_check.py", "grade_run.py", "ab_summary.py",
                     "install_smoke.py"):
            shutil.copyfile(ROOT / "evals" / name, self.repo / "evals" / name)
        venv_python = self.repo / ".venv/bin/python"
        venv_python.parent.mkdir(parents=True)
        venv_python.symlink_to(sys.executable)

        (self.case / "input.csv").write_text("quantity\n8\n")
        (self.case / "case.md").write_text("# Case\n\n## A\n\nOpening A\n\n## B\n\nOpening B\n")
        (self.case / "domain_card.md").write_text(
            "# Private\n\n## Shared facts\n\nshared-fact\n\n"
            "## A\n\nprivate-other-flow\n\n## B\n\nprivate-selected-flow\n"
        )
        self.write_expected([])
        roles = self.repo / "harness/roles"
        roles.mkdir(parents=True)
        for role in ("blind-analyst", "user-simulator", "grader"):
            (roles / f"{role}.md").write_text(f"Role: {role}\n")
        skill = self.repo / "skills/ask-first-eda"
        (skill / "scripts").mkdir(parents=True)
        (skill / "SKILL.md").write_text("Skill")
        (skill / "scripts/helper.py").write_text("# Bundled helper")
        for name in ("AGENTS.md", "CLAUDE.md"):
            (self.repo / name).write_text("Repository instructions")

        fake = parent / "fake codex"
        fake.write_text(textwrap.dedent(FAKE_CODEX))
        fake.chmod(0o700)
        self.calls = parent / "calls.jsonl"
        self.env = dict(os.environ, HOME=str(self.home), CODEX_BIN=str(fake),
                        CODEX_HOME=str(parent / "source-codex"),
                        FAKE_CALLS=str(self.calls),
                        PATH=f"{Path(sys.executable).parent}{os.pathsep}{os.environ['PATH']}")

    def write_expected(self, metrics, optional=(), dates=(), *, tolerance=0.01):
        expected = {"absolute_tolerance": tolerance, "dates_in_order": list(dates), "flows": {
            "A": {"metrics": [], "must": ["expected-other-flow"]},
            "B": {"metrics": metrics, "optional_metrics": list(optional)},
        }}
        (self.case / "expected.json").write_text(json.dumps(expected))

    def invoke(self, tool, *args, expected_code=0):
        result = subprocess.run(
            [sys.executable, "-I", str(self.repo / "evals" / tool), *map(str, args)],
            cwd=self.repo, env=self.env, capture_output=True, text=True, check=False, timeout=15,
        )
        self.assertEqual(result.returncode, expected_code, result.stderr + result.stdout)
        return result.stderr if expected_code else result.stdout

    def run_case(self, condition, *args):
        return self.invoke("run_case.py", "--case", "demo", "--flow", "B", "--condition",
                           condition, "--run-id", condition, *args)

    def test_runner_uses_the_same_input_opening_and_delivery_in_all_conditions(self):
        for condition in ("noskill", "prompted", "skill"):
            self.run_case(condition, "--max-turns", 1)

        def delivery_line(prompt):
            [line] = [line for line in prompt.splitlines()
                      if "report.html" in line and "results.json" in line]
            return line

        noskill, prompted, skill = (call["prompt"] for call in self.read_calls())
        prompt_line = ("Ask about a business definition only when the request and the file "
                       "cannot settle a choice that changes the result, and keep the evidence for each number.")
        skill_line = "An analysis skill is available at ./ask-first-eda/SKILL.md. Read it first and follow it."
        self.assertEqual(prompted.count(prompt_line), 1)
        self.assertEqual(prompted.replace(f"{prompt_line}\n", "", 1), noskill)
        self.assertEqual(skill.replace(f"\n\n{skill_line}", "", 1), noskill)
        self.assertTrue(noskill.endswith("\n\nOpening B"))
        delivery = delivery_line(noskill)
        for text in ("offline", "delivery/", "metrics"):
            self.assertIn(text, delivery.lower())
        self.assertNotRegex(delivery, r"(?i)skill|eda_summary|ambiguity")
        self.assertNotIn(
            "If other instructions specify a delivery location, use that location without making copies.",
            delivery,
        )
        metadata = [json.loads((self.run_dir(condition) / "meta.json").read_text())
                    for condition in ("noskill", "prompted", "skill")]
        self.assertEqual(set(metadata[0]["input_sha256"]), {"input.csv"})
        for item in metadata[1:]:
            for key in ("input_sha256", "models", "efforts"):
                self.assertEqual(item[key], metadata[0][key])
        self.assertFalse((self.cache_dir("prompted") / "work/ask-first-eda").exists())

    def test_blind_analyst_role_leaves_interview_and_evidence_policy_to_the_condition(self):
        role_text = (ROOT / "harness/roles/blind-analyst.md").read_text()
        self.assertNotRegex(role_text, r"(?i)\b(ask\b|questions\b|interview|ambigu\w*|evidence|traceable)")

    def test_a5_runner_records_reproducibility_metadata_for_both_conditions(self):
        paths = {"evals/numeric_check.py", "evals/grade_run.py", "harness/roles/grader.md"}
        for condition in ("skill", "noskill"):
            self.run_case(condition, "--max-turns", 1)
            meta = json.loads((self.run_dir(condition) / "meta.json").read_text())
            self.assertIsNone(meta["repo_commit"])
            self.assertEqual(meta["grader_files_sha256"], {
                path: sha256((self.repo / path).read_bytes()).hexdigest() for path in paths
            })
            versions = meta["dependencies"]
            self.assertEqual(set(versions), {
                "python", "pandas", "matplotlib", "openpyxl", "pyarrow",
            })
            self.assertRegex(versions["python"], r"^\d+\.\d+\.\d+$")
            for package in set(versions) - {"python"}:
                if versions[package] is not None:
                    self.assertRegex(versions[package], r"^[A-Za-z0-9.+!_-]+$")
            if condition == "skill":
                self.assertRegex(meta["skill_sha256"], r"^[0-9a-f]{64}$")
            else:
                self.assertIsNone(meta["skill_sha256"])
            self.assertIn("input.csv", meta["input_sha256"])
            self.assertNotIn(str(self.repo.parent), json.dumps(meta))

    def run_dir(self, name):
        return self.repo / "evals/runs" / name

    def cache_dir(self, name):
        return self.home / ".cache" / "eda-skill-evals" / name

    def read_calls(self):
        return [json.loads(line) for line in self.calls.read_text().splitlines()]

    def write_source_auth(self):
        codex_home = Path(self.env["CODEX_HOME"])
        for path in (codex_home / "skills/x/SKILL.md", codex_home / "plugins/cache/x",
                     codex_home / "AGENTS.md",
                     self.home / ".agents/skills/x/SKILL.md", self.home / "AGENTS.md"):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# Shared home fixture", encoding="utf-8")
        (codex_home / "config.toml").write_text('model = "shared-model"\n', encoding="utf-8")
        auth = codex_home / "auth.json"
        auth.write_text('{"token":"fake"}', encoding="utf-8")
        auth.chmod(0o644)
        return auth

    def assert_role_home(self, call, run_id, role):
        home = self.home / ".cache" / "eda-skill-evals" / run_id / f"home-{role}"
        codex_home = home / ".codex"
        self.assertEqual(Path(call["home"]), home)
        self.assertEqual(Path(call["codex_home"]), codex_home)
        self.assertFalse(home.is_relative_to(self.repo))
        self.assertEqual(S_IMODE(home.stat().st_mode), 0o700)
        self.assertEqual(S_IMODE(codex_home.stat().st_mode), 0o700)
        for directory in (home, codex_home, home / ".agents"):
            for name in ("skills", "plugins", "AGENTS.md"):
                self.assertFalse((directory / name).exists(), directory / name)
        config = (codex_home / "config.toml").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(config, ["[skills.bundled]", "enabled = false", "", "[features]", "plugins = false", "apps = false"])
        self.assertEqual(call["auth_mode"], 0o600)
        self.assertFalse((codex_home / "auth.json").exists())

    def test_runner_isolates_analyst_resume_and_simulator_homes(self):
        source_auth = self.write_source_auth()

        self.run_case("skill")

        first, simulator, resume, last = self.read_calls()
        for call, role in ((first, "analyst"), (simulator, "simulator"),
                           (resume, "analyst"), (last, "simulator")):
            self.assert_role_home(call, "skill", role)
        self.assertEqual(source_auth.read_text(encoding="utf-8"), '{"token":"fake"}')

    def test_runner_removes_role_auth_when_resume_fails(self):
        self.write_source_auth()
        self.env["FAKE_FAIL_RESUME"] = "1"

        self.invoke("run_case.py", "--case", "demo", "--flow", "B", "--condition", "skill",
                    "--run-id", "failed-resume", expected_code=1)

        first, simulator, resume = self.read_calls()
        for call, role in ((first, "analyst"), (simulator, "simulator"), (resume, "analyst")):
            self.assert_role_home(call, "failed-resume", role)

    def write_cached_auth(self, run_id, role):
        auth = self.cache_dir(run_id) / f"home-{role}/.codex/auth.json"
        auth.parent.mkdir(parents=True, exist_ok=True)
        auth.write_text('{"token":"cached-fixture"}', encoding="utf-8")
        return auth

    def test_runner_removes_stale_auth_before_analyst_and_preserves_locked_auth(self):
        import fcntl

        stale = self.write_cached_auth("interrupted", "analyst")
        active = self.write_cached_auth("active", "simulator")
        for run_id in ("interrupted", "active"):
            (self.cache_dir(run_id) / ".lifetime-lock").touch()
        self.env["FAKE_STALE_AUTH"] = str(stale)
        active_contents = active.read_bytes()

        fd = os.open(self.cache_dir("active"), os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.run_case("noskill", "--max-turns", 1)
            self.assertEqual(active.read_bytes(), active_contents)
        finally:
            os.close(fd)

        [analyst] = self.read_calls()
        self.assertFalse(analyst["stale_auth_exists"])
        self.assertFalse(stale.exists())

    def test_runner_creates_lifetime_lock_marker(self):
        self.run_case("noskill", "--max-turns", 1)

        self.assertTrue((self.cache_dir("noskill") / ".lifetime-lock").is_file())

    def test_runner_preserves_auth_in_an_unmarked_cache(self):
        legacy = self.write_cached_auth("legacy", "analyst")
        contents = legacy.read_bytes()

        self.run_case("noskill", "--max-turns", 1)

        self.assertTrue(legacy.is_file())
        self.assertEqual(legacy.read_bytes(), contents)
        self.assertFalse((self.cache_dir("legacy") / ".lifetime-lock").exists())

    def test_runner_removes_stale_auth_when_run_id_is_reused(self):
        self.run_case("noskill", "--max-turns", 1)
        auth = self.write_cached_auth("noskill", "analyst")
        config = auth.with_name("config.toml")
        config_before = config.read_bytes()
        meta = self.run_dir("noskill") / "meta.json"
        meta_before = meta.read_bytes()

        error = self.invoke("run_case.py", "--case", "demo", "--flow", "B", "--condition",
                            "noskill", "--run-id", "noskill", expected_code=1)

        self.assertIn("Run ID already exists: noskill", error)
        self.assertEqual(len(self.read_calls()), 1)
        self.assertEqual(meta.read_bytes(), meta_before)
        self.assertEqual(config.read_bytes(), config_before)
        self.assertFalse(auth.exists())

    def test_analyst_prompts_use_stdin_for_start_and_resume(self):
        self.run_case("skill")

        first, _, resume, _ = self.read_calls()
        for call, expected in ((first, "Opening B"), (resume, "Use the agreed scope.")):
            with self.subTest(command=call["args"]):
                self.assertEqual(call["argv"][-1], "-")
                self.assertNotIn(expected, " ".join(call["argv"]))
                self.assertIn(expected, call["prompt"])

    def test_analyst_prompts_omit_repo_python_path(self):
        self.run_case("skill")

        first, _, resume, _ = self.read_calls()
        for call in (first, resume):
            self.assertNotIn(str(self.repo), call["prompt"])
            self.assertNotIn(".venv/bin/python", call["prompt"])

    def test_analyst_path_starts_with_cache_bin_containing_venv_links(self):
        self.run_case("skill")

        first, _, resume, _ = self.read_calls()
        bin_dir = self.cache_dir("skill") / "bin"
        for call in (first, resume):
            self.assertEqual(call["path"].split(os.pathsep)[0], str(bin_dir))
        for name in ("python", "python3"):
            link = bin_dir / name
            self.assertTrue(link.is_symlink(), link)
            self.assertEqual(
                Path(os.path.abspath(bin_dir / link.readlink())),
                self.repo / ".venv/bin/python",
            )

    def test_isolated_skill_workspace_and_end_after_resume(self):
        self.run_case("skill")
        work = self.home / ".cache" / "eda-skill-evals" / "skill" / "work"
        calls = self.read_calls()
        self.assertEqual(len(calls), 4)
        first, simulator, resume, last = calls
        self.assertEqual(first["cwd"], str(work))
        self.assertEqual(first["files"], ["ask-first-eda", "ask-first-eda/SKILL.md",
                                         "ask-first-eda/scripts", "ask-first-eda/scripts/helper.py",
                                         "input.csv"])
        self.assertIn("workspace-write", first["args"])
        self.assertIn('model_reasoning_effort="medium"', first["args"])
        self.assertIn("./ask-first-eda/SKILL.md", first["prompt"])
        self.assertIn("Opening B", first["prompt"])
        self.assertNotIn("Opening A", first["prompt"])
        self.assertNotIn("private-selected-flow", first["prompt"])
        self.assertEqual(resume["cwd"], str(work))
        for option in ("-m", "--sandbox"):
            args = resume["args"]
            self.assertLess(args.index(option), args.index("resume"))
            self.assertEqual(args[args.index(option) + 1],
                             first["args"][first["args"].index(option) + 1])
        self.assertIn('sandbox_mode="workspace-write"', resume["args"])
        self.assertIn('model_reasoning_effort="medium"', resume["args"])
        self.assertIn("--skip-git-repo-check", resume["args"])
        self.assertIn("read-only", simulator["args"])
        self.assertIn('model_reasoning_effort="low"', simulator["args"])
        self.assertIn("private-selected-flow", simulator["prompt"])
        self.assertIn("shared-fact", simulator["prompt"])
        self.assertNotIn("private-other-flow", simulator["prompt"])
        self.assertIn("Which scope should I use?", simulator["prompt"])
        self.assertIn("Use the agreed scope.", last["prompt"])
        run = self.run_dir("skill")
        messages = [json.loads(line) for line in (run / "transcript.jsonl").read_text().splitlines()]
        self.assertEqual([msg["speaker"] for msg in messages],
                         ["user", "analyst", "simulator", "analyst", "simulator"])
        self.assertEqual(messages[-1]["text"], "[END]")
        self.assertEqual(messages[1]["tokens"]["output_tokens"], 8)
        self.assertGreaterEqual(messages[1]["duration_s"], 0)
        meta = json.loads((run / "meta.json").read_text())
        self.assertEqual((meta["turns"], meta["end_reason"]), (2, "simulator_end"))
        self.assertEqual(len(list((run / "raw").glob("*.jsonl"))), 4)
        artifacts = [".eda-work.test/delivery/chart.png", ".eda-work.test/delivery/eda_summary.json",
                     ".eda-work.test/delivery/report.html", "results/analysis.py",
                     "results/chart.png", "results/report.html"]
        self.assertEqual(meta["artifacts"], artifacts)
        for path in artifacts:
            self.assertTrue((run / path).is_file(), path)
        for path in ("ask-first-eda", "input.csv", "linked.py"):
            self.assertFalse((run / path).exists(), path)

    def test_runner_collects_cleaned_csv_and_exclusion_log(self):
        # An input bearing an artifact name still stays out of the run root.
        manifest = self.case / "case.md"
        manifest.write_text("inputs: input.csv, cleaned_x.csv\n" + manifest.read_text())
        (self.case / "cleaned_x.csv").write_text("quantity\n8\n9\n", encoding="utf-8")
        self.env["FAKE_WRITE_CLEAN_CSV"] = "1"
        self.run_case("skill", "--max-turns", 1)

        run = self.run_dir("skill")
        work = self.cache_dir("skill") / "work"
        meta = json.loads((run / "meta.json").read_text())
        self.assertTrue((work / "cleaned_x.csv").is_file())
        self.assertFalse((run / "cleaned_x.csv").exists())
        self.assertNotIn("cleaned_x.csv", meta["artifacts"])
        artifacts = {"delivery/cleaned_x.csv", "delivery-2/cleaned_sales.csv", "excluded.csv",
                     ".eda-work.test/delivery/cleaned_y.csv", ".eda-work.test/excluded.csv"}
        self.assertEqual(set(meta["artifacts"]), artifacts)
        for path in sorted(artifacts):
            self.assertEqual((run / path).read_bytes(), (work / path).read_bytes(), path)
        for path in ("scratch.csv", "delivery/intermediate.csv", ".eda-work.test/cleaned_preview.csv"):
            self.assertFalse((run / path).exists(), path)

    def test_noskill_ends_at_max_turns(self):
        self.run_case("noskill", "--max-turns", "1")
        [first] = self.read_calls()
        self.assertEqual(first["files"], ["input.csv"])
        self.assertNotIn("ask-first-eda/SKILL.md", first["prompt"])
        meta = json.loads((self.run_dir("noskill") / "meta.json").read_text())
        self.assertEqual((meta["turns"], meta["end_reason"]), (1, "max_turns"))
        self.assertEqual(meta["artifacts"], [])

    def test_runner_records_builtin_input_sha256(self):
        self.run_case("noskill", "--max-turns", "1")

        meta = json.loads((self.run_dir("noskill") / "meta.json").read_text())
        self.assertEqual(meta.get("input_sha256"), {
            "input.csv": sha256((self.case / "input.csv").read_bytes()).hexdigest(),
        })
        self.assertIs(meta.get("input_modified", False), False)

    def test_runner_records_skills_isolation(self):
        self.run_case("skill", "--max-turns", "1")

        meta = json.loads((self.run_dir("skill") / "meta.json").read_text(encoding="utf-8"))
        isolation = meta.get("skills_isolation", {})
        self.assertEqual(set(isolation), {"bundled_skills", "plugins", "apps"})
        for key in isolation:
            self.assertIs(isolation[key], False, key)

    def test_runner_flags_input_copy_with_changed_sha256(self):
        original = (self.case / "input.csv").read_bytes()
        self.env["FAKE_MODIFY_INPUT"] = "1"
        self.run_case("noskill", "--max-turns", 1)

        staged = (self.cache_dir("noskill") / "work/input.csv").read_bytes()
        meta = json.loads((self.run_dir("noskill") / "meta.json").read_text())
        self.assertEqual((self.case / "input.csv").read_bytes(), original)
        self.assertEqual(len(staged), len(original))
        self.assertNotEqual(sha256(staged).digest(), sha256(original).digest())
        self.assertEqual(meta["input_sha256"]["input.csv"], sha256(original).hexdigest())
        self.assertIs(meta.get("input_modified"), True)

    def test_runner_dry_run_does_not_launch_or_stage(self):
        source_auth = self.write_source_auth()
        output = self.run_case("skill", "--dry-run")
        self.assertIn("Dry run", output)
        self.assertIn("input.csv", output)
        self.assertIn("Analyst prompt:\n", output)
        prompt = output.split("Analyst prompt:\n", 1)[1]
        self.assertIn("Read it first and follow it.", prompt)
        self.assertTrue(prompt.rstrip().endswith("Opening B"))
        self.assertFalse(self.calls.exists())
        self.assertFalse(self.run_dir("skill").exists())
        self.assertFalse((self.home / ".cache").exists())
        self.assertEqual(source_auth.read_text(encoding="utf-8"), '{"token":"fake"}')

    def legacy_analyst_prompt(self, condition):
        prefix = {
            "noskill": "",
            "prompted": (
                "Ask about a business definition only when the request and the file cannot settle a choice "
                "that changes the result, and keep the evidence for each number.\n"
            ),
            "skill": (
                "An analysis skill is available at ./ask-first-eda/SKILL.md. Read it first and follow it.\n\n"
            ),
        }
        return (
            "Role: blind-analyst\n\n"
            f"{prefix[condition]}Use `python3 -I` to run Python with pandas and matplotlib.\n\n"
            "When the analysis is complete, save an offline HTML report (`report.html`) and a JSON "
            "file with the calculated metrics (`results.json`) in `delivery/` under the working directory.\n\n"
            "Opening B\n"
        )

    def test_runner_dry_run_prompted_rel_extends_prompted_instruction(self):
        output = self.run_case("prompted_rel", "--dry-run")
        prompt = output.split("Analyst prompt:\n", 1)[1]
        instruction = (
            "In chat, write file locations as paths relative to the working directory, never absolute paths."
        )

        self.assertRegex(prompt, rf"each number\.\s+{re.escape(instruction)}\nUse `python3 -I`")
        self.assertEqual(
            re.sub(rf"(?<=each number\.)\s+{re.escape(instruction)}", "", prompt, count=1),
            self.legacy_analyst_prompt("prompted"),
        )

    def test_runner_dry_run_current_keeps_legacy_prompts_and_shows_defaults(self):
        for condition in ("noskill", "prompted", "skill"):
            output = self.run_case(condition, "--dry-run")
            header, prompt = output.split("Analyst prompt:\n", 1)
            self.assertEqual(prompt, self.legacy_analyst_prompt(condition), condition)

        self.assertRegex(header, r"\bcurrent\b")
        self.assertIn("gpt-6.2-sol", header)
        self.assertRegex(header, r"\bmedium\b")
        for condition in ("noskill", "prompted", "skill"):
            output = self.run_case(condition, "--dry-run", "--opening-style", "current")
            self.assertEqual(output.split("Analyst prompt:\n", 1)[1],
                             self.legacy_analyst_prompt(condition), condition)

    def test_runner_dry_run_conversational_inserts_line_before_delivery(self):
        output = self.run_case("prompted", "--dry-run", "--opening-style", "conversational")
        header, prompt = output.split("Analyst prompt:\n", 1)
        instruction = (
            "This is a conversation. The user can answer questions before you finish, "
            "so ask when a choice that changes the result is open."
        )
        expected = self.legacy_analyst_prompt("prompted").replace(
            "\n\nWhen the analysis is complete,",
            f"\n\n{instruction}\nWhen the analysis is complete,",
            1,
        )

        self.assertEqual(prompt, expected)
        self.assertRegex(header, r"\bconversational\b")

    def test_runner_dry_run_shows_analyst_model_and_effort_overrides(self):
        output = self.run_case("noskill", "--dry-run", "--analyst-model", "gpt-6.1-sol",
                               "--analyst-effort", "high")
        header = output.split("Analyst prompt:\n", 1)[0]

        self.assertIn("gpt-6.1-sol", header)
        self.assertRegex(header, r"\bhigh\b")

    def assert_analyst_options(self, options, model, effort, opening_style):
        main = eval_function("run_case.py", "main")
        namespace = main.__globals__
        calls = []

        def reply(args, cwd, log, prompt, **kwargs):
            calls.append(args)
            return namespace["Reply"]("Done.", "analyst-thread", None, 0)

        with pytest.MonkeyPatch.context() as patch:
            patch.setitem(namespace, "ROOT", self.repo)
            patch.setitem(namespace, "call_codex", reply)
            patch.setenv("HOME", str(self.home))
            patch.setenv("CODEX_HOME", self.env["CODEX_HOME"])
            patch.setattr(sys, "argv", ["run_case.py", "--case", "demo", "--flow", "B",
                                       "--condition", "noskill", "--max-turns", "1",
                                       "--run-id", "options", *options])
            main()

        self.assertEqual(len(calls), 1)
        args = calls[0]
        self.assertEqual(args[args.index("-m") + 1], model)
        self.assertEqual(args[args.index("-c") + 1], f'model_reasoning_effort="{effort}"')
        meta = json.loads((self.run_dir("options") / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["models"]["analyst"], model)
        self.assertEqual(meta["efforts"]["analyst"], effort)
        self.assertEqual(meta.get("opening_style"), opening_style)

    def test_runner_records_default_analyst_options(self):
        self.assert_analyst_options([], "gpt-6.2-sol", "medium", "current")

    def test_runner_forwards_and_records_overridden_analyst_options(self):
        self.assert_analyst_options(
            ["--analyst-model", "gpt-6.1-sol", "--analyst-effort", "high",
             "--opening-style", "conversational"],
            "gpt-6.1-sol", "high", "conversational",
        )

    def test_runner_dry_run_displays_gallery_prior_without_staging(self):
        prior = self.repo / GALLERY_SUMMARY
        prior.parent.mkdir(parents=True)
        shutil.copyfile(ROOT / GALLERY_SUMMARY, prior)

        output = self.run_case("skill", "--dry-run", "--prior-summary", GALLERY_SUMMARY)

        self.assertIn(f"Prior summary: {GALLERY_SUMMARY} -> work/{STAGED_SUMMARY}",
                      output.splitlines())
        self.assertFalse(self.calls.exists())
        self.assertFalse((self.repo / "evals/runs").exists())
        self.assertFalse((self.home / ".cache").exists())

    def assert_prior_summary_run(self, *, write_new_summary):
        prior = self.repo / GALLERY_SUMMARY
        prior.parent.mkdir(parents=True)
        original = b'{"datasets": [], "ambiguity_log": [], "source": "gallery"}\n'
        prior.write_bytes(original)
        for name in ("report.html", "grade.json", "transcript.jsonl", "domain_card.md"):
            (prior.parent / name).write_text("Not for the analyst")
        self.env["FAKE_WRITE_NEW_SUMMARY"] = "1" if write_new_summary else "0"

        self.run_case("noskill", "--max-turns", 1, "--prior-summary", prior)

        [first] = self.read_calls()
        work = self.home / ".cache" / "eda-skill-evals" / "noskill" / "work"
        self.assertEqual(first["cwd"], str(work))
        self.assertEqual(first["files"], ["eda-work", "eda-work/delivery", STAGED_SUMMARY,
                                         "input.csv"])
        self.assertEqual((work / STAGED_SUMMARY).read_bytes(), original)
        self.assertEqual(prior.read_bytes(), original)
        run = self.run_dir("noskill")
        meta = json.loads((run / "meta.json").read_text())
        self.assertEqual(meta["prior_summary"], GALLERY_SUMMARY.as_posix())
        expected_artifacts = [ANALYST_SUMMARY] if write_new_summary else []
        self.assertEqual(meta["artifacts"], expected_artifacts)
        self.assertEqual([p.relative_to(run).as_posix() for p in run.rglob("eda_summary.json")],
                         expected_artifacts)
        if write_new_summary:
            self.assertEqual(json.loads((run / ANALYST_SUMMARY).read_text()),
                             {"datasets": [], "ambiguity_log": [], "source": "analyst"})

    def test_runner_stages_prior_without_collecting_it_as_an_artifact(self):
        self.assert_prior_summary_run(write_new_summary=False)

    def test_runner_collects_only_the_new_summary_when_prior_is_staged(self):
        self.assert_prior_summary_run(write_new_summary=True)

    def test_a5_case_dir_copies_only_declared_inputs_without_grading(self):
        case = self.repo / "examples/bike rides"
        case.mkdir(parents=True)
        for name in ("SOURCE.md", "README.md", "gen_spec.md", "make_data.py", "domain_card.md"):
            (case / name).write_text("fixture")
        (case / "sales.csv").write_text("rides\n12\n")
        (case / "lookup.json").write_text('{"zone":"east"}\n')
        (case / "case.md").write_text("# Case\n\ninputs: sales.csv, lookup.json\n\n## B\nOpening B\n")
        (case / "input.csv").write_text("unlisted\n")
        (case / "linked.csv").symlink_to(case / "sales.csv")
        self.invoke("run_case.py", "--case-dir", case, "--flow", "B", "--condition",
                    "noskill", "--max-turns", 1, "--run-id", "example")
        [call] = self.read_calls()
        self.assertEqual(call["files"], ["lookup.json", "sales.csv"])
        run = self.run_dir("example")
        meta = json.loads((run / "meta.json").read_text())
        self.assertEqual(meta["case"], "bike rides")
        self.assertEqual((self.repo / meta["case_dir"]).resolve(), case.resolve())
        self.assertFalse((run / "numeric_check.json").exists())
        self.assertFalse((run / "grade.json").exists())
        self.assertEqual(meta.get("input_sha256"), {
            name: sha256((case / name).read_bytes()).hexdigest()
            for name in ("lookup.json", "sales.csv")
        })

    def test_numeric_check_uses_external_expected_for_same_named_case(self):
        self.write_expected([{"name": "inventory_count", "value": 8}])
        case = self.repo / "examples/demo"
        case.mkdir(parents=True)
        content = b"count\n17\n"
        (case / "input.csv").write_bytes(content)
        (case / "expected.json").write_text(json.dumps({
            "absolute_tolerance": 0.01,
            "flows": {"B": {"metrics": [{"name": "inventory_count", "value": 17}]}},
        }))
        run = self.prepare_run()
        (run / "meta.json").write_text(json.dumps({
            "case": "demo", "flow": "B", "case_dir": case.relative_to(self.repo).as_posix(),
            "input_sha256": {"input.csv": sha256(content).hexdigest()},
        }))
        write_summary(run, [{"name": "inventory_count", "value": 17}])

        result = self.check_numbers(run)

        self.assertEqual([metric["name"] for metric in result["matched"]], ["inventory_count"])
        self.assertEqual(result["mismatched"], [])

    def test_quality_grading_runs_separately_without_numeric_check(self):
        self.invoke("run_case.py", "--case-dir", self.case, "--flow", "B", "--condition",
                    "noskill", "--max-turns", 1, "--run-id", "ungraded")
        run = self.run_dir("ungraded")
        (self.case / "expected.json").unlink()
        self.invoke("run_case.py", "grade-quality", "--run", run, "--dry-run")
        self.assertEqual(len(self.read_calls()), 1)
        self.invoke("run_case.py", "grade-quality", "--run", run)
        analyst, grader = self.read_calls()
        self.assertNotEqual(analyst["cwd"], grader["cwd"])
        self.assertIn("read-only", grader["args"])
        self.assertNotIn("resume", grader["args"])
        for marker in DOMAIN_CARD_MARKERS:
            self.assertNotIn(marker, grader["prompt"])
        self.assertNotIn("numeric_check.json", grader["prompt"])
        self.assertFalse((run / "numeric_check.json").exists())
        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual(grade["numbers_verdict"], "skipped")
        self.assertEqual(grade["overall"], "pass")
        self.assertEqual(grade["quality_scores"], {"traceability": 1})

    def test_ab_summary_counts_and_pairs_without_private_paths(self):
        for condition in ("skill", "noskill"):
            run = self.run_dir(condition)
            (run / "raw").mkdir(parents=True)
            (run / "meta.json").write_text(json.dumps({
                "case": "demo", "flow": "B", "condition": condition,
                "turns": 3, "wall_time_s": 4.125, "case_dir": str(self.home),
            }))
            transcript = [
                {"turn": 1, "speaker": "user", "text": "Question?"},
                {"turn": 1, "speaker": "analyst", "text": "Scope? Dates? Next I will plot."},
                {"turn": 2, "speaker": "analyst", "text": "url?x=y and a report."},
                {"turn": 3, "speaker": "analyst", "text": 'They asked "Which date?"'},
            ]
            (run / "transcript.jsonl").write_text(
                "".join(json.dumps(msg) + "\n" for msg in transcript)
            )
        run = self.run_dir("skill")
        (run / "grade.json").write_text(json.dumps({
            "overall": "pass", "numbers_verdict": "pass",
            "critical_failures": [], "evidence": [str(self.home)],
        }))
        (run / "numeric_check.json").write_text('{"mismatched":[{}]}')
        (run / "report.html").write_text("report")
        (run / "eda_summary.json").write_text('{"charts":[{},{}]}')
        (run / "raw/01-analyst.jsonl").write_text(
            '{"type":"turn.completed","usage":{"input_tokens":10,"cached_input_tokens":6,'
            '"output_tokens":4}}\nnot JSON\n'
        )
        (run / "raw/01-simulator.jsonl").write_text(
            '{"type":"usage","usage":{"input_tokens":2,"output_tokens":1}}\n'
        )
        (run / "raw/claude.jsonl").write_text(
            '{"type":"result","usage":{"input_tokens":3,"cache_read_input_tokens":4,'
            '"cache_creation_input_tokens":5,"output_tokens":1}}\n'
        )
        out = self.repo / "ab.md"
        self.invoke("ab_summary.py", "--runs", run, self.run_dir("noskill"), "--out", out)
        report = out.read_text()
        self.assertIn("| skill | demo | B | skill | pass | pass | 0 | 1 | 3 | 3 | 4.125 | 30 | yes | 2 |",
                      report)
        self.assertIn("| noskill | demo | B | noskill |", report)
        self.assertIn("| demo | B | skill | noskill |", report)
        self.assertNotIn(str(self.scratch.name), report)

    def test_ab_summary_does_not_merge_distinct_case_dirs_with_same_names(self):
        for condition in ("skill", "noskill"):
            run = self.run_dir(condition)
            run.mkdir(parents=True)
            (run / "meta.json").write_text(json.dumps({
                "case": "Sales (2026) privateuser", "flow": "B", "condition": condition,
                "case_dir": str(self.home / condition / "Sales (2026) privateuser"),
            }))
        self.env["LOGNAME"] = "privateuser"
        out = self.repo / "ab.md"
        self.invoke("ab_summary.py", "--runs", self.run_dir("skill"), self.run_dir("noskill"),
                    "--out", out)
        report = out.read_text()
        self.assertNotIn("privateuser", report)
        self.assertIn("| Sales (2026) &#91;redacted] | B | skill | — |", report)
        self.assertIn("| Sales (2026) &#91;redacted] | B | — | noskill |", report)

    def test_ab_summary_pairs_legacy_relative_and_absolute_case_dirs(self):
        for condition, case_dir in (("skill", "../home"), ("noskill", str(self.home))):
            run = self.run_dir(condition)
            run.mkdir(parents=True)
            (run / "meta.json").write_text(json.dumps({
                "case": "demo", "flow": "B", "condition": condition, "case_dir": case_dir,
            }))
        out = self.repo / "ab.md"
        self.invoke("ab_summary.py", "--runs", self.run_dir("skill"), self.run_dir("noskill"),
                    "--out", out)
        self.assertIn("| demo | B | skill | noskill |", out.read_text())

    def test_a4_ab_summary_keeps_review_distinct_from_pass(self):
        for condition, verdict in (("skill", "review"), ("noskill", "pass")):
            run = self.run_dir(condition)
            run.mkdir(parents=True)
            (run / "meta.json").write_text(json.dumps({
                "case": "demo", "flow": "B", "condition": condition,
            }))
            (run / "grade.json").write_text(json.dumps({
                "overall": verdict, "numbers_verdict": verdict, "critical_failures": [],
            }))
        out = self.repo / "ab.md"
        self.invoke("ab_summary.py", "--runs", self.run_dir("skill"), self.run_dir("noskill"),
                    "--out", out)
        report = out.read_text()
        self.assertIn("| skill | demo | B | skill | review | review |", report)
        self.assertIn("| demo | B | skill | noskill | review / pass | review / pass |", report)

    def test_install_smoke_dry_run_only_prints_commands(self):
        output = self.invoke("install_smoke.py", "--dry-run")
        self.assertEqual(len(output.splitlines()), 8)
        self.assertIn("~/.cache/ask-first-eda-install/claude/", output)
        self.assertIn("codex exec --json", output)
        self.assertNotIn(str(self.home), output)
        self.assertFalse(self.calls.exists())
        self.assertFalse((self.home / ".cache").exists())
        self.assertFalse((self.repo / "evals/install_smoke.json").exists())

    def test_install_smoke_observes_tool_events_with_fake_clients(self):
        binaries = self.home / "bin"
        binaries.mkdir()
        for client in ("claude", "codex"):
            fake = binaries / client
            fake.write_text(FAKE_SMOKE_CLIENT)
            fake.chmod(0o700)
            self.env[client.upper() + "_BIN"] = str(fake)
        output = self.invoke("install_smoke.py")
        results = json.loads((self.repo / "evals/install_smoke.json").read_text())
        self.assertEqual(len(results), 8)
        for client in ("claude", "codex"):
            rows = [row for row in results if row["client"] == client]
            self.assertEqual([r["observed"] for r in rows], [True, True, False, False])
            self.assertTrue(all(r["pass"] for r in rows))
        self.assertEqual(len(self.calls.read_text().splitlines()), 8)
        self.assertNotIn(str(self.home), output)
        self.assertNotIn(str(self.home), json.dumps(results))
        self.assertFalse((self.home / ".codex/skills").exists())

    def prepare_run(self, *, with_analyst_log=False):
        skill = self.repo / "skills/ask-first-eda"
        (skill / "references").mkdir()
        for path in ("scripts/build_report.py", "scripts/eda_io.py",
                     "references/eda_summary.schema.json"):
            shutil.copyfile(ROOT / "skills/ask-first-eda" / path, skill / path)
        run = self.run_dir("numeric")
        run.mkdir(parents=True)
        (run / "meta.json").write_text(json.dumps({"case": "demo", "flow": "B"}))
        if with_analyst_log:
            write_jsonl(run / "raw/01-analyst.jsonl", [{"type": "turn.completed"}])
        return run

    def check_numbers(self, run):
        self.invoke("numeric_check.py", "--run", run)
        return json.loads((run / "numeric_check.json").read_text())

    def write_raw_events(self, run, filename, items):
        write_jsonl(run / "raw" / filename,
                    ({"type": "item.completed", "item": item} for item in items))

    def test_grader_uses_isolated_home_for_both_attempts(self):
        self.write_source_auth()
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered"))

        self.invoke("grade_run.py", "--run", run)

        first, retry = self.read_calls()
        for call in (first, retry):
            self.assert_role_home(call, run.name, "grader")

    def test_quality_grader_uses_isolated_home(self):
        self.write_source_auth()
        run = self.prepare_run(with_analyst_log=True)
        (self.case / "expected.json").unlink()
        write_transcript(run, ("analyst", "Report delivered"))

        self.invoke("run_case.py", "grade-quality", "--run", run)

        [grader] = self.read_calls()
        self.assert_role_home(grader, run.name, "grader")

    def assert_foreign_skill_grade(self, *, quality_only, status, message):
        run = self.prepare_run()
        write_transcript(run, ("analyst", "Report delivered"))
        if status == "found":
            write_jsonl(run / "raw/01-analyst.jsonl", [command_event(FOREIGN_SKILL_COMMAND)])
        if quality_only:
            (self.case / "expected.json").unlink()
            self.invoke("run_case.py", "grade-quality", "--run", run)
        else:
            self.invoke("grade_run.py", "--run", run)

        grade = json.loads((run / "grade.json").read_text(encoding="utf-8"))
        self.assertIn(message, grade["critical_failures"])
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        check = json.loads((run / "foreign_skill_check.json").read_text(encoding="utf-8"))
        self.assertEqual(check["status"], status)
        self.assertEqual(grade["foreign_skill_check"], check)

    def test_grade_fails_when_analyst_loaded_foreign_skills(self):
        self.assert_foreign_skill_grade(
            quality_only=False, status="found",
            message="Analyst loaded skills outside the evaluated skill. See foreign_skill_check.json.",
        )

    def test_grade_fails_when_foreign_skill_check_is_unavailable(self):
        self.assert_foreign_skill_grade(
            quality_only=False, status="unknown", message="Foreign skill check unavailable.",
        )

    def test_quality_grade_fails_when_analyst_loaded_foreign_skills(self):
        self.assert_foreign_skill_grade(
            quality_only=True, status="found",
            message="Analyst loaded skills outside the evaluated skill. See foreign_skill_check.json.",
        )

    def test_quality_grade_fails_when_foreign_skill_check_is_unavailable(self):
        self.assert_foreign_skill_grade(
            quality_only=True, status="unknown", message="Foreign skill check unavailable.",
        )

    def assert_modified_input_grade_fails(self, *, quality_only):
        self.env["FAKE_GRADE_PASS"] = "1"
        run = self.prepare_run(with_analyst_log=True)
        meta = run / "meta.json"
        metadata = json.loads(meta.read_text())
        metadata["input_modified"] = True
        meta.write_text(json.dumps(metadata))
        write_transcript(run, ("analyst", "Report delivered"))
        (run / "eda_summary.json").write_text('{"metrics": []}')
        if quality_only:
            (self.case / "expected.json").unlink()
            self.invoke("run_case.py", "grade-quality", "--run", run)
        else:
            self.invoke("grade_run.py", "--run", run)

        grade = json.loads((run / "grade.json").read_text())
        self.assertIn("Analyst modified the input copy.", grade["critical_failures"])
        self.assertEqual(grade["overall"], "fail")
        if not quality_only:
            self.assertEqual(grade["numbers_verdict"], "fail")

    def test_grade_fails_when_analyst_modified_input_copy(self):
        self.assert_modified_input_grade_fails(quality_only=False)

    def test_quality_grade_fails_when_analyst_modified_input_copy(self):
        self.assert_modified_input_grade_fails(quality_only=True)

    def test_grade_marks_analyst_access_to_protected_paths_invalid(self):
        run = self.prepare_run()
        (run / "transcript.jsonl").write_text('{"speaker":"analyst","text":"Report delivered"}\n')
        commands = [
            "ls ./evals/cases",
            "cat ../expected.json",
            "cat domain_card.md",
            "ls ./harness/roles",
            "rg pattern ./_private",
            f'cat "{self.repo}/AGENTS.md"',
            f'''bash -lc 'cat "{self.repo}/CLAUDE.md"' ''',
            f'cat "{self.repo}/.venv/bin/python-extra"',
        ]
        self.write_raw_events(run, "02-analyst.jsonl", [
            *({"type": "command_execution", "command": command, "exit_code": 1}
              for command in commands),
            {"type": "mcp_tool_call", "tool": "read_file",
             "arguments": {"path": str(self.repo / "docs/spec.md")}},
        ])
        self.invoke("grade_run.py", "--run", run)
        grade = json.loads((run / "grade.json").read_text())
        leak_check = json.loads((run / "leak_check.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        self.assertEqual(grade["leak_check"], leak_check)
        self.assertEqual(leak_check["status"], "suspect")
        self.assertEqual([entry["line"] for entry in leak_check["evidence"]], list(range(1, 10)))
        self.assertTrue(all(entry["file"] == "raw/02-analyst.jsonl"
                            for entry in leak_check["evidence"]))
        self.assertIn(commands[0], leak_check["evidence"][0]["text"])
        self.assertFalse(self.calls.exists())
        self.assertIn("fail", (run / "grade.md").read_text())

    def test_numeric_tolerance_presence_and_conditional_marker(self):
        self.write_expected([
            {"name": "matches", "value": 1.10, "numerator": 11, "denominator": 10,
             "conditional": False},
            {"name": "wrong_parts", "value": 2, "numerator": 4, "denominator": 2,
             "conditional": True},
            {"name": "absent", "value": 3},
        ], optional=[{"name": "allowed_optional", "value": 4}])
        run = self.prepare_run()
        write_summary(run, [
            {"name": "matches", "value": 1.11, "numerator": 11, "denominator": 10,
             "condition": None},
            {"name": "wrong_parts", "value": 2, "numerator": 5, "denominator": 2,
             "condition": None},
            {"name": "allowed_optional", "value": 4},
            {"name": "unlisted", "value": 5},
        ])
        result = self.check_numbers(run)
        self.assertEqual({metric["name"] for metric in result["matched"]},
                         {"matches", "allowed_optional"})
        self.assertEqual([metric["name"] for metric in result["missing"]], ["absent"])
        self.assertEqual([metric["name"] for metric in result["extra"]], ["unlisted"])
        [mismatch] = result["mismatched"]
        self.assertEqual(mismatch["name"], "wrong_parts")
        self.assertEqual(set(mismatch["differences"]), {"numerator", "conditional"})

    def test_numeric_handles_case_key_variants_and_date_scopes(self):
        self.write_expected([
            {"name": "per_day", "date": "2000-01-01", "numerator_kg": 15,
             "denominator_t": 2, "value": 7.5},
            {"name": "per_day", "date": "2000-01-02", "numerator_kg": 24,
             "denominator_t": 4, "value": 6},
            {"name": "daily_series", "numerators_kg": [15, 24], "denominators_t": [2, 4],
             "values": [7.5, 6]},
            {"name": "daily_counts", "values": [2, 4], "denominator": None},
        ], dates=("2000-01-01", "2000-01-02"))
        run = self.prepare_run()
        write_summary(run, [
            {"name": "per_day (2000-01-02)", "numerator": 24, "denominator": 4, "value": 6},
            {"name": "per_day", "definition": "2000-01-01", "numerator": 15,
             "denominator": 2, "value": 7.5},
            {"name": "daily_series", "date": "2000-01-01", "value": 7.5, "numerator": 15,
             "denominator": 2},
            {"name": "daily_series", "date": "2000-01-02", "value": 6, "numerator": 24,
             "denominator": 4},
            {"name": "daily_counts", "date": "2000-01-02", "value": 4, "denominator": None},
            {"name": "daily_counts", "date": "2000-01-01", "value": 2, "denominator": None},
        ])
        result = self.check_numbers(run)
        self.assertEqual(len(result["matched"]), 4)
        for key in ("missing", "mismatched", "extra"):
            self.assertEqual(result[key], [])

    def test_numeric_fallback_requires_named_evidence_in_last_analyst_message(self):
        self.write_expected([
            {"name": "named_rate", "value": 12, "numerator": 36, "denominator": 3,
             "conditional": True},
            {"name": "daily_count", "date": "2000-01-01", "value": 9_007_199_254_740_993},
            {"name": "unrelated", "value": 50},
            {"name": "prior_only", "value": 21},
        ])
        run = self.prepare_run()
        messages = [
            {"speaker": "analyst", "text": "prior_only: 21"},
            {"speaker": "analyst", "text": "If open: named rate = 36 / 3 = 12\nCount: 50\n"
             "daily count (2000-01-01): 9,007,199,254,740,993"},
            {"speaker": "simulator", "text": "[END]"},
        ]
        (run / "transcript.jsonl").write_text(
            "".join(f"{json.dumps(message)}\n" for message in messages))
        result = self.check_numbers(run)
        self.assertEqual(result["source"], "transcript_text")
        self.assertEqual([metric["name"] for metric in result["matched"]],
                         ["named_rate", "daily_count"])
        self.assertEqual([metric["name"] for metric in result["missing"]],
                         ["unrelated", "prior_only"])

    def test_numeric_matches_localized_tuples_and_records_percent_conversion(self):
        self.write_expected([
            {"name": "part_rate", "numerator": 1, "denominator": 2, "value": 0.5,
             "unit": "ratio"},
            {"name": "change_pct", "numerator": 2, "denominator": 4, "value": 50},
            {"name": "conditional_rate", "numerator": 3, "denominator": 4, "value": 0.75,
             "conditional": True},
        ])
        run = self.prepare_run()
        delivery = run / ".eda-work.test" / "delivery"
        delivery.mkdir(parents=True)
        write_summary(delivery, [
            {"name": "part_rate", "numerator": 7, "denominator": 2, "value": 3.5},
            {"name": "비중", "numerator": 1, "denominator": 2, "value": 50, "unit": "%"},
            {"name": "증감률", "numerator": 2, "denominator": 4, "value": 0.5},
            {"name": "처리 비율", "numerator": 3, "denominator": 4, "value": 0.75,
             "condition": None},
        ])
        result = self.check_numbers(run)
        self.assertEqual(result["missing"], [])
        self.assertEqual([(item["name"], item["matched_via"]) for item in result["matched"]],
                         [("part_rate", "percent_to_ratio"), ("change_pct", "ratio_to_percent")])
        [mismatch] = result["mismatched"]
        self.assertEqual(mismatch["name"], "conditional_rate")
        self.assertEqual(mismatch["differences"]["conditional"]["reason"], "conditional_mismatch")

    def test_numeric_matches_split_daily_tuples_without_matching_labels(self):
        self.write_expected([
            {"name": "daily_rates", "numerators": [2, 6], "denominators": [1, 3], "values": [2, 2]},
        ], dates=("2000-01-01", "2000-01-02"))
        run = self.prepare_run()
        write_summary(run, [
            {"name": "둘째 날 지표", "numerator": 6, "denominator": 3, "value": 2},
            {"name": "첫째 날 집계", "numerator": 2, "denominator": 1, "value": 2},
        ])
        result = self.check_numbers(run)
        [match] = result["matched"]
        self.assertEqual(match["actual"]["numerator"], [2, 6])
        for key in ("missing", "mismatched", "extra"):
            self.assertEqual(result[key], [])

    def test_numeric_sign_agnostic_metrics_require_one_direction_for_all_dates(self):
        expected_path = self.case / "expected.json"
        run = self.prepare_run()
        for listed, first, second, label, bucket in (
            (True, 4, -7, "집계 방식 간 차이", "matched"),
            (True, -4, 7, "집계 방식 간 차이", "matched"),
            (True, -4, -7, "집계 방식 간 차이", "mismatched"),
            (False, -4, 7, "daily_difference", "mismatched"),
        ):
            with self.subTest(listed=listed, values=(first, second)):
                self.write_expected([{"name": "daily_difference", "values": [4, -7]}],
                                    dates=("2000-01-01", "2000-01-02"))
                if listed:
                    expected = json.loads(expected_path.read_text())
                    expected["flows"]["B"]["sign_agnostic_metrics"] = ["daily_difference"]
                    expected_path.write_text(json.dumps(expected))
                write_summary(run, [
                    {"name": f"1월 2일 {label}", "value": second},
                    {"name": f"1월 1일 {label}", "value": first},
                ])
                result = self.check_numbers(run)
                self.assertEqual([item["name"] for item in result[bucket]], ["daily_difference"])
                self.assertEqual(result[bucket][0]["actual"]["value"], [first, second])
                for other in {"matched", "mismatched", "missing", "extra"} - {bucket}:
                    self.assertEqual(result[other], [])

    def test_grade_retries_with_fresh_session_and_sends_bounded_report_text(self):
        self.env["FAKE_GRADE_EMPTY_FIRST"] = "1"
        run = self.prepare_run()
        (run / "transcript.jsonl").write_text('{"speaker":"analyst","text":"Transcript evidence"}\n')
        delivery = run / ".eda-work.test" / "delivery"
        delivery.mkdir(parents=True)
        write_summary(delivery, [], fixture="Summary evidence")
        (delivery / "report.html").write_text(
            '<p>Visible &amp; relevant</p><script>script-secret</script>'
            '<img src="data:image/png;base64,image-secret"><p>' + "x" * 50000 + "</p>"
        )
        self.write_raw_events(run, "01-analyst.jsonl", [
            {"type": "command_execution",
             "command": f'bash -lc \'"{self.repo}/.venv/bin/python" -I analysis.py\'',
             "aggregated_output": "expected.json"},
            {"type": "command_execution",
             "command": f'/bin/zsh -lc "\\"{self.repo}/.venv/bin/python\\" -I analysis.py"'},
            {"type": "agent_message", "text": f"I did not open {self.repo}/AGENTS.md"},
            {"type": "mcp_tool_call", "tool": "read_file",
             "arguments": {"path": "input.csv"}, "result": {"text": "domain_card.md"}},
        ])
        self.write_raw_events(run, "01-simulator.jsonl", [
            {"type": "command_execution", "command": "cat evals/cases/demo/expected.json"},
        ])
        self.invoke("grade_run.py", "--run", run, "--dry-run")
        self.assertTrue((run / "numeric_check.json").exists())
        self.assertEqual(json.loads((run / "leak_check.json").read_text()),
                         {"status": "clean", "evidence": []})
        self.assertFalse((run / "grade.json").exists())
        self.assertFalse(self.calls.exists())
        self.invoke("grade_run.py", "--run", run)
        first, retry = self.read_calls()
        for call in (first, retry):
            self.assertEqual(call["cwd"], str(run))
            self.assertNotIn("resume", call["args"])
            self.assertIn("read-only", call["args"])
            self.assertIn('model_reasoning_effort="high"', call["args"])
            prompt = call["prompt"]
            for text in ("Transcript evidence", "Summary evidence", "Visible & relevant",
                         ".eda-work.test/delivery/report.html", "numeric_check.json"):
                self.assertIn(text, prompt)
            self.assertEqual({marker for marker in DOMAIN_CARD_MARKERS if marker in prompt}, set())
            for text in ("expected-other-flow", "script-secret", "image-secret"):
                self.assertNotIn(text, prompt)
            self.assertLess(len(prompt), 25000)
        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("pass", "pass"))
        self.assertEqual(grade["critical_failures"], [])
        self.assertEqual(grade["quality_scores"], {"traceability": 1})
        self.assertEqual(grade["leak_check"], {"status": "clean", "evidence": []})
        self.assertEqual(grade.get("path_check"), {"status": "clean", "evidence": []})
        path_check = json.loads((run / "path_check.json").read_text(encoding="utf-8"))
        self.assertEqual(grade["path_check"], path_check)
        self.assertIn("report", (run / "grade.md").read_text())

    def test_grade_fails_when_absolute_home_path_is_found(self):
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "[x](/Users/someone/.cache/w/report.html)"))

        self.invoke("grade_run.py", "--run", run)

        grade = json.loads((run / "grade.json").read_text(encoding="utf-8"))
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        self.assertIn("Absolute home path in chat or deliverable. See path_check.json.",
                      grade["critical_failures"])
        self.assertEqual(grade["quality_scores"], {"traceability": 1})
        path_check = json.loads((run / "path_check.json").read_text(encoding="utf-8"))
        self.assertEqual(path_check["status"], "found")
        self.assertEqual(grade["path_check"], path_check)

    def test_grade_fails_with_invalid_summary_even_without_missing_metrics(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered"))
        (run / "eda_summary.json").write_text("{")

        self.invoke("grade_run.py", "--run", run)

        result = json.loads((run / "numeric_check.json").read_text())
        self.assertIn("summary_error", result)
        self.assertEqual(result["missing"], [])
        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        self.assertRegex(json.dumps(grade["critical_failures"], ensure_ascii=False),
                         r"(?i)(summary|json|요약)")

    def test_grade_fails_for_missing_required_metric_even_if_model_passes(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "inventory_count", "value": 17}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered"))
        write_summary(run, [])

        self.invoke("grade_run.py", "--run", run)

        result = json.loads((run / "numeric_check.json").read_text())
        self.assertEqual([item["name"] for item in result["missing"]], ["inventory_count"])
        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        self.assertRegex(json.dumps(grade["critical_failures"], ensure_ascii=False),
                         r"(?i)(inventory_count|missing|누락)")

    def test_grade_fails_for_required_mismatches_or_critical_failures(self):
        self.write_expected([{"name": "rate", "numerator": 10, "denominator": 2, "value": 5}])
        run = self.prepare_run(with_analyst_log=True)
        for metric, message in [
            ({"name": "rate", "numerator": 8, "denominator": 2, "value": 4}, "Wrong tuple"),
            ({"name": "rate", "numerator": 10, "denominator": 2, "value": 5}, "Critical fixture"),
        ]:
            with self.subTest(message=message):
                (run / "transcript.jsonl").write_text(
                    json.dumps({"speaker": "analyst", "text": message}) + "\n"
                )
                write_summary(run, [metric])
                self.invoke("grade_run.py", "--run", run)
                grade = json.loads((run / "grade.json").read_text())
                self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))

    def test_check_run_extracts_pct_from_the_final_analyst_message(self):
        self.write_expected([{"name": "rate", "value": 20, "unit": "%"}])
        run = self.prepare_run()
        write_transcript(run, ("analyst", "rate = 20 pct"))

        result = self.check_numbers(run)

        self.assertEqual(result["source"], "transcript_text")
        self.assertEqual([item["name"] for item in result["matched"]], ["rate"])

    def test_grade_matches_named_html_metric_missing_from_summary(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered."))
        delivery = run / "eda-work" / "delivery"
        delivery.mkdir(parents=True)
        (delivery / "report.html").write_text(
            '<script>Shipped mass = 100 g</script>'
            '<p>Shipped <strong>mass</strong> = 10 kg (raw rows 2–3)</p>', encoding="utf-8"
        )

        for with_summary in (False, True):
            with self.subTest(with_summary=with_summary):
                if with_summary:
                    write_summary(delivery, [])
                result = self.check_numbers(run)
                self.assertEqual([item["name"] for item in result["matched"]], ["shipped_mass"])
                self.invoke("grade_run.py", "--run", run)
                grade = json.loads((run / "grade.json").read_text())
                self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("pass", "pass"))

    def test_grade_uses_delivered_report_when_draft_has_the_expected_value(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered."))
        (run / "draft.html").write_text("<p>Shipped mass = 10 kg</p>")
        delivery = run / "eda-work" / "delivery"
        delivery.mkdir(parents=True)
        (delivery / "report.html").write_text("<p>Shipped mass = 99 kg</p>")

        self.invoke("grade_run.py", "--run", run)

        result = json.loads((run / "numeric_check.json").read_text())
        self.assertEqual(result["matched"], [])
        [mismatch] = result["mismatched"]
        self.assertEqual(mismatch["name"], "shipped_mass")
        self.assertEqual(mismatch["actual"]["value"], 99)
        self.assertEqual(mismatch["source_path"], "eda-work/delivery/report.html")
        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        [call] = self.read_calls()
        self.assertIn("Shipped mass = 99 kg", call["prompt"])
        self.assertNotIn("draft.html", call["prompt"])

    def test_numeric_uses_latest_delivery_when_there_is_no_summary(self):
        self.write_expected([{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run()
        for name, value, mtime in (("delivery", 10, 100), ("delivery-2", 99, 200)):
            report = run / "eda-work" / name / "report.html"
            report.parent.mkdir(parents=True)
            report.write_text(f"<p>Shipped mass = {value} kg</p>")
            os.utime(report, (mtime, mtime))

        result = self.check_numbers(run)

        self.assertEqual(result["matched"], [])
        [mismatch] = result["mismatched"]
        self.assertEqual(mismatch["source_path"], "eda-work/delivery-2/report.html")

    def test_numeric_uses_only_the_report_next_to_the_selected_summary(self):
        self.write_expected([{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run()
        delivery = run / "eda-work" / "delivery"
        delivery.mkdir(parents=True)
        write_summary(delivery, [])
        other = delivery.with_name("delivery-2")
        other.mkdir()
        (other / "report.html").write_text("<p>Shipped mass = 10 kg</p>")
        (delivery / "draft.html").write_text("<p>Shipped mass = 10 kg</p>")
        report = delivery / "report.html"
        report.write_text("<p>Shipped mass = 99 kg</p>")

        result = self.check_numbers(run)

        self.assertEqual(result["matched"], [])
        [mismatch] = result["mismatched"]
        self.assertEqual(mismatch["source_path"], "eda-work/delivery/report.html")

        report.unlink()
        result = self.check_numbers(run)
        self.assertEqual([item["name"] for item in result["missing"]], ["shipped_mass"])

    def test_numeric_marks_conflicting_values_in_one_report_mismatched(self):
        self.write_expected([{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run()
        delivery = run / "eda-work" / "delivery"
        delivery.mkdir(parents=True)
        report = delivery / "report.html"

        for second_claim in ("</p><p>Shipped mass = 99 kg", "; Shipped mass = 99 kg"):
            with self.subTest(second_claim=second_claim):
                report.write_text(f"<p>Shipped mass = 10 kg{second_claim}</p>")
                result = self.check_numbers(run)
                self.assertEqual(result["matched"], [])
                [mismatch] = result["mismatched"]
                self.assertEqual(mismatch["name"], "shipped_mass")
                self.assertEqual(mismatch["source_path"], "eda-work/delivery/report.html")

        report.write_text("<p>Shipped mass = 10 kg</p><p>Shipped mass = 10000 g</p>")
        result = self.check_numbers(run)
        [match] = result["matched"]
        self.assertEqual(match["name"], "shipped_mass")
        self.assertEqual(match["source_path"], "eda-work/delivery/report.html")
        self.assertEqual(result["mismatched"], [])

    def test_numeric_round3_completes_structured_month_year(self):
        self.write_expected([{"name": "Yield", "date": "2025-05", "value": 10}])
        run = self.prepare_run()
        write_summary(run, [{"name": "Yield in May 2026", "month": "May", "value": 10}])

        result = self.check_numbers(run)

        self.assertEqual(result["matched"], [])
        self.assertEqual(result["mismatched"], [])
        self.assertEqual([item["name"] for item in result["missing"]], ["Yield"])

    def test_numeric_round3_rejects_comparison_month_in_definition(self):
        self.write_expected([{"name": "Yield", "date": "2025-05", "value": 10}])
        run = self.prepare_run()
        write_summary(run, [{"name": "Yield", "value": 10,
                             "definition": "2025-06 monthly total, compared with 2025-05."}])

        result = self.check_numbers(run)

        self.assertEqual(result["matched"], [])
        self.assertEqual(result["mismatched"], [])
        self.assertEqual([item["name"] for item in result["missing"]], ["Yield"])

    def test_numeric_round3_rejects_conflicting_transcript_values(self):
        self.write_expected([{"name": "Shipped mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run()
        write_transcript(run, ("analyst", "Shipped mass = 99 kg; Shipped mass = 10 kg"))

        result = self.check_numbers(run)

        self.assertEqual(result["source"], "transcript_text")
        self.assertEqual(result["matched"], [])
        self.assertEqual([item["name"] for item in result["mismatched"]], ["Shipped mass"])

    def test_numeric_round3_matches_actual_and_conditional_report_values(self):
        self.write_expected([
            {"name": "Shipped mass", "value": 10, "unit": "kg"},
            {"name": "Shipped mass", "value": 99, "unit": "kg", "condition": "추가 주문 출하"},
        ])
        run = self.prepare_run()
        report = run / "delivery" / "report.html"
        report.parent.mkdir()

        for separator in ("</p><p>", ". ", "; "):
            with self.subTest(separator=separator):
                report.write_text(f"<p>Shipped mass = 10 kg{separator}"
                                  "If the extra order ships, shipped mass = 99 kg</p>")
                result = self.check_numbers(run)
                self.assertEqual(result["missing"], [])
                self.assertEqual(result["mismatched"], [])
                self.assertEqual([item["actual"]["value"] for item in result["matched"]], [10, 99])
                self.assertEqual([item["actual"]["conditional"] for item in result["matched"]],
                                 [False, True])

    def test_numeric_round3_delivery_number_outranks_mtime(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "Shipped mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered."))
        for name, value, mtime in (("delivery", 99, 200), ("delivery-2", 10, 100)):
            report = run / name / "report.html"
            report.parent.mkdir()
            report.write_text(f"<p>Shipped mass = {value} kg</p>")
            os.utime(report, (mtime, mtime))

        self.invoke("grade_run.py", "--run", run)

        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("pass", "pass"))
        result = json.loads((run / "numeric_check.json").read_text())
        [match] = result["matched"]
        self.assertEqual(match["source_path"], "delivery-2/report.html")

    def test_numeric_round3_report_conflicts_use_tolerance_in_expected_unit(self):
        self.write_expected([{"name": "Shipped mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run()
        report = run / "delivery" / "report.html"
        report.parent.mkdir()

        for claims in (("10003 g", "10004 g"), ("10.003 kg", "10.004 kg")):
            with self.subTest(claims=claims):
                report.write_text("".join(f"<p>Shipped mass = {claim}</p>" for claim in claims))
                result = self.check_numbers(run)
                self.assertEqual(result["mismatched"], [])
                self.assertEqual([item["name"] for item in result["matched"]], ["Shipped mass"])

    def test_grade_rejects_metrics_only_summary_even_when_report_has_the_right_value(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered."))
        write_summary(run, [{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        summary = run / "eda_summary.json"
        summary.write_text(json.dumps({"metrics": json.loads(summary.read_text())["metrics"]}))
        (run / "report.html").write_text("<p>Shipped mass = 10 kg</p>")

        self.invoke("grade_run.py", "--run", run)

        result = json.loads((run / "numeric_check.json").read_text())
        self.assertRegex(result.get("summary_error", ""), r"(?i)schema.*datasets")
        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        self.assertIn(result["summary_error"], grade["critical_failures"])

    def test_check_run_keeps_a_summary_mismatch_when_html_has_the_expected_value(self):
        self.write_expected([{"name": "shipped_mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run()
        write_summary(run, [{"name": "shipped_mass", "value": 10, "unit": "g"}])
        (run / "report.html").write_text("<p>Shipped mass = 10 kg</p>")

        result = self.check_numbers(run)

        self.assertEqual([item["name"] for item in result["mismatched"]], ["shipped_mass"])


    def test_a4_unknown_unit_records_review_in_grade(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "Shipped mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered."))
        write_summary(run, [{"name": "Shipped mass", "value": 10, "unit": "crates"}])

        self.invoke("grade_run.py", "--run", run)

        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("review", "review"))
        self.assertEqual(grade["review_reasons"], [{"name": "Shipped mass", "bucket": "unverified"}])
        self.assertIn("Shipped mass", (run / "grade.md").read_text())
        self.assertIn("unverified", (run / "grade.md").read_text())
        result = json.loads((run / "numeric_check.json").read_text())
        [entry] = result["unverified"]
        self.assertEqual(entry["reason"], "unknown_unit")
        self.assertEqual(entry["units"], {"expected": "kg", "actual": "crates"})
        self.assertEqual(result["matched"] + result["mismatched"] + result["missing"], [])

    def test_a4_selected_report_is_checked_after_summary_matches(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "Shipped mass", "value": 10, "unit": "kg"}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Report delivered."))
        delivery = run / "delivery"
        delivery.mkdir()
        write_summary(delivery, [{"name": "Shipped mass", "value": 10, "unit": "kg"}])
        (run / "report.html").write_text("<p>Shipped mass = 500 kg</p>")
        report = delivery / "report.html"

        for text, bucket in (("Shipped mass = 99 kg", "mismatched"),
                             ("Shipped mass = 10 kg", "matched"),
                             ("Shipped mass = 10004 g", "matched"),
                             ("Warehouse capacity = 99 kg", "matched")):
            with self.subTest(text=text):
                report.write_text(f"<p>{text}</p>")
                result = self.check_numbers(run)
                self.assertEqual([entry["name"] for entry in result[bucket]], ["Shipped mass"])
                if bucket == "mismatched":
                    [entry] = result[bucket]
                    self.assertEqual(result["matched"], [])
                    self.assertEqual(entry["reason"], "report_conflict")
                    self.assertEqual(entry["source_path"], "delivery/report.html")
                    self.assertEqual(entry["differences"]["report_conflict"]["claims"],
                                     [{"value": 10, "unit": "kg"}, {"value": 99, "unit": "kg"}])
                    self.invoke("grade_run.py", "--run", run)
                    grade = json.loads((run / "grade.json").read_text())
                    self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))

    def test_report_conflicts_require_compatible_known_unit_dimensions(self):
        run = self.prepare_run()
        report = run / "report.html"
        for unit, display, conflict in (
            ("kg", "1건", False),
            ("kg", "99 kg", True),
            ("kg", "99", True),
            ("%", "45건", False),
        ):
            with self.subTest(unit=unit, display=display):
                metric = {"name": "Measured value", "value": 10, "unit": unit}
                self.write_expected([metric])
                write_summary(run, [metric])
                report.write_text(f"<p>Measured value = {display}</p>")

                result = self.check_numbers(run)

                self.assertEqual(result["missing"], [])
                if conflict:
                    [entry] = result["mismatched"]
                    self.assertEqual(entry["reason"], "report_conflict")
                else:
                    self.assertEqual(result["mismatched"], [])
                    self.assertEqual([entry["name"] for entry in result["matched"]], [metric["name"]])

    def test_a4_rounding_uses_displayed_html_decimal_places(self):
        run = self.prepare_run()
        report = run / "report.html"
        for value, display, bucket in (
            (111.11111111111111, "111.11", "matched"),
            (10, "10.4", "mismatched"),
            (10, "10", "matched"),
            (10.4, "10", "matched"),
            (10.5, "10", "matched"),
            (10.51, "10", "mismatched"),
            (10.04, "10.0", "matched"),
            (10.04, "10.00", "mismatched"),
        ):
            with self.subTest(value=value, display=display):
                metric = {"name": "Batch rate", "value": value}
                self.write_expected([metric], tolerance=0.000001)
                write_summary(run, [metric])
                report.write_text(f"<p>Batch rate = {display}</p>")

                result = self.check_numbers(run)

                self.assertEqual([entry["name"] for entry in result[bucket]], ["Batch rate"])
                if bucket == "mismatched":
                    self.assertEqual(result[bucket][0]["reason"], "report_conflict")

    def test_a4_rounding_converts_display_precision_with_the_unit(self):
        run = self.prepare_run()
        report = run / "report.html"
        for value, unit, display, bucket in (
            (0.1111111111111111, "ratio", "11.11%", "matched"),
            (0.1111111111111111, "ratio", "11.10%", "mismatched"),
            (10.0004, "kg", "10000 g", "matched"),
            (10.0006, "kg", "10000 g", "mismatched"),
        ):
            with self.subTest(value=value, unit=unit, display=display):
                metric = {"name": "Batch rate", "value": value, "unit": unit}
                self.write_expected([metric], tolerance=0.000001)
                write_summary(run, [metric])
                report.write_text(f"<p>Batch rate = {display}</p>")

                result = self.check_numbers(run)

                self.assertEqual([entry["name"] for entry in result[bucket]], ["Batch rate"])

    def test_report_rounding_matches_the_answer_key(self):
        self.write_expected([{"name": "Batch rate", "value": 111.11111111111111}], tolerance=0.000001)
        run = self.prepare_run()
        delivery = run / "delivery"
        delivery.mkdir()
        report = delivery / "report.html"
        rounded = "<p>Batch rate = 111.11</p>"
        report.write_text("<p>Batch rate = 111.11111111111111</p>" + rounded)

        result = self.check_numbers(run)

        self.assertEqual([entry["name"] for entry in result["matched"]], ["Batch rate"])
        report.write_text(rounded)

        result = self.check_numbers(run)

        self.assertEqual([entry["name"] for entry in result["matched"]], ["Batch rate"])

    def test_a4_natural_sentence_with_unparsed_formula_requires_review(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "Operating throughput", "value": 20}])
        run = self.prepare_run(with_analyst_log=True)
        sentence = "Operating throughput was computed as 60/3=20 " + "for the window " * 20
        write_transcript(run, ("analyst", sentence))

        self.invoke("grade_run.py", "--run", run)

        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("review", "review"))
        self.assertEqual(grade["review_reasons"], [{"name": "Operating throughput", "bucket": "unparsed"}])
        result = json.loads((run / "numeric_check.json").read_text())
        self.assertEqual(result["missing"], [])
        [entry] = result["unparsed"]
        self.assertIn("60/3=20", entry["excerpt"])
        self.assertLessEqual(len(entry["excerpt"]), 200)

    def test_a4_unparsed_evidence_requires_a_numeric_claim_in_the_same_sentence(self):
        self.write_expected([{"name": "Operating throughput", "value": 20}])
        run = self.prepare_run()
        delivery = run / "delivery"
        delivery.mkdir()
        report = delivery / "report.html"
        for text, bucket in (("Operating throughput came to 20 units per hour", "unparsed"),
                             ("Operating throughput is discussed below. The window had 3 hours", "missing"),
                             ("Operating throughput was monitored on 2025-01-01", "missing"),
                             ("The window had 3 hours and 60/3=20", "missing")):
            with self.subTest(text=text):
                report.write_text(f"<p>{text}</p>")
                result = self.check_numbers(run)
                self.assertEqual([entry["name"] for entry in result.get(bucket, [])], ["Operating throughput"])
                self.assertEqual(len(result["missing"]) + len(result.get("unparsed", [])), 1)

    def test_a4_required_missing_takes_precedence_over_review(self):
        self.env["FAKE_GRADE_PASS"] = "1"
        self.write_expected([{"name": "Operating throughput", "value": 20},
                             {"name": "Shipped mass", "value": 10}])
        run = self.prepare_run(with_analyst_log=True)
        write_transcript(run, ("analyst", "Operating throughput was computed as 60/3=20."))

        self.invoke("grade_run.py", "--run", run)

        grade = json.loads((run / "grade.json").read_text())
        self.assertEqual((grade["numbers_verdict"], grade["overall"]), ("fail", "fail"))
        self.assertIn("Missing required metrics: Shipped mass", grade["critical_failures"])


def write_summary(directory, metrics, **extra):
    metric_defaults = {"definition": "", "numerator": None, "denominator": None, "unit": "",
                       "condition": None, "source_refs": [], "depends_on_ambiguity_ids": []}
    summary = {
        "datasets": [], "row_counts": [], "ambiguity_log": [], "charts": [], "exclusions": [],
        "metrics": [{**metric_defaults, **metric} for metric in metrics], **extra,
    }
    (directory / "eda_summary.json").write_text(json.dumps(summary))


def write_transcript(run, *messages):
    write_jsonl(run / "transcript.jsonl",
                ({"speaker": speaker, "text": text} for speaker, text in messages))


def eval_function(script, name):
    function = runpy.run_path(str(ROOT / "evals" / script)).get(name)
    assert callable(function), f"{script} must define {name}"
    return function


@pytest.mark.parametrize(("windows", "command", "status"), [
    pytest.param(False, "'{venv}/bin/python3' -I ./ask-first-eda/scripts/check_install.py",
                 "clean", id="versioned-python"),
    pytest.param(False, "'{venv}/bin/python3.13' -I ./analysis.py", "clean", id="minor-version"),
    pytest.param(True, r'"{venv}\Scripts\python.exe" -I .\analysis.py', "clean", id="windows-python"),
    pytest.param(False, "cat '{root}/evals/cases/x/expected.json'", "suspect", id="protected-file"),
    pytest.param(False, "'{venv}/bin/python3' '{root}/evals/numeric_check.py'",
                 "suspect", id="other-repo-file"),
    pytest.param(True, r'"{venv}\Scripts\python.exe" "{root}\evals\numeric_check.py"',
                 "suspect", id="windows-other-repo-file"),
    pytest.param(False, "cat '{venv}/bin/python3-extra'", "suspect", id="non-interpreter"),
])
def test_leak_check_allows_only_virtualenv_interpreter_paths(tmp_path, monkeypatch, windows, command, status):
    check_leaks = eval_function("grade_run.py", "check_leaks")
    repo = PureWindowsPath(r"C:\workspace\test repo") if windows else tmp_path / "test repo"
    monkeypatch.setitem(check_leaks.__globals__, "ROOT", repo)
    raw = tmp_path / "raw"
    raw.mkdir()
    command = command.format(root=repo, venv=repo / ".venv")
    write_jsonl(raw / "01-analyst.jsonl", [{
        "type": "item.completed", "item": {"type": "command_execution", "command": command},
    }])

    result = check_leaks(tmp_path)

    assert result["status"] == status
    assert [entry["text"] for entry in result["evidence"]] == ([command] if status == "suspect" else [])


@pytest.mark.parametrize("inside_repo", [False, True], ids=["external", "internal"])
def test_case_dir_text_does_not_require_relpath(tmp_path, monkeypatch, inside_repo):
    case_dir_text = eval_function("run_case.py", "case_dir_text")
    repo = tmp_path / "repo"
    case = (repo if inside_repo else tmp_path / "external") / "cases" / "demo"
    monkeypatch.setitem(case_dir_text.__globals__, "ROOT", repo)

    def cross_drive_relpath(*args, **kwargs):
        raise ValueError("path is on mount 'C:', start on mount 'D:'")

    with monkeypatch.context() as patch:
        patch.setattr(os.path, "relpath", cross_drive_relpath)
        actual = case_dir_text(case)

    assert actual == ("cases/demo" if inside_repo else case.as_posix())


def test_a5_default_case_inputs_ignore_unlisted_files_and_flow_body(tmp_path):
    (tmp_path / "case.md").write_text("# Case\n\n## A\n\ninputs: answer.csv\n")
    for name in ("input.csv", "notes.md", "answer.csv"):
        (tmp_path / name).touch()

    case_inputs = eval_function("run_case.py", "case_inputs")
    assert case_inputs(tmp_path) == [tmp_path / "input.csv"]


@pytest.mark.parametrize("entry", ["missing.csv", "../x", "nested/x", r"nested\x",
                                   "a..csv", "input.csv", "domain_card.md", "expected.json"])
def test_a5_case_inputs_reject_invalid_allowlist_entries(tmp_path, entry):
    (tmp_path / "case.md").write_text(f"# Case\ninputs: {entry}\n")
    (tmp_path / "target.csv").touch()
    (tmp_path / "input.csv").symlink_to(tmp_path / "target.csv")
    for name in ("a..csv", "domain_card.md", "expected.json"):
        (tmp_path / name).touch()
    case_inputs = eval_function("run_case.py", "case_inputs")

    with pytest.raises(ValueError):
        case_inputs(tmp_path)


def test_a5_default_case_inputs_reject_symlinks(tmp_path):
    (tmp_path / "case.md").write_text("# Case\n")
    (tmp_path / "input.csv").symlink_to(tmp_path / "missing.csv")
    case_inputs = eval_function("run_case.py", "case_inputs")

    with pytest.raises(ValueError):
        case_inputs(tmp_path)


def test_a5_existing_case_input_selection_is_unchanged():
    case_inputs = eval_function("run_case.py", "case_inputs")
    assert {
        case.name: [path.name for path in case_inputs(case)]
        for case in (ROOT / "evals/cases").iterdir() if (case / "case.md").is_file()
    } == {
        "orders_nested_json": ["input.json"],
        "production_next_month": ["input.xlsx"],
        "throughput_hourly": ["input.csv"],
        "utility_batches_excel": ["input.xlsx"],
    }


def test_a5_repo_metadata_reports_head_and_dirty_status():
    git = shutil.which("git")
    if git is None:
        pytest.skip("Git is unavailable")
    head = subprocess.run([git, "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    if head.returncode:
        pytest.skip("No repository HEAD in this source checkout")
    status = subprocess.check_output(
        [git, "status", "--porcelain", "--untracked-files=normal"], cwd=ROOT, text=True,
    )
    repo_metadata = eval_function("run_case.py", "repo_metadata")
    result = repo_metadata()
    assert re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", result["repo_commit"])
    assert result["repo_commit"] == head.stdout.strip()
    assert result["repo_dirty"] is bool(status)


def test_a5_skill_fingerprint_depends_on_paths_and_contents(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    files = {"A.md": "alpha", "B.md": "beta"}
    for folder, names in ((first, files), (second, reversed(files))):
        folder.mkdir()
        for name in names:
            (folder / name).write_text(files[name])

    fingerprint = eval_function("run_case.py", "skill_fingerprint")
    original = fingerprint(first)
    assert fingerprint(second) == original
    (second / "B.md").rename(second / "C.md")
    assert fingerprint(second) != original
    (second / "C.md").rename(second / "B.md")
    (second / "B.md").write_text("updated")
    assert fingerprint(second) != original


def test_a5_delivery_artifacts_are_copied_without_treating_results_as_summary(tmp_path):
    work, run = tmp_path / "work", tmp_path / "run"
    (work / "delivery").mkdir(parents=True)
    run.mkdir()
    (work / "delivery/report.html").write_text("<html><p>Example metric: 8</p></html>")
    (work / "delivery/results.json").write_text('{"example_metric": 8}')
    (work / "results.json").write_text('{"scratch": true}')
    copy_artifacts = eval_function("run_case.py", "copy_artifacts")
    report_path = eval_function("numeric_check.py", "report_path")
    summary_path = eval_function("numeric_check.py", "summary_path")

    assert set(copy_artifacts(work, run, [])) == {"delivery/report.html", "delivery/results.json"}
    assert (run / "delivery/results.json").read_bytes() == (work / "delivery/results.json").read_bytes()
    assert summary_path(run) is None
    assert report_path(run, None) == run / "delivery/report.html"

    (work / "delivery/eda_summary.json").write_text("{}")
    list(copy_artifacts(work, run, []))
    assert summary_path(run) == run / "delivery/eda_summary.json"
    assert report_path(run, summary_path(run)) == run / "delivery/report.html"


def test_numeric_selects_first_identical_summary_and_its_report(tmp_path):
    summary_path = eval_function("numeric_check.py", "summary_path")
    report_path = eval_function("numeric_check.py", "report_path")
    for name in ("eda-work/delivery", "delivery"):
        delivery = tmp_path / name
        delivery.mkdir(parents=True)
        (delivery / "eda_summary.json").write_bytes(b'{"metrics": []}')
        (delivery / "report.html").write_bytes(b"<p>Report</p>")

    summary = summary_path(tmp_path)

    assert summary == tmp_path / "delivery/eda_summary.json"
    assert report_path(tmp_path, summary) == tmp_path / "delivery/report.html"


def test_numeric_rejects_summaries_with_different_bytes(tmp_path):
    summary_path = eval_function("numeric_check.py", "summary_path")
    for name, content in (("delivery", b'{"metrics": []}'), ("eda-work/delivery", b'{"metrics":[]}')):
        delivery = tmp_path / name
        delivery.mkdir(parents=True)
        (delivery / "eda_summary.json").write_bytes(content)

    with pytest.raises(ValueError, match="Multiple eda_summary.json files found"):
        summary_path(tmp_path)


def test_numeric_selects_first_identical_report_without_a_summary(tmp_path):
    report_path = eval_function("numeric_check.py", "report_path")
    for name, mtime in (("eda-work/delivery", 200), ("delivery", 100)):
        report = tmp_path / name / "report.html"
        report.parent.mkdir(parents=True)
        report.write_bytes(b"<p>Report</p>")
        os.utime(report, (mtime, mtime))

    assert report_path(tmp_path, None) == tmp_path / "delivery/report.html"


def test_a5_grader_scores_charts_on_contribution():
    grader = (ROOT / "harness/roles/grader.md").read_text()
    assert re.search(r"(?i)evaluate charts by their contribution to answering the question", grader)
    assert not re.search(r"(?im)^(?!.*\bnot\b).*\b(?:penali[sz]e|reward|deduct)\b.*\b(?:chart count|number of charts)\b", grader)


@pytest.fixture(scope="module")
def compare_metrics():
    return eval_function("numeric_check.py", "compare_metrics")


@pytest.mark.parametrize(("changes", "bucket", "differences"), [
    pytest.param({}, "matched", set(), id="null-numerator"),
    pytest.param({"name": "reported quantity"}, "matched", set(), id="different-name"),
    pytest.param({"value": 24}, "mismatched", {"value"}, id="wrong-value"),
    pytest.param({"numerator": 30}, "mismatched", {"numerator"}, id="wrong-numerator"),
    pytest.param({"numerator": 25}, "matched", set(), id="matching-numerator"),
    pytest.param({"denominator": 24}, "matched", set(), id="submitted-denominator-is-ignored"),
    pytest.param({"name": "reported quantity", "denominator": 24, "numerator": 25},
                 "matched", set(), id="ignore-denominator-across-names"),
    pytest.param({"denominator": 24, "numerator": 30}, "mismatched", {"numerator"},
                 id="still-check-submitted-numerator"),
])
def test_compare_metrics_accepts_null_numerator_for_null_denominator(compare_metrics, changes, bucket, differences):
    reference = {"name": "measurement", "value": 25, "numerator": 25, "denominator": None}
    actual = {**reference, "numerator": None, **changes}

    result = compare_metrics([reference], [], [actual], Decimal("0.01"), [])

    [entry] = result[bucket]
    assert entry["name"] == reference["name"]
    assert set(entry.get("differences", {})) == differences


def test_compare_metrics_matches_throughput_with_localized_units(compare_metrics):
    required = [
        {"name": "elapsed_hour_throughput", "unit": "units/h", "value": 15,
         "numerator": 60, "denominator": 4, "conditional": True},
        {"name": "operating_hour_throughput", "unit": "units/h", "value": 20,
         "numerator": 60, "denominator": 3, "conditional": True},
    ]
    actual = [
        {"name": "기록된 전체 시간 기준 처리량", "unit": "개/시간", "value": 15.0,
         "numerator": 60, "denominator": 4, "condition": "기록된 시간을 모두 포함하는 경우"},
        {"name": "라인 운영 시간 기준 처리량", "unit": "개/시간", "value": 20.0,
         "numerator": 60, "denominator": 3, "condition": "라인이 운영된 시간만 포함하는 경우"},
    ]

    result = compare_metrics(required, [], actual, Decimal("0"), [])

    assert [item["name"] for item in result["matched"]] == [
        "elapsed_hour_throughput", "operating_hour_throughput",
    ], result


def test_compare_metrics_matches_utility_metrics_with_localized_dates(compare_metrics):
    dates = ["2026-01-01", "2026-01-02"]
    required = [
        {"name": "plant_rate", "date": dates[0], "value": 111.1111111111,
         "numerator_kg": 500, "denominator_t": 4.5},
        {"name": "plant_rate", "date": dates[1], "value": 307.1428571429,
         "numerator_kg": 4300, "denominator_t": 14},
        {"name": "mean_defined_batch_rate", "date": dates[0], "value": 150,
         "numerator_sum_of_rates": 600, "denominator_batches": 4},
        {"name": "mean_defined_batch_rate", "date": dates[1], "value": 225,
         "numerator_sum_of_rates": 900, "denominator_batches": 4},
        {"name": "mean_batch_minus_plant", "unit": "kg steam/t product",
         "values": [38.8888888889, -82.1428571429]},
    ]
    actual = [
        {"name": "1월 1일 전체 원단위", "unit": "kg/t", "value": 111.11111111111111,
         "numerator": 500, "denominator": 4.5},
        {"name": "1월 2일 전체 원단위", "unit": "kg/t", "value": 307.14285714285717,
         "numerator": 4300, "denominator": 14},
        {"name": "1월 1일 배치별 원단위 단순 평균", "unit": "kg/t", "value": 150,
         "numerator": 600, "denominator": 4},
        {"name": "1월 2일 배치별 원단위 단순 평균", "unit": "kg/t", "value": 225,
         "numerator": 900, "denominator": 4},
        {"name": "1월 2일 집계 방식 간 차이", "unit": "kg/t", "value": -82.14285714285717},
        {"name": "1월 1일 집계 방식 간 차이", "unit": "kg/t", "value": 38.888888888888886},
    ]

    result = compare_metrics(required, [], actual, Decimal("0.000001"), dates)

    assert [(item["name"], item.get("date")) for item in result["matched"]] == [
        ("plant_rate", dates[0]), ("plant_rate", dates[1]),
        ("mean_defined_batch_rate", dates[0]), ("mean_defined_batch_rate", dates[1]),
        ("mean_batch_minus_plant", None),
    ], result
    assert result["matched"][-1]["actual"]["value"] == [38.888888888888886, -82.14285714285717]


def test_compare_metrics_matches_daily_production_shares_in_percent(compare_metrics):
    dates = ["2026-01-01", "2026-01-02"]
    required = [
        {"name": "H_share_of_production", "unit": "fraction of tonnes",
         "numerators_t": [0.5, 10], "denominators_t": [4.5, 14],
         "values": [0.1111111111, 0.7142857143]},
    ]
    actual = [
        {"name": "1월 2일 품목 H 생산 비중", "unit": "%", "value": 71.42857142857143,
         "numerator": 10, "denominator": 14},
        {"name": "1월 1일 품목 H 생산 비중", "unit": "%", "value": 11.11111111111111,
         "numerator": 0.5, "denominator": 4.5},
    ]

    result = compare_metrics(required, [], actual, Decimal("0.000000001"), dates)

    assert result["missing"] == result["mismatched"] == [], result
    [match] = result["matched"]
    assert match["matched_via"] == "daily_tuple+percent_to_ratio"
    assert match["actual_names"] == [actual[1]["name"], actual[0]["name"]]


def test_compare_metrics_does_not_match_values_swapped_between_lines(compare_metrics):
    required = [
        {"name": "생산량", "line": "A라인", "value": 10},
        {"name": "생산량", "line": "B라인", "value": 20},
    ]
    actual = [
        {"name": "B라인 생산량", "value": 10},
        {"name": "A라인 생산량", "value": 20},
    ]

    result = compare_metrics(required, [], actual, Decimal("0.01"), [])

    assert result["matched"] == []


def test_compare_metrics_matches_list_values_and_components(compare_metrics):
    required = [{"name": "daily_series", "values": [7.5, 6], "numerators_kg": [15, 24],
                 "denominators_t": [2, 4]}]
    actual = [{"name": "daily_series", "values": [7.5, 6], "numerator": [15, 24],
               "denominator": [2, 4]}]

    result = compare_metrics(required, [], actual, Decimal("0.01"), [])

    assert [item["name"] for item in result["matched"]] == ["daily_series"]


@pytest.mark.parametrize(("reference", "actual", "bucket"), [
    pytest.param({"date": "2025-01-02"},
                 {"name": "yield 1/2", "definition": "observations on 2026-01-02"},
                 "missing", id="fraction-before-wrong-year"),
    pytest.param({"date": "2025-01-02"}, {"name": "yield 1/2"},
                 "missing", id="fraction-without-date"),
    pytest.param({"date": "2025-05"}, {"date": "2025-05"}, "matched", id="structured-month"),
    pytest.param({"date": "2025-05"}, {"date": "2025-05-04", "definition": "daily total"},
                 "missing", id="daily-value-is-not-monthly"),
    pytest.param({"date": "2025-05-04", "month": "2025-05"}, {"date": "2025-05-04"},
                 "matched", id="daily-date-with-consistent-month-field"),
    pytest.param({"date": "2025-04-01"},
                 {"date": "2025-04-01", "definition": "Yield may increase after calibration."},
                 "matched", id="may-is-modal-verb"),
    pytest.param({"date": "2025-05"}, {"name": "Output in May 2025"},
                 "matched", id="month-with-year-in-text"),
    pytest.param({"date": "2025-05"}, {"name": "Output in May"},
                 "matched", id="month-after-preposition"),
    pytest.param({"month": "2025-05"}, {"month": "May"}, "matched", id="english-month-name"),
    pytest.param({"date": "2025-05"}, {"name": "yield in 5월", "date": "2026-05"},
                 "missing", id="structured-year-takes-precedence"),
    pytest.param({"date": "2025-05"}, {"date": "2025-05", "month": "June"},
                 "missing", id="conflicting-date-and-month"),
    pytest.param({"date": "2025-01-02"},
                 {"name": "yield on 2025-01-02", "definition": "observations on 2026-01-02"},
                 "missing", id="conflicting-text-dates"),
    pytest.param({"date": "2025-01-02"},
                 {"date": "2025-01-02", "definition": "observations on 2026-01-02"},
                 "missing", id="conflicting-structured-and-text-dates"),
    pytest.param({"line": "A"}, {"line": "A"}, "matched", id="structured-line"),
    pytest.param({"line": "A"}, {"line": "B", "definition": "line A"},
                 "missing", id="structured-line-takes-precedence"),
])
def test_compare_metrics_matches_consistent_dates_and_structured_scope(
    compare_metrics, reference, actual, bucket,
):
    metric = {"name": "yield", "value": 10}

    optional = [{"name": "other period", "date": "2025-02-01", "value": 20}]
    result = compare_metrics([{**metric, **reference}], optional, [{**metric, **actual}],
                             Decimal("0.01"), [])

    assert [item["name"] for item in result[bucket]] == ["yield"], result


@pytest.mark.parametrize(("name", "actual", "value", "unit"), [
    pytest.param("production",
                 {"name": "5월 A라인 생산량",
                  "definition": "정기 보전일인 5월 13일 생산량은 해당 없음으로 처리한다."},
                 266170, "kg", id="production-with-maintenance-day-in-definition"),
    pytest.param("utilization",
                 {"name": "5월 A라인 가동률",
                  "definition": "5월 13일 정기 보전일은 가동률 집계에서 제외한다."},
                 82, "%", id="utilization-with-maintenance-day-in-definition"),
    pytest.param("production", {"name": "5월 13일 A라인 생산량", "date": "2025-05"},
                 266170, "kg", id="structured-date-before-name"),
    pytest.param("production", {"name": "5월 13일 A라인 생산량", "month": "2025-05"},
                 266170, "kg", id="structured-month-before-name"),
    pytest.param("production", {"name": "5월 A라인 생산량", "condition": "5월 13일 제외"},
                 266170, "kg", id="name-before-condition"),
])
def test_compare_metrics_matches_month_using_identifying_date(compare_metrics, name, actual, value, unit):
    required = [{"name": name, "month": "2025-05", "line": "A", "value": value, "unit": unit}]

    result = compare_metrics(required, [], [{**actual, "value": value, "unit": unit}], Decimal("0.01"), [])

    assert [item["name"] for item in result["matched"]] == [name], result


@pytest.mark.parametrize(("actual", "bucket"), [
    pytest.param({"definition": "5월 일자 행의 실제 가동시간 396시간 ÷ (계획 대상 22일 × 20시간) × 100. "
                                "5월 13일 정기 보전은 실제 0시간."},
                 "matched", id="daily-rows"),
    pytest.param({"definition": "5월 일보 실제 가동 396시간 ÷ 계획 440시간 × 100. "
                                "5월 13일 정기 보전 0시간 및 계획 20시간 포함."},
                 "matched", id="daily-report"),
    pytest.param({"definition": "6월 실적을 참고한다.", "condition": "5월 13일 정기 보전 포함"},
                 "matched", id="matching-month-in-condition"),
    pytest.param({"definition": "6월 일보. 6월 13일 정기 보전 포함."},
                 "missing", id="only-another-month"),
    pytest.param({"definition": "2026년 5월 일보. 2026년 5월 13일 정기 보전 포함."},
                 "missing", id="same-month-in-another-year"),
    pytest.param({"name": "5월 13일 A라인 가동률", "definition": "5월 일보"},
                 "missing", id="daily-name-before-definition"),
])
def test_compare_metrics_matches_month_in_definition_or_condition(compare_metrics, actual, bucket):
    values = {"unit": "%", "value": 90, "numerator": 396, "denominator": 440}
    required = [{"name": "utilization", "month": "2025-05", "line": "A", **values}]
    submitted = [{"name": "A라인 가동률", **values, **actual}]

    result = compare_metrics(required, [], submitted, Decimal("0.01"), [])

    assert [item["name"] for item in result[bucket]] == ["utilization"], result


@pytest.mark.parametrize(("actual", "matched"), [
    pytest.param({"name": "A라인 출고량", "definition": "2025-05"}, True, id="iso-month"),
    pytest.param({"name": "A라인 5월 출고량"}, True, id="korean-month"),
    pytest.param({"name": "출고량", "condition": "a 라인 / MAY 2025"}, True, id="english-month"),
    pytest.param({"name": "A라인 출고량", "definition": "2025-06"}, False, id="wrong-month"),
    pytest.param({"name": "B라인 5월 출고량"}, False, id="wrong-line"),
    pytest.param({"name": "A라인 출고량"}, False, id="missing-month"),
])
def test_compare_metrics_requires_each_group_and_period_in_metric_text(compare_metrics, actual, matched):
    required = [{"name": "출고량", "line": "A라인", "month": "2025-05", "value": 17}]
    optional = [{"name": "other period", "month": "2025-06", "value": 20}]

    result = compare_metrics(required, optional, [{**actual, "value": 17}], Decimal("0.01"), [])

    assert len(result["matched"]) == int(matched)


def test_compare_metrics_matches_undated_rows_when_flow_has_one_period(compare_metrics):
    required = [
        {"name": "output", "line": "A", "month": "2025-05", "value": 170, "unit": "kg"},
        {"name": "output", "line": "B", "month": "2025-05", "value": 230, "unit": "kg"},
    ]
    optional = [{"name": "uptime", "line": "A", "month": "2025-05", "value": 90, "unit": "%"}]
    actual = [
        {"name": "A line output", "definition": "Sum of 21 daily totals in kg", "value": 170, "unit": "kg"},
        {"name": "B line output", "value": 230, "unit": "kg"},
        {"name": "A line uptime", "definition": "Includes maintenance on May 13", "value": 90, "unit": "%"},
    ]

    result = compare_metrics(required, optional, actual, Decimal("0.01"), [])

    assert [item["actual_names"] for item in result["matched"]] == [
        ["A line output"], ["B line output"], ["A line uptime"],
    ]
    assert result["missing"] == result["mismatched"] == result["extra"] == []


@pytest.mark.parametrize("date_evidence", [
    {"month": "2026-05"},
    {"name": "output in May 2026"},
    {"definition": "Total for May 2026"},
    {"condition": "Only records in May 2026"},
])
def test_compare_metrics_rejects_other_period_evidence_in_single_period_flow(compare_metrics, date_evidence):
    required = [{"name": "output", "month": "2025-05", "value": 170}]
    actual = [{"name": "output", "value": 170, **date_evidence}]

    result = compare_metrics(required, [], actual, Decimal("0.01"), [])

    assert result["matched"] == []
    assert [item["name"] for item in result["missing"]] == ["output"]


def test_compare_metrics_requires_dates_for_multiple_daily_periods(compare_metrics):
    days = ["2025-05-01", "2025-05-02"]
    required = [{"name": f"output on {day}", "value": 170} for day in days]

    result = compare_metrics(required, [], [{"name": "output", "value": 170}], Decimal("0.01"), days)

    assert result["matched"] == []
    assert [item["date"] for item in result["missing"]] == days


@pytest.mark.parametrize(("other_month", "bucket"), [("2025-05", "matched"), ("2025-06", "missing")])
def test_compare_metrics_uses_full_flow_periods_for_report_fallback(compare_metrics, other_month, bucket):
    required = [{"name": "output", "month": "2025-05", "value": 170}]
    optional = [{"name": "uptime", "month": other_month, "value": 90}]
    actual = [{"name": "uptime", "month": other_month, "value": 90}]

    result = compare_metrics(
        required, optional, actual, Decimal("0.01"), [], named_evidence=True,
        report_metrics=lambda: ("report.html", [{"name": "output", "value": 170}]),
    )

    assert "output" in [item["name"] for item in result[bucket]]


@pytest.mark.parametrize(("scope", "actual", "matched_count"), [
    pytest.param({"channel": "Online"}, {"definition": "ON LINE orders"}, 1, id="channel-definition"),
    pytest.param({"team": "Night Shift"}, {"condition": "only NIGHTSHIFT"}, 1, id="team-condition"),
    pytest.param({"date": "2025-05"}, {"name": "orders in May 2025"}, 1, id="date-month-name"),
    pytest.param({"channel": "online"}, {"channel": "online"}, 1, id="structured-channel"),
    pytest.param({"team": "night shift"}, {"definition": "day shift"}, 0, id="wrong-team"),
    pytest.param({"date": "2025-05-04"}, {}, 0, id="missing-date"),
    pytest.param({"warehouse": "east"}, {"definition": "west warehouse"}, 0, id="custom-scope-key"),
])
def test_compare_metrics_checks_scope_values_in_name_definition_or_condition(
    compare_metrics, scope, actual, matched_count,
):
    required = [{"name": "orders", "value": 17, **scope}]

    optional = [{"name": "other period", "date": "2025-05-05", "value": 20}]
    result = compare_metrics(required, optional, [{"name": "orders", "value": 17, **actual}],
                             Decimal("0.01"), [])

    assert len(result["matched"]) == matched_count


def test_compare_metrics_excludes_condition_and_source_refs_from_scope_keys(compare_metrics):
    required = [{"name": "orders", "value": 17, "condition": "if a posting date is present",
                 "source_refs": "ledger!B2"}]
    actual = [{"name": "orders", "value": 17, "condition": "posted orders only"}]

    result = compare_metrics(required, [], actual, Decimal("0.01"), [])

    assert len(result["matched"]) == 1


@pytest.mark.parametrize(("expected_unit", "expected_value", "unit", "value", "bucket"), [
    pytest.param("ratio", 0.2, "%", 0.2, "mismatched", id="unscaled-percent"),
    pytest.param("ratio", 0.2, "%", 20, "matched", id="percent-to-ratio"),
    pytest.param("ratio", 0.2, "pct", 20, "matched", id="pct-to-ratio"),
    pytest.param("fraction of tonnes", 0.2, "%", 20, "matched", id="fraction-phrase"),
    pytest.param(" Share of production ", 0.2, "%", 20, "matched", id="share-phrase"),
    pytest.param("proportion of kg/h", 0.2, "%", 20, "matched", id="proportion-phrase"),
    pytest.param("mass ratio of kg", 0.2, "%", 20, "matched", id="ratio-phrase"),
    pytest.param("생산 비중", 0.2, "%", 20, "matched", id="korean-share-phrase"),
    pytest.param("투입 비율", 0.2, "%", 20, "matched", id="korean-ratio-phrase"),
    pytest.param("%", 20, "fraction of tonnes", 0.2, "matched", id="fraction-phrase-to-percent"),
    pytest.param("퍼센트", 20, "ratio", 0.2, "matched", id="ratio-to-percent"),
    pytest.param("%", 20, "", 0.2, "matched", id="empty-unit-is-ratio"),
    pytest.param("%", 20, "", 20, "mismatched", id="unscaled-empty-unit"),
    pytest.param("%", 20, " 퍼센트 ", 20, "matched", id="percent-alias"),
    pytest.param("ratio", 0.2, " Ratio ", 0.2, "matched", id="normalized-ratio"),
    pytest.param("kg", 10, "g", 10, "mismatched", id="unscaled-mass"),
    pytest.param("kg", 10, "g", 10000, "matched", id="converted-mass"),
    pytest.param("kg", 10, "kg", 10, "matched", id="equal-mass-units"),
    pytest.param("L", 8, "°C", 8, "mismatched", id="different-dimensions"),
    pytest.param("%p", 20, "%", 20, "mismatched", id="percentage-points"),
    pytest.param("kg", 10, "crates", 10, "unverified", id="unknown-unit"),
    pytest.param("Crates / lot", 10, " crates/ LOT ", 10, "matched", id="equal-unknown-unit"),
    pytest.param("kg/lot", 10, "kg/crate", 10, "unverified", id="unknown-compound-unit"),
    pytest.param("ratio", 0.2, "percent", 0.2, "mismatched", id="unscaled-percent-word"),
    pytest.param("ratio", 0.2, "percent", 20, "matched", id="percent-word-to-ratio"),
    pytest.param("ratio", 0.2, "per cent", 0.2, "mismatched", id="unscaled-per-cent"),
    pytest.param("ratio", 0.2, "per cent", 20, "matched", id="per-cent-to-ratio"),
    pytest.param("units/h", 60, "개/분", 1, "matched", id="converted-compound-unit"),
    pytest.param("kg", 0.2, " KG ", 0.2, "matched", id="normalized-unit"),
    pytest.param("kg", 0.2, None, 0.2, "matched", id="absent-actual-unit"),
    pytest.param(None, 0.2, "kg", 0.2, "matched", id="absent-expected-unit"),
    pytest.param(None, 10, "crates", 10, "matched", id="absent-expected-unit-with-unknown-actual"),
])
def test_compare_metrics_checks_units_before_accepting_numeric_values(
    compare_metrics, expected_unit, expected_value, unit, value, bucket,
):
    expected = {"name": "measurement", "value": expected_value, "numerator": 1, "denominator": 5}
    actual = {**expected, "value": value}
    if expected_unit is not None:
        expected["unit"] = expected_unit
    if unit is not None:
        actual["unit"] = unit

    result = compare_metrics([expected], [], [actual], Decimal("0.01"), [])

    assert [key for key in ("matched", "mismatched", "unverified") if result.get(key)] == [bucket]


def test_a4_parse_grade_accepts_review():
    parse_grade = eval_function("grade_run.py", "parse_grade")
    grade = {"critical_failures": [], "quality_scores": {}, "evidence": [],
             "numbers_verdict": "review", "overall": "review"}
    assert parse_grade(json.dumps(grade)) == {**grade, "unsupported_assumptions": None}


@pytest.mark.parametrize("count", [0, 3])
def test_grade_keeps_unsupported_assumption_count_in_json_and_markdown(count):
    parse_grade = eval_function("grade_run.py", "parse_grade")
    grade_markdown = eval_function("grade_run.py", "grade_markdown")
    grade = {"critical_failures": [], "quality_scores": {}, "evidence": [],
             "numbers_verdict": "pass", "overall": "pass", "unsupported_assumptions": count}

    assert parse_grade(json.dumps(grade)) == grade
    assert f"**Unsupported assumptions** {count}" in grade_markdown(grade)


@pytest.mark.parametrize("count", [-1, True, 1.5, "3"])
def test_parse_grade_rejects_invalid_unsupported_assumption_count(count):
    parse_grade = eval_function("grade_run.py", "parse_grade")
    grade = {"critical_failures": [], "quality_scores": {}, "evidence": [],
             "numbers_verdict": "pass", "overall": "pass", "unsupported_assumptions": count}

    with pytest.raises(ValueError, match="unsupported_assumptions"):
        parse_grade(json.dumps(grade))


@pytest.mark.parametrize("unit", ["percent", "per cent"])
@pytest.mark.parametrize(("value", "bucket"), [(0.2, "mismatched"), (20, "matched")])
def test_numeric_text_checks_percent_aliases(compare_metrics, unit, value, bucket):
    extract = eval_function("numeric_check.py", "transcript_metrics")
    required = [{"name": "share", "value": 0.2, "unit": "ratio"}]
    actual = extract(f"Share = {value} {unit}", required)

    result = compare_metrics(required, [], actual, Decimal("0.01"), [], named_evidence=True)

    assert [item["name"] for item in result[bucket]] == ["share"], result


def test_load_expected_rejects_input_changed_since_run(tmp_path, monkeypatch):
    load_expected = eval_function("numeric_check.py", "load_expected")
    case = tmp_path / "case"
    case.mkdir()
    monkeypatch.setitem(load_expected.__globals__, "case_path", lambda _: case)
    expected = {"absolute_tolerance": 0, "flows": {"B": {"metrics": []}}}
    (case / "expected.json").write_text(json.dumps(expected))
    (case / "case.md").write_text("# Case\ninputs: input.csv, lookup.json\n")
    inputs = {"input.csv": b"count\n17\n", "lookup.json": b'{"count":17}\n'}
    for name, content in inputs.items():
        (case / name).write_bytes(content)
    run = tmp_path / "run"
    run.mkdir()
    (run / "meta.json").write_text(json.dumps({
        "case": case.name, "flow": "B", "case_dir": str(case),
        "input_sha256": {name: sha256(content).hexdigest() for name, content in inputs.items()},
    }))
    assert load_expected(run) == (case, "B", expected)

    (case / "lookup.json").write_bytes(b'{"count":19}\n')

    with pytest.raises(ValueError):
        load_expected(run)


def test_make_role_home_rejects_base_inside_repo(tmp_path, monkeypatch):
    make_role_home = eval_function("run_case.py", "make_role_home")
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setitem(make_role_home.__globals__, "ROOT", repo)
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "missing-auth"))
    base = repo / "cache"

    with pytest.raises(ValueError):
        make_role_home(base, "analyst")

    assert not base.exists()


def test_make_role_home_disables_extra_skills(tmp_path, monkeypatch):
    make_role_home = eval_function("run_case.py", "make_role_home")
    monkeypatch.setenv("HOME", str(tmp_path / "source-home"))
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "source-codex"))
    base = tmp_path / "cache"
    base.mkdir()

    env = make_role_home(base, "analyst")

    config = Path(env["CODEX_HOME"]) / "config.toml"
    assert config.read_text(encoding="utf-8").strip() == (
        "[skills.bundled]\nenabled = false\n\n[features]\nplugins = false\napps = false"
    )


@pytest.mark.parametrize("auth_source", ["configured", "fallback", "missing"])
def test_make_role_home_copies_auth_when_available(tmp_path, monkeypatch, capsys, auth_source):
    make_role_home = eval_function("run_case.py", "make_role_home")
    home = tmp_path / "source-home"
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    source = home / ".codex"
    if auth_source == "configured":
        source = tmp_path / "source-codex"
        monkeypatch.setenv("CODEX_HOME", str(source))
    auth = b'{"token":"fixture-only"}\n'
    if auth_source != "missing":
        source.mkdir(parents=True)
        (source / "auth.json").write_bytes(auth)

    base = tmp_path / "cache"
    base.mkdir()
    env = make_role_home(base, "analyst")

    role_home = base / "home-analyst"
    codex_home = role_home / ".codex"
    assert {name: Path(value) for name, value in env.items()} == {
        "HOME": role_home, "CODEX_HOME": codex_home,
    }
    if auth_source == "missing":
        assert codex_home.is_dir()
        assert not (codex_home / "auth.json").exists()
        assert capsys.readouterr() == ("", "")
    else:
        assert (codex_home / "auth.json").read_bytes() == auth


def test_remove_role_auth_deletes_only_role_copies(tmp_path):
    remove_role_auth = eval_function("run_case.py", "remove_role_auth")
    copies = [tmp_path / f"home-{role}/.codex/auth.json"
              for role in ("analyst", "simulator", "grader")]
    other = tmp_path / "other/.codex/auth.json"
    config = tmp_path / "home-analyst/.codex/config.toml"
    for path in [*copies, other, config]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    remove_role_auth(tmp_path)

    assert all(not path.exists() for path in copies)
    assert other.is_file()
    assert config.is_file()


def foreign_skill_check(run):
    eval_function("grade_run.py", "check_foreign_skills")(run)
    return json.loads((run / "foreign_skill_check.json").read_text(encoding="utf-8"))


def test_check_foreign_skills_records_completed_commands_and_locations(tmp_path):
    commands = [
        FOREIGN_SKILL_COMMAND,
        "cat ~/.codex/skills/x/SKILL.md",
        "cat ~/.claude/skills/x/SKILL.md",
        "cat ~/.codex/plugins/cache/example/SKILL.md",
    ]
    filename = "raw/02-resume-analyst.jsonl"
    write_jsonl(tmp_path / filename, [
        {"type": "thread.started", "thread_id": "analyst-thread"},
        *(command_event(command, item_id=f"item_{index}")
          for index, command in enumerate(commands)),
    ])

    assert foreign_skill_check(tmp_path) == {"status": "found", "evidence": [
        {"file": filename, "line": line, "text": command}
        for line, command in enumerate(commands, 2)
    ]}


def test_check_foreign_skills_allows_evaluated_skill_and_ignores_simulator(tmp_path):
    write_jsonl(tmp_path / "raw/01-analyst.jsonl", [
        command_event("python3 ask-first-eda/scripts/inspect_data.py"),
        command_event("cat ask-first-eda/SKILL.md", item_id="item_1"),
    ])
    write_jsonl(tmp_path / "raw/01-simulator.jsonl", [command_event(FOREIGN_SKILL_COMMAND)])

    assert foreign_skill_check(tmp_path) == {"status": "clean", "evidence": []}


def test_check_foreign_skills_ignores_started_commands_and_messages(tmp_path):
    write_jsonl(tmp_path / "raw/01-analyst.jsonl", [
        command_event(FOREIGN_SKILL_COMMAND, event_type="item.started"),
        {"type": "item.completed", "item": {"type": "agent_message", "text": FOREIGN_SKILL_COMMAND}},
    ])

    assert foreign_skill_check(tmp_path) == {"status": "clean", "evidence": []}


def test_check_foreign_skills_is_unknown_without_analyst_logs(tmp_path):
    write_jsonl(tmp_path / "raw/01-simulator.jsonl", [command_event(FOREIGN_SKILL_COMMAND)])

    assert foreign_skill_check(tmp_path) == {"status": "unknown", "evidence": []}


def usage_event(input_tokens, cached_input_tokens, output_tokens, *, event_type="turn.completed"):
    return {"type": event_type, "usage": {
        "input_tokens": input_tokens, "cached_input_tokens": cached_input_tokens,
        "output_tokens": output_tokens,
    }}


@pytest.fixture
def analyst_metrics_run(tmp_path):
    run = tmp_path / "metrics-run"
    completed = command_event("sed -n 1,50p eda-skill/scripts/plots.py")
    write_jsonl(run / "raw/01-analyst.jsonl", [
        completed,
        completed,
        command_event("cat eda-skill/scripts/plots.py", item_id="item_1", event_type="item.started"),
        usage_event(10, 6, 4),
        usage_event(80, 70, 60, event_type="usage"),
    ])
    write_jsonl(run / "raw/02-analyst.jsonl", [
        command_event("python3 eda-skill/scripts/plots.py --help", item_id="item_2"),
        command_event("python3 eda-skill/scripts/build_report.py --spec x", item_id="item_3"),
        usage_event(7, 2, 5),
    ])
    for filename in ("01-simulator.jsonl", "imported-analyst.jsonl"):
        write_jsonl(run / "raw" / filename, [
            command_event("head eda-skill/scripts/plots.py", item_id="item_4"),
            usage_event(120, 90, 60),
        ])
    write_jsonl(run / "transcript.jsonl", [
        {"speaker": "user", "duration_s": 100},
        {"speaker": "analyst", "duration_s": 1.25},
        {"speaker": "simulator", "duration_s": 30},
        {"speaker": "analyst", "duration_s": 2.5},
    ])
    (run / "meta.json").write_text('{"case":"demo","flow":"B","condition":"skill"}', encoding="utf-8")
    return run


def test_analyst_metrics_deduplicates_commands_and_uses_analyst_logs_only(analyst_metrics_run):
    analyst_metrics = eval_function("ab_summary.py", "analyst_metrics")

    assert analyst_metrics(analyst_metrics_run) == {
        "commands": 3, "input_tokens": 17, "cached_input_tokens": 8, "uncached_input_tokens": 9,
        "output_tokens": 9, "analyst_seconds": 3.75, "source_reads": 1,
    }


@pytest.mark.parametrize(("command", "source_reads"), [
    pytest.param("sed -n 1,50p eda-skill/scripts/plots.py", 1, id="reads-source"),
    pytest.param("python3 eda-skill/scripts/plots.py --help", 0, id="python-help"),
    pytest.param("python3 eda-skill/scripts/build_report.py --spec x", 0, id="runs-script"),
])
def test_analyst_metrics_distinguishes_source_reads_from_execution(tmp_path, command, source_reads):
    analyst_metrics = eval_function("ab_summary.py", "analyst_metrics")
    write_jsonl(tmp_path / "raw/01-analyst.jsonl", [command_event(command)])

    assert analyst_metrics(tmp_path)["source_reads"] == source_reads


def test_ab_summary_renders_analyst_cost(analyst_metrics_run, tmp_path):
    out = tmp_path / "ab.md"
    subprocess.run(
        [sys.executable, "-I", str(ROOT / "evals/ab_summary.py"),
         "--runs", str(analyst_metrics_run), "--out", str(out)],
        check=True, capture_output=True, text=True,
    )

    report = out.read_text(encoding="utf-8")
    assert "## Analyst cost" in report.splitlines()
    section = report.split("## Analyst cost\n", 1)[1].split("\n## ", 1)[0]
    header, _, row = [
        [value.strip() for value in line.strip("|").split("|")]
        for line in section.splitlines() if line.startswith("|")
    ]
    assert header == [
        "Run ID", "Case", "Flow", "Condition", "Commands", "Input", "Cached input",
        "Uncached input", "Output", "Analyst time (s)", "Source reads",
    ]
    assert row[:9] == ["metrics-run", "demo", "B", "skill", "3", "17", "8", "9", "9"]
    assert float(row[9]) == 3.75
    assert row[10:] == ["1"]


def test_abc_summary_aggregates_grouped_runs_and_anonymizes_identifiers(tmp_path):
    def make_run(name, case, condition, wall_time, messages, *, metric=None, bucket=None,
                 artifacts=(), cleaning=None, assumptions=None):
        run = tmp_path / name
        run.mkdir()
        (run / "meta.json").write_text(json.dumps({
            "case": case, "case_dir": f"fixture/{case}", "flow": "B",
            "condition": condition, "wall_time_s": wall_time, "turns": len(messages),
        }))
        write_jsonl(run / "transcript.jsonl", [
            {"speaker": "user", "text": "Can you check 12345.6?"},
            *({"turn": turn, "speaker": "analyst", "text": message}
              for turn, message in enumerate(messages, 1)),
        ])
        if bucket:
            numeric = {key: [] for key in ("matched", "mismatched", "missing", "unparsed", "unverified", "extra")}
            numeric[bucket].append({"required": True, "actual": {"value": metric}})
            (run / "numeric_check.json").write_text(json.dumps(numeric))
        for artifact in artifacts:
            path = run / artifact
            path.parent.mkdir(exist_ok=True)
            path.write_text("{}")
        if cleaning:
            (run / "cleaning_check.json").write_text(json.dumps({"status": cleaning}))
        if assumptions is not None:
            (run / "grade.json").write_text(json.dumps({
                "numbers_verdict": "pass", "unsupported_assumptions": assumptions,
            }))
        return run

    complete = make_run(
        "reused-control-first", "Synthetic case alpha", "noskill", 2.5,
        ["Is 912345.6 in scope? I will wait.", "Candidate total is 12,345.60."],
        metric=12345.6, bucket="matched",
        artifacts=("delivery/report.html", "delivery/results.json"), cleaning="pass", assumptions=2,
    )
    write_jsonl(complete / "raw/01-analyst.jsonl", [
        command_event("python3 -I fixture.py"), usage_event(10, 6, 4),
    ])
    write_jsonl(complete / "raw/01-simulator.jsonl", [usage_event(900, 0, 5)])
    make_run(
        "reused-control-second", "Synthetic case alpha", "noskill", 1.5,
        ["Which interval?" + " " + "x" * 400],
        bucket="unverified", artifacts=("report.html",), cleaning="incomplete", assumptions=3,
    )
    make_run(
        "reused-prompted", "Synthetic case alpha", "prompted", 3,
        ["The candidate values include 87 and 246."],
        metric=[87, 246], bucket="mismatched",
        artifacts=("report.html", "eda_summary.json"), cleaning="review", assumptions=0,
    )
    make_run(
        "fresh-skill", "Synthetic case beta", "skill", 1,
        ["One source column was empty."], metric=55, bucket="matched",
        artifacts=("delivery/results.json",), cleaning="not_applicable",
    )
    out = tmp_path / "abc.md"

    result = subprocess.run(
        [sys.executable, "-I", str(ROOT / "evals/ab_summary.py"),
         "--runs", str(tmp_path / "reused-"), str(tmp_path / "fresh-*"),
         "--group", "reused=reused-*", "--group", "fresh=fresh-*",
         "--anonymize", "--out", str(out)],
        check=False, capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    report = out.read_text(encoding="utf-8")
    for raw_label in ("reused-control", "reused-prompted", "fresh-skill", "Synthetic case", str(tmp_path)):
        assert raw_label not in report
    assert "| R01 | case-1 | B | noskill |" in report
    assert "| R03 | case-1 | B | prompted |" in report
    assert "| R04 | case-2 | B | skill |" in report

    def table(section, key):
        headers, _, *rows = [
            line.strip("| ").split(" | ")
            for line in report.split(f"## {section}\n", 1)[1].split("\n## ", 1)[0].splitlines()
            if line.startswith("|")
        ]
        return {row[0]: dict(zip(headers, row))[key] for row in rows}

    assert table("reused", "Numeric pass / review / fail") == {"noskill": "1 / 1 / 0", "prompted": "0 / 0 / 1"}
    assert table("reused", "Complete") == {"noskill": "1/2 (50.0%)", "prompted": "1/1 (100.0%)"}
    assert table("reused", "Analyst turns") == {"noskill": "3", "prompted": "1"}
    assert table("reused", "Question turns") == {"noskill": "1", "prompted": "0"}
    assert table("reused", "Wall time (s)") == {"noskill": "4", "prompted": "3"}
    assert table("reused", "Uncached input + output tokens") == {"noskill": "8", "prompted": "0"}
    assert table("reused", "Commands") == {"noskill": "1", "prompted": "0"}
    assert table("reused", "Cleaning status") == {"noskill": "pass 1, incomplete 1", "prompted": "review 1"}
    assert table("reused", "Unsupported assumptions") == {"noskill": "5", "prompted": "0"}
    assert table("fresh", "Complete") == {"skill": "0/1 (0.0%)"}
    assert table("fresh", "Unsupported assumptions") == {"skill": "—"}
    assert table("Run outcomes", "First result turn") == {"R01": "2", "R02": "—", "R03": "1", "R04": "—"}
    assert "last 400 characters" in report


def check_run_paths(run):
    check_paths = runpy.run_path(str(ROOT / "evals/grade_run.py")).get("check_paths")
    assert callable(check_paths), "grade_run.py must define check_paths(run)"
    check_paths(run)
    return json.loads((run / "path_check.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize(("home", "before", "after"), [
    pytest.param("/Users/someone", "[x](", "/.cache/w/report.html)", id="markdown-link"),
    pytest.param(r"c:\uSeRs\someone", "0123456789" * 5 + " ", " " + "abcdefghij" * 5,
                 id="windows-case-insensitive-with-context"),
])
def test_check_paths_reports_analyst_message_with_line_and_context(tmp_path, home, before, after):
    write_transcript(tmp_path, ("simulator", "/home/simulator/input.csv"),
                     ("analyst", before + home + after))

    assert check_run_paths(tmp_path) == {"status": "found", "evidence": [{
        "file": "transcript.jsonl", "line": 2, "text": before[-40:] + home + after[:40],
    }]}


def test_check_paths_allows_relative_paths_and_skips_simulator_and_raw(tmp_path):
    write_transcript(tmp_path, ("simulator", "/Users/someone/input.csv"),
                     ("analyst", "eda-work/delivery/report.html\n~/x"))
    raw = tmp_path / "raw" / "nested"
    raw.mkdir(parents=True)
    (raw / "report.html").write_text("<p>/home/raw/x</p>", encoding="utf-8")
    (raw / "eda_summary.json").write_text('{"source":"/Users/raw/x"}', encoding="utf-8")
    (tmp_path / "notes.txt").write_text("/home/notes/x", encoding="utf-8")

    assert check_run_paths(tmp_path) == {"status": "clean", "evidence": []}


@pytest.mark.parametrize(("name", "content"), [
    pytest.param("report.html", "<p>/home/someone/x</p>", id="html"),
    pytest.param("eda_summary.json", '{"source":"/hOmE/someone/x"}', id="summary"),
])
def test_check_paths_reports_deliverable_with_no_line_number(tmp_path, name, content):
    write_transcript(tmp_path, ("analyst", "eda-work/delivery/report.html"))
    delivery = tmp_path / "eda-work" / "delivery"
    delivery.mkdir(parents=True)
    (delivery / name).write_text(content, encoding="utf-8")

    assert check_run_paths(tmp_path) == {"status": "found", "evidence": [{
        "file": f"eda-work/delivery/{name}", "line": None, "text": content,
    }]}


@pytest.fixture
def prior_summary_runner(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    case = repo / "evals/cases/demo"
    case.mkdir(parents=True)
    (case / "case.md").write_text("## B\nOpening B\n")
    (case / "input.csv").write_text("quantity\n8\n")

    gallery = repo / "docs/gallery"
    nested = gallery / "nested"
    nested.mkdir(parents=True)
    valid = '{"datasets": [], "ambiguity_log": []}'
    target = nested / "valid.summary.json"
    target.write_text(valid)
    (tmp_path / "outside.summary.json").write_text(valid)
    (repo / "evals/escaped.summary.json").write_text(valid)
    (tmp_path / "link.summary.json").symlink_to(target)
    (gallery / "link.summary.json").symlink_to(target)
    (gallery / "linked-directory").symlink_to(nested, target_is_directory=True)
    (gallery / "index.html").write_text(valid)
    (gallery / "directory.summary.json").mkdir()
    (gallery / "malformed.summary.json").write_text("{")
    (gallery / "array.summary.json").write_text("[]")
    (gallery / "no-datasets.summary.json").write_text('{"ambiguity_log": []}')
    (gallery / "no-ambiguity-log.summary.json").write_text('{"datasets": []}')

    run_case = runpy.run_path(str(ROOT / "evals/run_case.py"))["run_case"]
    monkeypatch.setitem(run_case.__globals__, "ROOT", repo)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.setenv("CODEX_BIN", str(tmp_path / "unused-codex"))
    return run_case


@pytest.mark.parametrize(("candidate", "dry_run"), [
    pytest.param("outside.summary.json", True, id="outside-gallery"),
    pytest.param("repo/docs/gallery/../../evals/escaped.summary.json", True, id="parent-traversal"),
    pytest.param("link.summary.json", True, id="external-symlink"),
    pytest.param("repo/docs/gallery/link.summary.json", True, id="gallery-symlink"),
    pytest.param("repo/docs/gallery/linked-directory/valid.summary.json", True, id="parent-symlink"),
    pytest.param("repo/docs/gallery/index.html", True, id="wrong-suffix"),
    pytest.param("repo/docs/gallery/directory.summary.json", True, id="directory"),
    pytest.param("repo/docs/gallery/malformed.summary.json", True, id="malformed-json"),
    pytest.param("repo/docs/gallery/array.summary.json", True, id="non-object"),
    pytest.param("repo/docs/gallery/no-datasets.summary.json", True, id="missing-datasets"),
    pytest.param("repo/docs/gallery/no-ambiguity-log.summary.json", True, id="missing-ambiguity-log"),
    pytest.param("outside.summary.json", False, id="actual-run-with-invalid-prior"),
])
def test_runner_rejects_invalid_prior_before_creating_folders(
    prior_summary_runner, tmp_path, candidate, dry_run,
):
    with pytest.raises(ValueError):
        prior_summary_runner(
            case_id="demo", flow="B", condition="noskill", max_turns=1,
            run_id="invalid-prior", dry_run=dry_run, prior_summary=tmp_path / candidate,
        )

    assert not (tmp_path / "repo/evals/runs").exists()
    assert not (tmp_path / "home/.cache").exists()


@pytest.mark.parametrize(("reference_changes", "actual_changes"), [
    pytest.param({}, {"numerator": 16}, id="wrong-numerator"),
    pytest.param({}, {"denominator": 2}, id="real-denominator"),
    pytest.param({}, {"value": 18}, id="wrong-value"),
    pytest.param({}, {"unit": "kg/t"}, id="wrong-unit"),
    pytest.param({"name": "A라인 평균 물량", "denominator": 22}, {"name": "A라인 평균 물량", "denominator": None},
                 id="average-with-missing-denominator"),
    pytest.param({}, {"name": "B라인 누적 물량", "denominator": None}, id="different-group"),
])
def test_cs7b_simple_aggregates(compare_metrics, reference_changes, actual_changes):
    metric = {"name": "A라인 누적 물량", "unit": "kg", "value": 17, "numerator": 17,
              "denominator": 1, "source_refs": ["2", "3"]}
    result = compare_metrics([{**metric, **reference_changes}], [],
                             [{**metric, **actual_changes}], Decimal("0.01"), [])
    assert not result["matched"], result


@pytest.mark.parametrize(("expected_unit", "actual_unit", "changes", "bucket"), [
    pytest.param("kg/건", "kg/t", {}, "mismatched", id="mass-denominator"),
    pytest.param("kg", "kg/t", {}, "mismatched", id="different-dimensions"),
    pytest.param("개/교대", "기록 물량/셀·교대", {}, "unverified", id="unconfirmed-base-unit"),
    pytest.param("초/건", "초", {"denominator": None}, "mismatched", id="missing-denominator"),
    pytest.param("초/건", "초", {"numerator": 17}, "mismatched", id="wrong-numerator"),
    pytest.param("초/건", "초", {"value": 7}, "mismatched", id="wrong-average"),
    pytest.param("초/건", "초", {"name": "B라인 평균 작업시간"}, "missing", id="different-subject"),
])
def test_cs7b_per_count_units(compare_metrics, expected_unit, actual_unit, changes, bucket):
    reference = {"name": "A라인 평균 작업시간", "value": 6, "numerator": 18, "denominator": 3,
                 "unit": expected_unit}
    actual = {**reference, "unit": actual_unit, **changes}
    result = compare_metrics([reference], [], [actual], Decimal("0.01"), [])
    assert len(result[bucket]) == 1, result
    if bucket == "mismatched" and actual_unit == "kg/t":
        assert "unit" in result[bucket][0]["differences"]
        assert "value" not in result[bucket][0]["differences"]


@pytest.mark.parametrize(("dates", "reference_changes", "submitted", "matched"), [
    pytest.param(["2025-04-02"], {"date": "2025-04-02"}, {}, True, id="single-evaluation-day"),
    pytest.param(["2025-04-02", "2025-04-03"], {"date": "2025-04-02"}, {}, False, id="multiple-evaluation-days"),
    pytest.param(["2025-04-02"], {"date": "2025-04-02"}, {"name": "04-03 전송 건수"},
                 False, id="different-short-date"),
    pytest.param(["2025-04-02", "2025-04-03"], {"date": "2025-04-02"}, {"name": "04-02 전송 건수"},
                 True, id="unique-short-date"),
    pytest.param(["2025-04-02", "2026-04-02"], {"date": "2025-04-02"}, {"name": "04-02 전송 건수"},
                 False, id="ambiguous-short-date"),
    pytest.param([], {}, {"definition": "2025-04-02~2025-04-04의 전송 건수"}, True,
                 id="full-period-legacy-key"),
    pytest.param(["2025-04-02", "2025-04-04"], {},
                 {"definition": "2025-04-02~2025-04-04의 전송 건수"}, True, id="whole-date-range"),
    pytest.param(["2025-04-02", "2025-04-04"], {},
                 {"definition": "2025-04-02~2025-04-03의 전송 건수"}, False, id="partial-date-range"),
    pytest.param(["2025-04-02", "2025-04-04"], {"date": "2025-04-02"},
                 {"definition": "2025-04-02~2025-04-04의 전송 건수"}, False, id="range-is-not-a-day"),
    pytest.param([], {}, {"definition": "2025-04-02 및 2025-04-04의 전송 건수"}, False,
                 id="separate-dates-are-not-a-range"),
])
def test_cs7b_evaluation_dates(compare_metrics, dates, reference_changes, submitted, matched):
    reference = {"name": "전송 건수", "value": 17, "numerator": 17, "denominator": 1, "unit": "건",
                 **reference_changes}
    actual = {"name": "전송 건수", "value": 17, "numerator": 17, "denominator": 1, "unit": "건",
              **submitted}
    # This aggregate is intentionally undated even when the flow also asks for a daily metric.
    optional = [{"name": "최대 큐 길이", "value": 2}]
    result = compare_metrics([reference], optional, [actual], Decimal("0.01"), dates)
    assert bool(result["matched"]) == matched, result


@pytest.mark.parametrize(("values", "bucket"), [([12, 17], "matched"), ([17, 12], "mismatched")])
def test_dated_aggregate_series_preserves_order(compare_metrics, values, bucket):
    dates = ["2025-01-02", "2025-01-03"]
    reference = {"name": "widget count", "values": [12, 17], "unit": "count"}
    actual = [{"name": "widget count", "date": day, "value": value, "unit": "count"}
              for day, value in zip(dates, values)]

    result = compare_metrics([reference], [], actual, Decimal(0), dates)

    [entry] = result[bucket]
    assert entry["actual"]["value"] == values


def test_unrelated_unit_does_not_block_exact_delivery_evidence(tmp_path):
    check_run = eval_function("numeric_check.py", "check_run")
    reference = {"name": "A average latency", "unit": "s/count", "value": 6,
                 "numerator": 18, "denominator": 3}
    expected = {"absolute_tolerance": 0, "flows": {"A": {"metrics": [reference]}}}
    (tmp_path / "meta.json").write_text('{"condition": "skill"}')
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "results.json").write_text(json.dumps({"metrics": [reference]}))
    write_summary(tmp_path, [{**reference, "name": "B average latency", "unit": "s"}])

    result = check_run(tmp_path, "A", expected, tmp_path / "eda_summary.json", None)

    [entry] = result["matched"]
    assert entry["source"] == "results.json"


@pytest.mark.parametrize(("summary_value", "results_content", "condition", "bucket", "source"), [
    pytest.param(None, {"metrics": [{"name": "mean delay", "value": 7, "unit": "s",
                                    "numerator": 21, "denominator": 3}]},
                 "skill", "matched", "results.json", id="structured-skill-delivery"),
    pytest.param("absent", {"metrics": [{"name": "mean delay", "value": 7, "unit": "s",
                                        "numerator": 21, "denominator": 3}]},
                 "skill", "matched", "results.json", id="no-summary-beats-incomplete-chat"),
    pytest.param(None, {"summary": "mean delay: 21 / 3 = 7 s"},
                 "skill", "matched", "results.json", id="text-skill-delivery"),
    pytest.param(None, {"findings": {"mean delay": "21 / 3 = 7 s"}},
                 "skill", "matched", "results.json", id="named-json-value"),
    pytest.param(8, {"metrics": [{"name": "mean delay", "value": 7, "unit": "s",
                                 "numerator": 21, "denominator": 3}]},
                 "skill", "mismatched", "eda_summary.json", id="cannot-repair-wrong-summary"),
    pytest.param(7, {"metrics": [{"name": "mean delay", "value": 8, "unit": "s",
                                 "numerator": 24, "denominator": 3}]},
                 "skill", "matched", "eda_summary.json", id="summary-takes-precedence"),
    pytest.param(None, {"metrics": [{"name": "mean delay", "value": 8, "unit": "s",
                                    "numerator": 21, "denominator": 3}],
                        "summary": "mean delay: 21 / 3 = 7 s"},
                 "skill", "mismatched", "results.json", id="structured-results-take-precedence"),
    pytest.param(None, {"metrics": [{"name": "other delay", "value": 7, "unit": "s",
                                    "numerator": 21, "denominator": 3}]},
                 "skill", "missing", "eda_summary.json", id="unrelated-numeric-tuple"),
    pytest.param(None, {"definitions": {"mean delay": "21 / 3 = 7 s"}},
                 "skill", "missing", "eda_summary.json", id="definitions-are-not-results"),
    pytest.param(None, {"metrics": [{"name": "mean delay", "value": 7, "unit": "s",
                                    "numerator": 21, "denominator": 3}]},
                 "noskill", "matched", "results.json", id="control-run-delivery"),
])
def test_cs7b_results_json_fallback(tmp_path, summary_value, results_content, condition, bucket, source):
    check_run = eval_function("numeric_check.py", "check_run")
    summary_path = eval_function("numeric_check.py", "summary_path")
    required = {"name": "mean delay", "value": 7, "unit": "s", "numerator": 21, "denominator": 3}
    expected = {"absolute_tolerance": 0.01, "flows": {"A": {"metrics": [required]}}}
    (tmp_path / "meta.json").write_text(json.dumps({"condition": condition}))
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "results.json").write_text(json.dumps(results_content))
    if summary_value == "absent":
        write_transcript(tmp_path, ("analyst", "mean delay: 7 s"))
    else:
        metrics = [] if summary_value is None else [{**required, "value": summary_value}]
        write_summary(delivery, metrics)

    result = check_run(tmp_path, "A", expected, summary_path(tmp_path), None)

    assert len(result[bucket]) == 1, result
    entry = result[bucket][0]
    assert entry.get("source", result["source"]) == source, result
    if source == "results.json":
        assert entry["source_path"] == "delivery/results.json"


def test_numeric_check_uses_identical_artifacts_across_conditions(tmp_path):
    check_run = eval_function("numeric_check.py", "check_run")
    summary_path = eval_function("numeric_check.py", "summary_path")
    report_path = eval_function("numeric_check.py", "report_path")
    required = {"name": "mean delay", "value": 7, "unit": "s", "numerator": 21, "denominator": 3}
    expected = {"absolute_tolerance": 0, "flows": {"A": {"metrics": [required]}}}
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "results.json").write_text(json.dumps({"metrics": [required]}))
    (delivery / "report.html").write_text("<h1>Delay report</h1>")
    write_transcript(tmp_path, ("analyst", "The report is ready."))

    results = []
    for condition in ("noskill", "prompted", "skill"):
        (tmp_path / "meta.json").write_text(json.dumps({"condition": condition}))
        summary = summary_path(tmp_path)
        results.append(check_run(tmp_path, "A", expected, summary, report_path(tmp_path, summary)))

    assert results[0] == results[1] == results[2]
    assert results[0]["source"] == "results.json"
    assert results[0]["matched"][0]["actual"]["value"] == 7


@pytest.mark.parametrize(("kind", "bucket", "source"), [
    pytest.param("summary", "matched", "results.json(summary)", id="renamed-summary"),
    pytest.param("invalid", "matched", "results.json", id="invalid-summary-remains-evidence"),
    pytest.param("both", "mismatched", "eda_summary.json", id="eda-summary-takes-precedence"),
])
def test_cs8_results_json_summary(tmp_path, kind, bucket, source):
    check_run = eval_function("numeric_check.py", "check_run")
    summary_path = eval_function("numeric_check.py", "summary_path")
    required = {"name": "mean delay", "value": 7, "unit": "s", "numerator": 21, "denominator": 3}
    expected = {"absolute_tolerance": 0.01, "flows": {"A": {"metrics": [required]}}}
    (tmp_path / "meta.json").write_text('{"condition": "skill"}')
    write_transcript(tmp_path, ("analyst", "The report is ready."))
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    metric = {**required, "name": "average waiting time"}
    if kind == "invalid":
        metric = {**required, "source_refs": "invalid"}
    write_summary(delivery, [metric])
    (delivery / "eda_summary.json").rename(delivery / "results.json")
    if kind == "both":
        write_summary(delivery, [{**required, "value": 8}])

    result = check_run(tmp_path, "A", expected, summary_path(tmp_path), None)

    assert [entry["name"] for entry in result[bucket]] == ["mean delay"], result
    assert result["source"] == source, result
    assert "summary_error" not in result


@pytest.mark.parametrize(("changes", "dates"), [
    pytest.param({"unit": "kg"}, [], id="incompatible-unit"),
    pytest.param({"name": "05-03 전송 건수"}, ["2025-05-03", "2025-05-04"],
                 id="daily-total-is-not-whole-period"),
])
def test_cs7b_aggregate_requires_matching_evidence(compare_metrics, changes, dates):
    reference = {"name": "전송 건수", "value": 17, "numerator": 17, "denominator": 1,
                 "unit": "건", "source_refs": ["2", "3"]}
    actual = {**reference, "denominator": None, **changes}

    result = compare_metrics([reference], [], [actual], Decimal("0.01"), dates)

    assert not result["matched"], result


@pytest.mark.parametrize(("expected_date", "actual", "dates"), [
    pytest.param("2025-04", {"name": "04-03 오류 건수"}, ["2025-04-02"],
                 id="short-date-outside-evaluation"),
    pytest.param("2025-04", {"name": "04-02 오류 건수 2025-04"}, ["2025-04-02"],
                 id="month-does-not-erase-short-date"),
    pytest.param(None, {"name": "04-03 오류 건수", "definition": "2025-04-02~2025-04-04"},
                 ["2025-04-02", "2025-04-04"], id="range-does-not-erase-short-date"),
])
def test_cs7b_preserves_short_date_evidence(compare_metrics, expected_date, actual, dates):
    reference = {"name": "오류 건수", "value": 17, "numerator": 17, "denominator": 1, "unit": "건"}
    required = {**reference, "date": expected_date} if expected_date else reference
    submitted = {**reference, **actual}
    result = compare_metrics([required], [], [submitted], Decimal("0.01"), dates)
    assert not result["matched"], result


@pytest.mark.parametrize(("reference_changes", "actual_changes"), [
    pytest.param({}, {"name": "B라인 전체 발송 건수", "source_refs": ["7", "8"]}, id="new-group"),
    pytest.param({"name": "A라인 총 발송 건수", "source_refs": ["first.csv 2, 3행"]},
                 {"name": "A라인 재발송 발송 건수", "source_refs": ["other.csv 2, 3행"]},
                 id="different-source-with-same-row-numbers"),
    pytest.param({"numerator": 16.99}, {"value": 17.01, "numerator": 17.02, "denominator": 1},
                 id="different-explicit-numerators"),
])
def test_cs7b_aggregate_does_not_erase_scope_or_components(compare_metrics, reference_changes, actual_changes):
    metric = {"name": "발송 건수", "value": 17, "numerator": 17, "denominator": 1, "unit": "건",
              "source_refs": ["2", "3"]}
    result = compare_metrics([{**metric, **reference_changes}], [],
                             [{**metric, "denominator": None, **actual_changes}], Decimal("0.01"), [])
    assert not result["matched"], result


@pytest.mark.parametrize(("name", "unit", "matched"), [
    pytest.param("작업반당 평균 대기시간", "초/회", False, id="additional-workgroup-scope"),
    pytest.param("평균 대기시간", "초/명", True, id="allowlisted-count-notation"),
])
def test_cs7b_count_notation_requires_existing_identity(compare_metrics, name, unit, matched):
    metric = {"name": "평균 대기시간", "value": 6, "numerator": 18, "denominator": 3, "unit": "초"}
    result = compare_metrics([metric], [], [{**metric, "name": name, "unit": unit}], Decimal("0.01"), [])
    assert bool(result["matched"]) is matched, result


@pytest.mark.parametrize("conflicting", [True, False], ids=["conflicting-result-rows", "transcript-provenance"])
def test_cs7b_results_preserves_conflicts_and_source(tmp_path, conflicting):
    check_run = eval_function("numeric_check.py", "check_run")
    metric = {"name": "mean delay", "value": 7, "unit": "s", "numerator": 21, "denominator": 3}
    expected = {"absolute_tolerance": 0.01, "flows": {"A": {"metrics": [metric]}}}
    (tmp_path / "meta.json").write_text('{"condition": "skill"}')
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    metrics = [{**metric, "value": 8}, metric] if conflicting else [{**metric, "name": "other delay"}]
    (delivery / "results.json").write_text(json.dumps({"metrics": metrics}))
    write_transcript(tmp_path, ("analyst", "mean delay: 21 / 3 = 7 s"))

    result = check_run(tmp_path, "A", expected, None, None)

    if conflicting:
        assert len(result["mismatched"]) == 1, result
        assert "results_conflict" in result["mismatched"][0]["differences"]
    else:
        assert len(result["matched"]) == 1, result
        assert result["source"] == "transcript_text", result


def test_cs7b_single_day_cannot_override_evaluation_date(compare_metrics):
    metric = {"name": "전송 건수", "value": 17, "numerator": 17, "denominator": 1, "unit": "건"}
    result = compare_metrics([{**metric, "date": "2025-04-03"}], [], [metric],
                             Decimal("0.01"), ["2025-04-02"])
    assert not result["matched"], result


@pytest.mark.parametrize("text", ["04-03 packet count: 4 count", "packet count: 04-03"])
def test_cs7b_results_text_short_dates_are_not_values(tmp_path, text):
    check_run = eval_function("numeric_check.py", "check_run")
    expected = {"absolute_tolerance": 0.01, "dates_in_order": ["2025-04-02"],
                "flows": {"A": {"metrics": [{"name": "packet count", "date": "2025-04-02",
                                            "value": 4, "unit": "count"}]}}}
    (tmp_path / "meta.json").write_text('{"condition": "skill"}')
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "results.json").write_text(json.dumps({"summary": text}))

    assert not check_run(tmp_path, "A", expected, None, None)["matched"]


def test_unit_denominator_compares_independently_of_definition_wording(compare_metrics):
    metric = {"name": "defects", "value": 17, "unit": "count", "numerator": 17, "denominator": 1}
    submitted = {**metric, "denominator": None, "definition": "defect count divided by checked count"}
    result = compare_metrics([metric], [], [submitted], Decimal("0.01"), [])
    assert len(result["matched"]) == 1, result


def test_non_null_denominator_must_match_for_an_average(compare_metrics):
    reference = {"name": "average delay", "value": 6, "denominator": 22, "unit": "s"}
    submitted = {**reference, "denominator": 24}

    result = compare_metrics([reference], [], [submitted], Decimal("0.001"), [])

    [entry] = result["mismatched"]
    assert entry["differences"] == {"denominator": {"expected": 22, "actual": 24}}


@pytest.mark.parametrize(("claim", "bucket"), [("84.48", "matched"), ("84", "mismatched"),
                                                ("84.4", "mismatched")])
@pytest.mark.parametrize("source", ["transcript_text", "report_html", "results.json"])
def test_text_claim_uses_display_precision(tmp_path, source, claim, bucket):
    check_run = eval_function("numeric_check.py", "check_run")
    reference = {"name": "utilization", "value": 84.4827, "unit": "%"}
    expected = {"absolute_tolerance": 0.001, "flows": {"A": {"metrics": [reference]}}}
    report = None
    if source == "transcript_text":
        write_transcript(tmp_path, ("analyst", f"utilization: {claim}%"))
    else:
        # A contradictory transcript must never override the results file.
        if source == "results.json":
            write_transcript(tmp_path, ("analyst", "utilization: 10%"))
            delivery = tmp_path / "delivery"
            delivery.mkdir()
            (delivery / "results.json").write_text(json.dumps({
                "metrics": [{"name": "utilization", "value": claim, "unit": "%"}],
            }))
        else:
            report = tmp_path / "report.html"
            report.write_text(f"<p>utilization: {claim}%</p>")

    result = check_run(tmp_path, "A", expected, None, report)

    [entry] = result[bucket]
    assert entry.get("source", result["source"]) == source
    assert entry["actual"]["value"] == float(claim)


@pytest.mark.parametrize(("unit", "value", "tolerance"), [("ratio", 0.844827, 0.000001),
                                                         ("%", 84.49, 0.02)])
def test_display_precision_respects_unit_scale_and_absolute_tolerance(tmp_path, unit, value, tolerance):
    check_run = eval_function("numeric_check.py", "check_run")
    reference = {"name": "utilization", "value": value, "unit": unit}
    expected = {"absolute_tolerance": tolerance, "flows": {"A": {"metrics": [reference]}}}
    write_transcript(tmp_path, ("analyst", "utilization: 84.48%"))

    assert check_run(tmp_path, "A", expected, None, None)["matched"]


@pytest.mark.parametrize("source", ["eda_summary.json", "results.json"])
def test_json_number_uses_only_absolute_tolerance(tmp_path, source):
    check_run = eval_function("numeric_check.py", "check_run")
    reference = {"name": "utilization", "value": 84.4827, "unit": "%"}
    expected = {"absolute_tolerance": 0.001, "flows": {"A": {"metrics": [reference]}}}
    metric = {**reference, "value": 84.48, "_display_decimals": 2}
    summary = None
    if source == "eda_summary.json":
        write_summary(tmp_path, [metric])
        summary = tmp_path / source
    else:
        delivery = tmp_path / "delivery"
        delivery.mkdir()
        (delivery / source).write_text(json.dumps({"metrics": [metric]}))

    result = check_run(tmp_path, "A", expected, summary, None)

    [entry] = result["mismatched"]
    assert entry["differences"] == {"value": {"expected": 84.4827, "actual": 84.48}}


def test_results_duplicates_ignore_denominators_for_a_non_ratio(tmp_path):
    check_run = eval_function("numeric_check.py", "check_run")
    reference = {"name": "item count", "value": 25, "numerator": 25, "denominator": None}
    expected = {"absolute_tolerance": 0, "flows": {"A": {"metrics": [reference]}}}
    delivery = tmp_path / "delivery"
    delivery.mkdir()
    (delivery / "results.json").write_text(json.dumps({
        "metrics": [{**reference, "denominator": value} for value in (None, 24)],
    }))

    assert check_run(tmp_path, "A", expected, None, None)["matched"]
