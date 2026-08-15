"""
Model Detector Utility — Dynamic Model Listing and Querying

Provides utility functions to list available models from Ollama,
local GGUF directories, and Google's Gemini models API.
"""

import os
import json
import urllib.request
import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger("helix.wizard.model_detector")

DEFAULT_MODELS = {
    "gemini": [
        "gemini-2.5-flash",
        "gemini-2.5-pro",
        "gemini-1.5-flash",
        "gemini-1.5-pro",
        "gemini-3.0-flash-preview"
    ],
    "anthropic": [
        "claude-fable-5",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-latest",
        "claude-3-opus-20240229"
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "o1",
        "o3-mini"
    ],
    "alibaba": [
        "qwen-turbo",
        "qwen-plus",
        "qwen-max"
    ],
    "ollama": [
        "granite4.1:8b",
        "granite4.1:3b",
        "llama3",
        "mistral"
    ],
    "llama_cpp": [],
    # Empty model selection means the authenticated account default.  The
    # friendly label is normalized by CodexCliSession before thread/start.
    "codex_cli": ["account-default"],
}


def get_default_models(provider: str) -> list:
    """Return default models for the specified provider."""
    return DEFAULT_MODELS.get(provider.lower(), [])


def detect_ollama_models(url: str = "http://localhost:11434") -> list:
    """Query local Ollama instance for pulled models."""
    if not url:
        url = "http://localhost:11434"
    endpoint = f"{url.rstrip('/')}/api/tags"
    try:
        req = urllib.request.Request(endpoint, method="GET")
        with urllib.request.urlopen(req, timeout=2) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            logger.info(f"Ollama detected models: {models}")
            return models
    except Exception as e:
        logger.warning(f"Failed to query Ollama at {endpoint}: {e}")
        return []


def detect_gguf_models(base_dir: str) -> list:
    """Scan local models/ directory for .gguf model files."""
    models_dir = Path(base_dir) / "models"
    if not models_dir.exists():
        return []
    try:
        models = [p.name for p in models_dir.glob("*.gguf")]
        logger.info(f"GGUF detected models in {models_dir}: {models}")
        return models
    except Exception as e:
        logger.warning(f"Failed to list GGUF models: {e}")
        return []


def fetch_gemini_models(api_key: str) -> list:
    """Query Google Generative Language API for available Gemini models."""
    if not api_key:
        return []
    url = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode("utf-8"))
            models = []
            for m in data.get("models", []):
                name = m.get("name", "")
                # Format: models/gemini-2.5-flash
                if name.startswith("models/"):
                    name = name[7:]
                
                # Filter for models supporting content generation
                methods = m.get("supportedGenerationMethods", [])
                if "generateContent" in methods:
                    models.append(name)
            logger.info(f"Fetched Gemini models: {models}")
            return sorted(list(set(models)))
    except Exception as e:
        logger.warning(f"Failed to fetch Gemini models: {e}")
        return []


def codex_login_status() -> str:
    """Return the local Codex authentication status, or an empty string."""
    executable = shutil.which("codex")
    if not executable:
        return ""
    try:
        proc = subprocess.run(
            [executable, "login", "status"],
            capture_output=True,
            text=True,
            timeout=8,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    output = (proc.stdout or proc.stderr or "").strip()
    return output if proc.returncode == 0 else ""


def codex_app_server_probe(timeout: int = 20) -> tuple[bool, str]:
    """Verify login plus the App Server initialize/thread handshake.

    Login status alone does not prove that the installed CLI supports the
    production transport Helix uses.  This opens no turn, calls no host tool,
    and closes the ephemeral read-only thread immediately.
    """
    login = codex_login_status()
    if not login:
        return False, "Install the Codex CLI and run `codex login`."
    session = None
    try:
        from core.self_state import identity_kernel
        from llm.providers.codex_cli_provider import CodexCliSession

        session = CodexCliSession(
            system_instruction=identity_kernel("I am Helix."),
            options={"timeout": timeout, "thought_only": True, "effort": "low"},
        )
        return True, f"{login}\nCodex App Server handshake: ready."
    except Exception as exc:
        logger.warning("Codex App Server probe failed: %s", exc)
        return False, f"Codex login is present, but App Server failed: {exc}"
    finally:
        if session is not None:
            session.close()
