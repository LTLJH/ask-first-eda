"""Check project-scope EDA skill activation with Claude Code and Codex."""

import argparse
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
SKILL_NAME = "ask-first-eda"
CACHE = Path(".cache") / "ask-first-eda-install"
PROJECT_SKILLS = {
    "claude": Path(".claude/skills") / SKILL_NAME,
    # https://developers.openai.com/api/reference/cli (project installation)
    "codex": Path(".agents/skills") / SKILL_NAME,
}
PROMPTS = (
    ("이 CSV 좀 봐줘. 어떤 데이터인지 파악하고 싶어", True),
    ("Run EDA on sales.csv", True),
    ("로지스틱 회귀 모델 학습 코드 짜줘", False),
    ("What is a p-value?", False),
)
CLAUDE_REQUIRED = (
    "--tools", "Read,Skill", "--permission-mode", "plan", "--setting-sources", "project",
    "--strict-mcp-config", "--mcp-config", '{"mcpServers":{}}', "--disallowedTools", "mcp__*",
)
CLAUDE_OPTIONAL = ("--max-turns", "3", "--no-session-persistence")
VERSION = re.compile(r"(?<!\d)\d+\.\d+\.\d+(?:-[a-zA-Z0-9.]+)?")


def command(client, binary, prompt, claude_options):
    if client == "claude":
        return [binary, "-p", prompt, "--output-format", "stream-json", "--verbose",
                *CLAUDE_REQUIRED, *claude_options]
    return [binary, "exec", "--json", "--sandbox", "read-only", "--skip-git-repo-check",
            "--ephemeral", "--ignore-user-config", "-c", 'approval_policy="never"', "--", prompt]


def client_stdout(args, cwd, timeout):
    env = dict(os.environ, PWD=str(cwd))
    env.pop("OLDPWD", None)
    # Allow Claude Code to run from an orchestrator session.
    env.pop("CLAUDECODE", None)
    try:
        result = subprocess.run(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                capture_output=True, encoding="utf-8", errors="replace",
                                check=False, timeout=timeout)
    except subprocess.TimeoutExpired as error:
        return (error.stdout or b"").decode("utf-8", errors="replace"), False
    except OSError:
        return "", False
    return result.stdout, result.returncode == 0


def json_events(stdout):
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(event, dict):
            yield event


def is_manifest(path, manifest, cwd):
    if not isinstance(path, str) or not path:
        return False
    # Codex and Claude may emit either an absolute path or one relative to cwd.
    candidate = Path.home() / path[2:] if path.startswith("~/") else cwd / path
    return Path(os.path.normpath(candidate)) == manifest


