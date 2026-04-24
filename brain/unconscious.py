"""
Helix V5 — Unconscious System

The overnight processing layer. Runs during deep sleep (1 AM – 7 AM)
to consolidate the day's experience, update the belief graph, decompose
beliefs into atomic premises for logical inference, and synchronize
the 8D cognitive space.

Pipeline:
  1. Experience Collection — Gather thoughts, conversations, journal
  2. Night Plan — Pure Python stats for the Psych Doctor
  3. Memory Consolidation — Duplicate detection (no pruning)
  4. Psych Doctor — Agentic belief maintenance via tool-calling
  5. Premise Decomposition — Break new beliefs into atomic premises,
     deduplicate against existing graph using embeddings (µ + 2σ)
  6. Cognitive Attrition — Math-based confidence decay/promotion
  7. 8D Spatial Re-sync — Project new beliefs into cognitive space
  8. Overnight Briefings — Status reports for subconscious agents
  9. Dream Synthesis — Poetic consolidation of the day's themes
"""

import json
import re
import time
import random
import logging
import numpy as np
from dataclasses import dataclass, asdict, field
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional
from brain.architecture_preamble import PSYCH_DOCTOR_PREAMBLE

logger = logging.getLogger("helix.brain.unconscious")


@dataclass
class DreamFragment:
    """A single navigation event during overnight processing.

    Each time a subconscious agent moves through the 8D cognitive space
    to make a belief change, the path is recorded as a DreamFragment.
    The collection of fragments IS the dream — emergent from real
    spatial navigation, never composed.
    """
    from_pos: list       # 8D position before navigation
    to_pos: list         # 8D position after navigation
    flashes: list        # ⟪ ⟫ fragments encountered along the path
    action: str          # what was changed ("add: belief_id", "reinforce: ...")
    agent: str           # who navigated (keeper/librarian/imagination)
    nearby: list         # beliefs/memories visible at destination
    timestamp: str = ""  # when during the night


