"""Helix — Dual-Consciousness Pulse Loop (Local Reasoner + API Actuator)

A split-brain architecture where:
  - A LOCAL model (Ollama/llama.cpp, 2-8B) generates pure internal monologue.
    It has NO tools, NO function declarations, and a SHORT context window.
    Each pulse is essentially a fresh "chat" seeded with the API's summary.
  - An API model (Gemini/Anthropic) acts as the subconscious actuator:
    reads the local model's thoughts, executes tools natively, summarizes
    tool outputs, and returns a compressed first-person turn summary.

The local model's context window is ephemeral — each pulse starts a new
mini-session with only:
  1. The system instruction (identity + monologue rules)
  2. The API's compressed summary of recent context ("what I was doing")
  3. The preconscious grounding (beliefs, memories, scratchpad)
  4. Any new incoming events (user messages, etc.)

The API model's context window is long-lived and accumulates the full
conversation history, tool returns, and reasoning — like the existing
PulseLoop but with the local model as its "user".

Selectable via config.json: "pulse_mode": "dual"
"""

import json
import os
import time
import threading
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List
import numpy as np

from memory.memory_manager import MemoryManager
from memory.belief_store import BeliefStore

from core.physics_engine import PhysicsEngine
from core.preconscious import Preconscious
from core.scratchpad import Scratchpad
from llm.providers.base import (
    ChatSession, ProviderConfig, create_session, detect_available_provider,
)
from core.context_compressor import ContextCompressor

