#!/usr/bin/env python3
"""Example 02: Custom Tool Declaration and Execution

This example demonstrates how to declare custom Python tools, register them in
Helix's ToolRegistry, and invoke them safely.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from tools.tool_registry import ToolRegistry


def custom_calculator_handler(args: dict) -> str:
    """Safe evaluation helper for mathematical expressions."""
    expression = args.get("expression", "")
    allowed = set("0123456789+-*/() .")
    if not set(expression).issubset(allowed):
        return "Error: Expression contains disallowed characters."
    try:
        result = eval(expression, {"__builtins__": {}}, {})
        return f"Result: {result}"
    except Exception as exc:
        return f"Execution error: {exc}"


def main():
    print("=== Helix AGI Example 02: Custom Tool Registration ===")

    registry = ToolRegistry()

    # Register custom tool declaration
    schema = {
        "name": "custom_calculator",
        "description": "Evaluates a basic mathematical expression safely.",
        "parameters": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Mathematical expression (e.g., '12 + 34 * 2')"
                }
            },
            "required": ["expression"]
        }
    }

    registry.register(
        name="custom_calculator",
        toolset="core",
        schema=schema,
        handler=custom_calculator_handler
    )

    print(f"[+] Custom tool 'custom_calculator' registered in ToolRegistry.")

    # Dispatch tool execution
    result = registry.dispatch("custom_calculator", {"expression": "25 * 4 + 15"})

    print(f"[+] Invocation Output: {result}")
    assert "Result: 115" in str(result)
    print("\n✓ Custom tool executed successfully!")


if __name__ == "__main__":
    main()
