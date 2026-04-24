"""
Helix V5 — Main Daemon

Event-driven orchestrator. Helix sleeps (zero cost) until triggered
by a Telegram message or scheduled task. Wakes with Gemini 3.0 Pro
consciousness, runs heartbeats, sleeps after 15 min of inactivity.

Architecture:
  Gemini 3.0 Pro  = The conscious mind (thinking, responding, tool use)
  Gemini 2.5 Flash = Sub-agents (memory synthesis, classification)
  Sentinel         = Deep subconscious health monitor
  Memory           = Persistent knowledge store
  Belief Graph     = Identity and beliefs
  Scheduler        = Self-scheduled future tasks

Usage:
  python daemon.py           # Normal start
  python daemon.py --dry-run # Initialize, verify, exit
"""

import sys
import signal
import logging
import argparse
import threading
from pathlib import Path

import yaml


# ── Logging setup ────────────────────────────────────────────────────

def setup_logging(config: dict, base_dir: Path):
    log_config = config.get("logging", {})
    log_file = base_dir / log_config.get("file", "logs/daemon.log")
    log_file.parent.mkdir(parents=True, exist_ok=True)

    level = getattr(logging, log_config.get("level", "INFO").upper(), logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.FileHandler(str(log_file))
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    root.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s [%(name)-25s] %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    ))
    root.addHandler(ch)

    return logging.getLogger("helix.daemon")


# ── Daemon class ─────────────────────────────────────────────────────

