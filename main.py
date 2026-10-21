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
import threading

_shutdown_requested = threading.Event()

# Select dependency source and neural device before imports can initialize torch.
import json
from pathlib import Path
from core.mindscape_config import activate as activate_mindscape, configuration_path
_config_path = configuration_path()
_startup_config = json.loads(_config_path.read_text()) if _config_path.exists() else {}
_mindscape_settings = activate_mindscape(_startup_config)

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

# Silence noisy libraries (e.g. Telegram polling httpx requests)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


def _load_credentials():
    """Load API keys from ~/.config/helix/credentials.env into os.environ.

    Supports both python-dotenv (if installed) and manual parsing.
    Credentials loaded: HELIX_TELEGRAM_TOKEN, MOLTBOOK_API_KEY,
    GITHUB_TOKEN, GEMINI_API_KEY, ANTHROPIC_API_KEY, etc.
    """
    cred_path = os.path.expanduser("~/.config/helix/credentials.env")
    if not os.path.exists(cred_path) and _mindscape_settings is not None:
        # The full local composition needs no cloud/channel credentials.
        return
    if not os.path.exists(cred_path):
        print("\n" + "="*70)
        print("  ⚠  HELIX AGI IS NOT CONFIGURED YET!")
        print("="*70)
        print("  Please run the Setup Wizard first to configure credentials and seed beliefs:")
        print("    - GUI Wizard (Recommended):  ./install.sh")
        print("    - CLI Setup:                 python setup.py")
        print("="*70 + "\n")
        import sys
        sys.exit(1)

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
from core.dual_pulse_loop import DualPulseLoop
from llm.orchestrator import LLMOrchestrator
from llm.background_daemon import BackgroundDaemon
from llm.providers.base import detect_available_provider, ProviderConfig
from tools.tool_executor import ToolExecutor
from tools.channel_router import ChannelRouter
from comms.telegram_bot import HelixTelegramBot
from comms.discord_bot import HelixDiscordBot
from comms.slack_bot import HelixSlackBot
from comms.whatsapp_bot import HelixWhatsAppBot
from comms.webhook_channel import HelixWebhookChannel
from brain.stability_sentinel import StabilitySentinel
from brain.sensory_cortex import SensoryCortex


def on_thought(pulse_number: int, thought: str, events: list):
    """Callback for each pulse — prints internal monologue to console."""
    state_tag = "💬" if events else "💭"
    print(f"\n  {state_tag} [Pulse {pulse_number}] {thought}")
    import logging
    logging.getLogger("helix.core.pulse_loop").info(f"[thought] [Pulse {pulse_number}] {thought}")


def on_context(pulse_number: int, context_text: str):
    """Callback for each pulse — prints exact context window fed to the agent."""
    print(f"\n  📖 [Context Window — Pulse {pulse_number}]")
    print(f"  {'─' * 60}")
    for line in context_text.strip().splitlines():
        print(f"    {line}")
    print(f"  {'─' * 60}")
    import logging
    logging.getLogger("helix.core.pulse_loop").debug(f"[context] [Pulse {pulse_number}]\n{context_text}")


def on_delivery(recipient: str, message: str):
    """Callback for outbound messages — prints to console."""
    print(f"\n  📤 → {recipient}: {message}")


