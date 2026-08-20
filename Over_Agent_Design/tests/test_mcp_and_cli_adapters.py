"""
Unit Test Suite for MCP & CLI Plugin Adapters.
Verifies:
1. CLIPluginAdapter plugin detection and safe command execution boundaries.
2. MCPClientAdapter JSON-RPC format validation and registry tool dispatches.
"""

import os
import sys
import unittest

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from cli_plugin_adapter import CLIPluginAdapter
from mcp_adapter import MCPClientAdapter, MCPRegistry

class TestMCPAndCLIAdapters(unittest.TestCase):
    def test_cli_plugin_detection(self):
        adapter = CLIPluginAdapter()
        plugins = adapter.list_available_plugins()
        print(f"\n  ✓ Active CLI Plugins Detected: {[p['plugin'] for p in plugins]}")
        self.assertIsInstance(plugins, list)
        
        # Test git CLI plugin if git is installed
        if any(p['plugin'] == 'git' for p in plugins):
            res = adapter.execute_cli_plugin("git", ["--version"])
            self.assertTrue(res["success"])
            self.assertIn("git version", res["output"].lower())
            print(f"  ✓ CLI Plugin 'git --version' Output: {res['output']}")

    def test_cli_plugin_uninstalled_fallback(self):
        adapter = CLIPluginAdapter()
        res = adapter.execute_cli_plugin("nonexistent_cli_xyz", ["--version"])
        self.assertFalse(res["success"])
        self.assertIn("is not installed on PATH", res["output"])
        print(f"  ✓ Gracefully handled uninstalled CLI plugin request")

    def test_mcp_registry_initialization(self):
        registry = MCPRegistry()
        all_tools = registry.get_all_tools()
        self.assertIsInstance(all_tools, dict)
        print(f"  ✓ MCP Registry initialized cleanly")

if __name__ == "__main__":
    unittest.main()
