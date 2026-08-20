#!/bin/bash
# Executable launcher script for True Native Desktop Floating Overlay
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PYTHON="$DIR/../venv/bin/python"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

echo "====================================================================="
echo " 🚀 LAUNCHING HELIX SUBCONSCIOUS OVER-AGENT DESKTOP FLOATING OVERLAY"
echo "====================================================================="

# Check if web server is already running
if ! curl -s http://localhost:8080 > /dev/null; then
    echo "Starting background HTTP server..."
    "$PYTHON" web_server.py &
    sleep 1
fi

echo "Launching Native OS Always-On-Top Floating Window Overlay..."
"$PYTHON" desktop_overlay.py
