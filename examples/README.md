# Helix AGI Developer Examples

This directory contains standalone, runnable code examples demonstrating how to embed, extend, and interact with the **Helix AGI** cognitive architecture.

## Available Examples

| Example Script | Description |
|---|---|
| [`01_basic_pulse_loop.py`](01_basic_pulse_loop.py) | Demonstrates setting up `PulseLoop`, event queueing (`emit`), and observing pulse state transitions. |
| [`02_custom_tool_registration.py`](02_custom_tool_registration.py) | Shows how to declare custom Python tool handlers with `ToolRegistry` and execute them via `ToolExecutor`. |
| [`03_action_path_planning.py`](03_action_path_planning.py) | Demonstrates multi-step task planning with `ActionPlanner`, 4-leg plan limits, clarification handling (`NEED_INPUT:`), and verification receipts. |
| [`04_typed_memory_retrieval.py`](04_typed_memory_retrieval.py) | Demonstrates querying `UnifiedRetrieval` and inspecting typed evidence assertions decorated by `RecordEnvelope`. |

## Running Examples

Execute any example script using the project virtual environment:

```bash
venv/bin/python examples/01_basic_pulse_loop.py
venv/bin/python examples/02_custom_tool_registration.py
venv/bin/python examples/03_action_path_planning.py
venv/bin/python examples/04_typed_memory_retrieval.py
```
