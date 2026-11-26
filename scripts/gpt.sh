#!/usr/bin/env bash
set -u
umask 077

usage() {
  cat >&2 <<'EOF'
Usage:
  scripts/gpt.sh <role> <model> <effort> <task-file> [--out FILE] [--image IMG]... [--cd DIR] [--sandbox MODE]
  scripts/gpt.sh --resume <SESSION_ID> <model> <effort> <task-file> [--out FILE] [--cd DIR]
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

extract_session_id() {
  python3 -I - "$log" <<'PY'
import json
import sys
from pathlib import Path

log = sys.argv[1]
secondary_id = ""

with Path(log).open(encoding="utf-8", errors="replace") as events:
    for line in events:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict):
            continue
        event_type = event.get("type")
        if event_type == "thread.started" and event.get("thread_id"):
            print(event["thread_id"])
            sys.exit(0)
        if event_type in ("session.started", "session_meta"):
            payload = event.get("payload")
            secondary_id = secondary_id or event.get("session_id") or event.get("id")
            if not secondary_id and isinstance(payload, dict):
                secondary_id = payload.get("id")

if secondary_id:
    print(secondary_id)
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

log_dir="$project_root/_private/tmp/logs"
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
id="$(extract_session_id)" || id=''
if [[ -z "$id" ]]; then
  warn 'No session ID found.'
fi
printf 'SESSION_ID=%s\nOUT=%s\nLOG=%s\nEXIT=%s\n' "$id" "$out" "$log" "$exit_code"
exit "$exit_code"
