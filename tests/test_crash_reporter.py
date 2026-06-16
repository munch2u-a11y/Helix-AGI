"""
Helix AGI — Test Suite for Crash Reporter

Verifies key masking, crash report creation, session marker lifecycle,
and unclean shutdown journal scanning.
"""

import os
import sys
import json
import shutil
import unittest
from pathlib import Path
from datetime import datetime
from unittest.mock import patch, MagicMock

# Ensure we can import from core
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.crash_reporter import (
    mask_sensitive_dict,
    get_system_stats,
    setup_crash_reporter,
    clear_session_marker,
    check_unclean_shutdown,
    generate_crash_report,
    _SESSION_MARKER_PATH,
    _CRASH_REPORTS_DIR,
)


class TestCrashReporter(unittest.TestCase):

    def setUp(self):
        # Backup original session marker if exists
        self.marker_backup = None
        if _SESSION_MARKER_PATH.exists():
            self.marker_backup = _SESSION_MARKER_PATH.read_text()
            _SESSION_MARKER_PATH.unlink()

        # Create fresh crash reports dir for testing
        self.test_reports_dir = Path(__file__).parent.parent / "logs" / "test_crash_reports"
        self.original_reports_dir = _CRASH_REPORTS_DIR
        # Patch the reports dir
        self.dir_patcher = patch("core.crash_reporter._CRASH_REPORTS_DIR", self.test_reports_dir)
        self.dir_patcher.start()

        if self.test_reports_dir.exists():
            shutil.rmtree(self.test_reports_dir)
        self.test_reports_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        # Clean up test reports
        if self.test_reports_dir.exists():
            shutil.rmtree(self.test_reports_dir)
        
        self.dir_patcher.stop()

        # Restore original marker
        if _SESSION_MARKER_PATH.exists():
            _SESSION_MARKER_PATH.unlink()
        if self.marker_backup:
            _SESSION_MARKER_PATH.write_text(self.marker_backup)

    def test_mask_sensitive_dict(self):
        config = {
            "llm_provider": "gemini",
            "gemini_api_key": "AIzaSyD-123456",
            "nested": {
                "anthropic_api_key": "sk-ant-12345",
                "normal_param": 100
            }
        }
        masked = mask_sensitive_dict(config)
        self.assertEqual(masked["llm_provider"], "gemini")
        self.assertEqual(masked["gemini_api_key"], "•••••••• [MASKED]")
        self.assertEqual(masked["nested"]["anthropic_api_key"], "•••••••• [MASKED]")
        self.assertEqual(masked["nested"]["normal_param"], 100)

    def test_get_system_stats(self):
        stats = get_system_stats()
        self.assertIn("os", stats)
        self.assertIn("python_version", stats)
        self.assertIn("cpu_count", stats)

    def test_session_marker_lifecycle(self):
        setup_crash_reporter()
        self.assertTrue(_SESSION_MARKER_PATH.exists())
        
        with open(_SESSION_MARKER_PATH, "r") as f:
            marker = json.load(f)
        self.assertEqual(marker["pid"], os.getpid())
        self.assertEqual(marker["status"], "running")

        clear_session_marker()
        self.assertFalse(_SESSION_MARKER_PATH.exists())

    def test_generate_crash_report(self):
        try:
            raise ValueError("Test error for crash reporter")
        except ValueError:
            exc_type, exc_value, exc_traceback = sys.exc_info()
            generate_crash_report(exc_type, exc_value, exc_traceback, is_thread=False)

        # Verify report files were created
        md_files = list(self.test_reports_dir.glob("*.md"))
        json_files = list(self.test_reports_dir.glob("*.json"))

        self.assertEqual(len(md_files), 1)
        self.assertEqual(len(json_files), 1)

        # Read JSON report to check contents
        with open(json_files[0], "r") as f:
            report = json.load(f)
        
        self.assertEqual(report["report_type"], "exception")
        self.assertEqual(report["exception"]["type"], "ValueError")
        self.assertEqual(report["exception"]["message"], "Test error for crash reporter")
        self.assertIn("Test error for crash reporter", report["exception"]["traceback"])

    @patch("subprocess.run")
    def test_check_unclean_shutdown(self, mock_run):
        # Setup mock journalctl output
        mock_output = MagicMock()
        mock_output.returncode = 0
        mock_output.stdout = "Jun 12 16:53:18 Home systemd[2234]: vte-spawn-c8ec61e8.scope: A process of this unit has been killed by the OOM killer.\n"
        mock_run.return_value = mock_output

        # Create a stale running marker for a dead PID
        marker = {
            "pid": 999999,  # Definitely non-existent PID
            "status": "running",
            "start_time": datetime.now().isoformat(),
        }
        with open(_SESSION_MARKER_PATH, "w") as f:
            json.dump(marker, f, indent=2)

        # Trigger unclean shutdown check
        report = check_unclean_shutdown()
        
        self.assertIsNotNone(report)
        self.assertEqual(report["report_type"], "unclean_shutdown")
        self.assertEqual(report["pid"], 999999)
        self.assertTrue(any("OOM killer" in line for line in report["clues"]))

        # Check report files written
        md_files = list(self.test_reports_dir.glob("unclean_shutdown_*.md"))
        self.assertEqual(len(md_files), 1)
        
        # Stale marker should be cleared
        self.assertFalse(_SESSION_MARKER_PATH.exists())


if __name__ == "__main__":
    unittest.main()
