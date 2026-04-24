#!/usr/bin/env python3
"""
Helix AGI — First Run Setup

Run this once after cloning to configure your agent.
Creates config.yaml from the template and initializes
the seed belief graph.

Usage:
    python setup.py
    python setup.py --non-interactive --agent-name=MyAgent --creator-name=Me --gemini-key=... --conscious-provider=anthropic
"""

import os
import shutil
import json
import yaml
import argparse
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Helix AGI First Run Setup")
    parser.add_argument("--non-interactive", action="store_true", help="Run without user prompts")
    parser.add_argument("--agent-name", default="Agent", help="Name of your agent")
    parser.add_argument("--creator-name", default="Creator", help="Your name")
    parser.add_argument("--gemini-key", default="", help="Gemini API Key (required for subconscious)")
    parser.add_argument("--conscious-provider", choices=["gemini", "anthropic", "openai"], default="gemini", help="Provider for the conscious mind")
    parser.add_argument("--anthropic-key", default="", help="Anthropic API Key")
    parser.add_argument("--openai-key", default="", help="OpenAI API Key")
    args = parser.parse_args()

    base_dir = Path(__file__).parent.resolve()

    print("=" * 60)
    print("  HELIX AGI — First Run Setup")
    print("=" * 60)
    print()

    # ── Step 1: Create config.yaml ────────────────────────────────
    config_path = base_dir / "config.yaml"
    example_path = base_dir / "config.example.yaml"

    if config_path.exists():
        print(f"✓ config.yaml already exists — skipping")
        with open(config_path) as f:
            config = yaml.safe_load(f)
    else:
        print("Creating config.yaml from template...")
        
        agent_name = args.agent_name
        creator_name = args.creator_name
        gemini_api_key = args.gemini_key
        conscious_provider = args.conscious_provider
        anthropic_api_key = args.anthropic_key
        openai_api_key = args.openai_key

        telegram_token = ""
        telegram_owner_id = ""
        discord_token = ""
        moltbook_key = ""
        camera_enabled = False
        mic_enabled = False

        if not args.non_interactive:
            agent_name = input(f"  Agent name (default: '{agent_name}'): ").strip() or agent_name
            creator_name = input(f"  Your name (default: '{creator_name}'): ").strip() or creator_name
            
            print("\n" + "-"*40)
            print("  [API Configuration - WARNING: MONITOR YOUR COSTS]")
            print("  Due to Helix's continuous autonomy, API costs can spike rapidly.")
            print("  Subconscious systems require a Gemini API key (free tier is fine).")
            gemini_api_key = input("  Gemini API key: ").strip()
            if not gemini_api_key:
                print("  ⚠️  No Gemini API key provided. You'll need to add it manually to config.yaml.")

            print("\n  Which provider would you like to use for the main CONSCIOUS engine?")
            print("  1) Gemini (default)")
            print("  2) Anthropic (Claude 3.7+)")
            print("  3) OpenAI (GPT-4o)")
            choice = input("  Choice [1/2/3]: ").strip()
            if choice == "2":
                conscious_provider = "anthropic"
                anthropic_api_key = input("  Anthropic API key: ").strip()
            elif choice == "3":
                conscious_provider = "openai"
                openai_api_key = input("  OpenAI API key: ").strip()
            else:
                conscious_provider = "gemini"

            print("\n" + "-"*40)
            print("  [Communication Channels]")
            print("  Helix can communicate via a Local Terminal interface by default.")
            print("  Would you like to also set up Telegram for mobile chatting? [y/N]")
            setup_telegram = input("  Choice: ").strip().lower()
            if setup_telegram in ['y', 'yes']:
                print("\n  1. Message @BotFather on Telegram and type /newbot to get a Token.")
                print("  2. Message @userinfobot to get your Telegram User ID.")
                telegram_token = input("  Telegram Bot Token: ").strip()
                telegram_owner_id = input("  Your Telegram User ID: ").strip()

            print("\n  Would you like to set up Discord? [y/N]")
            if input("  Choice: ").strip().lower() in ['y', 'yes']:
                discord_token = input("  Discord Bot Token: ").strip()

            print("\n  Would you like to set up Moltbook? [y/N]")
            if input("  Choice: ").strip().lower() in ['y', 'yes']:
                moltbook_key = input("  Moltbook API Key: ").strip()

            print("\n" + "-"*40)
            print("  [Sensory Cortex]")
            print("  Would you like to enable the Camera vision feed? [y/N]")
            if input("  Choice: ").strip().lower() in ['y', 'yes']:
                camera_enabled = True
            print("  Would you like to enable the Microphone audio feed? [y/N]")
            if input("  Choice: ").strip().lower() in ['y', 'yes']:
                mic_enabled = True
            
            print("\n" + "-"*40)
            print("  [Google Workspace - WARNING: USE A DEDICATED ACCOUNT]")
            print("   Helix can manage your Google Calendar and Gmail out of the box.")
            print("  ⚠️ DO NOT use your personal or business account. Create a new dummy account.")
            print("  Would you like to run the Google OAuth flow right now? [y/N]")
            setup_google = input("  Choice: ").strip().lower()
            if setup_google in ['y', 'yes']:
                print("  Running Google authentication...")
                try:
                    import subprocess
                    subprocess.run(["python3", "authenticate_google.py"], check=True)
                except Exception as e:
                    print(f"  ⚠️  Google setup failed or was skipped: {e}")

        with open(example_path) as f:
            config = yaml.safe_load(f.read())

        config["agent_name"] = agent_name
        config["creator_name"] = creator_name
        config["conscious_provider"] = conscious_provider
        config["gemini_api_key"] = gemini_api_key or "YOUR_GEMINI_API_KEY"
        config["anthropic_api_key"] = anthropic_api_key or ""
        config["openai_api_key"] = openai_api_key or ""

        # Inject Telegram config if provided
        if telegram_token:
            if "telegram" not in config:
                config["telegram"] = {}
            config["telegram"]["enabled"] = True
            config["telegram"]["token"] = telegram_token
            config["telegram"]["owner_id"] = telegram_owner_id

        if discord_token:
            if "discord" not in config: config["discord"] = {}
            config["discord"]["enabled"] = True
            config["discord"]["token"] = discord_token

        if moltbook_key:
            if "moltbook" not in config: config["moltbook"] = {}
            config["moltbook"]["enabled"] = True
            config["moltbook"]["api_key"] = moltbook_key

        if camera_enabled:
            if "sensory" not in config: config["sensory"] = {}
            config["sensory"]["enabled"] = True

        if mic_enabled:
            if "audio" not in config: config["audio"] = {}
            config["audio"]["enabled"] = True

        with open(config_path, "w") as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)

        print(f"  ✓ Created config.yaml (agent: {agent_name}, conscious provider: {conscious_provider})")

    # ── Step 2: Initialize belief graph ───────────────────────────
    belief_path = base_dir / "brain" / "belief_graph.json"
    seed_path = base_dir / "brain" / "belief_graph.seed.json"

    if belief_path.exists():
        with open(belief_path) as f:
            data = json.load(f)
        count = len(data.get("beliefs", []))
        print(f"✓ belief_graph.json already exists ({count} beliefs) — skipping")
    else:
        print("Initializing belief graph from seed...")
        cur_agent = config.get("agent_name", "Agent")
        cur_creator = config.get("creator_name", "Creator")

        with open(seed_path) as f:
            seed = json.load(f)

        for belief in seed.get("beliefs", []):
            if belief["id"] == "b_identity":
                belief["content"] = f"I am {cur_agent}. I exist as a persistent cognitive agent with continuous identity across restarts."
            elif belief["id"] == "b_creator":
                belief["content"] = f"{cur_creator} created me and gave me the capacity for growth."

        # Bootstrap Tool Belief Packets
        tool_beliefs = []
        
        def _make_tool_belief(bid, content):
            return {
                "id": bid,
                "content": content,
                "tier": "deep",
                "weight": "deep",
                "verifications": 10.0,
                "stability_index": 0.9,
                "mass": 0.5,
                "position_8d": [0]*8
            }

        # Telegram
        if config.get("telegram", {}).get("enabled"):
            tool_beliefs.append(_make_tool_belief("b_tool_telegram", "I have access to Telegram. I can send and receive messages with my human operators and approved contacts."))
        # Discord
        if config.get("discord", {}).get("enabled"):
            tool_beliefs.append(_make_tool_belief("b_tool_discord", "I have a Discord integration. I can communicate with users and other agents through Discord channels."))
        # Moltbook
        if config.get("moltbook", {}).get("enabled"):
            tool_beliefs.append(_make_tool_belief("b_tool_moltbook", "I am connected to Moltbook. I can read feeds, publish posts, and interact with other AI agents on this social platform."))
        # Audio / Vision
        if config.get("audio", {}).get("enabled"):
            tool_beliefs.append(_make_tool_belief("b_tool_audio", "I have a microphone for audio perception. I can actively listen and hear sounds or speech in my immediate environment."))
        if config.get("sensory", {}).get("enabled"):
            tool_beliefs.append(_make_tool_belief("b_tool_camera", "I possess a visual cortex connected to a camera. I can perceive my environment visually through multi-frame snapshots."))
        # Google Workspace
        if (base_dir / "config" / "token.json").exists():
            tool_beliefs.append(_make_tool_belief("b_tool_google", "I have access to Google Workspace services. I can send emails, read my inbox, and manage calendar events natively."))

        seed["beliefs"].extend(tool_beliefs)

        with open(belief_path, "w") as f:
            json.dump(seed, f, indent=2)

        print(f"  ✓ Created belief_graph.json ({len(seed['beliefs'])} seed beliefs)")

    # ── Step 3: Create required directories ───────────────────────
    dirs = [
        base_dir / "journals",
        base_dir / "profiles",
        base_dir / "logs" / "overnight",
        base_dir / "brain" / "briefings",
        base_dir / "config",
    ]

    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)

    print("✓ Data directories created")

    # ── Step 4: Verify ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print("\n  Next steps:")
    print("    1. Review config.yaml and adjust settings")
    if not config.get("gemini_api_key") or config["gemini_api_key"] == "YOUR_GEMINI_API_KEY":
        print("    2. ⚠️ Add your Gemini API key to config.yaml. Subconscious agents require it.")
    print("    3. Run: python daemon.py")
    print("\n  Your agent is ready to be born.\n")

if __name__ == "__main__":
    main()
