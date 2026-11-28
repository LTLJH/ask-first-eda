import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="gpt.sh requires Bash and POSIX permissions")

ROOT = Path(__file__).resolve().parents[1]
ROLE_PROMPT = "Synthetic role instructions"
TASK_PROMPT = "Synthetic task contents\nSecond line"
THREAD_ID = "2b7c1a05-42ef-4573-95e1-74d0479f1a61"
AUTH = '{"token":"fixture-only"}\n'
ISOLATION_CONFIG = "[skills.bundled]\nenabled = false\n\n[features]\nplugins = false\napps = false"

FAKE_CODEX = """\
#!/usr/bin/env -S python3 -I
import json
import os
from pathlib import Path
from stat import S_IMODE
import sys

args = sys.argv[1:]
if args == ["exec", "resume", "--help"]:
    print("  [PROMPT] If `-` is used, read from stdin")
    print("  -m, --model <MODEL>")
    sys.exit(0)

home = Path(os.environ["HOME"])
codex_home = Path(os.environ["CODEX_HOME"])
config = codex_home / "config.toml"
auth = codex_home / "auth.json"
skills = home / ".agents/skills"
skill = skills / "ask-first-eda/SKILL.md"
call = {
    "argv": args, "stdin": sys.stdin.read(), "home": str(home), "codex_home": str(codex_home),
    "config": config.read_text(encoding="utf-8") if config.is_file() else None,
    "auth": auth.read_text(encoding="utf-8") if auth.is_file() else None,
    "auth_mode": S_IMODE(auth.stat().st_mode) if auth.is_file() else None,
    "skills": sorted(entry.name for entry in skills.iterdir()) if skills.is_dir() else [],
    "skill": skill.read_text(encoding="utf-8") if skill.is_file() else None,
    "skill_symlink": skill.is_symlink() or skill.parent.is_symlink(),
    "skill_resolved": str(skill.resolve()),
}
Path(os.environ["FAKE_CALL"]).write_text(json.dumps(call), encoding="utf-8")
Path(args[args.index("-o") + 1]).write_text("Fake reply", encoding="utf-8")
thread_id = os.environ.get("FAKE_THREAD_ID")
if thread_id:
    print(json.dumps({"type": "thread.started", "thread_id": thread_id}))
if command := os.environ.get("FAKE_COMMAND"):
    print(json.dumps({"type": "item.completed", "item": {
        "id": "item_0", "type": "command_execution", "command": command, "exit_code": 0,
    }}))
print(json.dumps({"type": "turn.completed"}))
sys.exit(int(os.environ["FAKE_EXIT_CODE"]))
"""


@pytest.fixture
def run_gpt(tmp_path):
    repo = tmp_path / "repo"
    script = repo / "scripts/gpt.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/gpt.sh", script)
    role = repo / "harness/roles/fixture.md"
    role.parent.mkdir(parents=True)
    role.write_text(ROLE_PROMPT, encoding="utf-8")
    skill = repo / "skills/ask-first-eda/SKILL.md"
    skill.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "skills/ask-first-eda/SKILL.md", skill)
    task = tmp_path / "task file.md"
    task.write_text(TASK_PROMPT, encoding="utf-8")

    codex = tmp_path / "bin/codex"
    codex.parent.mkdir()
    codex.write_text(FAKE_CODEX, encoding="utf-8")
    codex.chmod(0o700)
    home = tmp_path / "home"
    foreign_skill = home / ".agents/skills/unrelated/SKILL.md"
    foreign_skill.parent.mkdir(parents=True)
    foreign_skill.write_text("Unrelated fixture skill", encoding="utf-8")
    codex_home = tmp_path / "source-codex"
    codex_home.mkdir()
    auth = codex_home / "auth.json"
    auth.write_text(AUTH, encoding="utf-8")
    auth.chmod(0o644)
    capture = tmp_path / "call.json"
    out = tmp_path / "output file.md"
    log_dir = repo / "_private/tmp/logs"

    def invoke(*, resume=False, thread_id=THREAD_ID, existing=False, global_home=False,
               command=None, exit_code=0):
        if existing:
            log_dir.mkdir(parents=True)
            log_dir.chmod(0o755)
            out.write_text("Previous reply", encoding="utf-8")
            out.chmod(0o644)
        if thread_id is None:
            sessions = codex_home / "sessions"
            sessions.mkdir(parents=True)
            (sessions / "rollout-2026-01-01T12-00-00-93d86d18-c367-41fb-8e73-d53f2b6a8120.jsonl").touch()

        env = {
            "PATH": os.pathsep.join(map(str, (codex.parent, Path(sys.executable).parent, os.defpath))),
            "HOME": str(home),
            "CODEX_HOME": str(codex_home),
            "FAKE_CALL": str(capture),
            "FAKE_EXIT_CODE": str(exit_code),
        }
        if thread_id is not None:
            env["FAKE_THREAD_ID"] = thread_id
        if command is not None:
            env["FAKE_COMMAND"] = command
        mode = ["--resume", THREAD_ID] if resume else ["fixture"]
        options = ["--global-home"] if global_home else []
        result = subprocess.run(
            ["bash", str(script), *mode, "fake-model", "medium", str(task), "--out", str(out), *options],
            cwd=repo, env=env, capture_output=True, text=True, timeout=15, umask=0o022,
        )
        call = json.loads(capture.read_text(encoding="utf-8")) if capture.is_file() else None
        return result, call

    return invoke


