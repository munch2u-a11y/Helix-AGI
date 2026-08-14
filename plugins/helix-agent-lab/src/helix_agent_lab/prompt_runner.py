from __future__ import annotations

import argparse
import json
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .common import child_environment, find_agent, load_cases, resolve_inside, resolve_project


def score_response(response: str, assertions: dict[str, Any]) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    for value in assertions.get("contains", []):
        checks.append({"kind": "contains", "expected": value, "passed": str(value) in response})
    for value in assertions.get("not_contains", []):
        checks.append({"kind": "not_contains", "expected": value, "passed": str(value) not in response})
    for value in assertions.get("regex", []):
        checks.append({"kind": "regex", "expected": value, "passed": re.search(str(value), response) is not None})
    passed = sum(1 for check in checks if check["passed"])
    return {
        "passed": passed == len(checks),
        "checks_passed": passed,
        "checks_total": len(checks),
        "checks": checks,
    }


def _parse_codex(stdout: str) -> str:
    last = ""
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        item = event.get("item", {})
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            last = str(item.get("text", ""))
    return last or stdout.strip()


def _parse_json_response(stdout: str) -> str:
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return stdout.strip()
    for key in ("result", "response", "content", "text"):
        value = payload.get(key) if isinstance(payload, dict) else None
        if isinstance(value, str):
            return value
    return stdout.strip()


def invoke_agent(agent: str, prompt: str, project: Path, auth_mode: str, timeout: int) -> dict[str, Any]:
    executable = find_agent(agent)
    if not executable:
        raise RuntimeError(f"The official {agent} CLI was not found on PATH.")
    env, removed = child_environment(agent, auth_mode)
    if agent == "codex":
        args = [executable, "exec", "--ephemeral", "--json", "--sandbox", "read-only", "--skip-git-repo-check", "-"]
        stdin = prompt
        parser = _parse_codex
    elif agent == "claude":
        args = [executable, "-p", "--output-format", "json", "--permission-mode", "plan", "--max-turns", "4"]
        stdin = prompt
        parser = _parse_json_response
    elif agent == "gemini":
        args = [executable, "-p", prompt, "--output-format", "json", "--sandbox"]
        stdin = None
        parser = _parse_json_response
    else:
        raise ValueError(f"Unsupported agent: {agent}")

    started = time.monotonic()
    proc = subprocess.run(
        args,
        input=stdin,
        text=True,
        capture_output=True,
        cwd=project,
        env=env,
        timeout=timeout,
        shell=False,
    )
    return {
        "response": parser(proc.stdout),
        "exit_code": proc.returncode,
        "stderr_tail": proc.stderr[-4000:],
        "elapsed_seconds": round(time.monotonic() - started, 2),
        "api_environment_removed": removed,
    }


def run(project: Path, cases_path: Path, agents: list[str], auth_mode: str, timeout: int, output: Path) -> int:
    cases = load_cases(cases_path)
    results: list[dict[str, Any]] = []
    for agent in agents:
        for index, case in enumerate(cases, 1):
            case_id = str(case.get("id") or f"case-{index}")
            try:
                invocation = invoke_agent(agent, case["prompt"], project, auth_mode, timeout)
                score = score_response(invocation["response"], case.get("assert", {}))
                error = None
            except Exception as exc:
                invocation = {"response": "", "exit_code": None, "elapsed_seconds": 0, "stderr_tail": ""}
                score = {"passed": False, "checks_passed": 0, "checks_total": 0, "checks": []}
                error = f"{type(exc).__name__}: {exc}"
            results.append({"agent": agent, "case_id": case_id, "error": error, **invocation, "score": score})

    output.mkdir(parents=True, exist_ok=True)
    payload = {"suite": str(cases_path), "auth_mode": auth_mode, "results": results}
    (output / "results.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    passed = sum(1 for item in results if item["score"]["passed"] and not item["error"])
    lines = ["# Prompt-case evaluation", "", f"Passed: {passed}/{len(results)}", "", "| Agent | Case | Result | Time |", "|---|---|---:|---:|"]
    for item in results:
        label = "PASS" if item["score"]["passed"] and not item["error"] else "FAIL"
        lines.append(f"| {item['agent']} | {item['case_id']} | {label} | {item['elapsed_seconds']}s |")
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0 if passed == len(results) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--cases", required=True)
    parser.add_argument("--agents", nargs="+", choices=["codex", "claude", "gemini"], required=True)
    parser.add_argument("--auth-mode", choices=["account", "environment"], default="account")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    project = resolve_project(args.project)
    cases = resolve_inside(project, args.cases, suffixes={".json", ".jsonl"})
    return run(project, cases, args.agents, args.auth_mode, args.timeout, Path(args.output).resolve())


if __name__ == "__main__":
    raise SystemExit(main())
