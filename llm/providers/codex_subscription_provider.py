"""Subscription-backed Codex chat transport for benchmark runs.

This provider deliberately shells out to the locally authenticated ``codex``
client instead of calling the OpenAI API.  It is intended for evaluation and
development runs where Codex is already signed in with ChatGPT.  It is never
auto-selected: callers must set ``HELIX_PROVIDER=codex_subscription`` or
construct the matching :class:`~llm.providers.base.ProviderConfig` explicitly.

Each ChatSession gets an isolated empty working directory and one persistent
Codex thread.  A new ChatSession therefore has no transcript memory from an
earlier benchmark question; all cross-session recall must arrive through
Helix's own preconscious injection.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

from llm.providers.base import ChatSession


logger = logging.getLogger("helix.llm.codex_subscription")


def _parse_json_stream(stdout: str) -> Tuple[Optional[str], str]:
    """Extract the thread id and latest agent message from Codex JSONL."""
    thread_id: Optional[str] = None
    last_message = ""
    for raw_line in (stdout or "").splitlines():
        try:
            event = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue

        event_type = str(event.get("type", ""))
        if event_type in {"thread.started", "thread.created"}:
            thread_id = str(
                event.get("thread_id")
                or (event.get("thread") or {}).get("id")
                or event.get("id")
                or ""
            ).strip() or thread_id

        item = event.get("item")
        if isinstance(item, dict) and item.get("type") == "agent_message":
            text = item.get("text") or item.get("content")
            if isinstance(text, str) and text.strip():
                last_message = text.strip()

        message = event.get("message")
        if event_type in {"agent_message", "message.completed"}:
            if isinstance(message, str) and message.strip():
                last_message = message.strip()
            elif isinstance(message, dict):
                text = message.get("text") or message.get("content")
                if isinstance(text, str) and text.strip():
                    last_message = text.strip()
    return thread_id, last_message


class CodexSubscriptionSession(ChatSession):
    """ChatSession implemented by ``codex exec`` / ``codex exec resume``."""

    def __init__(
        self,
        model: str,
        system_instruction: str,
        max_output_tokens: int = 2048,
        options: Optional[dict] = None,
    ):
        if not shutil.which("codex"):
            raise RuntimeError("The 'codex' CLI is required for codex_subscription.")
        self.model = (model or "").strip()
        self.system_instruction = system_instruction.strip()
        self.max_output_tokens = max_output_tokens
        self.options = dict(options or {})
        self.timeout = int(self.options.get("timeout", 600))
        self.thread_id: Optional[str] = None
        self._history_chars = 0
        self._turn = 0
        self._workspace = Path(tempfile.mkdtemp(prefix="helix_codex_chat_"))

    def send_message(self, message: str) -> str:
        self._turn += 1
        self._history_chars += len(message)
        response_path = self._workspace / f"response_{self._turn:03d}.txt"

        if self.thread_id:
            args = [
                "codex", "exec", "resume", "--json",
                "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
            ]
            if self.model:
                args.extend(["--model", self.model])
            args.extend(["--output-last-message", str(response_path), self.thread_id, "-"])
            prompt = message
        else:
            args = [
                "codex", "exec", "--json", "--sandbox", "read-only",
                "--skip-git-repo-check", "--ignore-user-config", "--ignore-rules",
                "--cd", str(self._workspace),
            ]
            if self.model:
                args.extend(["--model", self.model])
            args.extend(["--output-last-message", str(response_path), "-"])
            prompt = "\n\n".join([
                "# Role and response contract",
                self.system_instruction,
                "Do not inspect files or run tools. Answer only the supplied conversational turn.",
                "# Current turn",
                message,
            ])

        try:
            proc = subprocess.run(
                args,
                input=prompt,
                text=True,
                capture_output=True,
                timeout=self.timeout,
                cwd=self._workspace,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"Codex subscription turn timed out after {self.timeout}s"
            ) from exc

        parsed_thread_id, streamed_message = _parse_json_stream(proc.stdout)
        if parsed_thread_id:
            self.thread_id = parsed_thread_id

        final_message = ""
        if response_path.exists():
            final_message = response_path.read_text(encoding="utf-8").strip()
        if not final_message:
            final_message = streamed_message.strip()

        if proc.returncode != 0 or not final_message:
            detail = (proc.stderr or proc.stdout or "no output").strip()[-1200:]
            raise RuntimeError(
                f"Codex subscription turn failed (exit={proc.returncode}): {detail}"
            )
        if not self.thread_id:
            logger.warning("Codex returned a response without a reusable thread id")

        self._history_chars += len(final_message)
        return final_message

    def get_history_size(self) -> int:
        return self._history_chars

    def close(self) -> None:
        if self._workspace.exists():
            shutil.rmtree(self._workspace, ignore_errors=True)

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass
