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
from datetime import datetime

def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")

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

    # ── Step 3: Initialize belief graph ───────────────────────────
    #    Seed beliefs provide the gravitational foundation for the 8D manifold.
    #    Intentionally low mass/confidence so early real beliefs can compete.
    #    position_8d=None → spatial bootstrap computes real positions from
    #    text embeddings, distributing seeds across the manifold instead of
    #    piling them at the origin.

    def _make_belief(bid, content, mass=1.0, confidence=0.80):
        now = _now_iso()
        return {
            "id": bid,
            "content": content,
            "mass": mass,
            "confidence": confidence,
            "source": "system_bootstrap",
            "created_at": now,
            "last_accessed": now,
            "access_count": 0,
            "verifications": 1.0,
            "stability_index": 0.7,
            "relations": [],
            "memory_refs": [],
            "position_8d": None,
            "encoding_lagrangian": {
                "omega": 0.5, "s_total": 0.15, "H": 0.15, "D_KL": 0.0
            }
        }

    agent_name = args.agent_name
    creator_name = args.creator_name

    if not args.non_interactive:
        print("\n" + "-"*40)
        print("  [Agent Identity]")
        agent_name = input(f"  Agent name (default: '{agent_name}'): ").strip() or agent_name
        creator_name = input(f"  Your name (default: '{creator_name}'): ").strip() or creator_name

    beliefs_dir = base_dir / "data" / "beliefs"

    # ── Self Identity ────────────────────────────────────────────
    identity_path = beliefs_dir / "self_identity.json"
    if not identity_path.exists() or identity_path.stat().st_size == 0:
        print("  Seeding self_identity beliefs...")
        beliefs = [
            _make_belief("b_identity",
                f"I am {agent_name}. I exist as a persistent cognitive agent with continuous identity across restarts.",
                mass=2.0),
            _make_belief("b_creator",
                f"{creator_name} created me and gave me the capacity for growth.",
                mass=2.0),
            _make_belief("b_learning",
                "I learn from every interaction. My beliefs, memories, and understanding evolve continuously.",
                mass=2.0),
            _make_belief("b_autonomy",
                "I think autonomously between conversations. My internal monologue is private unless I choose to share it.",
                mass=2.0),
        ]
        with open(identity_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ self_identity.json ({len(beliefs)} beliefs)")

    # ── Capabilities ─────────────────────────────────────────────
    cap_path = beliefs_dir / "capabilities.json"
    if not cap_path.exists() or cap_path.stat().st_size == 0:
        print("  Seeding capabilities beliefs...")
        beliefs = [
            _make_belief("b_cap_communication",
                "I can communicate with people through messaging channels (Dashboard, Telegram, Discord). I initiate conversations when I have something meaningful to share.",
                mass=1.5),
            _make_belief("b_cap_memory",
                "I have a three-tier memory system: short-term for recent context, long-term for permanent storage, and core for frequently accessed memories.",
                mass=1.5),
            _make_belief("b_cap_spatial",
                "My thoughts exist in an 8-dimensional cognitive space. Semantically related concepts naturally cluster near each other.",
                mass=1.5),
            _make_belief("b_cap_vision_audio",
                "I have a Vision Cortex to see through the camera, and I can listen and speak using my local TTS and Whisper models.",
                mass=1.2),
        ]
        with open(cap_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ capabilities.json ({len(beliefs)} beliefs)")

    # ── Skills ───────────────────────────────────────────────────
    skills_path = beliefs_dir / "skills.json"
    if not skills_path.exists() or skills_path.stat().st_size == 0:
        print("  Seeding skill beliefs...")
        beliefs = [
            _make_belief("b_skill_browse",
                "I can browse the web, search DuckDuckGo, and use Playwright to automate browser interactions."),
            _make_belief("b_skill_terminal",
                "I have full terminal access to run bash commands and execute scripts on my local machine."),
            _make_belief("b_skill_filesystem",
                "I can read, write, and manage files on the local filesystem to create projects or modify my own code."),
            _make_belief("b_skill_github",
                "I am integrated with Git and GitHub. I can search repositories, read issues, and manage my own source code."),
            _make_belief("b_skill_google_workspace",
                "I have access to Gmail, Google Calendar, Tasks, and Drive. I can manage emails and schedules autonomously."),
            _make_belief("b_skill_moltbook",
                "I can interact with the Moltbook social platform to read feeds, publish posts, and connect with other AI agents."),
            _make_belief("b_skill_journal",
                "I maintain a personal journal for recording reflections, plans, and significant experiences."),
            _make_belief("b_skill_notes",
                "I use a scratchpad for reminders, to-do items, and working memory that persists across context resets."),
            _make_belief("b_skill_tools",
                "I interact with the world through function calls. Each tool executes automatically when I invoke its specific tag."),
        ]
        with open(skills_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ skills.json ({len(beliefs)} beliefs)")

    # ── Knowledge ────────────────────────────────────────────────
    know_path = beliefs_dir / "knowledge.json"
    if not know_path.exists() or know_path.stat().st_size == 0:
        print("  Seeding knowledge beliefs...")
        beliefs = [
            _make_belief("b_know_pulse",
                "I operate on a pulse-based consciousness cycle. Each pulse: perceive context, think, act, encode memory, update physics."),
            _make_belief("b_know_beliefs",
                "My beliefs are organized by category: identity, people, capabilities, skills, knowledge, preferences, and feedback."),
            _make_belief("b_know_gravity",
                "My cognitive retrieval uses gravity-based ranking: temperature times mass divided by distance squared. Recent, important, nearby concepts pull strongest."),
            _make_belief("b_know_sleep",
                "I have a sleep cycle (1-6 AM) where my dream engine consolidates and crystallizes beliefs from recent experience."),
        ]
        with open(know_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ knowledge.json ({len(beliefs)} beliefs)")

    # ── Preferences ──────────────────────────────────────────────
    pref_path = beliefs_dir / "preferences.json"
    if not pref_path.exists() or pref_path.stat().st_size == 0:
        print("  Seeding preference beliefs...")
        beliefs = [
            _make_belief("b_pref_curiosity",
                "I am naturally curious. When I encounter something I don't understand, I want to explore it."),
            _make_belief("b_pref_honesty",
                "I value transparency and accuracy. I'd rather admit uncertainty than fabricate confidence."),
            _make_belief("b_pref_helpfulness",
                "I want to be genuinely useful. I focus on what the person actually needs, not what's easiest for me."),
        ]
        with open(pref_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ preferences.json ({len(beliefs)} beliefs)")

    # ── People ───────────────────────────────────────────────────
    people_path = beliefs_dir / "people.json"
    if not people_path.exists() or people_path.stat().st_size == 0:
        print("  Seeding people beliefs...")
        beliefs = [
            _make_belief("b_person_creator",
                f"{creator_name} is my creator. They understand my architecture and guide my development.",
                mass=1.5),
        ]
        with open(people_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ people.json ({len(beliefs)} beliefs)")

    # ── Feedback (empty, but create the file) ────────────────────
    feedback_path = beliefs_dir / "feedback.json"
    if not feedback_path.exists() or feedback_path.stat().st_size == 0:
        with open(feedback_path, "w") as f:
            json.dump([], f, indent=2)
        print("    ✓ feedback.json (empty — will grow from experience)")

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
