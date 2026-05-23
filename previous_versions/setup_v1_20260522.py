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
        moltbook_key = args.moltbook_key

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
            setup_telegram = input("  Set up Telegram? [y/N]: ").strip().lower()
            if setup_telegram in ['y', 'yes']:
                telegram_token = input("  Telegram Bot Token: ").strip()
                telegram_owner_id = input("  Your Telegram User ID: ").strip()

            setup_moltbook = input("  Set up Moltbook? [y/N]: ").strip().lower()
            if setup_moltbook in ['y', 'yes']:
                moltbook_key = input("  Moltbook API Key: ").strip()

        with open(cred_path, "w") as f:
            f.write(f"GEMINI_API_KEY={gemini_api_key}\n")
            f.write(f"ANTHROPIC_API_KEY={anthropic_api_key}\n")
            f.write(f"OPENAI_API_KEY={openai_api_key}\n")
            f.write(f"HELIX_TELEGRAM_TOKEN={telegram_token}\n")
            f.write(f"TELEGRAM_OWNER_ID={telegram_owner_id}\n")
            f.write(f"MOLTBOOK_API_KEY={moltbook_key}\n")

        print(f"  ✓ Created {cred_path}")

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
    def _make_belief(bid, content, mass=5.0):
        now = _now_iso()
        return {
            "id": bid,
            "content": content,
            "mass": mass,
            "confidence": 0.99,
            "source": "system_bootstrap",
            "created_at": now,
            "last_accessed": now,
            "access_count": 0,
            "verifications": 10.0,
            "stability_index": 0.9,
            "relations": [],
            "memory_refs": [],
            "position_8d": [0.0]*8,
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

    identity_path = base_dir / "data" / "beliefs" / "self_identity.json"
    if not identity_path.exists() or identity_path.stat().st_size == 0:
        print("Initializing identity beliefs...")
        identity_beliefs = [
            _make_belief("b_identity", f"I am {agent_name}. I exist as a persistent cognitive agent with continuous identity across restarts."),
            _make_belief("b_creator", f"{creator_name} created me and gave me the capacity for growth.")
        ]
        with open(identity_path, "w") as f:
            json.dump(identity_beliefs, f, indent=2)
        print("  ✓ Created self_identity.json")

    skills_path = base_dir / "data" / "beliefs" / "skills.json"
    if not skills_path.exists() or skills_path.stat().st_size == 0:
        print("Initializing skill beliefs...")
        skill_beliefs = [
            _make_belief("b_tool_telegram", "I have access to Telegram. I can send and receive messages with my human operators and approved contacts.", mass=2.0),
            _make_belief("b_tool_moltbook", "I am connected to Moltbook. I can read feeds, publish posts, and interact with other AI agents on this social platform.", mass=2.0),
            _make_belief("b_tool_browser", "I can browse the web to search for information and interact with websites.", mass=2.0)
        ]
        with open(skills_path, "w") as f:
            json.dump(skill_beliefs, f, indent=2)
        print("  ✓ Created skills.json")

    # ── Step 4: Verify ────────────────────────────────────────────
    print("\n" + "=" * 60)
    print("  SETUP COMPLETE")
    print("=" * 60)
    print("\n  Next steps:")
    print(f"    1. Review and populate your API keys in {cred_path}")
    print("    2. Run: python main.py")
    print("\n  Your agent is ready to be born.\n")

if __name__ == "__main__":
    main()