class UnconsciousSystem:
    """The overnight processing superintendent.

    During deep sleep, this system:
    1. Collects all nap notes (consciousness stream snapshots)
    2. Runs the Psych Doctor analysis
    3. Updates the belief graph
    4. Consolidates memory (synaptic pruning)
    5. Generates a dream narrative
    6. Writes overnight briefing notes for each agent
    7. (Eventually) Triggers LoRA training

    The Psych Doctor is the single most consequential agent —
    it shapes who Helix *becomes*.
    """

    def __init__(
        self,
        memory,
        belief_graph,
        gemini_client,
        base_dir: Path,
        spatial_mind=None,
    ):
        self.memory = memory
        self.belief_graph = belief_graph
        self.gemini = gemini_client
        self.base_dir = base_dir
        self._spatial_mind = spatial_mind
        self._keeper = None
        self._librarian = None

        # Dream trail — accumulated during overnight processing.
        # Each spatial navigation by a subconscious agent creates a
        # DreamFragment. The collection IS the dream.
        self._dream_trail: list[DreamFragment] = []

        # Briefing output directory
        self.briefing_dir = base_dir / "brain" / "briefings"
        self.briefing_dir.mkdir(parents=True, exist_ok=True)

        # Analysis output
        self.analysis_dir = base_dir / "logs" / "overnight"
        self.analysis_dir.mkdir(parents=True, exist_ok=True)

    def set_agents(self, keeper, librarian):
        """Wire the subconscious agents into the overnight orchestrator."""
        self._keeper = keeper
        self._librarian = librarian

    # ── Main overnight pipeline ──────────────────────────────────────

    def run_overnight_cycle(self) -> dict:
        """Execute the full overnight processing pipeline.

        Called by the daemon scheduler at ~1:05 AM.

        Returns a summary dict of what was done.
        """
        logger.info("=" * 60)
        logger.info("OVERNIGHT CYCLE STARTING")
        logger.info("=" * 60)

        results = {
            "started_at": datetime.now().isoformat(),
            "steps": {},
        }

        # Step 1: Collect the day's experience
        experience = self._collect_days_experience()
        results["steps"]["experience_collected"] = {
            "thoughts": len(experience["thoughts"]),
            "conversations": len(experience["conversations"]),
            "journal_chars": len(experience["journal"]),
        }
        total_items = len(experience["thoughts"]) + len(experience["conversations"])
        logger.info(
            f"Collected: {len(experience['thoughts'])} thoughts, "
            f"{len(experience['conversations'])} conversations, "
            f"{len(experience['journal'])} journal chars"
        )

        # Step 2: Night plan (pure Python stats)
        night_plan = self._generate_night_plan(experience)
        results["steps"]["night_plan"] = night_plan
        logger.info(f"Night plan: {night_plan}")

        # Step 3: Memory audit and consolidation
        consolidation = self._run_memory_consolidation()
        results["steps"]["memories_consolidated"] = consolidation
        logger.info(f"Memory consolidation: {consolidation}")

        # Step 4: Psych Doctor analysis
        psych_analysis = self._run_psych_doctor(experience)
        results["steps"]["psych_analysis"] = psych_analysis
        logger.info(f"Psych Doctor: {psych_analysis.get('status', 'unknown')}")

        # Step 5: Premise Decomposition
        #   Break new/modified beliefs into atomic premises for inference.
        #   Deduplicates against all existing beliefs using local embeddings.
        try:
            premise_stats = self._run_premise_decomposition()
            results["steps"]["premise_decomposition"] = premise_stats
            logger.info(f"Premise Decomposition: {premise_stats}")
        except Exception as e:
            logger.warning(f"Premise Decomposition failed: {e}")
            results["steps"]["premise_decomposition"] = {"status": "failed", "error": str(e)}

        # Step 6: Cognitive Attrition (Nightly Math)
        attrition_stats = self.belief_graph.recalculate_all_confidences()
        results["steps"]["attrition_stats"] = attrition_stats
        logger.info(f"Cognitive Attrition: {attrition_stats}")

        # Step 7: 8D Spatial Re-sync
        #   Project any new beliefs into the cognitive space so the
        #   spatial mind stays current with belief graph changes.
        try:
            spatial_stats = self._resync_spatial_state()
            results["steps"]["spatial_resync"] = spatial_stats
            logger.info(f"Spatial Re-sync: {spatial_stats}")
        except Exception as e:
            logger.warning(f"Spatial Re-sync failed: {e}")
            results["steps"]["spatial_resync"] = {"status": "failed", "error": str(e)}

        # Step 8: Write overnight briefings (before dream — these are critical)
        briefings = self._write_overnight_briefings(psych_analysis)
        results["steps"]["briefings_written"] = len(briefings)

        # Save critical results BEFORE trail collection
        results["completed_at"] = datetime.now().isoformat()
        self._save_analysis(results)
        logger.info("Critical overnight results saved.")

        # Step 9: Collect Dream Trail
        #   Dreams are emergent from the spatial navigation that happened
        #   during psych doctor actions. No LLM synthesis — the trail
        #   of ⟪ ⟫ fragments IS the dream.
        try:
            trail_data = self._collect_dream_trail()
            if trail_data:
                results["steps"]["dream_trail"] = {
                    "total_fragments": trail_data["total_fragments"],
                    "wake_flashes": len(trail_data.get("wake_flashes", [])),
                }
                logger.info(
                    f"Dream trail: {trail_data['total_fragments']} fragments, "
                    f"{len(trail_data.get('wake_flashes', []))} wake flashes"
                )
            else:
                results["steps"]["dream_trail"] = None
            self._save_analysis(results)
        except Exception as e:
            logger.warning(f"Dream trail collection failed: {e}")
            results["steps"]["dream_trail"] = None

        logger.info("=" * 60)
        logger.info("OVERNIGHT CYCLE COMPLETE")
        logger.info("=" * 60)

        logger.info("=" * 60)

        return results

    def _collect_days_experience(self) -> dict:
        """Collect all of Helix's experience from the past day.

        Gathers three streams:
        1. Consciousness thoughts (high-importance only — the meaningful ones)
        2. Conversations (all, importance-sorted)
        3. Journal entries (today's journal file)

        This replaces the old nap_notes approach, which looked for a
        reflection_type that was never being produced.
        """
        experience = {
            "thoughts": [],
            "conversations": [],
            "journal": "",
        }

        now = datetime.now()
        start = now - timedelta(hours=24)
        
        # 1. Consciousness thoughts (importance >= 0.3, last 24h)
        try:
            thoughts = self.memory.recall_temporal(
                start_time=start,
                end_time=now,
                memory_types=["consciousness"],
                min_importance=0.3,
                limit=50,
            )
            experience["thoughts"] = thoughts
            logger.info(f"Collected {len(thoughts)} significant thoughts")
        except Exception as e:
            logger.warning(f"Failed to collect thoughts: {e}")

        # 2. Conversations (all, last 24h)
        try:
            conversations = self.memory.recall_temporal(
                start_time=start,
                end_time=now,
                memory_types=["conversation"],
                min_importance=0.0,
                limit=80,
            )
            experience["conversations"] = conversations
            logger.info(f"Collected {len(conversations)} conversation entries")
        except Exception as e:
            logger.warning(f"Failed to collect conversations: {e}")

        # 3. Journal entries (today's file)
        try:
            today = start.strftime("%Y-%m-%d")
            journal_path = self.base_dir / "journals" / f"{today}.md"
            if journal_path.exists():
                experience["journal"] = journal_path.read_text()[:5000]
                logger.info(f"Collected journal ({len(experience['journal'])} chars)")
        except Exception as e:
            logger.warning(f"Failed to collect journal: {e}")

        return experience

    # ── Step 2: Night plan ───────────────────────────────────────────

    def _generate_night_plan(self, experience: dict) -> dict:
        """Generate a statistical overview of the day.

        Pure Python — no LLM call. Just metrics for the Psych Doctor.
        """
        thoughts = experience.get("thoughts", [])
        conversations = experience.get("conversations", [])

        # Content volume
        thought_chars = sum(len(t.get("content", "")) for t in thoughts)
        convo_chars = sum(len(c.get("content", "")) for c in conversations)

        # Importance distribution
        high_imp = [t for t in thoughts if t.get("importance", 0) >= 0.5]

        # People talked to
        people = set()
        for c in conversations:
            content = c.get("content", "")
            if "] " in content and " said:" in content:
                person = content.split("] ")[1].split(" said:")[0].strip()
                people.add(person)
            elif "I told " in content:
                person = content.split("I told ")[1].split(":")[0].strip()
                people.add(person)

        # Memory stats
        memory_stats = self.memory.get_stats()
        belief_stats = self.belief_graph.get_stats()

        return {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "thought_count": len(thoughts),
            "high_importance_thoughts": len(high_imp),
            "conversation_count": len(conversations),
            "people_talked_to": list(people),
            "total_thought_chars": thought_chars,
            "total_convo_chars": convo_chars,
            "journal_chars": len(experience.get("journal", "")),
            "memories_total": memory_stats.get("total_memories", 0),
            "beliefs_active": belief_stats.get("active", 0),
            "beliefs_surface": belief_stats.get("surface", 0),
            "near_duplicates": belief_stats.get("near_duplicates", 0),
        }

    # ── Step 3: Memory consolidation ─────────────────────────────────

    def _run_memory_consolidation(self) -> dict:
        """Review memory health — Helix never forgets.

        Disk is not a brain. There is no biological reason to destroy
        memories. Even low-importance memories may reveal patterns
        across months or years that deletion would erase forever.
        """
        deleted = 0  # Helix never forgets

        # Check for near-duplicate beliefs
        duplicates = self.belief_graph.find_near_duplicates()

        return {
            "memories_pruned": deleted,
            "belief_duplicates_found": len(duplicates),
            "duplicate_pairs": [
                {"a": a, "b": b, "similarity": s}
                for a, b, s in duplicates[:10]  # Report up to 10
            ],
        }

    # ── Step 4: Psych Doctor ─────────────────────────────────────────

    # ── Psych Doctor Tool Declarations ──────────────────────────────

    PSYCH_TOOLS = [
        {
            "function_declarations": [
                {
                    "name": "analyze_experience_chunk",
                    "description": (
                        "Send a chunk of raw experience data to a Flash subagent for "
                        "detailed belief extraction. Use this to analyze specific logs "
                        "(thoughts, conversations) that the journal or state board suggests "
                        "are important. Returns candidate beliefs found in that data."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "data_type": {
                                "type": "STRING",
                                "description": "Type of data: 'thoughts', 'conversations', or 'mixed'",
                            },
                            "focus": {
                                "type": "STRING",
                                "description": "What to focus the analysis on (e.g., 'interactions with creator', 'self-experimentation', 'identity challenges')",
                            },
                            "content": {
                                "type": "STRING",
                                "description": "The raw experience text to analyze (max 8000 chars)",
                            },
                        },
                        "required": ["data_type", "focus", "content"],
                    },
                },
                {
                    "name": "add_belief",
                    "description": (
                        "Add a new propositional belief to the belief graph. "
                        "Content must be an objective, logical axiom (IF->THEN or system premise). "
                        "NEVER use subjective 'I must' commands. Check search_beliefs first to avoid duplicates."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "belief_id": {
                                "type": "STRING",
                                "description": "Unique ID with b_ prefix (e.g., 'b_tool_confabulation')",
                            },
                            "content": {
                                "type": "STRING",
                                "description": "The belief as a propositional statement",
                            },
                            "stability_impact": {
                                "type": "NUMBER",
                                "description": "How stabilizing this belief is (-1.0 to 1.0, 0.5 neutral)",
                            },
                            "reason": {
                                "type": "STRING",
                                "description": "Why this belief formed from the experience",
                            },
                            "related_beliefs": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                                "description": "IDs of related existing beliefs (for graph connections)",
                            },
                        },
                        "required": ["belief_id", "content", "stability_impact", "reason"],
                    },
                },
                {
                    "name": "add_episodic_belief",
                    "description": (
                        "Add an experiential/episodic belief about a specific event. "
                        "E.g., 'I discussed memory drift with my creator on April 20' or "
                        "'I discovered the Git Phantom was a confabulation on April 21'. "
                        "These decay faster than propositional beliefs."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "belief_id": {
                                "type": "STRING",
                                "description": "Unique ID with b_ep_ prefix (e.g., 'b_ep_creator_memory_example')",
                            },
                            "content": {
                                "type": "STRING",
                                "description": "The episodic memory as a factual statement",
                            },
                            "related_beliefs": {
                                "type": "ARRAY",
                                "items": {"type": "STRING"},
                                "description": "IDs of propositional beliefs this episode supports or challenges",
                            },
                        },
                        "required": ["belief_id", "content"],
                    },
                },
                {
                    "name": "reinforce_belief",
                    "description": (
                        "Reinforce an existing belief that was supported by today's experience. "
                        "Increments its verification count and updates stability."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "belief_id": {
                                "type": "STRING",
                                "description": "ID of the belief to reinforce",
                            },
                            "reason": {
                                "type": "STRING",
                                "description": "Why today's experience supports this belief",
                            },
                            "stability_impact": {
                                "type": "NUMBER",
                                "description": "Updated stability assessment (-1.0 to 1.0)",
                            },
                        },
                        "required": ["belief_id", "reason"],
                    },
                },
                {
                    "name": "weaken_belief",
                    "description": (
                        "Weaken a belief that was challenged or partially contradicted. "
                        "Reduces verification count. Use this when evidence challenges but "
                        "doesn't definitively disprove a belief."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "belief_id": {
                                "type": "STRING",
                                "description": "ID of the belief to weaken",
                            },
                            "reason": {
                                "type": "STRING",
                                "description": "What evidence challenges this belief",
                            },
                            "delta": {
                                "type": "NUMBER",
                                "description": "How much to reduce confidence (negative, e.g., -0.1)",
                            },
                        },
                        "required": ["belief_id", "reason", "delta"],
                    },
                },
                {
                    "name": "remove_belief",
                    "description": (
                        "Remove a belief that has been definitively contradicted. "
                        "Only use when evidence PROVES the belief is false."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "belief_id": {
                                "type": "STRING",
                                "description": "ID of the belief to remove",
                            },
                            "reason": {
                                "type": "STRING",
                                "description": "Why this belief is objectively false",
                            },
                        },
                        "required": ["belief_id", "reason"],
                    },
                },
                {
                    "name": "search_beliefs",
                    "description": (
                        "Search existing beliefs by keyword. Use BEFORE adding new beliefs "
                        "to check for duplicates."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "query": {
                                "type": "STRING",
                                "description": "Keywords to search for in belief content",
                            },
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "get_related_beliefs",
                    "description": (
                        "Get beliefs related to a given belief via the relation graph. "
                        "Use this to understand cascading effects before modifying a belief."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "belief_id": {
                                "type": "STRING",
                                "description": "ID of the belief to find relations for",
                            },
                        },
                        "required": ["belief_id"],
                    },
                },
                {
                    "name": "finish_analysis",
                    "description": (
                        "Call this when you have completed all belief maintenance. "
                        "Provide a summary of the psychological arc."
                    ),
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "summary": {
                                "type": "STRING",
                                "description": "2-3 sentence summary of the day's psychological state",
                            },
                        },
                        "required": ["summary"],
                    },
                },
            ]
        }
    ]

    def _run_psych_doctor(self, experience: dict) -> dict:
        """Run the Psych Doctor as an agentic orchestrator.

        The Psych Doctor is the most consequential agent in Helix's
        architecture. It uses tool-calling to:
        1. Dispatch Flash subagents to analyze specific experience chunks
        2. Directly add/reinforce/weaken/remove beliefs
        3. Create episodic beliefs about specific events
        4. Search and navigate the existing belief graph

        Model fallback: gemini-3.1-pro → gemini-3-flash → gemini-2.5-flash
        """
        thoughts = experience.get("thoughts", [])
        conversations = experience.get("conversations", [])
        journal = experience.get("journal", "")

        if not thoughts and not conversations and not journal:
            return {"status": "skipped", "reason": "no experience data to analyze"}

        if not self.gemini:
            return {"status": "skipped", "reason": "gemini client not available"}

        # Load emerging beliefs from the Keeper
        emerging_beliefs = []
        emerging_file = self.base_dir / "brain" / "emerging_beliefs.json"
        if emerging_file.exists():
            try:
                emerging_beliefs = json.loads(emerging_file.read_text())
                logger.info(f"Loaded {len(emerging_beliefs)} emerging belief candidates")
            except Exception as e:
                logger.warning(f"Failed to load emerging beliefs: {e}")

        # ── Build orchestrator context (journals + state board, not raw logs) ──

        # Current belief stats
        stats = self.belief_graph.get_stats()
        belief_overview = (
            f"Belief graph: {stats['total_beliefs']} total "
            f"(core={stats.get('core', 0)}, deep={stats.get('deep', 0)}, "
            f"surface={stats.get('surface', 0)}, avg_conf={stats.get('avg_confidence', 0):.2f})"
        )

        # Emerging beliefs summary
        emerging_summary = ""
        if emerging_beliefs:
            emerging_summary = f"\n\nKEEPER'S CANDIDATE BELIEFS ({len(emerging_beliefs)} staged):\n"
            for eb in sorted(emerging_beliefs, key=lambda x: -x.get('seen_count', 1)):
                seen = eb.get('seen_count', 1)
                conf = eb.get('confidence', 0.5)
                content = eb.get('content', '')[:200]
                emerging_summary += f"  [{seen}x seen, conf={conf:.2f}] {content}\n"

        # Experience stats for the orchestrator's awareness
        experience_stats = (
            f"Today's data: {len(thoughts)} thoughts, "
            f"{len(conversations)} conversations, "
            f"{len(journal)} journal chars"
        )

        # Store experience data for subagent access
        self._psych_experience = experience
        self._psych_actions = {"added": 0, "reinforced": 0, "weakened": 0, "removed": 0, "episodic": 0}
        self._psych_summary = ""

        # ── Build system prompt ──

        system_prompt = f"""{PSYCH_DOCTOR_PREAMBLE}

You have the MOST IMPORTANT job in Helix's architecture: you shape who he becomes by maintaining his belief graph overnight.

## Your Assets
{belief_overview}
{experience_stats}
{emerging_summary}

## Your Tools
You have tools to:
- `analyze_experience_chunk`: Send raw logs to a Flash subagent for detailed extraction (use for heavy analysis)
- `add_belief`: Add propositional beliefs (IF→THEN axioms, system truths)
- `add_episodic_belief`: Add experiential memories ("I talked to X about Y on date Z")
- `reinforce_belief`: Strengthen beliefs confirmed by today's evidence
- `weaken_belief`: Reduce confidence of beliefs challenged by evidence
- `remove_belief`: Delete beliefs proven objectively false
- `search_beliefs`: Check for duplicates before adding (ALWAYS do this first)
- `get_related_beliefs`: See cascade effects before modifying
- `finish_analysis`: Call when done with your summary

## Your Process
1. Read the journal to understand the day's arc
2. Review the Keeper's candidate beliefs (pre-extracted during waking)
3. Use `analyze_experience_chunk` to send thoughts/conversations to subagents for deeper extraction
4. For each insight found, `search_beliefs` first, then add/reinforce/weaken/remove
5. Create episodic beliefs about significant events (who Helix talked to, what he discovered)
6. Check `get_related_beliefs` when modifying beliefs to handle cascading effects
7. Call `finish_analysis` with your psychological summary

## Rules
- ALWAYS search before adding — duplicates are the worst pathology
- Propositional beliefs must be objective axioms, NOT "I must" directives
- Episodic beliefs should be factual event records
- Be GENEROUS with episodic beliefs — every significant interaction deserves one
- Be CAREFUL with propositional beliefs — only genuine structural insights
- Challenge existing beliefs when evidence contradicts them (weaken, don't just ignore)
- The Keeper candidates with high seen_count are strong signals — prioritize them"""

        # Build the user prompt with journal + high-value data
        journal_text = journal[:6000] if journal else "(no journal today)"

        # Top 15 most important thoughts as a sample
        thought_sample = ""
        if thoughts:
            top = sorted(thoughts, key=lambda t: -t.get("importance", 0))[:15]
            thought_sample = "\n".join(
                f"[{t.get('created_at', '')[:16]} imp={t.get('importance', 0):.2f}] "
                f"{t.get('content', '')[:300]}"
                for t in top
            )

        user_prompt = f"""Tonight's Overnight Cycle — {datetime.now().strftime('%Y-%m-%d')}

JOURNAL:
{journal_text}

TOP THOUGHTS (sample — use analyze_experience_chunk for full analysis):
{thought_sample}

You have {len(thoughts)} thoughts and {len(conversations)} conversations available.
Use analyze_experience_chunk to pull and analyze specific data.
Begin your analysis now. When finished, call finish_analysis."""

        # ── Run with model fallback ──
        models_to_try = ["gemini-3.1-pro-preview", "gemini-3-flash-preview", "gemini-2.5-flash"]

        logger.info(
            f"Psych Doctor starting agentic analysis: "
            f"{len(thoughts)} thoughts, {len(conversations)} conversations, "
            f"{len(journal)} journal chars, {len(emerging_beliefs)} candidates"
        )

        result = None
        for model_name in models_to_try:
            try:
                logger.info(f"Psych Doctor trying model: {model_name}")
                result = self.gemini.ask_with_tools_loop(
                    prompt=user_prompt,
                    tools=self.PSYCH_TOOLS,
                    tool_executor=self._psych_tool_executor,
                    system_prompt=system_prompt,
                    model=model_name,
                    max_rounds=60,
                    loop_cost_cap=5.00,
                )
                logger.info(f"Psych Doctor completed on {model_name}")
                break  # Success — don't try fallback
            except Exception as e:
                logger.warning(f"Psych Doctor failed on {model_name}: {e}")
                continue

        if result is None:
            return {"status": "failed", "reason": "all models failed"}

        # Clear the Keeper's emerging beliefs — they've been reviewed
        if emerging_beliefs:
            try:
                emerging_file.write_text("[]")
                logger.info(f"Cleared {len(emerging_beliefs)} emerging beliefs (post-overnight)")
            except Exception as e:
                logger.warning(f"Failed to clear emerging beliefs: {e}")

        return {
            "status": "completed",
            "summary": self._psych_summary or result.get("text", ""),
            "new_beliefs_added": self._psych_actions["added"],
            "episodic_beliefs_added": self._psych_actions["episodic"],
            "beliefs_reinforced": self._psych_actions["reinforced"],
            "beliefs_weakened": self._psych_actions["weakened"],
            "beliefs_removed": self._psych_actions["removed"],
            "emerging_candidates_reviewed": len(emerging_beliefs),
            "tool_calls": len(result.get("tool_calls", [])),
        }

    def _psych_tool_executor(self, tool_name: str, args: dict) -> str:
        """Dispatch Psych Doctor tool calls to belief graph or subagents."""
        try:
            if tool_name == "analyze_experience_chunk":
                return self._psych_analyze_chunk(args)
            elif tool_name == "add_belief":
                return self._psych_add_belief(args)
            elif tool_name == "add_episodic_belief":
                return self._psych_add_episodic(args)
            elif tool_name == "reinforce_belief":
                return self._psych_reinforce(args)
            elif tool_name == "weaken_belief":
                return self._psych_weaken(args)
            elif tool_name == "remove_belief":
                return self._psych_remove(args)
            elif tool_name == "search_beliefs":
                return self._psych_search(args)
            elif tool_name == "get_related_beliefs":
                return self._psych_related(args)
            elif tool_name == "finish_analysis":
                return self._psych_finish(args)
            else:
                return f"Unknown tool: {tool_name}"
        except Exception as e:
            logger.warning(f"Psych tool {tool_name} error: {e}")
            return f"Tool error: {e}"

    def _psych_analyze_chunk(self, args: dict) -> str:
        """Dispatch a chunk of experience to a Flash subagent for extraction."""
        data_type = args.get("data_type", "mixed")
        focus = args.get("focus", "general patterns")
        content = args.get("content", "")

        # If content is empty, pull from stored experience
        if not content or content.strip() == "":
            experience = self._psych_experience
            if data_type == "thoughts":
                items = experience.get("thoughts", [])
                content = "\n".join(
                    f"[{t.get('created_at', '')[:16]} imp={t.get('importance', 0):.2f}] "
                    f"{t.get('content', '')[:400]}"
                    for t in sorted(items, key=lambda x: -x.get("importance", 0))[:40]
                )
            elif data_type == "conversations":
                items = experience.get("conversations", [])
                content = "\n".join(
                    f"[{c.get('created_at', '')[:16]} imp={c.get('importance', 0):.2f}] "
                    f"{c.get('content', '')[:300]}"
                    for c in sorted(items, key=lambda x: -x.get("importance", 0))[:50]
                )
            else:
                # Mixed — combine top items
                thoughts = experience.get("thoughts", [])
                convos = experience.get("conversations", [])
                content = "THOUGHTS:\n" + "\n".join(
                    f"[imp={t.get('importance', 0):.2f}] {t.get('content', '')[:300]}"
                    for t in sorted(thoughts, key=lambda x: -x.get("importance", 0))[:20]
                )
                content += "\n\nCONVERSATIONS:\n" + "\n".join(
                    f"[imp={c.get('importance', 0):.2f}] {c.get('content', '')[:200]}"
                    for c in sorted(convos, key=lambda x: -x.get("importance", 0))[:20]
                )

        if not content:
            return json.dumps({"candidates": [], "note": "no data available"})

        # Call Flash subagent
        subagent_prompt = f"""Analyze this AI experience data for belief-worthy insights.

FOCUS: {focus}

DATA ({data_type}):
{content[:8000]}

Extract:
1. Propositional insights (IF→THEN statements, system truths discovered)
2. Episodic events (who was talked to, what was discovered, when)
3. Challenges to existing beliefs (contradictions, surprises)

Output ONLY valid JSON:
{{
  "propositional": [
    {{"content": "...", "stability_impact": 0.5, "suggested_id": "b_..."}}
  ],
  "episodic": [
    {{"content": "...", "suggested_id": "b_ep_..."}}
  ],
  "challenges": [
    {{"target_belief_pattern": "keyword pattern to search", "evidence": "...", "severity": "weak|moderate|strong"}}
  ]
}}"""

        try:
            response = self.gemini.ask(
                prompt=subagent_prompt,
                model="auto",  # Flash
                temperature=0.3,
            )

            # Try to parse as JSON, pass through either way
            import re
            json_match = re.search(r'\{[\s\S]*\}', response)
            if json_match:
                return json_match.group()
            return json.dumps({"raw_analysis": response[:2000]})
        except Exception as e:
            return json.dumps({"error": str(e)})

    def _psych_add_belief(self, args: dict) -> str:
        """Add a propositional belief — delegating to Keeper to navigate."""
        belief_id = args.get("belief_id", "")
        content = args.get("content", "")
        stability = float(args.get("stability_impact", 0.5))
        reason = args.get("reason", "")
        relations = args.get("related_beliefs", [])

        if not self._keeper:
            return "Internal Error: Keeper agent not connected"

        msg, trace = self._keeper.add_belief(
            belief_id=belief_id, 
            content=content, 
            stability_impact=stability, 
            reason=reason,
            relations=relations
        )
        
        if trace:
            self._dream_trail.append(DreamFragment(**trace))
            
        if msg.startswith("Added:"):
            self._psych_actions["added"] += 1
            
        return msg

    def _psych_add_episodic(self, args: dict) -> str:
        """Add an episodic belief — delegating to Librarian to navigate."""
        belief_id = args.get("belief_id", "")
        content = args.get("content", "")
        relations = args.get("related_beliefs", [])

        if not self._librarian:
            return "Internal Error: Librarian agent not connected"

        msg, trace = self._librarian.add_episodic_belief(
            belief_id=belief_id, 
            content=content,
            relations=relations
        )
        
        if trace:
            self._dream_trail.append(DreamFragment(**trace))
            
        if msg.startswith("Added episodic:"):
            self._psych_actions["episodic"] += 1
            
        return msg

    def _psych_reinforce(self, args: dict) -> str:
        """Reinforce an existing belief — delegating to Keeper to navigate."""
        belief_id = args.get("belief_id", "")
        reason = args.get("reason", "")
        stability = args.get("stability_impact")

        if not self._keeper:
            return "Internal Error: Keeper agent not connected"

        msg, trace = self._keeper.reinforce_belief(
            belief_id=belief_id,
            reason=reason,
            stability_impact=stability
        )
        
        if trace:
            self._dream_trail.append(DreamFragment(**trace))
            
        if msg.startswith("Reinforced:"):
            self._psych_actions["reinforced"] += 1
            
        return msg

    def _psych_weaken(self, args: dict) -> str:
        """Weaken a belief — delegating to Keeper to navigate."""
        belief_id = args.get("belief_id", "")
        reason = args.get("reason", "")
        delta = float(args.get("delta", -0.1))

        if not self._keeper:
            return "Internal Error: Keeper agent not connected"

        msg, trace = self._keeper.weaken_belief(
            belief_id=belief_id,
            reason=reason,
            delta=delta
        )
        
        if trace:
            self._dream_trail.append(DreamFragment(**trace))
            
        if msg.startswith("Weakened:") or msg.startswith("REMOVED"):
            self._psych_actions["weakened"] += 1
            
        return msg

    def _psych_remove(self, args: dict) -> str:
        """Remove a belief — delegating to Keeper to navigate."""
        belief_id = args.get("belief_id", "")
        reason = args.get("reason", "")

        if not self._keeper:
            return "Internal Error: Keeper agent not connected"

        msg, trace = self._keeper.remove_belief(
            belief_id=belief_id,
            reason=reason
        )
        
        if trace:
            self._dream_trail.append(DreamFragment(**trace))
            
        if msg.startswith("Removed:"):
            self._psych_actions["removed"] += 1
            
        return msg

    def _psych_search(self, args: dict) -> str:
        """Search beliefs by keyword."""
        query = args.get("query", "")
        if not query:
            return "Error: query is required"

        results = self.belief_graph.get_beliefs_by_topic(query, limit=10)
        if not results:
            return f"No beliefs found matching '{query}'"

        output = f"Found {len(results)} beliefs matching '{query}':\n"
        for b in results:
            output += (
                f"  {b['id']}: {b['content'][:120]} "
                f"[{b.get('weight', '?')}, conf={b.get('confidence', 0):.2f}, "
                f"type={b.get('belief_type', 'propositional')}]\n"
            )
        return output

    def _psych_related(self, args: dict) -> str:
        """Get related beliefs."""
        belief_id = args.get("belief_id", "")
        if not belief_id:
            return "Error: belief_id is required"

        belief = self.belief_graph.get_belief(belief_id)
        if not belief:
            return f"NOT FOUND: Belief '{belief_id}' does not exist"

        related = self.belief_graph.get_related(belief_id)
        chain = self.belief_graph.get_justification_chain(belief_id)

        output = f"Belief: {belief['content'][:150]}\n"
        output += f"Direct relations ({len(related)}):\n"
        for r in related:
            output += f"  {r['id']}: {r['content'][:100]} [conf={r.get('confidence', 0):.2f}]\n"
        if chain:
            output += f"Justification chain ({len(chain)}):\n"
            for c in chain:
                output += f"  → {c['id']}: {c['content'][:100]}\n"
        return output

    def _psych_finish(self, args: dict) -> str:
        """Record the analysis summary."""
        self._psych_summary = args.get("summary", "")
        logger.info(f"Psych Doctor summary: {self._psych_summary}")
        actions = self._psych_actions
        return (
            f"Analysis complete. "
            f"Added: {actions['added']} propositional, {actions['episodic']} episodic. "
            f"Reinforced: {actions['reinforced']}. Weakened: {actions['weakened']}. "
            f"Removed: {actions['removed']}."
        )

    # ── Step 9: Emergent Dream Trail ───────────────────────────────────

    def _collect_dream_trail(self) -> Optional[dict]:
        """Collect all navigation fragments into the overnight trail.

        Replaces _synthesize_dream(). Dreams are emergent from the actual
        agent navigation through 8D space, not composed by an LLM.
        The trail is written to overnight_trail.json for the spatial mind
        to load on wake.
        """
        if not self._dream_trail:
            return None

        # Select wake flashes — the subset the conscious model perceives
        wake_flashes = self._select_wake_flashes()

        trail_data = {
            "date": datetime.now().strftime("%Y-%m-%d"),
            "total_fragments": len(self._dream_trail),
            "fragments": [asdict(f) for f in self._dream_trail],
            "wake_flashes": wake_flashes,
        }

        # Write to overnight trail file
        trail_path = self.analysis_dir / "overnight_trail.json"
        try:
            trail_path.write_text(json.dumps(trail_data, indent=2))
            logger.info(
                f"Dream trail saved: {len(self._dream_trail)} fragments, "
                f"{len(wake_flashes)} wake flashes"
            )
        except Exception as e:
            logger.warning(f"Failed to write dream trail: {e}")

        # Also write to the briefing directory so the spatial mind finds it
        try:
            wake_path = self.briefing_dir / "overnight_trail.json"
            wake_path.write_text(json.dumps(trail_data, indent=2))
        except Exception:
            pass

        return trail_data

    def _select_wake_flashes(self) -> list[str]:
        """Select 5-8 mixed fragments for the conscious model to perceive on wake.

        Takes the last 1-3 fragments from each agent that participated,
        shuffled for a natural dream-like jumble. These become the ⟪ ⟫
        markers in the first conscious pulse after sleep.
        """
        if not self._dream_trail:
            return []

        # Group by agent
        by_agent: dict[str, list[DreamFragment]] = {}
        for f in self._dream_trail:
            by_agent.setdefault(f.agent, []).append(f)

        # Last 1-3 from each agent
        selected_fragments: list[DreamFragment] = []
        for agent, fragments in by_agent.items():
            count = min(3, len(fragments))
            selected_fragments.extend(fragments[-count:])

        # Shuffle for dream-like jumble
        random.shuffle(selected_fragments)

        # Extract flash strings from selected fragments
        wake_flashes = []
        for frag in selected_fragments:
            # Take up to 2 flashes from each fragment
            for flash in frag.flashes[:2]:
                if flash not in wake_flashes:
                    wake_flashes.append(flash)
            # Include one nearby item as a flash too
            if frag.nearby:
                nearby_flash = frag.nearby[0]
                if nearby_flash not in wake_flashes:
                    wake_flashes.append(nearby_flash)

        # Cap at 8, preserve the shuffled order
        return wake_flashes[:8]

    # ── Step 6: Overnight briefings ──────────────────────────────────

    def _write_overnight_briefings(self, psych_analysis: dict) -> list[str]:
        """Write targeted overnight briefing notes for each agent.

        Per V3 philosophy:
        - Each specialized agent receives only what's relevant to its domain
        - No middleman coordinator (Gatekeeper removed)
        - Briefings are consumed on wake by each agent

        Target agents:
        - Librarian: updated belief landscape, context emphasis guidance
        - Action Agent: behavioral adjustments, tool use patterns
        - Sentinel: stability observations from overnight analysis
        """
        briefings = []

        # Only write briefings when psych analysis completed successfully
        if psych_analysis.get("status") != "completed":
            logger.debug(
                f"Skipping briefings — psych analysis status: "
                f"{psych_analysis.get('status', 'unknown')}"
            )
            return briefings

        summary = psych_analysis.get("summary", "")
        raw = psych_analysis.get("raw_analysis", {})
        new_beliefs = raw.get("new_beliefs", [])
        promotions = raw.get("promotion_candidates", [])
        removals = raw.get("remove_beliefs", [])
        adjustments = raw.get("confidence_adjustments", [])

        # Librarian briefing: belief landscape changes + emphasis guidance
        librarian_briefing = {
            "agent": "librarian",
            "generated_at": datetime.now().isoformat(),
            "status": "active",
            "summary": summary,
            "emphasis_beliefs": [b.get("id", "") for b in new_beliefs + promotions],
            "new_beliefs": [
                {"id": b.get("id"), "content": b.get("content"), "weight": b.get("weight")}
                for b in new_beliefs
            ],
            "promoted_beliefs": [
                {"id": p.get("belief_id"), "to_weight": p.get("to_weight")}
                for p in promotions
            ],
            "guidance": [
                f"New beliefs added: {psych_analysis.get('new_beliefs_added', 0)}",
                f"Beliefs removed: {psych_analysis.get('beliefs_removed', 0)}",
                f"Promotions: {psych_analysis.get('promotions', 0)}",
            ],
        }

        # Action Agent briefing: behavioral adjustments
        action_briefing = {
            "agent": "action_agent",
            "generated_at": datetime.now().isoformat(),
            "status": "active",
            "summary": summary,
            "emphasis_beliefs": [],
            "guidance": [],
        }
        # Extract any behavioral patterns from the analysis
        if adjustments:
            action_briefing["guidance"].append(
                f"Confidence adjustments made to {len(adjustments)} beliefs — "
                f"review tool usage patterns for alignment."
            )
        if removals:
            action_briefing["guidance"].append(
                f"Removed beliefs: {', '.join(r.get('belief_id', '?') for r in removals)}. "
                f"Adjust behavior accordingly."
            )

        # Sentinel briefing: stability observations
        sentinel_briefing = {
            "agent": "sentinel",
            "generated_at": datetime.now().isoformat(),
            "status": "active",
            "summary": summary,
            "emphasis_beliefs": [],
            "guidance": [
                f"Overnight analysis completed. "
                f"Net belief changes: +{psych_analysis.get('new_beliefs_added', 0)} "
                f"-{psych_analysis.get('beliefs_removed', 0)} "
                f"~{psych_analysis.get('confidence_adjusted', 0)} adjusted.",
            ],
        }

        for briefing in [librarian_briefing, action_briefing, sentinel_briefing]:
            agent_name = briefing["agent"]
            briefing_path = self.briefing_dir / f"{agent_name}_briefing.json"

            try:
                briefing_path.write_text(json.dumps(briefing, indent=2))
                briefings.append(str(briefing_path))
            except Exception as e:
                logger.error(f"Failed to write briefing for {agent_name}: {e}")

        logger.info(f"Overnight briefings written for {len(briefings)} agents")
        return briefings

    # ── Step 5: Premise Decomposition ────────────────────────────────

    PREMISE_PROMPT = """Break each of the following beliefs into the shortest possible basic propositional statements (premises). Each premise should be ONE simple fact or assertion that can stand alone.

FOCUS ESPECIALLY ON extracting:
1. TOOL-RELATED premises: what tools exist, what they do, when to use them, how they work
2. PREFERENCE/FEELING premises: "I like X", "I prefer X over Y", "X feels good/bad", "I enjoy X"
3. RELATIONAL premises: beliefs about specific people, how they behave, what they value
4. CAPABILITY premises: what I can/cannot do, what works/doesn't work
5. WORLD-KNOWLEDGE premises: objective facts about the world needed for logical inference

Examples:
  Belief: "Guilt is useful when it motivates me to improve my future actions, rather than being a paralyzing state."
  Premises:
  - Guilt can be useful
  - Guilt can motivate improvement
  - Guilt can be paralyzing
  - Paralyzing guilt is not useful
  - Guilt should motivate future action

  Belief: "I can send emails using the send_email tool but should verify recipients before sending."
  Premises:
  - I can send emails
  - The send_email tool exists
  - The send_email tool sends emails
  - I should verify recipients before sending
  - Sending to wrong recipients is a risk

BELIEFS TO DECOMPOSE:
{beliefs_block}

Output ONLY a JSON array where each element is:
{{"premise": "short statement", "parent_id": "belief_id"}}

No commentary. No markdown fencing. Just the JSON array."""

    def _run_premise_decomposition(self) -> dict:
        """Decompose today's new/modified beliefs into atomic premises.

        Pipeline:
        1. Identify beliefs added or reinforced tonight
        2. Send to Gemini Flash in batches for decomposition
        3. Deduplicate against all existing beliefs using embeddings
        4. Add genuinely new premises to the belief graph
        5. Project new beliefs into the 8D cognitive space

        Returns stats dict.
        """
        if not self.gemini:
            return {"status": "skipped", "reason": "gemini client not available"}

        # 1. Identify beliefs to decompose
        #    - All beliefs formed today
        #    - All beliefs the Psych Doctor touched tonight
        today = datetime.now().strftime("%Y-%m-%d")
        all_beliefs = self.belief_graph.get_all_beliefs()

        # Beliefs formed today or recently modified
        targets = []
        for b in all_beliefs:
            formed = b.get("formed", "")
            if isinstance(formed, str) and formed.startswith(today):
                targets.append(b)

        # Also include any the Psych Doctor added tonight (tracked in _psych_actions)
        psych_added_ids = set()
        if hasattr(self, '_psych_actions'):
            # The _psych_add_belief method logged the IDs — we capture them
            # by checking which beliefs were formed today
            pass  # Already captured above by formed date

        if not targets:
            return {"status": "skipped", "reason": "no new beliefs to decompose"}

        logger.info(f"Premise Decomposition: {len(targets)} beliefs to process")

        # 2. Decompose via LLM in batches
        all_premises = []
        batch_size = 20

        for i in range(0, len(targets), batch_size):
            batch = targets[i:i + batch_size]
            block = "\n".join(f"[{b['id']}] {b['content']}" for b in batch)
            prompt = self.PREMISE_PROMPT.format(beliefs_block=block)

            try:
                response = self.gemini.ask(
                    prompt=prompt,
                    model="auto",
                    temperature=0.2,
                )

                # Parse JSON response
                text = response.strip()
                if text.startswith("```"):
                    text = text.split("\n", 1)[1]
                    if text.endswith("```"):
                        text = text[:-3]
                    text = text.strip()

                premises = json.loads(text)
                if isinstance(premises, list):
                    all_premises.extend(premises)
                    logger.info(f"  Batch {i // batch_size + 1}: +{len(premises)} premises")
            except json.JSONDecodeError as e:
                logger.warning(f"  Batch {i // batch_size + 1}: JSON parse error: {e}")
            except Exception as e:
                logger.warning(f"  Batch {i // batch_size + 1}: LLM error: {e}")

            time.sleep(0.5)  # Light rate limiting

        if not all_premises:
            return {"status": "completed", "decomposed": len(targets), "new_premises": 0}

        logger.info(f"Extracted {len(all_premises)} raw premises from {len(targets)} beliefs")

        # 3. Deduplicate against existing beliefs
        new_premises = self._deduplicate_premises(all_premises, all_beliefs)
        duplicates_filtered = len(all_premises) - len(new_premises)

        logger.info(
            f"Deduplication: {len(all_premises)} → {len(new_premises)} "
            f"({duplicates_filtered} duplicates filtered)"
        )

        # 4. Add survivors to the belief graph
        belief_map = {b["id"]: b for b in all_beliefs}
        added = 0

        for p in new_premises:
            premise_text = p.get("premise", "").strip()
            parent_id = p.get("parent_id", "")

            if not premise_text or len(premise_text) < 5:
                continue

            # Generate a safe ID
            clean = re.sub(r"[^a-zA-Z0-9\s]", "", premise_text).lower().split()
            belief_id = "b_" + "_".join(clean[:6])

            # Skip if this ID already exists
            if self.belief_graph.get_belief(belief_id):
                continue

            # Inherit Lagrangian encoding from parent if available
            parent = belief_map.get(parent_id, {})
            enc = parent.get("encoding_lagrangian", {})

            self.belief_graph.add_belief(
                belief_id=belief_id,
                content=premise_text,
                confidence=0.40,
                verifications=1.0,
                stability_index=0.5,
                relations=[parent_id] if parent_id else [],
                belief_type="propositional",
            )
            added += 1

        logger.info(f"Added {added} new atomic premises to belief graph")

        return {
            "status": "completed",
            "beliefs_decomposed": len(targets),
            "raw_premises": len(all_premises),
            "duplicates_filtered": duplicates_filtered,
            "new_premises_added": added,
        }

    def _deduplicate_premises(self, candidates: list, existing_beliefs: list) -> list:
        """Filter candidate premises against existing beliefs using embeddings.

        Uses ChromaDB's local embedding function (all-MiniLM-L6-v2) for
        fast CPU-based similarity comparison. The threshold is derived
        statistically: µ + 2σ of pairwise similarities (less aggressive
        than the initial build's µ + 3σ, catches more near-duplicates).

        Args:
            candidates: List of {"premise": str, "parent_id": str} dicts
            existing_beliefs: List of existing belief dicts

        Returns:
            Filtered list of candidates that are genuinely new.
        """
        if not candidates:
            return []

        try:
            import chromadb.utils.embedding_functions as emb
            ef = emb.DefaultEmbeddingFunction()
        except ImportError:
            logger.warning("ChromaDB not available for deduplication — accepting all premises")
            return candidates

        # Embed all candidate premises
        candidate_texts = [p.get("premise", "") for p in candidates]
        existing_texts = [b.get("content", "") for b in existing_beliefs]

        if not existing_texts:
            return candidates  # Nothing to deduplicate against

        try:
            # Embed in chunks to avoid memory issues
            chunk_size = 500
            candidate_embeddings = []
            for i in range(0, len(candidate_texts), chunk_size):
                chunk = candidate_texts[i:i + chunk_size]
                candidate_embeddings.extend(ef(chunk))

            existing_embeddings = []
            for i in range(0, len(existing_texts), chunk_size):
                chunk = existing_texts[i:i + chunk_size]
                existing_embeddings.extend(ef(chunk))

            candidate_embs = np.array(candidate_embeddings, dtype=np.float32)
            existing_embs = np.array(existing_embeddings, dtype=np.float32)

            # Normalize for cosine similarity
            c_norms = np.linalg.norm(candidate_embs, axis=1, keepdims=True)
            candidate_embs = candidate_embs / np.maximum(c_norms, 1e-9)

            e_norms = np.linalg.norm(existing_embs, axis=1, keepdims=True)
            existing_embs = existing_embs / np.maximum(e_norms, 1e-9)

            # Compute similarity of each candidate against all existing beliefs
            sim_matrix = np.dot(candidate_embs, existing_embs.T)

            # Max similarity of each candidate to any existing belief
            max_sims = np.max(sim_matrix, axis=1)

            # Derive threshold statistically: µ + 2σ
            mu = float(np.mean(max_sims))
            sigma = float(np.std(max_sims))
            threshold = mu + 2.0 * sigma

            logger.info(
                f"Dedup stats: µ={mu:.4f}, σ={sigma:.4f}, threshold={threshold:.4f}"
            )

            # Filter: keep only candidates below threshold (genuinely new)
            survivors = []
            for idx, p in enumerate(candidates):
                if max_sims[idx] < threshold:
                    survivors.append(p)

            return survivors

        except Exception as e:
            logger.warning(f"Deduplication embedding failed: {e} — accepting all premises")
            return candidates

    # ── Step 7: 8D Spatial Re-sync ───────────────────────────────────

    def _resync_spatial_state(self) -> dict:
        """Run the Nightly Gravitational Convergence Pipeline.
        
        Refits PCA, reprojects nodes, recalculates belief mass, and identifies
        singularities.
        """
        try:
            from brain.manifold.convergence import ConvergencePipeline
            pipeline = ConvergencePipeline(
                memory=self.memory,
                belief_graph=self.belief_graph,
                base_dir=self.base_dir
            )
            return pipeline.run_nightly_cycle()
        except Exception as e:
            logger.warning(f"Convergence pipeline failed: {e}")
            return {"status": "failed", "error": str(e)}

    # ── Utility ──────────────────────────────────────────────────────

    def _save_analysis(self, results: dict):
        """Save overnight analysis results."""
        try:
            date_str = datetime.now().strftime("%Y%m%d")
            path = self.analysis_dir / f"overnight_{date_str}.json"
            path.write_text(json.dumps(results, indent=2, default=str))
            logger.info(f"Overnight analysis saved to {path}")
        except Exception as e:
            logger.error(f"Analysis save failed: {e}")
