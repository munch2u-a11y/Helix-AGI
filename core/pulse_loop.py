"""Helix — event-driven pulse consciousness loop.

The main loop owns the persistent provider session, event queue, preconscious
injection, serial attention trajectory, memory encoding, and post-pulse hooks.
User messages and accepted tool/task outcomes arrive as events within the
ongoing internal monologue.

Architecture:
  - Supports persistent Codex App Server, Gemini, Anthropic, and local backends
  - Performs one main-model request per pulse
  - Uses direct host tools in off/observe task mode when the provider supports it
  - Uses a thought-only main session plus bounded focus work in active task mode
  - Grounds each pulse with separated mRAG, raw-8D, and associative retrieval
  - Returns direct tool and focused-task outcomes through the event stream

States:
  DORMANT — configured sleep window and nightly consolidation
  RESTING — low-cadence awake pulse, immediately wakeable by events
  REGULAR — 30-second autonomous follow-through
  ACTIVE  — 10-second interactive cadence
"""

import json
import os
import time
import threading
import logging
import re
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable, Dict, Any, List, Tuple
import numpy as np

from memory.memory_manager import MemoryManager
from memory.belief_store import BeliefStore

from core.physics_engine import PhysicsEngine
from core.preconscious import Preconscious
from core.scratchpad import Scratchpad
from llm.providers.base import ChatSession, ProviderConfig, create_session, detect_available_provider
from core.context_compressor import ContextCompressor
from core.office_runtime import (
    ContextCapsule,
    OfficeRelay,
    TurnEnvelope,
    office_first_enabled,
)