@pytest.fixture
def invoke_gpt(run_gpt, tmp_path):
    def invoke(**kwargs):
        result, call = run_gpt(**kwargs)
        result.check_returncode()
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines())
        assert [key for key in fields if key != "FOREIGN_SKILLS"] == ["SESSION_ID", "OUT", "LOG", "EXIT"]
        assert Path(fields["OUT"]) == tmp_path / "output file.md"
        assert Path(fields["LOG"]).parent == tmp_path / "repo/_private/tmp/logs"
        assert fields["EXIT"] == "0"
        return fields, call, result.stderr

    return invoke


@pytest.mark.parametrize("resume", [False, True], ids=["new", "resume"])
def test_gpt_passes_prompt_on_stdin(invoke_gpt, resume):
    _, call, _ = invoke_gpt(resume=resume)
    assert call["argv"][-1] == "-"
    assert all(TASK_PROMPT not in arg and ROLE_PROMPT not in arg for arg in call["argv"])
    expected = TASK_PROMPT if resume else f"{ROLE_PROMPT}\n\n---\n# Task\n{TASK_PROMPT}"
    assert call["stdin"] == expected


@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing"])
def test_gpt_keeps_logs_and_output_private(invoke_gpt, existing):
    fields, _, _ = invoke_gpt(existing=existing)
    log = Path(fields["LOG"])
    out = Path(fields["OUT"])
    assert {path: stat.S_IMODE(path.stat().st_mode) for path in (log.parent, log, out)} == {
        log.parent: 0o700,
        log: 0o600,
        out: 0o600,
    }
    assert out.read_text(encoding="utf-8") == "Fake reply"


@pytest.mark.parametrize("resume", [False, True], ids=["new", "resume"])
def test_gpt_warns_when_current_log_has_no_session_id(invoke_gpt, resume):
    fields, _, stderr = invoke_gpt(resume=resume, thread_id=None)
    assert fields["SESSION_ID"] == ""
    assert "Warning: No session ID found" in stderr


def test_gpt_reports_thread_started_id(invoke_gpt):
    fields, _, stderr = invoke_gpt()
    assert fields["SESSION_ID"] == THREAD_ID
    assert "No session ID found" not in stderr


@pytest.mark.parametrize(("resume", "exit_code"), [
    pytest.param(False, 0, id="success"),
    pytest.param(False, 7, id="failure"),
    pytest.param(True, 0, id="resume"),
])
def test_gpt_skill_isolation_uses_and_removes_temporary_homes(run_gpt, tmp_path, resume, exit_code):
    result, call = run_gpt(resume=resume, exit_code=exit_code)

    assert result.returncode == exit_code, result.stderr
    assert call is not None
    if resume:
        assert call["argv"][:2] == ["exec", "resume"]
        assert THREAD_ID in call["argv"]
    home, codex_home = Path(call["home"]), Path(call["codex_home"])
    caller_homes = {Path.home().resolve(), tmp_path / "home", tmp_path / "source-codex"}
    for directory in (home, codex_home):
        assert directory.is_absolute()
        assert directory.resolve() not in caller_homes
        assert not directory.resolve().is_relative_to(ROOT)
        assert not directory.resolve().is_relative_to(tmp_path / "repo")
        assert not directory.exists()
    assert (call["config"] or "").strip() == ISOLATION_CONFIG
    assert call["auth"] == AUTH
    assert call["auth_mode"] == 0o600
    assert (tmp_path / "source-codex/auth.json").read_text(encoding="utf-8") == AUTH


