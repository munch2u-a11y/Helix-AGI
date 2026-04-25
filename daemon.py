"""
Helix V6 — Live Daemon

Full consciousness daemon with all integrations:
  - Telegram bot for communication
  - Scheduler for timed tasks
  - PulseRouter for message routing
  - Tool system (provider-agnostic via tool_schema.py)
  - Librarian with remember_v6 (zero-LLM recall)
  - Stability Sentinel for Lagrangian state
  - 8D Cognitive Manifold
  - Overnight processing + morning pulse
  - Sensory Cortex (camera/audio)

Usage:
    python daemon.py           # Normal start
    python daemon.py --dry-run # Initialize, verify, exit
    python daemon.py --scaffold # Dead scaffold for test scripts
"""

import os
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


# ── V6 Live Daemon ──────────────────────────────────────────────────

class HelixDaemon:
    """Helix V6 event-driven orchestrator.

    Initializes all subsystems, then enters event-driven mode:
    Telegram polling + scheduler checking run continuously.
    Consciousness wakes on demand and naps after 5 idle pulses.
    """

    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).parent.resolve()
        self.config = yaml.safe_load((self.base_dir / "config.yaml").read_text())
        self.logger = setup_logging(self.config, self.base_dir)

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
        self.sensory_cortex = None
        self.unconscious = None
        self.telegram_bot = None

        # V6 additions
        self.cognitive_space = None
        self.spatial_mind = None
        self.manifold = None
        self.manifold_projector = None
        self.keeper = None
        self.interaction_engine = None

        self._running = False

    def init_subsystems(self):
        """Initialize all subsystems in dependency order."""
        self.logger.info("=" * 60)
        self.logger.info("HELIX V6 — INITIALIZING")
        self.logger.info("=" * 60)

        step = 0

        # ── 1. Gemini Client ────────────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Gemini client...")
        from gemini_client import GeminiClient
        self.gemini = GeminiClient(self.config, self.base_dir)
        self.logger.info(
            f"Gemini ready (conscious={self.gemini.conscious_model}, "
            f"default={self.gemini.default_model})"
        )

        # ── 2. Memory ───────────────────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Memory system...")
        from brain.memory import Memory
        self.memory = Memory(self.base_dir, self.config)
        stats = self.memory.get_stats()
        self.logger.info(
            f"Memory ready: {stats['total_memories']} memories, "
            f"{stats.get('chroma_count', 0)} vectors"
        )

        # ── 3. Belief Graph ─────────────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Belief graph...")
        from brain.belief_graph import BeliefGraph
        self.belief_graph = BeliefGraph(self.base_dir / "brain" / "belief_graph.json")
        bg_stats = self.belief_graph.get_stats()
        self.logger.info(
            f"Belief graph ready: {bg_stats['total_beliefs']} beliefs "
            f"(core={bg_stats.get('core', 0)}, deep={bg_stats.get('deep', 0)})"
        )

        # ── 3b. Cognitive Manifold (8D Space) ───────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Cognitive manifold + spatial mind...")
        try:
            from brain.manifold.projector import ManifoldProjector
            from brain.manifold.manifold import CognitiveManifold
            manifold_dir = self.base_dir / "brain" / "manifold"
            self.manifold_projector = ManifoldProjector(manifold_dir)
            self.manifold = CognitiveManifold()
            beliefs = self.belief_graph.get_all_beliefs()
            memories = self.memory.get_all_with_positions()
            self.manifold.rebuild_index(beliefs, memories)
            self.logger.info(f"Manifold ready: {len(self.manifold.nodes)} nodes")
        except Exception as e:
            self.manifold = None
            self.manifold_projector = None
            self.logger.warning(f"Manifold init failed: {e}")

        # V6 SpatialMind
        try:
            from brain.spatial_mind import SpatialMind
            self.spatial_mind = SpatialMind(base_dir=self.base_dir)
            self.spatial_mind.bootstrap(
                belief_graph=self.belief_graph,
                memory=self.memory,
            )
            self.cognitive_space = self.spatial_mind.belief_space
            self.logger.info(
                f"Spatial mind: {self.cognitive_space.point_count} points"
            )
        except Exception as e:
            self.logger.warning(f"SpatialMind init failed: {e}")

        # ── 4. Librarian ────────────────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Librarian...")
        from brain.librarian import Librarian
        self.librarian = Librarian(
            memory=self.memory,
            belief_graph=self.belief_graph,
            gemini_client=self.gemini,
            base_dir=self.base_dir,
        )
        if self.manifold:
            self.librarian.set_manifold(self.manifold, self.manifold_projector)
        self.logger.info("Librarian ready")

        # ── 5. Stability Sentinel ───────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Stability Sentinel...")
        from brain.stability_sentinel import StabilitySentinel
        self.sentinel = StabilitySentinel(
            base_dir=self.base_dir,
            memory=self.memory,
            gemini_client=self.gemini,
        )
        # V6: Wire spatial_mind for real H(q), D_KL, T
        if self.spatial_mind:
            self.sentinel._spatial_mind = self.spatial_mind
        snapshot = self.sentinel.get_lagrangian_snapshot()
        self.logger.info(
            f"Sentinel ready: Ω={snapshot.get('omega', 0):.3f}, "
            f"H={snapshot.get('H', 0):.3f}, T={snapshot.get('T', 0):.3f}"
        )

        # ── 6. Consciousness Loop ──────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Consciousness loop...")
        from brain.consciousness import ConsciousnessLoop
        consciousness_config = self.config.get("consciousness", {})
        consciousness_config["_gemini_config"] = self.config.get("gemini", {})
        consciousness_config["_anthropic_config"] = self.config.get("anthropic", {})
        # V6: Anthropic is the conscious provider
        consciousness_config["conscious_provider"] = "anthropic"
        self.consciousness = ConsciousnessLoop(
            gemini_client=self.gemini,
            belief_graph=self.belief_graph,
            memory=self.memory,
            base_dir=self.base_dir,
            config=consciousness_config,
            sentinel=self.sentinel,
        )
        self.consciousness._librarian = self.librarian
        if self.spatial_mind:
            self.consciousness._spatial_mind = self.spatial_mind
        if self.manifold:
            if hasattr(self.consciousness, 'keeper') and self.consciousness.keeper:
                self.consciousness.keeper.set_manifold(
                    self.manifold, self.manifold_projector
                )
        self.logger.info("Consciousness loop ready")

        # ── 6b. V6 Physics Wiring ──────────────────────────────────
        # Keeper with precipitation
        from brain.keeper import BeliefKeeper, BeliefPrecipitation
        self.keeper = self.consciousness.keeper  # Already created in consciousness init
        if self.cognitive_space:
            self.keeper.precipitation = BeliefPrecipitation(
                cognitive_space=self.cognitive_space,
                belief_graph=self.belief_graph,
                gemini_client=self.gemini,
            )
        # Interaction engine
        if self.cognitive_space:
            from brain.cognitive_space import InteractionEngine
            self.interaction_engine = InteractionEngine(
                cognitive_space=self.cognitive_space,
                sentinel=self.sentinel,
            )
            self.consciousness._interaction_engine = self.interaction_engine

        # ── 6c. Sensory Cortex ──────────────────────────────────────
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

        # ── 7. Scheduler ────────────────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Scheduler...")
        from brain.scheduler import Scheduler
        self.scheduler = Scheduler(
            base_dir=self.base_dir,
            config=self.config.get("scheduler", {}),
            wake_callback=self._on_scheduled_task,
        )
        self.logger.info(
            f"Scheduler ready ({len(self.scheduler.get_pending())} pending tasks)"
        )

        # ── 7b. Web Search ──────────────────────────────────────────
        try:
            from tools.web_search import WebSearch
            self.web_search = WebSearch(config=self.config)
            self.logger.info("Web Search ready")
        except Exception as e:
            self.web_search = None
            self.logger.warning(f"Web Search init failed: {e}")

        # ── 8. PulseRouter + Action Agent + Tools ───────────────────
        step += 1
        self.logger.info(f"[{step}/12] PulseRouter + tools...")
        from brain.pulse_router import PulseRouter
        self.pulse_router = PulseRouter(
            consciousness=self.consciousness,
            memory=self.memory,
            sentinel=self.sentinel,
            scheduler=self.scheduler,
            librarian=self.librarian,
        )
        self.consciousness._pulse_router = self.pulse_router

        # Wire action agent (for tool execution)
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
            self.logger.info("Action Agent + ToolRunner wired")
        except Exception as e:
            self.logger.warning(f"Action Agent init skipped: {e}")

        # Deep thought engine
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

        # Imagination engine
        try:
            if self.spatial_mind:
                from brain.imagination import ImaginationEngine
                self.imagination = ImaginationEngine(self.spatial_mind)
                self.logger.info("Imagination Engine ready")
        except Exception as e:
            self.logger.warning(f"Imagination Engine init skipped: {e}")

        self.logger.info("PulseRouter ready")

        # ── 8b. Unconscious System ──────────────────────────────────
        try:
            from brain.unconscious import UnconsciousSystem
            self.unconscious = UnconsciousSystem(
                memory=self.memory,
                belief_graph=self.belief_graph,
                gemini_client=self.gemini,
                base_dir=self.base_dir,
                spatial_mind=self.spatial_mind,
            )
            keeper = getattr(self.consciousness, 'keeper', None)
            if keeper and self.librarian:
                self.unconscious.set_agents(keeper=keeper, librarian=self.librarian)
            self._schedule_overnight()
            self._schedule_pre_dawn_briefing()
            self._schedule_morning_pulse()
            self.logger.info("Unconscious system ready (overnight scheduled)")
        except Exception as e:
            self.unconscious = None
            self.logger.warning(f"Unconscious system init skipped: {e}")

        # ── 9. Telegram Bot ─────────────────────────────────────────
        step += 1
        self.logger.info(f"[{step}/12] Telegram Bot...")
        if self.config.get("telegram", {}).get("enabled", False):
            try:
                from comms.telegram_bot import HelixTelegramBot
                self.telegram_bot = HelixTelegramBot(config=self.config)
                self.telegram_bot.set_pulse_router(self.pulse_router)
                self.pulse_router.register_delivery_channel(
                    "telegram", self.telegram_bot.send_message
                )
                self.logger.info("Telegram bot ready")
            except Exception as e:
                self.logger.error(f"Telegram bot init failed: {e}")
                self.telegram_bot = None
        else:
            self.logger.info("Telegram disabled in config")

        # ── 10. Audio Monitor ───────────────────────────────────────
        audio_cfg = self.config.get("audio", {})
        if audio_cfg.get("enabled", False):
            step += 1
            self.logger.info(f"[{step}/12] Audio Monitor...")
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

        # ── V6 Physics Summary ──────────────────────────────────────
        snapshot = self.sentinel.get_lagrangian_snapshot()
        self.logger.info(
            f"V6 Physics: Ω={snapshot.get('omega', 0):.3f}, "
            f"H={snapshot.get('H', 0):.3f}, "
            f"D_KL={snapshot.get('D_KL', 0):.3f}, "
            f"T={snapshot.get('T', 0):.3f}"
        )

        from brain.tool_schema import get_tool_count
        provider = self.config.get("conscious_provider", "gemini")
        self.logger.info(
            f"Tool system: {get_tool_count()} tools "
            f"(provider: {provider})"
        )

        self.logger.info("=" * 60)
        self.logger.info("ALL SUBSYSTEMS INITIALIZED")
        self.logger.info("=" * 60)

    def run(self):
        """Run the daemon — enters event-driven mode."""
        self._running = True

        # Start background services
        self.sentinel.start()
        self.consciousness.start()
        self.scheduler.start()

        if self.telegram_bot:
            self.telegram_bot.start()
        if self.audio_monitor:
            self.audio_monitor.start()

        self.logger.info(
            "Helix V6 is ONLINE — DORMANT, waiting for messages"
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
            threading.Thread(
                target=self._run_overnight,
                daemon=True,
                name="overnight-cycle",
            ).start()
        elif "PRE_DAWN_BRIEFING" in trigger:
            threading.Thread(
                target=self._run_pre_dawn_briefing,
                daemon=True,
                name="pre-dawn-briefing",
            ).start()
        elif "MORNING_PULSE" in trigger:
            threading.Thread(
                target=self._run_morning_pulse,
                daemon=True,
                name="morning-pulse",
            ).start()
        else:
            self.consciousness.wake(trigger)

    # ── Overnight cycle ──────────────────────────────────────────────

    def _schedule_overnight(self):
        """Schedule the overnight cycle to run at ~1:05 AM."""
        from datetime import datetime, timedelta
        now = datetime.now()
        target = now.replace(hour=1, minute=5, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        minutes_until = int((target - now).total_seconds() / 60)
        desc = "OVERNIGHT_CYCLE: Belief maintenance, memory consolidation, dream synthesis"
        pending = self.scheduler.get_pending()
        if any(desc in t.get("description", "") for t in pending):
            return
        self.scheduler.schedule(minutes=minutes_until, description=desc)
        self.logger.info(f"Overnight cycle scheduled for {target.strftime('%H:%M')}")

    def _run_overnight(self):
        """Execute the overnight processing pipeline."""
        if not self.unconscious:
            return
        self.logger.info("OVERNIGHT CYCLE STARTING")
        try:
            results = self.unconscious.run_overnight_cycle()
            self.logger.info(f"Overnight cycle complete: {results}")
        except Exception as e:
            self.logger.error(f"Overnight cycle failed: {e}")
        self._schedule_overnight()

    # ── Morning pulse ────────────────────────────────────────────────

    def _schedule_pre_dawn_briefing(self):
        """Schedule pre-dawn briefing for 5:55 AM."""
        from datetime import datetime, timedelta
        now = datetime.now()
        target = now.replace(hour=5, minute=55, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        minutes_until = int((target - now).total_seconds() / 60)
        desc = "PRE_DAWN_BRIEFING: Feed overnight analysis to subconscious agents"
        pending = self.scheduler.get_pending()
        if any(desc in t.get("description", "") for t in pending):
            return
        self.scheduler.schedule(minutes=minutes_until, description=desc)

    def _schedule_morning_pulse(self):
        """Schedule the morning wake pulse for 6:00 AM."""
        from datetime import datetime, timedelta
        now = datetime.now()
        target = now.replace(hour=6, minute=0, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        minutes_until = int((target - now).total_seconds() / 60)
        desc = "MORNING_PULSE: Good morning — review dreams, check calendar & email, plan the day"
        pending = self.scheduler.get_pending()
        if any(desc in t.get("description", "") for t in pending):
            return
        self.scheduler.schedule(minutes=minutes_until, description=desc)

    def _run_pre_dawn_briefing(self):
        """Feed overnight briefings to subconscious agents."""
        import json
        self.logger.info("PRE-DAWN BRIEFING — Subconscious agents waking")
        briefing_dir = self.base_dir / "brain" / "briefings"
        agents_briefed = []

        # Librarian
        try:
            lib_file = briefing_dir / "librarian_briefing.json"
            if lib_file.exists() and self.librarian:
                briefing = json.loads(lib_file.read_text())
                if briefing.get("summary"):
                    self.librarian.set_overnight_briefing(briefing)
                    agents_briefed.append("Librarian")
        except Exception as e:
            self.logger.warning(f"Librarian briefing failed: {e}")

        # Sentinel
        try:
            sent_file = briefing_dir / "sentinel_briefing.json"
            if sent_file.exists() and self.sentinel:
                briefing = json.loads(sent_file.read_text())
                if briefing.get("summary"):
                    agents_briefed.append("Sentinel")
        except Exception as e:
            self.logger.warning(f"Sentinel briefing failed: {e}")

        # Sensory Cortex
        try:
            if self.sensory_cortex:
                self.sensory_cortex.journal["last_full_scan"] = None
                self.sensory_cortex._save_journal()
                agents_briefed.append("Sensory Cortex")
        except Exception as e:
            self.logger.warning(f"Sensory Cortex briefing failed: {e}")

        self.logger.info(f"Pre-dawn briefing complete: {', '.join(agents_briefed) or 'none'}")
        self._schedule_pre_dawn_briefing()

    def _run_morning_pulse(self):
        """Execute the morning wake-up pulse."""
        import json
        from datetime import datetime

        self.logger.info("MORNING PULSE — Good morning, Helix")

        # Load dream trail into spatial mind
        if self.consciousness and self.spatial_mind:
            try:
                loaded = self.spatial_mind.load_overnight_trail()
                if loaded:
                    self.logger.info(f"Dream trail loaded: {loaded} fragments")
            except Exception as e:
                self.logger.debug(f"Dream trail load skipped: {e}")

        parts = [f"Good morning. It's {datetime.now().strftime('%A, %B %d at %I:%M %p')}."]

        # Read overnight analysis
        try:
            date_str = datetime.now().strftime("%Y%m%d")
            analysis_file = self.base_dir / "logs" / "overnight" / f"overnight_{date_str}.json"
            if analysis_file.exists():
                analysis = json.loads(analysis_file.read_text())
                steps = analysis.get("steps", {})
                psych = steps.get("psych_analysis", {})
                if psych.get("status") == "completed":
                    summary = psych.get("summary", "")
                    if summary:
                        parts.append(f"\nOvernight reflection: {summary}")
                dream = steps.get("dream", "")
                if dream and isinstance(dream, str) and len(dream) > 20:
                    fragment = dream[:250].rsplit(" ", 1)[0]
                    parts.append(f'\nDream fragment: "{fragment}..."')
            else:
                parts.append("\nNo overnight analysis found.")
        except Exception as e:
            self.logger.debug(f"Morning analysis read failed: {e}")

        parts.append("\nYou have email and calendar access now.")
        morning_text = "\n".join(parts)

        self.consciousness.emit("morning_pulse", {"content": morning_text})
        self.consciousness.wake(trigger="morning pulse — time to start the day")
        self.logger.info(f"Morning pulse delivered ({len(parts)} sections)")
        self._schedule_morning_pulse()

    # ── Shutdown ─────────────────────────────────────────────────────

    def shutdown(self):
        """Clean shutdown (idempotent — safe to call twice)."""
        if not self._running:
            return  # Already shut down
        self._running = False
        self.logger.info("Shutting down...")

        if self.consciousness:
            self.consciousness.stop()
        if self.scheduler:
            self.scheduler.stop()
        if self.sentinel:
            self.sentinel.stop()
        if self.telegram_bot:
            self.telegram_bot.stop()
        if self.audio_monitor:
            self.audio_monitor.stop()

        self.logger.info("Helix V6 is OFFLINE")

    def dry_run(self):
        """Initialize, verify, report, then exit."""
        self.logger.info("DRY RUN — verifying all subsystems")
        self.init_subsystems()

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
        self.logger.info(f"  Sentinel: Ω={self.sentinel.omega:.3f}")
        self.logger.info(f"  Budget: {self.gemini.get_cost_report()}")
        self.logger.info("=" * 60)


# ── V6 Test Scaffold (backward compat) ──────────────────────────────

class HelixV6Scaffold:
    """Dead scaffold — initializes subsystems for testing only.

    NO threads. NO bots. NO services. NO auto-start.
    Just loads data structures so test scripts can work with them.
    """

    def __init__(self, base_dir: Path = None):
        self.base_dir = base_dir or Path(__file__).parent.resolve()
        self.config = yaml.safe_load((self.base_dir / "config.yaml").read_text())
        self.logger = logging.getLogger("helix.v6.scaffold")

        self.gemini = None
        self.memory = None
        self.belief_graph = None
        self.librarian = None
        self.sentinel = None
        self.cognitive_space = None
        self.spatial_mind = None
        self.manifold = None
        self.manifold_projector = None
        self.keeper = None

    def init_subsystems(self):
        """Initialize data subsystems only — no threads, no services."""
        # 1. Gemini
        from gemini_client import GeminiClient
        self.gemini = GeminiClient(self.config, self.base_dir)

        # 2. Memory
        from brain.memory import Memory
        self.memory = Memory(self.base_dir, self.config)

        # 3. Belief Graph
        from brain.belief_graph import BeliefGraph
        self.belief_graph = BeliefGraph(self.base_dir / "brain" / "belief_graph.json")

        # 4. Spatial Mind
        from brain.spatial_mind import SpatialMind
        self.spatial_mind = SpatialMind(base_dir=self.base_dir)
        self.spatial_mind.bootstrap(
            belief_graph=self.belief_graph,
            memory=self.memory,
        )
        self.cognitive_space = self.spatial_mind.belief_space

        # 5. Manifold
        try:
            from brain.manifold.projector import ManifoldProjector
            from brain.manifold.manifold import CognitiveManifold
            manifold_dir = self.base_dir / "brain" / "manifold"
            self.manifold_projector = ManifoldProjector(manifold_dir)
            self.manifold = CognitiveManifold()
            beliefs = self.belief_graph.get_all_beliefs()
            memories = self.memory.get_all_with_positions()
            self.manifold.rebuild_index(beliefs, memories)
        except Exception as e:
            self.logger.warning(f"Manifold init failed: {e}")

        # 6. Sentinel (passive — no background thread)
        from brain.stability_sentinel import StabilitySentinel
        self.sentinel = StabilitySentinel(
            base_dir=self.base_dir,
            memory=self.memory,
            gemini_client=self.gemini,
        )
        if self.spatial_mind:
            self.sentinel._spatial_mind = self.spatial_mind

        # 7. Librarian
        from brain.librarian import Librarian
        self.librarian = Librarian(
            memory=self.memory,
            belief_graph=self.belief_graph,
            gemini_client=self.gemini,
            base_dir=self.base_dir,
        )

        # 8. Keeper with precipitation
        from brain.keeper import BeliefKeeper, BeliefPrecipitation
        self.keeper = BeliefKeeper(
            self.base_dir,
            belief_graph=self.belief_graph,
            gemini_client=self.gemini.client if hasattr(self.gemini, 'client') else None,
            gemini_wrapper=self.gemini,
        )
        if self.cognitive_space:
            self.keeper.precipitation = BeliefPrecipitation(
                cognitive_space=self.cognitive_space,
                belief_graph=self.belief_graph,
                gemini_client=self.gemini,
            )


# ── PID locking ──────────────────────────────────────────────────────

import atexit

PIDFILE = Path(__file__).parent.resolve() / "logs" / "daemon.pid"


def _acquire_pidlock():
    """Ensure only one daemon instance runs at a time."""
    if PIDFILE.exists():
        try:
            old_pid = int(PIDFILE.read_text().strip())
            os.kill(old_pid, 0)
            print(
                f"FATAL: Another daemon is already running (PID {old_pid}).",
                file=sys.stderr,
            )
            sys.exit(1)
        except (ProcessLookupError, ValueError):
            pass  # stale PID
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))
    atexit.register(lambda: PIDFILE.unlink(missing_ok=True))


# ── Entry point ──────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Helix V6 Daemon")
    parser.add_argument("--dry-run", action="store_true", help="Init, verify, exit")
    parser.add_argument("--scaffold", action="store_true", help="Dead scaffold mode")
    args = parser.parse_args()

    if args.scaffold:
        print("V6 Test Scaffold — use: from daemon import HelixV6Scaffold")
        sys.exit(0)

    _acquire_pidlock()

    base_dir = Path(__file__).parent.resolve()
    daemon = HelixDaemon(base_dir)

    if args.dry_run:
        daemon.dry_run()
    else:
        daemon.init_subsystems()
        daemon.run()