def resolve_main_provider(mindscape_settings: dict | None, cfg: dict | None = None) -> ProviderConfig | None:
    """Resolve the conscious LLM ProviderConfig across all three modes:
    1. Full RWKV Experimental: local_provider in ("rwkv", "bicameral_rwkv")
    2. Local Ollama: local_provider == "ollama"
    3. Hosted API: fallback via detect_available_provider()
    """
    cfg = cfg or {}
    if mindscape_settings is not None:
        local_prov = mindscape_settings.get("local_provider", "ollama")
        if local_prov in ("rwkv", "bicameral_rwkv"):
            from core.model_paths import default_rwkv_model
            fallback_rwkv = default_rwkv_model(Path(__file__).resolve().parent)
            rwkv_path = (
                os.environ.get("RWKV_MODEL_PATH")
                or mindscape_settings.get("mindscape", {}).get("rwkv_model")
                or mindscape_settings.get("local_model")
                or fallback_rwkv
            )
            return ProviderConfig(
                provider_type="rwkv",
                model=str(rwkv_path),
                context_window=int(mindscape_settings.get("local_context_window", 8192)),
                temperature=0.7,
                max_output_tokens=int(mindscape_settings["max_output_tokens"]) if mindscape_settings.get("max_output_tokens") is not None else None,
            )
        else:
            context = int(mindscape_settings.get("local_context_window", 32768))
            model = mindscape_settings.get("local_model", "granite4.1:8b")
            return ProviderConfig(
                provider_type="ollama",
                model=model,
                context_window=context,
                options={"num_ctx": context, "url": cfg.get("ollama_url", "http://localhost:11434")},
            )
    return detect_available_provider()


