#!/bin/bash
# Helix desktop widget — double-click to launch
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -x "venv/bin/python3" ]; then
    exec venv/bin/python3 -m desktop_widget.launcher "$@"
elif [ -x ".venv/bin/python3" ]; then
    exec .venv/bin/python3 -m desktop_widget.launcher "$@"
else
    echo "Helix requires its virtual environment. Run ./install.sh first." >&2
    exit 1
fi