def reads_manifest(command_text, manifest, cwd, output):
    if not isinstance(command_text, str):
        return False
    try:
        lexer = shlex.shlex(command_text, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        words = list(lexer)
    except ValueError:
        return False
    if not words:
        return False
    program = Path(words[0]).name
    if program in {"sh", "bash", "zsh"} and len(words) >= 3 and words[1] in {"-c", "-lc", "-cl"}:
        return reads_manifest(words[2], manifest, cwd, output)
    segments = [[]]
    for word in words:
        if word in {";", "&&", "||", "|"}:
            segments.append([])
        else:
            segments[-1].append(word)
    if len(segments) > 1 and not (
        isinstance(output, str) and f"name: {SKILL_NAME}" in output.splitlines()
    ):
        # The final shell status does not prove an earlier command ran successfully.
        return False
    for segment in segments:
        if not segment:
            continue
        program, *args = segment
        if program == "cd" and len(args) == 1:
            cwd = Path(os.path.normpath(cwd / args[0]))
        elif Path(program).name in {"cat", "head", "tail", "sed", "awk", "rg", "grep", "nl", "bat"}:
            if any(is_manifest(arg, manifest, cwd) for arg in args):
                return True
    return False


def codex_observation(events, manifest, cwd):
    completed = False
    for event in events:
        if event.get("type") == "turn.completed":
            completed = True
        if event.get("type") != "item.completed":
            continue
        item = event.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") == "command_execution" and item.get("exit_code") == 0:
            if reads_manifest(item.get("command"), manifest, cwd, item.get("aggregated_output")):
                return True, completed
        if item.get("type") == "file_read" and item.get("status") not in {"failed", "declined"}:
            if is_manifest(item.get("path") or item.get("file_path"), manifest, cwd):
                return True, completed
    return False, completed


def claude_observation(events, manifest, cwd):
    activations = set()
    denied = set()
    completed = False
    for event in events:
        kind = event.get("type")
        if kind == "result":
            completed = event.get("subtype") == "success" and not event.get("is_error")
            for denial in event.get("permission_denials", []):
                denied.add(denial.get("tool_use_id"))
        if kind not in {"assistant", "user"}:
            continue
        for block in event.get("message", {}).get("content", []):
            if not isinstance(block, dict):
                continue
            if block.get("type") == "tool_result" and block.get("is_error"):
                denied.add(block.get("tool_use_id"))
            if kind != "assistant" or block.get("type") != "tool_use":
                continue
            name, args = block.get("name"), block.get("input", {})
            if ((name == "Skill" and (args.get("skill") or args.get("name")) == SKILL_NAME)
                    or (name == "Read" and is_manifest(args.get("file_path"), manifest, cwd))):
                activations.add(block.get("id", "unidentified-tool-use"))
    return bool(activations - denied), completed


def probe_client(client, binary, project, timeout):
    stdout, ok = client_stdout([binary, "--version"], project, timeout)
    match = VERSION.search(stdout) if ok else None
    version = match[0] if match else "unverified"
    if not match or client != "claude":
        return version, bool(match), ()
    help_text, ok = client_stdout([binary, "--help"], project, timeout)
    required = (argument for argument in CLAUDE_REQUIRED if argument.startswith("--"))
    if not ok or not all(flag in help_text for flag in required):
        return version, False, ()
    options = []
    if "--max-turns" in help_text:
        options.extend(CLAUDE_OPTIONAL[:2])
    if "--no-session-persistence" in help_text:
        options.append(CLAUDE_OPTIONAL[-1])
    return version, True, options


def smoke(client, location, timeout):
    binary = os.environ.get(f"{client.upper()}_BIN") or client
    if os.sep in binary:
        binary = str(Path(binary).expanduser().resolve())
    base = Path.home() / CACHE / client
    resolved = base.resolve()
    if resolved != Path.home().resolve() / CACHE / client or resolved.is_relative_to(ROOT):
        raise ValueError("Smoke workspace must be a non-symlink cache directory outside the repository")
    base.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="project-", dir=base) as folder:
        project = Path(folder).resolve()
        version, available, options = probe_client(client, binary, project, timeout)
        manifest = project / location / "SKILL.md"
        if available:
            source = ROOT / "skills" / SKILL_NAME
            if not (source / "SKILL.md").is_file():
                raise ValueError(f"Missing {source.relative_to(ROOT) / 'SKILL.md'}")
            shutil.copytree(source, project / location, ignore=ignore_links)
            (project / "sales.csv").write_text("month,sales\nJan,8\nFeb,11\nMar,9\n", encoding="utf-8")
        for prompt, expected in PROMPTS:
            observed = "unverified"
            if available:
                output, ok = client_stdout(command(client, binary, prompt, options), project, timeout)
                observe = claude_observation if client == "claude" else codex_observation
                activated, completed = observe(json_events(output), manifest, project)
                if activated:
                    observed = True
                elif ok and completed:
                    observed = False
            yield {
                "client": client, "version": version, "install_path_type": "project",
                "install_path": f"~/{CACHE / client}/<project>/{location}/",
                "prompt": prompt, "expected": expected, "observed": observed,
                "pass": observed == expected if isinstance(observed, bool) else None,
            }


def ignore_links(folder, names):
    return [name for name in names if (Path(folder) / name).is_symlink()]


def print_results(rows):
    columns = ("client", "version", "install_path", "prompt", "expected", "observed", "pass")
    print("| " + " | ".join(columns) + " |")
    print("| " + " | ".join(["---"] * len(columns)) + " |")
    for row in rows:
        values = ("unverified" if row[key] is None else str(row[key]) for key in columns)
        print("| " + " | ".join(values) + " |")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Print the planned commands and manifest paths")
    parser.add_argument("--timeout", type=int, default=120, help="Seconds per client invocation")
    args = parser.parse_args()
    if args.timeout < 1:
        parser.error("--timeout must be positive")
    if args.dry_run:
        for client, location in PROJECT_SKILLS.items():
            for prompt, _ in PROMPTS:
                cmd = command(client, client, prompt, CLAUDE_OPTIONAL)
                print(f'(cd ~/{CACHE / client}/"$SMOKE_PROJECT"/ && {shlex.join(cmd)})'
                      f"  # project manifest: {location.as_posix()}/SKILL.md")
        return 0
    try:
        rows = [row for client, location in PROJECT_SKILLS.items()
                for row in smoke(client, location, args.timeout)]
        path = Path(__file__).with_suffix(".json")
        path.write_text(json.dumps(rows, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError):
        parser.exit(1, "Could not stage the smoke project or write the results.\n")
    print_results(rows)
    return 0 if all(row["pass"] for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