def setup_helix(data_dir: str = "data", *, start_sensors: bool = True, show_context: bool = False):
    """Initialize the complete Helix cognitive architecture."""
    print("Initializing Helix Architecture...")
    local_models = None
    if _mindscape_settings is not None:
        from core.mindscape_config import local_model_receipt
        local_models = local_model_receipt(_mindscape_settings)

    # Load configuration
    import json as _json
    global _cfg
    _cfg = {}
    try:
        with open(_config_path, "r") as _f:
            _cfg = _json.load(_f)
    except Exception:
        pass

    # Set vision provider environment variables before SensoryCortex is instantiated
    pulse_mode = _cfg.get("pulse_mode", "standard")
    local_type = _cfg.get("local_provider", "ollama").lower()
    vision_provider = _cfg.get("vision_provider", "local").lower()
    if pulse_mode == "dual" and local_type == "ollama":
        vision_provider = "gemini"
    vision_model = _cfg.get("vision_model", "gemini-2.5-flash").strip()

    os.environ["HELIX_VISION_PROVIDER"] = vision_provider
    os.environ["HELIX_VISION_MODEL"] = vision_model

    # ── 1. Memory Systems ────────────────────────────────────────────

    memory_manager = MemoryManager(os.path.join(data_dir, "memory"))
    belief_store = BeliefStore(os.path.join(data_dir, "beliefs"))
    scratchpad = Scratchpad(os.path.join(data_dir, "scratchpad"))

    mem_stats = memory_manager.get_stats()
    belief_stats = belief_store.get_stats()
    if belief_stats.get("premises", 0) == 0:
        print("  Belief store empty — auto-seeding default identity premises...")
        from bootstrap.seed_builder import BootstrapContext, write_seed_data
        agent_name = _cfg.get("agent_name", "Helix")
        creator_name = _cfg.get("creator_name", "User")
        archetype = _cfg.get("agent_archetype", "curious")
        ctx = BootstrapContext(
            agent_name=agent_name,
            creator_name=creator_name,
            profile="standard",
            personality=archetype if archetype in {"curious", "friendly", "safe", "professional"} else "curious",
            wake_time="08:00",
            sleep_time="23:00",
            channels=["dashboard"],
        )
        write_seed_data(data_dir, ctx, overwrite=False)
        belief_stats = belief_store.get_stats()
        print(f"  Beliefs (auto-seeded): {belief_stats}")
    else:
        print(f"  Beliefs: {belief_stats}")
    print(f"  Memory: {mem_stats}")
    print(f"  Scratchpad: {len(scratchpad.get_active_notes())} active notes")

    # ── 2. Physics Engine (stable 8D manifold + 1024D semantic index) ──
    spatial_dir = os.path.join(data_dir, "spatial")
    physics = PhysicsEngine(data_dir=spatial_dir)
    memory_manager.set_physics(physics)
    print(f"  Spatial: pulse={physics._pulse_count}, γ={physics._gamma:.2f}")
    print(f"  SemanticIndex: {physics.semantic_index.count} vectors ({physics.semantic_index.get_stats()['search_strategy']})")

    # ── 2b. Stability Sentinel ───────────────────────────────────────
    from pathlib import Path
    sentinel = StabilitySentinel(
        base_dir=Path(data_dir),
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

    # Tool learning: failure capture + lesson verification loop, and
    # learned notes compiled into tool descriptions by the nightly Curator
    from core.tool_lesson_tracker import set_dependencies as set_lesson_deps
    set_lesson_deps(belief_store, physics_engine=physics)
    try:
        from tools.tool_registry import registry as _registry
        n_notes = _registry.load_learned_notes(
            os.path.join(data_dir, "tool_learned_notes.json")
        )
        if n_notes:
            print(f"  Tool notes: {n_notes} tools carry learned notes")
    except Exception as e:
        print(f"  Tool notes: load failed ({e})")
    
    # Sensory Cortex (Passive Background Vision/Audio)
    start_sensors = start_sensors and bool(_cfg.get('camera_enabled', True) or _cfg.get('audio_enabled', False))
    sensory_cortex = SensoryCortex(camera_device=0) if start_sensors else None
    if start_sensors:
        sensory_cortex.start_passive_sensing()
    tool_executor._vision_cortex = sensory_cortex
    
    print(f"  Contacts: {len(channel_router.contacts)} known")
    print(f"  Tools: executor ready")

    # ── 3b. Communication Bots ────────────────────────────────────────────
    telegram_bot = HelixTelegramBot()
    if 'creation' in _cfg or 'telegram_enabled' in _cfg:
        telegram_bot.enabled = telegram_bot.enabled and _cfg.get('telegram_enabled', False)
    channel_router.set_telegram_bot(telegram_bot)
    print(f"  Telegram: {'enabled' if telegram_bot.enabled else 'disabled (no token)'}")

    discord_bot = HelixDiscordBot()
    if 'creation' in _cfg or 'discord_enabled' in _cfg:
        discord_bot.enabled = discord_bot.enabled and _cfg.get('discord_enabled', False)
    channel_router.set_discord_bot(discord_bot)
    print(f"  Discord: {'enabled' if discord_bot.enabled else 'disabled (no token)'}")

    slack_bot = HelixSlackBot()
    if 'creation' in _cfg or 'slack_enabled' in _cfg:
        slack_bot.enabled = slack_bot.enabled and _cfg.get('slack_enabled', False)
    channel_router.set_slack_bot(slack_bot)
    print(f"  Slack: {'enabled' if slack_bot.enabled else 'disabled (no token)'}")

    whatsapp_bot = HelixWhatsAppBot()
    if 'creation' in _cfg or 'whatsapp_enabled' in _cfg:
        whatsapp_bot.enabled = whatsapp_bot.enabled and _cfg.get('whatsapp_enabled', False)
    channel_router.set_whatsapp_bot(whatsapp_bot)
    print(f"  WhatsApp: {'enabled' if whatsapp_bot.enabled else 'disabled (no token)'}")

    webhook_channel = HelixWebhookChannel()
    if 'creation' in _cfg or 'webhook_enabled' in _cfg:
        webhook_channel.enabled = webhook_channel.enabled and _cfg.get('webhook_enabled', False)
    channel_router.set_webhook_channel(webhook_channel)
    print(f"  Webhook: {'enabled' if webhook_channel.enabled else 'disabled (no config)'}")

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
    # _cfg is already loaded at the start of setup_helix()
    pulse_mode = _cfg.get("pulse_mode", "standard")

    provider_config = resolve_main_provider(_mindscape_settings, _cfg)
    if provider_config:
        print(f"  Provider: {provider_config.provider_type} ({provider_config.model})")
    else:
        print("  Provider: NONE — running without LLM")

    # One provider-aware subconscious route for classification, compression,
    # belief formatting/consolidation, and Curator synthesis.  Codex/local
    # providers use isolated sessions; API fallback remains Gemini Flash.
    from core.auxiliary_llm import init_auxiliary_client
    auxiliary_llm = init_auxiliary_client(provider_config)

    # ── 6. Pulse Loop ────────────────────────────────────────────
    journal_dir = os.path.join(data_dir, 'journals')

    if pulse_mode == "dual":
        # ── Dual-Consciousness Mode ─────────────────────────────
        # Detect local provider (Ollama or llama_cpp) for the reasoner
        # and API provider (Gemini or Anthropic) for the actuator.
        local_provider = None
        api_provider = None

        # Local provider: prefer explicit HELIX_LOCAL_MODEL env var
        local_model = os.environ.get("HELIX_LOCAL_MODEL", _cfg.get("local_model", "")).strip()
        local_type = os.environ.get("HELIX_LOCAL_PROVIDER", _cfg.get("local_provider", "ollama")).lower()
        local_ctx = int(_cfg.get("local_context_window", 8192))

        if local_type == "ollama":
            local_model = local_model or "granite4.1:3b"
            local_provider = ProviderConfig(
                provider_type="ollama",
                model=local_model,
                context_window=local_ctx,
                temperature=0.8,
                max_output_tokens=2048,
                options={"num_ctx": local_ctx},
            )
        elif local_type == "llama_cpp":
            if not local_model:
                from pathlib import Path as _Path
                _ggufs = list(_Path("models").glob("*.gguf")) if _Path("models").exists() else []
                local_model = str(_ggufs[0]) if _ggufs else ""
            if local_model:
                local_provider = ProviderConfig(
                    provider_type="llama_cpp",
                    model=local_model,
                    context_window=local_ctx,
                    temperature=0.8,
                    max_output_tokens=2048,
                    options={"n_gpu_layers": -1},
                )

        # API provider: auto-detect (Gemini key or Anthropic key)
        gemini_key = os.environ.get("GEMINI_API_KEY", "")
        anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        api_model = os.environ.get("HELIX_API_MODEL", _cfg.get("api_model", "")).strip()

        if gemini_key:
            api_provider = ProviderConfig(
                provider_type="gemini",
                model=api_model or "gemini-2.5-flash",
                context_window=1_000_000,
                temperature=0.8,
                max_output_tokens=8192,
            )
        elif anthropic_key:
            api_provider = ProviderConfig(
                provider_type="anthropic",
                model=api_model or "claude-fable-5",
                context_window=1_000_000,
                temperature=0.8,
                max_output_tokens=16384,
            )

        if local_provider and api_provider:
            # Guard vision conflict: if local reasoner uses Ollama,
            # force vision to use Gemini API instead to avoid contention.
            if local_provider.provider_type == "ollama":
                os.environ.setdefault("HELIX_VISION_PROVIDER", "gemini")
                print(f"  Vision: routed to Gemini API (local reasoner uses Ollama)")

            print(f"  Pulse mode: DUAL")
            print(f"    Local Reasoner: {local_provider.provider_type} ({local_provider.model}, ctx={local_provider.context_window})")
            print(f"    API Actuator:   {api_provider.provider_type} ({api_provider.model})")

            pulse_loop = DualPulseLoop(
                memory_manager=memory_manager,
                belief_store=belief_store,
                physics_engine=physics,
                preconscious=preconscious,
                scratchpad=scratchpad,
                tool_executor=tool_executor,
                channel_router=channel_router,
                local_provider_config=local_provider,
                api_provider_config=api_provider,
                journal_dir=journal_dir,
                thought_callback=on_thought,
                delivery_callback=on_delivery,
                context_callback=on_context if show_context else None,
                sentinel=sentinel,
                sensory_cortex=sensory_cortex,
            )
        else:
            print(f"  ⚠ Dual mode requested but missing providers:")
            print(f"    Local: {'✓' if local_provider else '✗ (set HELIX_LOCAL_MODEL or local_model in config)'}")
            print(f"    API:   {'✓' if api_provider else '✗ (set GEMINI_API_KEY or ANTHROPIC_API_KEY)'}")
            print(f"  Falling back to standard pulse mode.")
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
                context_callback=on_context if show_context else None,
                sentinel=sentinel,
                sensory_cortex=sensory_cortex,
            )
    else:
        # ── Standard Pulse Mode ─────────────────────────────────
        print(f"  Pulse mode: standard")
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
            context_callback=on_context if show_context else None,
            sentinel=sentinel,
            sensory_cortex=sensory_cortex,
        )

    pulse_loop.config = _cfg
    if _mindscape_settings is not None:
        from core.mindscape import Mindscape
        pulse_loop.mindscape = Mindscape(_mindscape_settings, data_dir, preconscious, local_models=local_models)
        pulse_loop.mindscape.progress_feedback = pulse_loop.progress_feedback
        auxiliary_llm.context_counter = pulse_loop.mindscape.token_counter
        print("  Mindscape: Helix + mRAG + MightyMem/Habitus cortex + RWKV + Context Loom loaded")
        print(f"  Composition receipt: {pulse_loop.mindscape.directory / 'composition-manifest.json'}")

    # Wire comms bots to pulse loop for inbound messages
    telegram_bot.set_pulse_loop(pulse_loop)
    discord_bot.set_pulse_loop(pulse_loop)
    slack_bot.set_pulse_loop(pulse_loop)
    whatsapp_bot.set_pulse_loop(pulse_loop)
    webhook_channel.set_pulse_loop(pulse_loop)

    # Wire tool executor to pulse loop for context reset tool
    tool_executor.set_pulse_loop(pulse_loop)

    # Wire sentinel to tool executor (for somatic echo on memory recall)
    tool_executor._sentinel = sentinel

    # ── Sentinel → PulseLoop event bridge ────────────────────────────
    #    Stability events (critical, warning, context_awareness) flow
    #    into the pulse loop's event queue so Helix can consciously
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
    #    The Curator needs an llm_client with .generate(prompt, system_instruction)
    #    for Phase 2 (belief extraction) and Phase 3 (compound synthesis).
    class _CuratorResponse:
        def __init__(self, text: str):
            self.text = text or ""

    class _CuratorLLM:
        """Adapt AuxiliaryLLM text results to Curator's response interface."""
        def generate(self, prompt: str, system_instruction: str = ""):
            text = auxiliary_llm.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=0.3,
                max_output_tokens=8192,
            )
            return _CuratorResponse(text or "")

    curator_llm = _CuratorLLM()
    curator_route = (
        provider_config.provider_type if provider_config else "gemini fallback"
    )
    print(f"  Curator LLM: ready ({curator_route} auxiliary route)")

    daemon = BackgroundDaemon(
        physics_engine=physics,
        belief_store=belief_store,
        memory_manager=memory_manager,
        llm_client=curator_llm,
        data_dir=data_dir,
        case_office=getattr(
            getattr(getattr(preconscious, "_unified", None), "context_office", None),
            "cases",
            None,
        ),
    )

    print("  Pulse loop: Ready")

    # Wire dream engine to pulse loop for rollover snapshots
    pulse_loop.set_dream_engine(daemon)
    if getattr(pulse_loop, "mindscape", None) is not None:
        pulse_loop.mindscape.body.workspace.dream_engine = daemon

    # ── 7b. GGUF Manager (Micro-Models) ──────────────────────────────
    from core.gguf_manager import GGUFManager
    gguf_manager = GGUFManager(models_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "models"))
    gguf_manager.load_model("fast_classifier", "granite-4.1-3b-Q4_K_M.gguf", n_ctx=8192)

    # ── 8. Post-Pulse Hooks (Subconscious Background Tasks) ──────────
    from core.post_pulse_hooks import register_hook
    from core.workflow_detector import workflow_pattern_hook, set_dependencies

    # Natural thought -> durable task inception. In observe mode this records
    # and audits intentions while legacy action execution remains intact. In
    # active mode the main consciousness becomes thought-only and bounded,
    # identity-shared focus threads receive task-specific capabilities.
    from core.task_cognition.controller import TaskCognitionController

    task_controller = TaskCognitionController(
        data_dir=data_dir,
        mode=_cfg.get("task_cognition_mode", "observe"),
        pulse_loop=pulse_loop,
        belief_store=belief_store,
        memory_manager=memory_manager,
        physics_engine=physics,
        provider_config=provider_config,
        tool_executor=tool_executor,
        max_workers=_cfg.get("task_focus_workers", 2),
        max_depth=_cfg.get("task_focus_max_depth", 4),
    )
    if hasattr(pulse_loop, "set_task_cognition_controller"):
        pulse_loop.set_task_cognition_controller(task_controller)
    else:
        pulse_loop._task_cognition = task_controller
    register_hook(task_controller.observe_pulse, name="task_inception")

    set_dependencies(memory_manager, physics, sentinel=sentinel)
    register_hook(workflow_pattern_hook, name="workflow_detector")

    # Belief detector: scans internal monologue for belief realizations
    from core.belief_detector import (
        belief_detector_hook,
        set_dependencies as set_belief_deps,
    )
    set_belief_deps(belief_store, physics, sentinel=sentinel, gguf_manager=gguf_manager)
    register_hook(belief_detector_hook, name="belief_detector")

    # Engagement hook: tracks thought stagnation and tool activity → Ω
    from core.engagement_hook import (
        engagement_hook,
        set_dependencies as set_engagement_deps,
    )
    set_engagement_deps(sentinel, physics_engine=physics)
    register_hook(engagement_hook, name="engagement_monitor")

    # Co-occurrence hook: passive observer that tracks which beliefs are
    # co-injected into the context window. The nightly Curator reads its
    # clusters for compound synthesis. No writes to belief store or manifold.
    from core.co_occurrence_hook import register_co_occurrence_hook
    co_tracker = register_co_occurrence_hook(data_dir=data_dir)

    # Affect field hook: Plutchik emotional wave packets (Layer 3)
    # Deposits packets from Lagrangian signals every pulse, evolves
    # anisotropic diffusion, samples interference for steering + memory
    from core.affect_hook import register_affect_hook
    affect_field = register_affect_hook(
        sentinel=sentinel,
        spatial_mind=physics.spatial_mind,
        data_dir=data_dir,
    )

    print(
        "  Post-pulse hooks: registered "
        f"(task_inception={task_controller.mode}, workflow_detector, "
        "belief_detector, engagement_monitor, co_occurrence_tracker, affect_field)"
    )

    return pulse_loop, orchestrator, daemon, memory_manager, belief_store, scratchpad, telegram_bot, discord_bot, slack_bot, whatsapp_bot, webhook_channel, sentinel


