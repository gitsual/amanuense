#!/usr/bin/env bash
# radar.sh — one unattended pass of the documentation radar over a workshop.
#
# Fetches the repos in repos.txt, runs the workshop (report, tasks, change log), refreshes the
# capability radiator when the workshop has a radiador.json and, with --commit, records the
# result as a commit, so `git log -- <workshop>` becomes the history of the radar.
#
#   scripts/radar.sh                               one pass over AMANUENSE_WORKSPACE
#   scripts/radar.sh --workspace ~/team/docs       another workshop
#   scripts/radar.sh --commit [--push]             commit the snapshot (and push it)
#   scripts/radar.sh --deliver                     also build output/delivery-DATE
#   scripts/radar.sh -- --ai-cli claude            everything after "--" goes to "amanuense run"
#
# Options: --workspace DIR, --env FILE (default: the .env next to amanuense.sh), --log FILE
# (default: <workshop>/radar.log), --commit, --push, --deliver, -h/--help.
# Exit codes: 0 done, 1 setup error, 2 bad option, 3 another pass is running, 4 a repo is
# unreachable, 5 the push was rejected and could not be rebased cleanly.
#
# It never asks for a password (GIT_TERMINAL_PROMPT=0, GCM_INTERACTIVE=never): save the Git
# credentials first (one manual clone does it). Works in Linux, macOS and Git Bash on Windows.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$HERE/.env"
WS="" LOG="" COMMIT=0 PUSH=0 DELIVER=0 RUN_ARGS=()
die() { echo "✗ $1" >&2; exit "${2:-1}"; }
while (($#)); do
  case "$1" in
    --workspace) [[ $# -ge 2 ]] || die "--workspace needs a folder" 2; WS="$2"; shift ;;
    --workspace=*) WS="${1#*=}" ;;
    --env) [[ $# -ge 2 ]] || die "--env needs a file" 2; ENV_FILE="$2"; shift ;;
    --env=*) ENV_FILE="${1#*=}" ;;
    --log) [[ $# -ge 2 ]] || die "--log needs a file" 2; LOG="$2"; shift ;;
    --log=*) LOG="${1#*=}" ;;
    --commit) COMMIT=1 ;;
    --push) COMMIT=1 PUSH=1 ;;
    --deliver) DELIVER=1 ;;
    --) shift; RUN_ARGS=("$@"); break ;;
    -h|--help) sed -n '2,21p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) die "unknown option: $1 (see --help)" 2 ;;
  esac
  shift
done

# Settings and secrets: the launcher's .env (ignored by Git; see .env.example), read as plain
# KEY=VALUE lines the way amanuense.ps1 reads it, so "AMANUENSE_USER=Ana Ruiz" works unquoted.
# Windows editors leave CRLF line ends, which would otherwise end up inside every value.
if [[ -f "$ENV_FILE" ]]; then
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line%$'\r'}"
    [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=(.*)$ ]] || continue
    key="${BASH_REMATCH[2]}" value="${BASH_REMATCH[3]}"
    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ "$value" =~ ^\"(.*)\"$ || "$value" =~ ^\'(.*)\'$ ]]; then value="${BASH_REMATCH[1]}"; fi
    export "$key=$value"
  done < "$ENV_FILE"
fi

DEFAULT_WS="$HOME/docs-workshop"
[[ -d "$HOME/taller-docs" ]] && DEFAULT_WS="$HOME/taller-docs"
WS="${WS:-${AMANUENSE_WORKSPACE:-$DEFAULT_WS}}"
[[ -d "$WS" ]] || die "no workshop at $WS (set AMANUENSE_WORKSPACE or pass --workspace)"
WS="$(cd "$WS" && pwd)"
LOG="${LOG:-$WS/radar.log}"

exec > >(tee -a "$LOG") 2>&1
echo "── radar $(date '+%F %T') · $WS"

# A scheduled pass and a manual one must not overlap.
LOCK="$WS/.radar.lock"
mkdir "$LOCK" 2>/dev/null || die "another pass is running (remove $LOCK if it is stale)" 3
trap 'rmdir "$LOCK" 2>/dev/null || true' EXIT

export GIT_TERMINAL_PROMPT=0 GCM_INTERACTIVE=never
ROOT="$(git -C "$WS" rev-parse --show-toplevel 2>/dev/null || true)"
((COMMIT == 0)) || [[ -n "$ROOT" ]] || die "--commit needs the workshop inside a Git repository"

# The log records who ran each pass: the configured name or the Git identity, never the OS login.
[[ -n "${AMANUENSE_USER:-}" ]] || AMANUENSE_USER="$(git -C "$WS" config user.name 2>/dev/null || true)"
[[ -n "$AMANUENSE_USER" ]] || die "set AMANUENSE_USER in .env or git config user.name"
export AMANUENSE_USER

