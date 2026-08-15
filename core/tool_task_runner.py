"""Helix — Directed Tool Passes

One task, one toolset, one fresh context. The model is given that toolset's
full manifest (Layer B) and an objective, then works step by step until it
has an answer or runs out of budget.

This is not a second agent. It is Helix under a task frame — the same
weights, briefly steered. The frame is scaffolding: the manifest, the step
prompts and the loop mechanics are never written to memory. What survives a
pass is what Helix did and what came back, which the caller ingests
first-person at the originating pulse. In hindsight there was no pass; there
was only the work.

Two enforcement levels, by provider:

  llama.cpp  the decoding grammar is narrowed to this toolset, so a call to
             anything outside it cannot be generated at all.
  Ollama     no logit hook exists, so the manifest carries the restriction
             and this module refuses to dispatch a name outside the group.

Both paths end at the same place: a name outside the toolset never runs.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from core.action_protocol import (
    ToolReceipt,
    VerificationStatus,
    clarification_question,
    classify_tool_result,
    verify_receipts,
)
from llm.constrained_decoding import parse_action_tags, strip_action_tags

logger = logging.getLogger("helix.core.tool_task_runner")

DEFAULT_MAX_STEPS = 10
DEFAULT_REPORT_MAX_TOKENS = 800
DEFAULT_OBSERVATION_TOKENS = 600
DEFAULT_CONTEXT_NOTES_TOKENS = 900
DEFAULT_TASK_TOKENS = 300
DEFAULT_SUCCESS_CHECK_TOKENS = 120

# Prefix on a report whose task ran out of steps. The orchestrator's
# extension policy keys off this, so it must stay stable.
INCOMPLETE_MARKER = "INCOMPLETE"

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def _approx_tokens(text: str) -> int:
    """Cheap token estimate. Exact counts are not worth a tokenizer load
    here — every use is a budget clamp, not an accounting figure."""
    try:
        from memory.mrag.token_counting import count_text_tokens
        return count_text_tokens(text)
    except Exception:
        return max(1, len(text or "") // 4)


def _clamp(text: str, max_tokens: int) -> str:
    text = text or ""
    if _approx_tokens(text) <= max_tokens:
        return text
    keep = max_tokens * 4
    return text[:keep].rstrip() + "\n[...truncated...]"


def parse_json_action(text: str) -> Optional[Dict[str, Any]]:
    """Best-effort extraction of one JSON object from model output.

    Small models rarely emit clean bare JSON — there is usually a code
    fence or a sentence of preamble around it.
    """
    match = _JSON_BLOCK_RE.search(text or "")
    if not match:
        return None
    candidate = match.group(0)
    depth = 0
    for index, char in enumerate(candidate):
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                candidate = candidate[: index + 1]
                break
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


@dataclass
class ToolObservation:
    """One executed call and what it returned, kept whole for ingest."""

    tool: str
    args: Dict[str, Any]
    result: str
    ok: bool = True
    receipt: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolPassResult:
    toolset: str
    task: str
    report: str
    complete: bool = True
    steps: int = 0
    observations: List[ToolObservation] = field(default_factory=list)
    receipts: List[ToolReceipt] = field(default_factory=list)
    verification: Dict[str, Any] = field(default_factory=dict)
    question: str = ""
    frame_tokens: int = 0
    evidence_tokens: int = 0
    model_input_tokens: int = 0
    model_tokens: int = 0

    @property
    def made_calls(self) -> bool:
        return bool(self.observations)


_GRAMMAR_FORM = (
    "Respond with EXACTLY ONE tool call, in this exact form:\n"
    "{[(( tool_name(argument=\"value\") ))]}"
)

_JSON_FORM = (
    "Respond with EXACTLY ONE tool call, as a single JSON object:\n"
    '{"tool": "tool_name", "args": {"argument": "value"}}'
)

_FRAME = """{manifest}

You are completing one task using only the tools above.

{call_form}

You will be given each result in turn. Keep going until the task is done,
then reply with a short plain-text report — no tool call — describing what
you did and what you found. Copy every specific value (names, numbers,
paths, dates) exactly as it was returned to you.

Completion evidence: {success_check}

If a material target, recipient, content, choice, or authorization is missing
or ambiguous, do not guess and do not call a tool. Reply exactly:
NEED_INPUT: <one concise question>

