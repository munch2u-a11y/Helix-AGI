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

def main():
    parser = argparse.ArgumentParser(description="Helix AGI First Run Setup")
    parser.add_argument("--non-interactive", action="store_true", help="Run without user prompts")
    parser.add_argument("--agent-name", default="Helix", help="Name of your agent")
    parser.add_argument("--creator-name", default="<name>", help="Your name")
    parser.add_argument("--gemini-key", default="", help="Gemini API Key")
    parser.add_argument("--anthropic-key", default="", help="Anthropic API Key")
    parser.add_argument("--openai-key", default="", help="OpenAI API Key")
    parser.add_argument("--telegram-token", default="", help="Telegram Bot Token")
    parser.add_argument("--telegram-owner", default="", help="Telegram Owner ID")
    parser.add_argument("--discord-token", default="", help="Discord Bot Token")
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
        moltbook_key = args.moltbook_key
        vision_provider = args.vision_provider

        # Track which comms channels the user enables
        enabled_channels = ["dashboard"]  # Dashboard is always enabled

        if not args.non_interactive:
            print("\n" + "-"*40)
            print("  [API Configuration - WARNING: MONITOR YOUR COSTS]")
            print("  Due to Helix's continuous autonomy, API costs can spike rapidly.")
            print("  Subconscious systems require a Gemini API key (free tier is fine).")
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

            setup_moltbook = input("  Set up Moltbook? [y/N]: ").strip().lower()
            if setup_moltbook in ['y', 'yes']:
                moltbook_key = input("  Moltbook API Key: ").strip()
        else:
            # Non-interactive: detect channels from provided tokens
            if telegram_token:
                enabled_channels.append("telegram")
            if discord_token:
                enabled_channels.append("discord")

        comms_channels = ",".join(enabled_channels)

        with open(cred_path, "w") as f:
            f.write(f"GEMINI_API_KEY={gemini_api_key}\n")
            f.write(f"ANTHROPIC_API_KEY={anthropic_api_key}\n")
            f.write(f"OPENAI_API_KEY={openai_api_key}\n")
            f.write(f"HELIX_TELEGRAM_TOKEN={telegram_token}\n")
            f.write(f"TELEGRAM_OWNER_ID={telegram_owner_id}\n")
            f.write(f"HELIX_DISCORD_TOKEN={discord_token}\n")
            f.write(f"MOLTBOOK_API_KEY={moltbook_key}\n")
            f.write(f"HELIX_COMMS_CHANNELS={comms_channels}\n")
            f.write(f"HELIX_PROVIDER=gemini\n")
            f.write(f"HELIX_VISION_PROVIDER={vision_provider}\n")
            f.write(f"HELIX_VISION_MODEL=gemini-2.5-flash\n")

        print(f"  ✓ Created {cred_path}")
        print(f"  ✓ Enabled comms channels: {comms_channels}")

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