# Python 3.11+: the repo's .venv, the PATH, then the Windows launcher and the usual install folders.
PY=()
ok() { "$@" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; }
for c in "$HERE/.venv/bin/python" "$HERE/.venv/Scripts/python.exe" \
         python3.14 python3.13 python3.12 python3.11 python3 python; do
  if command -v "$c" >/dev/null 2>&1 && ok "$c"; then PY=("$c"); break; fi
done
if ((${#PY[@]} == 0)) && command -v py >/dev/null 2>&1 && ok py -3; then PY=(py -3); fi
if ((${#PY[@]} == 0)) && command -v cygpath >/dev/null 2>&1; then
  for c in "$(cygpath -u "${LOCALAPPDATA:-}")"/Programs/Python/Python3*/python.exe \
           "$(cygpath -u "${PROGRAMFILES:-}")"/Python3*/python.exe; do
    if [[ -x "$c" ]] && ok "$c"; then PY=("$c"); break; fi
  done
fi
((${#PY[@]})) || die "Python 3.11 or newer not found"
# A Windows Python needs Windows paths; Git Bash's cygpath gives them.
native() { if command -v cygpath >/dev/null 2>&1; then cygpath -w "$1"; else echo "$1"; fi; }
SRC="$(native "$HERE/src")"
if command -v cygpath >/dev/null 2>&1; then SEP=";"; else SEP=":"; fi
export PYTHONPATH="$SRC${PYTHONPATH:+$SEP$PYTHONPATH}" PYTHONIOENCODING=utf-8 PYTHONUTF8=1
WS_NATIVE="$(native "$WS")"
amanuense() { "${PY[@]}" -m amanuense "$@"; }

# Without the Git server every fetch would fail one by one: probe the first URL and stop early.
PROBE=""
if [[ -f "$WS/repos.txt" ]]; then
  PROBE="$(tr -d '\r' < "$WS/repos.txt" | sed -n -E '/^[[:space:]]*([A-Za-z][A-Za-z0-9+.-]*:\/\/|[A-Za-z0-9._-]+@[A-Za-z0-9._-]+:)/{s/^[[:space:]]*//;s/[[:space:]]+@.*$//;s/[[:space:]]*$//;p;q;}')"
fi
if [[ -n "$PROBE" ]]; then
  probe=(git ls-remote --heads "$PROBE")
  command -v timeout >/dev/null 2>&1 && probe=(timeout "${RADAR_PROBE_TIMEOUT:-60}" "${probe[@]}")
  "${probe[@]}" >/dev/null 2>&1 || die "cannot reach $PROBE (network, VPN or saved credentials?); nothing done" 4
fi

amanuense run "$WS_NATIVE" --no-open ${RUN_ARGS[@]+"${RUN_ARGS[@]}"}
if [[ -f "$WS/radiador.json" ]]; then amanuense radiator "$WS_NATIVE" --no-open >/dev/null; fi
if ((DELIVER)); then amanuense deliver "$WS_NATIVE" --no-open; fi

if ((COMMIT)); then
  # Clones, zips, the lock and the log are not part of the snapshot.
  SNAP=(. ':(exclude)repos' ':(exclude)*.zip' ':(exclude).radar.lock' ':(exclude)radar.log')
  [[ "$(cd "$(dirname "$LOG")" && pwd)" == "$WS" ]] && SNAP+=(":(exclude)$(basename "$LOG")")
  git -C "$WS" add -A -- "${SNAP[@]}"
  # The radiator stamps its generation time, and the comparison when it read Confluence and
  # when it ran; those stamps alone are not a change.
  STAMP='"(generated|fetched|used)": "|Generad[oa] por amanuense|Generated by amanuense'
  if git -C "$WS" diff --cached --quiet -I "$STAMP" -- "${SNAP[@]}"; then
    git -C "$WS" restore --staged --worktree -- "${SNAP[@]}" 2>/dev/null || true
    echo "· no changes since the last pass"
  else
    git -C "$WS" commit -q -m "chore(radar): snapshot $(date -u '+%F %H:%M') UTC" -- "${SNAP[@]}"
    echo "✓ $(git -C "$WS" log -1 --format='%h %s')"
  fi
fi

if ((PUSH)); then
  if git -C "$ROOT" push -q 2>/dev/null; then
    echo "✓ pushed"
  elif [[ -z "$(git -C "$ROOT" status --porcelain --untracked-files=no)" ]] && git -C "$ROOT" pull -q --rebase; then
    git -C "$ROOT" push -q && echo "✓ pushed after rebasing"
  else
    git -C "$ROOT" rebase --abort 2>/dev/null || true
    die "push rejected and the branch could not be rebased cleanly; push it by hand" 5
  fi
fi
echo "· done"
