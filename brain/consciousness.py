"""
Helix V6 — Consciousness Loop (Provider-Agnostic)

Event-driven consciousness with swappable LLM providers. The agent
sleeps (zero cost) until triggered, then runs a persistent chat
session with heartbeats.

Supported providers (set via config.yaml → conscious_provider):
  - "gemini"    — Google Gemini (default)
  - "anthropic" — Anthropic Claude
  - "openai"    — OpenAI GPT

Architecture:
  - System prompt: full belief graph + identity + tools
  - Persistent chat: model remembers all thoughts within session
  - Structured output: [SCHEDULE:min], native tool calls
  - Event-driven: wakes on message, sleeps on timeout
  - V6: Trail particles, belief precipitation, spatial awareness
"""

import re
import os
import time
import threading
import logging
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional, Callable

logger = logging.getLogger("helix.brain.consciousness")


class ConsciousnessLoop:
    """Event-driven consciousness with swappable LLM providers.

    Provider is selected via config['conscious_provider']:
      - 'gemini'    → Google Gemini (via google-genai SDK)
      - 'anthropic' → Anthropic Claude (via anthropic SDK)
      - 'openai'    → OpenAI GPT (via openai SDK)

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

        # Legacy SpatialMind removed. CognitiveManifold is injected by Daemon now.
        self._spatial_mind = None

        # V6: Interaction engine (set by daemon after init)
        self._interaction_engine = None  # InteractionEngine instance

        # V4: Previous thoughts — rolling seed for Keeper horizon
        self._previous_thoughts = ""

        # V5: Spatial context — populated each heartbeat by spatial_mind.pulse()
        self._spatial_context = ""

        self._thought_callback = thought_callback

        # Config
        self._config = config or {}

        # Sequential chain limit — max consecutive tool-using pulses
        # per wake cycle. Safety cap, easily raised or removed.
        self.SEQUENTIAL_CHAIN_LIMIT = 15

        # V6 Pulse Wrapper
        # After a trigger (message in/out, scheduled task), the agent gets
        # up to 5 pulses at 4-minute intervals. New triggers reset the
        # counter. After 5 quiet pulses with a settled mind, he naps.
        # Sequential tool returns within a pulse don't reset the counter.
        self.PULSE_INTERVAL = 4 * 60        # 4 minutes between follow-up pulses
        self.MAX_IDLE_PULSES = 5            # max pulses before nap
        self._idle_pulse_count = 0          # pulses since last trigger
        self._last_trigger_time = 0         # when the last trigger fired
        self._mind_settled = False          # True when output is short + no tools
        self._last_used_tools = False       # did the last heartbeat use tools?
        self._napping = False               # True when in nap state

        # Stream of consciousness log
        self._stream_content = ""
        self._stream_file = base_dir / "logs" / "consciousness_stream.log"
        self._stream_file.parent.mkdir(parents=True, exist_ok=True)

        # Session state
        self._state = "DORMANT"
        self._chat_history = []  # List of {"role": ..., "content": ...}
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

        # V6: Provider client — lazily initialized on first _think() call
        self._provider_client = None
        self._provider_name = (config or {}).get("conscious_provider", "gemini")

        logger.info(f"Consciousness loop initialized (provider: {self._provider_name})")

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
        """Wake agent — interrupt nap or dormancy.

        V6: Resets the idle pulse counter (new trigger = full 5-pulse window).
        """
        # Reset pulse counter — new trigger means fresh attention
        self._idle_pulse_count = 0
        self._napping = False
        self._mind_settled = False
        self._last_trigger_time = time.time()

        if self._state == "AWAKE":
            # Already awake — interrupt the wait
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
        Any event wakes the agent from the resting heartbeat wait.
        V6: Also nudges Ω via the Sentinel's omega drivers.
        """
        from brain.event_translator import translate_event
        text = translate_event(event_type, data)

        if text:
            with self._event_lock:
                self._event_queue.append(text)
            self._last_message_time = time.time()
            self._idle_pulse_count = 0  # Reset pulse counter
            self._napping = False
            self._mind_settled = False
            self._last_trigger_time = time.time()
            self._wake_event.set()  # Interrupt wait

            # V6: Nudge omega based on event type
            if self.sentinel and hasattr(self.sentinel, 'nudge_omega_from_event'):
                omega_event_map = {
                    "telegram_message": "incoming_message",
                    "user_message": "incoming_message",
                    "tool_result": "successful_tool_call",
                    "tool_error": "tool_failure",
                    "schedule_trigger": "incoming_message",
                    "error": "tool_failure",
                }
                omega_event = omega_event_map.get(event_type)
                if omega_event:
                    self.sentinel.nudge_omega_from_event(omega_event)

    def emit_raw(self, text: str, **kwargs):
        """Inject raw text into the event queue."""
        if text and text.strip():
            with self._event_lock:
                self._event_queue.append(text.strip())
            self._last_message_time = time.time()
            self._idle_pulse_count = 0  # Reset pulse counter
            self._napping = False
            self._mind_settled = False
            self._last_trigger_time = time.time()
            self._wake_event.set()  # Interrupt wait

    # ── Main loop ────────────────────────────────────────────────────

    def _main_loop(self):
        """Main consciousness thread — alternates between DORMANT and AWAKE."""
        self._last_sleep_date = None  # Track which date we last slept
        while self._running:
            # Check for circadian sleep cycle (1 AM - 5:59 AM)
            current_hour = datetime.now().hour
            today = datetime.now().strftime("%Y-%m-%d")
            if 1 <= current_hour < 6:
                if self._state == "AWAKE":
                    self._go_dormant("Circadian sleep cycle (1AM - 6AM)")
                    # V6: Clear yesterday's blocklist at start of sleep
                    if self.keeper and self._last_sleep_date != today:
                        self.keeper.clear_static_blocklist()
                        self._last_sleep_date = today
                        logger.info("V6: Cleared static blocklist for overnight")
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
                # Check nap condition: 5 idle pulses + mind settled
                if (self._napping or
                    (self._idle_pulse_count >= self.MAX_IDLE_PULSES
                     and self._mind_settled)):
                    self._napping = True
                    logger.info(
                        f"Napping — {self._idle_pulse_count} idle pulses, "
                        f"mind settled. Waiting for trigger."
                    )
                    # Nap: block until wake signal (no timeout = no cost)
                    self._wake_event.wait()
                    if self._wake_event.is_set():
                        self._wake_event.clear()
                        self._napping = False
                        self._idle_pulse_count = 0
                        self._mind_settled = False
                    continue

                self._heartbeat()

                # After heartbeat: wait PULSE_INTERVAL, or wake on trigger
                self._wake_event.wait(timeout=self.PULSE_INTERVAL)

                if self._wake_event.is_set():
                    # Woke by trigger — counter already reset in wake()/emit()
                    self._wake_event.clear()
                else:
                    # Slept undisturbed — this was an idle pulse
                    self._idle_pulse_count += 1

    # ── State transitions ────────────────────────────────────────────

    def _go_awake(self, trigger: str):
        """Transition to AWAKE — start a new session."""
        self._state = "AWAKE"
        self._chat_history = []
        self._heartbeat_count = 0
        self._last_message_time = time.time()

        # V6: Refresh static blocklist on morning wake
        if self.keeper:
            blocked = self.keeper.refresh_static_blocklist()
            if blocked:
                logger.info(f"V6: Refreshed static blocklist — {blocked} beliefs blocked")

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
        self._chat_history = []
        logger.info("DORMANT — consciousness suspended")

    # ── Heartbeat ────────────────────────────────────────────────────

    def _heartbeat(self):
        """One heartbeat — think, respond, act.

        This is one moment of conscious experience.
        """
        self._heartbeat_count += 1
        self._last_used_tools = False  # Reset for this heartbeat
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

        # 1.5 Enactive Embodiment Tick
        if self._sensory_cortex and getattr(self._sensory_cortex, "embodiment_active", False):
            try:
                embodiment_state = self._sensory_cortex._embodiment_tick()
                if embodiment_state:
                    events.append(embodiment_state)
                    # Inject a hyper-dynamic sensory node into the 8D manifold to warp geodesics
                    if self._spatial_mind:
                        # Clear last tick's volatile nodes
                        self._spatial_mind.clear_volatile_nodes()
                        
                        # Generate basic default positional mapping based on current center
                        curr_pos = np.zeros(8)
                        
                        self._spatial_mind.add_volatile_node(
                            node_id="b_sense_live",
                            node_type="sensory_reality",
                            content=embodiment_state["content"],
                            pos=curr_pos,
                            mass=20.0 # Extreme gravity well to bend all surrounding memory to it
                        )
            except Exception as e:
                logger.error(f"Embodiment tick integration failed: {e}")

        # 1c. V5: Spatial pulse — compute cognitive trail + nearby context
        #     Uses previous thought output to move the attention center
        #     and surfaces spatially relevant beliefs + memories
        if self._spatial_mind and self._previous_thoughts:
            try:
                agent_age = self.memory.get_agent_age() if self.memory else 3600.0
                # Build incoming stimulus from events
                incoming = None
                if events:
                    incoming = " ".join(
                        str(e.get("content", e.get("data", "")))
                        if isinstance(e, dict) else str(e)
                        for e in events[:3]  # Cap at 3 events for embedding
                    )
                self._spatial_context = self._spatial_mind.pulse_from_text(
                    thought_text=self._previous_thoughts,
                    incoming_text=incoming,
                    agent_age_seconds=agent_age,
                )
            except Exception as e:
                logger.debug(f"Spatial pulse failed: {e}")
                self._spatial_context = ""

        # 2. Build the user message for this heartbeat
        user_content = self._build_heartbeat_message(events)

        # 3. Call LLM (provider-agnostic)
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

        # 10. V6: Trail particle deposition + decay
        #     The conscious thought leaves a trace in the manifold.
        #     These accumulate into temporal awareness and, when dense
        #     enough, precipitate into new beliefs.
        if self._spatial_mind and response:
            try:
                space = self._spatial_mind.belief_space
                pos = self._spatial_mind.attention_center
                omega = self.sentinel.omega if self.sentinel else 0.5

                # Deposit trail particle at current attention position
                space.deposit_trail_particle(
                    position=pos,
                    content=response[:80],
                    pulse_id=self._heartbeat_count,
                    omega=omega,
                    importance=self._score_thought_importance(response) * 0.5,
                )

                # Decay all trail particles (radioactive decay model)
                space.decay_trail_particles()

            except Exception as e:
                logger.debug(f"V6 trail deposition failed: {e}")

        # 11. V6: Periodic belief precipitation (every 50 heartbeats)
        #     The Keeper owns precipitation — it's the V6 evolution of
        #     belief formation (trail clusters → surface beliefs).
        if (self.keeper and self.keeper.precipitation and
                self._heartbeat_count % 50 == 0 and
                self._heartbeat_count > 0):
            try:
                new_beliefs = self.keeper.precipitation.scan_and_precipitate()
                if new_beliefs and self.sentinel:
                    for _ in new_beliefs:
                        self.sentinel.nudge_omega_from_event("new_belief_formed")
            except Exception as e:
                logger.debug(f"V6 precipitation failed: {e}")

        # 12. V6: Mind settled detection (for nap decision)
        #     Short output + no tool calls = mind is at rest.
        #     The main loop uses this to decide when to nap.
        response_len = len(response.strip()) if response else 0
        self._mind_settled = (response_len < 50 and not self._last_used_tools)
        if self._mind_settled:
            logger.debug(
                f"Mind settled (response={response_len} chars, "
                f"idle_pulse={self._idle_pulse_count}/{self.MAX_IDLE_PULSES})"
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
                if isinstance(event, dict):
                    parts.append(f"  [{event.get('type', 'event')}] {event.get('content', str(event))}")
                else:
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

    def _extract_context_from_event(self, event_text):
        """Extract sender and topic from an event string for whisper context.

        Parses event strings like:
          '[16:30:00] Someone is talking to me. They said: "hey what's up"'
        to extract sender='PersonName' and topic='hey what's up'

        This feeds the Librarian's whisper() with context so it can
        provide relevant familiarity grounding.
        """
        if isinstance(event_text, dict):
            event_text = event_text.get("content", str(event_text))

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

    # ── LLM Interaction (Provider-Agnostic) ──────────────────────────────

    def _think(self, user_message: str) -> str:
        """Send to the configured LLM provider and get a thought.

        V6: Single LLM call per heartbeat, provider-agnostic.
        Dispatches to _think_gemini, _think_anthropic, or _think_openai
        based on config['conscious_provider'].
        """

        # Build system prompt with full belief graph
        system_prompt_text = self._build_system_prompt()

        # Add the user message to chat history
        self._chat_history.append({
            "role": "user",
            "content": user_message,
        })

        # Get tools in provider-native format
        tools = self._get_tools() or []
        model_name = self._get_conscious_model()

        # Dispatch to the correct provider
        provider = self._provider_name
        if provider == "anthropic":
            result_text = self._think_anthropic(
                system_prompt_text, tools, model_name
            )
        elif provider == "openai":
            result_text = self._think_openai(
                system_prompt_text, tools, model_name
            )
        else:  # Default: gemini
            result_text = self._think_gemini(
                system_prompt_text, tools, model_name
            )

        # Decrement hyperfocus
        if getattr(self, "hyperfocus_pulses_remaining", 0) > 0:
            self.hyperfocus_pulses_remaining -= 1
            if self.hyperfocus_pulses_remaining == 0:
                logger.info("Hyperfocus mode exhausted — returning to standard baseline.")

        # Add model response to chat history (text-only for continuity)
        if result_text:
            self._chat_history.append({
                "role": "assistant",
                "content": result_text,
            })

            # Cap chat history to prevent token explosion
            if len(self._chat_history) > 30:
                self._chat_history = (
                    self._chat_history[:2] + self._chat_history[-20:]
                )

        return result_text

    # ── Provider: Gemini ──────────────────────────────────────────────

    def _think_gemini(self, system_prompt: str, tools: list, model_name: str) -> str:
        """Call Google Gemini with native function calling."""
        try:
            from google.genai import types
        except ImportError:
            logger.error("google-genai not installed — cannot use Gemini provider")
            return ""

        start_time = time.time()

        try:
            # Build Gemini-format content
            contents = []
            for msg in self._chat_history:
                role = "user" if msg["role"] == "user" else "model"
                contents.append(types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=msg["content"])],
                ))

            # Create generate config
            config = types.GenerateContentConfig(
                system_instruction=system_prompt,
                tools=tools if tools else None,
                temperature=0.7,
            )

            response = self.gemini.client.models.generate_content(
                model=model_name,
                contents=contents,
                config=config,
            )

            elapsed = time.time() - start_time

            # Track costs
            input_tokens = getattr(response.usage_metadata, 'prompt_token_count', 0) or 0
            output_tokens = getattr(response.usage_metadata, 'candidates_token_count', 0) or 0
            cost = self._compute_cost(model_name, input_tokens, output_tokens, "gemini")
            self.gemini._log_call(
                model=model_name,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                elapsed=elapsed,
                prompt_preview=f"heartbeat_{self._heartbeat_count}",
                provider="gemini",
            )

            # Extract text and function calls
            result_text = ""
            if response.text:
                result_text = response.text

            # Handle Gemini function calls
            if response.candidates and response.candidates[0].content:
                for part in response.candidates[0].content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
                        fc = part.function_call
                        tool_result = self._execute_single_tool(
                            fc.name, dict(fc.args) if fc.args else {}
                        )
                        if tool_result:
                            result_text = (result_text + "\n" + tool_result).strip()

            return result_text

        except Exception as e:
            err_str = str(e)
            if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                raise Exception("429 rate_limit")
            raise Exception(f"Gemini API error: {e}")

    # ── Provider: Anthropic ───────────────────────────────────────────

    def _think_anthropic(self, system_prompt: str, tools: list, model_name: str) -> str:
        """Call Anthropic Claude with native tool use."""
        try:
            import anthropic
        except ImportError:
            logger.error("anthropic not installed — run: pip install anthropic")
            return ""

        # Lazy init client
        if self._provider_client is None:
            api_key = os.environ.get("ANTHROPIC_API_KEY", "")
            if not api_key:
                logger.error("ANTHROPIC_API_KEY not set — cannot think")
                return ""
            self._provider_client = anthropic.Anthropic(api_key=api_key)

        start_time = time.time()

        try:
            response = self._provider_client.messages.create(
                model=model_name,
                max_tokens=4096,
                system=system_prompt,
                tools=tools if tools else anthropic.NOT_GIVEN,
                messages=list(self._chat_history),
            )
        except anthropic.RateLimitError:
            raise Exception("429 rate_limit")
        except anthropic.APIStatusError as e:
            raise Exception(f"Anthropic API error: {e.status_code} {e.message}")

        elapsed = time.time() - start_time

        # Track costs
        input_tokens = response.usage.input_tokens or 0
        output_tokens = response.usage.output_tokens or 0
        cost = self._compute_cost(model_name, input_tokens, output_tokens, "anthropic")
        self.gemini._log_call(
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            elapsed=elapsed,
            prompt_preview=f"heartbeat_{self._heartbeat_count}",
            provider="anthropic",
        )

        # Extract text and tool_use blocks
        text_parts = []
        tool_use_blocks = []

        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_use_blocks.append(block)

        result_text = "\n".join(text_parts)

        # Execute tool calls if any (with sequential chaining)
        if tool_use_blocks:
            tool_results_text = self._execute_tool_calls_anthropic(
                tool_use_blocks, response, system_prompt, tools, model_name
            )
            if tool_results_text:
                result_text = (result_text + "\n" + tool_results_text).strip()

        return result_text

    # ── Provider: OpenAI ──────────────────────────────────────────────

    def _think_openai(self, system_prompt: str, tools: list, model_name: str) -> str:
        """Call OpenAI GPT with native function calling."""
        try:
            import openai
        except ImportError:
            logger.error("openai not installed — run: pip install openai")
            return ""

        # Lazy init client
        if self._provider_client is None:
            api_key = os.environ.get("OPENAI_API_KEY", "")
            if not api_key:
                logger.error("OPENAI_API_KEY not set — cannot think")
                return ""
            self._provider_client = openai.OpenAI(api_key=api_key)

        start_time = time.time()

        try:
            # Build OpenAI messages format
            messages = [{"role": "system", "content": system_prompt}]
            for msg in self._chat_history:
                messages.append({
                    "role": msg["role"],
                    "content": msg["content"],
                })

            # Convert tools to OpenAI function format
            openai_tools = self._tools_to_openai(tools) if tools else None

            kwargs = {
                "model": model_name,
                "messages": messages,
                "max_tokens": 4096,
            }
            if openai_tools:
                kwargs["tools"] = openai_tools

            response = self._provider_client.chat.completions.create(**kwargs)

        except openai.RateLimitError:
            raise Exception("429 rate_limit")
        except openai.APIStatusError as e:
            raise Exception(f"OpenAI API error: {e.status_code} {e.message}")

        elapsed = time.time() - start_time

        # Track costs
        input_tokens = response.usage.prompt_tokens or 0
        output_tokens = response.usage.completion_tokens or 0
        cost = self._compute_cost(model_name, input_tokens, output_tokens, "openai")
        self.gemini._log_call(
            model=model_name,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost=cost,
            elapsed=elapsed,
            prompt_preview=f"heartbeat_{self._heartbeat_count}",
            provider="openai",
        )

        choice = response.choices[0]
        result_text = choice.message.content or ""

        # Handle OpenAI tool calls
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                import json
                tool_name = tc.function.name
                tool_args = json.loads(tc.function.arguments) if tc.function.arguments else {}
                tool_result = self._execute_single_tool(tool_name, tool_args)
                if tool_result:
                    result_text = (result_text + "\n" + tool_result).strip()

        return result_text

    def _tools_to_openai(self, tools: list) -> list:
        """Convert universal tool dicts to OpenAI function calling format."""
        result = []
        try:
            from brain.tool_schema import ALL_TOOLS
            for tool in ALL_TOOLS:
                properties = {}
                required = []
                for pname, pinfo in tool.get("parameters", {}).items():
                    properties[pname] = {
                        "type": pinfo["type"],
                        "description": pinfo.get("description", ""),
                    }
                    if pinfo.get("required", False):
                        required.append(pname)
                result.append({
                    "type": "function",
                    "function": {
                        "name": tool["name"],
                        "description": tool["description"],
                        "parameters": {
                            "type": "object",
                            "properties": properties,
                            "required": required,
                        },
                    },
                })
        except Exception as e:
            logger.debug(f"OpenAI tool conversion failed: {e}")
        return result

    # ── Single Tool Execution (shared by Gemini/OpenAI) ───────────────

    def _execute_single_tool(self, tool_name: str, tool_args: dict) -> str:
        """Execute a single tool call and return the result string."""
        tool_runner = None
        if self._pulse_router and hasattr(self._pulse_router, 'action_agent'):
            agent = self._pulse_router.action_agent
            if hasattr(agent, 'tool_runner'):
                tool_runner = agent.tool_runner

        if not tool_runner:
            return f"Tool {tool_name} not available"

        try:
            result = tool_runner.execute(tool_name, tool_args)
            self._last_used_tools = True
            if tool_name == "send_telegram":
                self._idle_pulse_count = 0
                self._mind_settled = False
                self._last_message_time = time.time()
            return str(result)
        except Exception as e:
            return f"Tool error: {e}"

    # ── Cost Computation (all providers) ──────────────────────────────

    def _compute_cost(self, model: str, input_tokens: int, output_tokens: int, provider: str) -> float:
        """Compute cost for any provider."""
        pricing = {
            # Anthropic
            "claude-haiku-4-5": {"input": 0.80, "output": 4.00},
            "claude-haiku-4-5-20250414": {"input": 0.80, "output": 4.00},
            "claude-sonnet-4-20250514": {"input": 3.00, "output": 15.00},
            # OpenAI
            "gpt-4o-mini": {"input": 0.15, "output": 0.60},
            "gpt-4o": {"input": 2.50, "output": 10.00},
            "gpt-4.1-mini": {"input": 0.40, "output": 1.60},
            "gpt-4.1": {"input": 2.00, "output": 8.00},
            # Gemini
            "gemini-2.5-flash-preview-04-17": {"input": 0.15, "output": 0.60},
            "gemini-2.5-pro-preview-05-06": {"input": 1.25, "output": 10.00},
        }
        rates = pricing.get(model, {"input": 1.00, "output": 5.00})
        return (input_tokens / 1_000_000) * rates["input"] + (output_tokens / 1_000_000) * rates["output"]


    def _execute_tool_calls_anthropic(
        self, tool_use_blocks, initial_response, system_prompt_text, tools, model_name
    ):
        """Execute Anthropic tool_use calls with sequential chaining.

        Each API call that returns tool_use blocks triggers execution.
        Tool results are sent back as tool_result content blocks.
        Continues until the model stops calling tools or safety cap is hit.
        """

        # Get the tool runner from pulse router
        tool_runner = None
        if self._pulse_router and hasattr(self._pulse_router, 'action_agent'):
            agent = self._pulse_router.action_agent
            if hasattr(agent, 'tool_runner'):
                tool_runner = agent.tool_runner

        accumulated_text = []
        current_tool_blocks = tool_use_blocks

        # Build running messages for multi-turn tool chaining
        # We need the full assistant response (with tool_use blocks) in the history
        running_messages = list(self._chat_history)

        # Add the initial assistant response with tool_use blocks
        running_messages.append({
            "role": "assistant",
            "content": [{"type": b.type, "id": b.id, "name": b.name, "input": b.input} if b.type == "tool_use" else {"type": "text", "text": b.text} for b in initial_response.content],
        })

        for pulse_num in range(self.SEQUENTIAL_CHAIN_LIMIT):
            # Execute each tool call
            tool_result_blocks = []
            for block in current_tool_blocks:
                tool_name = block.name
                tool_input = block.input or {}
                tool_use_id = block.id

                logger.info(
                    f"Tool call [pulse {pulse_num + 1}]: "
                    f"{tool_name}({tool_input})"
                )

                result_str = f"Tool {tool_name} not available"
                if tool_runner:
                    try:
                        result_str = tool_runner.execute(tool_name, tool_input)
                    except Exception as e:
                        result_str = f"Tool error: {e}"

                # V6: Mark tools used (prevents nap on this pulse)
                self._last_used_tools = True

                # V6: Outgoing messages reset idle pulse counter
                if tool_name == "send_telegram":
                    self._idle_pulse_count = 0
                    self._mind_settled = False
                    self._last_message_time = time.time()

                # Emit tool result to consciousness stream
                self.emit("tool_call", {
                    "tool": tool_name,
                    "result": str(result_str),
                    "args": tool_input,
                })

                tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": str(result_str),
                })

            # Send tool results back to the model
            try:
                running_messages.append({
                    "role": "user",
                    "content": tool_result_blocks,
                })

                start_time = time.time()

                import anthropic as _anthropic
                follow_response = self._provider_client.messages.create(
                    model=model_name,
                    max_tokens=4096,
                    system=system_prompt_text,
                    tools=tools if tools else _anthropic.NOT_GIVEN,
                    messages=running_messages,
                )
                elapsed = time.time() - start_time

                # Track costs
                input_tokens = follow_response.usage.input_tokens or 0
                output_tokens = follow_response.usage.output_tokens or 0
                cost = self._compute_cost(
                    model_name, input_tokens, output_tokens, "anthropic"
                )
                self.gemini._log_call(
                    model=model_name,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    cost=cost,
                    elapsed=elapsed,
                    prompt_preview=(
                        f"tool_chain_{self._heartbeat_count}"
                        f"_pulse_{pulse_num + 1}"
                    ),
                    provider="anthropic",
                )

                # Separate text from tool_use blocks
                new_text = []
                new_tool_blocks = []
                for block in follow_response.content:
                    if block.type == "text" and block.text:
                        new_text.append(block.text)
                    elif block.type == "tool_use":
                        new_tool_blocks.append(block)

                if new_text:
                    accumulated_text.append("\n".join(new_text))

                if new_tool_blocks:
                    # More tools requested — continue the chain
                    current_tool_blocks = new_tool_blocks
                    # Add this assistant response to running messages
                    running_messages.append({
                        "role": "assistant",
                        "content": [{"type": b.type, "id": b.id, "name": b.name, "input": b.input} if b.type == "tool_use" else {"type": "text", "text": b.text} for b in follow_response.content],
                    })
                    logger.info(
                        f"Sequential chain continuing "
                        f"(pulse {pulse_num + 1} → {pulse_num + 2})"
                    )
                    continue
                else:
                    # No more tools — chain ends naturally
                    logger.info(
                        f"Sequential chain complete after "
                        f"{pulse_num + 1} pulse(s)"
                    )
                    break

            except Exception as e:
                logger.warning(
                    f"Tool chain pulse {pulse_num + 1} failed: {e}"
                )
                break
        else:
            # Hit the safety cap
            logger.warning(
                f"Sequential chain hit safety cap "
                f"({self.SEQUENTIAL_CHAIN_LIMIT} pulses)"
            )

        return "\n".join(accumulated_text)

    def _get_tools(self):
        """Get tool declarations in the native format for the active provider.

        Uses tool_schema.py as the single source of truth, converting
        to Gemini, Anthropic, or OpenAI format based on config.
        """
        provider = self._provider_name
        try:
            from brain.tool_schema import to_gemini, to_anthropic, ALL_TOOLS
            if provider == "anthropic":
                return to_anthropic(ALL_TOOLS)
            elif provider == "openai":
                return ALL_TOOLS  # Converted in _think_openai
            else:  # gemini
                from google.genai import types
                return [types.Tool(function_declarations=to_gemini(ALL_TOOLS))]
        except Exception as e:
            logger.debug(f"Tool loading failed: {e}")
            return None

    def _get_conscious_model(self) -> str:
        """Get the consciousness model name from config.

        Returns the model name for the active provider.
        Defaults per provider:
          - gemini:    gemini-2.5-flash-preview-04-17
          - anthropic: claude-haiku-4-5
          - openai:    gpt-4o-mini
        """
        provider = self._provider_name
        defaults = {
            "gemini": "gemini-2.5-flash-preview-04-17",
            "anthropic": "claude-haiku-4-5",
            "openai": "gpt-4o-mini",
        }
        # Check provider-specific config
        provider_config = self._config.get(f"_{provider}_config", {})
        return provider_config.get(
            "conscious_model",
            self._config.get("conscious_model", defaults.get(provider, "gemini-2.5-flash-preview-04-17"))
        )

    # ── System prompt ────────────────────────────────────────────────

    def _build_system_prompt(self) -> str | list[dict]:
        """Build the system prompt from beliefs and working state.

        Identity comes entirely from the belief graph — no hardcoded
        personality, name, or relationship blocks. The only hardcoded
        content is mechanical: how to use tools and output formats.
        
        V6: Returns a list of content blocks if provider is Anthropic
        to enable prompt caching, otherwise returns a single string.
        """
        core_text, horizon_text = self._build_belief_context()

        static_sections = []
        if core_text:
            static_sections.append(core_text)

        static_sections.append(
            "## Mechanical notes\n"
            "To schedule a future task, include this tag in your thoughts:\n"
            "[SCHEDULE:minutes] description of what to do"
        )
        static_block = "\n\n".join(static_sections)

        dynamic_sections = []
        if horizon_text:
            dynamic_sections.append(horizon_text)

        if self._spatial_context:
            dynamic_sections.append(self._spatial_context)

        state_text = self._build_state_board_context()
        if state_text:
            dynamic_sections.append(state_text)

        memory_context = self._build_memory_context()
        if memory_context:
            dynamic_sections.append(memory_context)

        scratchpad_text = self._build_scratchpad_context()
        if scratchpad_text:
            dynamic_sections.append(scratchpad_text)

        dynamic_block = "\n\n".join(dynamic_sections)

        # Provider specific format
        if self._provider_name == "anthropic":
            blocks = [
                {
                    "type": "text",
                    "text": static_block,
                    "cache_control": {"type": "ephemeral"}
                }
            ]
            if dynamic_block:
                blocks.append({
                    "type": "text",
                    "text": dynamic_block
                })
            return blocks
        else:
            final_sections = [static_block]
            if dynamic_block:
                final_sections.append(dynamic_block)
            return "\n\n".join(final_sections)

    def _build_belief_context(self) -> tuple[str, str]:
        """V4: Build belief context using the Keeper's horizon system.

        Instead of dumping ALL beliefs (~15K tokens), this surfaces:
        1. Core beliefs (identity axioms, always present)
        2. Keeper horizon (contextually relevant beliefs for THIS pulse)

        Returns:
            (core_beliefs_str, horizon_beliefs_str)
        """
        core_sections = ["## My Beliefs"]

        # 1. Core beliefs — always present, identity floor
        core = self.keeper.get_core_beliefs()
        if core:
            core_sections.append("### Core")
            for b in core:
                core_sections.append(f"- {b}")

        core_str = "\n".join(core_sections)
        
        horizon_sections = []
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
            horizon_sections.append("### What feels familiar right now")
            for b in horizon:
                horizon_sections.append(f"- {b}")

        horizon_str = "\n".join(horizon_sections) if horizon_sections else ""
        return (core_str, horizon_str)

    def _build_state_board_context(self) -> str:
        """V6: Build the State Board — raw spatial physics, no interpretation.

        The model receives raw numbers and interprets its own state.
        No word descriptors — those are the model's job, not ours.
        """
        import json

        if self.sentinel:
            try:
                snapshot = self.sentinel.get_lagrangian_snapshot()
                omega = snapshot.get("omega", 0.5)
                severity = snapshot.get("severity", "all_clear")
                H = snapshot.get("H", 0)
                D_KL = snapshot.get("D_KL", 0)
                T = snapshot.get("T", 1.0)
                s_total = snapshot.get("s_total", 0)

                self._state_board["spatial"] = {
                    "Ω": round(omega, 3),
                    "H": round(H, 3),
                    "D_KL": round(D_KL, 3),
                    "T": round(T, 3),
                    "S": round(s_total, 3),
                    "severity": severity,
                }

            except Exception:
                pass

        # V6: Inject affordances as felt intentions
        if self._spatial_mind and self._interaction_engine:
            try:
                pos = self._spatial_mind.attention_center
                affordances = self._interaction_engine.compute_affordances(
                    pos, self._heartbeat_count, threshold=0.3
                )
                if affordances:
                    intentions = []
                    for aff in affordances[:3]:
                        desire = aff.get("desire", "")[:60]
                        tool = aff.get("tool_name", "")
                        intentions.append(f"{desire} (→ {tool})")
                    self._state_board["felt_intentions"] = intentions
                elif "felt_intentions" in self._state_board:
                    del self._state_board["felt_intentions"]
            except Exception:
                pass

        board_json = json.dumps(self._state_board, indent=2)
        return f"## Current State\n```\n{board_json}\n```"

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
                source="consciousness",
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
            "chat_history_length": len(self._chat_history),
            "events_queued": len(self._event_queue),
            "last_message_age": (
                time.time() - self._last_message_time
                if self._last_message_time > 0
                else None
            ),
        }


