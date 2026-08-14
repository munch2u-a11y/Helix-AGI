"""Helix — Tool Orchestration for local models

The main window holds one line per toolset and one call format. Everything
else — planning, execution, the step transcripts — happens in directed
passes that never touch it.

A request moves through three stages, all on the same local model, all
sequential so a consumer GPU never runs two generations at once:

  1. Plan       split the request into an ordered task list, one toolset
                per task. The planner sees the toolset briefs, what prior
                runs learned about the tools, and a scoped slice of Helix's
                own memory.
  2. Execute    each task runs as a directed pass in its own fresh context.
                Reports accumulate on a shared scratchpad so a later task
                can build on an earlier one.
  3. Summarize  the scratchpad is reduced to the single reply that re-enters
                the main window. Skipped when one task already produced a
                fitting report.

On memory scoping this deliberately diverges from the mRAG design it is
ported from. mRAG walls its planner off from conversational memory on the
grounds that routing needs tool facts, not user history. Helix's requests
are personally situated — "email Josh about the thing we discussed" cannot
be routed from tool facts alone — so the planner receives a scoped context
slice from the caller instead of nothing.

Nothing here is remembered. The plan, the scratchpad and the summarization
prompt are scaffolding; only the observations the passes produced are
ingested, first-person, at the originating pulse.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from core.tool_task_runner import (
    INCOMPLETE_MARKER, ToolObservation, ToolPassResult, ToolTaskRunner,
    _approx_tokens, _clamp, parse_json_action,
)

logger = logging.getLogger("helix.core.tool_orchestrator")

DEFAULT_MAX_TASKS = 4
DEFAULT_MAX_TASK_EXTENSIONS = 1
PLANNING_KNOWLEDGE_MAX_TOKENS = 150
PLANNING_CONTEXT_MAX_TOKENS = 400

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.DOTALL)

_PLAN_PROMPT = """Split this request into an ordered task list.

TOOLSETS:
{toolsets}
{knowledge}{context}
REQUEST: {request}

