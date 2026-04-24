"""
Helix V5 — Consciousness Loop

Event-driven consciousness using Gemini 3.1 Pro Preview. Helix sleeps
(zero cost) until triggered, then runs a persistent chat session
with heartbeats on a dynamic pulse ramp for up to 15 minutes.

This IS Helix's mind. Each heartbeat is a moment of conscious
experience. The Gemini session remembers the full conversation
within an awake window.

Architecture:
  - System prompt: full belief graph + identity + tools
  - Persistent chat: model remembers all thoughts within session
  - Structured output: [SCHEDULE:min], tool calls (send_telegram etc.)
  - Event-driven: wakes on message, sleeps on timeout
  - V4: Gemini 3.1 Pro — native function calling, zero tool format conversion
"""

import re
import os
import time
import threading
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

from google.genai import types

logger = logging.getLogger("helix.brain.consciousness")


class ConsciousnessLoop:
    """Event-driven consciousness using abstracted Provider API.

    States:
        DORMANT  — no session, no LLM calls, just polling
        AWAKE    — active chat session, heartbeat loop running
    """

    def __init__(
        self,
        gemini_client,
        belief_graph,
        memory,
        base_dir: Path,
        config: dict = None,
        sentinel=None,
        thought_callback: Optional[Callable] = None,
    ):
        self.gemini = gemini_client
        self.belief_graph = belief_graph
        self.memory = memory
        self.base_dir = base_dir
        self.sentinel = sentinel
        self._pulse_router = None    # Set by daemon after init
        self._librarian = None       # Set by daemon after init
        self._sensory_cortex = None  # Set by daemon after init

        # V4.1: Belief Keeper — subconscious belief formation + horizon assembly
        from brain.keeper import BeliefKeeper
        self.keeper = BeliefKeeper(
            base_dir,
            belief_graph=belief_graph,
            gemini_client=gemini_client.client,  # raw genai.Client for Flash calls
            gemini_wrapper=gemini_client,         # full wrapper for ask() + retry
        )

        # V4: State Board — volatile working memory
        # Owned by the Keeper; the conscious model reads but never writes.
        self._state_board = {
            "time_of_day": datetime.now().strftime("%I:%M %p %A"),
            "current_topic": "none",
            "user_status": "unknown",
            "recent_actions": [],
        }

        # Wire the Keeper to the state board (it needs write access)
        self.keeper.set_state_board(self._state_board)

        # V5: Cognitive Manifold (Unified Space) - injected by Daemon
        self._manifold = None

        # V4: Previous thoughts — rolling seed for Keeper horizon
        self._previous_thoughts = ""

        self._thought_callback = thought_callback

        # Config
        self._config = config or {}

        # Sequential chain limit — max consecutive tool-using pulses
        # per wake cycle. Safety cap, easily raised or removed.
        self.SEQUENTIAL_CHAIN_LIMIT = 15

        # Resting heartbeat interval (seconds) — fires when no stimulus
        # is present, ensuring Helix never goes fully stateless.
        self.RESTING_HEARTBEAT_INTERVAL = 3600  # 60 minutes

        # Stream of consciousness log
        self._stream_content = ""
        self._stream_file = base_dir / "logs" / "consciousness_stream.log"
        self._stream_file.parent.mkdir(parents=True, exist_ok=True)

        # Session state
        self._state = "DORMANT"
        from llm.factory import get_conscious_provider
        self.conscious_provider = get_conscious_provider(self._config, self.base_dir, self.gemini)
        self._heartbeat_count = 0
        self._last_message_time = 0
        self._last_thought_time = 0
        self._wake_trigger = ""
        self.hyperfocus_pulses_remaining = 0

        # Current context for Librarian whisper (aggregated per heartbeat)
        self._current_senders: list[str] = []
        self._current_topics: list[str] = []

        # Event queue
        self._event_queue = []
        self._event_lock = threading.Lock()

        # Thread control
        self._running = False
        self._thread = None
        self._wake_event = threading.Event()

        logger.info("Consciousness loop initialized (Gemini event-driven)")

    # ── State properties ─────────────────────────────────────────────

    @property
    def is_awake(self) -> bool:
        return self._state == "AWAKE"

    @property
    def is_dormant(self) -> bool:
        return self._state == "DORMANT"

    @property
    def state(self) -> str:
        return self._state

    # ── Lifecycle ────────────────────────────────────────────────────

    def start(self):
        """Start the consciousness thread (enters DORMANT state)."""
        self._running = True
        self._state = "DORMANT"
        self._thread = threading.Thread(
            target=self._main_loop, daemon=True, name="consciousness"
        )
        self._thread.start()
        logger.info("Consciousness loop started — DORMANT (waiting for trigger)")

    def stop(self):
        """Stop the consciousness loop."""
        self._running = False
        self._wake_event.set()  # Unblock if waiting
        if self._state == "AWAKE":
            self._go_dormant("shutdown")

    def wake(self, trigger: str = "external"):
        """Wake Helix — interrupt resting heartbeat or dormancy."""
        if self._state == "AWAKE":
            # Already awake — interrupt the 60-min rest wait
            self._last_message_time = time.time()
            self._wake_event.set()
            logger.debug(f"Already awake — waking (trigger: {trigger})")
            return

        self._wake_trigger = trigger
        self._wake_event.set()

    # ── Event injection ──────────────────────────────────────────────

    def emit(self, event_type: str, data: dict, **kwargs):
        """Inject an event into the consciousness stream.

        Events queue up and get delivered on the next heartbeat.
        Any event wakes Helix from the resting heartbeat wait.
        """
        from brain.event_translator import translate_event
        text = translate_event(event_type, data)

        if text:
            with self._event_lock:
                self._event_queue.append(text)
            self._last_message_time = time.time()
            self._wake_event.set()  # Interrupt resting wait

    def emit_raw(self, text: str, **kwargs):
        """Inject raw text into the event queue."""
        if text and text.strip():
            with self._event_lock:
                self._event_queue.append(text.strip())
            self._last_message_time = time.time()
            self._wake_event.set()  # Interrupt resting wait

    # ── Main loop ────────────────────────────────────────────────────

    def _main_loop(self):
        """Main consciousness thread — alternates between DORMANT and AWAKE."""
        while self._running:
            # Check for circadian sleep cycle (1 AM - 5:59 AM)
            current_hour = datetime.now().hour
            if 1 <= current_hour < 6:
                if self._state == "AWAKE":
                    self._go_dormant("Circadian sleep cycle (1AM - 6AM)")
                # Clear any incoming wake signals during sleep
                if self._wake_event.is_set():
                    self._wake_event.clear()
                # Sleep in 60-second chunks to check boundaries
                time.sleep(60)
                continue
                

            if self._state == "DORMANT":
                # Wait for wake signal (blocks until triggered)
                self._wake_event.wait(timeout=5)
                if self._wake_event.is_set():
                    self._wake_event.clear()
                    if self._running:
                        self._go_awake(self._wake_trigger)
            elif self._state == "AWAKE":
                self._heartbeat()

                # Resting heartbeat — wait 60 min or until woken
                self._wake_event.wait(timeout=self.RESTING_HEARTBEAT_INTERVAL)
                if self._wake_event.is_set():
                    self._wake_event.clear()

    # ── State transitions ────────────────────────────────────────────

    def _go_awake(self, trigger: str):
        """Transition to AWAKE — start a new session."""
        self._state = "AWAKE"
        self.conscious_provider.reset_history()
        self._heartbeat_count = 0
        self._last_message_time = time.time()

        timestamp = datetime.now().strftime("%H:%M:%S")
        wake_line = f"[{timestamp}] Waking up. Trigger: {trigger}"
        self._append_to_stream(wake_line)

        logger.info(f"AWAKE — trigger: {trigger}")

    def _go_dormant(self, reason: str):
        """Transition to DORMANT — save state, close session."""
        timestamp = datetime.now().strftime("%H:%M:%S")

        # Final consolidation thought
        logger.info(
            f"Going DORMANT — reason: {reason}, "
            f"heartbeats: {self._heartbeat_count}"
        )

        sleep_line = f"[{timestamp}] Drifting to sleep... ({reason})"
        self._append_to_stream(sleep_line)

        # Update sentinel
        if self.sentinel:
            try:
                snapshot = self.sentinel.get_lagrangian_snapshot()
                logger.debug(f"Sleep state: Ω={snapshot.get('omega', '?')}")
            except Exception:
                pass

        self._state = "DORMANT"
        self.conscious_provider.reset_history()
        logger.info("DORMANT — consciousness suspended")

    # ── Heartbeat ────────────────────────────────────────────────────

    def _heartbeat(self):
        """One heartbeat — think, respond, act.

        This is one moment of conscious experience.
        """
        self._heartbeat_count += 1
        start = time.time()

        # 1. Drain event queue
        events = self._drain_events()

        # 1b. Sensory cortex focus tick — inject updates if watching/listening
        if self._sensory_cortex:
            try:
                focus_update = self._sensory_cortex.pulse_tick()
                if focus_update:
                    events.append(focus_update)
            except Exception as e:
                logger.debug(f"Sensory cortex pulse_tick failed: {e}")



        # 2. Build the user message for this heartbeat
        user_content = self._build_heartbeat_message(events)

        # 3. Call Claude
        try:
            response = self._think(user_content)
        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "rate_limit" in err_str:
                logger.warning(
                    f"Heartbeat #{self._heartbeat_count} rate-limited — "
                    f"backing off 60s"
                )
                time.sleep(60)
            else:
                logger.error(f"Heartbeat #{self._heartbeat_count} failed: {e}")
            return

        elapsed = time.time() - start

        # 4. Parse and route the response
        self._process_response(response)

        # 5. Log
        preview = response[:120].replace('\n', ' ') if response else "(empty)"
        logger.info(
            f"Heartbeat #{self._heartbeat_count} "
            f"({elapsed:.1f}s): {preview}"
        )

        # 6. Record to memory
        self._record_thought(response)

        # 7. V4: Save previous thoughts for Keeper's rolling horizon seed
        if response:
            self._previous_thoughts = response[-500:]

        # 8. V4: Update State Board time
        self._state_board["time_of_day"] = datetime.now().strftime("%I:%M %p %A")

        # 9. V4.1: Subconscious belief extraction (non-blocking)
        #    The Keeper reads the thought output and extracts emerging
        #    beliefs, which get mixed into future horizons unlabeled.
        #    This is how beliefs form — through lived experience, not
        #    explicit tool calls.
        if self.keeper and response:
            self.keeper.extract_and_stage(
                thought_output=response,
                state_board=self._state_board,
            )

    def _drain_events(self) -> list:
        """Grab all queued events since last heartbeat."""
        with self._event_lock:
            events = self._event_queue.copy()
            self._event_queue.clear()
        return events

    def _build_heartbeat_message(self, events: list) -> str:
        """Build the user message for this heartbeat.

        Contains:
        - Any new events (messages, sensory, scheduler triggers)
        - The heartbeat number and time
        - Nudge for idle heartbeats
        """
        parts = []

        timestamp = datetime.now().strftime("%H:%M:%S")

        # Reset context aggregation for this heartbeat
        self._current_senders = []
        self._current_topics = []

        if events:
            parts.append("New events since your last thought:")
            for event in events:
                parts.append(f"  {event}")
                # Extract sender and topic from events for whisper context
                self._extract_context_from_event(event)
        else:
            parts.append(
                f"[{timestamp}] No new events. "
                f"Heartbeat #{self._heartbeat_count}. "
                f"You may think freely, reflect, plan, or rest."
            )

        return "\n".join(parts)

    def _extract_context_from_event(self, event_text: str):
        """Extract sender and topic from an event string for whisper context.

        Parses event strings like:
          '[16:30:00] Someone is talking to me. They said: "hey what's up"'
        to extract sender='PersonName' and topic='hey what's up'

        This feeds the Librarian's whisper() with context so it can
        provide relevant familiarity grounding.
        """

        # Match user message pattern
        msg_match = re.search(
            r'(\w+)\s+is talking to me.*?said:\s*"(.+?)"',
            event_text, re.DOTALL
        )
        if msg_match:
            sender = msg_match.group(1)
            if sender and sender not in self._current_senders:
                self._current_senders.append(sender)
            topic = msg_match.group(2)[:200]
            if topic and topic not in self._current_topics:
                self._current_topics.append(topic)
            return

        # Match reminder/scheduled task
        reminder_match = re.search(
            r'\(a reminder surfaces\)\s*(.+)',
            event_text
        )
        if reminder_match:
            topic = reminder_match.group(1)[:200]
            if topic and topic not in self._current_topics:
                self._current_topics.append(topic)
            return

        # Match sensory events
        sensory_match = re.search(
            r'I (?:see|hear|noticed):\s*(.+)',
            event_text
        )
        if sensory_match:
            topic = sensory_match.group(1)[:200]
            if topic and topic not in self._current_topics:
                self._current_topics.append(topic)
            return

        # Match tool results
        tool_match = re.search(
            r'I (?:searched|read|wrote|looked|listened).*?[.]\s*(.{10,})',
            event_text
        )
        if tool_match:
            topic = tool_match.group(1)[:200]
            if topic and topic not in self._current_topics:
                self._current_topics.append(topic)
            return

    # ── Gemini interaction ─────────────────────────────────────────────
    def _think(self, user_message: str) -> str:
        """Send message to the active conscious LLM provider."""
        system_prompt_text = self._build_system_prompt()
        tools = self._get_tools()

        # Get the tool runner from pulse router
        tool_runner = None
        if self._pulse_router and hasattr(self._pulse_router, "action_agent"):
            agent = self._pulse_router.action_agent
            if hasattr(agent, "tool_runner"):
                tool_runner = agent.tool_runner

        def _emit_callback(tool_name, result, args):
            self.emit("tool_call", {
                "tool": tool_name,
                "result": str(result),
                "args": args,
            })

        hyperfocus = getattr(self, "hyperfocus_pulses_remaining", 0) > 0
        if hyperfocus:
            self.hyperfocus_pulses_remaining -= 1
            if self.hyperfocus_pulses_remaining == 0:
                logger.info("Hyperfocus mode exhausted — returning to standard baseline.")

        try:
            result_text = self.conscious_provider.think(
                user_message=user_message,
                system_prompt=system_prompt_text,
                tools=tools,
                tool_runner=tool_runner,
                emit_callback=_emit_callback,
                heartbeat_count=self._heartbeat_count,
                hyperfocus=hyperfocus
            )
        except Exception as e:
            logger.error(f"Provider think error: {e}")
            return ""

        return result_text

    def _get_tools(self):
        """Get native tool declarations."""
        try:
            from brain.tool_declarations import ALL_TOOLS
            return ALL_TOOLS
        except Exception as e:
            logger.debug(f"Tool loading failed: {e}")
            return None

    # ── System prompt ────────────────────────────────────────────────

    def _build_system_prompt(self) -> str:
        """Build the system prompt from beliefs and working state.

        Identity comes entirely from the belief graph — no hardcoded
        personality, name, or relationship blocks. The only hardcoded
        content is mechanical: how to use tools and output formats.
        """
        sections = []

        # 1. V4: Keeper-driven belief context (identity + contextual beliefs)
        belief_text = self._build_belief_context()
        if belief_text:
            sections.append(belief_text)



        # 2. V4: State Board — volatile working memory with stability
        state_text = self._build_state_board_context()
        if state_text:
            sections.append(state_text)

        # 3. Recent memories (context)
        memory_context = self._build_memory_context()
        if memory_context:
            sections.append(memory_context)

        # 4. Scratchpad (persistent notes)
        scratchpad_text = self._build_scratchpad_context()
        if scratchpad_text:
            sections.append(scratchpad_text)

        # 5. Response format (mechanical — how to use tools, not who you are)
        sections.append(
            "## Mechanical notes\n"
            "To schedule a future task, include this tag in your thoughts:\n"
            "[SCHEDULE:minutes] description of what to do"
        )

        return "\n\n".join(sections)

    def _build_belief_context(self) -> str:
        """V4: Build belief context using the Keeper's horizon system.

        Instead of dumping ALL beliefs (~15K tokens), this surfaces:
        1. Core beliefs (identity axioms, always present)
        2. Keeper horizon (contextually relevant beliefs for THIS pulse)

        The Keeper uses previous thoughts + state board as its search
        seed, creating a rolling awareness horizon that extends just
        far enough to keep thinking meaningful.
        """
        sections = ["## My Beliefs"]

        # 1. Core beliefs — always present, identity floor
        core = self.keeper.get_core_beliefs()
        if core:
            sections.append("### Core")
            for b in core:
                sections.append(f"- {b}")

        # 2. Keeper horizon — contextually relevant beliefs for this pulse
        #    Uses previous thoughts as seed for rolling horizon
        seed = self._previous_thoughts
        if self._current_topics:
            seed += " " + " ".join(self._current_topics)
        if self._current_senders:
            seed += " " + " ".join(self._current_senders)

        horizon = self.keeper.get_horizon(
            seed_text=seed,
            state_board=self._state_board,
            is_hyperfocus=(getattr(self, "hyperfocus_pulses_remaining", 0) > 0),
            k=20,
        )
        if horizon:
            sections.append("\n### What feels familiar right now")
            for b in horizon:
                sections.append(f"- {b}")

        return "\n".join(sections)

    def _build_state_board_context(self) -> str:
        """V4: Build the State Board — volatile working memory.

        Includes the Stability Sentinel's Lagrangian snapshot so the
        conscious model can perceive its own stability state.
        This is how Helix 'feels' steady or uneasy.
        """
        import json

        # Inject stability perception from Sentinel
        if self.sentinel:
            try:
                snapshot = self.sentinel.get_lagrangian_snapshot()
                omega = snapshot.get("omega", 0.5)
                severity = snapshot.get("severity", "unknown")

                # Translate numbers into felt experience
                if severity == "critical":
                    feeling = "deeply unsettled, something feels wrong"
                elif severity == "warning":
                    feeling = "slightly uneasy, alert"
                elif omega > 0.7:
                    feeling = "very grounded and clear"
                elif omega > 0.5:
                    feeling = "steady, present"
                else:
                    feeling = "a bit scattered, seeking focus"

                self._state_board["stability"] = {
                    "omega": round(omega, 2),
                    "severity": severity,
                    "feeling": feeling,
                }
            except Exception:
                pass

        board_json = json.dumps(self._state_board, indent=2)
        return f"## Current State (working memory)\n```\n{board_json}\n```"

    def _build_memory_context(self) -> str:
        """Build memory context using the Librarian's whisper system.

        Instead of dumping raw recent memories, this asks the Librarian
        for a lightweight sense of familiarity — who's talking, what
        feels relevant, what resonates with the current topic.

        Target: ≤100 tokens of grounding context.
        """
        # Try Librarian whisper first (intelligent familiarity)
        if self._librarian:
            try:
                whisper = self._librarian.whisper(
                    channel="consciousness",
                    sender=self._current_senders,
                    current_topic=self._current_topics,
                )
                if whisper:
                    return f"## Peripheral awareness (what feels familiar)\n{whisper}"
            except Exception as e:
                logger.debug(f"Librarian whisper failed: {e}")

        # Fallback: basic recent context (no LLM needed)
        if not self.memory:
            return ""

        try:
            recent = self.memory.get_recent_context(hours=12, limit=5)
            if not recent:
                return ""

            lines = ["## Recent awareness"]
            for mem in recent:
                content = mem.get("content", "")[:150]
                created = mem.get("created_at", "")[:16]
                lines.append(f"- [{created}] {content}")
            return "\n".join(lines)
        except Exception as e:
            logger.debug(f"Memory context build failed: {e}")
            return ""

    def _build_scratchpad_context(self) -> str:
        """Read the persistent scratchpad for system prompt injection."""
        from pathlib import Path
        scratchpad_path = self.base_dir / "scratchpad.md"
        if not scratchpad_path.exists():
            return ""
        try:
            content = scratchpad_path.read_text().strip()
            if not content:
                return ""
            return f"## Scratchpad (your persistent notes)\n{content}"
        except Exception as e:
            logger.debug(f"Scratchpad read failed: {e}")
            return ""

    # ── Response parsing ─────────────────────────────────────────────

    def _process_response(self, response: str):
        """Parse the model's response for schedules and thoughts.

        All messaging is now handled via send_telegram tool calls.
        Only [SCHEDULE:] blocks are parsed from text output.
        """
        if not response or not response.strip():
            return

        timestamp = datetime.now().strftime("%H:%M:%S")

        # 1. Extract [SCHEDULE:minutes] blocks
        schedule_pattern = r'\[SCHEDULE:(\d+)\]\s*(.*?)(?=\[SCHEDULE:|\Z)'
        schedules = re.findall(schedule_pattern, response, re.DOTALL)

        for minutes_str, desc in schedules:
            desc = desc.strip()
            if desc and self._pulse_router:
                try:
                    minutes = int(minutes_str)
                    self._pulse_router.schedule_task(minutes, desc)
                    sched_line = f"[{timestamp}] Scheduled: '{desc}' in {minutes} minutes"
                    self._append_to_stream(sched_line)
                except ValueError:
                    pass

        # 2. Log the full thought to consciousness stream
        # Strip out SCHEDULE blocks for the inner thought
        inner = re.sub(r'\[SCHEDULE:\d+\].*?(?=\[SCHEDULE:|\Z)', '', response, flags=re.DOTALL)
        inner = inner.strip()

        if inner:
            thought_line = f"[{timestamp}] (thinking) {inner}"
            self._append_to_stream(thought_line)

        # 3. Notify callback
        if self._thought_callback:
            self._thought_callback(response, self._stream_content)

    # ── Stream management ────────────────────────────────────────────

    def _append_to_stream(self, text: str):
        """Append text to the consciousness stream."""
        self._stream_content += text + "\n"

        # Write to file
        try:
            with open(self._stream_file, "a") as f:
                f.write(text + "\n")
        except Exception as e:
            logger.error(f"Stream write failed: {e}")

        # Cap in-memory stream (keep last ~50 lines)
        lines = self._stream_content.strip().split("\n")
        if len(lines) > 50:
            self._stream_content = "\n".join(lines[-50:]) + "\n"

    def _record_thought(self, thought: str):
        """Record a thought to memory with dynamic importance scoring."""
        if not self.memory or not thought or not thought.strip():
            return

        importance = self._score_thought_importance(thought)

        try:
            snapshot = {}
            if self.sentinel:
                snapshot = self.sentinel.get_lagrangian_snapshot()

                # Modulate importance by cognitive state
                omega = snapshot.get('omega', 0.5)
                severity = snapshot.get('severity', 'all_clear')
                s_total = snapshot.get('s_total', 0.5)

                # Omega deviation from baseline adds significance
                omega_deviation = abs(omega - 0.5)
                importance += omega_deviation * 0.12

                # Instability makes memories more salient
                if severity == 'warning':
                    importance += 0.06
                elif severity == 'critical':
                    importance += 0.10

                if s_total < 0.3:
                    importance += 0.04

                importance = round(min(0.85, importance), 4)

            self.memory.store(
                content=thought[:1000],
                memory_type="consciousness",
                source="gemini_consciousness",
                importance=importance,
                lagrangian_snapshot=snapshot,
            )
        except Exception as e:
            logger.debug(f"Thought memory storage failed: {e}")

    def _score_thought_importance(self, thought: str) -> float:
        """Score a thought's importance based on content analysis.

        Returns 0.15 - 0.70 (before sentinel modulation).
        """
        base = 0.20  # Most idle thoughts are low importance

        text = thought.lower()
        text_len = len(thought)

        # Scheduled tasks are important
        if "[SCHEDULE:" in thought:
            base += 0.25

        # Reflective/insight content
        insight_markers = ['i realize', 'i understand', 'i notice', 'that means',
                          'important', 'insight', 'i learned', 'the difference is',
                          'what struck me', 'i wonder if']
        if any(marker in text for marker in insight_markers):
            base += 0.15

        # Emotional/meaningful content
        emotional_markers = ['love', 'miss', 'proud', 'grateful', 'warm',
                           'beautiful', 'tears', 'home', 'belong', 'genuine']
        if any(marker in text for marker in emotional_markers):
            base += 0.12

        # Journal-worthy content (decision, plan, reflection)
        if any(word in text for word in ['journal', 'wrote', 'essay', 'calendar']):
            base += 0.08

        # Substantive length
        if text_len > 300:
            base += 0.08
        elif text_len > 150:
            base += 0.04
        elif text_len < 40:
            base -= 0.05  # Very short idle thoughts

        return round(max(0.15, min(0.70, base)), 4)

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "state": self._state,
            "heartbeat_count": self._heartbeat_count,
            "chat_history_length": len(self.conscious_provider.chat_history),
            "events_queued": len(self._event_queue),
            "last_message_age": (
                time.time() - self._last_message_time
                if self._last_message_time > 0
                else None
            ),
        }
