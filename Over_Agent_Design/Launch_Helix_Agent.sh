#!/bin/bash
# =====================================================================
# Helix Subconscious Over-Agent Terminal Launcher
# Double-click or run from terminal: ./Launch_Helix_Agent.sh
# =====================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PYTHON="$DIR/../venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

echo -e "\033[1;36mStarting Helix Subconscious Over-Agent Terminal...\033[0m"

# Execute main terminal application with debug mode enabled by default
"$PYTHON" main.py --debug "$@"