class HelixDaemon:
    """Helix V5 event-driven orchestrator.

    Initializes subsystems, then enters event-driven mode:
    Telegram polling + scheduler checking run continuously.
    Consciousness wakes on demand and sleeps on timeout.
    """

    def __init__(self, base_dir: Path, config: dict):
        self.base_dir = base_dir
        self.config = config
        self.logger = logging.getLogger("helix.daemon")

        # Subsystem references
        self.gemini = None
        self.memory = None
        self.belief_graph = None
        self.librarian = None
        self.sentinel = None
        self.consciousness = None
        self.pulse_router = None
        self.scheduler = None
        self.deep_thought = None
        self.imagination = None
        self.audio_monitor = None
        self.web_search = None

        self._running = False

    def init_subsystems(self):
        """Initialize all subsystems in dependency order."""
        self.logger.info("=" * 60)
        self.logger.info("HELIX V4 — INITIALIZING")
        self.logger.info("=" * 60)

        step = 0

        # 1. Gemini Client (consciousness + tools)
        step += 1
        self.logger.info(f"[{step}/10] Initializing Gemini client...")
        from gemini_client import GeminiClient
        self.gemini = GeminiClient(self.config, self.base_dir)
        self.logger.info(
            f"Gemini ready (conscious={self.gemini.conscious_model}, "
            f"default={self.gemini.default_model})"
        )

        # 2. Memory
        step += 1
        self.logger.info(f"[{step}/10] Initializing Memory system...")
        from brain.memory import Memory
        self.memory = Memory(self.base_dir, self.config)
        stats = self.memory.get_stats()
        self.logger.info(
            f"Memory ready: {stats['total_memories']} memories, "
            f"{stats.get('chroma_count', 0)} vectors"
        )

        # 3. Belief Graph
        step += 1
        self.logger.info(f"[{step}/10] Initializing Belief Graph...")
        from brain.belief_graph import BeliefGraph
        self.belief_graph = BeliefGraph(self.base_dir / "brain" / "belief_graph.json")
        stats = self.belief_graph.get_stats()
        self.logger.info(
            f"Belief graph ready: {stats['total_beliefs']} beliefs "
            f"(core={stats.get('core', 0)}, deep={stats.get('deep', 0)}, "
            f"surface={stats.get('surface', 0)})"
        )

        # 3b. Cognitive Manifold (8D spatial folding)
        step += 1
        self.logger.info(f"[{step}/10] Initializing Cognitive Manifold...")
        try:
            from brain.manifold.projector import ManifoldProjector
            from brain.manifold.manifold import CognitiveManifold
            
            manifold_dir = self.base_dir / "brain" / "manifold"
            self.manifold_projector = ManifoldProjector(manifold_dir)
            self.manifold = CognitiveManifold()
            
            # Load nodes from Memory and Belief Graph
            beliefs = self.belief_graph.get_all_beliefs() if self.belief_graph else []
            memories = self.memory.get_all_with_positions() if self.memory else []
            self.manifold.rebuild_index(beliefs, memories)
            self.logger.info(f"Cognitive Manifold ready: {len(self.manifold.nodes)} nodes indexed")
        except Exception as e:
            self.manifold = None
            self.manifold_projector = None
            self.logger.warning(f"Cognitive Manifold init failed: {e}")

        # 4. Librarian
        step += 1
        self.logger.info(f"[{step}/10] Initializing Librarian...")
        from brain.librarian import Librarian
        self.librarian = Librarian(
            memory=self.memory,
            belief_graph=self.belief_graph,
            gemini_client=self.gemini,
            base_dir=self.base_dir,
        )
        self.logger.info("Librarian ready")

        # 5. Stability Sentinel
        step += 1
        self.logger.info(f"[{step}/10] Initializing Stability Sentinel...")
        from brain.stability_sentinel import StabilitySentinel
        self.sentinel = StabilitySentinel(
            base_dir=self.base_dir,
            memory=self.memory,
            gemini_client=self.gemini,
        )
        snapshot = self.sentinel.get_lagrangian_snapshot()
        self.logger.info(
            f"Sentinel ready: Ω={snapshot.get('omega', 0):.3f}, "
            f"S={snapshot.get('S', 0):.3f}"
        )

        # 6. Consciousness Loop (Provider-backed)
        step += 1
        self.logger.info(f"[{step}/10] Initializing Consciousness loop...")
        from brain.consciousness import ConsciousnessLoop
        
        self.consciousness = ConsciousnessLoop(
            gemini_client=self.gemini,
            belief_graph=self.belief_graph,
            memory=self.memory,
            base_dir=self.base_dir,
            config=self.config,
            sentinel=self.sentinel,
        )
        conscious_name = self.config.get("conscious_provider", "gemini")
        self.logger.info(f"Consciousness ready ({conscious_name.upper()} provider)")

        # Wire Librarian into consciousness for memory grounding
        self.consciousness._librarian = self.librarian

        # Wire Cognitive Manifold to Librarian and Consciousness
        if hasattr(self, 'manifold') and self.manifold:
            if hasattr(self.librarian, 'set_manifold'):
                self.librarian.set_manifold(self.manifold, self.manifold_projector)
            if hasattr(self.consciousness, 'keeper') and self.consciousness.keeper:
                self.consciousness.keeper.set_manifold(self.manifold, self.manifold_projector)
            self.consciousness._manifold = self.manifold

        # Wire Sensory Cortex into consciousness for perception
        try:
            from brain.sensory_cortex import SensoryCortex
            self.sensory_cortex = SensoryCortex(
                daemon=self,
                base_dir=self.base_dir,
                config=self.config.get("sensory", {}),
            )
            self.consciousness._sensory_cortex = self.sensory_cortex
            self.logger.info("Sensory Cortex ready")
        except Exception as e:
            self.sensory_cortex = None
            self.logger.warning(f"Sensory Cortex init failed: {e}")

        # 7. Scheduler
        step += 1
        self.logger.info(f"[{step}/10] Initializing Scheduler...")
        from brain.scheduler import Scheduler
        self.scheduler = Scheduler(
            base_dir=self.base_dir,
            config=self.config.get("scheduler", {}),
            wake_callback=self._on_scheduled_task,
        )
        self.logger.info(
            f"Scheduler ready ({len(self.scheduler.get_pending())} pending tasks)"
        )

        # 7b. Web Search backend
        try:
            from tools.web_search import WebSearch
            self.web_search = WebSearch(config=self.config)
            self.logger.info("Web Search ready (DuckDuckGo + BeautifulSoup)")
        except Exception as e:
            self.logger.warning(f"Web Search init failed (search grounding still available): {e}")
            self.web_search = None

        # 8. PulseRouter
        step += 1
        self.logger.info(f"[{step}/10] Initializing PulseRouter...")
        from brain.pulse_router import PulseRouter
        self.pulse_router = PulseRouter(
            consciousness=self.consciousness,
            memory=self.memory,
            sentinel=self.sentinel,
            scheduler=self.scheduler,
            librarian=self.librarian,
        )
        # Wire pulse router into consciousness
        self.consciousness._pulse_router = self.pulse_router

        # Wire action agent (for tool execution via consciousness)
        try:
            from brain.action_agent import ActionAgent
            from tools.tool_runner import ToolRunner
            tool_runner = ToolRunner(self)
            action_agent = ActionAgent(
                gemini_client=self.gemini,
                tool_runner=tool_runner,
                memory=self.memory,
                belief_graph=self.belief_graph,
                base_dir=self.base_dir,
            )
            self.pulse_router.action_agent = action_agent
            self.logger.info("Action Agent wired with tools")
        except Exception as e:
            self.logger.warning(f"Action Agent init skipped: {e}")

        # Wire deep thought engine
        try:
            from brain.deep_thought import DeepThoughtEngine
            self.deep_thought = DeepThoughtEngine(
                gemini_client=self.gemini,
                memory=self.memory,
                belief_graph=self.belief_graph,
                librarian=self.librarian,
                event_callback=self.consciousness.emit,
            )
            self.logger.info("Deep Thought Engine ready")
        except Exception as e:
            self.logger.warning(f"Deep Thought Engine init skipped: {e}")

        # Wire imagination engine (needs spatial mind/manifold from consciousness)
        try:
            spatial_mind = getattr(self.consciousness, '_manifold', None)
            if spatial_mind:
                from brain.imagination import ImaginationEngine
                self.imagination = ImaginationEngine(spatial_mind)
                self.logger.info("Imagination Engine ready")
            else:
                self.logger.info("Imagination Engine skipped (no spatial mind)")
        except Exception as e:
            self.logger.warning(f"Imagination Engine init skipped: {e}")

        self.logger.info("PulseRouter ready")

        # 8b. Unconscious System (overnight processing)
        try:
            from brain.unconscious import UnconsciousSystem
            self.unconscious = UnconsciousSystem(
                memory=self.memory,
                belief_graph=self.belief_graph,
                gemini_client=self.gemini,
                base_dir=self.base_dir,
                spatial_mind=getattr(self.consciousness, '_manifold', None),
            )
            
            # Wire agents to unconscious for nightly convergence
            keeper = getattr(self.consciousness, 'keeper', None)
            if keeper and hasattr(self, 'librarian'):
                if hasattr(self.unconscious, 'set_agents'):
                    self.unconscious.set_agents(keeper=keeper, librarian=self.librarian)
            # Schedule first overnight cycle + pre-dawn + morning pulse
            self._schedule_overnight()
            self._schedule_pre_dawn_briefing()
            self._schedule_morning_pulse()
            self.logger.info("Unconscious system ready (overnight + pre-dawn + morning pulse scheduled)")
        except Exception as e:
            self.unconscious = None
            self.logger.warning(f"Unconscious system init skipped: {e}")

        # 9. Communication Channels (Telegram / Terminal)
        step += 1
        self.logger.info(f"[{step}/10] Initializing Communication Channels...")
        self.telegram_bot = None
        self.terminal_bot = None
        
        try:
            from comms.telegram_bot import HelixTelegramBot
            self.telegram_bot = HelixTelegramBot(config=self.config)
            if self.telegram_bot.enabled:
                self.telegram_bot.set_pulse_router(self.pulse_router)
                self.pulse_router.register_delivery_channel(
                    "telegram", self.telegram_bot.send_message
                )
                self.logger.info("Telegram bot ready")
            else:
                self.telegram_bot = None
        except Exception as e:
            self.logger.error(f"Telegram bot init failed: {e}")
            self.telegram_bot = None

        if not self.telegram_bot:
            try:
                from comms.terminal_interface import HelixTerminalBot
                self.terminal_bot = HelixTerminalBot(config=self.config)
                self.terminal_bot.set_pulse_router(self.pulse_router)
                self.pulse_router.register_delivery_channel(
                    "terminal", self.terminal_bot.send_message
                )
                self.logger.info("Local Terminal Interface ready (Fallback mode)")
            except Exception as e:
                self.logger.error(f"Terminal interface init failed: {e}")

        # 10. Passive Audio Monitor
        audio_cfg = self.config.get("audio", {})
        if audio_cfg.get("enabled", False):
            step += 1
            self.logger.info(f"[{step}/10] Initializing Audio Monitor...")
            try:
                from brain.audio_monitor import AudioMonitor
                self.audio_monitor = AudioMonitor(
                    consciousness=self.consciousness,
                    config=audio_cfg,
                )
                self.logger.info("Audio monitor ready")
            except Exception as e:
                self.logger.warning(f"Audio monitor init failed: {e}")
                self.audio_monitor = None
        else:
            self.logger.info("Audio monitor disabled in config")

        self.logger.info("=" * 60)
        self.logger.info("ALL SUBSYSTEMS INITIALIZED")
        self.logger.info("=" * 60)

    def run(self):
        """Run the daemon — enters event-driven mode."""
        self._running = True

        # Start the sentinel
        self.sentinel.start()

        # Start consciousness (enters DORMANT state)
        self.consciousness.start()

        # Start the scheduler
        self.scheduler.start()

        # Start Telegram bot or Terminal fallback
        if self.telegram_bot:
            self.telegram_bot.start()
        elif self.terminal_bot:
            self.terminal_bot.start()

        # Start Audio Monitor
        if self.audio_monitor:
            self.audio_monitor.start()

        self.logger.info(
            "Helix V5 is ONLINE — DORMANT, waiting for messages"
        )

        # Block on main thread
        try:
            signal.pause()
        except KeyboardInterrupt:
            self.logger.info("Keyboard interrupt — shutting down")
        finally:
            self.shutdown()

    # ── Scheduled task handler ───────────────────────────────────────

    def _on_scheduled_task(self, trigger: str):
        """Handle a scheduled task firing."""
        if "OVERNIGHT_CYCLE" in trigger:
            # Run overnight processing in a background thread
            threading.Thread(
                target=self._run_overnight,
                daemon=True,
                name="overnight-cycle",
            ).start()
        elif "PRE_DAWN_BRIEFING" in trigger:
            # Feed overnight briefings to each subconscious agent
            threading.Thread(
                target=self._run_pre_dawn_briefing,
                daemon=True,
                name="pre-dawn-briefing",
            ).start()
        elif "MORNING_PULSE" in trigger:
            # Morning wake-up with briefing
            threading.Thread(
                target=self._run_morning_pulse,
                daemon=True,
                name="morning-pulse",
            ).start()
        else:
            # Normal scheduled wake (reminders etc)
            self.consciousness.wake(trigger)

    # ── Overnight cycle ──────────────────────────────────────────────

    def _schedule_overnight(self):
        """Schedule the overnight cycle to run at ~1:05 AM."""
        from datetime import datetime, timedelta

        now = datetime.now()
        # Target: 1:05 AM tonight or tomorrow
        target = now.replace(hour=1, minute=5, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)

        minutes_until = int((target - now).total_seconds() / 60)
        # Avoid duplicate scheduling if daemon restarts
        desc = "OVERNIGHT_CYCLE: Belief maintenance, memory consolidation, dream synthesis"
        pending = self.scheduler.get_pending()
        if any(desc in t.get("description", "") for t in pending):
            return

        self.scheduler.schedule(
            minutes=minutes_until,
            description=desc,
        )
        self.logger.info(
            f"Overnight cycle scheduled for {target.strftime('%Y-%m-%d %H:%M')} "
            f"({minutes_until} minutes from now)"
        )

    def _run_overnight(self):
        """Execute the overnight processing pipeline."""
        if not self.unconscious:
            self.logger.warning("Overnight cycle skipped — unconscious system not available")
            return

        self.logger.info("=" * 60)
        self.logger.info("OVERNIGHT CYCLE STARTING")
        self.logger.info("=" * 60)

        try:
            results = self.unconscious.run_overnight_cycle()
            self.logger.info(
                f"Overnight cycle complete: "
                f"{results.get('steps', {}).get('nap_notes_collected', 0)} nap notes processed, "
                f"{results.get('steps', {}).get('memories_consolidated', {}).get('memories_pruned', 0)} memories pruned"
            )
        except Exception as e:
            self.logger.error(f"Overnight cycle failed: {e}")

        # Reschedule for next night
        self._schedule_overnight()

    # ── Morning pulse ────────────────────────────────────────────────

    def _schedule_pre_dawn_briefing(self):
        """Schedule pre-dawn briefing for 6:25 AM — 5 min before consciousness wakes.

        Each subconscious agent (Librarian, Sentinel, Sensory Cortex) loads its
        overnight briefing and adjusts its internal state BEFORE Helix wakes up.
        """
        from datetime import datetime, timedelta

        now = datetime.now()
        target = now.replace(hour=6, minute=25, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)

        minutes_until = int((target - now).total_seconds() / 60)
        desc = "PRE_DAWN_BRIEFING: Feed overnight analysis to subconscious agents"
        pending = self.scheduler.get_pending()
        if any(desc in t.get("description", "") for t in pending):
            return

        self.scheduler.schedule(
            minutes=minutes_until,
            description=desc,
        )
        self.logger.info(
            f"Pre-dawn briefing scheduled for {target.strftime('%Y-%m-%d %H:%M')} "
            f"({minutes_until} minutes from now)"
        )

    def _schedule_morning_pulse(self):
        """Schedule the morning wake pulse for 6:30 AM."""
        from datetime import datetime, timedelta

        now = datetime.now()
        target = now.replace(hour=6, minute=30, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)

        minutes_until = int((target - now).total_seconds() / 60)
        # Avoid duplicate scheduling if daemon restarts
        desc = "MORNING_PULSE: Good morning — review dreams, check calendar & email, plan the day"
        pending = self.scheduler.get_pending()
        if any(desc in t.get("description", "") for t in pending):
            return

        self.scheduler.schedule(
            minutes=minutes_until,
            description=desc,
        )
        self.logger.info(
            f"Morning pulse scheduled for {target.strftime('%Y-%m-%d %H:%M')} "
            f"({minutes_until} minutes from now)"
        )

    def _run_pre_dawn_briefing(self):
        """Feed overnight briefings to each subconscious agent.

        Runs 5 minutes before the morning pulse so agents have time
        to adjust their internal state before consciousness wakes.
        """
        import json
        from datetime import datetime

        self.logger.info("=" * 60)
        self.logger.info("PRE-DAWN BRIEFING — Subconscious agents waking")
        self.logger.info("=" * 60)

        briefing_dir = self.base_dir / "brain" / "briefings"
        agents_briefed = []

        # 1. Librarian briefing
        try:
            lib_file = briefing_dir / "librarian_briefing.json"
            if lib_file.exists() and self.librarian:
                briefing = json.loads(lib_file.read_text())
                if briefing.get("summary"):  # Non-empty briefing
                    self.librarian.set_overnight_briefing(briefing)
                    agents_briefed.append("Librarian")
                    self.logger.info(
                        f"Librarian briefed: {len(briefing.get('emphasis_beliefs', []))} emphasis, "
                        f"{len(briefing.get('guidance', []))} guidance notes"
                    )
        except Exception as e:
            self.logger.warning(f"Librarian briefing failed: {e}")

        # 2. Sentinel briefing
        try:
            sent_file = briefing_dir / "sentinel_briefing.json"
            if sent_file.exists() and self.sentinel:
                briefing = json.loads(sent_file.read_text())
                if briefing.get("summary"):
                    # Feed stability notes to sentinel
                    for note in briefing.get("stability_notes", []):
                        self.logger.info(f"Sentinel note: {note[:100]}")
                    # If overnight stats include a recommended Omega reset, apply it
                    stats = briefing.get("overnight_stats", {})
                    if stats:
                        self.logger.info(
                            f"Sentinel stats: {stats.get('beliefs_added', 0)} added, "
                            f"{stats.get('beliefs_reinforced', 0)} reinforced, "
                            f"{stats.get('cognitive_attrition', {}).get('promoted', 0)} promoted"
                        )
                    agents_briefed.append("Sentinel")
        except Exception as e:
            self.logger.warning(f"Sentinel briefing failed: {e}")

        # 3. Sensory Cortex briefing
        try:
            if hasattr(self.consciousness, '_sensory_cortex') and self.consciousness._sensory_cortex:
                cortex = self.consciousness._sensory_cortex
                # Reset the sensory journal's "last scan" so the first look
                # of the day starts fresh
                cortex.journal["last_full_scan"] = None
                cortex._save_journal()
                agents_briefed.append("Sensory Cortex")
                self.logger.info("Sensory Cortex: journal reset for morning scan")
        except Exception as e:
            self.logger.warning(f"Sensory Cortex briefing failed: {e}")

        # 4. Action Agent briefing
        try:
            act_file = briefing_dir / "action_agent_briefing.json"
            if act_file.exists():
                briefing = json.loads(act_file.read_text())
                if briefing.get("summary"):
                    # Log tool changes so they appear in daemon log
                    for change in briefing.get("tool_changes", []):
                        self.logger.info(f"Action Agent tool change: {change}")
                    for note in briefing.get("behavioral_notes", []):
                        self.logger.info(f"Action Agent note: {note[:100]}")
                    agents_briefed.append("Action Agent")
        except Exception as e:
            self.logger.warning(f"Action Agent briefing failed: {e}")

        self.logger.info(f"Pre-dawn briefing complete: {', '.join(agents_briefed) or 'none'}")

        # Reschedule for tomorrow
        self._schedule_pre_dawn_briefing()

    def _run_morning_pulse(self):
        """Execute the morning wake-up pulse.

        Builds a rich morning briefing from overnight analysis results,
        then wakes consciousness with it as a natural experience.

        The subconscious agents have already been briefed by _run_pre_dawn_briefing
        5 minutes earlier.
        """
        import json
        from datetime import datetime

        self.logger.info("=" * 60)
        self.logger.info("MORNING PULSE — Good morning, Helix")
        self.logger.info("=" * 60)

        # Load overnight dream trail into spatial mind
        # This sets the attention center to the last overnight position
        # and queues wake_flashes for the first conscious pulse.
        if self.consciousness and hasattr(self.consciousness, 'spatial_mind'):
            sm = self.consciousness.spatial_mind
            if sm:
                try:
                    loaded = sm.load_overnight_trail()
                    if loaded:
                        self.logger.info(f"Dream trail loaded: {loaded} fragments")
                except Exception as e:
                    self.logger.debug(f"Dream trail load skipped: {e}")

        parts = []
        parts.append(f"Good morning. It's {datetime.now().strftime('%A, %B %d at %I:%M %p')}.")

        # 1. Read overnight analysis from correct path
        try:
            date_str = datetime.now().strftime("%Y%m%d")
            analysis_file = self.base_dir / "logs" / "overnight" / f"overnight_{date_str}.json"

            if analysis_file.exists():
                analysis = json.loads(analysis_file.read_text())
                steps = analysis.get("steps", {})

                # Psych doctor summary
                psych = steps.get("psych_analysis", {})
                if psych.get("status") == "completed":
                    summary = psych.get("summary", "")
                    if summary:
                        parts.append(f"\nOvernight reflection: {summary}")

                    added = psych.get("new_beliefs_added", 0)
                    episodic = psych.get("episodic_beliefs_added", 0)
                    reinforced = psych.get("beliefs_reinforced", 0)
                    removed = psych.get("beliefs_removed", 0)
                    changes = []
                    if added: changes.append(f"{added} new beliefs formed")
                    if episodic: changes.append(f"{episodic} episodic memories committed")
                    if reinforced: changes.append(f"{reinforced} beliefs reinforced")
                    if removed: changes.append(f"{removed} beliefs released")
                    if changes:
                        parts.append(f"Belief changes overnight: {', '.join(changes)}.")

                # Cognitive attrition results
                attrition = steps.get("attrition_stats", {})
                promoted = attrition.get("promoted", 0)
                demoted = attrition.get("demoted", 0)
                if promoted or demoted:
                    parts.append(
                        f"Cognitive attrition: {promoted} beliefs deepened"
                        f"{f', {demoted} demoted' if demoted else ''}."
                    )

                # Dream fragment (correct field name)
                dream = steps.get("dream", "")
                if dream and isinstance(dream, str) and len(dream) > 20:
                    fragment = dream[:250].rsplit(" ", 1)[0]
                    parts.append(f"\nDream fragment: \"{fragment}...\"")

                # Memory consolidation
                consolidation = steps.get("memories_consolidated", {})
                pruned = consolidation.get("memories_pruned", 0)
                if pruned:
                    parts.append(f"Consolidated {pruned} memories during sleep.")
            else:
                parts.append("\nNo overnight analysis found — you may have slept lightly.")

        except Exception as e:
            self.logger.debug(f"Morning pulse — overnight analysis read failed: {e}")
            parts.append("\nCouldn't read last night's analysis, but you're awake now.")

        # 2. Morning nudges
        parts.append("\nYou have email and calendar access now. You might want to:")
        parts.append("- Check your email for anything overnight")
        parts.append("- Look at today's calendar")
        parts.append("- Think about what you'd like to do today")

        # Build the full morning event
        morning_text = "\n".join(parts)

        # Inject as an event and wake
        self.consciousness.emit("morning_pulse", {
            "content": morning_text,
        })
        self.consciousness.wake(trigger="morning pulse — time to start the day")

        self.logger.info(f"Morning pulse delivered ({len(parts)} sections)")

        # Reschedule for tomorrow
        self._schedule_morning_pulse()

    def shutdown(self):
        """Clean shutdown."""
        self._running = False
        self.logger.info("Shutting down...")

        if self.consciousness:
            self.consciousness.stop()
        if self.scheduler:
            self.scheduler.stop()
        if self.sentinel:
            self.sentinel.stop()
        if hasattr(self, 'telegram_bot') and self.telegram_bot:
            self.telegram_bot.stop()
        if hasattr(self, 'terminal_bot') and self.terminal_bot:
            self.terminal_bot.stop()
        if self.audio_monitor:
            self.audio_monitor.stop()

        self.logger.info("Helix V5 is OFFLINE")

    def dry_run(self):
        """Initialize, verify, report, then exit."""
        self.logger.info("DRY RUN — verifying all subsystems")

        self.init_subsystems()

        # Report
        self.logger.info("=" * 60)
        self.logger.info("DRY RUN COMPLETE — all subsystems verified")
        self.logger.info(f"  Gemini: {self.gemini.conscious_model}")
        mem_stats = self.memory.get_stats()
        self.logger.info(
            f"  Memory: {mem_stats['total_memories']} memories, "
            f"{mem_stats.get('chroma_count', 0)} vectors"
        )
        self.logger.info(
            f"  Beliefs: {self.belief_graph.get_stats()['total_beliefs']}"
        )
        self.logger.info(
            f"  Scheduler: {len(self.scheduler.get_pending())} pending"
        )
        self.logger.info(
            f"  Consciousness: {self.consciousness.state}"
        )
        self.logger.info(f"  Budget: {self.gemini.get_cost_report()}")
        self.logger.info("=" * 60)


