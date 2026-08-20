"""Tests for the read-only local installation health check."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from scripts.run_health_check import Check, collect_checks, exit_code


class HealthCheckTests(unittest.TestCase):
    def test_exit_code_only_fails_on_required_failure(self):
        self.assertEqual(exit_code([Check("optional", "WARN", "missing")]), 0)
        self.assertEqual(exit_code([Check("required", "FAIL", "missing")]), 1)

    def test_apache_license_and_ui_files_are_detected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative in (
                "dashboard/dashboard.py",
                "dashboard/dashboard_ui.html",
                "desktop_widget/web/index.html",
                "desktop_widget/web/mascot.js",
            ):
                path = root / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("present", encoding="utf-8")
            (root / "LICENSE").write_text("Apache License\nVersion 2.0", encoding="utf-8")

            checks = {check.component: check for check in collect_checks(root)}
            self.assertEqual(checks["Repository license"].status, "PASS")
            self.assertEqual(checks["User interfaces"].status, "PASS")


if __name__ == "__main__":
    unittest.main()
