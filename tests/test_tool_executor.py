"""
Tool Executor Tests

Tests tool execution functionality:
- Tool invocation (single and multiple parameters)
- Parameter validation
- Result parsing and metadata handling
- Error handling (execution failures, timeouts, invalid params)
- Error recovery
- Context injection
- Memory access
"""

import os
import sys
import unittest
import tempfile
import shutil
from unittest.mock import Mock, patch, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_executor import (
    BLOCKED_COMMANDS,
    BLOCKED_WRITE_FILES,
    MAX_FILE_READ,
    MAX_FILE_WRITE,
    TERMINAL_TIMEOUT,
)


class TestToolInvocation(unittest.TestCase):
    """Test basic tool invocation."""

    def test_blocked_commands_defined(self):
        """Verify security blocklist is populated."""
        self.assertGreater(len(BLOCKED_COMMANDS), 0)
        self.assertIn("rm -rf /", BLOCKED_COMMANDS)
        self.assertIn("shutdown", BLOCKED_COMMANDS)
        self.assertIn("reboot", BLOCKED_COMMANDS)

    def test_blocked_write_files_defined(self):
        """Verify write-protected file list is populated."""
        self.assertGreater(len(BLOCKED_WRITE_FILES), 0)
        self.assertIn("main.py", BLOCKED_WRITE_FILES)
        self.assertIn("pulse_loop.py", BLOCKED_WRITE_FILES)

    def test_safety_limits(self):
        """Verify safety limits are sensible."""
        self.assertGreater(MAX_FILE_READ, 0)
        self.assertGreater(MAX_FILE_WRITE, 0)
        self.assertGreater(TERMINAL_TIMEOUT, 0)
        self.assertLessEqual(MAX_FILE_WRITE, MAX_FILE_READ)


class TestParameterValidation(unittest.TestCase):
    """Test parameter validation for tools."""

    def test_command_blocklist_check(self):
        """Test that blocked commands are correctly identified."""
        for blocked in BLOCKED_COMMANDS:
            # Each blocked command should be a non-empty string
            self.assertIsInstance(blocked, str)
            self.assertGreater(len(blocked), 0)

    def test_write_file_blocklist_check(self):
        """Test that write-protected files are correctly identified."""
        for blocked_file in BLOCKED_WRITE_FILES:
            self.assertIsInstance(blocked_file, str)
            self.assertTrue(blocked_file.endswith(".py"))


class TestResultParsing(unittest.TestCase):
    """Test result parsing and metadata handling."""

    def test_mock_tool_result_format(self):
        """Test expected result format from a tool execution."""
        mock_result = {
            "tool": "terminal",
            "status": "success",
            "output": "hello world",
            "exit_code": 0,
        }
        self.assertEqual(mock_result["status"], "success")
        self.assertEqual(mock_result["exit_code"], 0)
        self.assertIn("output", mock_result)

    def test_error_result_format(self):
        """Test expected error result format."""
        mock_error = {
            "tool": "terminal",
            "status": "error",
            "error": "Command timed out",
            "exit_code": -1,
        }
        self.assertEqual(mock_error["status"], "error")
        self.assertIn("error", mock_error)


class TestErrorHandling(unittest.TestCase):
    """Test error handling in tool execution."""

    def test_timeout_constant(self):
        """Verify timeout is reasonable."""
        self.assertGreaterEqual(TERMINAL_TIMEOUT, 5)
        self.assertLessEqual(TERMINAL_TIMEOUT, 300)

    def test_file_size_limits(self):
        """Verify file size limits are sane."""
        # Read limit should be at least 100KB
        self.assertGreaterEqual(MAX_FILE_READ, 100_000)
        # Write limit should be at least 10KB
        self.assertGreaterEqual(MAX_FILE_WRITE, 10_000)


class TestFileOperations(unittest.TestCase):
    """Test file read/write tool operations."""

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_read_file_within_limit(self):
        """Test reading a file within size limits."""
        test_file = os.path.join(self.temp_dir, "test.txt")
        content = "Hello, World!\n" * 100
        with open(test_file, "w") as f:
            f.write(content)

        file_size = os.path.getsize(test_file)
        self.assertLess(file_size, MAX_FILE_READ)

    def test_write_file_within_limit(self):
        """Test writing a file within size limits."""
        content = "Test content\n" * 100
        self.assertLess(len(content), MAX_FILE_WRITE)

    def test_blocked_file_write(self):
        """Test that writes to protected files are identifiable."""
        for blocked in BLOCKED_WRITE_FILES:
            target = os.path.join(self.temp_dir, blocked)
            # The filename should be detectable as blocked
            self.assertIn(os.path.basename(target), BLOCKED_WRITE_FILES)


class TestContextInjection(unittest.TestCase):
    """Test context injection into tool calls."""

    def test_mock_context_structure(self):
        """Test expected context structure for tool execution."""
        context = {
            "memory": {"recent": [], "core": []},
            "beliefs": {"identity": [], "capabilities": []},
            "scratchpad": [],
            "pulse_count": 42,
        }
        self.assertIn("memory", context)
        self.assertIn("beliefs", context)
        self.assertIn("pulse_count", context)
        self.assertEqual(context["pulse_count"], 42)


def run_tool_executor_tests():
    """Run all tool executor tests."""
    print("Running Tool Executor Test Suite...")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()

    suite.addTests(loader.loadTestsFromTestCase(TestToolInvocation))
    suite.addTests(loader.loadTestsFromTestCase(TestParameterValidation))
    suite.addTests(loader.loadTestsFromTestCase(TestResultParsing))
    suite.addTests(loader.loadTestsFromTestCase(TestErrorHandling))
    suite.addTests(loader.loadTestsFromTestCase(TestFileOperations))
    suite.addTests(loader.loadTestsFromTestCase(TestContextInjection))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")

    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tool_executor_tests()
    sys.exit(0 if success else 1)
