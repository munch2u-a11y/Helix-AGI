#!/bin/bash
# Helix‑AGI Agent Launcher — Double-click to run
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Use venv if it exists
if [ -f "venv/bin/python3" ]; then
    exec venv/bin/python3 main.py "$@"
elif [ -f ".venv/bin/python3" ]; then
    exec .venv/bin/python3 main.py "$@"
else
    exec python3 main.py "$@"
fi
