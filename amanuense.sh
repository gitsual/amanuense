#!/usr/bin/env bash
# amanuense.sh — documentation workshop (see docs/guide.md).
#   First run creates the workshop folder; next runs analyse it and open output/index.html.
#   ./amanuense.sh [extra args, e.g. --ai-cli claude]
#   ./amanuense.sh obsidian EXPORT.docx VAULT/MIND   (export to an Obsidian vault)
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
# --lang works before or after the subcommand; init only needs that one flag.
LANG_ARGS=()
for ((i = 1; i <= $#; i++)); do
  case "${!i}" in
    --lang) j=$((i + 1)); LANG_ARGS=(--lang "${!j:-}") ;;
    --lang=*) LANG_ARGS=("${!i}") ;;
  esac
done
if [[ ! -d "$WS/1-confluence-export" && ! -d "$WS/1-export-confluence" ]]; then
  GUIDE="$("$PY" -m amanuense "${LANG_ARGS[@]}" init "$WS")"
  echo "Workshop created: $WS — fill its folders (see $GUIDE) and run this again."
  exit 0
fi
exec "$PY" -m amanuense run "$WS" "$@"
