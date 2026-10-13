#!/usr/bin/env bash
# amanuense.sh — documentation workshop (see docs/guia.md).
#   First run creates the workshop folder; next runs analyse it and open salida/index.html.
#   ./amanuense.sh [extra args, e.g. --ai-cli claude]
#   Workshop folder: AMANUENSE_WORKSPACE (or .env), default ~/taller-docs.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$HERE/.env" ]] && set -a && source "$HERE/.env" && set +a
WS="${AMANUENSE_WORKSPACE:-$HOME/taller-docs}"
PY="$HERE/.venv/bin/python"
[[ -x "$PY" ]] || PY="$(command -v python3 || command -v python)" || { echo "✗ missing: Python 3" >&2; exit 1; }
export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"
if [[ ! -d "$WS/1-export-confluence" ]]; then
  "$PY" -m amanuense init "$WS"
  echo "Workshop created: $WS — fill its folders (see LEEME.md) and run this again."
  exit 0
fi
exec "$PY" -m amanuense run "$WS" "$@"
