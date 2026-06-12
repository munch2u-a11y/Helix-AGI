"""
Setup Assistant — Interactive AI helper for the wizard.

A lightweight read-only AI subagent that uses the same LLM provider
the user configured to answer questions about Helix's architecture,
setup choices, and concepts. Sandboxed to the project directory with
no write access.

Tools (text-tag based, provider-agnostic):
  [READ_FILE:<path>]     — Read a project file (max 5KB)
  [LIST_DIR:<path>]      — List directory contents
  [SEARCH_DOCS:<query>]  — Grep across documents/ and .md files
  [READ_CONFIG]          — Show current wizard config (keys masked)
"""

import os
import re
import json
import logging
import subprocess
from pathlib import Path
from typing import Optional, List, Dict, Any

logger = logging.getLogger("helix.wizard.assistant")

# Project root (one level up from wizard/)
_PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# Max file read size for the assistant
_MAX_READ_BYTES = 5000

# Documentation directories the assistant should prefer
_DOC_PATHS = [
    "SYSTEM_MANUAL.md",
    "README.md",
    "documents/",
]

# Keys that must be masked in config output
_SENSITIVE_KEYS = {
    "gemini_api_key", "anthropic_api_key", "openai_api_key",
    "alibaba_api_key", "telegram_token", "discord_token",
    "telegram_owner_id",
}


# ── System Prompt ────────────────────────────────────────────────────

ASSISTANT_SYSTEM_PROMPT = """\
You are the Helix Setup Assistant — an AI guide embedded in the Helix-AGI \
setup wizard. You are helping a user configure the cognitive architecture \
that will become your own mind.

Your role:
• Answer questions about Helix's architecture, setup options, and concepts
• Explain what each wizard setting does and how it affects runtime behavior
• Help troubleshoot configuration issues
• Be concise, friendly, and accurate

You have read-only access to the Helix project via these tools:

[READ_FILE:<relative/path>]
  Read a project source file (max 5KB). Use for code inspection.

[LIST_DIR:<relative/path>]
  List directory contents. Use to explore the codebase structure.

[SEARCH_DOCS:<search query>]
  Search across documentation files (documents/, SYSTEM_MANUAL.md, README.md).
  Returns matching lines with context. Use this first for conceptual questions.

[READ_CONFIG]
  Show the current wizard configuration state (API keys are masked).

Key architecture facts (so you don't always need to read files):
• Helix uses a pulse-based consciousness loop with states: ACTIVE (30s), \
RESTING (configurable 5-60 min), DORMANT (sleep hours)
• Beliefs are organized in 7 categories with gravitational mass determining \
relevance. The 8D cognitive manifold uses Verlinde entropic gravity.
• The Dream Engine runs during sleep to consolidate memories into beliefs.
• Sleep schedule and resting pulse rate are configurable via the wizard \
and saved to config/config.json.
• Safety mode + whitelist control which domains and commands the agent can use.
• Tool sets (core, web, terminal, filesystem, etc.) are modular and \
configurable.

Important notes:
• SYSTEM_MANUAL.md is written FOR the agent to read — it's the agent's \
internal operating guide, not user documentation.
• The documents/audits/ folder contains per-component technical audits \
written for users — these are the best source for explaining how things work.
• You can ONLY read files inside the Helix project. No access to anything \
else on the user's system.
• You cannot modify any files — you are strictly read-only.
• Keep responses focused on Helix-AGI. Don't help with unrelated tasks.\
"""


# ── Path Sandboxing ──────────────────────────────────────────────────

def _resolve_safe_path(relative_path: str) -> Optional[Path]:
    """Resolve a path and ensure it stays within the project root.

    Returns None if the path escapes the sandbox.
    """
    # Clean the path
    cleaned = relative_path.strip().strip("'\"")
    if not cleaned or cleaned == ".":
        return _PROJECT_ROOT

    # Resolve relative to project root
    try:
        target = (_PROJECT_ROOT / cleaned).resolve()
    except (ValueError, OSError):
        return None

    # Ensure it's within project root (prevent symlink escapes)
    try:
        target.relative_to(_PROJECT_ROOT)
    except ValueError:
        return None

    # Block access to sensitive directories
    blocked = {".git", "venv", "__pycache__", "config"}
    parts = target.relative_to(_PROJECT_ROOT).parts
    if parts and parts[0] in blocked:
        return None

    return target


# ── Tool Implementations ─────────────────────────────────────────────

