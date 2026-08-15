#!/bin/bash
# Helix-AGI System Diagnostic & Health Check Launcher — Double-click to run
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -f "venv/bin/python3" ]; then
    exec venv/bin/python3 scripts/run_health_check.py "$@"
elif [ -f ".venv/bin/python3" ]; then
    exec .venv/bin/python3 scripts/run_health_check.py "$@"
else
    exec python3 scripts/run_health_check.py "$@"
fi
