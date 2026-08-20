#!/bin/bash
# Executable launcher script for Setup Wizard
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PYTHON="$DIR/../venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi
"$PYTHON" setup_wizard.py
