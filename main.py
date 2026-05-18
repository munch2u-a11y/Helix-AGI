"""
Helix — Main Entry Point

Initializes the full cognitive architecture and runs the pulse loop:
  - Three-tier memory (short-term, long-term, core)
  - Categorized belief store (identity, people, capabilities, desires, knowledge)
  - Astrophysical physics engine
  - Active pre-conscious (short-term + core + beliefs + scratchpad)
  - Scratchpad (conscious notepad with reminders)
  - Continuous pulse-based consciousness loop (start_chat())
"""

import os
import time
import logging
import logging.handlers
import numpy as np

# ── Logging Setup ────────────────────────────────────────────────────
# All logger.info/debug calls across the codebase route here.
# Captures FC dispatch, pulse state, preconscious injection, etc.
_log_dir = os.path.join(os.path.dirname(__file__), "logs")
os.makedirs(_log_dir, exist_ok=True)

_file_handler = logging.handlers.RotatingFileHandler(
    os.path.join(_log_dir, "helix.log"),
    maxBytes=5_000_000,  # 5 MB per file
    backupCount=3,        # keep 3 rotated copies
    encoding="utf-8",
)
_file_handler.setFormatter(logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
))

# Root logger — captures everything
logging.basicConfig(
    level=logging.INFO,
    handlers=[_file_handler],
)


def _load_credentials():
    """Load API keys from ~/.config/helix/credentials.env into os.environ.

    Supports both python-dotenv (if installed) and manual parsing.
    Credentials loaded: HELIX_TELEGRAM_TOKEN, MOLTBOOK_API_KEY,
    GITHUB_TOKEN, GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.
    """
    cred_path = os.path.expanduser("~/.config/helix/credentials.env")
    if not os.path.exists(cred_path):
        print(f"  ⚠ No credentials file at {cred_path}")
        return

    # Try python-dotenv first
    try:
        from dotenv import load_dotenv
        load_dotenv(cred_path, override=False)
        print(f"  Credentials: loaded via dotenv")
        return
    except ImportError:
        pass

    # Manual parse — handle KEY="value" and KEY=value
    loaded = 0
    with open(cred_path, 'r') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value and key not in os.environ:
                    os.environ[key] = value
                    loaded += 1
    print(f"  Credentials: loaded {loaded} keys")


# Load credentials BEFORE any imports that use env vars
_load_credentials()


from memory.memory_manager import MemoryManager
from memory.belief_store import BeliefStore
from core.physics_engine import PhysicsEngine
from core.preconscious import Preconscious
from core.scratchpad import Scratchpad
from core.pulse_loop import PulseLoop
from llm.orchestrator import LLMOrchestrator
from llm.background_daemon import BackgroundDaemon
from llm.providers.base import detect_available_provider
from tools.tool_executor import ToolExecutor
from tools.channel_router import ChannelRouter
from comms.telegram_bot import HelixTelegramBot
from brain.stability_sentinel import StabilitySentinel


def on_thought(pulse_number: int, thought: str, events: list):
    """Callback for each pulse — prints internal monologue to console."""
    state_tag = "💬" if events else "💭"
    print(f"\n  {state_tag} [Pulse {pulse_number}] {thought}")


def on_delivery(recipient: str, message: str):
    """Callback for outbound messages — prints to console."""
    print(f"\n  📤 → {recipient}: {message}")


