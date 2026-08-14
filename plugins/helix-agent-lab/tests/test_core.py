import sys
import time
from pathlib import Path

import pytest

from helix_agent_lab.common import child_environment, load_cases, resolve_inside
from helix_agent_lab.prompt_runner import score_response
from helix_agent_lab import server


def test_account_mode_removes_codex_api_keys(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")
    monkeypatch.setenv("CODEX_API_KEY", "secret")
    env, removed = child_environment("codex", "account")
    assert "OPENAI_API_KEY" not in env
    assert "CODEX_API_KEY" not in env
    assert removed == ["CODEX_API_KEY", "OPENAI_API_KEY"]


def test_environment_mode_preserves_explicit_configuration(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "secret")
    env, removed = child_environment("claude", "environment")
    assert env["ANTHROPIC_API_KEY"] == "secret"
    assert removed == []


def test_path_must_stay_inside_project(tmp_path: Path):
    project = tmp_path / "project"
    project.mkdir()
    outside = tmp_path / "outside.json"
    outside.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError, match="inside"):
        resolve_inside(project, "../outside.json")


def test_cases_and_deterministic_score(tmp_path: Path):
    path = tmp_path / "cases.jsonl"
    path.write_text('{"id":"one","prompt":"hello","assert":{"contains":["ok"]}}\n', encoding="utf-8")
    assert load_cases(path)[0]["id"] == "one"
    score = score_response("status: ok", {"contains": ["ok"], "not_contains": ["fail"]})
    assert score["passed"] is True
    assert score["checks_passed"] == 2


def test_cases_require_an_assertion(tmp_path: Path):
    path = tmp_path / "cases.json"
    path.write_text('[{"id":"one","prompt":"hello"}]', encoding="utf-8")
    with pytest.raises(ValueError, match="assertion"):
        load_cases(path)


def test_async_run_records_summary(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("HELIX_AGENT_LAB_DATA", str(tmp_path / "data"))
    command = [
        sys.executable,
        "-c",
        (
            "import pathlib,sys; "
            "p=pathlib.Path(sys.argv[1]); p.mkdir(parents=True); "
            "(p/'summary.md').write_text('# Passed\\n', encoding='utf-8'); "
            "print('done')"
        ),
        "{RUN_DIR}/results",
    ]
    record = server._start("unit", tmp_path, command, {})
    deadline = time.time() + 5
    while time.time() < deadline:
        current = server._read_record(record["run_id"])
        if current["status"] != "running":
            break
        time.sleep(0.02)
    result = server.get_run(record["run_id"])
    assert result["status"] == "passed"
    assert "# Passed" in result["summary"]
    assert "done" in result["stdout_tail"]
