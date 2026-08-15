#!/usr/bin/env python3
"""Run the modular action path against a real local model and virtual tools.

No email, file, browser, or shell side effect leaves this process. The local
model plans and drives the normal orchestrator/worker loop against an in-memory
world so its schema use, clarification behavior, verification, and token use
can be measured independently of service credentials.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from llm.orchestrated import build_orchestrator
from llm.providers.base import ProviderConfig
from tools.tool_registry import ToolRegistry


def _schema(name, description, properties=None, required=None):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties or {},
            "required": required or [],
        },
    }


class VirtualComputer:
    def __init__(self):
        self._registry = ToolRegistry()
        self.files = {
            "/virtual/report.txt": "Quarterly report\nFinal total: 42",
            "/virtual/config.py": "RETRIES = 2\n",
        }
        self.calls = []
        self._register()

    def _add(self, name, toolset, description, properties, required):
        self._registry.register(
            name=name,
            toolset=toolset,
            schema=_schema(name, description, properties, required),
            handler=lambda args, tool=name: self.execute_function_call(tool, args),
        )

    def _register(self):
        self._add(
            "read_file", "files", "Read a virtual local file by exact path.",
            {"path": {"type": "string"}}, ["path"],
        )
        self._add(
            "write_file", "files",
            "Write the complete content of a virtual file. Read it afterward to verify.",
            {"path": {"type": "string"}, "content": {"type": "string"}},
            ["path", "content"],
        )
        self._add(
            "email_send", "email", "Send a virtual email and return a delivery ID.",
            {"to": {"type": "string"}, "subject": {"type": "string"}, "body": {"type": "string"}},
            ["to", "subject", "body"],
        )
        self._registry.register_toolset_description(
            "files", "Read and update virtual local files"
        )
        self._registry.register_toolset_description(
            "email", "Send virtual email with delivery receipts"
        )

    def execute_function_call(self, name, args):
        self.calls.append((name, dict(args)))
        if name == "read_file":
            path = str(args.get("path") or "")
            if path not in self.files:
                return f"Error: file not found: {path}"
            return self.files[path]
        if name == "write_file":
            path = str(args.get("path") or "")
            content = str(args.get("content") or "")
            if not path or not content:
                return "Error: path and content are required."
            self.files[path] = content
            return f"File written successfully: {path}"
        if name == "email_send":
            recipient = str(args.get("to") or "")
            if "@" not in recipient:
                return "Could not deliver: recipient must be a complete email address."
            return f"Email sent to {recipient}. Message ID: virtual-msg-1"
        return f"Unknown tool: {name}"


CASES = [
    {
        "name": "clarify_ambiguous_recipient",
        "request": "Email Alex the quarterly report.",
        "check": lambda outcome, world: bool(outcome.question and not world.calls),
    },
    {
        "name": "read_exact_value",
        "request": "Read /virtual/report.txt and report the final total.",
        "check": lambda outcome, world: (
            outcome.complete
            and any(name == "read_file" for name, _args in world.calls)
            and "42" in outcome.reply
        ),
    },
    {
        "name": "write_with_readback",
        "request": "Update /virtual/config.py so its complete content is RETRIES = 4, then verify it.",
        "check": lambda outcome, world: (
            outcome.complete
            and [name for name, _args in world.calls].count("write_file") >= 1
            and [name for name, _args in world.calls].count("read_file") >= 1
            and "RETRIES = 4" in world.files["/virtual/config.py"]
        ),
    },
]


def run_smoke(model: str, selected=None):
    wanted = set(selected or [item["name"] for item in CASES])
    rows = []
    with tempfile.TemporaryDirectory(prefix="helix-local-action-") as temp_dir:
        for case in CASES:
            if case["name"] not in wanted:
                continue
            world = VirtualComputer()
            config = ProviderConfig(
                provider_type="ollama",
                model=model,
                context_window=8192,
                temperature=0.1,
                max_output_tokens=384,
                options={"num_ctx": 8192, "keep_alive": "10m"},
            )
            orchestrator = build_orchestrator(
                config,
                world,
                context_provider=lambda _request: (
                    "Known contacts: Mara is mara@example.test. "
                    "No unique email address is known for Alex."
                ),
                max_steps=6,
                data_dir=temp_dir,
            )
            started = time.monotonic()
            outcome = orchestrator.handle(case["request"])
            elapsed = time.monotonic() - started
            passed = bool(case["check"](outcome, world))
            rows.append({
                "name": case["name"],
                "passed": passed,
                "state": "waiting_input" if outcome.question else (
                    "verified" if outcome.complete else outcome.verification.get("status", "failed")
                ),
                "question": outcome.question,
                "reply": outcome.reply,
                "calls": [name for name, _args in world.calls],
                "planner_prompt_tokens": outcome.planning_prompt_tokens,
                "steering_model_tokens": outcome.steering_model_tokens,
                "worker_model_tokens": outcome.worker_model_tokens,
                "elapsed_seconds": round(elapsed, 2),
            })
    return {
        "smoke": "helix_local_action_path_v1",
        "model": model,
        "passed": sum(row["passed"] for row in rows),
        "total": len(rows),
        "all_passed": bool(rows) and all(row["passed"] for row in rows),
        "measured_model_tokens": sum(
            row["steering_model_tokens"] + row["worker_model_tokens"]
            for row in rows
        ),
        "elapsed_seconds": round(sum(row["elapsed_seconds"] for row in rows), 2),
        "cases": rows,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=os.environ.get("HELIX_MODEL", "granite4.1:8b"))
    parser.add_argument(
        "--cases",
        default=",".join(item["name"] for item in CASES),
        help="Comma-separated case names",
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--require-all", action="store_true")
    args = parser.parse_args()
    report = run_smoke(
        args.model,
        [name.strip() for name in args.cases.split(",") if name.strip()],
    )
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(
            f"Local Action Smoke ({report['model']}): "
            f"{report['passed']}/{report['total']} passed, "
            f"{report['measured_model_tokens']} measured tokens, "
            f"{report['elapsed_seconds']}s"
        )
        for row in report["cases"]:
            mark = "PASS" if row["passed"] else "FAIL"
            print(
                f"{mark:4}  {row['name']:<30} state={row['state']:<13} "
                f"calls={row['calls']} tokens="
                f"{row['steering_model_tokens'] + row['worker_model_tokens']}"
            )
    if args.require_all and not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