def setup_helix(data_dir: str = "data"):
    """Initialize the complete Helix cognitive architecture."""
    print("Initializing Helix Architecture...")

    # ── 1. Memory Systems ────────────────────────────────────────────

    memory_manager = MemoryManager(os.path.join(data_dir, "memory"))
    belief_store = BeliefStore(os.path.join(data_dir, "beliefs"))
    scratchpad = Scratchpad(os.path.join(data_dir, "scratchpad"))

    mem_stats = memory_manager.get_stats()
    belief_stats = belief_store.get_stats()
    print(f"  Memory: {mem_stats}")
    print(f"  Beliefs: {belief_stats}")
    print(f"  Scratchpad: {len(scratchpad.get_active_notes())} active notes")

    # ── 2. Physics Engine (8D spatial manifold) ────────────────────────
    spatial_dir = os.path.join(data_dir, "spatial")
    physics = PhysicsEngine(data_dir=spatial_dir)
    print(f"  Spatial: pulse={physics._pulse_count}, γ={physics._gamma:.2f}")

    # ── 2b. Stability Sentinel ───────────────────────────────────────
    from pathlib import Path
    sentinel = StabilitySentinel(
        base_dir=Path("."),
        memory=memory_manager,
        probe_interval=60,
    )
    print(f"  Sentinel: Ω={sentinel.omega:.3f}, severity={sentinel.get_severity()}")

    # ── 2c. Wire Sentinel → Spatial Mind ─────────────────────────────
    #    Connects the Sentinel to the real 8D manifold so _compute_lagrangian()
    #    uses actual Shannon entropy and KL divergence from the cognitive space
    #    instead of falling back to hardware health proxies.
    sentinel._spatial_mind = physics.spatial_mind

    # ── 2d. Bootstrap 8D Manifold ────────────────────────────────────
    #    Populate both cognitive spaces (belief field + memory field) from
    #    existing data so gravity queries are non-empty from the first pulse
    #    and the identity center x* is computed from real core beliefs.
    physics.bootstrap_from_stores(belief_store, memory_manager)
    print(f"  Spatial bootstrap: {physics.spatial_mind.belief_space.point_count} beliefs, "
          f"{physics.spatial_mind.memory_space.point_count} memories in 8D manifold")

    # ── 3. Tool Executor + Channel Router ───────────────────────────────
    channel_router = ChannelRouter(data_dir=data_dir)
    tool_executor = ToolExecutor(channel_router=channel_router)
    tool_executor.memory_manager = memory_manager
    tool_executor.scratchpad = scratchpad
    print(f"  Contacts: {len(channel_router.contacts)} known")
    print(f"  Tools: executor ready")

    # ── 3b. Telegram Bot ────────────────────────────────────────────
    telegram_bot = HelixTelegramBot()
    channel_router.set_telegram_bot(telegram_bot)
    print(f"  Telegram: {'enabled' if telegram_bot.enabled else 'disabled (no token)'}")

    # ── 4. Pre-Conscious + Scratchpad ────────────────────────────────
    tool_schemas_path = os.path.join(data_dir, "tool_schemas.json")
    preconscious = Preconscious(
        memory_manager=memory_manager,
        belief_store=belief_store,
        physics_engine=physics,
        scratchpad=scratchpad,
        channel_router=channel_router,
        tool_schemas_path=tool_schemas_path,
        sentinel=sentinel,
    )

    # ── 5. LLM Provider Detection ────────────────────────────────
    provider_config = detect_available_provider()
    if provider_config:
        print(f"  Provider: {provider_config.provider_type} ({provider_config.model})")
    else:
        print("  Provider: NONE — running without LLM")

    # ── 6. Pulse Loop ────────────────────────────────────────────
    journal_dir = "journals"
    pulse_loop = PulseLoop(
        memory_manager=memory_manager,
        belief_store=belief_store,
        physics_engine=physics,
        preconscious=preconscious,
        scratchpad=scratchpad,
        tool_executor=tool_executor,
        channel_router=channel_router,
        provider_config=provider_config,
        journal_dir=journal_dir,
        thought_callback=on_thought,
        delivery_callback=on_delivery,
        sentinel=sentinel,
    )

    # Wire telegram to pulse loop for inbound messages
    telegram_bot.set_pulse_loop(pulse_loop)

    # Wire tool executor to pulse loop for context reset tool
    tool_executor.set_pulse_loop(pulse_loop)

    # Wire sentinel to tool executor (for somatic echo on memory recall)
    tool_executor._sentinel = sentinel

    # ── Sentinel → PulseLoop event bridge ────────────────────────────
    #    Stability events (critical, warning, context_awareness) flow
    #    into the pulse loop's event queue so the agent can consciously
    #    perceive stability changes.
    sentinel.set_event_callback(pulse_loop.emit)

    # ── Context usage proxy for Sentinel ─────────────────────────────
    #    Lightweight adapter so the Sentinel can monitor context window
    #    saturation without holding a full PulseLoop reference.
    class _ContextProxy:
        def __init__(self, pl):
            self._pl = pl
        def context_usage_pct(self):
            if not self._pl._compressor:
                return 0.0
            max_tokens = self._pl._compressor.context_length
            current = self._pl._session_token_count
            return (current / max_tokens) * 100 if max_tokens > 0 else 0.0

    sentinel._consciousness = _ContextProxy(pulse_loop)

    # ── 6. Orchestrator (thin wrapper) ───────────────────────────────
    orchestrator = LLMOrchestrator(pulse_loop, memory_manager)

    # ── 7. Background Daemon (Dream Engine) ────────────────────────
    daemon = BackgroundDaemon(
        physics_engine=physics,

        belief_store=belief_store,
        memory_manager=memory_manager,
        data_dir=data_dir,
    )

    print("  Pulse loop: Ready")

    # Wire dream engine to pulse loop for rollover snapshots
    pulse_loop.set_dream_engine(daemon)

    # ── 8. Post-Pulse Hooks (Subconscious Background Tasks) ──────────
    from core.post_pulse_hooks import register_hook
    from core.workflow_detector import workflow_pattern_hook, set_dependencies

    set_dependencies(memory_manager, physics, sentinel=sentinel)
    register_hook(workflow_pattern_hook, name="workflow_detector")

    # Belief detector: scans internal monologue for belief realizations
    from core.belief_detector import (
        belief_detector_hook,
        set_dependencies as set_belief_deps,
    )
    set_belief_deps(belief_store, physics, sentinel=sentinel)
    register_hook(belief_detector_hook, name="belief_detector")

    # Engagement hook: tracks thought stagnation and tool activity → Ω
    from core.engagement_hook import (
        engagement_hook,
        set_dependencies as set_engagement_deps,
    )
    set_engagement_deps(sentinel, physics_engine=physics)
    register_hook(engagement_hook, name="engagement_monitor")

    print("  Post-pulse hooks: registered (workflow_detector, belief_detector, engagement_monitor)")

    return pulse_loop, orchestrator, daemon, memory_manager, belief_store, scratchpad, telegram_bot, sentinel


