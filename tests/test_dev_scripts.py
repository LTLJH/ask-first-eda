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

FAKE_CODEX = """\
#!/usr/bin/env -S python3 -I
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
if args == ["exec", "resume", "--help"]:
    print("  [PROMPT] If `-` is used, read from stdin")
    print("  -m, --model <MODEL>")
    sys.exit(0)

Path(os.environ["FAKE_CALL"]).write_text(
    json.dumps({"argv": args, "stdin": sys.stdin.read()}), encoding="utf-8",
)
Path(args[args.index("-o") + 1]).write_text("Fake reply", encoding="utf-8")
thread_id = os.environ.get("FAKE_THREAD_ID")
if thread_id:
    print(json.dumps({"type": "thread.started", "thread_id": thread_id}))
print(json.dumps({"type": "turn.completed"}))
"""


@pytest.fixture
def invoke_gpt(tmp_path):
    repo = tmp_path / "repo"
    script = repo / "scripts/gpt.sh"
    script.parent.mkdir(parents=True)
    shutil.copyfile(ROOT / "scripts/gpt.sh", script)
    role = repo / "harness/roles/fixture.md"
    role.parent.mkdir(parents=True)
    role.write_text(ROLE_PROMPT, encoding="utf-8")
    task = tmp_path / "task file.md"
    task.write_text(TASK_PROMPT, encoding="utf-8")

    codex = tmp_path / "bin/codex"
    codex.parent.mkdir()
    codex.write_text(FAKE_CODEX, encoding="utf-8")
    codex.chmod(0o700)
    home = tmp_path / "home"
    home.mkdir()
    codex_home = home / ".codex"
    capture = tmp_path / "call.json"
    out = tmp_path / "output file.md"
    log_dir = repo / "_private/tmp/logs"

    def invoke(*, resume=False, thread_id=THREAD_ID, existing=False):
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
        }
        if thread_id is not None:
            env["FAKE_THREAD_ID"] = thread_id
        mode = ["--resume", THREAD_ID] if resume else ["fixture"]
        result = subprocess.run(
            ["bash", str(script), *mode, "fake-model", "medium", str(task), "--out", str(out)],
            cwd=repo, env=env, capture_output=True, text=True, check=True, timeout=15, umask=0o022,
        )
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines())
        assert list(fields) == ["SESSION_ID", "OUT", "LOG", "EXIT"]
        assert Path(fields["OUT"]) == out
        assert Path(fields["LOG"]).parent == log_dir
        assert fields["EXIT"] == "0"
        call = json.loads(capture.read_text(encoding="utf-8"))
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
