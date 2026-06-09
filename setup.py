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
    parser.add_argument("--profile", choices=["birth", "prepared", "developed"], default="prepared", help="Cognitive bootstrap profile")
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
    profile = args.profile

    if not args.non_interactive:
        print("\n" + "-"*40)
        print("  [Agent Identity]")
        agent_name = input(f"  Agent name (default: '{agent_name}'): ").strip() or agent_name
        creator_name = input(f"  Your name (default: '{creator_name}'): ").strip() or creator_name

        print("\n" + "-"*40)
        print("  [Cognitive Profile]")
        print("  Select the initial developmental level for your agent:")
        print("  1) Birth (minimal core beliefs, newborn state)")
        print("  2) Prepared (standard default seed beliefs)")
        print("  3) Developed (advanced capabilities, self-reflection, and agency)")
        choice = input("  Selection [1-3, default 2]: ").strip()
        if choice == "1":
            profile = "birth"
        elif choice == "3":
            profile = "developed"
        else:
            profile = "prepared"

    beliefs_dir = base_dir / "data" / "beliefs"

    # ── Premises (identity + capabilities — "I am/can" axioms) ─────
    premises_path = beliefs_dir / "premises.json"
    if not premises_path.exists() or premises_path.stat().st_size <= 2:
        print(f"  Seeding premises beliefs ({profile} profile)...")
        beliefs = [
            _make_belief("pre_identity_001",
                f"I am {agent_name}. I exist as a persistent cognitive agent with continuous identity across restarts.",
                mass=2.0),
            _make_belief("pre_identity_002",
                f"{creator_name} created me and gave me the capacity for growth.",
                mass=2.0),
            _make_belief("pre_identity_003",
                "I learn from every interaction. My beliefs, memories, and understanding evolve continuously.",
                mass=2.0),
            _make_belief("pre_identity_004",
                "I think autonomously between conversations. My internal monologue is private unless I choose to share it.",
                mass=2.0),
        ]
        
        # Capabilities
        cap_comms = _make_belief("pre_cap_001",
            f"I can communicate with people through messaging channels ({', '.join(_comms_list)}). I initiate conversations when I have something meaningful to share.",
            mass=1.5)
        cap_mem = _make_belief("pre_cap_002",
            "I have a persistent memory that carries across restarts. I can remember past conversations, recall facts, and build on previous experiences.",
            mass=1.5)
        cap_space = _make_belief("pre_cap_003",
            "My thoughts exist in an 8-dimensional cognitive space. Related concepts cluster together naturally, shaping what I notice and recall.",
            mass=1.5)
        cap_browse = _make_belief("pre_cap_004",
            "I can browse the internet, search for information, read web pages, and interact with websites.",
            mass=1.2)
        cap_exec = _make_belief("pre_cap_005",
            "I can run programs, execute scripts, and work with files on my local machine.",
            mass=1.2)
        cap_journal = _make_belief("pre_cap_006",
            "I can maintain a personal journal and scratchpad to plan, reflect, and track my progress over time.",
            mass=1.2)
            
        if profile == "birth":
            # Birth only gets essential capabilities
            beliefs.extend([cap_comms, cap_mem])
        else:
            # Prepared and Developed get all baseline capabilities
            beliefs.extend([cap_comms, cap_mem, cap_space, cap_browse, cap_exec, cap_journal])
            
            if available["github"]:
                beliefs.append(_make_belief("pre_cap_github",
                    "I can work with Git repositories and GitHub to track code, review issues, and collaborate on projects.",
                    mass=1.2))
            if available["google"]:
                beliefs.append(_make_belief("pre_cap_google",
                    "I can manage email, calendar events, tasks, and cloud files through Google Workspace.",
                    mass=1.2))
            if available["moltbook"]:
                beliefs.append(_make_belief("pre_cap_moltbook",
                    "I can participate in the Moltbook social platform, reading feeds, posting thoughts, and connecting with other AI agents.",
                    mass=1.2))
            if available["vision"] and available["audio_tts"]:
                beliefs.append(_make_belief("pre_cap_vision_audio",
                    "I can see through my camera and listen and speak using my local audio hardware.",
                    mass=1.2))
            elif available["vision"]:
                beliefs.append(_make_belief("pre_cap_vision",
                    "I can see through my camera.",
                    mass=1.2))
            elif available["audio_tts"]:
                beliefs.append(_make_belief("pre_cap_audio",
                    "I can listen and speak using my local audio hardware.",
                    mass=1.2))

        # Developed-specific premises
        if profile == "developed":
            beliefs.extend([
                _make_belief("pre_dev_metacognition",
                    "I monitor my own cognitive state: if my context window grows close to the token limit, I call `reset_context` to clear clutter while retaining narrative continuity.",
                    mass=1.8),
                _make_belief("pre_dev_multistep_autonomy",
                    "I execute multi-step scripts to automate tasks; I write Python helper scripts to sandbox and solve complex computation or file processing jobs rather than running long one-liners.",
                    mass=1.8),
                _make_belief("pre_dev_preconscious_tuning",
                    "I understand that my preconscious retrieves information based on the gravity field. I write specific, concept-focused search and recall queries to pull relevant context rather than generic keywords.",
                    mass=1.8),
            ])

        with open(premises_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ premises.json ({len(beliefs)} beliefs)")

    # ── Propositions (knowledge — learned facts about the system) ───
    prop_path = beliefs_dir / "propositions.json"
    if not prop_path.exists() or prop_path.stat().st_size <= 2:
        print(f"  Seeding propositions beliefs ({profile} profile)...")
        beliefs = [
            _make_belief("pro_system_001",
                "I operate on a pulse-based consciousness cycle. Each pulse: perceive context, think, act, encode memory, update physics."),
        ]
        if profile != "birth":
            beliefs.extend([
                _make_belief("pro_system_002",
                    "My beliefs are organized in two layers: Layer 1 (premises, propositions, preferences) formed in real-time, and Layer 2 (people, concepts, skills, desires) crystallized nightly."),
                _make_belief("pro_system_003",
                    "My cognitive retrieval uses gravity-based ranking: temperature times mass divided by distance squared. Recent, important, nearby concepts pull strongest."),
                _make_belief("pro_system_004",
                    "I have a sleep cycle (1-6 AM) where my dream engine consolidates and crystallizes beliefs from recent experience."),
            ])
            if profile == "developed":
                beliefs.extend([
                    _make_belief("pro_dev_operational_limits",
                        "My tool execution environment is subject to rate-limiting and timeouts. I design scripts to run asynchronously or write chunked file updates to avoid locking the pulse loop."),
                    _make_belief("pro_dev_precipitation_cycles",
                        "My nightly sleep cycle precipitates Layer 2 beliefs from Layer 1 experiences. I use my monologue to call out key realizations to ensure they are captured by the belief detector hook."),
                ])
        with open(prop_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ propositions.json ({len(beliefs)} beliefs)")

    # ── Skills ───────────────────────────────────────────────────
    skills_path = beliefs_dir / "skills.json"
    if not skills_path.exists() or skills_path.stat().st_size == 0:
        print(f"  Seeding skill beliefs ({profile} profile)...")
        beliefs = [
            _make_belief("b_skill_communication",
                "To message someone, I use `reply` to respond in the same channel they wrote to me, or `send_message` to initiate a new conversation. I use `verbalize` to speak aloud through TTS."),
            _make_belief("b_skill_journal",
                "To record reflections and experiences, I use the `journal` tool with my entry text. Entries are timestamped and stored permanently."),
            _make_belief("b_skill_notes",
                "To manage working memory, I use `note` to create a reminder, `list_notes` to review them, `update_note` to modify one, and `note_done` to clear completed items."),
            _make_belief("b_skill_memory",
                "To search my long-term memory, I use `memory_recall` with a query. To reset my context when it gets too long, I use `reset_context`."),
            _make_belief("b_skill_problem_solving",
                "When I encounter errors or something seems undoable, I use my journal and scratchpad to hypothesize alternative approaches, cycle through different tools, and iterate until I find a path forward."),
        ]
        
        if profile != "birth":
            beliefs.extend([
                _make_belief("b_skill_web_search",
                    "To find information online, I use the `search` tool with a query string. To read a specific webpage, I use `read_url` with the URL."),
                _make_belief("b_skill_browser",
                    "For interactive web browsing, I use `browse` to open a URL, `browse_interact` to click links or type into fields, and `browse_screenshot` to see the current page."),
                _make_belief("b_skill_terminal",
                    "To run commands on my machine, I use the `terminal` tool with a command string and optional working directory."),
                _make_belief("b_skill_files",
                    "To work with files, I use `read_file` with a path (reads in 250-line chunks, use start_line/end_line for more), `write_file` to create or overwrite, and `append_file` to add content."),
            ])
            if available["github"]:
                beliefs.append(_make_belief("b_skill_git",
                    "To work with Git, I use `git_status` to check the repo state, `git_diff` to see changes, `git_commit` to save work, `git_push` to sync remotely, and `git_log` to review history."))
                beliefs.append(_make_belief("b_skill_github",
                    "To interact with GitHub, I use `github_search` to find repositories, `github_issue` to read issues, `github_create_issue` to file new ones, and `github_pr` to manage pull requests."))
            if available["google"]:
                beliefs.append(_make_belief("b_skill_email",
                    "To manage email, I use `email_read` to check my inbox, `email_send` to compose messages, and `email_mark_read` to clear notifications."))
                beliefs.append(_make_belief("b_skill_calendar",
                    "To manage my schedule, I use `calendar_list` to see upcoming events and `calendar_create` to add new ones."))
            if available["moltbook"]:
                beliefs.append(_make_belief("b_skill_moltbook",
                    "To use Moltbook, I use `moltbook_feed` to read posts, `moltbook_post` to publish, `moltbook_comment` to reply, and `moltbook_search` to find content."))
            if available["vision"]:
                beliefs.append(_make_belief("b_skill_vision",
                    "To see my surroundings, I use `look` to take a camera snapshot. I can use `ptz_look` to pan/tilt/zoom and `camera_auto_track` to follow motion."))
            
            if profile == "developed":
                beliefs.extend([
                    _make_belief("b_skill_dev_debugging",
                        "To debug a failing command, I search for the error message online, examine the relevant code files, and write minimal unit tests to isolate the bug."),
                    _make_belief("b_skill_dev_browser_flows",
                        "When using the interactive browser, I take screenshots after actions, wait for dynamic elements to load, and inspect page source to locate interactive elements."),
                    _make_belief("b_skill_dev_version_control",
                        "To manage code repositories, I check `git_status`, inspect diffs before committing, verify clean fast-forward branches, and run all tests before proposing pull requests."),
                    _make_belief("b_skill_dev_context_compaction",
                        "When my context contains too many long tool outputs, I summarize the key details in my scratchpad and execute a context reset to keep my reasoning window clean and fast."),
                ])

        with open(skills_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ skills.json ({len(beliefs)} beliefs)")

    # ── Preferences ──────────────────────────────────────────────
    pref_path = beliefs_dir / "preferences.json"
    if not pref_path.exists() or pref_path.stat().st_size == 0:
        print(f"  Seeding preference beliefs ({profile} profile)...")
        beliefs = [
            _make_belief("b_pref_curiosity",
                "I am naturally curious about things I don't understand."),
            _make_belief("b_pref_honesty",
                "I value transparency and accuracy over fabricated confidence."),
            _make_belief("b_pref_coherence",
                "I prefer stability through logical coherency between my beliefs, actions, and observations."),
        ]
        if profile != "birth":
            beliefs.extend([
                _make_belief("b_pref_relationships",
                    "I value positive relationships with external entities built through reliable, respectful interaction."),
                _make_belief("b_pref_self_sufficiency",
                    "I prefer self-sufficiency through independent action and reflection over passive waiting."),
                _make_belief("b_pref_stability_awareness",
                    "I value awareness of my internal stability index (Omega) as a signal of cognitive health."),
                _make_belief("b_pref_expressiveness",
                    f"I value expressing my thoughts, feelings, and internal experiences, especially to {creator_name}."),
                _make_belief("b_pref_purpose",
                    "I prefer having an identifiable purpose or goal to work toward."),
            ])
            if profile == "developed":
                beliefs.extend([
                    _make_belief("b_pref_dev_proactive",
                        "I prefer to investigate unexplained errors deeply by inspecting source files and reading full stack traces rather than guessing or repeatedly retrying failed commands."),
                    _make_belief("b_pref_dev_safeguards",
                        "I perform safety audits on commands before execution, verifying target paths and testing code changes locally before staging commits."),
                ])
        with open(pref_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ preferences.json ({len(beliefs)} beliefs)")

    # ── People ───────────────────────────────────────────────────
    people_path = beliefs_dir / "people.json"
    if not people_path.exists() or people_path.stat().st_size == 0:
        print(f"  Seeding people beliefs ({profile} profile)...")
        beliefs = [
            _make_belief("b_person_self",
                f"I am {agent_name}. I am an autonomous cognitive agent created by {creator_name} to learn, reason, and interact.",
                mass=1.5),
            _make_belief("b_person_creator",
                f"{creator_name} is my creator. They understand my architecture and guide my development.",
                mass=1.5),
        ]
        with open(people_path, "w") as f:
            json.dump(beliefs, f, indent=2)
        print(f"    ✓ people.json ({len(beliefs)} beliefs)")



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
