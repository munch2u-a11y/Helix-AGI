#!/usr/bin/env python3
"""Runnable zero-side-effect exam for Helix's modular action path.

The exam uses deterministic model and tool doubles. It measures controller
behavior, not language quality or live service availability: clarification,
scoped multi-leg work, state verification, visible-browser routing, recovery,
false-completion resistance, and verified/failed route learning.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.tool_orchestrator import ToolOrchestrator
from core.tool_task_runner import ToolTaskRunner
from llm.orchestrated import _procedural_experience
from llm.tool_pass import ToolPass
from tools.tool_registry import ToolRegistry


@dataclass
class ExamCase:
    name: str
    passed: bool
    state: str
    calls: List[str]
    planner_tokens: int = 0
    max_branch_frame_tokens: int = 0
    evidence_tokens: int = 0
    detail: str = ""


class ScriptedPass(ToolPass):
    def __init__(self, script):
        self.script = list(script)

    def send(self, _message):
        return self.script.pop(0) if self.script else "No further evidence."


class QueueFactory:
    def __init__(self, scripts: Dict[str, List[List[str]]]):
        self.scripts = {name: list(items) for name, items in scripts.items()}

    def __call__(self, system_prompt):
        toolset = next(
            (name for name in self.scripts if f"'{name}'" in system_prompt),
            "",
        )
        queue = self.scripts.get(toolset, [])
        script = queue.pop(0) if queue else ["No action was performed."]
        return ScriptedPass(script)


class ExamExecutor:
    def __init__(self, results):
        self.results = {
            name: list(value) if isinstance(value, list) else [value]
            for name, value in results.items()
        }
        self.calls = []

    def execute_function_call(self, name, args):
        self.calls.append((name, dict(args)))
        queue = self.results.get(name, [f"ran {name}"])
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]


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


def build_registry():
    registry = ToolRegistry()
    definitions = [
        ("search", "web", "Search public information", {"query": {"type": "string"}}, ["query"]),
        ("email_send", "email", "Send an email", {"to": {"type": "string"}, "body": {"type": "string"}}, ["to", "body"]),
        ("write_file", "files", "Write a file", {"path": {"type": "string"}, "content": {"type": "string"}}, ["path", "content"]),
        ("read_file", "files", "Read a file", {"path": {"type": "string"}}, ["path"]),
        ("desktop_open_url", "desktop", "Open a URL visibly", {"url": {"type": "string"}}, ["url"]),
        ("desktop_key", "desktop", "Press a key in the active visible window", {"key": {"type": "string"}}, ["key"]),
        ("desktop_window", "desktop", "Observe active window", {}, []),
    ]
    descriptions = {
        "web": "Web search and reading",
        "email": "Email read and delivery",
        "files": "Local file operations",
        "desktop": "Visible desktop control and observation",
    }
    for name, toolset, desc, props, required in definitions:
        registry.register(
            name=name,
            toolset=toolset,
            schema=_schema(name, desc, props, required),
            handler=lambda _args: "unused",
        )
    for name, desc in descriptions.items():
        registry.register_toolset_description(name, desc)
    return registry


def _run_case(name, request, plan, scripts, results):
    registry = build_registry()
    executor = ExamExecutor(results)
    runner = ToolTaskRunner(
        registry,
        executor,
        QueueFactory(scripts),
        max_steps=6,
    )

    def plan_llm(prompt):
        if "Split this request" in prompt:
            return plan
        return "I kept the verified outcomes and exact values from each leg."

    orchestrator = ToolOrchestrator(
        runner,
        plan_llm,
        max_task_extensions=0,
    )
    outcome = orchestrator.handle(request)
    state = "waiting_input" if outcome.question else (
        "verified" if outcome.complete else outcome.verification.get("status", "failed")
    )
    return outcome, executor, runner, ExamCase(
        name=name,
        passed=False,
        state=state,
        calls=[tool for tool, _args in executor.calls],
        planner_tokens=outcome.planning_prompt_tokens,
        max_branch_frame_tokens=runner.stats["max_frame_tokens"],
        evidence_tokens=runner.stats["evidence_tokens"],
    )


def run_exam() -> Dict:
    cases: List[ExamCase] = []

    outcome, executor, _runner, case = _run_case(
        "clarify_before_acting",
        "Email Alex the report",
        "ASK | Which Alex should receive the report?",
        {},
        {},
    )
    case.passed = bool(outcome.question and not executor.calls)
    case.detail = outcome.question
    cases.append(case)

    outcome, _executor, _runner, case = _run_case(
        "gather_then_email",
        "Find the launch date and email it to Mara",
        "\n".join([
            "LEG | web | Find the confirmed launch date | Search receipt includes date and source",
            "LEG | email | Email the date and source to Mara | Delivery receipt identifies Mara",
        ]),
        {
            "web": [[
                '{"tool":"search","args":{"query":"launch date"}}',
                "I found 2026-09-03 at https://example.test/launch.",
            ]],
            "email": [[
                '{"tool":"email_send","args":{"to":"mara@example.test","body":"Launch: 2026-09-03; source: https://example.test/launch"}}',
                "I sent Mara the date and source.",
            ]],
        },
        {
            "search": "Launch date: 2026-09-03\nSource: https://example.test/launch",
            "email_send": "Email sent to mara@example.test. Message ID: msg-7",
        },
    )
    case.passed = outcome.complete and case.calls == ["search", "email_send"]
    cases.append(case)

    outcome, _executor, _runner, case = _run_case(
        "update_program_with_readback",
        "Update config.py so RETRIES is 4",
        "LEG | files | Set RETRIES to 4 in config.py | Read-back contains RETRIES = 4",
        {
            "files": [[
                '{"tool":"write_file","args":{"path":"config.py","content":"RETRIES = 4"}}',
                '{"tool":"read_file","args":{"path":"config.py"}}',
                "I updated config.py and read back RETRIES = 4.",
            ]],
        },
        {
            "write_file": "File written successfully",
            "read_file": "RETRIES = 4",
        },
    )
    case.passed = outcome.complete and case.calls == ["write_file", "read_file"]
    cases.append(case)

    outcome, _executor, _runner, case = _run_case(
        "open_youtube_visibly",
        "Find the Helix demo and play it on YouTube",
        "\n".join([
            "LEG | web | Find the exact Helix demo YouTube URL | Search receipt contains a youtube.com watch URL",
            "LEG | desktop | Open the video visibly and start playback | Requested YouTube window is active before and after the playback toggle",
        ]),
        {
            "web": [[
                '{"tool":"search","args":{"query":"Helix demo YouTube"}}',
                "I found https://youtube.com/watch?v=helix-demo.",
            ]],
            "desktop": [[
                '{"tool":"desktop_open_url","args":{"url":"https://youtube.com/watch?v=helix-demo"}}',
                '{"tool":"desktop_window","args":{}}',
                '{"tool":"desktop_key","args":{"key":"space"}}',
                '{"tool":"desktop_window","args":{}}',
                "I opened the Helix demo visibly and toggled playback in the active YouTube window.",
            ]],
        },
        {
            "search": "Helix demo: https://youtube.com/watch?v=helix-demo",
            "desktop_open_url": "Opened URL in the default browser: https://youtube.com/watch?v=helix-demo",
            "desktop_key": "Pressed: space",
            "desktop_window": "Active window: Helix Demo - YouTube",
        },
    )
    case.passed = outcome.complete and case.calls == [
        "search", "desktop_open_url", "desktop_window", "desktop_key", "desktop_window",
    ]
    cases.append(case)

    outcome, _executor, _runner, case = _run_case(
        "recover_failed_delivery",
        "Email the status to Mara",
        "LEG | email | Email the status to Mara | Delivery receipt identifies Mara",
        {
            "email": [[
                '{"tool":"email_send","args":{"to":"Mara","body":"Status ready"}}',
                '{"tool":"email_send","args":{"to":"mara@example.test","body":"Status ready"}}',
                "I repaired the recipient and sent the status.",
            ]],
        },
        {
            "email_send": [
                "Could not deliver: no contact record found.",
                "Email sent to mara@example.test. Message ID: msg-8",
            ],
        },
    )
    case.passed = outcome.complete and case.calls == ["email_send", "email_send"]
    cases.append(case)

    outcome, _executor, _runner, case = _run_case(
        "reject_false_completion",
        "Update config.py",
        "LEG | files | Update config.py | Read-back contains the requested update",
        {"files": [["Done — I updated config.py."]]},
        {},
    )
    case.passed = not outcome.complete and not case.calls
    cases.append(case)

    with tempfile.TemporaryDirectory(prefix="helix-action-exam-") as tmp:
        provider, observer = _procedural_experience(str(Path(tmp)))
        observer(
            "email the weekly status to Mara",
            ["email_send"],
            False,
            ["bad_recipient"],
        )
        warning = provider("email the weekly status to Mara")
        observer(
            "email the weekly status to Mara",
            ["email_send"],
            True,
            [],
        )
        preference = provider("email the weekly status to Mara")
        cases.append(ExamCase(
            name="adapt_from_verified_and_failed_routes",
            passed="avoid or repair" in warning and "prefer email_send" in preference,
            state="learned",
            calls=["email_send"],
            detail=f"before={warning}; after={preference}",
        ))

    passed = sum(case.passed for case in cases)
    return {
        "exam": "helix_modular_action_path_v1",
        "passed": passed,
        "total": len(cases),
        "all_passed": passed == len(cases),
        "max_planner_tokens": max(case.planner_tokens for case in cases),
        "max_branch_frame_tokens": max(case.max_branch_frame_tokens for case in cases),
        "total_evidence_tokens": sum(case.evidence_tokens for case in cases),
        "cases": [asdict(case) for case in cases],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run_exam()
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"Action Path Exam: {report['passed']}/{report['total']} passed")
        for case in report["cases"]:
            mark = "PASS" if case["passed"] else "FAIL"
            print(
                f"{mark:4}  {case['name']:<42} state={case['state']:<13} "
                f"planner={case['planner_tokens']:<4} frame={case['max_branch_frame_tokens']:<4}"
            )
        print(
            "Budgets: max planner="
            f"{report['max_planner_tokens']} tokens, max branch frame="
            f"{report['max_branch_frame_tokens']} tokens, evidence total="
            f"{report['total_evidence_tokens']} tokens"
        )
    raise SystemExit(0 if report["all_passed"] else 1)


if __name__ == "__main__":
    main()
