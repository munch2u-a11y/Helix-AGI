#!/usr/bin/env python3
"""Fast, read-only Helix installation and UI health diagnostic."""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Check:
    component: str
    status: str
    detail: str


def _module_available(module_name: str) -> bool:
    try:
        return importlib.util.find_spec(module_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


def _nearest_existing_parent(path: Path) -> Path:
    candidate = path
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    return candidate


def collect_checks(repo_root: Path = REPO_ROOT) -> List[Check]:
    """Collect diagnostics without booting Helix or modifying its state."""
    checks: List[Check] = []
    in_venv = sys.prefix != sys.base_prefix or "venv" in sys.executable
    checks.append(Check(
        "Virtual environment",
        "PASS" if in_venv else "WARN",
        sys.executable if in_venv else "Use venv/bin/python for the complete dependency set",
    ))

    required = ("numpy", "flask")
    missing_required = [name for name in required if not _module_available(name)]
    checks.append(Check(
        "Core UI dependencies",
        "FAIL" if missing_required else "PASS",
        f"Missing: {', '.join(missing_required)}" if missing_required else "numpy and Flask available",
    ))

    widget_modules = ("PyQt6", "PyQt6.QtWebEngineWidgets")
    missing_widget = [name for name in widget_modules if not _module_available(name)]
    checks.append(Check(
        "Desktop widget dependencies",
        "WARN" if missing_widget else "PASS",
        f"Optional widget packages missing: {', '.join(missing_widget)}" if missing_widget else "PyQt6 and Qt WebEngine available",
    ))

    config_path = repo_root / "config" / "config.json"
    checks.append(Check(
        "Local configuration",
        "PASS" if config_path.exists() else "WARN",
        str(config_path) if config_path.exists() else "Run the setup wizard before starting Helix",
    ))

    data_path = repo_root / "data"
    writable_parent = _nearest_existing_parent(data_path)
    checks.append(Check(
        "Data directory",
        "PASS" if os.access(writable_parent, os.W_OK) else "FAIL",
        f"Writable via {writable_parent}" if os.access(writable_parent, os.W_OK) else f"Not writable: {writable_parent}",
    ))

    ui_files = (
        repo_root / "dashboard" / "dashboard.py",
        repo_root / "dashboard" / "dashboard_ui.html",
        repo_root / "desktop_widget" / "web" / "index.html",
        repo_root / "desktop_widget" / "web" / "mascot.js",
    )
    missing_ui = [str(path.relative_to(repo_root)) for path in ui_files if not path.is_file()]
    checks.append(Check(
        "User interfaces",
        "FAIL" if missing_ui else "PASS",
        f"Missing: {', '.join(missing_ui)}" if missing_ui else "Dashboard, canvas, and desktop widget assets present",
    ))

    license_path = repo_root / "LICENSE"
    apache = license_path.exists() and "Apache License" in license_path.read_text(encoding="utf-8", errors="replace")[:200]
    checks.append(Check(
        "Repository license",
        "PASS" if apache else "FAIL",
        "Apache License 2.0" if apache else "LICENSE is missing or is not Apache 2.0",
    ))
    return checks


def exit_code(checks: Iterable[Check]) -> int:
    return 1 if any(check.status == "FAIL" for check in checks) else 0


def print_table(checks: Iterable[Check]) -> None:
    rows = list(checks)
    print("\nHELIX AGI HEALTH CHECK")
    print("=" * 88)
    print(f"{'Component':<30} {'Status':<8} Details")
    print("-" * 88)
    for check in rows:
        print(f"{check.component:<30} {check.status:<8} {check.detail}")
    print("=" * 88)
    print("Ready" if exit_code(rows) == 0 else "One or more required checks failed")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args(argv)
    checks = collect_checks()
    if args.json:
        print(json.dumps({"checks": [asdict(check) for check in checks], "ok": exit_code(checks) == 0}, indent=2))
    else:
        print_table(checks)
    return exit_code(checks)


if __name__ == "__main__":
    raise SystemExit(main())
