"""
Unit tests for the Dynamic Tool System (Tool Factory)
"""

import os
import sys
import json
import shutil
import unittest
from unittest.mock import MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.tool_executor import ToolExecutor
from tools.tool_registry import registry


class TestToolFactory(unittest.TestCase):
    """Test dynamic tool creation, registration, execution, and deletion."""

    def setUp(self):
        # Setup clean test environment
        self.custom_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools",
            "custom"
        )
        os.makedirs(self.custom_dir, exist_ok=True)
        
        # Mock PulseLoop
        self.mock_pulse_loop = MagicMock()
        self.mock_pulse_loop._active_toolsets = {"core"}
        self.mock_pulse_loop._pending_toolset_rebuild = False
        
        # Instantiate ToolExecutor
        self.executor = ToolExecutor()
        self.executor.set_pulse_loop(self.mock_pulse_loop)

    def tearDown(self):
        # Clean up any test_tool* files created during tests
        for filename in os.listdir(self.custom_dir):
            if filename.startswith("test_tool_") and filename.endswith(".py"):
                try:
                    os.remove(os.path.join(self.custom_dir, filename))
                except OSError:
                    pass
        # Clean registry of test tools
        registry.deregister("test_tool_addition")

    def test_create_custom_tool_template(self):
        """Test skeleton generation for a custom tool."""
        tool_name = "test_tool_addition"
        toolset = "math_group"
        description = "Add two numbers"
        parameters = {
            "type": "object",
            "properties": {
                "a": {"type": "integer", "description": "First number"},
                "b": {"type": "integer", "description": "Second number"}
            },
            "required": ["a", "b"]
        }
        
        # Call tool creator template
        res_str = self.executor.execute_function_call("create_custom_tool_template", {
            "name": tool_name,
            "toolset": toolset,
            "description": description,
            "parameters": parameters,
            "requires_env": ["SOME_API_KEY"]
        })
        res = json.loads(res_str)
        
        self.assertIn("status", res)
        self.assertEqual(res["status"], "success")
        
        # Check that file exists
        filepath = os.path.join(self.custom_dir, f"{tool_name}.py")
        self.assertTrue(os.path.exists(filepath))
        
        with open(filepath, "r") as f:
            content = f.read()
            
        self.assertIn(f'toolset = "{toolset}"', content)
        self.assertIn('"name": "test_tool_addition"', content)
        self.assertIn('"SOME_API_KEY"', content)
        self.assertIn("def handler(args: dict) -> str:", content)

    def test_register_and_execute_custom_tool(self):
        """Test compiling, registering, and dispatching a custom tool."""
        tool_name = "test_tool_addition"
        filepath = os.path.join(self.custom_dir, f"{tool_name}.py")
        
        # Write a fully implemented tool file manually
        content = """
schema = {
    "name": "test_tool_addition",
    "description": "Adds two numbers",
    "parameters": {
        "type": "object",
        "properties": {
            "a": {"type": "integer"},
            "b": {"type": "integer"}
        },
        "required": ["a", "b"]
    }
}
toolset = "math_group"

def handler(args: dict) -> str:
    import json
    a = int(args.get("a", 0))
    b = int(args.get("b", 0))
    return json.dumps({"result": a + b})
"""
        with open(filepath, "w") as f:
            f.write(content)
            
        # Register the custom tool
        reg_res_str = self.executor.execute_function_call("register_custom_tool", {"name": tool_name})
        reg_res = json.loads(reg_res_str)
        
        self.assertEqual(reg_res["status"], "success")
        self.assertEqual(self.mock_pulse_loop._pending_toolset_rebuild, True)
        self.assertIn("math_group", self.mock_pulse_loop._active_toolsets)
        
        # Now execute the custom tool using ToolExecutor dispatch!
        exec_res_str = self.executor.execute_function_call("test_tool_addition", {"a": 40, "b": 2})
        exec_res = json.loads(exec_res_str)
        
        self.assertEqual(exec_res["result"], 42)

    def test_list_custom_tools(self):
        """Test listing custom tools."""
        tool_name = "test_tool_addition"
        filepath = os.path.join(self.custom_dir, f"{tool_name}.py")
        
        # Write a temporary tool file
        with open(filepath, "w") as f:
            f.write("schema = {'name': 'test_tool_addition'}\ndef handler(args): pass\n")
            
        # Prior to registration
        list_res_str = self.executor.execute_function_call("list_custom_tools", {})
        list_res = json.loads(list_res_str)
        self.assertIn("custom_tools", list_res)
        
        tool_info = next((t for t in list_res["custom_tools"] if t["name"] == tool_name), None)
        self.assertIsNotNone(tool_info)
        self.assertEqual(tool_info["registered"], False)
        
        # Register it
        self.executor.execute_function_call("register_custom_tool", {"name": tool_name})
        
        # Check listing again
        list_res_str = self.executor.execute_function_call("list_custom_tools", {})
        list_res = json.loads(list_res_str)
        tool_info = next((t for t in list_res["custom_tools"] if t["name"] == tool_name), None)
        self.assertIsNotNone(tool_info)
        self.assertEqual(tool_info["registered"], True)

    def test_delete_custom_tool(self):
        """Test dynamic deregistration and deletion of a custom tool."""
        tool_name = "test_tool_addition"
        filepath = os.path.join(self.custom_dir, f"{tool_name}.py")
        
        # Create and register first
        with open(filepath, "w") as f:
            f.write("schema = {'name': 'test_tool_addition'}\ndef handler(args): pass\n")
        self.executor.execute_function_call("register_custom_tool", {"name": tool_name})
        
        # Delete it
        del_res_str = self.executor.execute_function_call("delete_custom_tool", {"name": tool_name})
        del_res = json.loads(del_res_str)
        
        self.assertEqual(del_res["status"], "success")
        self.assertFalse(os.path.exists(filepath))
        
        # Confirm it's no longer registered
        self.assertIsNone(registry.get_entry(tool_name))


if __name__ == "__main__":
    unittest.main()
