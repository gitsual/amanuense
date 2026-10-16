#!/usr/bin/env bash
# amanuense.sh — documentation workshop (see docs/guide.md).
#   No arguments: opens the review app (the first time it also creates the workshop folder).
#   ./amanuense.sh [run args, e.g. --ai-cli claude]   (look for changes, then the app)
#   ./amanuense.sh obsidian EXPORT.docx VAULT/MIND   (export to an Obsidian vault)
#   ./amanuense.sh vault                             (rebuild WORKSHOP/vault from the whole workshop)
#   ./amanuense.sh deliver --zip                     (delivery folder + zip)
#   ./amanuense.sh --lang es        (Spanish workshop; default English, an existing workshop keeps its own)
#   Workshop folder: AMANUENSE_WORKSPACE (or .env), default ~/docs-workshop (~/taller-docs if it exists).
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$HERE/.env" ]] && set -a && source "$HERE/.env" && set +a
DEFAULT_WS="$HOME/docs-workshop"
[[ -d "$HOME/taller-docs" ]] && DEFAULT_WS="$HOME/taller-docs"
WS="${AMANUENSE_WORKSPACE:-$DEFAULT_WS}"
PY=""
for c in "$HERE/.venv/bin/python" python3.14 python3.13 python3.12 python3.11 python3 python; do
  c="$(command -v "$c" 2>/dev/null)" || continue
  "$c" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null && { PY="$c"; break; }
done
[[ -n "$PY" ]] || { echo "✗ missing: Python 3.11 or newer" >&2; exit 1; }
export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"
[[ "${1:-}" == obsidian ]] && exec "$PY" -m amanuense "$@"
[[ "${1:-}" == vault ]] && exec "$PY" -m amanuense obsidian "$WS" "$WS/vault" --force "${@:2}"
# --lang works before or after the subcommand; init only needs that one flag.
LANG_ARGS=()
for ((i = 1; i <= $#; i++)); do
  case "${!i}" in
    --lang) j=$((i + 1)); LANG_ARGS=(--lang "${!j:-}") ;;
    --lang=*) LANG_ARGS=("${!i}") ;;
  esac
done
if [[ "${1:-}" == review ]]; then shift; exec "$PY" -m amanuense review "$WS" "$@"; fi
if [[ $# -eq ${#LANG_ARGS[@]} ]]; then exec "$PY" -m amanuense review "$WS" "$@"; fi
[[ "${1:-}" == radiator ]] && exec "$PY" -m amanuense radiator "$WS" "${@:2}"
if [[ ! -d "$WS/1-confluence-export" && ! -d "$WS/1-export-confluence" ]]; then
  GUIDE="$("$PY" -m amanuense "${LANG_ARGS[@]}" init "$WS")"
  echo "Workshop created: $WS — fill its folders (see $GUIDE) and run this again."
  exit 0
fi
[[ "${1:-}" == deliver ]] && exec "$PY" -m amanuense deliver "$WS" "${@:2}"
exec "$PY" -m amanuense run "$WS" "$@"
