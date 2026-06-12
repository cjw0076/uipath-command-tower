#!/usr/bin/env bash
# Competition Command Tower — one-command offline Maestro Case demo.
# Stdlib Python only. No network, no secrets, no UiPath credentials required.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"
export PYTHONPATH="$HERE/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -m command_tower --json out/portfolio_snapshot.json

echo
echo "Stop at the human gates (manual mode) with:"
echo "  PYTHONPATH=$HERE/src python3 -m command_tower --manual"
echo
echo "Benchmark the engine across the whole portfolio with:"
echo "  PYTHONPATH=$HERE/src python3 eval/run_eval.py"
echo
echo "Launch the interactive web dashboard with:"
echo "  pip install -r webapp/requirements.txt && ./run_dashboard.sh"