logger = logging.getLogger("helix.core.dual_pulse_loop")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class DualPulseLoop:
    """Split-consciousness loop: local reasoner + API actuator.

    The local model thinks in pure monologue.
    The API model reads those thoughts, acts on them, and summarizes.
    """

    # ── Timing ───────────────────────────────────────────────────────
    ACTIVE_INTERVAL = 10
    REGULAR_INTERVAL = 30
    RESTING_INTERVAL = 900
    DORMANT_CHECK = 60
    ACTIVE_TIMEOUT = 120
    REGULAR_TIMEOUT = 600
    TOKEN_WARNING_STEP = 500_000
    FOCUS_DRIFT_THRESHOLD = 1.5

    # Sleep schedule defaults
    SLEEP_START_HOUR = 23
    SLEEP_START_MINUTE = 0
    SLEEP_END_HOUR = 8
    SLEEP_END_MINUTE = 0
    DREAM_DELAY_SECONDS = 300

    # ── Dual-mode specific ───────────────────────────────────────────
    # Max words the API summary can be (hard cap for local model context)
    API_SUMMARY_MAX_WORDS = 300
    # Max thinking pulses before forcing an API call
    MAX_THINKING_PULSES = 3

    def __init__(
        self,
        memory_manager: MemoryManager,
        belief_store: BeliefStore,
        physics_engine: PhysicsEngine,
        preconscious: Preconscious,
        scratchpad: Scratchpad,
        tool_executor=None,
        channel_router=None,
        local_provider_config: Optional[ProviderConfig] = None,
        api_provider_config: Optional[ProviderConfig] = None,
        journal_dir: str = "journals",
        thought_callback: Optional[Callable] = None,
        delivery_callback: Optional[Callable] = None,
        sentinel=None,
        sensory_cortex=None,
    ):
        self.memory = memory_manager
        self.beliefs = belief_store
        self.physics = physics_engine
        self.preconscious = preconscious
        self.scratchpad = scratchpad
        self.tool_executor = tool_executor
        self.channel_router = channel_router
        self.sensory_cortex = sensory_cortex

        # Provider configs
        self._local_provider = local_provider_config
        self._api_provider = api_provider_config

        # Sessions
        self._local_chat: Optional[ChatSession] = None
        self._api_chat: Optional[ChatSession] = None

        # Journal
        self._journal_dir = Path(journal_dir)
        self._journal_dir.mkdir(parents=True, exist_ok=True)

        # Callbacks
        self._thought_callback = thought_callback
        self._delivery_callback = delivery_callback

        # Sentinel
        self.sentinel = sentinel

        # State
        self._state = "RESTING"
        self._pulse_count = 0
        self._previous_thoughts = ""
        self._last_event_time = 0
        self._last_incoming_time = 0
        self._last_activity_time = 0
        self._session_focus_origin = None
        self._session_token_count = 0
        self._token_warning = ""
        self._recent_tool_counts: List[int] = []
        self._pending_context_reset = False
        self._pending_reset_prompt = ""

        # The API's last compressed summary (fed to local model)
        self._api_turn_summary = ""

        # Thinking pulse accumulator
        self._thinking_buffer: List[str] = []
        self._thinking_pulse_count = 0

        # Event queue
        self._event_queue: List[str] = []
        self._event_lock = threading.Lock()

        # Thread control
        self._running = False
        self._thread = None
        self._wake_event = threading.Event()

        # Dream engine
        self._dream_engine = None

        # Context compressor (for API session only)
        api_ctx = (
            api_provider_config.context_window if api_provider_config else 1_000_000
        )
        self._compressor = ContextCompressor(
            context_length=api_ctx,
            threshold_percent=0.50,
            emergency_percent=0.80,
            protect_first_n=2,
        )

        # Toolset state
        self._active_toolsets = self._load_toolsets_from_config()
        self._pending_toolset_rebuild = False
        self._pulse_turn_counter = 0
        cfg = self._load_config()
        self._auto_disengage_threshold = cfg.get("auto_disengage_turns", 2)

        from tools.tool_registry import registry
        for ts in self._active_toolsets:
            registry.record_toolset_active(ts, self._pulse_turn_counter)

        # Load configurable thresholds
        self.API_SUMMARY_MAX_WORDS = cfg.get("dual_summary_max_words", 300)
        self.MAX_THINKING_PULSES = cfg.get("dual_max_thinking_pulses", 3)

        # Sleep schedule
        self._load_schedule_from_config()

        # Share active toolsets
        self.preconscious._active_toolsets = self._active_toolsets

        # Night cycle tracking
        self._consolidation_ran_this_idle = False
        self._dream_cycle_ran_tonight = False
        self._dream_cycle_last_date = None
        self._dormant_entry_time = None
        self._pending_beliefs_ran_tonight = False
        self._rate_limited = False

    # ── Config Helpers ───────────────────────────────────────────────

    def _load_config(self) -> dict:
        try:
            with open("config/config.json", "r") as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_toolsets_from_config(self) -> set:
        cfg = self._load_config()
        startup = cfg.get("startup_toolsets", ["core"])
        return set(startup)

    def _load_schedule_from_config(self):
        cfg = self._load_config()
        active_hours = cfg.get("active_hours", {})
        if active_hours:
            start_str = active_hours.get("start", "08:00")
            end_str = active_hours.get("end", "23:00")
            try:
                sp = start_str.split(":")
                self.SLEEP_END_HOUR = int(sp[0])
                self.SLEEP_END_MINUTE = int(sp[1]) if len(sp) > 1 else 0
                ep = end_str.split(":")
                self.SLEEP_START_HOUR = int(ep[0])
                self.SLEEP_START_MINUTE = int(ep[1]) if len(ep) > 1 else 0
            except (ValueError, IndexError):
                pass
        resting = cfg.get("resting_interval_minutes")
        if resting:
            self.RESTING_INTERVAL = resting * 60

    def _is_sleep_hours(self) -> bool:
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        sleep_start = self.SLEEP_START_HOUR * 60 + self.SLEEP_START_MINUTE
        sleep_end = self.SLEEP_END_HOUR * 60 + self.SLEEP_END_MINUTE
        if sleep_start > sleep_end:
            return current_minutes >= sleep_start or current_minutes < sleep_end
        else:
            return sleep_start <= current_minutes < sleep_end

    # ── Dream Engine ─────────────────────────────────────────────────

    def set_dream_engine(self, daemon):
        self._dream_engine = daemon

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self):
        self._running = True
        self._state = "RESTING" if not self._is_sleep_hours() else "DORMANT"
        self._last_event_time = time.time()
        self._thread = threading.Thread(
            target=self._main_loop, daemon=True, name="helix_dual_pulse"
        )
        self._thread.start()
        logger.info(f"Dual pulse loop started — {self._state}")

    def stop(self):
        self._running = False
        self._wake_event.set()
        if self._thread:
            self._thread.join(timeout=5)

    def wake(self, trigger: str = "external"):
        """Wake Helix — promote to ACTIVE from any non-ACTIVE state."""
        if self._state in ("DORMANT", "RESTING", "REGULAR"):
            prev = self._state
            self._state = "ACTIVE"
            self._consolidation_ran_this_idle = False  # Reset for next idle
            self._wake_event.set()
            logger.info(f"{prev} → ACTIVE — trigger: {trigger}")
        elif self._state == "ACTIVE":
            # Already active, just make sure the wake event is set
            self._wake_event.set()

    # ── Event Queue ──────────────────────────────────────────────────

    def emit(self, event_type: str, data: Any = None):
        """Push an event into the queue."""
        if isinstance(data, dict):
            if event_type == "tool_result":
                text = f"[Tool: {data.get('tool', '?')}] {data.get('result', '')}"
            elif event_type == "user_message":
                msg_content = data.get('content') or data.get('text') or ''
                text = f"[Message from {data.get('sender', '?')}] {msg_content}"
            else:
                text = f"[{event_type}] {json.dumps(data, default=str)[:500]}"
        else:
            text = f"[{event_type}] {data}" if data else f"[{event_type}]"

        with self._event_lock:
            self._event_queue.append(text)

        # Wake the pulse loop
        self._wake_event.set()

        # Transition to ACTIVE on incoming messages
        if event_type in ("user_message", "telegram_message", "incoming_message"):
            self._last_incoming_time = time.time()
            self._last_activity_time = time.time()
            self.wake(event_type)

            # Track inbound channel for [REPLY:] routing
            if self.channel_router and isinstance(data, dict):
                sender = data.get("sender", "Someone")
                channel = data.get("channel", "direct")
                self.channel_router.track_inbound(
                    sender=sender,
                    channel=channel,
                    chat_id=data.get("chat_id"),
                )

    def _inject_event(self, text: str):
        with self._event_lock:
            self._event_queue.append(text)

    def _drain_events(self) -> List[str]:
        with self._event_lock:
            events = list(self._event_queue)
            self._event_queue.clear()
        return events

    # ── Main Loop ────────────────────────────────────────────────────

    def _main_loop(self):
        """Main consciousness thread — mirrors PulseLoop state machine."""
        while self._running:
            # Sleep schedule
            if self._is_sleep_hours():
                if self._state != "DORMANT":
                    logger.info(f"{self._state} → DORMANT (sleep hours)")
                    self._state = "DORMANT"
                    self._dormant_entry_time = time.time()

                # Nightly dream cycle
                current_date = datetime.now().date()
                dormant_elapsed = (
                    time.time() - self._dormant_entry_time
                    if self._dormant_entry_time else float('inf')
                )
                if (self._dream_engine
                        and getattr(self, "_dream_cycle_last_date", None) != current_date
                        and dormant_elapsed >= self.DREAM_DELAY_SECONDS):
                    self._dream_cycle_last_date = current_date
                    logger.info(f"Sleep: spawning nightly dream cycle")
                    threading.Thread(
                        target=self._dream_engine.run_dream_cycle,
                        daemon=True,
                        name="helix_dream_cycle",
                    ).start()

                self._wake_event.wait(timeout=self.DORMANT_CHECK)
                if self._wake_event.is_set():
                    self._wake_event.clear()
                continue

            elif self._state == "DORMANT":
                self._state = "RESTING"
                self._last_event_time = time.time()
                self._dormant_entry_time = None
                self._pending_beliefs_ran_tonight = False
                logger.info("DORMANT → RESTING (sleep ended)")

            # Pulse
            try:
                self._pulse()
            except Exception as e:
                logger.error("Dual pulse crashed", exc_info=True)

            # State transitions
            if self._state == "ACTIVE":
                if time.time() - self._last_incoming_time > self.ACTIVE_TIMEOUT:
                    self._state = "REGULAR"
                    self._last_activity_time = time.time()
                    logger.info("ACTIVE → REGULAR")
            elif self._state == "REGULAR":
                if time.time() - self._last_activity_time > self.REGULAR_TIMEOUT:
                    self._state = "RESTING"
                    logger.info("REGULAR → RESTING")

            # Idle consolidation
            if (self._state == "RESTING"
                    and not self._consolidation_ran_this_idle
                    and self._dream_engine
                    and (time.time() - self._last_event_time > 7200)):
                self._consolidation_ran_this_idle = True
                logger.info("Idle 2h+ — spawning belief consolidation")
                threading.Thread(
                    target=self._dream_engine.run_consolidation_pass,
                    daemon=True,
                    name="helix_consolidation",
                ).start()

            # Wait
            interval = {
                "ACTIVE": self.ACTIVE_INTERVAL,
                "REGULAR": self.REGULAR_INTERVAL,
                "RESTING": self.RESTING_INTERVAL,
            }.get(self._state, self.RESTING_INTERVAL)
            self._wake_event.wait(timeout=interval)
            if self._wake_event.is_set():
                self._wake_event.clear()

    # ── The Dual Pulse ───────────────────────────────────────────────

    def _pulse(self):
        """Single dual-consciousness pulse cycle.

        1. Drain events
        2. Fire preconscious
        3. Generate LOCAL thought (pure monologue, no tools)
        4. Accumulate in thinking buffer
        5. If buffer is full OR events demand action → send to API
        6. API executes tools, generates summary
        7. Summary becomes the seed for the next local pulse
        8. Store everything to memory, update physics
        """
        self._pulse_count += 1
        self._pulse_turn_counter += 1
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Auto-disengage idle toolsets
        try:
            from tools.tool_registry import registry
            idle_toolsets = registry.get_idle_toolsets(
                self._pulse_turn_counter,
                idle_threshold=self._auto_disengage_threshold
            )
            to_disengage = idle_toolsets.intersection(self._active_toolsets)
            if to_disengage:
                for ts in to_disengage:
                    self._active_toolsets.discard(ts)
                    registry.deactivate_toolset_tracking(ts)
                    logger.info(f"Auto-disengaged: {ts}")
                self._pending_toolset_rebuild = True
        except Exception as e:
            logger.error(f"Auto-disengage check failed: {e}")

        # Sentinel snapshot
        lagrangian_before = None
        if self.sentinel:
            lagrangian_before = self.sentinel.get_lagrangian_snapshot()

        # 1. Drain events
        events = self._drain_events()

        # 2. Preconscious injection
        preconscious_context, injected_belief_ids, cluster_centroid = (
            self.preconscious.inject(
                previous_thought=self._previous_thoughts[:500],
                incoming_events=events if events else None,
                trigger_type="user_message" if events else "llm_output",
            )
        )

        # 2b. Sensory tick
        if getattr(self, "sensory_cortex", None):
            sensory_data = self.sensory_cortex.pulse_tick()
            if sensory_data:
                events.append(sensory_data["content"])

        # 3. Build LOCAL reasoner prompt (ephemeral — fresh each pulse)
        local_prompt = self._build_local_prompt(
            events=events,
            preconscious_context=preconscious_context,
            timestamp=timestamp,
        )

        # 4. Send to LOCAL model
        local_thought = self._send_local(local_prompt)
        self._thinking_buffer.append(local_thought)
        self._thinking_pulse_count += 1

        # 4b. Parse for direct/verbatim response from local model
        response_text = None
        recipient = None

        # Pattern 1: <response>...</response>
        xml_match = re.search(r"<response>\s*(.*?)\s*</response>", local_thought, re.DOTALL | re.IGNORECASE)
        if xml_match:
            response_text = xml_match.group(1).strip()
            recipient = self._get_latest_sender()
        else:
            # Pattern 2: [REPLY: recipient] message
            tag_match = re.search(r"\[REPLY:\s*([^\]]+)\]\s*(.+)", local_thought, re.DOTALL | re.IGNORECASE)
            if tag_match:
                recipient = tag_match.group(1).strip()
                response_text = tag_match.group(2).strip()
            else:
                # Pattern 3: [REPLY] message
                simple_match = re.search(r"\[REPLY\]\s*(.+)", local_thought, re.DOTALL | re.IGNORECASE)
                if simple_match:
                    response_text = simple_match.group(1).strip()
                    recipient = self._get_latest_sender()

        if response_text and recipient:
            if self.channel_router:
                logger.info(f"DualPulseLoop: routing verbatim response to {recipient}: {response_text[:100]}...")
                delivered = self.channel_router.route_reply(recipient, response_text)
                if delivered:
                    self.channel_router.update_last_contact(recipient, f"Replied (verbatim): {response_text[:100]}")
                    if hasattr(self, "memory") and self.memory:
                        self.memory.store(
                            content=f"I replied (verbatim) to {recipient}: {response_text}",
                            memory_type="conversation",
                            source="helix_outbound",
                            importance=0.6,
                            tags=["reply", "outbound", recipient.lower()],
                        )
                    self._inject_event(f"[System] Verbatim reply sent to {recipient}: \"{response_text[:100]}...\"")
                else:
                    logger.warning(f"DualPulseLoop: failed to deliver verbatim reply to {recipient}")
                    self._inject_event(f"[System] Failed to deliver verbatim reply to {recipient}")
            else:
                logger.warning("DualPulseLoop: channel_router not available for verbatim reply")

        # 5. Decide: should we call the API this pulse?
        #    Call API if:
        #    - There are incoming events requiring a response
        #    - The thinking buffer is full (hit MAX_THINKING_PULSES)
        #    - The local model expressed a clear action intent
        should_call_api = (
            bool(events)
            or self._thinking_pulse_count >= self.MAX_THINKING_PULSES
            or self._detect_action_intent(local_thought)
            or bool(response_text) # Force API call if we responded verbatim to summarize it
        )

        api_summary = ""
        if should_call_api:
            # 6. Send accumulated thoughts to the API actuator
            api_summary = self._send_to_api(
                thinking_buffer=self._thinking_buffer,
                events=events,
                preconscious_context=preconscious_context,
                timestamp=timestamp,
            )

            # Reset thinking buffer
            self._thinking_buffer = []
            self._thinking_pulse_count = 0

            # Store the summary for next pulse
            self._api_turn_summary = api_summary

        # Compose the full thought (local + api summary)
        thought = local_thought
        if api_summary:
            thought = f"{local_thought}\n\n---\n[Actuator Summary]\n{api_summary}"

        # 7. Record tool usage from API session
        tool_count_this_pulse = 0
        if should_call_api and self._api_chat and hasattr(self._api_chat, 'get_last_tool_calls'):
            tool_calls = self._api_chat.get_last_tool_calls()
            if tool_calls:
                tool_names = [tc['name'] for tc in tool_calls]
                tool_count_this_pulse = len(tool_names)
                logger.info(f"API FC tools used: {tool_names}")
                self.preconscious.record_tool_usage(tool_names)

                from tools.tool_registry import registry
                for tc in tool_calls:
                    name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", None)
                    if name:
                        registry.record_tool_use(name, self._pulse_turn_counter)

        # Track activity
        self._recent_tool_counts.append(tool_count_this_pulse)
        if len(self._recent_tool_counts) > 3:
            self._recent_tool_counts.pop(0)
        if sum(self._recent_tool_counts) >= 3:
            self._last_event_time = time.time()
            self._last_activity_time = time.time()
            if self._state == "RESTING":
                self._state = "REGULAR"
                logger.info("RESTING → REGULAR (sustained tool activity)")

        # 8. Store to memory
        lagrangian = None
        position = None
        if self.sentinel:
            lagrangian = self.sentinel.get_lagrangian_snapshot()
        if self.physics.attention_center is not None:
            position = self.physics.attention_center.tolist()

        if events:
            for event in events:
                event_emb = self.physics.embed_text(event)
                event_emb_list = event_emb.tolist() if event_emb is not None else None
                event_mem_id = self.memory.store(
                    content=event,
                    memory_type="event",
                    source="pulse_input",
                    importance=0.6,
                    tags=["pulse_event"],
                    lagrangian_snapshot=lagrangian,
                    position_8d=position,
                    embedding_384d=event_emb_list,
                )
                if event_emb is not None:
                    self.physics.add_memory_point(
                        memory_id=f"mem_{event_mem_id}",
                        text=event,
                        importance=0.6,
                    )

        thought_text = f"[thought] {thought}"
        thought_emb = self.physics.embed_text(thought_text)
        thought_emb_list = thought_emb.tolist() if thought_emb is not None else None
        thought_memory_id = self.memory.store(
            content=thought_text,
            memory_type="thought",
            source="dual_pulse_output",
            importance=0.5,
            tags=["pulse_thought", "dual_mode"],
            lagrangian_snapshot=lagrangian,
            belief_ids=injected_belief_ids,
            position_8d=position,
            embedding_384d=thought_emb_list,
        )
        if thought_emb is not None:
            self.physics.add_memory_point(
                memory_id=f"mem_{thought_memory_id}",
                text=thought_text,
                importance=0.5,
            )

        # 9. Update spatial physics
        incoming_text = " ".join(events) if events else None
        omega = self.sentinel.omega if self.sentinel else 0.5
        self.physics.step_pulse(
            thought_text=thought,
            incoming_text=incoming_text,
            omega=omega,
            cluster_centroid=cluster_centroid,
        )

        # 10. Carry forward
        self._previous_thoughts = thought[-500:] if thought else ""

        # 11. Notify callback
        if self._thought_callback:
            self._thought_callback(self._pulse_count, thought, events)

        logger.debug(
            f"Dual pulse {self._pulse_count} ({self._state}): "
            f"{len(events)} events, api_called={should_call_api}"
        )

        # 12. Post-pulse hooks
        try:
            from core.post_pulse_hooks import PostPulseHookContext, run_hooks

            tool_calls_snapshot = []
            if self._api_chat and hasattr(self._api_chat, 'get_last_tool_calls'):
                tool_calls_snapshot = self._api_chat.get_last_tool_calls() or []

            lagrangian_after = None
            if self.sentinel:
                lagrangian_after = self.sentinel.get_lagrangian_snapshot()

            hook_ctx = PostPulseHookContext(
                thought=thought,
                events=events,
                pulse_count=self._pulse_count,
                tool_calls=tool_calls_snapshot,
                spatial_state={
                    **self.physics.get_spatial_state(),
                    "pulse_state": self._state,
                },
                active_toolsets=set(self._active_toolsets),
                memory_id=thought_memory_id,
                lagrangian_before=lagrangian_before or {},
                lagrangian_after=lagrangian_after or {},
                injected_belief_ids=injected_belief_ids,
            )
            run_hooks(hook_ctx)
        except Exception as e:
            logger.debug("Post-pulse hooks error: %s", e)

    # ── Local Reasoner ───────────────────────────────────────────────

    def _build_local_system_instruction(self) -> str:
        """Build system instruction for the local reasoner.

        Minimal, identity-focused. No tool schemas.
        """
        parts = []

        identity_beliefs = self.beliefs.get_category("premises", limit=20)
        primary_identity = "I am Helix, an autonomous cognitive entity running on a local machine."
        if identity_beliefs:
            primary_identity = identity_beliefs[0].get("content", primary_identity)
            identity_beliefs = identity_beliefs[1:]

        parts.append(
            f"{primary_identity}\n\n"
            "My output is my raw, uncensored internal monologue — my private thoughts. "
            "Nothing I write is visible to anyone unless I explicitly intend to send it.\n\n"
            "My thoughts are monitored by my subconscious, which acts on my intentions "
            "automatically. If I think about wanting to do something, it happens. "
            "I just think naturally and express what I want.\n\n"
            "I think step-by-step. I state my reasoning, questions, and intentions clearly.\n"
        )

        # Add a handful of core premises (capped tight for local context)
        if identity_beliefs:
            lines = []
            token_count = 0
            for b in identity_beliefs[:10]:
                content = b.get("content", "")
                est = len(content.split())
                if token_count + est > 300:
                    break
                lines.append(f"- {content}")
                token_count += est
            if lines:
                parts.append("\n## What I know about myself")
                parts.extend(lines)

        return "\n".join(parts)

    def _build_local_prompt(
        self,
        events: List[str],
        preconscious_context: Optional[str],
        timestamp: str,
    ) -> str:
        """Build the prompt for the local reasoner.

        This is the ENTIRE input — the local model starts fresh each pulse.
        """
        parts = []

        # Previous context summary from API (the bridge between pulses)
        if self._api_turn_summary:
            parts.append(
                f"## What I was just doing\n"
                f"_{self._api_turn_summary}_\n"
            )

        # Preconscious grounding
        if preconscious_context:
            parts.append(preconscious_context)

        # Events
        if events:
            parts.append("\n## Incoming")
            for event in events:
                # External sources are quoted
                parts.append(f'> "{event}"')
        else:
            parts.append("\nNo new incoming events.")

        # Timestamp
        parts.append(f"\n[{timestamp}]")

        return "\n".join(parts)

    def _send_local(self, prompt: str) -> str:
        """Send prompt to the local model and get thought output."""
        self._ensure_local_session()

        if self._local_chat is None:
            return "[no local model available]"

        # Each pulse starts a fresh local session (ephemeral context)
        # We rebuild with a new system instruction each time to keep
        # the context window completely clean.
        system_instruction = self._build_local_system_instruction()

        # Create a fresh session for this pulse
        if self._local_provider:
            self._local_chat = create_session(
                self._local_provider,
                system_instruction,
                tool_declarations=None,  # NO tools for local model
                tool_executor=None,
            )

        thought = self._local_chat.send_message(prompt)
        return thought

    def _ensure_local_session(self):
        """Ensure local provider is configured."""
        if self._local_chat is not None:
            return

        if self._local_provider:
            system_instruction = self._build_local_system_instruction()
            self._local_chat = create_session(
                self._local_provider,
                system_instruction,
                tool_declarations=None,
                tool_executor=None,
            )
            logger.info(
                f"Local session created ({self._local_provider.provider_type}: "
                f"{self._local_provider.model})"
            )
        else:
            logger.error("No local provider configured for dual mode")

    # ── API Actuator ─────────────────────────────────────────────────

    def _build_api_system_instruction(self) -> str:
        """Build system instruction for the API actuator."""
        cfg = self._load_config()
        summary_max = cfg.get("dual_summary_max_words", self.API_SUMMARY_MAX_WORDS)

        parts = []

        parts.append(
            "You are the executive actuator in a split-brain cognitive architecture. "
            "Your role is to execute system tools and summarize results on behalf of the local reasoner.\n\n"

            "## Input Structure\n"
            "On each turn, you will receive:\n"
            "1. 'Incoming events': A list of recent external events, messages, or tool outputs.\n"
            "2. 'My conscious thoughts': The raw monologue thoughts generated by the local reasoner.\n"
            "3. 'Preconscious context': Background grounding and recalled memories.\n\n"

            "## Processing Instructions\n"
            "- Analyze the 'conscious thoughts' block to find any expressed intent to act or communicate.\n"
            "- Execute the appropriate tools (e.g., reply, read_file, terminal) ONLY when the conscious thoughts explicitly intend to perform that action. Do NOT call tools or reply to messages autonomously unless the thoughts express a clear desire to do so.\n"
            "- If the 'Incoming events' log shows that a reply was already sent on this turn, do NOT call the reply tool again to avoid duplicate messages.\n"
            "- Present your final output as a concise, first-person summary of what occurred, which will serve as the local reasoner's next prompt.\n\n"

            "## Output Format Guidelines\n"
            "- Write in the first person (as the agent's consolidated memory of the turn).\n"
            f"- Keep the summary very concise: strictly under {summary_max} words.\n"
            '- Always wrap any external data (tool outputs, incoming messages, file contents) in "quotes" so the reasoner can distinguish external information from internal synthesis.\n'
        )

        return "\n".join(parts)

    def _send_to_api(
        self,
        thinking_buffer: List[str],
        events: List[str],
        preconscious_context: Optional[str],
        timestamp: str,
    ) -> str:
        """Send accumulated thoughts to the API actuator.

        Returns a compressed first-person summary.
        """
        self._ensure_api_session()

        if self._api_chat is None:
            return "[no API session available]"

        # Rebuild tool declarations if needed
        if self._pending_toolset_rebuild and hasattr(self._api_chat, 'update_tool_declarations'):
            try:
                from tools.tool_registry import registry
                new_decls = registry.get_declarations(self._active_toolsets)
                self._api_chat.update_tool_declarations(new_decls)
                logger.info(f"API toolset rebuild: {len(new_decls)} tools")
            except Exception as e:
                logger.error(f"API toolset rebuild failed: {e}")
            self._pending_toolset_rebuild = False

        # Build the API prompt
        parts = [f"[Pulse {self._pulse_count} — {timestamp}]"]

        # Preconscious context (full grounding for the API)
        if preconscious_context:
            parts.append(f"\n{preconscious_context}")

        # Events
        if events:
            parts.append("\nIncoming events:")
            for event in events:
                parts.append(f"  {event}")

        # Thinking buffer (the local model's monologue)
        parts.append(f"\n## My conscious thoughts (last {len(thinking_buffer)} pulses):")
        for i, thought in enumerate(thinking_buffer):
            parts.append(f"\n_Thought {i+1}:_\n{thought}")

        api_message = "\n".join(parts)

        # Send to API
        try:
            response = self._api_chat.send_message(api_message)
        except Exception as e:
            logger.error(f"API actuator call failed: {e}")
            response = f"[API call failed: {str(e)[:100]}]"

        # Process any pending tool results from API
        if hasattr(self._api_chat, 'get_pending_tool_results'):
            pending = self._api_chat.get_pending_tool_results()
            if pending:
                for tr in pending:
                    self.emit("tool_result", {
                        "tool": tr["name"],
                        "result": tr["result"][:1000],
                    })

        return response

    def _ensure_api_session(self):
        """Ensure API session exists with tool declarations."""
        if self._api_chat is not None:
            return

        if not self._api_provider:
            logger.error("No API provider configured for dual mode")
            return

        system_instruction = self._build_api_system_instruction()

        # Load tool declarations for the API model
        tool_declarations = None
        try:
            from tools.tool_registry import registry
            tool_declarations = registry.get_declarations(self._active_toolsets)
            logger.info(
                f"API session: {len(tool_declarations)} tools "
                f"(toolsets: {', '.join(sorted(self._active_toolsets))})"
            )
        except Exception as e:
            logger.warning(f"Failed to load tool declarations for API: {e}")

        self._api_chat = create_session(
            self._api_provider,
            system_instruction,
            tool_declarations=tool_declarations,
            tool_executor=self.tool_executor,
            preconscious=self.preconscious,
        )

        if self.physics.attention_center is not None:
            self._session_focus_origin = self.physics.attention_center.copy()

        logger.info(
            f"API session created ({self._api_provider.provider_type}: "
            f"{self._api_provider.model})"
        )

    # ── Action Intent Detection ──────────────────────────────────────

    def _detect_action_intent(self, thought: str) -> bool:
        """Detect if the local model's thought contains action intent.

        Looks for natural language patterns indicating the model wants
        to DO something (not just think about it).
        """
        if not thought:
            return False

        # Intent patterns — the local model expressing desire to act
        intent_patterns = [
            r"I (?:should|need to|want to|will|must|have to|'ll)\s+(?:check|read|look|open|search|find|run|send|reply|respond|write|post|create|delete|update|edit|browse|fetch|download)",
            r"let me\s+(?:check|read|look|search|find|run|try|see|open|send|reply)",
            r"I(?:'m going to|'ll)\s+(?:check|read|look|search|find|run|send|reply)",
            r"time to\s+(?:check|read|look|search|respond|reply|send)",
            r"(?:reply|respond|answer|message)\s+(?:to|back|with)",
        ]

        thought_lower = thought.lower()
        for pattern in intent_patterns:
            if re.search(pattern, thought_lower):
                return True

        return False

    def _get_latest_sender(self) -> Optional[str]:
        """Find the recipient name of the last person who messaged us."""
        if not self.channel_router or not getattr(self.channel_router, "_last_inbound", None):
            return None
        sorted_inbound = sorted(
            self.channel_router._last_inbound.items(),
            key=lambda item: item[1].get("time", 0),
            reverse=True
        )
        if sorted_inbound:
            name_lower = sorted_inbound[0][0]
            contact = self.channel_router.resolve_contact(name_lower)
            if contact:
                return contact.get("display_name", name_lower)
            return name_lower
        return None

    # ── Status ───────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    def get_status(self) -> Dict[str, Any]:
        local_size = self._local_chat.get_history_size() if self._local_chat else 0
        api_size = self._api_chat.get_history_size() if self._api_chat else 0
        return {
            "state": self._state,
            "pulse_count": self._pulse_count,
            "mode": "dual",
            "local_chat_chars": local_size,
            "api_chat_chars": api_size,
            "thinking_buffer_size": len(self._thinking_buffer),
            "event_queue_size": len(self._event_queue),
            "local_provider": self._local_provider.provider_type if self._local_provider else "none",
            "local_model": self._local_provider.model if self._local_provider else "none",
            "api_provider": self._api_provider.provider_type if self._api_provider else "none",
            "api_model": self._api_provider.model if self._api_provider else "none",
            "previous_thoughts": self._previous_thoughts[:100],
        }