# ═══════════════════════════════════════════════════════════════════════
# V6: LOCAL CONSCIOUSNESS LOOP — Physics-Driven Spatial Awareness
# ═══════════════════════════════════════════════════════════════════════
#
# The manifold IS the mind. The LLM is just the spark.
#
# Architecture:
#     1. Physics tick (1Hz): Update attention, forces, trail, affordances
#     2. If affordances exist OR external input received: call local LLM
#     3. LLM receives spatial prompt (~200 tokens)
#     4. LLM outputs: natural language thought + optional tool parameters
#     5. If tool needed: call Action Agent (Gemini Flash for complex tools)
#     6. Deposit trail particle at current position
#     7. Return to step 1
#
# Model options (via Ollama):
#     - huihui_ai/qwen3.5-abliterated:0.8B (1.0 GB) — fastest
#     - huihui_ai/qwen3.5-abliterated:4B (3.3 GB) — balanced
#     - helix-persona:latest (3.3 GB) — identity-trained
# ═══════════════════════════════════════════════════════════════════════


class V6ConsciousnessLoop:
    """V6 consciousness: continuous physics + on-demand local LLM.

    The physics tick runs at 1Hz. LLM calls happen only when:
    - An interaction potential generates a tool affordance
    - External input arrives (message, event, stimulus)
    - The system needs natural language output

    Between LLM calls, the manifold evolves on pure equations:
    forces move the attention center, trail particles accumulate,
    and beliefs precipitate from dense clusters.
    """

    def __init__(
        self,
        spatial_mind=None,
        sentinel=None,
        interaction_engine=None,
        precipitation=None,
        spatial_prompt_builder=None,
        action_agent=None,
        ollama_model: str = "huihui_ai/qwen3.5-abliterated:4B",
        ollama_host: str = "http://localhost:11434",
        physics_interval: float = 1.0,
        precipitation_interval: int = 50,  # every N pulses
    ):
        self.spatial_mind = spatial_mind
        self.sentinel = sentinel
        self.interaction_engine = interaction_engine
        self.precipitation = precipitation
        self.prompt_builder = spatial_prompt_builder
        self.action_agent = action_agent

        # Ollama config
        self.ollama_model = ollama_model
        self.ollama_host = ollama_host

        # Timing
        self.physics_interval = physics_interval
        self.precipitation_interval = precipitation_interval

        # State
        self._pulse_id = 0
        self._running = False
        self._thread = None
        self._external_queue: list[dict] = []
        self._queue_lock = threading.Lock()

        # History
        self._thoughts: list[dict] = []
        self._last_llm_call_time = 0.0

        # Callbacks
        self._on_thought: Optional[Callable] = None
        self._on_action: Optional[Callable] = None

        logger.info(
            f"V6ConsciousnessLoop initialized: model={ollama_model}, "
            f"physics_interval={physics_interval}s"
        )

    # ── Main Loop ────────────────────────────────────────────────────

    def start(self):
        """Start the consciousness loop in a background thread."""
        if self._running:
            logger.warning("Consciousness loop already running")
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            daemon=True,
            name="v6-consciousness",
        )
        self._thread.start()
        logger.info("V6 consciousness loop started")

    def stop(self):
        """Stop the consciousness loop."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=10)
        logger.info("V6 consciousness loop stopped")

    def _loop(self):
        """Main consciousness loop — runs continuously."""
        while self._running:
            try:
                self._physics_tick()
            except Exception as e:
                logger.error(f"Consciousness tick error: {e}")

            time.sleep(self.physics_interval)

    # ── Physics Tick ─────────────────────────────────────────────────

    def _physics_tick(self):
        """One tick of the consciousness loop.

        1. Update attention center via force integration
        2. Compute affordances
        3. Check for external input
        4. If affordances or input → call LLM
        5. If LLM produced tool intent → call action agent
        6. Deposit trail particle
        7. Periodic: run belief precipitation
        """
        self._pulse_id += 1

        if not self.spatial_mind:
            return

        # 1. Get current state
        position = self.spatial_mind.attention_center.copy()
        space = self.spatial_mind.belief_space

        # 2. Compute affordances from interaction potentials
        affordances = []
        if self.interaction_engine:
            affordances = self.interaction_engine.compute_affordances(
                position, self._pulse_id
            )

        # 3. Check for external input
        external_input = self._drain_external_queue()

        # 4. Decide whether to call the LLM
        needs_llm = (
            len(affordances) > 0 or
            len(external_input) > 0
        )

        thought_text = ""

        if needs_llm:
            # Build spatial prompt
            nearby_beliefs = space.gravity_ranked_query(position, k=6)
            nearby_memories = self.spatial_mind.memory_space.gravity_ranked_query(
                position, k=3
            )

            # Get trail particles for context
            recent_trail = space.get_trail_particles(
                position=position, radius=1.0, max_age_seconds=1800
            )

            # Compute forces for the prompt
            forces = {
                "F_grav": space.compute_gravity_force(position),
                "F_stab": space.compute_stability_force(
                    position, self.spatial_mind._identity_center,
                    self.sentinel.omega if self.sentinel else 0.5
                ),
            }

            # Get Lagrangian snapshot
            lagrangian = (self.sentinel.get_lagrangian_snapshot()
                         if self.sentinel else None)

            # Build the prompt
            if self.prompt_builder:
                # Format external input
                input_text = None
                if external_input:
                    input_text = " | ".join(
                        e.get("content", "") for e in external_input
                    )

                spatial_state = self.prompt_builder.build(
                    position=position,
                    velocity=self.spatial_mind._velocity,
                    identity_center=self.spatial_mind._identity_center,
                    nearby_beliefs=nearby_beliefs,
                    nearby_memories=nearby_memories,
                    forces=forces,
                    affordances=affordances,
                    trail_particles=recent_trail,
                    lagrangian_snapshot=lagrangian,
                    external_input=input_text,
                )

                system_prompt = self.prompt_builder.build_system_prompt(
                    spatial_state
                )

                # Call the local LLM
                thought_text = self._call_local_llm(system_prompt)

                if thought_text:
                    self._thoughts.append({
                        "pulse_id": self._pulse_id,
                        "thought": thought_text[:500],
                        "affordances": len(affordances),
                        "external_input": len(external_input),
                        "timestamp": time.time(),
                    })

                    # Notify callback
                    if self._on_thought:
                        self._on_thought(thought_text, self._pulse_id)

            # 5. If affordances with tool_name → execute via action agent
            if affordances and self.action_agent:
                for aff in affordances:
                    tool_name = aff.get("tool_name")
                    if tool_name:
                        result = self._execute_affordance(
                            aff, thought_text
                        )
                        if result and result.get("success"):
                            if self.sentinel:
                                self.sentinel.nudge_omega_from_event(
                                    "successful_tool_call"
                                )
                            if self.interaction_engine:
                                self.interaction_engine.mark_executed(
                                    tool_name, self._pulse_id
                                )
                        elif self.sentinel:
                            self.sentinel.nudge_omega_from_event(
                                "tool_failure"
                            )

        # 6. Deposit trail particle
        if thought_text or external_input:
            content = thought_text[:80] if thought_text else (
                external_input[0].get("content", "")[:80]
                if external_input else ""
            )
            space.deposit_trail_particle(
                position=position,
                content=content,
                pulse_id=self._pulse_id,
                omega=self.sentinel.omega if self.sentinel else 0.5,
            )

        # 7. Decay trail particles
        space.decay_trail_particles()

        # 8. Periodic belief precipitation
        if (self.precipitation and
                self._pulse_id % self.precipitation_interval == 0):
            new_beliefs = self.precipitation.scan_and_precipitate()
            for belief in new_beliefs:
                if self.sentinel:
                    self.sentinel.nudge_omega_from_event("new_belief_formed")

        # 9. Update spatial mind (advance attention via forces)
        if thought_text:
            embedding = self.spatial_mind.embed_text(thought_text)
            if embedding is not None and np.any(embedding):
                self.spatial_mind.pulse(embedding)

    # ── LLM Interface ────────────────────────────────────────────────

    def _call_local_llm(self, prompt: str) -> str:
        """Call the local Ollama model with the spatial prompt."""
        try:
            import requests
            response = requests.post(
                f"{self.ollama_host}/api/generate",
                json={
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": self._get_temperature(),
                        "num_predict": 256,
                    },
                },
                timeout=30,
            )
            response.raise_for_status()
            result = response.json()
            self._last_llm_call_time = time.time()
            return result.get("response", "").strip()

        except Exception as e:
            logger.error(f"Local LLM call failed: {e}")
            return ""

    def _get_temperature(self) -> float:
        """Get LLM temperature from the cognitive manifold's local T."""
        if self.sentinel:
            T = getattr(self.sentinel, '_spatial_T', 1.0)
            return max(0.1, min(1.5, float(T) * 0.7))
        return 0.7

    # ── Action Agent Interface ───────────────────────────────────────

    def _execute_affordance(
        self, affordance: dict, thought_text: str
    ) -> Optional[dict]:
        """Execute a tool affordance via the action agent (Gemini Flash)."""
        if not self.action_agent:
            return None

        instruction = (
            f"Execute tool '{affordance.get('tool_name', 'unknown')}' "
            f"because: {affordance.get('desire', 'unknown desire')} → "
            f"{affordance.get('capability', 'unknown capability')}. "
            f"Interaction potential: {affordance.get('potential', 0):.2f}. "
            f"Context: {thought_text[:500]}"
        )

        try:
            result = self.action_agent.execute(
                instruction=instruction,
                intent_type="resolve",
                stream_context=thought_text,
            )
            return result
        except Exception as e:
            logger.error(f"Affordance execution failed: {e}")
            return {"success": False, "error": str(e)}

    # ── External Input ───────────────────────────────────────────────

    def inject_input(self, content: str, source: str = "external"):
        """Inject external input into the consciousness loop."""
        with self._queue_lock:
            self._external_queue.append({
                "content": content,
                "source": source,
                "timestamp": time.time(),
            })
        if self.sentinel:
            self.sentinel.nudge_omega_from_event("incoming_message")

    def _drain_external_queue(self) -> list[dict]:
        """Drain and return all pending external inputs."""
        with self._queue_lock:
            items = self._external_queue[:]
            self._external_queue.clear()
        return items

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get consciousness loop status."""
        return {
            "running": self._running,
            "pulse_id": self._pulse_id,
            "ollama_model": self.ollama_model,
            "thoughts_count": len(self._thoughts),
            "last_thought": (self._thoughts[-1] if self._thoughts else None),
            "last_llm_call": self._last_llm_call_time,
            "pending_inputs": len(self._external_queue),
        }

    # ── Single Pulse (for testing) ───────────────────────────────────

    def single_pulse(self, external_input: str = None) -> dict:
        """Execute a single consciousness pulse synchronously."""
        if external_input:
            self.inject_input(external_input)
        self._physics_tick()
        return {
            "pulse_id": self._pulse_id,
            "last_thought": (
                self._thoughts[-1] if self._thoughts else None
            ),
        }