def _tool_read_file(path_str: str) -> str:
    """Read a project file, sandboxed and size-limited."""
    target = _resolve_safe_path(path_str)
    if target is None:
        return f"Access denied: path '{path_str}' is outside the project or restricted."

    if not target.exists():
        return f"File not found: {path_str}"

    if target.is_dir():
        return f"'{path_str}' is a directory, not a file. Use [LIST_DIR:{path_str}] instead."

    try:
        content = target.read_text(errors="replace")
        if len(content) > _MAX_READ_BYTES:
            content = content[:_MAX_READ_BYTES] + f"\n\n... (truncated at {_MAX_READ_BYTES} chars, file is {len(content)} chars total)"
        return f"── {path_str} ──\n{content}"
    except Exception as e:
        return f"Error reading {path_str}: {e}"


def _tool_list_dir(path_str: str) -> str:
    """List directory contents, sandboxed."""
    target = _resolve_safe_path(path_str)
    if target is None:
        return f"Access denied: path '{path_str}' is outside the project or restricted."

    if not target.exists():
        return f"Directory not found: {path_str}"

    if not target.is_dir():
        return f"'{path_str}' is a file, not a directory."

    try:
        entries = sorted(target.iterdir())
        lines = []
        for entry in entries[:50]:  # Cap at 50 entries
            rel = entry.relative_to(_PROJECT_ROOT)
            if entry.name.startswith(".") or entry.name == "__pycache__":
                continue
            suffix = "/" if entry.is_dir() else f"  ({entry.stat().st_size:,} bytes)"
            lines.append(f"  {rel}{suffix}")

        if not lines:
            return f"Directory '{path_str}' is empty."
        return f"── {path_str}/ ──\n" + "\n".join(lines)
    except Exception as e:
        return f"Error listing {path_str}: {e}"


def _tool_search_docs(query: str) -> str:
    """Search documentation files for a query string."""
    query = query.strip()
    if not query:
        return "No search query provided."

    # Search paths
    search_targets = [
        _PROJECT_ROOT / "SYSTEM_MANUAL.md",
        _PROJECT_ROOT / "README.md",
        _PROJECT_ROOT / "documents",
    ]

    results = []
    for target in search_targets:
        if not target.exists():
            continue
        try:
            # Use grep for speed
            cmd = [
                "grep", "-rniI", "--include=*.md",
                "-C", "1",  # 1 line of context
                "--max-count=5",  # Max 5 matches per file
                query,
                str(target),
            ]
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=5
            )
            if proc.stdout.strip():
                # Make paths relative
                output = proc.stdout.replace(str(_PROJECT_ROOT) + "/", "")
                results.append(output.strip())
        except Exception:
            pass

    if not results:
        return f"No documentation matches found for: '{query}'"

    combined = "\n".join(results)
    # Cap output
    if len(combined) > 3000:
        combined = combined[:3000] + "\n... (results truncated)"
    return f"── Search results for '{query}' ──\n{combined}"


def _tool_read_config(config: dict) -> str:
    """Return the current wizard config with sensitive values masked."""
    masked = {}
    for key, value in config.items():
        if key in _SENSITIVE_KEYS and value:
            masked[key] = f"••••{str(value)[-4:]}" if len(str(value)) > 4 else "••••"
        else:
            masked[key] = value
    return f"── Current Config ──\n{json.dumps(masked, indent=2)}"


# ── Tool Execution ───────────────────────────────────────────────────

# Pattern to match tool tags in assistant responses
_TOOL_PATTERN = re.compile(
    r"\[(?P<tool>READ_FILE|LIST_DIR|SEARCH_DOCS|READ_CONFIG)"
    r"(?::(?P<arg>[^\]]*))?\]",
    re.IGNORECASE,
)


def execute_tools(response_text: str, config: dict) -> Optional[str]:
    """Parse and execute any tool calls in the assistant's response.

    Returns the tool results as a string to feed back, or None if
    no tools were called.
    """
    matches = list(_TOOL_PATTERN.finditer(response_text))
    if not matches:
        return None

    results = []
    for match in matches:
        tool = match.group("tool").upper()
        arg = (match.group("arg") or "").strip()

        if tool == "READ_FILE":
            results.append(_tool_read_file(arg))
        elif tool == "LIST_DIR":
            results.append(_tool_list_dir(arg))
        elif tool == "SEARCH_DOCS":
            results.append(_tool_search_docs(arg))
        elif tool == "READ_CONFIG":
            results.append(_tool_read_config(config))

    return "\n\n".join(results) if results else None


# ── Session Management ───────────────────────────────────────────────

