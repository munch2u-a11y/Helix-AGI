#!/usr/bin/env python3
"""Thin wrapper for the legacy tool_extrapolation benchmark command.

Preserves the historical `tests/tool_extrapolation_benchmark.py` entry point
while delegating to the cleaned-up simulator-backed implementation in `scripts/`.
"""

from pathlib import Path
import runpy


if __name__ == "__main__":
    target = Path(__file__).resolve().parents[1] / "scripts" / "tool_extrapolation_benchmark.py"
    runpy.run_path(str(target), run_name="__main__")
