#!/bin/bash
# Helix‑AGI Setup Wizard — Double-click to launch
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

# Use venv if it exists
if [ -f "venv/bin/python3" ]; then
    exec venv/bin/python3 -m wizard "$@"
elif [ -f ".venv/bin/python3" ]; then
    exec .venv/bin/python3 -m wizard "$@"
else
    exec python3 -m wizard "$@"
fi