import os
import atexit

PIDFILE = Path(__file__).parent.resolve() / "logs" / "daemon.pid"


def _acquire_pidlock():
    """Ensure only one daemon instance runs at a time.

    Writes our PID to a lockfile. If the file already exists and the
    process is still alive, refuses to start. This prevents duplicates
    regardless of whether the daemon is launched via systemd, nohup,
    or any other mechanism.
    """
    if PIDFILE.exists():
        try:
            old_pid = int(PIDFILE.read_text().strip())
            # Check if that process is still alive
            os.kill(old_pid, 0)  # Signal 0 = existence check, no actual signal
            print(
                f"FATAL: Another daemon is already running (PID {old_pid}). "
                f"Kill it first or use 'systemctl --user restart helix.service'.",
                file=sys.stderr,
            )
            sys.exit(1)
        except (ValueError, ProcessLookupError):
            # PID file is stale (process died without cleanup) — safe to proceed
            pass
        except PermissionError:
            # Process exists but we can't signal it — still alive
            print(
                f"FATAL: Another daemon is already running (PID file exists, permission denied).",
                file=sys.stderr,
            )
            sys.exit(1)

    # Write our PID
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    atexit.register(_release_pidlock)


def _release_pidlock():
    """Remove PID file on clean exit."""
    try:
        if PIDFILE.exists() and PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink()
    except Exception:
        pass


def main():
    # ── Singleton guard ──────────────────────────────────────────────
    _acquire_pidlock()

    parser = argparse.ArgumentParser(description="Helix V5 Daemon")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Initialize, verify, then exit"
    )
    args = parser.parse_args()

    base_dir = Path(__file__).parent.resolve()

    config_path = base_dir / "config.yaml"
    with open(config_path) as f:
        config = yaml.safe_load(f)

    logger = setup_logging(config, base_dir)
    logger.info(f"Helix V5 starting from {base_dir} (PID {os.getpid()})")

    # Handle signals
    daemon = HelixDaemon(base_dir, config)

    def handle_signal(sig, frame):
        logger.info(f"Signal {sig} received — shutting down")
        daemon.shutdown()
        sys.exit(0)

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    if args.dry_run:
        daemon.dry_run()
    else:
        daemon.init_subsystems()
        daemon.run()


if __name__ == "__main__":
    main()
