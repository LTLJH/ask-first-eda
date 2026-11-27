#!/usr/bin/env bash
set -u
umask 077

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/gpt.sh <role> <model> <effort> <task-file> [--out FILE] [--image IMG]... [--cd DIR] [--sandbox MODE] [--global-home]
  scripts/gpt.sh --resume <SESSION_ID> <model> <effort> <task-file> [--out FILE] [--cd DIR] [--global-home]
EOF
}

argument_error() {
  printf 'Error: %s\n' "$1" >&2
  usage
  exit 2
}

warn() {
  printf 'Warning: %s\n' "$1" >&2
}

absolute_path() {
  case "$1" in
    /*) printf '%s\n' "$1" ;;
    *) printf '%s/%s\n' "$caller_dir" "$1" ;;
  esac
}

has_option() {
  grep -Eq "(^|[[:space:],])($1)([[:space:],=]|$)" <<< "$resume_help"
}

read_log() {
  python3 -I - "$log" <<'PY'
import json
import re
import sys
from pathlib import Path

foreign_path = re.compile(
    r"(?<![\w.-])(?:\.(?:codex|agents|claude)/skills/|plugins/cache/)"
    r"(?!ask-first-eda(?:/|$|[\s'\"`;&|()<>]))"
)
thread_id = ""
secondary_id = ""
foreign = False

with Path(sys.argv[1]).open(encoding="utf-8", errors="replace") as events:
    for line in events:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started":
            thread_id = thread_id or event.get("thread_id")
        if event_type in ("session.started", "session_meta"):
            payload = event.get("payload")
            secondary_id = secondary_id or event.get("session_id") or event.get("id")
            if not secondary_id and isinstance(payload, dict):
                secondary_id = payload.get("id")
        item = event.get("item")
        if event_type == "item.completed" and isinstance(item, dict) and item.get("type") == "command_execution":
            command = item.get("command")
            if isinstance(command, str) and foreign_path.search(command):
                foreign = True

print(thread_id or secondary_id)
print("found" if foreign else "clean")
PY
}

copy_session() {
  python3 -I - "$@" <<'PY'
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

session_id, destination, *sources = sys.argv[1:]
if not re.fullmatch(r"[0-9a-fA-F-]{36}", session_id):
    sys.exit(0)

for source in map(Path, sources):
    for rollout in source.rglob(f"rollout-*-{session_id}.jsonl"):
        if rollout.is_symlink() or not rollout.is_file():
            continue
        target = Path(destination) / rollout.relative_to(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as staged:
            try:
                with rollout.open("rb") as stream:
                    shutil.copyfileobj(stream, staged)
                staged.close()
                os.replace(staged.name, target)
            finally:
                Path(staged.name).unlink(missing_ok=True)
        sys.exit(0)
PY
}

project_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)" || exit 1
caller_dir="$(pwd -P)" || exit 1
session_id=''
run_dir="$project_root"
requested_dir=''
sandbox='workspace-write'
out=''
image_args=()
global_home=false
log_dir="$project_root/_private/tmp/logs"

if [[ "${1:-}" == --resume ]]; then
  [[ "$#" -ge 5 && -n "$2" && "$2" != -* ]] || argument_error 'A session ID is required to resume.'
  session_id="$2"
  role='resume'
  shift 2
else
  [[ "$#" -ge 4 ]] || argument_error 'Role, model, reasoning effort, and task file are required.'
  role="$1"
  [[ "$role" =~ ^[[:alnum:]_-]+$ && "$role" != -* ]] || argument_error "Invalid role name: $role"
  shift
fi

model="$1"
effort="$2"
task_file="$3"
shift 3
[[ -n "$model" && "$model" != -* && -n "$effort" && "$effort" != -* ]] ||
  argument_error 'Model and reasoning effort are required.'
[[ -f "$task_file" && -r "$task_file" ]] || argument_error "Cannot read task file: $task_file"

while [[ "$#" -gt 0 ]]; do
  option="$1"
  case "$option" in
    --global-home) global_home=true; shift; continue ;;
    --out|--cd|--image|--sandbox) ;;
    *) argument_error "Unknown option: $option" ;;
  esac
  [[ "$#" -ge 2 && -n "$2" && "$2" != --* ]] || argument_error "Missing value for $option."
  case "$option" in
    --out) out="$(absolute_path "$2")" ;;
    --cd) requested_dir="$(absolute_path "$2")" ;;
    --image)
      [[ -z "$session_id" ]] || argument_error 'Resume mode does not accept --image.'
      [[ -f "$2" && -r "$2" ]] || argument_error "Cannot read image file: $2"
      image_args+=(-i "$(absolute_path "$2")")
      ;;
    --sandbox)
      [[ -z "$session_id" ]] || argument_error 'Resume mode does not accept --sandbox.'
      case "$2" in
        read-only|workspace-write|danger-full-access) sandbox="$2" ;;
        *) argument_error "Invalid sandbox mode: $2" ;;
      esac
      ;;
  esac
  shift 2
done

prompt="$(cat -- "$task_file")" || exit 1
if ! "$global_home"; then
  source_codex_home="${CODEX_HOME:-$HOME/.codex}"
  isolated_home="$(mktemp -d /tmp/ask-first-eda-gpt.XXXXXXXX)" || exit 1
  trap 'rm -rf -- "$isolated_home"' EXIT
  trap 'exit 129' HUP
  trap 'exit 130' INT
  trap 'exit 143' TERM
  case "$(cd -- "$isolated_home" && pwd -P)" in
    "$project_root"|"$project_root"/*) argument_error 'The isolated home must be outside the repository.' ;;
  esac
  export HOME="$isolated_home" CODEX_HOME="$isolated_home/.codex"
  mkdir -p -- "$CODEX_HOME" "$HOME/.agents/skills" || exit 1
  cat > "$CODEX_HOME/config.toml" <<'EOF' || exit 1
[skills.bundled]
enabled = false

[features]
plugins = false
apps = false
EOF
  if [[ -f "$source_codex_home/auth.json" ]]; then
    cat -- "$source_codex_home/auth.json" > "$CODEX_HOME/auth.json" || exit 1
  fi
  cp -R -- "$project_root/skills/ask-first-eda" "$HOME/.agents/skills/" || exit 1
  if [[ -n "$session_id" ]]; then
    copy_session "$session_id" "$CODEX_HOME/sessions" "$log_dir/sessions" \
      "$source_codex_home/sessions" "$source_codex_home/archived_sessions" || exit 1
  fi
fi

effort_config="model_reasoning_effort=\"$effort\""
if [[ -n "$session_id" ]]; then
  resume_help="$(codex exec resume --help)" || exit 1
  cmd=(codex exec resume -c "$effort_config" --skip-git-repo-check)
  if has_option '-m|--model'; then
    cmd+=(-m "$model")
  else
    warn "This version of codex exec resume does not support -m. Ignoring the requested model ($model)."
  fi
  if [[ -n "$requested_dir" ]]; then
    if has_option '-C|--cd'; then
      [[ -d "$requested_dir" ]] || argument_error "Working directory does not exist: $requested_dir"
      cmd+=(-C "$requested_dir")
    else
      warn "This version of codex exec resume does not support -C. Ignoring --cd ($requested_dir)."
    fi
  fi
else
  run_dir="${requested_dir:-$project_root}"
  [[ -d "$run_dir" ]] || argument_error "Working directory does not exist: $run_dir"
  if [[ "$role" != none ]]; then
    role_file="$project_root/harness/roles/$role.md"
    [[ -f "$role_file" && -r "$role_file" ]] || argument_error "Cannot read role file: $role_file"
    role_prompt="$(cat -- "$role_file")" || exit 1
    prompt="$role_prompt"$'\n\n---\n# Task\n'"$prompt"
  fi
  cmd=(codex exec -m "$model" -c "$effort_config" --sandbox "$sandbox" --skip-git-repo-check -C "$run_dir")
  if [[ "${image_args[0]:-}" == -i ]]; then
    cmd+=("${image_args[@]}")
  fi
fi

timestamp="$(date '+%Y%m%d-%H%M%S')" || exit 1
log="$log_dir/${timestamp}_${role}_$$.jsonl"
out="${out:-$log_dir/${timestamp}_${role}_$$.md}"
[[ "$out" != "$log" ]] || argument_error '--out and the JSONL log must refer to different files.'
mkdir -p -- "$log_dir" "$(dirname -- "$out")" || exit 1
chmod -- 700 "$log_dir" || exit 1
# Preserve existing logs even if the same role starts twice in one second.
(set -C; : > "$log") || exit 1
[[ ! "$out" -ef "$log" ]] || argument_error '--out and the JSONL log must refer to different files.'
chmod -- 600 "$log" || exit 1
# Codex can overwrite a previously created output file without changing its mode.
if [[ -f "$out" ]]; then
  chmod -- 600 "$out" || exit 1
fi

cmd+=(--json -o "$out" --)
if [[ -n "$session_id" ]]; then
  cmd+=("$session_id")
fi
cmd+=(-)

exit_code=0
printf '%s' "$prompt" | (cd -- "$project_root" && "${cmd[@]}") > "$log" || exit_code=$?
log_fields="$(read_log)" || exit 1
id="${log_fields%%$'\n'*}"
foreign_skills="${log_fields##*$'\n'}"
if [[ -z "$id" ]]; then
  warn 'No session ID found.'
fi
if [[ "$foreign_skills" == found ]]; then
  exit_code=3
elif ! "$global_home"; then
  if ! copy_session "${id:-$session_id}" "$log_dir/sessions" "$CODEX_HOME/sessions"; then
    warn 'Could not save the session for resume.'
    [[ "$exit_code" != 0 ]] || exit_code=1
  fi
fi
printf 'SESSION_ID=%s\nOUT=%s\nLOG=%s\nEXIT=%s\nFOREIGN_SKILLS=%s\n' "$id" "$out" "$log" "$exit_code" "$foreign_skills"
exit "$exit_code"
