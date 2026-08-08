"""ChatGPT-authenticated Codex CLI backend for Helix consciousness.

This is the production Codex integration.  It keeps one persistent
``codex app-server`` process and one ephemeral thread for a ChatSession.
Helix tools remain host-mediated: the model emits one schema-constrained
action envelope, then this provider validates and dispatches that action via
ToolExecutor.  This preserves the one-request-per-pulse architecture and the
preconscious grounding of tool results.

The separate ``codex_subscription`` provider intentionally remains a small
``codex exec`` transport for isolated benchmark questions.
"""

from __future__ import annotations

import json
import logging
import queue
import re
import shutil
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from llm.providers.base import ChatSession
from llm.tool_schema import to_codex_tool_catalog, validate_tool_arguments


logger = logging.getLogger("helix.llm.providers.codex_cli")

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

_TOOL_RESULT_LIMIT = 48_000


def _cap_tool_result(value: Any) -> str:
    text = value if isinstance(value, str) else str(value or "")
    if len(text) <= _TOOL_RESULT_LIMIT:
        return text
    half = _TOOL_RESULT_LIMIT // 2
    omitted = len(text) - _TOOL_RESULT_LIMIT
    return (
        text[:half]
        + f"\n\n[... {omitted} characters omitted; request a smaller range ...]\n\n"
        + text[-half:]
    )


