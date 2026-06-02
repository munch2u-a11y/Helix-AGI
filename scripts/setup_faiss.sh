#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# Helix — FAISS Installation Script
#
# Installs faiss-cpu for scalable semantic search (384D index).
# The SemanticIndex will auto-upgrade from numpy brute-force to
# FAISS IVF when the vector count exceeds the configured threshold
# (default: 2000).
#
# Usage:
#   bash scripts/setup_faiss.sh
#
# Or from the Helix virtual environment:
#   pip install faiss-cpu
# ──────────────────────────────────────────────────────────────────────

set -e

echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  Helix — Installing FAISS (CPU) for scalable vector search  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""

# Detect the correct pip
if [ -n "$VIRTUAL_ENV" ]; then
    PIP="$VIRTUAL_ENV/bin/pip"
elif [ -f ".venv/bin/pip" ]; then
    PIP=".venv/bin/pip"
else
    PIP="pip3"
fi

echo "Using pip: $PIP"
echo ""

$PIP install faiss-cpu

echo ""
echo "✓ FAISS installed successfully."
echo "  The SemanticIndex will now auto-upgrade to IVF indexing"
echo "  when the vector count exceeds the configured threshold."
echo ""
