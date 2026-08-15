"""Post-pulse controller that turns natural intentions into task events."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from core.task_cognition.capabilities import CapabilityRegistry
from core.task_cognition.context import TaskContextBuilder
from core.task_cognition.focus import FocusManager, FocusOutcome
from core.task_cognition.inception import IntentionDetector
from core.task_cognition.models import TaskRecord
from core.task_cognition.orchestrators import OrchestratorSpace
from core.task_cognition.procedures import ProceduralMemory
from core.task_cognition.store import TaskStore

logger = logging.getLogger("helix.core.task_cognition.controller")
_MODES = {"off", "observe", "active"}


class TaskCognitionController:
    """Own the task lifecycle while the main consciousness keeps thinking."""

    def __init__(
        self,
        *,
        data_dir: str | Path,
        mode: str,
        pulse_loop,
        belief_store,
        memory_manager,
        physics_engine,
        provider_config,
        tool_executor,
        max_workers: int = 2,
        max_depth: int = 4,
    ):
        requested = os.environ.get("HELIX_TASK_COGNITION", mode or "off").strip().lower()
        self.mode = requested if requested in _MODES else "off"
        tool_capable = (
            provider_config is not None
            and provider_config.provider_type in {"gemini", "anthropic", "codex", "codex_cli"}
        )
        standard_loop = pulse_loop.__class__.__name__ == "PulseLoop"
        if self.mode == "active" and not (tool_capable and standard_loop):
            logger.warning(
                "Active task cognition requires the standard pulse loop and a "
                "tool-capable provider; falling back to observe mode"
            )
            self.mode = "observe"
        self.pulse_loop = pulse_loop
        self.memory = memory_manager
        task_dir = Path(data_dir) / "tasks"
        self.store = TaskStore(task_dir)
        self.detector = IntentionDetector()
        self.capabilities = CapabilityRegistry(
            query_embedder=lambda text: physics_engine.embed_semantic_text(
                text, is_query=True
            ),
            document_batch_embedder=lambda texts: physics_engine.embed_semantic_batch(
                texts, is_query=False
            ),
        )
        self.orchestrators = None
        self.procedures = None
        self.context_builder = None
        self.focus: Optional[FocusManager] = None
        self._pending_resumed = False
        if self.active and provider_config is not None:
            self.orchestrators = OrchestratorSpace(
                task_dir,
                semantic_embedder=lambda text: physics_engine.embed_semantic_text(text, is_query=True),
                spatial_projector=physics_engine.embed_and_project,
                semantic_dim=getattr(physics_engine.semantic_index, "dim", 1024),
            )
            self.procedures = ProceduralMemory(task_dir)
            self.context_builder = TaskContextBuilder(
                belief_store, memory_manager, physics_engine
            )
            premises = belief_store.get_category("premises", limit=1)
            identity = (
                premises[0].get("content", "")
                if premises else "I am Helix, experiencing an ongoing stream of events and thought."
            )
            self.focus = FocusManager(
                store=self.store,
                capabilities=self.capabilities,
                orchestrators=self.orchestrators,
                procedures=self.procedures,
                context_builder=self.context_builder,
                provider_config=provider_config,
                tool_executor=tool_executor,
                identity=identity,
                result_callback=self._on_result,
                max_workers=max_workers,
                max_depth=max_depth,
            )
        logger.info("Task cognition initialized: mode=%s", self.mode)

    @property
    def enabled(self) -> bool:
        return self.mode != "off"

    @property
    def active(self) -> bool:
        return self.mode == "active"

    def awareness(self, active_toolsets: set[str]) -> str:
        return self.capabilities.broad_awareness(active_toolsets) if self.enabled else ""

    def observe_pulse(self, ctx) -> None:
        """Post-pulse hook: persist committed intentions and optionally run them."""
        if not self.enabled:
            return
        resumed_waiting = False
        if self.active and self.focus is not None:
            resumed_waiting = self._resume_waiting_from_events(ctx)
        if self.active and self.focus is not None and not self._pending_resumed:
            self._pending_resumed = True
            for pending in self.store.open_tasks():
                if pending.status.value in {"focusing", "ready", "executing", "reflecting"}:
                    pending = self.store.transition(
                        pending.task_id,
                        "created",
                        force=True,
                        error="Recovered after an interrupted focus thread.",
                    )
                if pending.status.value == "created":
                    if not pending.orchestrator_ids:
                        routed = self.orchestrators.select(pending, limit=3)
                        pending = self.store.update(
                            pending.task_id,
                            orchestrator_ids=[
                                record.orchestrator_id for record, _score in routed
                            ],
                        )
                    self.focus.submit(pending, set(ctx.active_toolsets))
        candidates = [] if resumed_waiting else self.detector.detect(ctx.thought, ctx.events)
        for candidate in candidates:
            record = TaskRecord(
                objective=candidate.objective,
                details=candidate.evidence,
                task_type=candidate.task_type,
                signature=candidate.signature,
                source_thought_id=ctx.memory_id if ctx.memory_id >= 0 else None,
                source_pulse=ctx.pulse_count,
                source_events=list(ctx.events)[-5:],
                commitment=candidate.commitment,
                authorization_scope=candidate.authorization_scope,
                metadata={
                    "inception": "natural_thought",
                    "spatial_state": dict(ctx.spatial_state),
                },
            )
            stored = self.store.create(record)
            if stored.task_id != record.task_id:
                continue
            logger.info(
                "Intention became task %s (%s, commitment=%.2f): %s",
                stored.task_id,
                stored.task_type,
                stored.commitment,
                stored.objective[:160],
            )
            if self.active and self.focus is not None:
                # Route on the serial post-pulse path. Direct A -> B habit
                # learning must follow the order Helix formed tasks, not the
                # nondeterministic order parallel worker threads happened to run.
                routed = self.orchestrators.select(stored, limit=3)
                stored = self.store.update(
                    stored.task_id,
                    orchestrator_ids=[
                        item.orchestrator_id for item, _score in routed
                    ],
                )
                self.focus.submit(stored, set(ctx.active_toolsets))

    def _on_result(self, outcome: FocusOutcome) -> None:
        task = self.store.get(outcome.task_id)
        if task is None:
            return
        if outcome.waiting_for_input:
            self.pulse_loop.emit("task_question", {
                "task_id": task.task_id,
                "objective": task.objective,
                "question": outcome.question,
            })
            self.pulse_loop.wake(trigger="task_question")
            return
        if outcome.success:
            content = f"I completed a task I formed: {task.objective}. Outcome: {outcome.summary}"
            try:
                self.memory.store(
                    content=content,
                    memory_type="task_outcome",
                    source="task_cognition",
                    importance=0.7,
                    tags=["task", "completed", task.task_type],
                )
            except Exception as exc:
                logger.warning("Task outcome memory write failed: %s", exc)
        self.pulse_loop.emit("task_result", {
            "task_id": task.task_id,
            "objective": task.objective,
            "success": outcome.success,
            "result": outcome.summary or outcome.error,
        })
        self.pulse_loop.wake(trigger="task_result")

    def provide_input(
        self,
        task_id: str,
        answer: str,
        active_toolsets: Optional[set[str]] = None,
    ) -> bool:
        """Attach a user's clarification answer and resume the same task."""
        if not self.active or self.focus is None:
            return False
        task = self.store.get(task_id)
        answer = str(answer or "").strip()
        if task is None or task.status.value != "waiting_input" or not answer:
            return False
        metadata = dict(task.metadata)
        history = list(metadata.get("clarification_history", []))
        history.append({"question": task.question, "answer": answer})
        metadata["clarification_history"] = history[-5:]
        source_events = list(task.source_events)
        source_events.append(f"Clarification answer: {answer}")
        task = self.store.update(
            task.task_id,
            question="",
            required_inputs=[],
            source_events=source_events[-8:],
            metadata=metadata,
        )
        active = set(
            active_toolsets
            if active_toolsets is not None
            else getattr(self.pulse_loop, "_active_toolsets", {"core"})
        )
        return self.focus.submit(task, active)

    def _resume_waiting_from_events(self, ctx) -> bool:
        """Resume one unambiguous waiting task from the next direct answer.

        The standard pulse path currently carries translated event strings.
        We only bind automatically when exactly one task is waiting and a new
        direct-message event is present; multiple waiting questions require an
        explicit ``provide_input(task_id, answer)`` call.
        """
        waiting = [
            task for task in self.store.open_tasks()
            if task.status.value == "waiting_input"
        ]
        if len(waiting) != 1:
            return False
        answers = []
        for event in list(getattr(ctx, "events", ()) or ()):
            text = str(event or "")
            marker = "They said: \""
            if " is talking to me via " not in text or marker not in text:
                continue
            answer = text.split(marker, 1)[1]
            if answer.endswith('"'):
                answer = answer[:-1]
            if answer.strip():
                answers.append(answer.strip())
        if not answers:
            return False
        return self.provide_input(
            waiting[0].task_id,
            answers[-1],
            set(getattr(ctx, "active_toolsets", {"core"})),
        )

    def shutdown(self) -> None:
        if self.focus is not None:
            self.focus.shutdown(wait=False)