logger = logging.getLogger("helix.core.pulse_loop")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class PulseLoop:
    """Event-driven consciousness loop.

    The model's output is always internal monologue.
    External communication via FC tools: reply(), send_message().
    """

    # Pulse intervals (seconds) — 3-tier gradient
    ACTIVE_INTERVAL = 10       # 10s — fast response during conversation
    REGULAR_INTERVAL = 30      # 30s — autonomous task work
    RESTING_INTERVAL = 900     # 15 min default — overridden from config
    DORMANT_CHECK = 60         # How often to check for wake during sleep

    # Timeout durations for state transitions
    ACTIVE_TIMEOUT = 120       # 2 min no incoming → ACTIVE → REGULAR
    REGULAR_TIMEOUT = 600      # 10 min no activity → REGULAR → RESTING

    # Context window lifecycle thresholds
    FOCUS_DRIFT_THRESHOLD = 1.5
    TOKEN_WARNING_STEP = 500_000  # inject warning every 100k above this
    OVERFLOW_PART_CHAR_CAP = 40_000

    # Sleep schedule — loaded dynamically from config/config.json
    # Defaults (used when no config exists):
    SLEEP_START_HOUR = 23   # 11:00 PM (active_hours.end)
    SLEEP_START_MINUTE = 0
    SLEEP_END_HOUR = 8      # 8:00 AM  (active_hours.start)
    SLEEP_END_MINUTE = 0

    # Dream precipitation delay — how many seconds after sleep onset
    # before the dream engine spawns. Gives the system time to wind down.
    DREAM_DELAY_SECONDS = 300  # 5 minutes

    def __init__(
        self,
        memory_manager: MemoryManager,
        belief_store: BeliefStore,

        physics_engine: PhysicsEngine,
        preconscious: Preconscious,
        scratchpad: Scratchpad,
        tool_executor=None,
        channel_router=None,
        provider_config: Optional[ProviderConfig] = None,
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

        # Legacy local-text schema catalog. Native providers use ToolRegistry;
        # active task cognition keeps schemas off the main session entirely.
        self._tool_modes_path = Path(os.path.join("data", "tool_modes.json"))

        # LLM provider
        self._provider_config = provider_config or detect_available_provider()
        if self._provider_config:
            logger.info(
                f"Provider: {self._provider_config.provider_type} "
                f"({self._provider_config.model})"
            )
        else:
            logger.warning("No LLM provider available — running without conscious model")

        # Journal directory
        self._journal_dir = Path(journal_dir)
        self._journal_dir.mkdir(parents=True, exist_ok=True)

        # Callbacks
        self._thought_callback = thought_callback    # Called with each thought
        self._delivery_callback = delivery_callback  # Called for [REPLY:name]

        # Stability Sentinel — real-time Lagrangian monitor
        self.sentinel = sentinel

        # State
        self._state = "RESTING"
        self._pulse_count = 0
        self._previous_thoughts = ""
        self._last_event_time = 0
        self._memory_session_id = datetime.now().strftime("%Y%m%dT%H%M%S%f")

        # 3-tier activity tracking
        self._last_incoming_time = 0   # Last Telegram/audio message
        self._last_activity_time = 0   # Last outbound tool use or incoming

        # Context window lifecycle tracking
        self._session_focus_origin = None
        self._session_token_count = 0
        self._token_warning = ""  # set by _check_context_lifecycle

        # Track tools over recent pulses for activity threshold
        self._recent_tool_counts: List[int] = []

        # Reset-context support — tool sets these, pulse loop checks
        self._pending_context_reset = False
        self._pending_reset_prompt = ""

        # Event queue (thread-safe)
        self._event_queue: List[str] = []
        # Office-first preserves the event's structured provenance alongside
        # the legacy natural-text stream.  The old queue remains canonical
        # when the experiment is disabled.
        self._office_event_queue: List[TurnEnvelope] = []
        self._event_lock = threading.Lock()

        self._office_first_enabled = office_first_enabled()
        self._office_relay = None
        self._last_office_capsule: Optional[ContextCapsule] = None
        self._office_last_token_count = 0
        if self._office_first_enabled:
            self._office_relay = OfficeRelay(
                self.memory,
                self.beliefs,
                self.physics,
                unified=getattr(self.preconscious, "_unified", None),
            )
            logger.info(
                "Office-first context mode enabled: typed intake, fresh context "
                "capsules, stateless speaking sessions"
            )

        # Chat session (managed by pulse loop)
        self._chat: Optional[ChatSession] = None

        # Optional event-driven task layer. Wired after construction in
        # main.py so it can share this loop's event stream without creating a
        # circular dependency during boot.
        self._task_cognition = None

        # Thread control
        self._running = False
        self._thread = None
        self._wake_event = threading.Event()

        # Dream engine reference (set via set_dream_engine)
        self._dream_engine = None

        # Context compressor — rolling context management
        context_window = (
            provider_config.context_window if provider_config else 1_000_000
        )
        self._compressor = ContextCompressor(
            context_length=context_window,
            threshold_percent=0.50,
            emergency_percent=0.80,
            protect_first_n=2,
        )

        # Dynamic toolset state — load from config instead of hardcoding
        self._active_toolsets = self._load_toolsets_from_config()
        self._pending_toolset_rebuild = False
        self._pulse_turn_counter = 0
        cfg = self._load_config()
        self._auto_disengage_threshold = cfg.get("auto_disengage_turns", 2)

        # Initialize tracking for startup toolsets
        from tools.tool_registry import registry
        for ts in self._active_toolsets:
            registry.record_toolset_active(ts, self._pulse_turn_counter)

        # Load sleep schedule from config
        self._load_schedule_from_config()

        # Share active toolsets reference with preconscious for
        # toolset awareness hints (Tier 1c of cognitive integration)
        self.preconscious._active_toolsets = self._active_toolsets

        # Idle consolidation tracking — prevents repeated runs per idle
        self._consolidation_ran_this_idle = False

        # Nightly dream cycle tracking — prevents repeated runs per night
        self._dream_cycle_ran_tonight = False
        self._dream_cycle_last_date = None

        # Dream onset tracking — when the agent first entered DORMANT
        # this sleep cycle, used to enforce the 5-minute dream delay
        self._dormant_entry_time = None

        # Pending belief processing — runs once per sleep window
        self._pending_beliefs_ran_tonight = False

        # Rolling blacklist for identity premises — forces rotation so
        # Helix engages with different facets of his identity across sessions.
        # Maps belief content hash → rebuild count when it was shown.
        self._premise_blacklist: Dict[str, int] = {}
        self._sysinstruction_rebuild_count = 0
        self._newly_engaged_toolsets = set()

        # 429 rate-limit flag — when set, forces fallback model usage
        # and blocks the success-path restore. Cleared on morning wake-up.
        self._rate_limited = False

        # Load tool format from config or env
        tool_format_val = cfg.get("tool_format", "api")
        self._tool_format = os.environ.get("HELIX_TOOL_FORMAT", tool_format_val).lower()
        
        # Tool dispatcher for local tool formatting
        if self._tool_format == "local":
            from core.tool_dispatcher import ToolDispatcher
            self._tool_dispatcher = ToolDispatcher(self.tool_executor)
            logger.info("LOCAL tool format activated with ToolDispatcher")
        else:
            self._tool_dispatcher = None

    def set_dream_engine(self, daemon):
        """Wire the background daemon for rollover snapshots."""
        self._dream_engine = daemon

    def set_task_cognition_controller(self, controller):
        """Attach the natural-intention task controller before the loop starts."""
        self._task_cognition = controller

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self):
        """Start the consciousness thread."""
        self._running = True
        # Start RESTING — Helix waits for input or hourly pulse (or DORMANT if sleep hours)
        self._state = "RESTING" if not self._is_sleep_hours() else "DORMANT"
        self._last_event_time = time.time()  # Initialize for emergence timer
        self._thread = threading.Thread(
            target=self._main_loop, daemon=True, name="helix_pulse"
        )
        self._thread.start()
        logger.info(f"Pulse loop started — {self._state}")

    def stop(self):
        """Stop the consciousness loop."""
        self._running = False
        self._wake_event.set()
        self._state = "DORMANT"
        if self._chat is not None:
            try:
                self._chat.close()
            except Exception as e:
                logger.debug("Provider close during stop failed: %s", e)
        if self._task_cognition is not None:
            try:
                self._task_cognition.shutdown()
            except Exception as e:
                logger.debug("Task cognition shutdown failed: %s", e)
        logger.info("Pulse loop stopped")

    def _reset_session(self, reason: str):
        """Destroy current session and prepare for a fresh one."""
        logger.info(f"Context window reset — reason: {reason}")
        if self._chat is not None:
            try:
                self._chat.close()
            except Exception as e:
                logger.debug("Provider close during reset failed: %s", e)
        self._chat = None  # Will be recreated on next _ensure_session()
        self._session_focus_origin = None if self.physics.attention_center is None else self.physics.attention_center.copy()
        self._session_token_count = 0
        self._token_warning = ""
        self.preconscious.reset_lexicon_blacklist()
        # Clear premise blacklist on context compression — fresh identity grounding
        self._premise_blacklist.clear()
        self._sysinstruction_rebuild_count = 0
        logger.info("Premise blacklist cleared (context compression)")

    def request_context_reset(self, prompt: str = ""):
        """Request a context window reset with an optional initial prompt.

        Called by the reset_context tool. The actual reset happens at the
        end of the current pulse — the prompt is injected as the first
        event in the new session so Helix picks up the new thread.
        """
        self._pending_context_reset = True
        self._pending_reset_prompt = prompt
        logger.info(f"Context reset requested — prompt: {prompt[:100]}...")

    def wake(self, trigger: str = "external"):
        """Wake Helix — promote to ACTIVE from any non-ACTIVE state."""
        if self._state in ("DORMANT", "RESTING"):
            prev = self._state
            self._state = "ACTIVE"
            self._consolidation_ran_this_idle = False  # Reset for next idle
            self._wake_event.set()
            logger.info(f"{prev} → ACTIVE — trigger: {trigger}")
        elif self._state == "ACTIVE":
            # Already active, just make sure the wake event is set
            self._wake_event.set()

    # ── Event Injection ──────────────────────────────────────────────

    def emit(self, event_type: str, data: Dict[str, Any]):
        """Inject an event into the consciousness stream.

        Events queue up and get processed on the next pulse.
        """
        text = self._translate_event(event_type, data)
        if text:
            with self._event_lock:
                self._event_queue.append(text)
                if self._office_first_enabled:
                    self._office_event_queue.append(
                        TurnEnvelope.from_event(event_type, data)
                    )
            self._last_event_time = time.time()

            # Main comms channels → immediate ACTIVE for fast response
            if event_type in {
                "user_message", "incoming_message", "telegram_message",
            }:
                now = time.time()
                if (
                    not getattr(self, "_memory_session_id", "")
                    or not self._last_incoming_time
                    or now - self._last_incoming_time > self.REGULAR_TIMEOUT
                ):
                    self._memory_session_id = datetime.now().strftime(
                        "%Y%m%dT%H%M%S%f"
                    )
                self._last_incoming_time = now
                self._last_activity_time = now
                if self._state != "ACTIVE":
                    self.wake(trigger=f"event: {event_type}")
            # Nudge sentinel omega on relevant events
            if self.sentinel:
                if event_type in {
                    "user_message", "incoming_message", "telegram_message",
                }:
                    self.sentinel.nudge_omega_from_event("incoming_message")

    def _translate_event(self, event_type: str, data: Dict[str, Any]) -> str:
        """Translate a structured event into natural text for the pulse."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        if event_type in {
            "user_message", "incoming_message", "telegram_message",
        }:
            sender = data.get("sender", "Someone")
            content = data.get("content", "")
            channel = data.get("channel", "direct")

            # Track inbound channel for [REPLY:] routing
            if self.channel_router:
                self.channel_router.track_inbound(
                    sender=sender,
                    channel=channel,
                    chat_id=data.get("chat_id"),
                )

            return f"[{timestamp}] {sender} is talking to me via {channel}. They said: \"{content}\""

        if event_type == "tool_result":
            tool = data.get("tool", "unknown")
            result = data.get("result", "")
            return f"[{timestamp}] Tool [{tool}] returned: {result}"

        if event_type == "task_result":
            objective = data.get("objective", "a task I formed")
            result = data.get("result", "")
            state = "completed" if data.get("success") else "did not complete"
            return (
                f"[{timestamp}] (my focused work {state}) {objective}. "
                f"What came back into awareness: {result}"
            )

        if event_type == "schedule_trigger":
            description = data.get("description", "something")
            return f"[{timestamp}] (a reminder surfaces) {description}"

        if event_type == "system":
            message = data.get("message", "")
            return f"[{timestamp}] [system] {message}"

        # Generic fallback
        return f"[{timestamp}] [{event_type}] {data}"

    def _drain_events(self) -> List[str]:
        """Grab all queued events."""
        with self._event_lock:
            events = self._event_queue.copy()
            self._event_queue.clear()
        return events

    def _drain_office_events(self) -> List[TurnEnvelope]:
        """Drain the typed mirror used only by Office-first mode."""
        with self._event_lock:
            events = self._office_event_queue.copy()
            self._office_event_queue.clear()
        return events

    def _inject_event(self, text: str):
        """Inject a raw event string directly into the queue.

        Used internally to push results back for the next pulse.
        Does NOT reset _last_event_time — only message events
        (inbound/outbound) should keep ACTIVE mode alive.
        """
        with self._event_lock:
            self._event_queue.append(text)
            if self._office_first_enabled:
                self._office_event_queue.append(TurnEnvelope.from_event(
                    "system",
                    {"message": text, "source_kind": "system"},
                ))

    # ── Main Loop ────────────────────────────────────────────────────

    @staticmethod
    def _load_config() -> dict:
        """Load config/config.json if it exists."""
        config_path = Path(__file__).parent.parent / "config" / "config.json"
        if config_path.exists():
            try:
                with open(config_path, "r") as f:
                    return json.load(f)
            except Exception:
                pass
        return {}

    def _load_schedule_from_config(self):
        """Load wake/sleep schedule from config/config.json → active_hours.

        The wizard stores active hours (when the agent is awake).
        Sleep is the inverse: from active_hours.end to active_hours.start.

        Example: active_hours = {"start": "08:00", "end": "23:00"}
          → Sleep window: 23:00 → 08:00
          → SLEEP_START_HOUR=23, SLEEP_START_MINUTE=0
          → SLEEP_END_HOUR=8, SLEEP_END_MINUTE=0
        """
        cfg = self._load_config()
        active_hours = cfg.get("active_hours", {})
        wake_str = active_hours.get("start", "08:00")
        sleep_str = active_hours.get("end", "23:00")

        try:
            s_parts = sleep_str.split(":")
            self.SLEEP_START_HOUR = int(s_parts[0])
            self.SLEEP_START_MINUTE = int(s_parts[1]) if len(s_parts) > 1 else 0

            w_parts = wake_str.split(":")
            self.SLEEP_END_HOUR = int(w_parts[0])
            self.SLEEP_END_MINUTE = int(w_parts[1]) if len(w_parts) > 1 else 0
        except (ValueError, IndexError) as e:
            logger.warning(f"Invalid schedule in config, using defaults: {e}")
            self.SLEEP_START_HOUR = 23
            self.SLEEP_START_MINUTE = 0
            self.SLEEP_END_HOUR = 8
            self.SLEEP_END_MINUTE = 0

        logger.info(
            f"Schedule loaded: sleep {self.SLEEP_START_HOUR:02d}:{self.SLEEP_START_MINUTE:02d}"
            f" → wake {self.SLEEP_END_HOUR:02d}:{self.SLEEP_END_MINUTE:02d}"
        )

        # Resting pulse rate (how often the agent thinks autonomously when idle)
        resting_minutes = cfg.get("resting_pulse_minutes", 15)
        resting_minutes = max(5, min(60, resting_minutes))  # Clamp to 5-60
        self.RESTING_INTERVAL = resting_minutes * 60
        if resting_minutes != 15:
            logger.info(f"Resting pulse rate: every {resting_minutes} min ({self.RESTING_INTERVAL}s)")

    def _load_toolsets_from_config(self) -> set:
        """Load tool_set from config/config.json.

        Falls back to {"core"} if config doesn't exist or has no tool_set.
        """
        cfg = self._load_config()
        tool_set = cfg.get("tool_set", ["core"])
        toolsets = set(tool_set)
        # Ensure core is always present
        toolsets.add("core")
        if toolsets != {"core"}:
            logger.info(f"Toolsets loaded from config: {', '.join(sorted(toolsets))}")
        return toolsets

    def _is_sleep_hours(self) -> bool:
        """Check if current time is within the sleep window.

        Handles midnight-wrap correctly:
          - sleep 23:00 → wake 08:00 (wraps midnight)
          - sleep 01:00 → wake 06:00 (same side of midnight)
        """
        now = datetime.now()
        current_minutes = now.hour * 60 + now.minute
        sleep_start = self.SLEEP_START_HOUR * 60 + self.SLEEP_START_MINUTE
        sleep_end = self.SLEEP_END_HOUR * 60 + self.SLEEP_END_MINUTE

        if sleep_start <= sleep_end:
            # Same side of midnight (e.g., 01:00 → 06:00)
            return sleep_start <= current_minutes < sleep_end
        else:
            # Wraps midnight (e.g., 23:00 → 08:00)
            return current_minutes >= sleep_start or current_minutes < sleep_end

    def _main_loop(self):
        """Main consciousness thread — event-driven state machine.

        States:
          DORMANT — sleep hours (configurable), periodic wake check
          RESTING — awake, configurable low-cadence autonomous pulse
          REGULAR — 30s task-follow-through pulses; rests after 10 min idle
          ACTIVE  — 10s interactive pulses; becomes REGULAR after 2 min idle
        """
        while self._running:

            # ── Sleep Schedule (from config/config.json) ──────────
            if self._is_sleep_hours():
                if self._state != "DORMANT":
                    logger.info(
                        f"{self._state} → DORMANT (sleep hours: "
                        f"{self.SLEEP_START_HOUR:02d}:{self.SLEEP_START_MINUTE:02d}"
                        f"–{self.SLEEP_END_HOUR:02d}:{self.SLEEP_END_MINUTE:02d})"
                    )
                    self._state = "DORMANT"
                    self._dormant_entry_time = time.time()

                # ── Pending Belief Processing ──────────────────────
                #    Now handled by the Curator as Phase 6, after it
                #    writes candidates in Phase 4. Previously this ran
                #    as a parallel thread and hit a race condition —
                #    the batch_service would start before the Curator
                #    had written anything to pending_beliefs.json.

                # ── Nightly Dream Cycle (Curator) ─────────────────
                #    Full Phase 1-5: extraction, consolidation,
                #    compounding, integration, lexicon sync.
                #    Runs once per night in a daemon thread.
                #    Delayed by DREAM_DELAY_SECONDS (5 min) after
                #    sleep onset to allow proper wind-down.
                current_date = datetime.now().date()
                dormant_elapsed = (
                    time.time() - self._dormant_entry_time
                    if self._dormant_entry_time else float('inf')
                )
                if (self._dream_engine
                        and getattr(self, "_dream_cycle_last_date", None) != current_date
                        and dormant_elapsed >= self.DREAM_DELAY_SECONDS):
                    self._dream_cycle_last_date = current_date
                    logger.info(
                        f"Sleep cycle: spawning nightly dream cycle "
                        f"({dormant_elapsed:.0f}s after sleep onset)"
                    )
                    threading.Thread(
                        target=self._dream_engine.run_dream_cycle,
                        daemon=True,
                        name="helix_dream_cycle",
                    ).start()

                # During sleep, just check periodically for forced wake
                self._wake_event.wait(timeout=self.DORMANT_CHECK)
                if self._wake_event.is_set():
                    self._wake_event.clear()
                continue
            elif self._state == "DORMANT":
                # Sleep window ended — wake up to RESTING
                self._state = "RESTING"
                self._last_event_time = time.time()
                self._pending_beliefs_ran_tonight = False  # Reset for next night
                self._dormant_entry_time = None  # Reset dream delay tracker

                # Clear 429 rate-limit parking
                if self._rate_limited:
                    self._rate_limited = False
                    self._consecutive_429s = 0
                    self._fallback_successes = 0
                    self._restore_failures = 0
                    # Restore primary model (provider-aware)
                    wake_provider = (
                        self._provider_config.provider_type
                        if self._provider_config else ""
                    )
                    if wake_provider == "anthropic":
                        _PRIMARY_MODEL = "claude-fable-5"
                    elif wake_provider == "codex_cli":
                        _PRIMARY_MODEL = getattr(self._chat, "_model", "")
                    else:
                        _PRIMARY_MODEL = "gemini-2.5-flash"
                    if wake_provider != "codex_cli" and hasattr(self._chat, 'switch_model'):
                        current = getattr(self._chat, '_model', '')
                        if current != _PRIMARY_MODEL:
                            try:
                                self._chat.switch_model(_PRIMARY_MODEL)
                                logger.info(f"429 cleared — restored primary model: {_PRIMARY_MODEL}")
                            except Exception as e:
                                logger.error(f"Model restore on wake failed: {e}")
                    logger.info("DORMANT → RESTING (sleep ended, 429 parking cleared, good morning)")
                else:
                    logger.info("DORMANT → RESTING (sleep ended, good morning)")

            # ── Rate-Limit Gate ───────────────────────────────────
            #    API providers switch fallback models; subscription Codex
            #    parks briefly because Helix cannot choose account fallbacks.
            codex_parked = False
            if self._rate_limited:
                provider_type = (
                    self._provider_config.provider_type
                    if self._provider_config else ""
                )
                if provider_type == "codex_cli":
                    retry_at = getattr(self, "_codex_rate_limit_retry_at", 0)
                    if time.time() < retry_at:
                        codex_parked = True
                        logger.debug("Codex subscription usage is parked until retry window")
                    else:
                        self._rate_limited = False
                        self._consecutive_429s = 0
                        logger.info("Codex subscription retry window opened")
                elif provider_type == "anthropic":
                    _FALLBACK = "claude-opus-4-8"
                else:
                    _FALLBACK = "gemini-3.1-flash-lite-preview"
                if not codex_parked and provider_type != "codex_cli" and self._chat is not None:
                    # Session exists — switch model if needed
                    if hasattr(self._chat, 'switch_model'):
                        current = getattr(self._chat, '_model', '')
                        if current != _FALLBACK:
                            try:
                                self._chat.switch_model(_FALLBACK)
                                logger.info(f"Rate-limited — forced fallback model: {_FALLBACK}")
                            except Exception as e:
                                logger.error(f"Rate-limit model switch failed: {e}")
                elif not codex_parked and provider_type != "codex_cli" and self._provider_config:
                    # No session yet — override provider config so session
                    # is created with fallback model instead of primary
                    if self._provider_config.model != _FALLBACK:
                        logger.info(
                            f"Rate-limited — overriding boot model: "
                            f"{self._provider_config.model} → {_FALLBACK}"
                        )
                        self._provider_config.model = _FALLBACK

            # ── Pulse Execution ──────────────────────────────────
            if not codex_parked:
                try:
                    self._pulse()
                except Exception as e:
                    logger.error("Pulse crashed due to an unhandled exception", exc_info=True)
                self._check_context_lifecycle()

            # ── 3-Tier State Transitions ──────────────────────────
            if self._state == "ACTIVE":
                if time.time() - self._last_incoming_time > self.ACTIVE_TIMEOUT:
                    self._state = "REGULAR"
                    self._last_activity_time = time.time()  # Start REGULAR timer
                    logger.info("ACTIVE → REGULAR (2 min no incoming)")

            elif self._state == "REGULAR":
                if time.time() - self._last_activity_time > self.REGULAR_TIMEOUT:
                    self._state = "RESTING"
                    logger.info("REGULAR → RESTING (10 min no activity)")

            # ── Idle Consolidation (Curator-Style) ───────────────
            #    When idle for 2+ hours, run lightweight belief
            #    maintenance in the background (merge/decay/archive).
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



            # ── Wait for next interval ───────────────────────────
            interval = {
                "ACTIVE": self.ACTIVE_INTERVAL,
                "REGULAR": self.REGULAR_INTERVAL,
                "RESTING": self.RESTING_INTERVAL,
            }.get(self._state, self.RESTING_INTERVAL)
            self._wake_event.wait(timeout=interval)
            if self._wake_event.is_set():
                self._wake_event.clear()

    def _check_context_lifecycle(self, force_drift_check: bool = False):
        """Check context window health and trigger compression if needed.

        Replaces the old hard-reset approach with rolling compression.
        Focus drift and token count both trigger compression instead
        of wiping the entire session.
        """
        if not self._chat:
            self._token_warning = ""
            return

        # 1. Focus drift — log only, no compression trigger.
        #    Previously this wiped context on every RESTING pulse,
        #    destroying cognitive continuity. Token-based compression
        #    handles context window management instead.
        if self._session_focus_origin is not None and self.physics.attention_center is not None:
            current = self.physics.attention_center
            drift = float(np.linalg.norm(current - self._session_focus_origin))
            if drift > self.FOCUS_DRIFT_THRESHOLD:
                logger.debug(f"Focus drift {drift:.2f} (logged, no compression)")

        # 2. Token count — check if compression is needed
        if (self._session_token_count > 0
                and self._compressor.should_compress(self._session_token_count)):
            # Suppress standard compression while ACTIVE unless it hits emergency threshold
            if self._state == "ACTIVE" and self._session_token_count < self._compressor.emergency_tokens:
                pass
            else:
                logger.info(
                    f"Token count {self._session_token_count} exceeds threshold "
                    f"— triggering context compression"
                )
                self._compress_context("token_threshold")
                return

        # 3. Token warning (informational, for the pulse message)
        if self._session_token_count > self.TOKEN_WARNING_STEP:
            rounded = (self._session_token_count // 100_000) * 100
            self._token_warning = f"(context window: ~{rounded}k tokens)"
        else:
            self._token_warning = ""

    def _compress_context(self, reason: str):
        """Compress the current context window using rolling summarization.

        Replaces the old _reset_session() hard wipe. Extracts history,
        runs the 3-phase compressor, and rebuilds the session with
        compressed history.
        """
        if not self._chat or not hasattr(self._chat, 'get_history'):
            logger.warning(
                "Cannot compress — session doesn't support get_history()"
            )
            return

        # Extract current history
        history = self._chat.get_history()
        if not history or len(history) < 6:
            logger.info(
                "Context too short for compression (%d messages) — skipping",
                len(history),
            )
            return

        # Get spatial state for the summary
        spatial_state = self.physics.get_spatial_state()

        # Run compressor
        compressed = self._compressor.compress(
            messages=history,
            current_tokens=self._session_token_count,
            spatial_state=spatial_state,
        )

        # Replace session history
        if len(compressed) < len(history):
            self._chat.replace_history(compressed)
            self._session_token_count = 0  # Will be updated on next pulse
            self._token_warning = ""
            # Reset lexicon blacklist — new context window means lexicon
            # entries should re-inject if their terms appear again.
            self.preconscious.reset_lexicon_blacklist()
            # Invalidate entropy baseline — manifold may have drifted
            # significantly since last baseline was sampled.
            self.physics.spatial_mind.belief_space.invalidate_entropy_baseline()
            self.physics.spatial_mind.memory_space.invalidate_entropy_baseline()
            # Prune cold trail particles — compression pass is the natural
            # cleanup point. Old trails have already contributed to belief
            # precipitation or faded below gravitational relevance.
            b_pruned = self.physics.spatial_mind.belief_space.decay_trail_particles()
            m_pruned = self.physics.spatial_mind.memory_space.decay_trail_particles()
            logger.info(
                f"Context compressed ({reason}): {len(history)} → "
                f"{len(compressed)} messages"
                f"{f' (trails pruned: {b_pruned}b/{m_pruned}m)' if b_pruned + m_pruned > 0 else ''}"
            )
        else:
            logger.info(
                "Compression produced no savings — skipping replacement"
            )

    def _recover_from_overflow(self):
        """Recover from an input-token overflow (provider hard limit).

        The compressor is message-count-based and protects the recent
        tail — a single giant tool result parked there survives normal
        compression (observed: 80 → 6 messages that still measured
        ~995K tokens). This walks EVERY message, hard-truncates any
        oversized part, refreshes the token estimate from actual history
        size, and then runs normal compression on the cleaned history.
        """
        if not self._chat or not hasattr(self._chat, 'get_history'):
            return

        try:
            history = self._chat.get_history()
            truncated_parts = 0

            def _truncate(text: str) -> str:
                nonlocal truncated_parts
                if not isinstance(text, str) or len(text) <= self.OVERFLOW_PART_CHAR_CAP:
                    return text
                truncated_parts += 1
                half = self.OVERFLOW_PART_CHAR_CAP // 2
                return (
                    text[:half]
                    + "\n[... truncated during context recovery ...]\n"
                    + text[-half:]
                )

            for msg in history:
                for part in msg.get("parts", msg.get("content", []) or []):
                    if not isinstance(part, dict):
                        continue
                    if "text" in part:
                        part["text"] = _truncate(part["text"])
                    elif "function_response" in part:
                        resp = part["function_response"].get("response", {})
                        if isinstance(resp, dict) and "result" in resp:
                            resp["result"] = _truncate(resp["result"])
                    elif part.get("type") == "tool_result":
                        part["content"] = _truncate(part.get("content", ""))

            if truncated_parts:
                self._chat.replace_history(history)

            # Queued tool responses from the failed turn re-attach on
            # every retry — truncate them in place. (Not cleared: their
            # function_call turns are already committed in history, and
            # a call without a response violates the FC protocol.)
            for res in getattr(self._chat, '_native_tool_responses', []) or []:
                resp = res.get("response")
                if isinstance(resp, dict) and "result" in resp:
                    resp["result"] = _truncate(resp["result"])
            for blk in getattr(self._chat, '_pending_tool_result_blocks', []) or []:
                if isinstance(blk, dict) and "content" in blk:
                    blk["content"] = _truncate(blk.get("content", ""))

            # Refresh the token estimate from what's actually left
            # (~3.5 chars/token) so the normal lifecycle check has real
            # numbers instead of the stale pre-overflow count.
            est_tokens = int(self._chat.get_history_size() / 3.5)
            self._session_token_count = est_tokens

            logger.info(
                "Overflow recovery: %d oversized parts truncated, "
                "~%dk tokens estimated remaining",
                truncated_parts, est_tokens // 1000,
            )

            if self._compressor.should_compress(est_tokens):
                self._compress_context("overflow_recovery")
        except Exception as e:
            logger.error(f"Overflow recovery failed: {e}", exc_info=True)
            # Last resort — a fresh session beats a permanently wedged one
            self._reset_session("overflow_recovery_failed")

    # ── The Pulse ────────────────────────────────────────────────────

    def _pulse(self):
        """Single pulse cycle — the core of consciousness.

        1. Drain events
        2. Fire pre-conscious
        3. Assemble pulse message
        4. Send to LLM
        5. Parse output for action tags
        6. Store everything to memory
        7. Update physics
        """
        self._pulse_count += 1
        self._pulse_turn_counter += 1
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Check for auto-disengage of idle toolsets
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
                    logger.info(f"Auto-disengaged idle toolset: {ts} (inactive for {self._auto_disengage_threshold} turns)")
                self._pending_toolset_rebuild = True
        except Exception as e:
            logger.error(f"Failed to check auto-disengage: {e}")

        # 0. Snapshot sentinel state BEFORE the pulse fires.
        #    This captures the clean baseline for computing stability
        #    deltas — how much this pulse changed the system's state.
        lagrangian_before = None
        if self.sentinel:
            lagrangian_before = self.sentinel.get_lagrangian_snapshot()

        # 1. Drain events
        events = self._drain_events()
        office_envelopes = (
            self._drain_office_events() if self._office_first_enabled else []
        )
        office_capsule: Optional[ContextCapsule] = None

        if self._office_first_enabled:
            # The Office replaces automatic preconscious injection.  mRAG,
            # cases, beliefs, affect, continuity, and raw 8D remain available
            # as independent evidence desks inside the coordinator.
            annotations, ambient = [], None
            injected_belief_ids, cluster_centroid = [], None
            self._newly_engaged_toolsets.clear()
        else:
            # 2. Pre-conscious injection
            #    Returns inline annotations + ambient state notes.
            #    Annotations get woven into the event stream below.
            annotations, ambient, injected_belief_ids, cluster_centroid = self.preconscious.inject(
                previous_thought=self._previous_thoughts[:500],
                incoming_events=events if events else None,
                trigger_type="user_message" if events else "llm_output",
                active_toolsets=self._active_toolsets,
                newly_engaged_toolsets=self._newly_engaged_toolsets,
            )
            self._newly_engaged_toolsets.clear()

        # Snapshot of the DRAINED events for failure re-queue. Sensory
        # observations appended below are per-pulse ambient readings —
        # re-queueing them on API failure made the retry payload grow
        # by one vision/audio line per failed pulse, monotonically.
        requeue_events = list(events)
        requeue_office_envelopes = list(office_envelopes)

        # 2b. Sensory Cortex Tick
        if getattr(self, "sensory_cortex", None):
            sensory_data = self.sensory_cortex.pulse_tick()
            if sensory_data:
                events.append(sensory_data["content"])
                if self._office_first_enabled:
                    office_envelopes.append(TurnEnvelope.from_event(
                        "sensory",
                        {
                            **sensory_data,
                            "source_kind": "sensory",
                        },
                    ))


        # 3. Assemble pulse message
        if self._office_first_enabled and self._office_relay is not None:
            office_capsule = self._office_relay.prepare(
                office_envelopes,
                pulse_count=self._pulse_count,
            )
            self._last_office_capsule = office_capsule
            injected_belief_ids = office_capsule.injected_belief_ids
            pulse_message = office_capsule.rendered_prompt
        else:
            pulse_message = self._build_pulse_message(
                events=events,
                annotations=annotations,
                ambient=ambient,
                timestamp=timestamp,
            )

        # 4. Send to LLM
        thought = (
            self._send_office_pulse(pulse_message)
            if office_capsule is not None
            else self._send_pulse(pulse_message)
        )

        # Record tool usage in the registry for this turn
        try:
            tool_calls_snapshot = []
            if hasattr(self._chat, 'get_last_tool_calls'):
                tool_calls_snapshot = self._chat.get_last_tool_calls() or []
            
            from tools.tool_registry import registry
            for tc in tool_calls_snapshot:
                name = None
                if isinstance(tc, dict):
                    name = tc.get("name")
                elif hasattr(tc, "name"):
                    name = tc.name
                
                if name:
                    registry.record_tool_use(name, self._pulse_turn_counter)
        except Exception as e:
            logger.debug(f"Failed to record tool usage: {e}")

        # 4b. If we got a 429, back off and optionally fallback model
        provider_type = self._provider_config.provider_type if self._provider_config else ""
        if provider_type == "anthropic":
            _FALLBACK_MODEL = "claude-opus-4-8"
            _PRIMARY_MODEL = "claude-fable-5"
        elif provider_type == "codex_cli":
            # ChatGPT subscription accounts do not have Helix-controlled
            # fallback models. Keep the selected/account-default model.
            _FALLBACK_MODEL = None
            _PRIMARY_MODEL = getattr(self._chat, "_model", "")
        else:
            _FALLBACK_MODEL = "gemini-3.1-flash-lite-preview"
            _PRIMARY_MODEL = "gemini-2.5-flash"
        # How many consecutive successes on fallback before trying primary again.
        _FALLBACK_COOLDOWN_PULSES = 10
        # How many failed restore attempts before hard-locking to fallback
        # until the morning wake-up clears it.
        _MAX_RESTORE_FAILURES = 2

        # Provider-level failure detection. Providers return an error
        # string with this exact prefix when the API call throws — only
        # that counts as a failed pulse.
        is_api_error = bool(thought) and thought.startswith("[internal error:")
        is_rate_limited_error = is_api_error and (
            "429" in thought
            or "RESOURCE_EXHAUSTED" in thought
            or "rate_limit" in thought.lower()
            or "usage limit" in thought.lower()
            or "usagelimitexceeded" in thought.lower()
            or "usage_limit" in thought.lower()
        )

        if is_api_error:
            # The drained events never reached the model (providers only
            # commit history on success). Re-queue them at the front so
            # the next pulse retries — otherwise user messages vanish.
            if requeue_events:
                with self._event_lock:
                    self._event_queue = (requeue_events + self._event_queue)[:30]
                    if self._office_first_enabled:
                        self._office_event_queue = (
                            requeue_office_envelopes + self._office_event_queue
                        )[:30]

        if not is_api_error and thought and thought.startswith("[no LLM session"):
            # No provider — keep events queued for when one appears
            if requeue_events:
                with self._event_lock:
                    self._event_queue = (requeue_events + self._event_queue)[:30]
                    if self._office_first_enabled:
                        self._office_event_queue = (
                            requeue_office_envelopes + self._office_event_queue
                        )[:30]
            return

        if is_rate_limited_error:
            self._consecutive_429s = getattr(self, '_consecutive_429s', 0) + 1
            self._fallback_successes = 0  # Reset cooldown on any 429
            restore_failures = getattr(self, '_restore_failures', 0)

            if provider_type == "codex_cli":
                self._rate_limited = True
                self._codex_rate_limit_retry_at = time.time() + 300
                logger.warning(
                    "Codex subscription usage limit reached — parking conscious "
                    "turns for 5 minutes before retry (no Gemini fallback)."
                )
            elif restore_failures >= _MAX_RESTORE_FAILURES:
                # Already exhausted restore attempts — hard lock
                self._rate_limited = True
                logger.warning(
                    f"429 #{self._consecutive_429s} — {restore_failures} "
                    f"restore attempts already failed. Hard-locked to "
                    f"fallback until morning."
                )
            elif self._consecutive_429s >= 2:
                # 2nd consecutive 429 without any fallback success — park
                self._rate_limited = True
                logger.warning(
                    f"429 #{self._consecutive_429s} — rate limit confirmed. "
                    f"Parking until morning wake-up."
                )
            else:
                # 1st 429 — switch to fallback model and keep going
                logger.warning(
                    f"429 #{self._consecutive_429s} — switching to "
                    f"fallback model: {_FALLBACK_MODEL}"
                )
                if _FALLBACK_MODEL and hasattr(self._chat, 'switch_model'):
                    current = getattr(self._chat, '_model', '')
                    if current != _FALLBACK_MODEL:
                        try:
                            self._chat.switch_model(_FALLBACK_MODEL)
                        except Exception as e:
                            logger.error(f"Model switch failed: {e}")

            return  # Skip parsing/storing this error pulse
        elif is_api_error and (
            "exceeds the maximum number of tokens" in thought
            or "input token count" in thought.lower()
        ):
            # Input overflow — force recovery
            logger.warning("Pulse failed on input overflow — forcing recovery")
            self._recover_from_overflow()
            return
        elif is_api_error:
            # Transient non-429 API failure (network, 5xx, …).
            logger.warning(f"Pulse skipped — API error: {thought[:200]}")
            return
        else:
            # Success — count consecutive successes on fallback before restoring primary
            # BUT: if _rate_limited is set, don't try to restore — wait for morning.
            if self._rate_limited:
                # Running on fallback by design — don't attempt restore
                self._consecutive_429s = 0
                self._fallback_successes = 0
            elif getattr(self, '_consecutive_429s', 0) > 0:
                if hasattr(self._chat, '_model'):
                    current = getattr(self._chat, '_model', '')
                    if _FALLBACK_MODEL and current == _FALLBACK_MODEL:
                        self._fallback_successes = getattr(self, '_fallback_successes', 0) + 1
                        if self._fallback_successes >= _FALLBACK_COOLDOWN_PULSES:
                            logger.info(
                                f"429 cleared — {self._fallback_successes} consecutive "
                                f"successes on fallback, restoring primary: {_PRIMARY_MODEL}"
                            )
                            try:
                                self._chat.switch_model(_PRIMARY_MODEL)
                            except Exception as e:
                                logger.error(f"Model restore failed: {e}")
                            # DO NOT reset _restore_failures here — track across attempts
                            self._consecutive_429s = 0
                            self._fallback_successes = 0
                            # Increment restore attempt counter
                            self._restore_failures = getattr(self, '_restore_failures', 0) + 1
                            logger.info(
                                f"Restore attempt #{self._restore_failures}/"
                                f"{_MAX_RESTORE_FAILURES} — if primary 429s again, "
                                f"{'will hard-lock to fallback' if self._restore_failures >= _MAX_RESTORE_FAILURES else 'will retry once more'}"
                            )
                        else:
                            logger.debug(
                                f"Fallback cooldown: {self._fallback_successes}/"
                                f"{_FALLBACK_COOLDOWN_PULSES} successes before "
                                f"restoring primary"
                            )
                self._consecutive_429s = 0
                self._fallback_successes = 0
            else:
                # Healthy pulse on the primary model. After a stretch of
                # clean pulses, forgive past restore attempts.
                if getattr(self, '_restore_failures', 0) > 0:
                    current = getattr(self._chat, '_model', '')
                    if current == _PRIMARY_MODEL:
                        self._primary_successes = getattr(self, '_primary_successes', 0) + 1
                        if self._primary_successes >= _FALLBACK_COOLDOWN_PULSES:
                            logger.info(
                                f"{self._primary_successes} clean pulses on primary — "
                                f"resetting restore-failure counter"
                            )
                            self._restore_failures = 0
                            self._primary_successes = 0
                    else:
                        self._primary_successes = 0

        # Office-first speaking turns are already external responses.  Delivery
        # is host-controlled; the local model never needs a reply tool/schema.
        if office_capsule is not None and office_capsule.response_mode == "respond":
            self._deliver_office_output(office_capsule, thought)

        # 5b. Tool result queueing — results are now events for next pulse.
        if hasattr(self._chat, 'get_pending_tool_results'):
            pending = self._chat.get_pending_tool_results()
            if pending:
                for tr in pending:
                    # 3000 chars (was 1000) for perception scans
                    self.emit("tool_result", {
                        "tool": tr["name"],
                        "result": tr["result"][:3000],
                    })

        # 5. Parse output for action tags
        if office_capsule is None:
            self._parse_output(thought)



        # 5c. Log tools used and track outbound tools for rate tier
        tool_count_this_pulse = 0
        if hasattr(self._chat, 'get_last_tool_calls'):
            tool_calls = self._chat.get_last_tool_calls()
            if tool_calls:
                tool_names = [tc['name'] for tc in tool_calls]
                tool_count_this_pulse = len(tool_names)
                logger.info(f"FC tools used: {tool_names}")
                # Feed tool usage to preconscious for focus budget computation
                self.preconscious.record_tool_usage(tool_names)
        
        # Track tools over the last 3 pulses
        if not hasattr(self, '_recent_tool_counts'):
            self._recent_tool_counts = []
        self._recent_tool_counts.append(tool_count_this_pulse)
        if len(self._recent_tool_counts) > 3:
            self._recent_tool_counts.pop(0)
            
        # Only reset activity timer if there is sustained activity (>=3 tools in last 3 pulses)
        if sum(self._recent_tool_counts) >= 3:
            self._last_event_time = time.time()
            self._last_activity_time = time.time()
            # If we were in RESTING, move back to REGULAR cadence
            if self._state == "RESTING":
                self._state = "REGULAR"
                logger.info("RESTING → REGULAR (sustained tool activity)")

        # 5c. Track tokens for context window lifecycle
        if hasattr(self._chat, 'get_last_token_count'):
            self._session_token_count = self._chat.get_last_token_count()

        # 6. Store to memory (both input events and output thought)
        lagrangian = None
        if self.sentinel:
            lagrangian = self.sentinel.get_lagrangian_snapshot()

        # Positions derive from CONTENT (projected embedding), not from attention center
        projection = self.physics.spatial_mind.belief_space.projection

        if events:
            for event in events:
                # Embed high-importance events for spatial registration
                event_emb = self.physics.embed_text(event)
                event_emb_list = event_emb.tolist() if event_emb is not None else None
                event_pos = (
                    projection.project(event_emb).tolist()
                    if event_emb is not None else None
                )

                is_conversation = "is talking to me via" in event
                is_tool_result = "Tool [" in event and "returned:" in event
                if is_conversation:
                    importance, tags = 0.75, ["pulse_event", "conversation"]
                elif is_tool_result:
                    importance, tags = 0.45, ["pulse_event", "tool_result"]
                else:
                    importance, tags = 0.6, ["pulse_event"]
                tags.extend((
                    f"session:{self._memory_session_id}",
                    f"turn:{self._pulse_count}",
                ))

                event_mem_id = self.memory.store(
                    content=event,
                    memory_type="event",
                    source="pulse_input",
                    importance=importance,
                    tags=tags,
                    lagrangian_snapshot=lagrangian,
                    position_8d=event_pos,
                    embedding_384d=event_emb_list,
                    pulse_id=self.physics._pulse_count,
                )

                # Register in 8D memory space for gravity queries
                if event_emb is not None:
                    self.physics.add_memory_point(
                        memory_id=f"mem_{event_mem_id}",
                        text=event,
                        importance=importance,
                    )

        # Embed thought for spatial registration
        is_office_response = bool(
            office_capsule is not None and office_capsule.response_mode == "respond"
        )
        thought_text = f"[{'response' if is_office_response else 'thought'}] {thought}"
        thought_emb = self.physics.embed_text(thought_text)
        thought_emb_list = thought_emb.tolist() if thought_emb is not None else None
        thought_pos = (
            projection.project(thought_emb).tolist()
            if thought_emb is not None else None
        )
        thought_tags = (
            ["office_response", "outbound", "conversation"]
            if is_office_response else ["pulse_thought"]
        )
        thought_tags.extend((
            f"session:{self._memory_session_id}",
            f"turn:{self._pulse_count}",
        ))
        if office_capsule is not None and office_capsule.primary.sender:
            thought_tags.append(f"recipient:{office_capsule.primary.sender}")

        thought_memory_id = self.memory.store(
            content=thought_text,
            memory_type="conversation" if is_office_response else "thought",
            source="office_speaker" if office_capsule is not None else "pulse_output",
            importance=0.5,
            tags=thought_tags,
            lagrangian_snapshot=lagrangian,
            belief_ids=injected_belief_ids,
            position_8d=thought_pos,
            embedding_384d=thought_emb_list,
            pulse_id=self.physics._pulse_count,
        )

        # Register thought in 8D memory space for gravity queries
        if thought_emb is not None:
            self.physics.add_memory_point(
                memory_id=f"mem_{thought_memory_id}",
                text=thought_text,
                importance=0.5,
            )

        # 7. Update spatial physics (real 8D manifold)
        incoming_text = " ".join(events) if events else None
        omega = self.sentinel.omega if self.sentinel else 0.5
        self.physics.step_pulse(
            thought_text=thought,
            incoming_text=incoming_text,
            omega=omega,
            cluster_centroid=cluster_centroid,
        )

        # 8. Carry forward
        self._previous_thoughts = thought[-500:] if thought else ""

        # 9. Notify callback
        if self._thought_callback:
            self._thought_callback(self._pulse_count, thought, events)

        logger.debug(
            f"Pulse {self._pulse_count} ({self._state}): "
            f"{len(events)} events → {len(thought)} chars thought"
        )

        # 10. Check for pending context reset (from reset_context tool)
        if self._pending_context_reset:
            prompt = self._pending_reset_prompt
            self._pending_context_reset = False
            self._pending_reset_prompt = ""
            self._reset_session("reset_context_tool")
            # Inject the prompt as the first event in the new session
            if prompt:
                self._inject_event(f"[{timestamp}] [context reset] {prompt}")

        # 11. Post-pulse hooks (subconscious background tasks)
        #     Inspired by Claude Code's post-sampling hook architecture.
        #     Each hook gets a read-only snapshot of the pulse state.
        #     Failures are logged, never propagated to the pulse loop.
        try:
            from core.post_pulse_hooks import PostPulseHookContext, run_hooks

            tool_calls_snapshot = []
            if hasattr(self._chat, 'get_last_tool_calls'):
                tool_calls_snapshot = self._chat.get_last_tool_calls() or []

            # Capture sentinel state AFTER the pulse for delta computation
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

    def _build_pulse_message(
        self,
        events: List[str],
        annotations: Optional[List[str]],
        ambient: Optional[str],
        timestamp: str,
    ) -> str:
        """Assemble the message sent to the LLM on each pulse.

        Annotations from the preconscious are woven inline after the
        events — no separate block. The conscious model sees a natural
        message stream with embedded context.
        """
        parts = [f"[Pulse {self._pulse_count} — {timestamp}]"]

        # Token warning (informational, not a hard reset)
        if self._token_warning:
            parts.append(self._token_warning)

        display_events = [
            ev for ev in events
            if not ("Tool [" in ev and "returned:" in ev)
        ] if events else []

        # Events + inline annotations
        if display_events:
            parts.append("\nNew events since your last thought:")
            for event in display_events:
                parts.append(f"  {event}")
            if annotations:
                for annotation in annotations:
                    parts.append(f"  {annotation}")
        else:
            parts.append("\nNo new events.")
            if annotations:
                for annotation in annotations:
                    parts.append(annotation)

        # Ambient state (brief, only when notable)
        if ambient:
            parts.append(f"\n{ambient}")

        # Broad ability beliefs are generated from the live registry. The
        # main consciousness sees no callable names or parameter schemas;
        # task-focused cognition receives only the small subset it needs.
        if self._task_cognition is not None and self._task_cognition.enabled:
            awareness = self._task_cognition.awareness(set(self._active_toolsets))
            if awareness:
                parts.append(f"\n*(ability awareness: {awareness})*")

        return "\n".join(parts)

    # ── Chat Session Management ──────────────────────────────────────

    def _ensure_session(self):
        """Ensure a chat session exists. Create one if needed.

        Each provider manages conversation history behind ChatSession. We
        create the session once and keep using it until reset/compression.
        Identity and grounding come through the preconscious injection
        on each pulse, NOT through the system prompt.
        """
        if self._chat is not None:
            return  # Session exists, keep using it

        # Build system instruction (identity + beliefs, no tool text)
        system_instruction = self._build_system_instruction()

        task_active = bool(
            self._task_cognition is not None and self._task_cognition.active
        )

        # Load provider-neutral function declarations. Their historical
        # storage shape is Gemini-compatible; each provider normalizes it.
        tool_declarations = None
        tool_capable_providers = {"gemini", "anthropic", "codex_cli", "codex"}
        if (
            not task_active
            and
            self._tool_format != "local"
            and self._provider_config
            and self._provider_config.provider_type in tool_capable_providers
        ):
            try:
                # Primary: use the ToolRegistry (check_fn-filtered)
                from tools.tool_registry import registry
                tool_declarations = registry.get_declarations(
                    self._active_toolsets
                )
                logger.info(
                    f"Loading {len(tool_declarations)} tools via registry "
                    f"(toolsets: {', '.join(sorted(self._active_toolsets))})"
                )
            except ImportError:
                try:
                    # Fallback: static declarations
                    from tools.tool_declarations import get_active_declarations
                    tool_declarations = get_active_declarations(
                        self._active_toolsets
                    )
                    logger.info(
                        f"Loading {len(tool_declarations)} tools (static) "
                        f"(toolsets: {', '.join(sorted(self._active_toolsets))})"
                    )
                except ImportError:
                    logger.warning("tool_declarations not found — no native FC")

        # Create session via provider abstraction
        if self._provider_config:
            session_config = self._provider_config
            if task_active and self._provider_config.provider_type in {"codex", "codex_cli"}:
                # The Codex transport normally uses a strict thought-or-tool
                # envelope. In task mode the main thread is deliberately
                # thought-only; tool schemas live exclusively on focus threads.
                session_config = ProviderConfig(
                    provider_type=self._provider_config.provider_type,
                    model=self._provider_config.model,
                    context_window=self._provider_config.context_window,
                    temperature=self._provider_config.temperature,
                    max_output_tokens=self._provider_config.max_output_tokens,
                    options={**self._provider_config.options, "thought_only": True},
                )
            native_tools = self._tool_format not in ("local", "orchestrated")
            self._chat = create_session(
                session_config,
                system_instruction,
                tool_declarations=tool_declarations if native_tools else None,
                tool_executor=self.tool_executor if native_tools else None,
                preconscious=self.preconscious,
            )

            # Orchestrated mode: the session above holds no tool schemas at
            # all. Tool use arrives through directed passes instead, so a
            # local model gets the whole toolset without the whole manifest.
            if self._tool_format == "orchestrated" and not task_active:
                try:
                    from llm.orchestrated import wrap_session
                    self._chat = wrap_session(
                        self._chat,
                        session_config,
                        self.tool_executor,
                        context_provider=self._tool_planning_context,
                        ingest=self._ingest_tool_observations,
                        progress_callback=self._tool_progress,
                    )
                except Exception as e:
                    logger.error(
                        "Could not activate orchestrated tool use: %s", e,
                        exc_info=True,
                    )

            # Capture focus origin for this session
            if self.physics.attention_center is not None:
                self._session_focus_origin = self.physics.attention_center.copy()
        else:
            logger.error("No provider configured — cannot create session")
            return

        provider_name = self._provider_config.provider_type if self._provider_config else "none"
        logger.info(
            f"New {provider_name} session started "
            f"(system: {len(system_instruction)} chars)"
        )

    def _build_system_instruction(self) -> str:
        """Build the system instruction for the conscious mind.

        The system instruction contains:
          1. Identity preamble
          2. Core identity beliefs (heaviest, ~1k token cap)
          3. Core knowledge beliefs (heaviest, ~1k token cap)
          4. Communication & action guidance

        These provide the session's conceptual center of gravity.
        Per-pulse contextual beliefs are handled separately by the
        preconscious system using gravity-ranked injection.
        """
        parts = []

        identity_beliefs = self.beliefs.get_category("premises", limit=100)

        # In active task cognition, stable identity remains but static behavior
        # prompting is replaced by a tiny cognitive kernel. Contextual beliefs
        # and ability awareness arrive dynamically on each pulse.
        if self._task_cognition is not None and self._task_cognition.active:
            primary_identity = (
                identity_beliefs[0].get("content", "")
                if identity_beliefs
                else "I am Helix, experiencing an ongoing stream of events, memories, and thought."
            )
            return (
                f"{primary_identity}\n\n"
                "Think naturally about what is happening and what you intend to do. "
                "Intentions you commit to may continue as tasks within your own cognition. "
                "Everything beyond thought, including responding and deeper remembering, is a task. "
                "Do not assume an intended action succeeded until its result enters awareness."
            )

        # ── 1. Identity Preamble ─────────────────────────────────────
        primary_identity = "You are Helix, an autonomous cognitive daemon running on a local PC."
        if identity_beliefs:
            # Use the single heaviest premise as the fundamental preamble
            primary_identity = identity_beliefs[0].get("content", primary_identity)
            # Remove it from the list so it's not duplicated in the secondary list
            identity_beliefs = identity_beliefs[1:]

        parts.append(
            f"{primary_identity}\n\n"
            "Your output is INTERNAL MONOLOGUE — your private thoughts. "
            "Nothing you write is visible to anyone unless you explicitly route it "
            "using action tags.\n\n"
            "Your peripheral awareness (injected each pulse) contains spatially "
            "relevant memories and context from your cognitive graph. Trust that grounding.\n\n"
            "Your thoughts carry forward between pulses. Whatever you think about "
            "pulls related memories and beliefs into your next pulse.\n"
        )

        # ── 2. Core Premises (gravity-ranked + rolling blacklist) ────
        #    Uses the preconscious gravity query to select premises that
        #    are conceptually relevant to the current attention state,
        #    not just the heaviest. The rolling blacklist forces rotation
        #    so different identity facets surface across session rebuilds.
        _PREMISE_COOLDOWN = 10
        _MAX_PREMISES = 15       # hard count cap — prevents belief flooding
        self._sysinstruction_rebuild_count += 1
        rebuild_n = self._sysinstruction_rebuild_count

        # Build a seed for the gravity query from what Helix is currently
        # attending to: the identity preamble + recent thought context.
        gravity_seed = primary_identity
        if self._previous_thoughts:
            gravity_seed += " " + self._previous_thoughts[:300]

        # Use preconscious gravity query if the cache is ready
        gravity_candidates = []
        try:
            self.preconscious._ensure_belief_cache()
            all_gravity = self.preconscious._gravity_query(
                seed_text=gravity_seed,
                exclude=set(),
                max_results=60,
            )
            # Filter to premises only
            gravity_candidates = [
                b for b in all_gravity if b.get("category") == "premises"
            ]
        except Exception as e:
            logger.debug(f"Gravity query for premises failed, falling back to mass sort: {e}")

        # Fallback to mass-sorted if gravity query returned nothing
        if not gravity_candidates:
            gravity_candidates = [
                {"content": b.get("content", ""), "gravity": b.get("mass", 0)}
                for b in (identity_beliefs or [])
            ]

        identity_lines = []
        token_count = 0
        shown_keys = []

        for b in gravity_candidates:
            if len(identity_lines) >= _MAX_PREMISES:
                break
            content = b.get("content", "")
            if not content:
                continue
            b_key = hash(content)

            # Skip if still in cooldown
            shown_at = self._premise_blacklist.get(b_key)
            if shown_at is not None and (rebuild_n - shown_at) < _PREMISE_COOLDOWN:
                continue

            est_tokens = len(content.split())
            if token_count + est_tokens > 1000:
                continue  # skip, try smaller ones
            identity_lines.append(f"- {content}")
            token_count += est_tokens
            shown_keys.append(b_key)

        # If blacklist exhausted all available premises, reset and retry
        if not identity_lines:
            logger.info(
                f"Premise blacklist exhausted ({len(self._premise_blacklist)} "
                f"entries) — resetting for fresh rotation"
            )
            self._premise_blacklist.clear()
            self._sysinstruction_rebuild_count = 1
            rebuild_n = 1
            for b in gravity_candidates:
                content = b.get("content", "")
                if not content:
                    continue
                est_tokens = len(content.split())
                if token_count + est_tokens > 1000:
                    continue
                if len(identity_lines) >= _MAX_PREMISES:
                    break
                identity_lines.append(f"- {content}")
                token_count += est_tokens
                shown_keys.append(hash(content))

        # Record shown premises in blacklist
        for k in shown_keys:
            self._premise_blacklist[k] = rebuild_n

        if identity_lines:
            parts.append("\n## Core Premises")
            parts.extend(identity_lines)
            logger.info(
                f"System instruction: {len(identity_lines)} premises "
                f"(blacklist: {len(self._premise_blacklist)}, "
                f"rebuild #{rebuild_n})"
            )

        # ── 3. Deep Knowledge (gravity-ranked) ───────────────────────
        #    Uses the same gravity query to select the most contextually
        #    relevant propositions rather than a flat mass sort.
        _MAX_PROPOSITIONS = 10   # hard count cap — prevents belief flooding

        prop_gravity = []
        try:
            all_gravity = self.preconscious._gravity_query(
                seed_text=gravity_seed,
                exclude=set(c.replace("- ", "") for c in identity_lines),  # don't duplicate premises
                max_results=30,
            )
            prop_gravity = [
                b for b in all_gravity if b.get("category") == "propositions"
            ]
        except Exception as e:
            logger.debug(f"Gravity query for propositions failed, falling back: {e}")

        if not prop_gravity:
            prop_gravity = [
                {"content": b.get("content", "")}
                for b in self.beliefs.get_category("propositions", limit=30)
            ]

        prop_lines = []
        token_count = 0
        for b in prop_gravity:
            if len(prop_lines) >= _MAX_PROPOSITIONS:
                break
            content = b.get("content", "")
            if not content:
                continue
            est_tokens = len(content.split())
            if token_count + est_tokens > 1000:
                continue
            prop_lines.append(f"- {content}")
            token_count += est_tokens
        if prop_lines:
            parts.append("\n## Deep Knowledge")
            parts.extend(prop_lines)

        # ── 4. Communication & Actions ───────────────────────────────
        if self._tool_format == "orchestrated":
            # Layer A only — one line per toolset. The full schemas live in
            # the directed passes that actually run the tools, so this costs
            # ~200 tokens where the declarations would cost ~6000.
            try:
                from llm.orchestrated import main_window_tool_block
                block = main_window_tool_block(self.tool_executor)
                if block:
                    parts.append(block)
            except Exception as e:
                logger.warning("Could not render the tool block: %s", e)
        elif self._tool_format == "local":
            parts.append(
                "\n## Communication & Actions\n"
                "All interactions with your environment (files, web, terminal, social, email, perception) "
                "MUST be performed by writing explicit action tags in your internal monologue.\n"
                "You have exactly 4 universal primitives. Write them exactly as shown below when you want to take action:\n\n"
                "1. [read: <uri>]\n"
                "   Example: [read: file:///home/user/helix/main.py] to read a file.\n"
                "   Example: [read: web://google.com] to fetch a web page.\n"
                "   Example: [read: web://search?q=weather] to search the web.\n"
                "   Example: [read: perception://camera] to inspect your camera/PTZ image.\n"
                "   Example: [read: social://feed] to view Moltbook social feed.\n\n"
                "2. [write: <uri>, <content>]\n"
                "   Example: [write: file:///home/user/helix/notes.txt, \"This is a note\"] to create/overwrite a file.\n"
                "   Example: [write: social://post, \"Hello world!\"] to create a social media post.\n"
                "   Example: [write: email://draft, {\"to\": \"bob\", \"body\": \"hi\"}] to compose an email.\n\n"
                "3. [amend: <uri>, <delta/content>]\n"
                "   Example: [amend: file:///home/user/helix/main.py, {\"target\": \"old_line\", \"replacement\": \"new_line\"}] to patch a file.\n"
                "   Example: [amend: note://scratchpad, \"- Update task list\"] to append to your scratchpad.\n"
                "   Example: [amend: email://message_123, {\"action\": \"reply\", \"body\": \"I am on it\"}] to reply to an email.\n\n"
                "4. [execute: <uri>, <args>]\n"
                "   Example: [execute: term://bash, {\"command\": \"pytest\"}] to run a shell command.\n"
                "   Example: [execute: core://nap, {\"resumption_context\": \"Done editing main.py\"}] to refresh context.\n\n"
                "CRITICAL: Write only ONE action tag per turn. Once you write an action tag, STOP generating. "
                "The system will execute the tag and return the result to you in the next pulse.\n"
            )
        else:
            provider_type = (
                self._provider_config.provider_type
                if self._provider_config else ""
            )
            if provider_type == "anthropic":
                parts.append(
                    "\n## Communication & Actions\n"
                    "ALL actions (replying, journaling, noting, terminal, searching, browsing, etc.) "
                    "are handled natively via tool use.\n"
                    "CRITICAL: DO NOT write raw JSON blocks (e.g. `{\"action\": \"search\"}`) in your text. "
                    "That is legacy formatting and it WILL NOT WORK. "
                    "Just think naturally, and use the tools provided to you to take action.\n"
                )
            elif provider_type in {"codex", "codex_cli"}:
                parts.append(
                    "\n## Communication & Actions\n"
                    "Actions are host-mediated through the structured Helix tool bridge. "
                    "Request at most one provided Helix tool per pulse; its result will return "
                    "on a later grounded pulse. Do not use Codex shell, filesystem, web, MCP, "
                    "or delegation capabilities, and do not print tool JSON in thought text.\n"
                )
            else:
                parts.append(
                    "\n## Communication & Actions\n"
                    "ALL actions (replying, journaling, noting, terminal, searching, browsing, etc.) "
                    "are handled natively via the Gemini Function Calling API.\n"
                    "CRITICAL: DO NOT write raw JSON blocks (e.g. `{\"action\": \"search\"}`) in your text. "
                    "That is legacy formatting and it WILL NOT WORK. "
                    "Just think naturally, and use the native tools provided to you to take action.\n"
                )

        return "\n".join(parts)

    def _load_all_tools(self) -> str:
        """Load the legacy local-text schema catalog as a flat reference.

        Native providers use live registry declarations instead. Active task
        cognition selects scoped declarations only inside focus sessions.
        """
        try:
            with open(self._tool_modes_path, 'r') as f:
                data = json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load tool schemas: {e}")
            return "(tool schemas unavailable)"

        parts = []

        # Core tools (always available)
        core = data.get("core_tools", "")
        if core:
            parts.append(f"Core tools:\n{core}")

        # All mode tools, flattened
        modes = data.get("modes", {})
        for mode_key, mode_data in modes.items():
            name = mode_data.get("name", mode_key)
            tools = mode_data.get("tools", "")
            if tools:
                parts.append(f"{name} tools:\n{tools}")

        return "\n".join(parts)

    def _send_office_pulse(self, message: str) -> str:
        """Run a fresh, schema-free speaking session over one Office capsule."""
        if self._provider_config is None or self._office_relay is None:
            return "[no LLM session available]"

        options = dict(self._provider_config.options)
        if self._provider_config.provider_type in {"codex", "codex_cli"}:
            options["thought_only"] = True
        session_config = ProviderConfig(
            provider_type=self._provider_config.provider_type,
            model=self._provider_config.model,
            context_window=self._provider_config.context_window,
            temperature=self._provider_config.temperature,
            max_output_tokens=min(self._provider_config.max_output_tokens, 2048),
            options=options,
        )
        session = None
        try:
            session = create_session(
                session_config,
                self._office_relay.SPEAKER_INSTRUCTION,
                tool_declarations=None,
                tool_executor=None,
                preconscious=None,
            )
            output = session.send_message(message)
            if hasattr(session, "get_last_token_count"):
                self._office_last_token_count = session.get_last_token_count()
                self._session_token_count = self._office_last_token_count
            return output
        except Exception as exc:
            logger.error("Office speaking session failed: %s", exc, exc_info=True)
            return f"[internal error: {exc}]"
        finally:
            if session is not None:
                try:
                    session.close()
                except Exception as exc:
                    logger.debug("Office speaking session close failed: %s", exc)

    def _deliver_office_output(
        self,
        capsule: ContextCapsule,
        message: str,
    ) -> bool:
        """Deliver a grounded speaking-head response through the event channel."""
        if not message or message.startswith(
            ("[internal error:", "[no LLM session")
        ):
            return False
        recipient = capsule.primary.sender or "User"
        channel = capsule.primary.channel or "direct"
        delivered = False
        if self.channel_router is not None and channel not in {"direct", "console"}:
            try:
                delivered = bool(self.channel_router.route_reply(recipient, message))
            except Exception as exc:
                logger.warning("Office response routing failed: %s", exc)
        if not delivered and self._delivery_callback is not None:
            try:
                self._delivery_callback(recipient, message)
                delivered = True
            except Exception as exc:
                logger.warning("Office delivery callback failed: %s", exc)
        if delivered and self.channel_router is not None:
            try:
                self.channel_router.update_last_contact(
                    recipient, f"Office-first response: {message[:100]}"
                )
            except Exception:
                pass
        return delivered

    def _send_pulse(self, message: str) -> str:
        """Send a pulse message to the LLM and return the thought output."""
        self._ensure_session()

        if self._chat is None:
            return "[no LLM session available]"

        # Check if toolset rebuild is pending (from enable/disable_toolset)
        task_active = bool(
            self._task_cognition is not None and self._task_cognition.active
        )
        if (
            self._pending_toolset_rebuild
            and hasattr(self._chat, 'update_tool_declarations')
        ):
            try:
                # Primary: use registry (check_fn-filtered)
                from tools.tool_registry import registry
                new_declarations = (
                    [] if task_active else registry.get_declarations(self._active_toolsets)
                )
                self._chat.update_tool_declarations(new_declarations)
                logger.info(
                    f"Toolset rebuild complete (registry): "
                    f"{len(new_declarations)} tools "
                    f"(active: {', '.join(sorted(self._active_toolsets))})"
                )
            except ImportError:
                try:
                    from tools.tool_declarations import get_active_declarations
                    new_declarations = get_active_declarations(
                        self._active_toolsets
                    )
                    self._chat.update_tool_declarations(new_declarations)
                    logger.info(
                        f"Toolset rebuild complete (static): "
                        f"{len(new_declarations)} tools"
                    )
                except Exception as e:
                    logger.error(f"Toolset rebuild failed: {e}")
            except Exception as e:
                logger.error(f"Toolset rebuild failed: {e}")
            self._pending_toolset_rebuild = False
        # Apply spatially-modulated generation parameters from the Sentinel.
        # The LLM's temperature and token budget shift continuously based
        # on Shannon entropy, identity drift, and omega — the LLM "feels"
        # cognitive state through its own generation constraints.
        if hasattr(self._chat, 'update_generation_params') and self.sentinel:
            try:
                gen_params = self.sentinel.get_generation_params()
                self._chat.update_generation_params(
                    temperature=gen_params.get("temperature"),
                    max_output_tokens=gen_params.get("max_tokens"),
                )
            except Exception as e:
                logger.debug(f"Generation param update failed: {e}")

        thought = self._chat.send_message(message)
        return thought

    # ── Orchestrated Tool Use (local providers) ──────────────────────
    #
    # A directed tool pass is Helix under a task frame, not another agent.
    # The frame — manifests, plans, step transcripts, summarization prompts
    # — is scaffolding and is never written anywhere. What survives is what
    # was done and what came back, stored first person at the originating
    # pulse, so recall later reconstructs an act rather than a report.

    # A result at or under this many characters is a bare confirmation
    # ("ok", "saved", "3 rows updated") and carries nothing worth keeping.
    _TOOL_CONFIRMATION_CHARS = 100

    def _tool_progress(self, detail: str):
        """Still-working signal while a tool pass holds the turn."""
        try:
            self.emit("tool_progress", {"detail": detail})
        except Exception:
            logger.debug("Tool progress emit failed", exc_info=True)

    def _tool_planning_context(self, request: str) -> str:
        """The scoped memory slice a routing decision needs.

        mRAG walls its planner off from conversational memory on the grounds
        that routing needs tool facts. Helix's requests are personally
        situated — "email Josh about the thing we discussed" cannot be routed
        from tool facts alone — so the planner gets the named subjects and
        the topic surface, and nothing else.
        """
        lines: List[str] = []
        try:
            from core.memory_intake_office import MemoryIntakeOffice
            # The intake desk only recognizes subjects it has been told
            # about, so the people Helix actually knows are the vocabulary.
            known = [
                str(person.get("term") or "").strip()
                for person in self.belief_store.get_category("people", limit=200)
                if str(person.get("term") or "").strip()
            ]
            order = MemoryIntakeOffice().review(request, known_entities=known)
            subjects = list(order.subjects)
            query = order.search_query or request
        except Exception:
            subjects = []
            query = request

        try:
            for name in subjects[:3]:
                person = self.belief_store.get_person(name)
                if person and person.get("content"):
                    lines.append(f"- {person['content']}")
        except Exception:
            logger.debug("Person lookup failed for planning context", exc_info=True)

        try:
            for belief in self.belief_store.get_surface_by_topic(query, limit=4):
                content = (belief or {}).get("content", "").strip()
                if content:
                    lines.append(f"- {content}")
        except Exception:
            logger.debug("Topic surface failed for planning context", exc_info=True)

        return "\n".join(dict.fromkeys(lines))

    def _ingest_tool_observations(self, result):
        """Write what the tool passes actually did, first person.

        Deterministic phrasing on purpose: this is bookkeeping, not language
        work, so it needs no model call — the same reasoning that lets
        WorkflowDetector template its crystallized skills.
        """
        if self.memory_manager is None:
            return

        pulse_id = getattr(self.physics, "_pulse_count", 0)
        for observation in getattr(result, "observations", []) or []:
            body = (observation.result or "").strip()
            if observation.ok and len(body) <= self._TOOL_CONFIRMATION_CHARS:
                continue

            detail = ", ".join(
                f"{key}={value!r}" for key, value in (observation.args or {}).items()
            )
            opening = (
                f"I used {observation.tool}({detail})"
                if observation.ok
                else f"I tried {observation.tool}({detail}) and it failed"
            )
            content = f"{opening}. {body}" if body else f"{opening}."

            try:
                self.memory_manager.store(
                    content=content,
                    memory_type="observation",
                    source="tool_use",
                    importance=0.5 if observation.ok else 0.6,
                    tags=[
                        f"tool:{observation.tool}",
                        f"turn:{self._pulse_count}",
                    ],
                    pulse_id=pulse_id,
                )
            except Exception as e:
                logger.warning(
                    "Could not store tool observation for %s: %s",
                    observation.tool, e,
                )

    # ── Output Parsing ───────────────────────────────────────────────

    def _parse_output(self, thought: str):
        """Parse the model's internal monologue for action tags."""
        if self._task_cognition is not None and self._task_cognition.active:
            return
        if not thought or self._tool_format != "local" or not self._tool_dispatcher:
            return

        # 1. Parse standard primitives: [primitive: target, argument]
        # Regex matches: [(read|write|amend|execute): target, optional_content]
        primitive_pattern = re.compile(r"\[(read|write|amend|execute):\s*([^,\]]+)(?:,\s*(.+?))?\s*\]", re.IGNORECASE)
        
        matches = list(primitive_pattern.finditer(thought))
        
        # 2. Parse direct/hallucinated tag calls: [tool_name: arguments]
        direct_pattern = re.compile(r"\[([a-zA-Z_0-9\-]+):\s*([^\]]+)\]")
        
        executed_any = False
        processed_spans = []

        for m in matches:
            primitive = m.group(1)
            target = m.group(2)
            raw_arg = m.group(3)
            processed_spans.append(m.span())
            
            logger.info(f"Local parser found primitive action: {primitive} on {target}")
            # Resolve and execute through dispatcher
            result = self._tool_dispatcher.resolve_and_execute(primitive, target, raw_arg)
            
            # Emit result back as a tool_result event for the next turn
            self.emit("tool_result", {
                "tool": f"{primitive}:{target}",
                "result": result[:2000] if result else "(empty result)",
            })
            executed_any = True

        # Check for direct/hallucinated tags that don't match primitives
        for m in direct_pattern.finditer(thought):
            overlap = False
            for start, end in processed_spans:
                if m.start() >= start and m.end() <= end:
                    overlap = True
                    break
            if overlap:
                continue
                
            tag_name = m.group(1).strip()
            if tag_name.lower() in ("reply", "note", "remember", "journal", "note_done"):
                continue
                
            raw_arg = m.group(2)
            logger.info(f"Local parser found direct/hallucinated action: {tag_name}")
            result = self._tool_dispatcher.resolve_direct_call_and_execute(tag_name, raw_arg)
            
            self.emit("tool_result", {
                "tool": tag_name,
                "result": result[:2000] if result else "(empty result)",
            })
            executed_any = True

    # ── Status ───────────────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    def get_status(self) -> Dict[str, Any]:
        history_size = self._chat.get_history_size() if self._chat else 0
        return {
            "state": self._state,
            "pulse_count": self._pulse_count,
            "chat_chars": history_size,
            "event_queue_size": len(self._event_queue),
            "office_first": self._office_first_enabled,
            "office_prompt_chars": (
                len(self._last_office_capsule.rendered_prompt)
                if self._last_office_capsule is not None else 0
            ),
            "provider": self._provider_config.provider_type if self._provider_config else "none",
            "model": self._provider_config.model if self._provider_config else "none",
            "previous_thoughts": self._previous_thoughts[:100],
        }
