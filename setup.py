#!/usr/bin/env python3
"""
Helix AGI — First Run Setup

Run this once after cloning to configure your agent.
Creates ~/.config/helix/credentials.env and initializes
the seed belief graph in the data directory.

Usage:
    python setup.py
    python setup.py --non-interactive --agent-name=MyAgent --creator-name=Me --gemini-key=... 
"""

import os
import json
import argparse
from pathlib import Path
from bootstrap import (
    BootstrapContext,
    PERSONALITY_OPTIONS,
    PROFILE_OPTIONS,
    canonicalize_bootstrap_profile,
    canonicalize_personality,
    personality_label,
    profile_label,
    write_seed_data,
)

DEFAULT_LOCAL_MODEL = "granite4.1:3b"


def apply_config_updates(base_dir: Path, updates: dict) -> bool:
    """Merge keys into config/config.json, preserving everything else."""
    config_path = base_dir / "config" / "config.json"
    config = {}
    if config_path.exists():
        try:
            with open(config_path) as f:
                config = json.load(f)
        except Exception as e:
            print(f"  ⚠ Could not read {config_path}: {e}")
            return False

    config.update(updates)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
            f.write("\n")
    except Exception as e:
        print(f"  ⚠ Could not write {config_path}: {e}")
        return False
    return True


def local_mode_config(provider: str, model: str, context_window: int) -> dict:
    """Config for fully-local operation with orchestrated tool use.

    A local model cannot hold 80 tool schemas in an 8K window, and Ollama has
    no native tool channel at all. `tool_format: orchestrated` gives the main
    window one line per toolset and runs the actual tool work in directed
    passes, so local mode gets the full toolset without the full manifest.
    """
    return {
        "tool_format": "orchestrated",
        "local_provider": provider,
        "local_model": model or DEFAULT_LOCAL_MODEL,
        "local_context_window": context_window,
    }


def subscription_cli_config(provider: str, model: str) -> dict:
    """Config for driving the conscious model through a logged-in CLI.

    A subscription is a quota, not a bill: exhausting the window parks Helix
    for the remainder of it rather than charging more. Measured steady-state
    cost of one resumed Claude Code turn on a small Helix prompt is ~$0.017
    (6.9K cached prefix read + ~700 output tokens), and output — not prompt —
    is the majority of it. At the 30-second REGULAR cadence that is roughly
    $2/hour of quota; at the 15-minute resting cadence it is a few cents.

    So this mode ships with the slowest resting pulse the loop allows. The
    cadence is what makes a subscription viable, not the transport.
    """
    return {
        "llm_provider": provider,
        "llm_model": model,
        "resting_pulse_minutes": 60,
    }


