#!/usr/bin/env bash
# Competition Command Tower — interactive web dashboard. Offline, no credentials.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"
PORT="${1:-8120}"
echo "Dashboard on http://127.0.0.1:${PORT}  (synthetic portfolio, offline, no secrets)"
exec python3 -m uvicorn webapp.server:app --host 127.0.0.1 --port "$PORT"
