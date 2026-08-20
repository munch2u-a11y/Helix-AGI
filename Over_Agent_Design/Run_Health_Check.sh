#!/bin/bash
# =====================================================================
# Helix Health Check & System Diagnostics
# =====================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "====================================================================="
echo "          Helix Subconscious Over-Agent — Health Check               "
echo "====================================================================="

echo -n "1. Checking Python 3 Installation ... "
if command -v python3 &> /dev/null; then
    echo -e "\033[1;32mOK\033[0m ($(python3 --version))"
else
    echo -e "\033[1;31mFAILED\033[0m"
fi

echo -n "2. Checking Ollama Local LLM Server ... "
if curl -s http://localhost:11434/api/tags &> /dev/null; then
    echo -e "\033[1;32mONLINE (http://localhost:11434)\033[0m"
else
    echo -e "\033[1;31mOFFLINE\033[0m (Run 'ollama serve' to start)"
fi

echo -n "3. Checking Shared Identity File (identity.md) ... "
if [ -f "identity.md" ]; then
    echo -e "\033[1;32mFOUND\033[0m"
else
    echo -e "\033[1;31mMISSING\033[0m"
fi

echo -n "4. Checking Workspace Directory ... "
if [ -d "$DIR" ]; then
    echo -e "\033[1;32mVALID ($DIR)\033[0m"
else
    echo -e "\033[1;31mNOT FOUND\033[0m"
fi

echo "====================================================================="
echo "Health check diagnostic complete."
echo "====================================================================="