def main():
    parser = argparse.ArgumentParser(description="Helix AGI First Run Setup")
    parser.add_argument("--non-interactive", action="store_true", help="Run without user prompts")
    parser.add_argument("--agent-name", default="Helix", help="Name of your agent")
    parser.add_argument("--creator-name", default="<name>", help="Your name")
    parser.add_argument("--gemini-key", default="", help="Gemini API Key")
    parser.add_argument("--anthropic-key", default="", help="Anthropic API Key")
    parser.add_argument("--openai-key", default="", help="OpenAI API Key")
    parser.add_argument(
        "--provider",
        choices=["codex_cli", "claude_cli", "gemini", "anthropic", "ollama", "llama_cpp"],
        default="gemini",
        help="Primary conscious LLM provider",
    )
    parser.add_argument(
        "--subscription-cli",
        choices=["claude_cli", "codex_cli"],
        default="",
        help="Run the conscious model through an already-logged-in CLI "
             "subscription instead of an API key",
    )
    parser.add_argument("--model", default="", help="Provider model (blank uses the provider default)")
    parser.add_argument(
        "--local-mode",
        action="store_true",
        help="Run fully local: no API key, tools driven by orchestrated "
             "directed passes instead of native function calling",
    )
    parser.add_argument(
        "--local-context-window",
        type=int,
        default=8192,
        help="Context window for the local model in local mode",
    )
    parser.add_argument("--telegram-token", default="", help="Telegram Bot Token")
    parser.add_argument("--telegram-owner", default="", help="Telegram Owner ID")
    parser.add_argument("--discord-token", default="", help="Discord Bot Token")
    parser.add_argument("--slack-bot-token", default="", help="Slack Bot Token (xoxb-...)")
    parser.add_argument("--slack-app-token", default="", help="Slack App Token (xapp-...)")
    parser.add_argument("--whatsapp-token", default="", help="WhatsApp Business API Token")
    parser.add_argument("--whatsapp-phone-id", default="", help="WhatsApp Phone Number ID")
    parser.add_argument("--whatsapp-verify-token", default="", help="WhatsApp Webhook Verify Token")
    parser.add_argument("--webhook-outbound-url", default="", help="Generic Webhook Outbound URL")
    parser.add_argument("--webhook-inbound-secret", default="", help="Generic Webhook Inbound Secret")
    parser.add_argument("--moltbook-key", default="", help="Moltbook API Key")
    parser.add_argument(
        "--profile",
        choices=["birth", "prepared", "developed", "basic", "standard", "predeveloped", "pre-developed", "import", "imported", "external"],
        default="standard",
        help="Cognitive bootstrap profile",
    )
    parser.add_argument(
        "--personality",
        choices=["curious", "friendly", "safe", "professional"],
        default="curious",
        help="Initial voice seed for bootstrap beliefs",
    )
    parser.add_argument("--vision-provider", choices=["local", "gemini"], default="local", help="Vision provider (local model or Gemini)")
    args = parser.parse_args()

    base_dir = Path(__file__).parent.resolve()

    print("=" * 60)
    print("  HELIX AGI — First Run Setup")
    print("=" * 60)
    print()

    # ── Step 1: Create credentials.env ────────────────────────────────
    cred_dir = Path(os.path.expanduser("~/.config/helix"))
    cred_dir.mkdir(parents=True, exist_ok=True)
    cred_path = cred_dir / "credentials.env"

    # Bound before the branch below: credential creation is skipped on a
    # re-run, but the mode selection still has to be applied.
    local_mode = args.local_mode
    subscription_cli = args.subscription_cli
    llm_provider = args.provider
    llm_model = args.model
    if subscription_cli:
        llm_provider = subscription_cli
        local_mode = False
    elif local_mode and llm_provider not in {"ollama", "llama_cpp"}:
        llm_provider = "ollama"

    if cred_path.exists():
        print(f"✓ {cred_path} already exists — skipping credential creation.")
    else:
        print("Creating credentials.env...")
        
        gemini_api_key = args.gemini_key
        anthropic_api_key = args.anthropic_key
        openai_api_key = args.openai_key
        telegram_token = args.telegram_token
        telegram_owner_id = args.telegram_owner
        discord_token = args.discord_token
        slack_bot_token = args.slack_bot_token
        slack_app_token = args.slack_app_token
        whatsapp_token = args.whatsapp_token
        whatsapp_phone_id = args.whatsapp_phone_id
        whatsapp_verify_token = args.whatsapp_verify_token
        webhook_outbound_url = args.webhook_outbound_url
        webhook_inbound_secret = args.webhook_inbound_secret
        moltbook_key = args.moltbook_key
        vision_provider = args.vision_provider
        llm_provider = args.provider
        llm_model = args.model
        local_mode = args.local_mode
        subscription_cli = args.subscription_cli
        if subscription_cli:
            llm_provider = subscription_cli
            local_mode = False
        elif local_mode and llm_provider not in {"ollama", "llama_cpp"}:
            llm_provider = "ollama"

        # Track which comms channels the user enables
        enabled_channels = ["dashboard"]  # Dashboard is always enabled

        if not args.non_interactive:
            print("\n" + "-"*40)
            print("  [Mode]")
            print("  1. Local  — runs entirely on your machine. No API key, no")
            print("              per-token cost. Full tool use via orchestrated")
            print("              directed passes. Slower, and needs Ollama or a")
            print("              GGUF model installed.")
            print("  2. Hosted — an API provider drives the conscious model, with")
            print("              native tool calling. Faster and sharper; costs")
            print("              money continuously, because Helix never stops.")
            print("  3. Subscription CLI — an already-logged-in Codex or Claude")
            print("              Code CLI drives the conscious model. No API key.")
            print("              A subscription is a quota, not a bill: running")
            print("              hot exhausts the window and parks Helix, so this")
            print("              mode gates the model behind a slower pulse.")
            mode_choice = input("  Mode (1/2/3) [2]: ").strip()
            local_mode = mode_choice == "1"
            subscription_cli = ""

            if mode_choice == "3":
                selected = input(
                    "  CLI (claude_cli/codex_cli) [claude_cli]: "
                ).strip().lower()
                subscription_cli = (
                    selected if selected in {"claude_cli", "codex_cli"} else "claude_cli"
                )
                llm_provider = subscription_cli
                llm_model = input(
                    "  Model (blank = account default): "
                ).strip()
                binary = "claude" if subscription_cli == "claude_cli" else "codex"
                print(f"  Subscription CLI selected — make sure `{binary}` is logged in.")
                print("  Pulse cadence will be set to resting-only to protect the quota.")
            elif local_mode:
                selected = input(
                    "  Local runtime (ollama/llama_cpp) [ollama]: "
                ).strip().lower()
                llm_provider = selected if selected in {"ollama", "llama_cpp"} else "ollama"
                llm_model = input(
                    f"  Local model (blank = {DEFAULT_LOCAL_MODEL}): "
                ).strip()
                print("  Local mode selected — no API keys required.")
                print("  Tools run through directed passes, one toolset at a time.")
            else:
                print("\n" + "-"*40)
                print("  [API Configuration - WARNING: MONITOR YOUR COSTS]")
                print("  Due to Helix's continuous autonomy, API costs can spike rapidly.")
                print("  Subconscious systems follow the selected provider; Gemini remains an optional fallback.")
                selected = input(
                    "  Primary provider (codex_cli/gemini/anthropic/ollama/llama_cpp) "
                    "[gemini]: "
                ).strip().lower()
                if selected in {"codex_cli", "gemini", "anthropic", "ollama", "llama_cpp"}:
                    llm_provider = selected
                llm_model = input(
                    "  Primary model (blank = provider/account default): "
                ).strip()
                gemini_api_key = input("  Gemini API key: ").strip()
                anthropic_api_key = input("  Anthropic API key (optional): ").strip()
                openai_api_key = input("  OpenAI API key (optional): ").strip()

            print("\n" + "-"*40)
            print("  [Vision Configuration]")
            print("  Helix can use either a local vision model (Ollama/Gemma3) or Gemini Flash.")
            print("  Using the local model is free and cost-efficient.")
            vision_provider = input("  Vision provider (local/gemini) [default: local]: ").strip().lower()
            if vision_provider not in ['local', 'gemini']:
                vision_provider = 'local'

            print("\n" + "-"*40)
            print("  [Communication Channels]")
            print("  The web dashboard (localhost chat) is always enabled.")
            setup_telegram = input("  Set up Telegram? [y/N]: ").strip().lower()
            if setup_telegram in ['y', 'yes']:
                telegram_token = input("  Telegram Bot Token: ").strip()
                telegram_owner_id = input("  Your Telegram User ID: ").strip()
                if telegram_token:
                    enabled_channels.append("telegram")

            setup_discord = input("  Set up Discord? [y/N]: ").strip().lower()
            if setup_discord in ['y', 'yes']:
                discord_token = input("  Discord Bot Token: ").strip()
                if discord_token:
                    enabled_channels.append("discord")

            setup_slack = input("  Set up Slack? [y/N]: ").strip().lower()
            if setup_slack in ['y', 'yes']:
                print("  Slack requires both a Bot Token (xoxb-...) and an App Token (xapp-...).")
                print("  Create these at https://api.slack.com/apps")
                slack_bot_token = input("  Slack Bot Token (xoxb-...): ").strip()
                slack_app_token = input("  Slack App Token (xapp-...): ").strip()
                if slack_bot_token and slack_app_token:
                    enabled_channels.append("slack")

            setup_whatsapp = input("  Set up WhatsApp? [y/N]: ").strip().lower()
            if setup_whatsapp in ['y', 'yes']:
                print("  WhatsApp requires a Business Cloud API token and Phone Number ID.")
                print("  Configure these at https://developers.facebook.com/")
                whatsapp_token = input("  WhatsApp API Token: ").strip()
                whatsapp_phone_id = input("  WhatsApp Phone Number ID: ").strip()
                whatsapp_verify_token = input("  Webhook Verify Token (for inbound, optional): ").strip()
                if whatsapp_token and whatsapp_phone_id:
                    enabled_channels.append("whatsapp")

            setup_webhook = input("  Set up Generic Webhook? [y/N]: ").strip().lower()
            if setup_webhook in ['y', 'yes']:
                print("  The generic webhook connects Helix to any external service")
                print("  (Zapier, n8n, Matrix bridges, custom apps, etc.)")
                webhook_outbound_url = input("  Outbound Webhook URL (where Helix sends messages): ").strip()
                webhook_inbound_secret = input("  Inbound Secret (for verifying incoming POSTs, optional): ").strip()
                if webhook_outbound_url or webhook_inbound_secret:
                    enabled_channels.append("webhook")

            setup_moltbook = input("  Set up Moltbook? [y/N]: ").strip().lower()
            if setup_moltbook in ['y', 'yes']:
                moltbook_key = input("  Moltbook API Key: ").strip()
        else:
            # Non-interactive: detect channels from provided tokens
            if telegram_token:
                enabled_channels.append("telegram")
            if discord_token:
                enabled_channels.append("discord")
            if slack_bot_token and slack_app_token:
                enabled_channels.append("slack")
            if whatsapp_token and whatsapp_phone_id:
                enabled_channels.append("whatsapp")
            if webhook_outbound_url or webhook_inbound_secret:
                enabled_channels.append("webhook")

        comms_channels = ",".join(enabled_channels)

        with open(cred_path, "w") as f:
            f.write(f"GEMINI_API_KEY={gemini_api_key}\n")
            f.write(f"ANTHROPIC_API_KEY={anthropic_api_key}\n")
            f.write(f"OPENAI_API_KEY={openai_api_key}\n")
            f.write(f"HELIX_TELEGRAM_TOKEN={telegram_token}\n")
            f.write(f"TELEGRAM_OWNER_ID={telegram_owner_id}\n")
            f.write(f"HELIX_DISCORD_TOKEN={discord_token}\n")
            f.write(f"HELIX_SLACK_BOT_TOKEN={slack_bot_token}\n")
            f.write(f"HELIX_SLACK_APP_TOKEN={slack_app_token}\n")
            f.write(f"HELIX_WHATSAPP_TOKEN={whatsapp_token}\n")
            f.write(f"HELIX_WHATSAPP_PHONE_ID={whatsapp_phone_id}\n")
            f.write(f"HELIX_WHATSAPP_VERIFY_TOKEN={whatsapp_verify_token}\n")
            f.write(f"HELIX_WEBHOOK_OUTBOUND_URL={webhook_outbound_url}\n")
            f.write(f"HELIX_WEBHOOK_INBOUND_SECRET={webhook_inbound_secret}\n")
            f.write(f"MOLTBOOK_API_KEY={moltbook_key}\n")
            f.write(f"HELIX_COMMS_CHANNELS={comms_channels}\n")
            f.write(f"HELIX_PROVIDER={llm_provider}\n")
            f.write(f"HELIX_MODEL={llm_model}\n")
            f.write(f"HELIX_VISION_PROVIDER={vision_provider}\n")
            f.write(f"HELIX_VISION_MODEL=gemini-2.5-flash\n")

        print(f"  ✓ Created {cred_path}")
        print(f"  ✓ Enabled comms channels: {comms_channels}")

    # ── Subscription CLI: quota-paced conscious model, no API key ─────
    if subscription_cli:
        updates = subscription_cli_config(subscription_cli, llm_model)
        if apply_config_updates(base_dir, updates):
            print(
                f"  ✓ Subscription CLI: {subscription_cli} "
                f"({llm_model or 'account default'}), "
                f"resting pulse every {updates['resting_pulse_minutes']} min"
            )

    # ── Local mode: orchestrated tool use, no API dependency ──────────
    if local_mode:
        updates = local_mode_config(
            llm_provider, llm_model, args.local_context_window,
        )
        if apply_config_updates(base_dir, updates):
            print(
                f"  ✓ Local mode: {updates['local_provider']} "
                f"({updates['local_model']}, ctx={updates['local_context_window']}), "
                "orchestrated tool use"
            )

    # ── Step 2: Create required directories ───────────────────────
    dirs = [
        base_dir / "journals",
        base_dir / "logs",
        base_dir / "data" / "beliefs",
        base_dir / "data" / "memory",
        base_dir / "data" / "scratchpad",
        base_dir / "data" / "spatial",
        base_dir / "data" / "screenshots",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    print("✓ Data directories created")

    # ── Detect available integrations from credentials ────────────
    # Determines which skill/capability beliefs to seed based on
    # what the user has actually configured.
    available = {
        "github": bool(os.environ.get("GITHUB_TOKEN")),
        "google": os.path.exists(os.path.expanduser("~/.config/helix/google_token.json")),
        "moltbook": False,
        "telegram": False,
        "discord": False,
        "slack": False,
        "whatsapp": False,
        "webhook": False,
        "vision": os.path.exists("/dev/video0"),
        "audio_tts": False,
    }

    # Parse credentials.env for integration tokens
    if cred_path.exists():
        with open(cred_path) as f:
            for line in f:
                line = line.strip()
                if "=" in line:
                    key, _, val = line.partition("=")
                    if key == "MOLTBOOK_API_KEY" and val:
                        available["moltbook"] = True
                    elif key == "HELIX_TELEGRAM_TOKEN" and val:
                        available["telegram"] = True
                    elif key == "HELIX_DISCORD_TOKEN" and val:
                        available["discord"] = True
                    elif key == "HELIX_SLACK_BOT_TOKEN" and val:
                        available["slack"] = True
                    elif key == "HELIX_WHATSAPP_TOKEN" and val:
                        available["whatsapp"] = True
                    elif key in ("HELIX_WEBHOOK_OUTBOUND_URL", "HELIX_WEBHOOK_INBOUND_SECRET") and val:
                        available["webhook"] = True
                    elif key == "GITHUB_TOKEN" and val:
                        available["github"] = True

    # Check for TTS capability (piper + audio player)
    try:
        import subprocess
        import importlib
        importlib.import_module("piper")
        # Also need an audio player to actually hear it
        import shutil
        has_player = any(shutil.which(p) for p in ["ffplay", "gst-play-1.0", "mpv", "gst-launch-1.0"])
        if has_player:
            available["audio_tts"] = True
    except Exception:
        pass

    # Build dynamic comms channel list for belief text
    _comms_list = ["Dashboard"]  # Always available
    if available["telegram"]:
        _comms_list.append("Telegram")
    if available["discord"]:
        _comms_list.append("Discord")
    if available["slack"]:
        _comms_list.append("Slack")
    if available["whatsapp"]:
        _comms_list.append("WhatsApp")
    if available["webhook"]:
        _comms_list.append("Webhook")

    print(f"  Detected integrations: {', '.join(k for k, v in available.items() if v) or 'core only'}")

    agent_name = args.agent_name
    creator_name = args.creator_name
    profile = canonicalize_bootstrap_profile(args.profile)
    personality = canonicalize_personality(args.personality)

    if not args.non_interactive:
        print("\n" + "-"*40)
        print("  [Agent Identity]")
        agent_name = input(f"  Agent name (default: '{agent_name}'): ").strip() or agent_name
        creator_name = input(f"  Your name (default: '{creator_name}'): ").strip() or creator_name

        print("\n" + "-"*40)
        print("  [Cognitive Profile]")
        print("  Select the initial developmental level for your agent:")
        print("  1) Basic (minimal autonomy, continuity, and orientation beliefs)")
        print("  2) Standard (recommended default bootstrap)")
        print("  3) Pre-Developed (deeper reflective and preconscious framing)")
        choice = input("  Selection [1-3, default 2]: ").strip()
        if choice == "1":
            profile = "basic"
        elif choice == "3":
            profile = "predeveloped"
        else:
            profile = "standard"

        print("\n" + "-"*40)
        print("  [Bootstrap Voice]")
        print("  Select the initial wording style for your agent:")
        print("  1) Friendly (warm, collaborative, relational language)")
        print("  2) Curious (exploratory, synthesis-seeking language)")
        print("  3) Safe (careful, verification-first language)")
        print("  4) Professional (concise, structured, exact language)")
        p_choice = input("  Selection [1-4, default 2]: ").strip()
        if p_choice == "1":
            personality = "friendly"
        elif p_choice == "3":
            personality = "safe"
        elif p_choice == "4":
            personality = "professional"
        else:
            personality = "curious"

    # ── Load schedule from config for dynamic belief text ─────────────
    config_path = base_dir / "config" / "config.json"
    sleep_time_str = "23:00"
    wake_time_str = "08:00"
    if config_path.exists():
        try:
            with open(config_path) as f:
                _cfg = json.load(f)
            active_hours = _cfg.get("active_hours", {})
            sleep_time_str = active_hours.get("end", "23:00")
            wake_time_str = active_hours.get("start", "08:00")
        except Exception:
            pass

    # ── Step 3: Initialize dynamic bootstrap seed ──────────────────
    bootstrap_context = BootstrapContext(
        agent_name=agent_name,
        creator_name=creator_name,
        profile=profile,
        personality=personality,
        wake_time=wake_time_str,
        sleep_time=sleep_time_str,
        channels=_comms_list,
    )
    seed_result = write_seed_data(base_dir / "data", bootstrap_context, overwrite=False)

    print(
        f"  Seeding bootstrap beliefs ({profile_label(profile)} profile, "
        f"{personality_label(personality)} voice)..."
    )
    for category, count in seed_result["belief_counts"].items():
        if category in seed_result["written_categories"]:
            print(f"    ✓ {category}.json ({count} beliefs)")
        else:
            print(f"    - {category}.json already populated; leaving existing beliefs intact")
    if seed_result["memory_journal_written"]:
        print(f"    ✓ cognitive_journal.jsonl ({seed_result['memory_count']} bootstrap memories)")
    else:
        print("    - cognitive_journal.jsonl already populated; leaving existing memories intact")

    # ── Step 4: Verify ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print("\n  Next steps:")
    print(f"    1. Review and populate your API keys in {cred_path}")
    print("    2. Run: python main.py")
    print("\n  IMPORTANT: Your agent is basically a newborn. On startup, be prepared")
    print("  to immediately converse with it to explain who it is, verify its tools")
    print("  are fully set up, and ground its initial cognitive state.\n")

if __name__ == "__main__":
    main()
