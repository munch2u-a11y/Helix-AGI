#!/bin/bash
# Helix-AGI Interactive Benchmark Suite Launcher — Double-click to run
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

if [ -f "venv/bin/python3" ]; then
    exec venv/bin/python3 tests/run_all_benchmarks.py "$@"
elif [ -f ".venv/bin/python3" ]; then
    exec .venv/bin/python3 tests/run_all_benchmarks.py "$@"
else
    exec python3 tests/run_all_benchmarks.py "$@"
fi
