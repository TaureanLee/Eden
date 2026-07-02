#!/usr/bin/env bash
# Eden — one-step launcher for macOS and Linux.
# Sets up a local Python environment the first time, then starts Eden and
# opens your browser. Re-running is fast; setup only happens once.
#
#   ./run.sh                 # start Eden, pick your headset in the browser
#   ./run.sh --synthetic     # no hardware: explore with a simulated brain
#   ./run.sh --port 5001     # any server.py flag is passed straight through
set -euo pipefail

cd "$(dirname "$0")"

VENV_PY=".venv/bin/python"
SENTINEL=".venv/.eden-deps-installed"

find_python() {
  for c in python3 python; do
    if command -v "$c" >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  return 1
}

if [ ! -x "$VENV_PY" ]; then
  echo "Setting up Eden for the first time..."
  PY="$(find_python)" || { echo "Python 3.10+ not found. Install it from https://www.python.org/downloads/ and re-run."; exit 1; }
  "$PY" -m venv .venv
fi

if [ ! -f "$SENTINEL" ]; then
  echo "Installing dependencies (one time)..."
  "$VENV_PY" -m pip install --upgrade pip
  "$VENV_PY" -m pip install -r requirements.txt
  touch "$SENTINEL"
fi

echo "Starting Eden... your browser will open at http://127.0.0.1:5000"
exec "$VENV_PY" server.py "$@"
