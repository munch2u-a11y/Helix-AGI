"""Model identity and fallback policy regressions for the Ollama backend."""

from unittest.mock import Mock

import pytest

from llm_backend import LLMBackend


def test_primary_failure_does_not_silently_change_models(monkeypatch) -> None:
    monkeypatch.delenv("HELIX_LLM_FALLBACK_MODEL", raising=False)
    backend = LLMBackend(default_model="granite-test")
    backend._call_ollama = Mock(side_effect=RuntimeError("primary unavailable"))

    with pytest.raises(RuntimeError, match="primary unavailable"):
        backend.generate("hello")

    assert backend._call_ollama.call_count == 1
    assert backend._call_ollama.call_args.args[0]["model"] == "granite-test"


def test_explicit_fallback_is_visible_and_opt_in() -> None:
    backend = LLMBackend(
        default_model="granite-test",
        fallback_model="qwen-test",
    )
    attempted_models = []

    def call(payload):
        attempted_models.append(payload["model"])
        if payload["model"] == "granite-test":
            raise RuntimeError("primary unavailable")
        return "fallback response"

    backend._call_ollama = call

    assert backend.generate("hello") == "fallback response"
    assert attempted_models == ["granite-test", "qwen-test"]