A plain-text report is not evidence. For file, browser, or desktop changes,
use a later read or observation to confirm the resulting state before your
report. If a call fails, repair its arguments or use a safe alternative."""


class ToolTaskRunner:
    """Runs one task against one toolset in a fresh context."""

    def __init__(
        self,
        registry,
        tool_executor,
        pass_factory: Callable[[str], Any],
        grammar_constrained: bool = False,
        max_steps: int = DEFAULT_MAX_STEPS,
        report_max_tokens: int = DEFAULT_REPORT_MAX_TOKENS,
        observation_tokens: int = DEFAULT_OBSERVATION_TOKENS,
        context_notes_tokens: int = DEFAULT_CONTEXT_NOTES_TOKENS,
        task_tokens: int = DEFAULT_TASK_TOKENS,
        success_check_tokens: int = DEFAULT_SUCCESS_CHECK_TOKENS,
        progress_callback: Optional[Callable[[str], None]] = None,
    ):
        self.registry = registry
        self.executor = tool_executor
        self.pass_factory = pass_factory
        self.grammar_constrained = grammar_constrained
        self.max_steps = max_steps
        self.report_max_tokens = report_max_tokens
        self.observation_tokens = observation_tokens
        self.context_notes_tokens = context_notes_tokens
        self.task_tokens = task_tokens
        self.success_check_tokens = success_check_tokens
        self.progress_callback = progress_callback
        self.stats = {"runs": 0, "tool_calls": 0, "rejected": 0,
                      "recovered": 0, "incomplete": 0, "last_toolset": None,
                      "input_tokens": 0, "evidence_tokens": 0,
                      "max_frame_tokens": 0, "model_tokens": 0}

    # ── Framing ──────────────────────────────────────────────────────

    def _system_prompt(self, toolset: str, success_check: str = "") -> str:
        manifest = self.registry.toolset_manifest(toolset)
        call_form = _GRAMMAR_FORM if self.grammar_constrained else _JSON_FORM
        return _FRAME.format(
            manifest=manifest,
            call_form=call_form,
            success_check=_clamp(
                success_check or "A successful tool receipt proves the requested outcome.",
                self.success_check_tokens,
            ),
        )

    def _parse_action(self, output: str):
        """Return (tool_name, args) or None when the output is a report."""
        tagged = parse_action_tags(output)
        if tagged:
            return tagged[0]

        action = parse_json_action(output)
        if action and "tool" in action:
            args = action.get("args")
            return str(action["tool"]), (args if isinstance(args, dict) else {})
        return None

    def _report_text(self, output: str) -> str:
        return strip_action_tags(output).strip()

    @staticmethod
    def _resolve_name(name: str, allowed: set) -> Optional[str]:
        """Map a model-emitted name onto a real tool *within this toolset*.

        Small models produce near-misses — `send_email` for `email_send`,
        `web_search` for `search`. Helix already carries this recovery for
        its URI-primitive path (ToolDispatcher._fuzzy_match_tool); the same
        forgiveness applies here, but scoped to the group, so a fuzzy match
        can never resolve to a tool outside the manifest the model was given.
        """
        if name in allowed:
            return name

        def norm(value: str) -> str:
            return value.lower().replace("_", "").replace("-", "")

        target = norm(name)
        if not target:
            return None

        exact = [c for c in allowed if norm(c) == target]
        if len(exact) == 1:
            return exact[0]

        partial = [
            c for c in allowed
            if target in norm(c) or norm(c) in target
        ]
        if len(partial) == 1:
            return partial[0]
        return None

    def _progress(self, message: str) -> None:
        if self.progress_callback is None:
            return
        try:
            self.progress_callback(message)
        except Exception:
            logger.debug("Progress callback failed", exc_info=True)

    # ── Execution ────────────────────────────────────────────────────

    def run(
        self,
        toolset: str,
        task: str,
        context_notes: str = "",
        success_check: str = "",
    ) -> ToolPassResult:
        task = _clamp((task or "").strip(), self.task_tokens)
        allowed = set(self.registry.toolset_tool_names(toolset))
        if not allowed:
            return ToolPassResult(
                toolset=toolset,
                task=task,
                report=f"No tools available in '{toolset}'.",
                complete=False,
            )

        self.stats["runs"] += 1
        self.stats["last_toolset"] = toolset

        observations: List[ToolObservation] = []
        receipts: List[ToolReceipt] = []
        report = ""
        complete = False
        steps = 0
        question = ""
        evidence_tokens = 0
        model_input_tokens = 0
        model_tokens = 0

        system_prompt = self._system_prompt(toolset, success_check)
        tool_pass = self.pass_factory(system_prompt)
        try:
            tool_pass.scope_tools(sorted(allowed))

            message = task
            if context_notes:
                message = (
                    "Results from earlier steps:\n"
                    f"{_clamp(context_notes, self.context_notes_tokens)}\n\n"
                    f"Your task: {task}"
                )
            frame_tokens = _approx_tokens(system_prompt + "\n" + message)
            self.stats["max_frame_tokens"] = max(
                self.stats["max_frame_tokens"], frame_tokens
            )

            for steps in range(1, self.max_steps + 1):
                try:
                    model_input_tokens += _approx_tokens(system_prompt + "\n" + message)
                    output = tool_pass.send(message)
                    try:
                        model_tokens += int(tool_pass.get_last_token_count() or 0)
                    except Exception:
                        pass
                except Exception as e:
                    logger.error("Tool pass generation failed: %s", e)
                    report = f"Generation failed during '{task}': {e}"
                    break

                action = self._parse_action(output)
                if action is None:
                    report = self._report_text(output)
                    question = clarification_question(report)
                    if question:
                        break
                    verification = verify_receipts(receipts)
                    if verification.verified:
                        complete = True
                        break
                    if steps < self.max_steps:
                        message = (
                            "Your report does not yet have sufficient tool evidence: "
                            + " ".join(verification.reasons)[:900]
                            + "\nUse a tool to do or independently confirm the task, "
                            "or reply NEED_INPUT: with the one missing input."
                        )
                        continue
                    break

                requested, args = action
                tool_name = self._resolve_name(requested, allowed)

                if tool_name is None:
                    # Reachable on Ollama, where nothing constrains decoding.
                    self.stats["rejected"] += 1
                    logger.info(
                        "Rejected out-of-group tool %s in toolset %s",
                        requested, toolset,
                    )
                    message = (
                        f"'{requested}' is not in this toolset. "
                        f"Use one of: {', '.join(sorted(allowed))}."
                    )
                    continue

                if tool_name != requested:
                    self.stats["recovered"] += 1
                    logger.debug(
                        "Recovered near-miss tool name %s -> %s", requested, tool_name,
                    )

                self._progress(f"[{toolset}] step {steps}/{self.max_steps}: {tool_name}")
                receipt_method = getattr(
                    self.executor, "execute_function_call_receipt", None
                )
                if receipt_method is not None:
                    try:
                        receipt = ToolReceipt.from_dict(
                            receipt_method(tool_name, args)
                        )
                        result = receipt.result
                    except Exception as exc:
                        result = f"Tool error ({tool_name}): {exc}"
                        receipt = classify_tool_result(tool_name, args, result)
                else:
                    result = self.executor.execute_function_call(tool_name, args) or ""
                    receipt = classify_tool_result(tool_name, args, result)
                self.stats["tool_calls"] += 1
                receipts.append(receipt)
                observations.append(
                    ToolObservation(
                        tool=tool_name,
                        args=args,
                        result=result,
                        ok=receipt.ok,
                        receipt=receipt.to_dict(),
                    )
                )

                # The model sees a clamped result; the whole thing stays on
                # the observation for first-person ingest.
                clamped_result = _clamp(result, self.observation_tokens)
                evidence_tokens += _approx_tokens(clamped_result)
                if not receipt.ok:
                    message = (
                        f"The {tool_name} attempt failed or was blocked:\n"
                        f"{clamped_result}\n\n"
                        "Repair the arguments, use a safe alternative in this toolset, "
                        "or reply NEED_INPUT: with the one required question."
                    )
                else:
                    verification = verify_receipts(receipts)
                    next_step = (
                        "The receipts now verify the task; give the concise final report."
                        if verification.verified
                        else "Continue with the independent observation needed to verify it."
                    )
                    message = (
                        f"Result of {tool_name}:\n"
                        f"{clamped_result}\n\n{next_step}"
                    )
            else:
                complete = False
        finally:
            try:
                tool_pass.close()
            except Exception:
                logger.debug("Tool pass close failed", exc_info=True)

        verification = verify_receipts(receipts)
        complete = bool(complete and verification.verified and not question)

        if not report:
            # Budget exhausted with no closing report — say so honestly
            # rather than presenting partial work as finished.
            complete = False
            done = "; ".join(
                f"{o.tool}: {_clamp(o.result, 60)}" for o in observations
            ) or "nothing completed"
            report = f"{INCOMPLETE_MARKER}: ran out of steps on '{task}'. So far — {done}"
        elif not complete and not question and not report.startswith(INCOMPLETE_MARKER):
            reason = " ".join(verification.reasons) or "completion was not verified"
            report = f"{INCOMPLETE_MARKER}: {reason} Reported so far: {report}"

        if not complete:
            self.stats["incomplete"] += 1
        self.stats["input_tokens"] += model_input_tokens
        self.stats["evidence_tokens"] += evidence_tokens
        self.stats["model_tokens"] += model_tokens

        return ToolPassResult(
            toolset=toolset,
            task=task,
            report=_clamp(report, self.report_max_tokens),
            complete=complete,
            steps=steps,
            observations=observations,
            receipts=receipts,
            verification=verification.to_dict(),
            question=question,
            frame_tokens=frame_tokens,
            evidence_tokens=evidence_tokens,
            model_input_tokens=model_input_tokens,
            model_tokens=model_tokens,
        )