Rules:
- 1 to {max_tasks} tasks; each task is handled by exactly one toolset.
- A task is an OUTCOME to achieve, not a single tool operation — one task
  can take several tool calls (e.g. "fix the bug in calc.py so the tests
  pass", never "read calc.py").
- Prefer fewer, bigger tasks. Add a task only when a different toolset is needed.
- Each task must be self-contained and specific.
- Order tasks so later ones can build on earlier results.
Output only a JSON array: [{{"toolset": "<name>", "task": "<task>"}}]"""

_SUMMARY_PROMPT = """Below is what you just did across several steps. Write the single \
summary you will keep.

WHAT YOU SET OUT TO DO: {request}

WHAT HAPPENED:
{scratchpad}

Keep only what matters, keep every specific value (names, numbers, dates, \
paths) exactly, and write it in first person as your own account. Under \
{target_words} words. Output only the summary."""


def _parse_json_array(text: str) -> List[Any]:
    match = _JSON_ARRAY_RE.search(text or "")
    if not match:
        return []
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


@dataclass
class OrchestrationResult:
    """What a whole tool request produced.

    `reply` is the only part that re-enters the main window. `observations`
    is what gets ingested as memory — the actual doing.
    """

    request: str
    reply: str
    plan: List[Tuple[str, str]] = field(default_factory=list)
    observations: List[ToolObservation] = field(default_factory=list)
    complete: bool = True

    @property
    def made_calls(self) -> bool:
        return bool(self.observations)


class ToolOrchestrator:
    """Plan, execute and summarize one tool request. See module docstring."""

    def __init__(
        self,
        runner: ToolTaskRunner,
        plan_llm: Callable[[str], str],
        knowledge_provider: Optional[Callable[[List[str]], Dict[str, List[str]]]] = None,
        context_provider: Optional[Callable[[str], str]] = None,
        max_tasks: int = DEFAULT_MAX_TASKS,
        max_task_extensions: int = DEFAULT_MAX_TASK_EXTENSIONS,
    ):
        """
        Args:
            runner: Executes one task against one toolset.
            plan_llm: Callable(prompt) -> text, run in its own fresh context.
            knowledge_provider: toolset names -> {tool: [learned statements]}.
                Routing improves when the planner knows what prior runs
                discovered about a tool's real behavior.
            context_provider: request -> scoped memory block. Supplied by the
                caller so the orchestrator does not itself decide what slice
                of Helix's memory a routing decision deserves.
        """
        self.runner = runner
        self.plan_llm = plan_llm
        self._knowledge = knowledge_provider
        self._context = context_provider
        self.max_tasks = max_tasks
        self.max_task_extensions = max_task_extensions
        self.stats = {"requests": 0, "tasks_planned": 0, "summaries": 0,
                      "extensions": 0, "incomplete_tasks": 0, "last_plan": []}

    # ── Layer A ──────────────────────────────────────────────────────

    def main_window_brief(self, call_format: str = "") -> str:
        """The only tool text the main window ever holds."""
        return self.runner.registry.toolset_brief(call_format=call_format)

    # ── Pipeline ─────────────────────────────────────────────────────

    def handle(self, request: str) -> OrchestrationResult:
        request = (request or "").strip()
        if not request:
            return OrchestrationResult(
                request=request, reply="No tool request given.", complete=False,
            )

        self.stats["requests"] += 1
        tasks = self._plan(request)
        if not tasks:
            available = ", ".join(self._toolset_names())
            return OrchestrationResult(
                request=request,
                reply=f"Could not route that request against the available toolsets ({available}).",
                complete=False,
            )

        self.stats["tasks_planned"] += len(tasks)
        self.stats["last_plan"] = [f"{ts}: {task}" for ts, task in tasks]

        scratchpad: List[str] = []
        observations: List[ToolObservation] = []
        any_incomplete = False

        for index, (toolset, task) in enumerate(tasks):
            notes = "\n\n".join(scratchpad)
            result = self.runner.run(toolset, task, context_notes=notes)
            observations.extend(result.observations)

            extensions_left = self.max_task_extensions
            while not result.complete and extensions_left > 0:
                extensions_left -= 1
                self.stats["extensions"] += 1
                continuation = f"{notes}\n\n{result.report}" if notes else result.report
                result = self.runner.run(
                    toolset,
                    f"Continue this unfinished task and complete it: {task}",
                    context_notes=continuation,
                )
                observations.extend(result.observations)

            if not result.complete:
                any_incomplete = True
                self.stats["incomplete_tasks"] += 1

            scratchpad.append(
                f"[{index + 1}/{len(tasks)} {toolset}] {result.report}"
            )

        combined = "\n\n".join(scratchpad)

        # One task that finished and already fits: restating it through
        # another generation would only cost time and lose specifics.
        if len(tasks) == 1 and not any_incomplete and _approx_tokens(combined) <= self.runner.report_max_tokens:
            reply = scratchpad[0].split("] ", 1)[-1] if scratchpad else combined
        else:
            reply = self._summarize(request, combined, any_incomplete)

        return OrchestrationResult(
            request=request,
            reply=reply,
            plan=tasks,
            observations=observations,
            complete=not any_incomplete,
        )

    # ── Planning ─────────────────────────────────────────────────────

    def _toolset_names(self) -> List[str]:
        registry = self.runner.registry
        try:
            return sorted(registry._available_toolsets().keys())
        except Exception:
            return registry.get_toolset_names()

    def _plan(self, request: str) -> List[Tuple[str, str]]:
        names = self._toolset_names()
        if not names:
            return []
        if len(names) == 1:
            return [(names[0], request)]

        prompt = _PLAN_PROMPT.format(
            toolsets=self.runner.registry.toolset_brief(),
            knowledge=self._knowledge_block(names),
            context=self._context_block(request),
            request=request,
            max_tasks=self.max_tasks,
        )

        try:
            output = self.plan_llm(prompt)
        except Exception as e:
            logger.warning("Planning call failed: %s", e)
            output = ""

        tasks: List[Tuple[str, str]] = []
        for entry in _parse_json_array(output):
            if not isinstance(entry, dict):
                continue
            toolset = str(entry.get("toolset") or entry.get("group") or "").strip()
            task = str(entry.get("task", "")).strip()
            if toolset in names and task:
                tasks.append((toolset, task))

        if not tasks:
            logger.info("Planner produced no usable tasks for %r", request[:80])
        return tasks[: self.max_tasks]

    def _knowledge_block(self, names: List[str]) -> str:
        """What earlier runs learned about these tools, for routing."""
        if self._knowledge is None:
            return ""
        try:
            learned = self._knowledge(names) or {}
        except Exception as e:
            logger.debug("Knowledge provider failed: %s", e)
            return ""

        lines: List[str] = []
        spent = 0
        for tool_name, statements in learned.items():
            for statement in statements or []:
                line = f"- {tool_name}: {statement}"
                cost = _approx_tokens(line)
                if spent + cost > PLANNING_KNOWLEDGE_MAX_TOKENS:
                    break
                lines.append(line)
                spent += cost
        if not lines:
            return ""
        return "\nKNOWN TOOL BEHAVIOR (from prior runs):\n" + "\n".join(lines) + "\n"

    def _context_block(self, request: str) -> str:
        """Scoped memory the planner needs to resolve people and referents."""
        if self._context is None:
            return ""
        try:
            block = (self._context(request) or "").strip()
        except Exception as e:
            logger.debug("Context provider failed: %s", e)
            return ""
        if not block:
            return ""
        return (
            "\nWHAT YOU ALREADY KNOW THAT MAY BE RELEVANT:\n"
            + _clamp(block, PLANNING_CONTEXT_MAX_TOKENS) + "\n"
        )

    # ── Tail summary ─────────────────────────────────────────────────

    def _summarize(self, request: str, scratchpad: str, any_incomplete: bool) -> str:
        self.stats["summaries"] += 1
        target_words = int(self.runner.report_max_tokens * 0.7)
        if any_incomplete:
            request += (
                "\n(Note: at least one step did not finish — say plainly what "
                "was done and what is still outstanding.)"
            )
        prompt = _SUMMARY_PROMPT.format(
            request=request, scratchpad=scratchpad, target_words=target_words,
        )
        try:
            summary = (self.plan_llm(prompt) or "").strip()
        except Exception as e:
            logger.warning("Tail summary failed, using the raw scratchpad: %s", e)
            summary = ""
        if not summary:
            summary = scratchpad
        return _clamp(summary, self.runner.report_max_tokens)
