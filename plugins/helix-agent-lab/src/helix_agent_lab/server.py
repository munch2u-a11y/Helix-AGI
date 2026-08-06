from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .common import (
    child_environment,
    data_root,
    find_agent,
    load_cases,
    project_python,
    resolve_inside,
    resolve_project,
)

INSTRUCTIONS = (
    "Only use this server for user-requested tests. Call inspect_environment before a run. "
    "Never request, read, or return credentials. Account mode launches an official installed CLI "
    "with cached login and strips API-key environment variables; it does not guarantee zero charges. "
    "Starting a run may send test prompts or code context to the selected provider and writes local artifacts. "
    "Confirm the project, suite, and agents with the user first."
)

mcp = FastMCP("helix-agent-lab", instructions=INSTRUCTIONS, log_level="WARNING")
_processes: dict[str, subprocess.Popen[str]] = {}
_lock = threading.Lock()


def _run_dir(run_id: str) -> Path:
    return data_root() / "runs" / run_id


def _record_path(run_id: str) -> Path:
    return _run_dir(run_id) / "run.json"


def _read_record(run_id: str) -> dict[str, Any]:
    path = _record_path(run_id)
    if not path.is_file():
        raise ValueError(f"Unknown run_id: {run_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def _write_record(record: dict[str, Any]) -> None:
    path = _record_path(record["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    temp.replace(path)


def _watch(run_id: str, proc: subprocess.Popen[str], stdout_handle, stderr_handle) -> None:
    code = proc.wait()
    stdout_handle.close()
    stderr_handle.close()
    record = _read_record(run_id)
    if record.get("status") != "cancelled":
        record["status"] = "passed" if code == 0 else "failed"
    record["exit_code"] = code
    record["finished_at"] = time.time()
    _write_record(record)
    with _lock:
        _processes.pop(run_id, None)


def _start(
    kind: str,
    project: Path,
    command: list[str],
    metadata: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    run_id = uuid.uuid4().hex[:12]
    run_dir = _run_dir(run_id)
    run_dir.mkdir(parents=True, exist_ok=False)
    command = [part.replace("{RUN_DIR}", str(run_dir)) for part in command]
    stdout_handle = (run_dir / "stdout.log").open("w", encoding="utf-8")
    stderr_handle = (run_dir / "stderr.log").open("w", encoding="utf-8")
    record = {
        "run_id": run_id,
        "kind": kind,
        "status": "running",
        "project": str(project),
        "started_at": time.time(),
        "finished_at": None,
        "exit_code": None,
        "metadata": metadata,
        "artifacts": str(run_dir),
    }
    _write_record(record)
    try:
        proc = subprocess.Popen(
            command,
            cwd=project,
            stdin=subprocess.DEVNULL,
            stdout=stdout_handle,
            stderr=stderr_handle,
            text=True,
            shell=False,
            env=env,
        )
    except Exception:
        stdout_handle.close()
        stderr_handle.close()
        record["status"] = "failed_to_start"
        record["finished_at"] = time.time()
        _write_record(record)
        raise
    record["pid"] = proc.pid
    _write_record(record)
    with _lock:
        _processes[run_id] = proc
    threading.Thread(target=_watch, args=(run_id, proc, stdout_handle, stderr_handle), daemon=True).start()
    return record


@mcp.tool(
    title="Inspect local test environment",
    description="Discover installed official coding-agent CLIs and Helix benchmark entrypoints without reading credentials or contacting providers.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def inspect_environment(project_path: str | None = None) -> dict[str, Any]:
    agents = {}
    for name in ("codex", "claude", "gemini"):
        path = find_agent(name)
        agents[name] = {"installed": bool(path), "executable": path}
    project: dict[str, Any] | None = None
    if project_path:
        root = resolve_project(project_path)
        project = {
            "path": str(root),
            "helix_cross_agent_benchmark": (root / "scripts" / "cross_agent_benchmark.py").is_file(),
            "helix_test_runner": (root / "tests" / "run_all_tests.py").is_file(),
        }
    return {
        "agents": agents,
        "project": project,
        "auth_note": "Account readiness is verified only by the official CLI when a run starts. Credentials are never inspected.",
    }


@mcp.tool(
    title="Start Helix cross-agent benchmark",
    description="Start Helix-AGI's repository-native simulator benchmark asynchronously. Supported native adapters are explicitly allowlisted.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
)
def start_helix_benchmark(
    project_path: str,
    agents: list[str] = ["codex"],
    episodes: list[str] | None = None,
    runs: int = 1,
    seed: int = 7,
    auth_mode: str = "account",
) -> dict[str, Any]:
    project = resolve_project(project_path)
    entrypoint = project / "scripts" / "cross_agent_benchmark.py"
    if not entrypoint.is_file():
        raise ValueError("This project does not contain scripts/cross_agent_benchmark.py.")
    allowed = {"helix", "hermes", "pi", "codex", "codex_file_turn", "scripted"}
    if not agents or any(agent not in allowed for agent in agents):
        raise ValueError(f"agents must be selected from {sorted(allowed)}")
    if not 1 <= runs <= 20:
        raise ValueError("runs must be between 1 and 20.")
    if auth_mode not in {"account", "environment"}:
        raise ValueError("auth_mode must be 'account' or 'environment'.")
    api_backed = sorted(set(agents) & {"helix", "hermes", "pi"})
    if auth_mode == "account" and api_backed:
        raise ValueError(
            "Helix's native adapters for helix/hermes/pi use provider API credentials. "
            "Use prompt-case evaluation for Claude or Gemini account login, or explicitly choose auth_mode='environment'."
        )
    env = os.environ.copy()
    removed: list[str] = []
    if auth_mode == "account" and any(agent.startswith("codex") for agent in agents):
        env, removed = child_environment("codex", "account")
    command = [
        project_python(project),
        str(entrypoint),
        "--agents",
        *agents,
        "--runs",
        str(runs),
        "--seed",
        str(seed),
        "--output-dir",
        "{RUN_DIR}/results",
    ]
    if episodes:
        command.extend(["--episodes", *episodes])
    return _start(
        "helix_benchmark",
        project,
        command,
        {
            "agents": agents,
            "episodes": episodes,
            "runs": runs,
            "seed": seed,
            "auth_mode": auth_mode,
            "api_environment_removed": removed,
        },
        env=env,
    )


@mcp.tool(
    title="Start deterministic prompt-case evaluation",
    description="Run JSON or JSONL prompt cases through installed Codex, Claude Code, or Gemini CLIs. Account mode strips API-key environment variables and relies on each official CLI's cached login.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True),
)
def start_prompt_eval(
    project_path: str,
    cases_file: str,
    agents: list[str],
    auth_mode: str = "account",
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    project = resolve_project(project_path)
    cases = resolve_inside(project, cases_file, suffixes={".json", ".jsonl"})
    load_cases(cases)
    allowed = {"codex", "claude", "gemini"}
    if not agents or any(agent not in allowed for agent in agents):
        raise ValueError(f"agents must be selected from {sorted(allowed)}")
    if auth_mode not in {"account", "environment"}:
        raise ValueError("auth_mode must be 'account' or 'environment'.")
    if not 30 <= timeout_seconds <= 1800:
        raise ValueError("timeout_seconds must be between 30 and 1800.")
    plugin_root = Path(__file__).resolve().parents[2]
    command = [
        project_python(project),
        "-m",
        "helix_agent_lab.prompt_runner",
        "--project",
        str(project),
        "--cases",
        str(cases.relative_to(project)),
        "--agents",
        *agents,
        "--auth-mode",
        auth_mode,
        "--timeout",
        str(timeout_seconds),
        "--output",
        "{RUN_DIR}/results",
    ]
    env_path = str(plugin_root / "src")
    env = os.environ.copy()
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = env_path + (os.pathsep + existing if existing else "")
    return _start(
        "prompt_eval",
        project,
        command,
        {"agents": agents, "cases_file": str(cases), "auth_mode": auth_mode},
        env=env,
    )


@mcp.tool(
    title="Get test-run status",
    description="Read status and artifact location for a previously started test run.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def get_run(run_id: str, log_tail_chars: int = 4000) -> dict[str, Any]:
    if not 0 <= log_tail_chars <= 20_000:
        raise ValueError("log_tail_chars must be between 0 and 20,000.")
    record = _read_record(run_id)
    run_dir = _run_dir(run_id)
    with _lock:
        known_process = run_id in _processes
    if record["status"] == "running" and not known_process:
        record["status"] = "unknown_after_server_restart"
    for name in ("stdout", "stderr"):
        path = run_dir / f"{name}.log"
        record[f"{name}_tail"] = path.read_text(encoding="utf-8", errors="replace")[-log_tail_chars:] if path.is_file() else ""
    summaries = [
        run_dir / "results" / "summary.md",
        run_dir / "results" / "comparative_summary.md",
    ]
    summary_path = next((path for path in summaries if path.is_file()), None)
    record["summary"] = (
        summary_path.read_text(encoding="utf-8", errors="replace")[-12_000:]
        if summary_path
        else ""
    )
    record["result_files"] = [
        str(path)
        for path in sorted((run_dir / "results").rglob("*"))
        if path.is_file()
    ][:100] if (run_dir / "results").is_dir() else []
    return record


@mcp.tool(
    title="List recent test runs",
    description="List recent locally recorded test runs without reading their logs.",
    annotations=ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True, openWorldHint=False),
)
def list_runs(limit: int = 20) -> dict[str, Any]:
    if not 1 <= limit <= 100:
        raise ValueError("limit must be between 1 and 100.")
    root = data_root() / "runs"
    records: list[dict[str, Any]] = []
    if root.is_dir():
        paths = sorted(root.glob("*/run.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        for path in paths[:limit]:
            record = json.loads(path.read_text(encoding="utf-8"))
            records.append({key: record.get(key) for key in ("run_id", "kind", "status", "project", "started_at", "finished_at", "exit_code", "metadata")})
    return {"runs": records}


@mcp.tool(
    title="Cancel a running test",
    description="Terminate a test process started by this MCP server. This cannot undo files the test or coding agent already wrote.",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True, openWorldHint=False),
)
def cancel_run(run_id: str) -> dict[str, Any]:
    record = _read_record(run_id)
    with _lock:
        proc = _processes.get(run_id)
    if not proc or proc.poll() is not None:
        return {"run_id": run_id, "cancelled": False, "status": record["status"]}
    record["status"] = "cancelled"
    record["finished_at"] = time.time()
    _write_record(record)
    proc.terminate()
    return {"run_id": run_id, "cancelled": True, "status": "cancelled"}


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
