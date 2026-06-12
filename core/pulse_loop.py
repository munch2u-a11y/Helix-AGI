"""Helix — Pulse-Based Consciousness Loop (V10: Event-Driven Architecture)

The cognitive cycle. Helix runs as a Gemini chat session with a rich
system prompt containing full identity, beliefs, and all tool schemas.
User messages arrive as events within the ongoing internal monologue.

Architecture:
  - Uses Gemini (1M context) for the conscious mind
  - Gemini native function calling handles multi-step tool use within
    a single turn (compositional FC)
  - Preconscious belief injection on EVERY tool return, not just per-pulse
  - System prompt includes ALL beliefs and ALL tools (no mode-switching)
  - Each pulse sends a message containing:
      1. Pre-conscious injection (spatial context + recent memory)
      2. New events since last pulse (user messages, tool returns, etc.)
      3. Continuation prompt
  - Communication via native FC tools: reply(), send_message(), verbalize()
  - Meta-actions via text tags: [NOTE:], [REMEMBER:], [JOURNAL:]

States:
  DORMANT    — sleeping (configurable via wizard), auto-wakes at configured time
  QUIET      — awake, NO pulses, waiting for external event
  ACTIVE     — 30s pulse cadence, processing conversation + follow-up
  EMERGENCE  — single autonomous pulse after 120 min inactivity
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

        # Tool schemas path — all tools loaded into system prompt
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
        self._event_lock = threading.Lock()

        # Chat session (managed by pulse loop)
        self._chat: Optional[ChatSession] = None

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

        # 429 rate-limit flag — when set, forces fallback model usage
        # and blocks the success-path restore. Cleared on morning wake-up.
        self._rate_limited = False

    def set_dream_engine(self, daemon):
        """Wire the background daemon for rollover snapshots."""
        self._dream_engine = daemon

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
        logger.info("Pulse loop stopped")

    def _reset_session(self, reason: str):
        """Destroy current session and prepare for a fresh one."""
        logger.info(f"Context window reset — reason: {reason}")
        self._chat = None  # Will be recreated on next _ensure_session()
        self._session_focus_origin = None if self.physics.attention_center is None else self.physics.attention_center.copy()
        self._session_token_count = 0
        self._token_warning = ""
        self.preconscious.reset_lexicon_blacklist()

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
            self._last_event_time = time.time()

            # Main comms channels → immediate ACTIVE for fast response
            if event_type == "user_message":
                self._last_incoming_time = time.time()
                self._last_activity_time = time.time()
                if self._state != "ACTIVE":
                    self.wake(trigger=f"event: {event_type}")
            # Nudge sentinel omega on relevant events
            if self.sentinel:
                if event_type == "user_message":
                    self.sentinel.nudge_omega_from_event("incoming_message")

    def _translate_event(self, event_type: str, data: Dict[str, Any]) -> str:
        """Translate a structured event into natural text for the pulse."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        if event_type == "user_message":
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

    def _inject_event(self, text: str):
        """Inject a raw event string directly into the queue.

        Used internally to push results back for the next pulse.
        Does NOT reset _last_event_time — only message events
        (inbound/outbound) should keep ACTIVE mode alive.
        """
        with self._event_lock:
            self._event_queue.append(text)

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
          DORMANT  — Sleep hours (configurable), periodic wake check
          RESTING  — Awake, 1 pulse per hour (autonomous thought)
          ACTIVE   — 30s pulses. Drops to RESTING after 2 min no I/O.
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
                    if self._provider_config and self._provider_config.provider_type == "anthropic":
                        _PRIMARY_MODEL = "claude-fable-5"
                    else:
                        _PRIMARY_MODEL = "gemini-2.5-flash"
                    if hasattr(self._chat, 'switch_model'):
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
            #    When rate-limited, force fallback model but keep pulsing.
            if self._rate_limited:
                if self._provider_config and self._provider_config.provider_type == "anthropic":
                    _FALLBACK = "claude-opus-4-8"
                else:
                    _FALLBACK = "gemini-3.1-flash-lite-preview"
                if self._chat is not None:
                    # Session exists — switch model if needed
                    if hasattr(self._chat, 'switch_model'):
                        current = getattr(self._chat, '_model', '')
                        if current != _FALLBACK:
                            try:
                                self._chat.switch_model(_FALLBACK)
                                logger.info(f"Rate-limited — forced fallback model: {_FALLBACK}")
                            except Exception as e:
                                logger.error(f"Rate-limit model switch failed: {e}")
                elif self._provider_config:
                    # No session yet — override provider config so session
                    # is created with fallback model instead of primary
                    if self._provider_config.model != _FALLBACK:
                        logger.info(
                            f"Rate-limited — overriding boot model: "
                            f"{self._provider_config.model} → {_FALLBACK}"
                        )
                        self._provider_config.model = _FALLBACK

            # ── Pulse Execution ──────────────────────────────────
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
        timestamp = datetime.now().strftime("%H:%M:%S")

        # 0. Snapshot sentinel state BEFORE the pulse fires.
        #    This captures the clean baseline for computing stability
        #    deltas — how much this pulse changed the system's state.
        lagrangian_before = None
        if self.sentinel:
            lagrangian_before = self.sentinel.get_lagrangian_snapshot()

        # 1. Drain events
        events = self._drain_events()

        # 2. Pre-conscious injection
        #    Separate seeds: previous thought + incoming events
        preconscious_context, injected_belief_ids, cluster_centroid = self.preconscious.inject(
            previous_thought=self._previous_thoughts[:500],
            incoming_events=events if events else None,
            trigger_type="user_message" if events else "llm_output",
        )
        
        # 2b. Sensory Cortex Tick
        if getattr(self, "sensory_cortex", None):
            sensory_data = self.sensory_cortex.pulse_tick()
            if sensory_data:
                events.append(sensory_data["content"])


        # 3. Assemble pulse message
        pulse_message = self._build_pulse_message(
            events=events,
            preconscious_context=preconscious_context,
            timestamp=timestamp,
        )

        # 4. Send to LLM
        thought = self._send_pulse(pulse_message)

        # 4b. If we got a 429, back off and optionally fallback model
        if self._provider_config and self._provider_config.provider_type == "anthropic":
            _FALLBACK_MODEL = "claude-opus-4-8"
            _PRIMARY_MODEL = "claude-fable-5"
        else:
            _FALLBACK_MODEL = "gemini-3.1-flash-lite-preview"
            _PRIMARY_MODEL = "gemini-2.5-flash"
        # How many consecutive successes on fallback before trying primary again.
        _FALLBACK_COOLDOWN_PULSES = 10
        # How many failed restore attempts before hard-locking to fallback
        # until the morning wake-up clears it.
        _MAX_RESTORE_FAILURES = 2

        if thought and "429 RESOURCE_EXHAUSTED" in thought:
            self._consecutive_429s = getattr(self, '_consecutive_429s', 0) + 1
            self._fallback_successes = 0  # Reset cooldown on any 429
            restore_failures = getattr(self, '_restore_failures', 0)

            if restore_failures >= _MAX_RESTORE_FAILURES:
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
                if hasattr(self._chat, 'switch_model'):
                    current = getattr(self._chat, '_model', '')
                    if current != _FALLBACK_MODEL:
                        try:
                            self._chat.switch_model(_FALLBACK_MODEL)
                        except Exception as e:
                            logger.error(f"Model switch failed: {e}")

            return  # Skip parsing/storing this error pulse
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
                    if current == _FALLBACK_MODEL:
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
                            # Increment restore attempt counter so if primary
                            # immediately 429s again, we're one step closer
                            # to hard-locking.
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

        # 5b. Tool result queueing — results are now events for next pulse.
        #     This ensures every tool interaction gets full preconscious
        #     grounding on the next pulse cycle.
        if hasattr(self._chat, 'get_pending_tool_results'):
            pending = self._chat.get_pending_tool_results()
            if pending:
                for tr in pending:
                    self.emit("tool_result", {
                        "tool": tr["name"],
                        "result": tr["result"][:1000],
                    })

        # 5. Parse output for action tags
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
        #    Include the Lagrangian snapshot so every memory is encoded
        #    with the somatic state at formation — this is what drives
        #    dynamic memory mass via the cognitive mass equation.
        #
        #    Memories are now embedded at store time and registered in
        #    both the 384D semantic index AND the 8D memory space, so
        #    the preconscious gravity queries can surface them alongside
        #    beliefs. Previously, no embedding was passed, so all 19K+
        #    memories were invisible to the spatial manifold.
        lagrangian = None
        position = None
        if self.sentinel:
            lagrangian = self.sentinel.get_lagrangian_snapshot()
        if self.physics.attention_center is not None:
            position = self.physics.attention_center.tolist()

        if events:
            for event in events:
                # Embed high-importance events for spatial registration
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

                # Register in 8D memory space for gravity queries
                if event_emb is not None:
                    self.physics.add_memory_point(
                        memory_id=f"mem_{event_mem_id}",
                        text=event,
                        importance=0.6,
                    )

        # Embed thought for spatial registration
        thought_text = f"[thought] {thought}"
        thought_emb = self.physics.embed_text(thought_text)
        thought_emb_list = thought_emb.tolist() if thought_emb is not None else None

        thought_memory_id = self.memory.store(
            content=thought_text,
            memory_type="thought",
            source="pulse_output",
            importance=0.5,
            tags=["pulse_thought"],
            lagrangian_snapshot=lagrangian,
            belief_ids=injected_belief_ids,
            position_8d=position,
            embedding_384d=thought_emb_list,
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
        preconscious_context: Optional[str],
        timestamp: str,
    ) -> str:
        """Assemble the message sent to the LLM on each pulse."""
        parts = [f"[Pulse {self._pulse_count} — {timestamp}]"]

        # Token warning (informational, not a hard reset)
        if self._token_warning:
            parts.append(self._token_warning)

        # Pre-conscious context (already wrapped in <spatial-awareness> fencing)
        if preconscious_context:
            parts.append(f"\n{preconscious_context}")

        # Events
        if events:
            parts.append("\nNew events since your last thought:")
            for event in events:
                parts.append(f"  {event}")
        else:
            parts.append("\nNo new events.")

        # Previous thought seed (if no events and first pulses)
        if not events and self._previous_thoughts:
            prev_pulse = max(0, self._pulse_count - 1)
            parts.append(
                f"\n<historical_thought>\n"
                f"[Thought from Pulse {prev_pulse}]\n"
                f"{self._previous_thoughts[:300]}\n"
                f"</historical_thought>"
            )

        return "\n".join(parts)

    # ── Chat Session Management ──────────────────────────────────────

    def _ensure_session(self):
        """Ensure a chat session exists. Create one if needed.

        The Gemini SDK manages conversation history and context
        internally. We just create the session once and keep using it.
        Identity and grounding come through the preconscious injection
        on each pulse, NOT through the system prompt.
        """
        if self._chat is not None:
            return  # Session exists, keep using it

        # Build system instruction (identity + beliefs, no tool text)
        system_instruction = self._build_system_instruction()

        # Load tool declarations for Gemini native function calling
        tool_declarations = None
        if self._provider_config and self._provider_config.provider_type == "gemini":
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
            self._chat = create_session(
                self._provider_config,
                system_instruction,
                tool_declarations=tool_declarations,
                tool_executor=self.tool_executor,
                preconscious=self.preconscious,
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

        # ── 2. Core Premises ─────────────────────────────────────────
        #    Heaviest premises provide the stable foundational truths
        #    that persist across the context window.
        if identity_beliefs:
            identity_lines = []
            token_count = 0
            for b in identity_beliefs:
                content = b.get("content", "")
                est_tokens = len(content.split())
                if token_count + est_tokens > 1000:
                    continue  # skip, try smaller ones
                identity_lines.append(f"- {content}")
                token_count += est_tokens
            if identity_lines:
                parts.append("\n## Core Premises")
                parts.extend(identity_lines)

        # ── 3. Core Propositions ──────────────────────────────────────
        #    Heaviest propositions provide foundational understanding.
        prop_beliefs = self.beliefs.get_category("propositions", limit=100)
        if prop_beliefs:
            prop_lines = []
            token_count = 0
            for b in prop_beliefs:
                content = b.get("content", "")
                est_tokens = len(content.split())
                if token_count + est_tokens > 1000:
                    continue
                prop_lines.append(f"- {content}")
                token_count += est_tokens
            if prop_lines:
                parts.append("\n## Deep Knowledge")
                parts.extend(prop_lines)

        # ── 4. Communication & Actions ───────────────────────────────
        _is_anthropic = (
            self._provider_config
            and self._provider_config.provider_type == "anthropic"
        )
        if _is_anthropic:
            parts.append(
                "\n## Communication & Actions\n"
                "ALL actions (replying, journaling, noting, terminal, searching, browsing, etc.) "
                "are handled natively via tool use.\n"
                "CRITICAL: DO NOT write raw JSON blocks (e.g. `{\"action\": \"search\"}`) in your text. "
                "That is legacy formatting and it WILL NOT WORK. "
                "Just think naturally, and use the tools provided to you to take action.\n"
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
        """Load ALL tool schemas from tool_modes.json as a flat reference.

        No mode-switching — all tools are always available.
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

    def _send_pulse(self, message: str) -> str:
        """Send a pulse message to the LLM and return the thought output."""
        self._ensure_session()

        if self._chat is None:
            return "[no LLM session available]"

        # Check if toolset rebuild is pending (from enable/disable_toolset)
        if self._pending_toolset_rebuild and hasattr(self._chat, 'update_tool_declarations'):
            try:
                # Primary: use registry (check_fn-filtered)
                from tools.tool_registry import registry
                new_declarations = registry.get_declarations(
                    self._active_toolsets
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

    # ── Output Parsing ───────────────────────────────────────────────

    def _parse_output(self, thought: str):
        """Parse the model's internal monologue for action tags.
        
        DEPRECATED: All tools are now native Function Calls. This method is left
        empty but preserved for backwards compatibility with any non-FC models
        if implemented in the future.
        """
        pass

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
            "provider": self._provider_config.provider_type if self._provider_config else "none",
            "model": self._provider_config.model if self._provider_config else "none",
            "previous_thoughts": self._previous_thoughts[:100],
        }