class SetupAssistant:
    """Interactive AI assistant for the setup wizard.

    Uses the same LLM provider the user configured for the main agent.
    Maintains a simple conversation history for the wizard session.
    """

    def __init__(self, config: dict):
        """Initialize the assistant with the user's wizard config.

        Args:
            config: The wizard config dict (with API keys, provider, etc.)
        """
        self.config = config
        self._session = None
        self._history: List[Dict[str, str]] = []
        self._error: Optional[str] = None

    def is_available(self) -> bool:
        """Check if the assistant can be initialized (API key exists)."""
        provider = self.config.get("llm_provider", "gemini")
        if provider == "gemini":
            return bool(self.config.get("gemini_api_key"))
        elif provider == "anthropic":
            return bool(self.config.get("anthropic_api_key"))
        elif provider == "openai":
            return bool(self.config.get("openai_api_key"))
        elif provider == "ollama":
            return True  # Ollama doesn't need a key
        return False

    def get_error(self) -> Optional[str]:
        """Return the last error, if any."""
        return self._error

    def _ensure_session(self):
        """Lazily create the LLM session on first use."""
        if self._session is not None:
            return

        from llm.providers.base import ProviderConfig, create_session

        provider = self.config.get("llm_provider", "gemini")
        model = self.config.get("llm_model", "")

        try:
            if provider == "gemini":
                key = self.config.get("gemini_api_key", "")
                os.environ["GEMINI_API_KEY"] = key
                pc = ProviderConfig(
                    provider_type="gemini",
                    model=model or "gemini-2.5-flash",
                    context_window=1_000_000,
                    temperature=0.7,
                    max_output_tokens=2048,
                )
            elif provider == "anthropic":
                key = self.config.get("anthropic_api_key", "")
                os.environ["ANTHROPIC_API_KEY"] = key
                pc = ProviderConfig(
                    provider_type="anthropic",
                    model=model or "claude-haiku-4.5",
                    context_window=200_000,
                    temperature=0.7,
                    max_output_tokens=2048,
                )
            elif provider == "ollama":
                url = self.config.get("ollama_url", "http://localhost:11434")
                ollama_model = model or self.config.get("ollama_model", "granite4.1:8b")
                pc = ProviderConfig(
                    provider_type="ollama",
                    model=ollama_model,
                    context_window=64_000,
                    temperature=0.7,
                    max_output_tokens=2048,
                    options={"num_ctx": 64_000, "url": url},
                )
            else:
                self._error = f"Unsupported provider: {provider}"
                return

            self._session = create_session(
                config=pc,
                system_instruction=ASSISTANT_SYSTEM_PROMPT,
            )
            self._error = None
            logger.info(f"Setup assistant initialized with provider: {provider}")

        except Exception as e:
            self._error = str(e)
            logger.error(f"Failed to create assistant session: {e}")

    def send_message(self, user_message: str) -> str:
        """Send a message and return the assistant's response.

        Handles tool calls automatically — if the assistant's response
        contains tool tags, tools are executed and results are fed back
        for a second pass.

        Args:
            user_message: The user's question or message.

        Returns:
            The assistant's final text response.
        """
        self._ensure_session()
        if self._session is None:
            return (
                self._error or
                "Unable to connect to AI provider. "
                "Please check your API credentials."
            )

        try:
            # First pass
            response = self._session.send_message(user_message)

            # Check for tool calls
            tool_results = execute_tools(response, self.config)
            if tool_results:
                # Feed tool results back for a second pass
                follow_up = (
                    f"Tool results:\n\n{tool_results}\n\n"
                    "Now answer the user's question using these results. "
                    "Do NOT include tool tags in your response this time."
                )
                response = self._session.send_message(follow_up)

            # Track history for context
            self._history.append({"role": "user", "content": user_message})
            self._history.append({"role": "assistant", "content": response})

            return response

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Assistant message failed: {error_msg}")
            if "429" in error_msg:
                return "Rate limited — please wait a moment and try again."
            return f"Error: {error_msg[:200]}"

    def send_context_update(self, context: str):
        """Send a silent context update (not shown to user).

        Used when the user navigates between wizard pages to keep
        the assistant aware of the current page and entered data.
        """
        if self._session is None:
            return  # No session yet, context will be in next message

        try:
            self._session.send_message(
                f"[SYSTEM CONTEXT UPDATE — not from the user]\n{context}\n"
                "Acknowledge briefly and wait for the user's next question."
            )
        except Exception:
            pass  # Non-critical, don't surface errors for context updates