def _parse_action_envelope(raw: str) -> Dict[str, Any]:
    """Parse a constrained final response, tolerating fenced JSON."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return {
            "response_type": "thought",
            "text": text,
            "tool_name": "",
            "tool_arguments": {},
        }
    if not isinstance(data, dict):
        raise ValueError("Codex response envelope must be a JSON object")
    response_type = data.get("response_type")
    if response_type not in {"thought", "tool_call"}:
        raise ValueError(f"Unsupported Codex response_type: {response_type!r}")
    arguments = data.get("tool_arguments", "{}")
    if isinstance(arguments, str):
        try:
            arguments = json.loads(arguments or "{}")
        except json.JSONDecodeError as exc:
            raise ValueError("Codex tool_arguments must contain JSON") from exc
    if not isinstance(arguments, dict):
        raise ValueError("Codex tool_arguments must decode to a JSON object")
    return {
        "response_type": response_type,
        "text": str(data.get("text", "")),
        "tool_name": str(data.get("tool_name", "")).strip(),
        "tool_arguments": arguments,
    }


class _AppServerTransport:
    """Minimal synchronous JSON-RPC/JSONL transport over app-server stdio."""

    def __init__(self, codex_path: str, workspace: Path):
        self._events: queue.Queue = queue.Queue()
        self._stderr_tail = deque(maxlen=80)
        self._write_lock = threading.Lock()
        self._proc = subprocess.Popen(
            [codex_path, "app-server", "--listen", "stdio://"],
            cwd=workspace,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        threading.Thread(target=self._read_stdout, daemon=True).start()
        threading.Thread(target=self._read_stderr, daemon=True).start()

    def _read_stdout(self) -> None:
        assert self._proc.stdout is not None
        for line in self._proc.stdout:
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                logger.debug("Ignoring non-JSON app-server stdout: %s", line[:300])
                continue
            if isinstance(event, dict):
                self._events.put(event)
        self._events.put({"_transport_eof": True})

    def _read_stderr(self) -> None:
        assert self._proc.stderr is not None
        for line in self._proc.stderr:
            line = line.rstrip()
            if line:
                self._stderr_tail.append(line)
                logger.debug("Codex app-server: %s", line)

    def send(self, payload: Dict[str, Any]) -> None:
        if self._proc.poll() is not None:
            raise RuntimeError(self.failure_detail())
        assert self._proc.stdin is not None
        encoded = json.dumps(payload, separators=(",", ":"))
        with self._write_lock:
            self._proc.stdin.write(encoded + "\n")
            self._proc.stdin.flush()

    def receive(self, timeout: float) -> Dict[str, Any]:
        try:
            event = self._events.get(timeout=timeout)
        except queue.Empty as exc:
            raise TimeoutError("Timed out waiting for Codex app-server") from exc
        if event.get("_transport_eof"):
            raise RuntimeError(self.failure_detail())
        return event

    def failure_detail(self) -> str:
        detail = "\n".join(self._stderr_tail)
        code = self._proc.poll()
        return f"Codex app-server stopped (exit={code}): {detail[-1600:] or 'no detail'}"

    def close(self) -> None:
        if self._proc.poll() is None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2)


class CodexCliSession(ChatSession):
    """Persistent App Server session using the local ChatGPT login."""

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
        codex_path = shutil.which("codex")
        if not codex_path:
            raise RuntimeError("The 'codex' CLI is required for HELIX_PROVIDER=codex_cli")
        self._model = (model or "").strip()
        if self._model.lower() in {"default", "account-default", "auto"}:
            self._model = ""
        self._system_instruction = system_instruction
        self._max_output_tokens = int(max_output_tokens)
        self._tool_executor = tool_executor
        self._preconscious = preconscious
        self._options = dict(options or {})
        self._timeout = float(self._options.get("timeout", 600))
        self._effort = str(self._options.get("effort", "medium"))
        self._summary = str(self._options.get("summary", "none"))
        self._history: List[Dict[str, Any]] = []
        self._history_prefix = ""
        self._last_token_count = 0
        self._tools_used: List[Dict[str, Any]] = []
        self._pending_tool_results: List[Dict[str, Any]] = []
        self._pending_model_results: List[Dict[str, Any]] = []
        self._tool_catalog = to_codex_tool_catalog(tool_declarations)
        self._tool_names = {tool["name"] for tool in self._tool_catalog}
        self._tool_schemas = {
            tool["name"]: tool["input_schema"] for tool in self._tool_catalog
        }
        self._tool_catalog_dirty = False
        self._next_id = 1
        self._responses: Dict[Any, Dict[str, Any]] = {}
        self._closed = False
        self._workspace = Path(tempfile.mkdtemp(prefix="helix_codex_app_"))

        try:
            self._transport = _AppServerTransport(codex_path, self._workspace)
            self._initialize()
            self._thread_id = self._start_thread()
        except Exception:
            self.close()
            raise
        logger.info(
            "Codex CLI session created: model=%s, tools=%d, workspace=%s",
            self._model or "account default",
            len(self._tool_catalog),
            self._workspace,
        )

    def _request(self, method: str, params: Dict[str, Any]) -> Dict[str, Any]:
        request_id = self._next_id
        self._next_id += 1
        self._transport.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self._timeout
        while True:
            cached = self._responses.pop(request_id, None)
            if cached is not None:
                event = cached
            else:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError(f"Codex {method} timed out after {self._timeout:g}s")
                event = self._transport.receive(remaining)
            if "method" in event:
                self._handle_event(event)
                continue
            if event.get("id") == request_id:
                if "error" in event:
                    raise RuntimeError(f"Codex {method} failed: {event['error']}")
                return event.get("result") or {}
            if "id" in event:
                self._responses[event["id"]] = event

    def _initialize(self) -> None:
        self._request("initialize", {
            "clientInfo": {"name": "helix-agi", "title": "Helix AGI", "version": "1"},
            "capabilities": {"experimentalApi": True},
        })
        self._transport.send({"method": "initialized", "params": {}})

    def _developer_instructions(self) -> str:
        catalog = json.dumps(self._tool_catalog, ensure_ascii=False, separators=(",", ":"))
        action_contract = (
            "For each pulse, either return internal thought text or request exactly ONE Helix "
            "host tool. The final response is constrained to a JSON object. For thought, set "
            "response_type='thought', put the thought in text, and leave tool_name empty with "
            "tool_arguments='{}'. For an action, set response_type='tool_call', identify one tool "
            "from the catalog, and put arguments matching its JSON Schema as a JSON-encoded "
            "object string in tool_arguments. Optionally put "
            "brief internal thought in text. Never print a host tool request inside text. Tool "
            "results arrive at the beginning of a later pulse.\n\n"
            f"HELIX HOST TOOL CATALOG:\n{catalog}"
            if self._tool_catalog else
            "No Helix host tools are registered for this session. Return response_type='thought' "
            "with the requested application text. Follow any application-specific textual "
            "protocol described in the system instruction."
        )
        return (
            "You are the conscious language-model substrate inside Helix AGI. "
            "The Helix system instruction supplied separately defines your identity.\n\n"
            "This thread is a conversational cognition transport, not a coding task. "
            "Do not inspect files, execute shell commands, browse, call MCP, delegate, or use "
            "Codex built-in tools. The empty read-only working directory is intentional.\n\n"
            + action_contract
        )

    def _start_thread(self) -> str:
        params: Dict[str, Any] = {
            "cwd": str(self._workspace),
            "approvalPolicy": "never",
            "sandbox": "read-only",
            "ephemeral": True,
            "serviceName": "helix-agi",
            "baseInstructions": self._system_instruction,
            "developerInstructions": self._developer_instructions(),
        }
        if self._model:
            params["model"] = self._model
        result = self._request("thread/start", params)
        thread = result.get("thread") or {}
        thread_id = str(thread.get("id", "")).strip()
        if not thread_id:
            raise RuntimeError(f"Codex thread/start returned no thread id: {result}")
        return thread_id

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

    def send_message(self, message: str) -> str:
        self._tools_used = []
        pending_results_snapshot = list(self._pending_model_results)
        history_prefix_snapshot = self._history_prefix
        catalog_dirty_snapshot = self._tool_catalog_dirty
        turn_input = self._format_turn_input(message)
        params: Dict[str, Any] = {
            "threadId": self._thread_id,
            "input": [{"type": "text", "text": turn_input}],
            "outputSchema": _ACTION_SCHEMA,
            "approvalPolicy": "never",
            "sandboxPolicy": {"type": "readOnly", "networkAccess": False},
        }
        if self._model:
            params["model"] = self._model
        if self._effort:
            params["effort"] = self._effort
        if self._summary in {"auto", "concise", "detailed", "none"}:
            params["summary"] = self._summary

        try:
            result = self._request("turn/start", params)
            turn = result.get("turn") or {}
            turn_id = str(turn.get("id", ""))
            raw_response = self._wait_for_turn(turn_id)
            envelope = _parse_action_envelope(raw_response)
        except Exception as exc:
            # The provider did not commit this local turn. Preserve queued
            # host results/catalog/history so the pulse loop can safely retry.
            self._pending_model_results = pending_results_snapshot
            self._history_prefix = history_prefix_snapshot
            self._tool_catalog_dirty = catalog_dirty_snapshot
            logger.error("Codex CLI turn failed: %s", exc)
            return f"[internal error: Codex CLI turn failed — {str(exc)[:500]}]"

        thought = envelope["text"]
        self._history.append({"role": "user", "parts": [{"text": turn_input}]})

        if envelope["response_type"] == "tool_call":
            name = envelope["tool_name"]
            args = envelope["tool_arguments"]
            if name not in self._tool_names:
                result_text = f"Unknown or inactive Helix tool: {name}"
            elif self._tool_executor is None:
                result_text = f"Tool executor not available for: {name}"
            else:
                try:
                    validate_tool_arguments(args, self._tool_schemas[name])
                    result_text = self._tool_executor.execute_function_call(name, args)
                except Exception as exc:
                    logger.warning("Helix tool rejected/failed in Codex provider %s: %s", name, exc)
                    result_text = f"Tool error ({name}): {exc}"
            result_text = _cap_tool_result(result_text)
            self._tools_used.append({"name": name, "args": args})
            record = {"name": name, "args": args, "result": result_text}
            self._pending_model_results.append(record)
            self._pending_tool_results.append(record)
            assistant_text = thought or "[tools called, results pending]"
        else:
            assistant_text = thought

        self._history.append({"role": "model", "parts": [{"text": assistant_text}]})
        return assistant_text

    def _wait_for_turn(self, turn_id: str) -> str:
        deadline = time.monotonic() + self._timeout
        final_text = ""
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"Codex turn timed out after {self._timeout:g}s")
            event = self._transport.receive(remaining)
            if "id" in event and "method" not in event:
                self._responses[event["id"]] = event
                continue
            method = event.get("method", "")
            params = event.get("params") or {}
            if method == "item/completed":
                item = params.get("item") or {}
                if item.get("type") == "agentMessage" and item.get("text"):
                    final_text = str(item["text"])
            elif method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage") or {}
                last = usage.get("last") or usage.get("total") or {}
                self._last_token_count = int(
                    last.get("inputTokens", last.get("totalTokens", 0)) or 0
                )
            elif method == "turn/completed":
                turn = params.get("turn") or {}
                if turn_id and str(turn.get("id", "")) != turn_id:
                    continue
                status = turn.get("status")
                if status != "completed":
                    raise RuntimeError(f"Codex turn {status}: {turn.get('error')}")
                if not final_text:
                    for item in turn.get("items") or []:
                        if item.get("type") == "agentMessage" and item.get("text"):
                            final_text = str(item["text"])
                if not final_text:
                    raise RuntimeError("Codex completed without an agent message")
                return final_text
            else:
                self._handle_event(event)

    def _handle_event(self, event: Dict[str, Any]) -> None:
        """Handle app-server requests that can arrive while awaiting a response."""
        method = event.get("method", "")
        request_id = event.get("id")
        params = event.get("params") or {}
        if request_id is None:
            if method == "thread/tokenUsage/updated":
                usage = params.get("tokenUsage") or {}
                last = usage.get("last") or usage.get("total") or {}
                self._last_token_count = int(
                    last.get("inputTokens", last.get("totalTokens", 0)) or 0
                )
            return

        if method == "item/tool/call":
            name = str(params.get("tool", ""))
            args = params.get("arguments") or {}
            if name in self._tool_names and self._tool_executor is not None:
                try:
                    validate_tool_arguments(args, self._tool_schemas[name])
                    value = _cap_tool_result(
                        self._tool_executor.execute_function_call(name, args)
                    )
                    success = not value.startswith(("Tool error", "Unknown tool"))
                except Exception as exc:
                    value, success = f"Tool error ({name}): {exc}", False
            else:
                value, success = f"Unknown or inactive Helix tool: {name}", False
            self._tools_used.append({"name": name, "args": args})
            self._pending_tool_results.append({"name": name, "args": args, "result": value})
            self._transport.send({
                "id": request_id,
                "result": {
                    "contentItems": [{"type": "inputText", "text": value}],
                    "success": success,
                },
            })
            return

        # Built-in Codex actions are never authoritative in this mode.
        if method == "item/permissions/requestApproval":
            self._transport.send({"id": request_id, "result": {"permissions": {}}})
        elif method == "item/tool/requestUserInput":
            self._transport.send({"id": request_id, "result": {"answers": {}}})
        elif method == "mcpServer/elicitation/request":
            self._transport.send({"id": request_id, "result": {"action": "decline"}})
        elif "approval" in method.lower():
            self._transport.send({"id": request_id, "result": {"decision": "decline"}})
        else:
            self._transport.send({
                "id": request_id,
                "error": {"code": -32601, "message": f"Unsupported request: {method}"},
            })

    def get_pending_tool_results(self) -> List[Dict[str, Any]]:
        results = self._pending_tool_results
        self._pending_tool_results = []
        return results

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
        return sum(len(json.dumps(message, ensure_ascii=False)) for message in self._history)

    def replace_history(self, compressed_history: List[Dict[str, Any]]) -> None:
        """Start a clean Codex thread and inject the compressor's summary once."""
        self._history = list(compressed_history)
        self._history_prefix = (
            "<helix_compressed_history>\n"
            + json.dumps(self._history, ensure_ascii=False)
            + "\n</helix_compressed_history>"
        )
        self._thread_id = self._start_thread()
        logger.info("Codex history replaced with %d compressed messages", len(self._history))

    def update_tool_declarations(self, declarations: Iterable[Dict[str, Any]]) -> None:
        self._tool_catalog = to_codex_tool_catalog(declarations)
        self._tool_names = {tool["name"] for tool in self._tool_catalog}
        self._tool_schemas = {
            tool["name"]: tool["input_schema"] for tool in self._tool_catalog
        }
        self._tool_catalog_dirty = True

    def update_generation_params(
        self, temperature: float = None, max_output_tokens: int = None
    ) -> None:
        # App Server exposes reasoning effort rather than sampling temperature.
        if max_output_tokens is not None:
            self._max_output_tokens = int(max_output_tokens)

    def switch_model(self, new_model: str) -> None:
        new_model = (new_model or "").strip()
        if new_model.lower() in {"default", "account-default", "auto"}:
            new_model = ""
        self._model = new_model

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        transport = getattr(self, "_transport", None)
        if transport is not None:
            transport.close()
        workspace = getattr(self, "_workspace", None)
        if workspace is not None:
            shutil.rmtree(workspace, ignore_errors=True)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