def main_loop(data_dir="data", interactive=False, show_context=False):
    """Interactive loop — user messages are events in the pulse stream."""
    pulse_loop, orchestrator, daemon, memory, beliefs, scratchpad, telegram_bot, discord_bot, slack_bot, whatsapp_bot, webhook_channel, sentinel = setup_helix(data_dir, show_context=show_context)
    if _shutdown_requested.is_set():
        pulse_loop.stop()
        return

    print("\n--- Helix Pulse System ---")
    print("Commands: 'exit', 'stats', 'core', 'recent', 'beliefs', 'notes', 'dream', 'context'")
    print("Anything else is sent as a user message into the pulse stream.\n")

    # Start communication bots
    telegram_bot.start()
    discord_bot.start()
    slack_bot.start()
    whatsapp_bot.start()
    webhook_channel.start()

    # Start sentinel monitoring thread
    sentinel.start()

    # Start Dashboard communication poller thread
    def poll_dashboard(*, once=False):
        from dashboard.dashboard_comms import get_comms
        comms = get_comms()
        import logging
        poller_logger = logging.getLogger("helix.main.dashboard_poller")
        while once or pulse_loop._running:
            try:
                # Process inbound control commands
                for cmd_obj in comms.pop_control():
                    cmd = cmd_obj.get("command")
                    poller_logger.info(f"Dashboard control command: {cmd}")
                    if cmd == "pause":
                        pulse_loop.pause()
                    elif cmd == "resume":
                        pulse_loop.resume()
                    elif cmd == "shutdown":
                        poller_logger.info("Graceful shutdown requested via dashboard")
                        _shutdown_requested.set()
                        return

                messages = comms.pop_inbound()
                for msg in messages:
                    poller_logger.info(f"Dashboard inbound message from {msg['sender']}: {msg['content'][:100]}")
                    pulse_loop.emit(
                        "user_message",
                        {
                            "sender": msg["sender"],
                            "content": msg["content"],
                            "channel": "dashboard",
                            "chat_id": 0,
                        }
                    )
            except Exception as e:
                poller_logger.error(f"Error polling dashboard: {e}")
            if once:
                return
            time.sleep(1)

    import threading
    from dashboard.dashboard_comms import get_comms
    comms = get_comms()
    agent_name = _cfg.get("agent_name", "Helix")
    comms.write_pid(os.getpid(), agent_name=agent_name)

    # The consumer's running condition must be true before its thread starts.
    # Admit already queued real messages before the first autonomous pulse.
    poll_dashboard(once=True)
    pulse_loop.wake("system_boot")
    pulse_loop.start()
    t = threading.Thread(target=poll_dashboard, daemon=True, name="helix-dashboard-poller")
    t.start()

    # Give it a moment to run the first pulse
    time.sleep(1)

    # Detect if running headless (no terminal attached)
    import sys
    headless = not sys.stdin.isatty() and not interactive

    if headless:
        print("Agent is running through the configured communication channels.")
        try:
            _shutdown_requested.wait()
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
                    # High-importance memories from the journal (the
                    # refactored MemoryManager has no get_core_memories)
                    recent = memory.get_recent(limit=200)
                    core_mems = [
                        m for m in recent
                        if (m.get("importance") or 0) >= 0.7
                    ][:10]
                    if core_mems:
                        print("[Core Memories]")
                        for m in core_mems:
                            print(f"  [{m['created_at']}] (imp={m.get('importance', 0):.2f}) {m['content'][:100]}")
                    else:
                        print("[Core] None yet — stored with importance >= 0.7")
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
                elif user_input.lower() in ("context", "show-context"):
                    show_context = not getattr(pulse_loop, "_context_callback", None)
                    pulse_loop._context_callback = on_context if show_context else None
                    print(f"[Context View] show_context is now {'ON' if show_context else 'OFF'}")
                    continue
                else:
                    # Inject as user message event
                    orchestrator.send_user_message(user_input, sender="User")

                # Wait briefly for the pulse to process
                time.sleep(0.5)

            except KeyboardInterrupt:
                break

    pulse_loop.stop()
    try:
        from dashboard.dashboard_comms import get_comms
        get_comms().clear_pid()
    except Exception:
        pass
    print("\nHelix offline.")


if __name__ == "__main__":
    import argparse
    import signal
    # A launcher shutdown must let initialization or the active pulse finish
    # saving its joint state, including when the process has no terminal.
    signal.signal(signal.SIGTERM, lambda *_: _shutdown_requested.set())
    parser = argparse.ArgumentParser(description="Run the configured Helix composition")
    parser.add_argument("--data-dir", default=_startup_config.get("data_dir", "data"),
                        help="Agent data directory; defaults to the profile selected during setup")
    parser.add_argument("--check-setup", action="store_true", help="Load the actual composition, sync/checkpoint, then exit")
    parser.add_argument("--interactive", action="store_true", help="Force interactive CLI mode even without TTY")
    parser.add_argument("--show-context", action="store_true", help="Print exact rendered context window fed to the agent on each pulse")
    args = parser.parse_args()
    if args.check_setup:
        components = setup_helix(args.data_dir, start_sensors=False, show_context=args.show_context)
        components[0].stop()
        print("Setup initialized. This verifies loading, not agent competence.")
    else:
        main_loop(args.data_dir, interactive=args.interactive, show_context=args.show_context)
