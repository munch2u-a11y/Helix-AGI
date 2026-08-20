#!/bin/bash
# Helix system diagnostic — double-click to run
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -x "venv/bin/python3" ]; then
    exec venv/bin/python3 scripts/run_health_check.py "$@"
elif [ -x ".venv/bin/python3" ]; then
    exec .venv/bin/python3 scripts/run_health_check.py "$@"
else
    echo "Helix requires its virtual environment. Run ./install.sh first." >&2
    exit 1
fi
