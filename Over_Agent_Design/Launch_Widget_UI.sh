#!/bin/bash
# Executable launcher script for True Native Desktop Floating Overlay
cd "$(dirname "$0")"

echo "====================================================================="
echo " 🚀 LAUNCHING HELIX SUBCONSCIOUS OVER-AGENT DESKTOP FLOATING OVERLAY"
echo "====================================================================="

# Check if web server is already running
if ! curl -s http://localhost:8080 > /dev/null; then
    echo "Starting background HTTP server..."
    python3 web_server.py &
    sleep 1
fi

echo "Launching Native OS Always-On-Top Floating Window Overlay..."
/home/nemo/Helix/.venv/bin/python desktop_overlay.py
