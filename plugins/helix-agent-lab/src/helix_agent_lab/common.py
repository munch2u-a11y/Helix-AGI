from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

AGENT_EXECUTABLES = {
    "codex": ("codex", "codex.exe"),
    "claude": ("claude", "claude.exe", "claude.cmd"),
    "gemini": ("gemini", "gemini.exe", "gemini.cmd"),
}

ACCOUNT_ENV_BLOCKLIST = {
    "codex": {"CODEX_API_KEY", "OPENAI_API_KEY"},
    "claude": {"ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN"},
    "gemini": {
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "GOOGLE_GENAI_USE_VERTEXAI",
    },
}


def data_root() -> Path:
    raw = os.environ.get("HELIX_AGENT_LAB_DATA", "").strip()
    if raw and "${" not in raw:
        root = Path(raw).expanduser()
    else:
        root = Path.home() / ".helix-agent-lab"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def resolve_project(path: str) -> Path:
    project = Path(path).expanduser().resolve()
    if not project.is_dir():
        raise ValueError(f"Project directory does not exist: {project}")
    return project


def resolve_inside(project: Path, relative_path: str, *, suffixes: set[str] | None = None) -> Path:
    candidate = (project / relative_path).resolve()
    try:
        candidate.relative_to(project)
    except ValueError as exc:
        raise ValueError("Path must stay inside the selected project.") from exc
    if not candidate.is_file():
        raise ValueError(f"File does not exist: {candidate}")
    if suffixes and candidate.suffix.lower() not in suffixes:
        raise ValueError(f"Expected one of {sorted(suffixes)}, got {candidate.suffix!r}.")
    return candidate


def find_agent(agent: str) -> str | None:
    for name in AGENT_EXECUTABLES.get(agent, ()):
        found = shutil.which(name)
        if found:
            return found
    return None


def project_python(project: Path) -> str:
    configured = os.environ.get("HELIX_AGENT_LAB_PYTHON", "").strip()
    candidates = [
        Path(configured).expanduser() if configured else None,
        project / ".venv" / "Scripts" / "python.exe",
        project / ".venv" / "bin" / "python",
        Path(sys.executable),
    ]
    for candidate in candidates:
        if candidate and candidate.is_file():
            return str(candidate.resolve())
    raise RuntimeError("No Python interpreter is available for the test run.")


def child_environment(agent: str, auth_mode: str) -> tuple[dict[str, str], list[str]]:
    env = os.environ.copy()
    removed: list[str] = []
    if auth_mode == "account":
        for key in ACCOUNT_ENV_BLOCKLIST[agent]:
            if key in env:
                removed.append(key)
                env.pop(key, None)
    elif auth_mode != "environment":
        raise ValueError("auth_mode must be 'account' or 'environment'.")
    env["HELIX_AGENT_LAB"] = "1"
    return env, sorted(removed)


def load_cases(path: Path) -> list[dict[str, Any]]:
    if path.suffix.lower() == ".jsonl":
        cases = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        payload = json.loads(path.read_text(encoding="utf-8"))
        cases = payload.get("cases", []) if isinstance(payload, dict) else payload
    if not isinstance(cases, list) or not cases:
        raise ValueError("Cases file must contain a non-empty list.")
    for index, case in enumerate(cases):
        if not isinstance(case, dict) or not isinstance(case.get("prompt"), str):
            raise ValueError(f"Case {index + 1} must be an object with a string prompt.")
        if len(case["prompt"]) > 16_000:
            raise ValueError(f"Case {index + 1} prompt exceeds 16,000 characters.")
        assertions = case.get("assert")
        if not isinstance(assertions, dict) or not any(
            assertions.get(key) for key in ("contains", "not_contains", "regex")
        ):
            raise ValueError(f"Case {index + 1} must define at least one deterministic assertion.")
    return cases
