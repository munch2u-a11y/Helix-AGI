"""Portable development launcher for the bundled MCP server."""

from __future__ import annotations

import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "src"))

try:
    from helix_agent_lab.server import main
except ModuleNotFoundError as exc:
    if exc.name == "mcp":
        raise SystemExit(
            "Helix Agent Lab requires the MCP Python SDK. "
            "Run: python -m pip install -e \"<plugin-path>\""
        ) from exc
    raise


if __name__ == "__main__":
    main()