def main_loop():
    """Interactive loop — user messages are events in the pulse stream."""
    pulse_loop, orchestrator, daemon, memory, beliefs, scratchpad, telegram_bot, sentinel = setup_helix()

    print("\n--- Helix Pulse System ---")
    print("Commands: 'exit', 'stats', 'core', 'recent', 'beliefs', 'notes', 'dream'")
    print("Anything else is sent as a user message into the pulse stream.\n")

    # Start Telegram bot
    telegram_bot.start()

    # Start sentinel monitoring thread
    sentinel.start()

    # Start the pulse loop in background
    pulse_loop.wake("system_boot")
    pulse_loop.start()

    # Give it a moment to run the first pulse
    time.sleep(1)

    # Detect if running headless (no terminal attached)
    import sys
    headless = not sys.stdin.isatty()

    if headless:
        print("Running in headless/daemon mode (Telegram only).")
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            pass
    else:
        while True:
            try:
                user_input = input("\nYou: ")

                if not user_input.strip():
                    continue
                elif user_input.lower() == "exit":
                    break
                elif user_input.lower() == "stats":
                    status = pulse_loop.get_status()
                    mem_stats = memory.get_stats()
                    print(f"[Pulse] {status}")
                    print(f"[Memory] {mem_stats}")
                    print(f"[Beliefs] {beliefs.get_stats()}")
                    continue
                elif user_input.lower() == "core":
                    core_mems = memory.get_core_memories(limit=10)
                    if core_mems:
                        print("[Core Memories]")
                        for m in core_mems:
                            print(f"  [{m['created_at']}] (x{m['access_count']}) {m['content'][:100]}")
                    else:
                        print("[Core] None yet — promotes after 2+ accesses or importance >= 0.7")
                    continue
                elif user_input.lower() == "recent":
                    recent = memory.get_recent(limit=8)
                    if recent:
                        print("[Recent Short-Term]")
                        for m in recent:
                            print(f"  [{m['created_at']}] {m['content'][:100]}")
                    else:
                        print("[Recent] Empty.")
                    continue
                elif user_input.lower() == "beliefs":
                    from memory.belief_store import BELIEF_CATEGORIES
                    for cat in BELIEF_CATEGORIES:
                        cat_beliefs = beliefs.get_category(cat, limit=5)
                        if cat_beliefs:
                            print(f"[{cat}]")
                            for b in cat_beliefs:
                                print(f"  mass={b['mass']:.1f} | {b['content'][:80]}")
                        else:
                            print(f"[{cat}] (empty)")
                    continue
                elif user_input.lower() == "notes":
                    active = scratchpad.get_active_notes()
                    if active:
                        print("[Scratchpad]")
                        for n in active:
                            due = f" (due: {n['due_at']})" if n.get('due_at') else ""
                            print(f"  [{n['id']}] {n['content'][:80]}{due}")
                    else:
                        print("[Scratchpad] Empty.")
                    continue
                elif user_input.lower() == "dream":
                    print("[Dream Engine] Starting belief crystallization cycle...")
                    print("  (This may take several minutes with local LLM synthesis)")
                    try:
                        results = daemon.run_dream_cycle()
                        status = results.get('status', 'unknown')
                        total = results.get('total_beliefs_created', 0)
                        passes = len(results.get('passes', []))
                        print(f"[Dream Engine] {status}: {total} beliefs across {passes} passes")
                        for p in results.get('passes', []):
                            print(f"  Pass {p['pass']}: {p['clusters_found']} clusters → {p['beliefs_created']} beliefs")
                    except Exception as e:
                        print(f"[Dream Engine] Error: {e}")
                    continue
                else:
                    # Inject as user message event
                    orchestrator.send_user_message(user_input, sender="<name>")

                # Wait briefly for the pulse to process
                time.sleep(0.5)

            except KeyboardInterrupt:
                break

    pulse_loop.stop()
    print("\nAgent offline.")


if __name__ == "__main__":
    main_loop()
