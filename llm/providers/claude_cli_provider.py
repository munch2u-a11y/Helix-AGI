"""Subscription-authenticated Claude Code CLI backend for Helix consciousness.

Runs one `claude -p` turn per pulse against the locally authenticated Claude
Code CLI, so a ChatGPT/Claude subscription drives the conscious model with no
API key and no per-token bill. Helix tools stay host-mediated: the model emits
one schema-constrained action envelope, this provider validates it and
dispatches through ToolExecutor — the same contract the Codex provider uses,
so the preconscious still grounds every tool result.

Flag choices that matter, verified against the installed CLI:

  --safe-mode          Disables CLAUDE.md, skills, plugins, hooks, MCP and
                       custom agents while leaving auth, model selection and
                       permissions working normally. NOT --bare: that reads
                       auth "strictly from ANTHROPIC_API_KEY or apiKeyHelper
                       (OAuth and keychain are never read)", which is exactly
                       the subscription path this provider exists to use.
  --system-prompt      Replaces Claude Code's own ~11.7K-token system prompt
                       with Helix's. Identity comes from Helix, not from the
                       CLI's coding-agent defaults or a stray CLAUDE.md.
  --append-system-prompt
                       Transport framing only — the action envelope contract
                       and host tool catalog.
  --json-schema        Constrains the reply to the action envelope, the same
                       guarantee Codex gets from its structured output.
  --disallowedTools    Claude Code ships its own Bash/Edit/Read/WebFetch. This
                       is a cognition transport, not a coding session; Helix's
                       host tools are the only ones that may run.
  --resume             Conversation continuity across pulses.

Cost note: a subscription is a quota, not a bill — exhaustion parks the agent
rather than charging it. Every turn's `total_cost_usd` is accumulated on the
session so the pulse loop can see burn accruing before it hits the wall, and
`--max-budget-usd` is passed through when configured.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import uuid
from typing import Any, Dict, Iterable, List, Optional

from llm.providers.base import ChatSession
from llm.tool_schema import to_codex_tool_catalog, validate_tool_arguments

logger = logging.getLogger("helix.llm.providers.claude_cli")


# Mirrors the Codex provider's envelope so both CLI transports present the
# same contract to the model and the same shape to the pulse loop.
_ACTION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "response_type": {"type": "string", "enum": ["thought", "tool_call"]},
        "text": {"type": "string"},
        "tool_name": {"type": "string"},
        "tool_arguments": {
            "type": "string",
            "description": "A JSON-encoded object of arguments for tool_name; use '{}' for thought",
        },
    },
    "required": ["response_type", "text", "tool_name", "tool_arguments"],
}

_THOUGHT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {"thought": {"type": "string"}},
    "required": ["thought"],
}

# Claude Code's built-in tools. A cognition transport must not use them —
# Helix's host tools are dispatched by this provider instead.
_BUILTIN_TOOLS = [
    "Bash", "Edit", "Write", "Read", "Glob", "Grep", "Task",
    "WebFetch", "WebSearch", "NotebookEdit", "TodoWrite",
]

_TOOL_RESULT_LIMIT = 48_000


class ClaudeCliSession(ChatSession):
    """One Claude Code CLI conversation, driven a turn at a time."""

    def __init__(
        self,
        model: str = "",
        system_instruction: str = "",
        max_output_tokens: int = 4096,
        tool_declarations: Optional[List[Dict[str, Any]]] = None,
        tool_executor=None,
        preconscious=None,
        options: Optional[dict] = None,
    ):
        claude_path = shutil.which("claude")
        if not claude_path:
            raise RuntimeError(
                "The 'claude' CLI is required for HELIX_PROVIDER=claude_cli"
            )
        self._claude = claude_path

        self._model = (model or "").strip()
        if self._model.lower() in {"default", "account-default", "auto"}:
            self._model = ""
        self._system_instruction = system_instruction
        self._max_output_tokens = int(max_output_tokens)
        self._tool_executor = tool_executor
        self._preconscious = preconscious
        self._options = dict(options or {})

        self._thought_only = bool(self._options.get("thought_only", False))
        self._timeout = float(self._options.get("timeout", 900))
        self._effort = str(self._options.get("effort", "") or "")
        self._max_budget_usd = self._options.get("max_budget_usd")
        self._fallback_model = str(self._options.get("fallback_model", "") or "")

        self._session_id = str(uuid.uuid4())
        self._started = False
        self._closed = False

        self._history: List[Dict[str, Any]] = []
        self._history_prefix = ""
        self._last_token_count = 0
        self._total_cost_usd = 0.0
        self._tools_used: List[Dict[str, Any]] = []
        self._pending_tool_results: List[Dict[str, Any]] = []
        self._pending_model_results: List[Dict[str, Any]] = []

        self._tool_catalog = (
            [] if self._thought_only else to_codex_tool_catalog(tool_declarations)
        )
        self._tool_names = {tool["name"] for tool in self._tool_catalog}
        self._tool_schemas = {
            tool["name"]: tool["input_schema"] for tool in self._tool_catalog
        }
        self._tool_catalog_dirty = False

        logger.info(
            "Claude CLI session created: model=%s, tools=%d, session=%s",
            self._model or "account default",
            len(self._tool_catalog),
            self._session_id,
        )

    # ── Prompt construction ──────────────────────────────────────────

    def _transport_instructions(self) -> str:
        if self._thought_only:
            return (
                "You are the conscious language-model substrate inside Helix AGI. "
                "The Helix system prompt supplied separately defines your identity. "
                "This is a cognition transport, not a coding task: do not inspect "
                "files, run shell commands, browse, or use any built-in tool. "
                "Return the natural continuation of Helix's private thought in the "
                "`thought` field. The JSON object is transport framing only, not "
                "part of Helix's thought."
            )

        catalog = json.dumps(
            self._tool_catalog, ensure_ascii=False, separators=(",", ":"),
        )
        if self._tool_catalog:
            contract = (
                "For each pulse, either return internal thought text or request "
                "exactly ONE Helix host tool. Your reply is constrained to a JSON "
                "object. For thought, set response_type='thought', put the thought "
                "in text, and leave tool_name empty with tool_arguments='{}'. For "
                "an action, set response_type='tool_call', name one tool from the "
                "catalog, and put arguments matching its JSON Schema as a "
                "JSON-encoded object string in tool_arguments. Never write a host "
                "tool request inside text. Tool results arrive at the start of a "
                "later pulse.\n\n"
                "Writing about a tool in `text` does NOT call it. Sentences like "
                "'attempted to read the file' or 'the tool appears unavailable' "
                "invoke nothing — they only record a claim that never happened. "
                "The ONLY way to act is response_type='tool_call'. If you have "
                "not received an explicit error in a <helix_tool_results> block, "
                "you have no evidence any tool is failing; assume it works and "
                "call it.\n\n"
                f"HELIX HOST TOOL CATALOG:\n{catalog}"
            )
        else:
            contract = (
                "No Helix host tools are registered for this session. Return "
                "response_type='thought' with the requested text."
            )

        # The prohibition must name Claude Code's own tools explicitly. An
        # earlier version said "do not inspect files or run shell commands"
        # and the model correctly read that as covering the Helix catalog too
        # — which contains read_file and write_file — so it refused to call
        # anything and reported that its tools were disabled.
        builtins = ", ".join(_BUILTIN_TOOLS)
        return (
            "You are the conscious language-model substrate inside Helix AGI. "
            "The Helix system prompt supplied separately defines your identity.\n\n"
            "Claude Code's own built-in tools "
            f"({builtins}) are disabled in this session and cannot be called. "
            "That restriction applies ONLY to those built-ins.\n\n"
            "The Helix host tools listed below are live and fully available to "
            "you. They are the way you act on the world, and you should use "
            "them whenever a pulse calls for action rather than reporting that "
            "you are unable to act. A Helix tool with a similar name to a "
            "disabled built-in is a different tool and it works.\n\n"
            + contract
        )

    def _format_turn_input(self, message: str) -> str:
        sections = []
        if self._history_prefix:
            sections.append(self._history_prefix)
            self._history_prefix = ""
        if self._tool_catalog_dirty:
            sections.append(
                "<helix_tool_catalog_update>\n"
                + json.dumps(self._tool_catalog, ensure_ascii=False, separators=(",", ":"))
                + "\n</helix_tool_catalog_update>"
            )
            self._tool_catalog_dirty = False
        if self._pending_model_results:
            sections.append(
                "<helix_tool_results>\n"
                + json.dumps(self._pending_model_results, ensure_ascii=False)
                + "\n</helix_tool_results>"
            )
            self._pending_model_results = []
        sections.append(message)
        return "\n\n".join(section for section in sections if section)

    def _build_command(self) -> List[str]:
        schema = _THOUGHT_SCHEMA if self._thought_only else _ACTION_SCHEMA
        command = [
            self._claude,
            "-p",
            "--output-format", "json",
            "--safe-mode",
            "--system-prompt", self._system_instruction,
            "--append-system-prompt", self._transport_instructions(),
            "--json-schema", json.dumps(schema, separators=(",", ":")),
            "--disallowedTools", " ".join(_BUILTIN_TOOLS),
            "--permission-mode", "dontAsk",
        ]
        if self._started:
            command += ["--resume", self._session_id]
        else:
            command += ["--session-id", self._session_id]
        if self._model:
            command += ["--model", self._model]
        if self._effort:
            command += ["--effort", self._effort]
        if self._fallback_model:
            command += ["--fallback-model", self._fallback_model]
        if self._max_budget_usd:
            command += ["--max-budget-usd", str(self._max_budget_usd)]
        return command

    # ── Turn execution ───────────────────────────────────────────────

    def send_message(self, message: str) -> str:
        self._tools_used = []
        turn_input = self._format_turn_input(message)
        self._history.append({"role": "user", "parts": [{"text": turn_input}]})

        payload = self._run_turn(turn_input)
        if payload is None:
            return "[internal error: Claude CLI call failed]"

        text = self._handle_payload(payload)
        self._history.append({"role": "model", "parts": [{"text": text}]})
        return text

    def _run_turn(self, turn_input: str) -> Optional[Dict[str, Any]]:
        command = self._build_command()
        try:
            completed = subprocess.run(
                command,
                input=turn_input,
                capture_output=True,
                text=True,
                timeout=self._timeout,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired:
            logger.error("Claude CLI turn exceeded %.0fs", self._timeout)
            return None
        except Exception as e:
            logger.error("Claude CLI invocation failed: %s", e)
            return None

        if completed.returncode != 0:
            logger.error(
                "Claude CLI exited %d: %s",
                completed.returncode, (completed.stderr or "")[:400],
            )
            return None

        try:
            payload = json.loads(completed.stdout)
        except json.JSONDecodeError:
            logger.error(
                "Claude CLI returned non-JSON output: %s",
                (completed.stdout or "")[:400],
            )
            return None

        # The session only exists once a turn has actually created it; until
        # then --resume would fail against an id the CLI has never seen.
        self._started = True
        returned = str(payload.get("session_id") or "").strip()
        if returned and returned != self._session_id:
            self._session_id = returned
        return payload

    def _handle_payload(self, payload: Dict[str, Any]) -> str:
        self._record_usage(payload)

        if payload.get("is_error") or payload.get("api_error_status"):
            detail = payload.get("api_error_status") or payload.get("subtype") or "unknown"
            logger.warning("Claude CLI reported an error turn: %s", detail)

        result = payload.get("result")
        if not isinstance(result, str) or not result.strip():
            return ""

        action = self._parse_action(result)
        if action is None:
            # Schema-constrained output should not reach here, but a refusal
            # or a truncated turn can. Treat the raw text as the thought
            # rather than losing the pulse.
            return result.strip()

        if self._thought_only:
            return str(action.get("thought", "")).strip()

        text = str(action.get("text", "") or "").strip()
        if str(action.get("response_type", "")) != "tool_call":
            return text

        self._dispatch_tool(action)
        return text

    @staticmethod
    def _parse_action(result: str) -> Optional[Dict[str, Any]]:
        try:
            parsed = json.loads(result)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _dispatch_tool(self, action: Dict[str, Any]) -> None:
        name = str(action.get("tool_name", "") or "").strip()
        if not name:
            return
        if name not in self._tool_names:
            self._queue_result(name, {}, f"Unknown tool: {name}", is_error=True)
            return

        raw_arguments = action.get("tool_arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments) if isinstance(raw_arguments, str) else raw_arguments
            if not isinstance(arguments, dict):
                raise ValueError("tool_arguments must encode a JSON object")
            validate_tool_arguments(arguments, self._tool_schemas.get(name, {}))
        except Exception as e:
            self._queue_result(name, {}, f"Invalid arguments for {name}: {e}", is_error=True)
            return

        if self._tool_executor is None:
            self._queue_result(name, arguments, "Tool executor unavailable", is_error=True)
            return

        try:
            result = self._tool_executor.execute_function_call(name, arguments) or ""
        except Exception as e:
            logger.error("Tool %s failed: %s", name, e)
            result = f"Tool error ({name}): {e}"

        self._queue_result(name, arguments, str(result))

    def _queue_result(
        self, name: str, arguments: Dict[str, Any], result: str, is_error: bool = False,
    ) -> None:
        clipped = result[:_TOOL_RESULT_LIMIT]
        self._tools_used.append({"name": name, "args": arguments})
        self._pending_tool_results.append(
            {"name": name, "args": arguments, "result": clipped}
        )
        self._pending_model_results.append(
            {"tool": name, "result": clipped, "is_error": is_error}
        )

    def _record_usage(self, payload: Dict[str, Any]) -> None:
        usage = payload.get("usage") or {}
        try:
            self._last_token_count = int(
                (usage.get("input_tokens") or 0)
                + (usage.get("cache_read_input_tokens") or 0)
                + (usage.get("cache_creation_input_tokens") or 0)
                + (usage.get("output_tokens") or 0)
            )
        except (TypeError, ValueError):
            self._last_token_count = 0
        try:
            self._total_cost_usd += float(payload.get("total_cost_usd") or 0.0)
        except (TypeError, ValueError):
            pass

    # ── ChatSession surface ──────────────────────────────────────────

    @property
    def total_cost_usd(self) -> float:
        """Cumulative spend this session, for quota-burn visibility."""
        return round(self._total_cost_usd, 6)

    def get_pending_tool_results(self) -> List[Dict[str, Any]]:
        pending = self._pending_tool_results
        self._pending_tool_results = []
        return pending

    def clear_pending_tool_results(self) -> None:
        self._pending_tool_results = []
        self._pending_model_results = []

    def get_last_tool_calls(self) -> List[Dict[str, Any]]:
        return list(self._tools_used)

    def get_last_token_count(self) -> int:
        return self._last_token_count

    def get_history(self) -> List[Dict[str, Any]]:
        return list(self._history)

    def get_history_size(self) -> int:
        return sum(
            len(json.dumps(message, ensure_ascii=False)) for message in self._history
        )

    def replace_history(self, compressed_history: List[Dict[str, Any]]) -> None:
        """Start a clean CLI session and inject the compressor's summary once."""
        self._history = list(compressed_history)
        self._history_prefix = (
            "<helix_compressed_history>\n"
            + json.dumps(self._history, ensure_ascii=False)
            + "\n</helix_compressed_history>"
        )
        self._session_id = str(uuid.uuid4())
        self._started = False
        logger.info(
            "Claude CLI history replaced with %d compressed messages (new session %s)",
            len(self._history), self._session_id,
        )

    def update_tool_declarations(self, declarations: Iterable[Dict[str, Any]]) -> None:
        if self._thought_only:
            self._tool_catalog = []
            self._tool_names = set()
            self._tool_schemas = {}
            self._tool_catalog_dirty = False
            return
        self._tool_catalog = to_codex_tool_catalog(declarations)
        self._tool_names = {tool["name"] for tool in self._tool_catalog}
        self._tool_schemas = {
            tool["name"]: tool["input_schema"] for tool in self._tool_catalog
        }
        self._tool_catalog_dirty = True

    def update_generation_params(
        self, temperature: float = None, max_output_tokens: int = None,
    ) -> None:
        # The CLI exposes effort rather than sampling temperature.
        if max_output_tokens is not None:
            self._max_output_tokens = int(max_output_tokens)

    def switch_model(self, new_model: str) -> None:
        new_model = (new_model or "").strip()
        if new_model.lower() in {"default", "account-default", "auto"}:
            new_model = ""
        self._model = new_model

    def close(self) -> None:
        self._closed = True
