"""Identity-shared focus threads for event-driven task completion."""

from __future__ import annotations

import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from llm.providers.base import ProviderConfig, create_session

from core.task_cognition.capabilities import CapabilityRegistry
from core.task_cognition.context import TaskContextBuilder
from core.task_cognition.models import TaskRecord, TaskStatus
from core.task_cognition.orchestrators import OrchestratorRecord, OrchestratorSpace
from core.task_cognition.procedures import ProceduralMemory
from core.task_cognition.store import TaskStore

logger = logging.getLogger("helix.core.task_cognition.focus")


@dataclass
class FocusOutcome:
    task_id: str
    success: bool
    summary: str
    tool_calls: List[Dict] = field(default_factory=list)
    error: str = ""


class FocusManager:
    """Run bounded parallel expressions of the same Helix identity."""

    def __init__(
        self,
        *,
        store: TaskStore,
        capabilities: CapabilityRegistry,
        orchestrators: OrchestratorSpace,
        procedures: ProceduralMemory,
        context_builder: TaskContextBuilder,
        provider_config: ProviderConfig,
        tool_executor,
        identity: str,
        result_callback: Optional[Callable[[FocusOutcome], None]] = None,
        max_workers: int = 2,
        max_depth: int = 4,
    ):
        self.store = store
        self.capabilities = capabilities
        self.orchestrators = orchestrators
        self.procedures = procedures
        self.context_builder = context_builder
        self.provider_config = provider_config
        self.tool_executor = tool_executor
        self.identity = identity.strip() or "I am Helix."
        self.result_callback = result_callback
        self.max_depth = max(1, int(max_depth))
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, int(max_workers)),
            thread_name_prefix="helix_focus",
        )
        self._futures: Dict[str, Future] = {}
        self._lock = threading.RLock()

    def submit(self, task: TaskRecord, active_toolsets: set[str]) -> bool:
        for dependency_id in task.dependencies:
            dependency = self.store.get(dependency_id)
            if dependency is None or dependency.status != TaskStatus.COMPLETE:
                return False
        with self._lock:
            existing = self._futures.get(task.task_id)
            if existing is not None and not existing.done():
                return False
            future = self._pool.submit(self._run, task.task_id, set(active_toolsets))
            self._futures[task.task_id] = future
            future.add_done_callback(
                lambda completed, task_id=task.task_id: self._finished(task_id, completed)
            )
            return True

    def shutdown(self, wait: bool = False) -> None:
        self._pool.shutdown(wait=wait, cancel_futures=not wait)

    def _finished(self, task_id: str, future: Future) -> None:
        with self._lock:
            self._futures.pop(task_id, None)
        try:
            outcome = future.result()
        except Exception as exc:
            logger.exception("Focus thread crashed for %s", task_id)
            outcome = FocusOutcome(task_id, False, "", error=str(exc))
            task = self.store.get(task_id)
            if task and not task.is_terminal:
                self.store.transition(
                    task_id, TaskStatus.FAILED, force=True, error=str(exc)[:1000]
                )
        if self.result_callback:
            try:
                self.result_callback(outcome)
            except Exception:
                logger.exception("Task result callback failed for %s", task_id)

    def _run(self, task_id: str, active_toolsets: set[str]) -> FocusOutcome:
        task = self.store.get(task_id)
        if task is None:
            return FocusOutcome(task_id, False, "", error="Task disappeared")
        self.store.transition(task_id, TaskStatus.FOCUSING)

        selected_orchestrators = [
            (record, 1.0)
            for record in (
                self.orchestrators.get(orchestrator_id)
                for orchestrator_id in task.orchestrator_ids
            )
            if record is not None
        ]
        if not selected_orchestrators:
            # Compatibility for queued tasks created before situational routing
            # was introduced. Do not teach a sequence from worker scheduling.
            selected_orchestrators = self.orchestrators.select(
                task, limit=3, observe_transition=False
            )
            task.orchestrator_ids = [
                record.orchestrator_id for record, _ in selected_orchestrators
            ]
        anchor = selected_orchestrators[0][0]
        depth = self._adaptive_depth(task, anchor)
        habits = self.procedures.relevant(task)
        preferred_capabilities = set(anchor.capability_counts)
        for habit in habits:
            preferred_capabilities.update(habit.get("tool_sequence", []))
        chosen_capabilities = self.capabilities.select(
            task.objective,
            task_type=task.task_type,
            authorization_scope=task.authorization_scope,
            active_toolsets=active_toolsets,
            preferred_names=preferred_capabilities,
            limit=8,
        )
        task.capability_names = [item.name for item in chosen_capabilities]
        task.focus_depth = depth
        self.store.update(
            task_id,
            orchestrator_ids=task.orchestrator_ids,
            capability_names=task.capability_names,
            focus_depth=depth,
        )

        if task.task_type in {"action", "respond"} and not chosen_capabilities:
            message = "The intention needs an ability or authorization that is not presently available."
            self.store.transition(task_id, TaskStatus.BLOCKED, error=message)
            return FocusOutcome(task_id, False, message, error=message)

        context = self.context_builder.render(
            task.objective,
            max_items=32 if self.provider_config.context_window >= 100_000 else 20,
            token_budget=12_000 if self.provider_config.context_window >= 100_000 else 4_000,
        )
        system = self._focus_kernel()
        prompt = self._task_prompt(task, context, anchor, habits)
        config = self._focus_config()
        session = create_session(
            config=config,
            system_instruction=system,
            tool_declarations=self.capabilities.declarations_for(chosen_capabilities),
            tool_executor=self.tool_executor,
        )

        calls: List[Dict] = []
        tool_results: List[str] = []
        thoughts: List[str] = []
        ended_with_reflection = False
        failure = ""
        try:
            self.store.transition(task_id, TaskStatus.EXECUTING)
            turn_message = prompt
            for step in range(depth):
                thought = session.send_message(turn_message) or ""
                if thought.startswith("[internal error:"):
                    failure = thought
                    break
                if thought and thought != "[tools called, results pending]":
                    thoughts.append(thought)
                step_calls = session.get_last_tool_calls() if hasattr(session, "get_last_tool_calls") else []
                step_results = (
                    session.get_pending_tool_results()
                    if hasattr(session, "get_pending_tool_results") else []
                )
                calls.extend(step_calls or [])
                tool_results.extend(
                    str(item.get("result", "")) for item in (step_results or [])
                    if item.get("result")
                )
                if not step_calls:
                    ended_with_reflection = True
                    break
                if any(self._tool_result_failed(item.get("result", "")) for item in step_results):
                    failure = next(
                        str(item.get("result", "")) for item in step_results
                        if self._tool_result_failed(item.get("result", ""))
                    )
                    break
                turn_message = (
                    "The result of my last action is now part of my awareness. "
                    "Continue only if another action is necessary to finish this task; "
                    "otherwise state the concise outcome."
                )
        finally:
            session.close()

        task = self.store.get(task_id) or task
        self.store.transition(task_id, TaskStatus.REFLECTING, force=bool(failure))
        needs_action = task.task_type in {"action", "respond"}
        success = not failure and (bool(calls) or not needs_action)
        if ended_with_reflection and thoughts:
            summary = thoughts[-1]
        elif tool_results:
            summary = tool_results[-1]
        else:
            summary = thoughts[-1] if thoughts else (
                "The intended action completed." if success else failure
            )
        if success:
            self.store.transition(
                task_id,
                TaskStatus.COMPLETE,
                result=summary[:4000],
                attempts=task.attempts + 1,
            )
        else:
            failure = failure or "No authorized action was completed."
            self.store.transition(
                task_id,
                TaskStatus.FAILED,
                error=failure[:2000],
                attempts=task.attempts + 1,
            )

        tool_names = [call.get("name", "") for call in calls]
        learned_task = self.store.get(task_id) or task
        try:
            self.orchestrators.learn(
                learned_task,
                success=success,
                capabilities=tool_names,
                focus_depth=depth,
            )
            self.procedures.observe(learned_task, tool_names, success=success)
        except Exception as exc:
            logger.warning("Task completed but procedural learning failed: %s", exc)
        return FocusOutcome(task_id, success, summary[:4000], calls, failure[:2000])

    def _adaptive_depth(self, task: TaskRecord, orchestrator: OrchestratorRecord) -> int:
        novelty = 1.0 / (orchestrator.observations + 1.0)
        failure_rate = orchestrator.failures / max(1.0, orchestrator.observations)
        uncertainty = float(task.metadata.get("uncertainty", 0.35))
        stakes = 0.65 if task.authorization_scope == "unverified" else 0.25
        habit_strength = min(1.0, orchestrator.observations / 8.0)
        pressure = novelty + uncertainty + stakes + failure_rate - (0.75 * habit_strength)
        return max(1, min(self.max_depth, 1 + round(max(0.0, pressure))))

    def _focus_kernel(self) -> str:
        return (
            f"{self.identity}\n"
            "This is focused work within my own continuing cognition. The task, memories, "
            "beliefs, and outcomes are mine; do not describe a separate agent. Complete only "
            "the stated task with the abilities made available for it. Do not assume an action "
            "succeeded until its result is present."
        )

    @staticmethod
    def _task_prompt(
        task: TaskRecord,
        context: str,
        orchestrator: OrchestratorRecord,
        habits: List[Dict],
    ) -> str:
        habit_lines = [
            " -> ".join(item.get("tool_sequence", []))
            for item in habits if item.get("tool_sequence")
        ]
        learned = "; ".join(habit_lines) if habit_lines else "none yet"
        recent_events = "\n".join(f"- {event}" for event in task.source_events[-5:])
        return (
            "<task>\n"
            f"Objective: {task.objective}\n"
            f"Type: {task.task_type}\n"
            f"Details: {task.details or task.objective}\n"
            f"Constraints: {'; '.join(task.constraints) or 'none beyond the stated scope'}\n"
            f"Success: {'; '.join(task.success_conditions) or 'the objective is actually satisfied'}\n"
            f"Authorization: {task.authorization_scope}\n"
            f"Recent triggering events:\n{recent_events or '- none'}\n"
            "</task>\n\n"
            "<recalled_context>\n" + context + "\n</recalled_context>\n\n"
            f"Learned procedural tendencies relevant here: {learned}\n"
            f"Situational habit reliability: {orchestrator.reliability:.2f}."
        )

    def _focus_config(self) -> ProviderConfig:
        options = dict(self.provider_config.options or {})
        options.pop("thought_only", None)
        # Focus depth already adapts total work; use a bounded reasoning effort
        # unless the operator explicitly configured one.
        options.setdefault("effort", "medium")
        return ProviderConfig(
            provider_type=self.provider_config.provider_type,
            model=self.provider_config.model,
            context_window=self.provider_config.context_window,
            temperature=self.provider_config.temperature,
            max_output_tokens=self.provider_config.max_output_tokens,
            options=options,
        )

    @staticmethod
    def _tool_result_failed(result: str) -> bool:
        text = str(result or "").lower().strip()
        return text.startswith(("error", "tool error", "unknown tool", "command blocked")) or (
            "could not deliver" in text
        )