def test_gpt_skill_isolation_copies_only_ask_first_eda(run_gpt, tmp_path):
    result, call = run_gpt()

    assert result.returncode == 0, result.stderr
    assert call is not None
    assert call["skills"] == ["ask-first-eda"]
    source = tmp_path / "repo/skills/ask-first-eda/SKILL.md"
    assert call["skill"] == source.read_text(encoding="utf-8")
    assert not call["skill_symlink"]
    assert Path(call["skill_resolved"]).is_relative_to(Path(call["home"]).resolve())


def test_gpt_skill_isolation_global_home_opt_out(run_gpt, tmp_path):
    result, call = run_gpt(global_home=True)

    assert result.returncode == 0, result.stderr
    assert call is not None
    assert Path(call["home"]) == tmp_path / "home"
    assert Path(call["codex_home"]) == tmp_path / "source-codex"


@pytest.mark.parametrize(("command", "codex_exit", "status", "exit_code"), [
    pytest.param("cat ~/.codex/skills/using-superpowers/SKILL.md", 0, "found", 3, id="codex"),
    pytest.param("cat .agents/skills/other/SKILL.md", 0, "found", 3, id="agents"),
    pytest.param("cat ~/.claude/skills/other/SKILL.md", 0, "found", 3, id="claude"),
    pytest.param("cat ~/.codex/plugins/cache/other/SKILL.md", 0, "found", 3, id="plugins-cache"),
    pytest.param("cat .agents/skills/ask-first-eda-extra/SKILL.md", 0, "found", 3, id="lookalike"),
    pytest.param("cat .agents/skills/ask-first-eda/SKILL.md", 0, "clean", 0, id="clean-success"),
    pytest.param("cat .agents/skills/ask-first-eda/SKILL.md", 7, "clean", 7, id="clean-failure"),
])
def test_gpt_skill_isolation_reports_foreign_skills(run_gpt, command, codex_exit, status, exit_code):
    result, call = run_gpt(command=command, exit_code=codex_exit)

    assert call is not None
    assert result.returncode == exit_code, result.stdout + result.stderr
    assert f"FOREIGN_SKILLS={status}" in result.stdout.splitlines()


@pytest.mark.skipif(shutil.which("git") is None, reason="Git is required")
def test_pre_commit_runs_pytest_in_the_committing_worktree(tmp_path):
    repo = tmp_path / "repo"
    worktree = tmp_path / "linked worktree"
    capture = tmp_path / "pytest-calls.txt"
    env = {
        "PATH": os.environ.get("PATH", os.defpath),
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Fixture",
        "GIT_AUTHOR_EMAIL": "fixture@example.com",
        "GIT_COMMITTER_NAME": "Fixture",
        "GIT_COMMITTER_EMAIL": "fixture@example.com",
        "FAKE_PYTEST_CALLS": str(capture),
    }

    def git(*args, cwd=repo):
        result = subprocess.run(
            ["git", *args], cwd=cwd, env=env, capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr

    hook = repo / "scripts/hooks/pre-commit"
    hook.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/hooks/pre-commit", hook)
    hook.chmod(0o755)
    git("init", "--template=")
    git("add", "scripts/hooks/pre-commit")
    git("commit", "-m", "Add fixture hook")
    git("worktree", "add", "--detach", str(worktree), "HEAD")

    shared_hook = repo / ".git/hooks/pre-commit"
    shared_hook.parent.mkdir()
    shared_hook.symlink_to("../../scripts/hooks/pre-commit")
    for tree in (repo, worktree):
        fake_pytest = tree / Path(".venv", "bin", "pytest")
        fake_pytest.parent.mkdir(parents=True)
        fake_pytest.write_text(
            '#!/bin/sh\n'
            'cd "$(dirname "$0")/../.." || exit 1\n'
            'pwd -P >> "$FAKE_PYTEST_CALLS"\n',
            encoding="utf-8",
        )
        fake_pytest.chmod(0o700)

    git("commit", "--allow-empty", "-m", "Commit in main checkout")
    assert capture.read_text(encoding="utf-8").splitlines() == [str(repo.resolve())]

    git("commit", "--allow-empty", "-m", "Commit in linked worktree", cwd=worktree)
    assert capture.read_text(encoding="utf-8").splitlines() == [
        str(repo.resolve()), str(worktree.resolve()),
    ]
