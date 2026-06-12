#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────
#   Helix‑AGI — Setup Wizard Launcher
#
#   Checks for Python dependencies and launches the setup wizard.
#   Run this from the repository root:
#     chmod +x install.sh && ./install.sh
# ──────────────────────────────────────────────────────────────

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║       HELIX‑AGI SETUP WIZARD             ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# ── Check Python ──────────────────────────────────────────────
PYTHON=""
for candidate in python3 python; do
    if command -v "$candidate" &>/dev/null; then
        version=$("$candidate" --version 2>&1 | grep -oP '\d+\.\d+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "❌ Python 3.10+ is required but not found."
    echo "   Install Python from https://python.org/downloads"
    exit 1
fi

echo "✓ Using $PYTHON ($($PYTHON --version))"

# ── Check virtual environment ─────────────────────────────────
if [ -d "venv" ]; then
    echo "✓ Virtual environment found"
    source venv/bin/activate 2>/dev/null || true
elif [ -d ".venv" ]; then
    echo "✓ Virtual environment found (.venv)"
    source .venv/bin/activate 2>/dev/null || true
else
    echo "Creating virtual environment..."
    $PYTHON -m venv venv
    source venv/bin/activate
    echo "✓ Virtual environment created"
fi

# ── Install dependencies ──────────────────────────────────────
echo ""
echo "Checking dependencies..."
pip install --quiet --upgrade pip

# Install PyQt6 first (needed for the wizard GUI)
pip install --quiet PyQt6 PyQt6-WebEngine 2>/dev/null || {
    echo "⚠ PyQt6 installation failed. You may need to install system Qt libraries:"
    echo "   sudo apt install python3-pyqt6 python3-pyqt6.qtwebengine"
}

# Install remaining requirements
if [ -f "requirements.txt" ]; then
    pip install --quiet -r requirements.txt 2>/dev/null || {
        echo "⚠ Some dependencies failed to install."
        echo "   The wizard may still work — advanced features may be limited."
    }
fi

echo "✓ Dependencies ready"
echo ""

# ── Launch Wizard ─────────────────────────────────────────────
echo "Launching Helix‑AGI Setup Wizard..."
echo ""
$PYTHON -m wizard "$@"
