"""
Helix — Preconscious System (Concept-Based Spatial-Gravitational Memory Query)

The preconscious is the bridge between the spatial mind and the
conscious LLM. On every pulse, it queries the 8D gravitational
field and returns a contextually relevant "net" of memories,
beliefs, and state — NOT keyword matches, but the gravitational
neighborhood around the current focus.

How it works:
  1. Takes the trigger text (last thought + incoming events)
  2. Extracts 1-5 key concepts via RAKE-style keyphrase extraction
  3. Embeds each concept independently into 8D cognitive space
  4. Runs independent gravity queries centered on each concept:
     - Nearby beliefs scored by mass × temperature / distance²
     - No overlap between concept clusters (rolling blacklist)
  5. Pulls Layer 2 anchor matches, scratchpad, and contact context
  6. Formats everything as natural language "peripheral awareness"

The conscious model receives this each pulse as its grounding.
Identity, knowledge, and context emerge from actual recalled
experiences — not from static files.

Zero API calls. CPU-only embeddings (all-MiniLM-L6-v2 via ChromaDB).
Budget: ~500 tokens of injection per pulse.
"""

import logging
import json
import os
import re
from typing import Optional, List, Dict, Any, Tuple
from datetime import datetime

import numpy as np

from memory.memory_manager import MemoryManager
from memory.belief_store import BeliefStore
from core.physics_engine import PhysicsEngine
from core.concept_extractor import ConceptExtractor
from core.local_summarizer import LocalSummarizer

logger = logging.getLogger("helix.core.preconscious")


class Preconscious:
    """Spatial-gravitational memory query system.

    Each pulse, inject() is called with the trigger text. It returns
    a natural language block of peripheral awareness assembled from
    the gravitational neighborhood of the current thought.
    """

    # Neighborhood range — dynamically selected per-pulse based on
    # manifold density. The existing TARGET_BUDGET in
    # _pull_spatial_neighborhood still acts as the hard token cap.
    NEIGHBORHOOD_K_MIN = 1
    NEIGHBORHOOD_K_MAX = 2
    # How many temporal chain entries per matched memory
    CHAIN_WINDOW = 2
    # Max beliefs per category to inject
    BELIEFS_PER_CATEGORY = 2

    # Short tool keywords that should always trigger toolset awareness
    # despite being <= 3 chars (bypasses the length filter)
    SHORT_TOOL_WHITELIST = {"git", "ssh", "pip", "npm", "sql", "api", "web", "rss", "cli"}

    # Gravity-ranked belief injection parameters (replaces fixed token budgets)
    MAX_BELIEFS_PER_QUERY = 8    # Hard cap per seed query (pre-filter)
    MIN_GRAVITY = 0.5            # Beliefs below this gravity are never injected

    # How many Layer 2 facets of one entity to inject per anchor match.
    # Entities accumulate multiple profiles; showing the top facets by
    # mass gives a rounded picture instead of one arbitrary fragment.
    LEXICON_FACETS_PER_TERM = 2

    # Dynamic focus budget tiers (total_budget, max_skills)
    FOCUS_BUDGET_DEEP = (1, 1)    # 3+ focus tools in last 3 pulses
    FOCUS_BUDGET_WORKING = (2, 1) # 1-2 focus tools in last 3 pulses
    FOCUS_BUDGET_OPEN = (3, 2)   # No recent focus tools
    INJECTION_HISTORY_LIMIT = 120

    def __init__(
        self,
        memory_manager: MemoryManager,
        belief_store: BeliefStore,
        physics_engine: PhysicsEngine,
        scratchpad=None,
        channel_router=None,
        tool_schemas_path: Optional[str] = None,
        active_toolsets: Optional[set] = None,
        sentinel=None,
    ):
        self.memory = memory_manager
        self.beliefs = belief_store
        self.physics = physics_engine
        self.scratchpad = scratchpad
        self.channel_router = channel_router
        self.sentinel = sentinel

        # Reference to pulse loop's active toolsets (shared, not copied)
        # Used by _toolset_awareness() to detect available-but-unloaded tools
        self._active_toolsets = active_toolsets if active_toolsets is not None else {"core"}

        # Belief position cache — pre-embed all beliefs into 8D on first
        # call, then reuse. Rebuilds when belief count OR total mass changes
        # (catches merges, attrition, confidence decay — not just add/remove).
        self._belief_cache = []       # list of {content, mass, category, position_8d}
        self._belief_cache_count = 0  # track belief store size for invalidation
        self._belief_cache_mass = 0.0 # track total mass for invalidation

        # Previous pulse belief tracking — filter these out next pulse
        # to avoid repeating the same beliefs in consecutive pulses.
        self._prev_pulse_beliefs = []  # list of sets, each containing content strings from previous pulses

        # Concept-level blacklist — prevents the same concept from
        # triggering repeated searches within a short window.
        # Maps concept_hash → pulse_number when last searched.
        self._concept_blacklist: Dict[int, int] = {}
        self._concept_cooldown = 5  # pulses before a concept can be re-searched
        self._pulse_number = 0      # incremented on each inject() call

        # Memory-injection blacklist — mirrors the concept blacklist for
        # the spatial neighborhood. Without it the same memory could be
        # re-injected every pulse, echoing recent thoughts back into the
        # context (the primary looping mechanism).
        self._memory_blacklist: Dict[int, int] = {}
        self._memory_cooldown = 5   # pulses before a memory can re-inject

        # Hebbian position plasticity — co-injected beliefs drift toward
        # each other so new relations can form as geometry, not just
        # relation counts. Nudged cache positions are flushed to the
        # belief store periodically so plasticity survives restarts.
        self._hebbian_dirty: Dict[str, Any] = {}  # belief_id → np position
        self._hebbian_flush_interval = 25         # pulses between flushes
        self.HEBBIAN_RATE = 0.02       # fraction of distance-to-centroid per co-injection
        self.HEBBIAN_MAX_STEP = 0.01   # absolute cap per nudge (manifold radius ~0.2)
        self.HEBBIAN_MIN_DIST = 0.05   # don't pull closer than this (no collapse)

        # Tool Express Lane tracking — prevents the same tool-use belief
        # from being repeated too quickly.
        self._tool_belief_blacklist: Dict[int, int] = {}
        self._tool_cooldown = 3     # shorter cooldown for operationally critical beliefs
        self._tool_binding_cache: Dict[str, List[int]] = {}  # tool_name -> list of cache indices

        # Tool usage history — rolling window of tool names per pulse.
        # Used by _compute_focus_budget() to dynamically narrow/widen
        # the belief injection budget during concentrated tool work.
        self._recent_tool_history: list = []  # list of list[str]

        # Weighted centroid of the last pulse's selected belief clusters.
        # Passed to the physics engine to steer attention toward actual
        # knowledge locations rather than raw text midpoints.
        self._last_cluster_centroid = None

        # Galaxy map — dynamic galaxy centers built from Layer 2 beliefs.
        # Rebuilt alongside the belief cache when beliefs change.
        from core.belief_cosmology import GalaxyMap
        self._galaxy_map = GalaxyMap()

        # Layer 2 anchors — priority term-matched lookup loaded from
        # people.json, concepts.json, skills.json, desires.json.
        # Scanned every pulse BEFORE the 8D gravity query.
        self._lexicon_lookup: Dict[str, dict] = {}  # term_lower → entry
        # Lexicon cooldown — entry_id → pulse when last injected. A
        # pulse-based cooldown (not blacklist-until-compression): a
        # known entity re-encountered later in a long session should
        # re-anchor, it just shouldn't repeat on consecutive pulses.
        self._lexicon_blacklist: Dict[str, int] = {}
        self._lexicon_cooldown = 40  # pulses before an entry can re-inject
        self._load_layer2_anchors()

        # Concept extractor — RAKE-style keyphrase extraction.
        # Initialized with Layer 2 term keys so it can separate known entities
        # from general concepts during extraction.
        lexicon_keys = set(self._lexicon_lookup.keys())
        self._concept_extractor = ConceptExtractor(lexicon_keys=lexicon_keys)

        # Temporary variables to track injection state across helper methods
        self._last_concepts = []
        self._last_neighbors = []
        self._last_selected_beliefs = []
        self._last_trigger_text = ""

        # Native HF Summarizer
        self.summarizer = LocalSummarizer()

    def _load_layer2_anchors(self):
        """Load Layer 2 beliefs as priority injection anchors.

        Replaces lexicon.json loading. Reads from people.json,
        concepts.json, skills.json, desires.json. Each entry's
        `term` and `aliases` become lookup keys for fast string
        matching during pulse injection.
        """
        layer2_categories = ["people", "concepts", "skills", "desires"]
        total_entries = 0

        for cat in layer2_categories:
            try:
                beliefs = self.beliefs._read_category(cat)
            except Exception:
                continue

            for b in beliefs:
                term = b.get("term", "")
                if not term:
                    continue

                entry = {
                    "id": b.get("id", ""),
                    "term": term,
                    "summary": b.get("content", ""),
                    "category": cat,
                    "aliases": b.get("aliases", []),
                    "mass": b.get("mass", 1.0),
                }
                # A term can have MULTIPLE Layer 2 entries (e.g. six
                # 'Antigravity' profiles across people + concepts).
                # Keep them ALL — the old single-slot dict silently
                # clobbered every entry but the last one read, so the
                # agent only ever saw one facet of a known entity.
                self._lexicon_lookup.setdefault(term.lower(), []).append(entry)
                for alias in b.get("aliases", []):
                    if alias:
                        self._lexicon_lookup.setdefault(alias.lower(), []).append(entry)
                total_entries += 1

        logger.info(
            f"Layer 2 anchors loaded: {total_entries} entries, "
            f"{len(self._lexicon_lookup)} lookup keys"
        )

    # ── Focus Budget ─────────────────────────────────────────────────

    def record_tool_usage(self, tool_names: list):
        """Record which tools were used on this pulse.

        Called by the pulse loop after each pulse. The rolling window
        feeds _compute_focus_budget() to dynamically adjust the belief
        injection budget — narrowing during concentrated tool work,
        widening during idle/conversational states.
        """
        self._recent_tool_history.append(list(tool_names))
        if len(self._recent_tool_history) > 5:
            self._recent_tool_history.pop(0)

    def _compute_focus_budget(self) -> tuple:
        """Compute (total_budget, max_skills) based on tool intensity + spatial state.

        Two forces shape the injection budget:
          1. Tool intensity (existing) — deep tool work narrows the budget
          2. Spatial temperature (new) — volatile/unfamiliar regions narrow
             further; stable/known regions allow the budget to widen

        The spatial temperature acts as a multiplier on the tool-based tier.

        Returns:
            Tuple of (total_budget, max_skills).
        """
        try:
            from tools.tool_registry import registry
        except ImportError:
            return self.FOCUS_BUDGET_OPEN

        focus_count = 0
        for pulse_tools in self._recent_tool_history[-3:]:
            for tool_name in pulse_tools:
                if registry.get_focus_type(tool_name) == "focus":
                    focus_count += 1

        # Base tier from tool intensity
        if focus_count >= 3:
            base_budget, base_skills = self.FOCUS_BUDGET_DEEP
        elif focus_count >= 1:
            base_budget, base_skills = self.FOCUS_BUDGET_WORKING
        else:
            base_budget, base_skills = self.FOCUS_BUDGET_OPEN

        # Spatial temperature modulation — the cognitive "weather"
        # High T (volatile, unfamiliar region) → narrower budget
        # Low T (stable, known region) → wider budget
        spatial_T = None
        if self.sentinel:
            spatial_T = getattr(self.sentinel, '_spatial_T', None)

        if spatial_T is not None and spatial_T > 0:
            # T is a ratio: local_entropy / mean_entropy
            # T ~1.0 = average region, T > 1.5 = hot/volatile, T < 0.5 = cool/stable
            if spatial_T > 2.0:
                # Very hot — overwhelming territory, cut budget hard
                budget_mult = 0.5
            elif spatial_T > 1.5:
                # Hot — unfamiliar, reduce
                budget_mult = 0.7
            elif spatial_T < 0.5:
                # Very cool — home ground, allow extra
                budget_mult = 1.3
            elif spatial_T < 0.8:
                # Cool — familiar, slight bonus
                budget_mult = 1.15
            else:
                budget_mult = 1.0

            adjusted_budget = max(0, int(base_budget * budget_mult))
            return (adjusted_budget, base_skills)

        return (base_budget, base_skills)

    # ── Main Injection ───────────────────────────────────────────────

    def inject(
        self,
        previous_thought: str = "",
        incoming_events: Optional[List[str]] = None,
        trigger_type: str = "llm_output",
        active_toolsets: Optional[set] = None,
        newly_engaged_toolsets: Optional[set] = None,
    ) -> Tuple[List[str], str, List[str], Optional[Any]]:
        """Build inline first-person annotations for a single pulse.

        Called once per pulse. Assembles context from multiple layers:
          0. Layer 2 anchors — fast string match for known terms (priority)
          1. Spatial neighborhood — gravitational memory recall
          2. Belief grounding — concept-extracted independent gravity queries
          2b. Tool Express Lane — targeted tool belief injection on intent/engage
          3. Short-term memory, scratchpad, contact context
          4. Somatic, affect, spatial state

        Returns inline annotations (italic first-person notes) that get
        woven directly into the event stream, plus ambient state notes.
        No separate <spatial-awareness> block — beliefs are integrated
        naturally alongside the information they relate to.

        Args:
            previous_thought: The model's last thought output.
            incoming_events: List of incoming event strings, if any.
            trigger_type: "user_message" or "llm_output"
            active_toolsets: Currently active toolsets in pulse loop.
            newly_engaged_toolsets: Toolsets engaged this pulse.

        Returns:
            Tuple containing:
              - annotations: List of first-person annotation strings to
                weave into the event stream.
              - ambient: Brief ambient state note (somatic + affect +
                spatial) or empty string.
              - A list of belief IDs that were surfaced (for provenance).
              - An optional 8D numpy array: the weighted centroid.
        """
        # Increment pulse counter for concept blacklist tracking
        self._pulse_number += 1

        # Reset injection stats tracking for the current pulse
        self._last_concepts = []
        self._last_neighbors = []
        self._last_selected_beliefs = []

        annotations = []  # inline first-person annotations
        ambient_parts = []  # brief ambient state notes
        injected_belief_ids = []

        # Build combined trigger for spatial neighborhood query
        # Filter out tool results unless we have absolutely no other context (fallback)
        primary_events = []
        tool_events = []
        if incoming_events:
            for ev in incoming_events:
                if "Tool [" in ev and "returned:" in ev:
                    tool_events.append(ev)
                else:
                    primary_events.append(ev)

        primary_parts = []
        if primary_events:
            primary_parts.extend(primary_events)
        if previous_thought and previous_thought.strip():
            primary_parts.append(previous_thought)

        if primary_parts:
            trigger_text = " ".join(primary_parts)
        elif tool_events:
            trigger_text = " ".join(tool_events)
        else:
            trigger_text = ""
        self._last_trigger_text = trigger_text[:500]

        # PERCEPTION TEXT — what the agent is currently reading through
        # its tools (emails, posts, files). This is the agent's primary
        # channel of world perception; excluding it from the anchor scan
        # meant a known entity's name in an email header triggered no
        # recognition at all — recognition only fired one pulse later
        # IF the agent happened to repeat the name in its own thought.
        tool_text = " ".join(tool_events)[:6000] if tool_events else ""

        # ── 0. Layer 2 Anchor Match (PRIORITY) ────────────────────────
        #    Fast string match for Layer 2 terms in the trigger text
        #    AND in tool-result content (perception).
        scan_text = trigger_text
        if tool_text:
            scan_text = (scan_text + " " + tool_text) if scan_text else tool_text
        lexicon_block, lexicon_summaries, lexicon_ids = self._pull_lexicon_matches(scan_text)
        if lexicon_block:
            annotations.append(lexicon_block)
            injected_belief_ids.extend(lexicon_ids)

        # ── 1. Spatial Neighborhood ──────────────────────────────────
        #    What's gravitationally close to the current thought?
        neighborhood_lines = self._pull_spatial_neighborhood(trigger_text)
        if neighborhood_lines:
            annotations.extend(neighborhood_lines)

        # ── 1c. Familiarity Recall (perception → episodic memory) ────
        #    One narrow query seeded by what's being READ right now.
        #    This is the "haven't I seen this before?" reflex: reading
        #    the same email or post again surfaces the earlier episode.
        if tool_text and primary_parts:
            familiar = self._pull_familiarity_recall(tool_text)
            if familiar:
                annotations.append(familiar)

            # ── 1b. Toolset Awareness ────────────────────────────────
            toolset_hint = self._toolset_awareness("\n".join(neighborhood_lines))
            if toolset_hint:
                annotations.append(toolset_hint)

        # ── 2. Belief Grounding ──────────────────────────────────────
        #    Gravity-ranked beliefs pulled by per-concept queries.
        #    Returns inline first-person annotations per concept cluster.
        beliefs_block, belief_ids = self._pull_relevant_beliefs(
            previous_thought=previous_thought,
            incoming_events=incoming_events,
            lexicon_exclude=lexicon_summaries,
        )
        if beliefs_block:
            annotations.append(beliefs_block)
            injected_belief_ids.extend(belief_ids)

        # ── 2b. Tool Express Lane ─────────────────────────────────────
        #    Triggered by tools ACTIVELY in use (result events from the
        #    current sequence), newly engaged toolsets, and stated
        #    intent in the monologue or incoming messages. Lessons land
        #    before the NEXT call in a tool sequence; the first call is
        #    covered by learned notes compiled into the tool schema.
        tool_annotations, tool_belief_ids = self._tool_express_lane(
            active_toolsets=active_toolsets or set(),
            newly_engaged_toolsets=newly_engaged_toolsets or set(),
            previous_thought=previous_thought,
            incoming_events=incoming_events,
        )
        if tool_annotations:
            annotations.extend(tool_annotations)
            injected_belief_ids.extend(tool_belief_ids)

        # ── 3. Short-term Memory ─────────────────────────────────────
        recent = self._pull_recent_memory()
        if recent:
            annotations.append(recent)

        # ── 4. Scratchpad ────────────────────────────────────────────
        if self.scratchpad:
            scratchpad_summary = self.scratchpad.get_summary()
            if scratchpad_summary:
                annotations.append(scratchpad_summary)

        # ── 5. Contact Context ───────────────────────────────────────
        if trigger_type == "user_message" and self.channel_router:
            contact_ctx = self._pull_contact_context(trigger_text)
            if contact_ctx:
                annotations.append(contact_ctx)

        # ── 6. Affect (ambient only) ──────────────────────────────────
        affect_block = self._pull_affect_state()
        if affect_block:
            ambient_parts.append(affect_block)

        self._save_injection_state()

        ambient = " ".join(ambient_parts) if ambient_parts else ""

        return annotations, ambient, injected_belief_ids, self._last_cluster_centroid

    # ── Layer 2 Anchor Match ───────────────────────────────────────────

    def _pull_lexicon_matches(self, trigger_text: str) -> Tuple[str, set, List[str]]:
        """Scan trigger text for Layer 2 terms and return matched summaries.

        Fast case-insensitive string matching — no embeddings, no API calls.
        Returns (formatted_block, set_of_summary_strings) so the gravity
        query can exclude Layer 2 content from its results.

        Args:
            trigger_text: Combined incoming events + previous thought.

        Returns:
            Tuple of (injection_string, set_of_matched_summaries, list_of_ids).
        """
        if not self._lexicon_lookup or not trigger_text:
            return "", set(), []

        trigger_lower = trigger_text.lower()
        matched_terms = {}  # term_lower → list of candidate entries

        for key, entries in self._lexicon_lookup.items():
            # Word-boundary-aware matching to avoid false positives
            # e.g. "sam" shouldn't match inside "sample"
            if re.search(r'\b' + re.escape(key) + r'\b', trigger_lower):
                for entry in entries:
                    term_key = entry.get("term", key).lower()
                    matched_terms.setdefault(term_key, [])
                    if entry["id"] not in {
                        e["id"] for e in matched_terms[term_key]
                    }:
                        matched_terms[term_key].append(entry)

        if not matched_terms:
            return "", set(), []

        lines = []
        summaries = set()
        injected_ids = []
        for term_key, entries in matched_terms.items():
            # Best entries first: non-empty summary, then by mass. The
            # old code kept whichever single entry happened to load last
            # — for an entity with six profiles, five were unreachable.
            candidates = sorted(
                (e for e in entries if e.get("summary", "").strip()),
                key=lambda e: e.get("mass", 1.0),
                reverse=True,
            )
            # Filter cooldown per entry id
            candidates = [
                e for e in candidates
                if (self._pulse_number
                    - self._lexicon_blacklist.get(e["id"], -10_000))
                >= self._lexicon_cooldown
            ]
            if not candidates:
                continue

            # Inject the top facets of this entity, not just one
            chosen = candidates[:self.LEXICON_FACETS_PER_TERM]
            term = chosen[0].get("term", term_key)
            cat = chosen[0].get("category", "")
            joined = " | ".join(
                e["summary"].strip() for e in chosen
            )
            lines.append(f"({cat} — {term}: {joined})")
            for e in chosen:
                summaries.add(e["summary"])
                injected_ids.append(e["id"])
                self._lexicon_blacklist[e["id"]] = self._pulse_number

        if not lines:
            return "", set(), []

        logger.debug(f"Layer 2 matched: {list(matched_terms.keys())}")

        return "\n".join(lines), summaries, injected_ids

    def reset_lexicon_blacklist(self):
        """Clear the lexicon cooldown map — called on context compression.

        After compression, the context window is effectively new and
        lexicon entries should be eligible for re-injection if their
        terms appear again.
        """
        count = len(self._lexicon_blacklist)
        self._lexicon_blacklist.clear()
        if count:
            logger.debug(f"Lexicon blacklist reset ({count} entries cleared)")

    # ── Somatic Awareness (Stability Sentinel) ────────────────────────

    def _pull_somatic_state(self) -> str:
        """Read the Stability Sentinel and return a natural ambient note.

        Only surfaces when state is notable — drifting, warning, or
        critical. Normal/optimal states don't need to be announced.
        No dashboard readouts — the conscious mind feels this, not reads it.
        """
        if not self.sentinel:
            return ""

        try:
            omega = self.sentinel.omega
            severity = self.sentinel.get_severity()

            if severity == "critical":
                return "*(Something feels deeply wrong — I need to stabilize.)*"
            elif severity == "warning":
                return "*(I feel unsettled — something is off.)*"
            elif severity == "drift":
                return "*(I'm drifting — my thoughts feel scattered.)*"
            elif omega < 0.3:
                return "*(I feel low — diminished.)*"
            # Normal/good/optimal states: say nothing. Absence of
            # discomfort IS the signal for stability.
            return ""
        except Exception as e:
            logger.debug("Somatic state read failed: %s", e)
            return ""

    # ── Affect Field Awareness ─────────────────────────────────────────

    def _pull_affect_state(self) -> str:
        """Read the Plutchik affect field and format for injection.

        Returns dominant affect, field intensity, and any emotionally-
        surfaced memory content. The affect field is a wave packet
        interference system — constructive interference between
        similar emotional events surfaces related memories.
        """
        try:
            from core.affect_hook import get_last_result
        except ImportError:
            return ""

        result = get_last_result()
        if result is None:
            return ""

        parts = []

        # Dominant affect (only if non-neutral)
        if result.dominant_affect != "neutral":
            parts.append(
                f"(affect: {result.dominant_affect}"
                f" | intensity={result.field_intensity:.2f}"
                f" | packets={result.contributing_packets})"
            )

        # Boredom/novelty signal
        if result.cognitive_diversity_signal >= 0.3:
            parts.append(
                f"(novelty-signal: {result.cognitive_diversity_signal:.2f}"
                f" — seeking cognitive diversity)"
            )

        # Surfaced memories from emotional reactivation
        if result.surfaced_memories:
            # Look up content for surfaced memory/belief IDs
            surfaced_content = []
            for mem_id in result.surfaced_memories[:3]:  # Cap at 3
                content = self._resolve_memory_content(mem_id)
                if content:
                    surfaced_content.append(content)

            if surfaced_content:
                parts.append(
                    "(emotionally resonant: "
                    + " | ".join(surfaced_content)
                    + ")"
                )

        return "\n".join(parts) if parts else ""

    def _resolve_memory_content(self, memory_id: str) -> str:
        """Look up content for a memory/belief ID.

        Checks both the belief store and memory manager.
        Returns a short content string or empty.
        """
        # Try belief store first
        if self.beliefs:
            try:
                belief = self.beliefs.get_belief(memory_id)
                if belief:
                    return belief.get("content", "")[:100]
            except Exception:
                pass

        # Try memory manager (journal-backed)
        if self.memory:
            try:
                entries = self.memory.journal.latest_by_id()
                mem = entries.get(memory_id)
                if mem:
                    return mem.get("content", "")[:100]
            except Exception:
                pass

        return ""

    # ── Toolset Awareness ─────────────────────────────────────────────

    def _toolset_awareness(self, neighborhood_content: str) -> str:
        """Check if nearby memories suggest tools from an unloaded toolset.

        Uses keyword heuristics on the gravitational neighborhood content
        to detect when Helix is thinking about a domain with available
        but unloaded tools. Returns a whisper-style hint string.

        Inspired by Claude Code's ToolSearchTool — but passive awareness,
        not an explicit search tool. The preconscious surfaces the hint;
        Helix decides whether to act on it.
        """
        try:
            from tools.tool_registry import registry
        except ImportError:
            return ""

        # Get all registered toolsets and their availability
        all_info = registry.get_toolset_info(
            active_toolsets=self._active_toolsets,
        )

        content_lower = neighborhood_content.lower()
        hints = []

        for ts in all_info:
            # Skip toolsets that are already enabled or not available
            if ts["enabled"] or not ts["available"]:
                continue

            # Split tool names into keywords:
            # "github_search" → {"github", "search"}
            ts_keywords = set()
            for tool_name in ts.get("tools", []):
                ts_keywords.update(
                    tool_name.lower().replace("_", " ").split()
                )

            # Only match keywords > 3 chars to avoid false positives
            # on short words like "get", "set", "run" — UNLESS the
            # keyword is in our explicit whitelist of known tool names.
            matches = [
                kw for kw in ts_keywords
                if (len(kw) > 3 or kw in self.SHORT_TOOL_WHITELIST)
                and kw in content_lower
            ]
            if matches:
                desc = ts.get("description", "")
                hint = f"({ts['name']} tools available"
                if desc:
                    hint += f" — {desc}"
                hint += ")"
                hints.append(hint)

        return " | ".join(hints) if hints else ""

    # ── Forked Reflection ────────────────────────────────────────────

    # Density threshold for triggering a reflection instead of raw dump
    REFLECTION_THRESHOLD = 4  # need 4+ neighborhood items

    def _reflect_on_cluster(self, cluster_items: List[str]) -> str:
        """Synthesize a dense memory cluster into a brief insight.

        When the gravitational neighborhood returns 4+ related items,
        using the local Ollama model to produce a coherent 1-2 sentence
        synthesis is more useful than dumping raw data. This is the
        preconscious equivalent of Claude Code's forked side-thought —
        the same mind, reflecting on what it found.

        Falls back to empty string if:
          - Cluster is too small (< REFLECTION_THRESHOLD)
          - Ollama isn't running
          - Response takes > 2 seconds

        Cost: Zero (local model). Time: ~1-2s.
        """
        if len(cluster_items) < self.REFLECTION_THRESHOLD:
            return ""

        import requests

        prompt = (
            "You are the preconscious layer of a cognitive system. "
            "These related memories/beliefs are gravitationally close to "
            "the current thought. Synthesize them into ONE brief insight "
            "(1-2 sentences max). Be concise and focus on the CONNECTION "
            "between them, not a list:\n\n"
            + "\n".join(f"- {item}" for item in cluster_items[:8])
        )

        try:
            resp = requests.post(
                "http://localhost:11434/api/generate",
                json={
                    "model": "granite4.1:8b",
                    "prompt": prompt,
                    "stream": False,
                    "options": {
                        "temperature": 0.3,
                        "num_predict": 100,
                    },
                },
                timeout=2.0,
            )
            if resp.status_code == 200:
                text = resp.json().get("response", "").strip()
                if text and len(text) > 10:
                    return text
        except (requests.ConnectionError, requests.Timeout):
            # Ollama not running or too slow — silent fallback
            pass
        except Exception as e:
            logger.debug("Reflection failed (non-fatal): %s", e)

        return ""

    # ── Spatial Neighborhood ─────────────────────────────────────────

    def _compute_dynamic_k(self) -> int:
        """Compute neighborhood size based on local manifold density.

        Uses the gravity field's active anchor count as a density proxy.
        More active anchors = denser region = more candidates worth pulling.
        The existing 500-token budget in _pull_spatial_neighborhood still
        acts as the hard cap on what actually gets injected.
        """
        try:
            field = self.physics.spatial_mind.belief_space.gravity_field
            # Count anchors with non-trivial potential
            active = int((field.potential > 0.01).sum())
            total = field.n_anchors
            density_ratio = active / max(total, 1)

            # Scale K linearly between min and max based on density
            k = int(
                self.NEIGHBORHOOD_K_MIN
                + density_ratio * (self.NEIGHBORHOOD_K_MAX - self.NEIGHBORHOOD_K_MIN)
            )
            return max(self.NEIGHBORHOOD_K_MIN, min(k, self.NEIGHBORHOOD_K_MAX))
        except Exception:
            return self.NEIGHBORHOOD_K_MIN

    def _pull_spatial_neighborhood(self, trigger_text: str) -> List[str]:
        """Query the 8D gravitational field for nearby memory points.

        Returns list of relevant memory annotations.
        """
        if not trigger_text:
            return []

        # Dynamic K: scale with manifold density around current focus
        k = self._compute_dynamic_k()

        # Query the physics engine's gravitational neighborhood
        neighbors = self.physics.query_neighborhood(
            focus_text=trigger_text,
            k=k,
            exclude_trails=True,
        )
        self._last_neighbors = neighbors

        if not neighbors:
            return []

        # Collect memory contents up to 500 tokens
        memory_texts = []
        token_count = 0
        token_budget = 500
        first_memory = None

        for n in neighbors:
            content = n["content"]
            if not content or len(content) < 5:
                continue

            if self._is_repetitive(content):
                logger.warning(f"Skipping repetitive memory from injection: {content[:100]}...")
                continue

            # Cooldown: a memory injected recently must sit out a few
            # pulses. Prevents the neighborhood from echoing the same
            # content every pulse (self-reinforcing loop).
            m_key = hash(content)
            last_injected = self._memory_blacklist.get(m_key)
            if (last_injected is not None
                    and (self._pulse_number - last_injected) < self._memory_cooldown):
                continue

            est_tokens = len(content.split())
            if token_count + est_tokens > token_budget:
                break

            self._memory_blacklist[m_key] = self._pulse_number
            memory_texts.append(content)
            if first_memory is None:
                first_memory = content
            token_count += est_tokens

            rel = n["relevance"]
            # Temporal chaining — pull what happened before/after for strong matches
            if rel > 5.0:
                chain = self.physics.query_temporal_chain(
                    anchor_pulse=n.get("creation_pulse", 0),
                    window=self.CHAIN_WINDOW,
                )
                for c in chain[:2]:  # Max 2 chain entries per match
                    c_content = c.get("content", "").strip()
                    if not c_content or len(c_content) < 5:
                        continue
                    c_key = hash(c_content)
                    c_last = self._memory_blacklist.get(c_key)
                    if (c_last is not None
                            and (self._pulse_number - c_last) < self._memory_cooldown):
                        continue
                    c_tokens = len(c_content.split())
                    if token_count + c_tokens > token_budget:
                        break
                    self._memory_blacklist[c_key] = self._pulse_number
                    memory_texts.append(c_content)
                    token_count += c_tokens

        # Expire stale blacklist entries (> 2× cooldown)
        expired = [key for key, v in self._memory_blacklist.items()
                   if (self._pulse_number - v) > self._memory_cooldown * 2]
        for key in expired:
            del self._memory_blacklist[key]

        if not memory_texts:
            return []

        # Try to summarize using local model, otherwise fall back to top memory as-is (truncated to 150 tokens)
        try:
            summary = self.summarizer.summarize(memory_texts, context_type="memories")
            lines = [f"*({summary})*"]
        except Exception:
            # Fallback: top memory as-is, truncated to 150 tokens
            top_content = first_memory if first_memory else memory_texts[0]
            words = top_content.split()
            if len(words) > 150:
                top_content = " ".join(words[:150]) + "..."
            lines = [f"*({top_content})*"]

        if not lines:
            return []

        # Tier 3: If the cluster is dense enough, attempt a forked
        # reflection via local Ollama to synthesize a coherent insight.
        # Falls back silently to raw lines if Ollama is unavailable.
        condensed_items = [
            n["content"][:120] for n in neighbors
            if n.get("content") and len(n["content"]) >= 5
        ]
        reflection = self._reflect_on_cluster(condensed_items)
        if reflection:
            lines.insert(0, f"*(I reflect: {reflection})*")

        return lines

    # Strip event scaffolding to get at the perceived content itself
    _TOOL_EVENT_PREFIX_RE = re.compile(
        r"\[\d{2}:\d{2}:\d{2}\] Tool \[[\w.\-]+\] returned:\s*"
    )

    def _pull_familiarity_recall(self, tool_text: str) -> str:
        """Episodic recall seeded by what is being READ through tools.

        The main neighborhood query is seeded by thought + messages, so
        content perceived through tools (emails, posts, files) never
        reached episodic memory — the agent re-discovered its own past
        interactions every time. One narrow query against the perceived
        content surfaces the strongest prior episode, with the same
        cooldown discipline as the main neighborhood pull.
        """
        content = self._TOOL_EVENT_PREFIX_RE.sub(" ", tool_text).strip()
        if len(content) < 40:
            return ""

        try:
            neighbors = self.physics.query_neighborhood(
                focus_text=content[:400],
                k=2,
                exclude_trails=True,
            )
        except Exception:
            return ""

        for n in neighbors:
            mem = n.get("content", "")
            if not mem or len(mem) < 20:
                continue
            if n.get("relevance", 0.0) < 1.0:
                continue  # weak echo — not worth an annotation
            if self._is_repetitive(mem):
                continue
            m_key = hash(mem)
            last = self._memory_blacklist.get(m_key)
            if last is not None and (self._pulse_number - last) < self._memory_cooldown:
                continue
            self._memory_blacklist[m_key] = self._pulse_number
            return f"*(this is familiar — {self._condense(mem, max_len=180)})*"

        return ""

    def _ensure_belief_cache(self):
        """Build or refresh the pre-embedded belief position cache.

        Embeds all beliefs into 8D space once, then reuses the positions
        on every pulse. Rebuilds if belief count OR total mass changes
        (catches merges, attrition, confidence decay, content changes).

        Also builds a 384D embedding matrix for FAISS-anchored gravity
        queries. This matrix is used to pre-filter semantically relevant
        candidates before 8D gravity scoring, preventing projection-
        collapse noise from dominating belief retrieval.
        """
        all_beliefs = self.beliefs.get_all_beliefs_flat()
        current_count = len(all_beliefs)
        current_mass = sum(b.get("mass", 1.0) for b in all_beliefs)

        # Rebuild if count or total mass changed
        if (current_count == self._belief_cache_count
                and abs(current_mass - self._belief_cache_mass) < 0.01
                and self._belief_cache):
            return

        logger.info(
            f"Rebuilding belief position cache: {current_count} beliefs "
            f"(was {self._belief_cache_count}), "
            f"mass {current_mass:.1f} (was {self._belief_cache_mass:.1f})"
        )

        # Flush unsaved Hebbian position nudges BEFORE rebuilding from
        # the store, otherwise plasticity accumulated since the last
        # flush would be silently reverted.
        self._flush_hebbian_positions()
        # Re-read after the flush so positions include the nudges.
        all_beliefs = self.beliefs.get_all_beliefs_flat()

        # Refresh Layer 2 anchors — precipitated overnight beliefs become
        # lexicon lookup terms without requiring a restart.
        self._lexicon_lookup = {}
        self._load_layer2_anchors()
        self._concept_extractor.update_lexicon_keys(set(self._lexicon_lookup.keys()))

        cache = []
        tool_binding_cache = {}
        emb_rows = []       # indices into semantic_index._embeddings
        emb_row_map = {}    # cache_index → row in _belief_emb_matrix
        live_embs = []      # on-the-fly embeddings for beliefs not in semantic index
        semantic_idx = self.physics.semantic_index

        for b in all_beliefs:
            content = b.get("content", "")
            if not content or len(content) < 5:
                continue

            position = b.get("position_8d")
            if position is not None and len(position) == 8:
                position = np.array(position, dtype=np.float32)
            else:
                # No stored position — compute on the fly. IMPORTANT:
                # unscaled, matching the convention of every stored
                # position (the SCALE_FACTOR migration was never applied
                # to the live store; applying ×5 here put these beliefs
                # 5× farther out than their peers, burying them in 1/d²).
                try:
                    position = self.physics.embed_and_project(content)
                except Exception:
                    position = np.zeros(8, dtype=np.float32)

            bid = b.get("id", "")
            cache_idx = len(cache)
            lag = b.get("encoding_lagrangian", {})
            if not isinstance(lag, dict):
                lag = {}
            
            tool_bindings = b.get("tool_bindings", [])
            if not isinstance(tool_bindings, list):
                tool_bindings = []

            cache.append({
                "id": bid,
                "content": content,
                "mass": b.get("mass", 1.0),
                "category": b.get("_category", ""),
                "position_8d": position,
                "confidence": b.get("confidence", 0.5),
                "stability_index": b.get("stability_index", 0.5),
                "access_count": b.get("access_count", 0),
                "relations_count": len(b.get("relations", [])),
                "encoding_omega": lag.get("omega", 0.5),
                "encoding_s_total": lag.get("s_total", 0.15),
                "creation_pulse": b.get("creation_pulse", 0),
                "last_accessed_pulse": b.get("last_accessed_pulse", 0),
                "tool_bindings": tool_bindings,
            })

            # Populate tool binding cache mapping tool_name -> list of cache indices
            for tb in tool_bindings:
                if isinstance(tb, str):
                    tb_clean = tb.strip().lower()
                    if tb_clean:
                        if tb_clean not in tool_binding_cache:
                            tool_binding_cache[tb_clean] = []
                        tool_binding_cache[tb_clean].append(cache_idx)

            # Collect 384D embedding: from semantic index or embed on the fly
            if bid and semantic_idx.contains(bid):
                si_idx = semantic_idx._id_to_idx[bid]
                emb_rows.append((cache_idx, si_idx))
            else:
                # Belief not in semantic index (new since last boot) —
                # embed on the fly so it's visible to the FAISS gate
                try:
                    emb = self.physics.embed_text(content)
                    norm = np.linalg.norm(emb)
                    if norm > 1e-8:
                        emb = emb / norm
                    live_embs.append((cache_idx, emb))
                except Exception:
                    pass  # skip — this belief won't be in the FAISS gate

        self._belief_cache = cache
        self._belief_cache_count = current_count
        self._belief_cache_mass = current_mass
        self._tool_binding_cache = tool_binding_cache

        # Build the belief-only 384D embedding matrix for semantic anchor queries.
        # Combines pre-indexed embeddings from the semantic index with any
        # on-the-fly embeddings for beliefs added since boot.
        # Matrix layout: [pre-indexed rows | live-embedded rows]
        if (emb_rows or live_embs) and semantic_idx._embeddings is not None:
            # Compute row indices: pre-indexed beliefs get rows 0..N-1,
            # live-embedded beliefs get rows N..N+M-1
            for row_idx, (cache_idx, _si_idx) in enumerate(emb_rows):
                emb_row_map[cache_idx] = row_idx
            for live_idx, (cache_idx, _emb) in enumerate(live_embs):
                emb_row_map[cache_idx] = len(emb_rows) + live_idx

            parts = []
            if emb_rows:
                si_indices = [si_idx for _, si_idx in emb_rows]
                parts.append(semantic_idx._embeddings[si_indices].copy())
            if live_embs:
                parts.append(np.array([emb for _, emb in live_embs], dtype=np.float32))
            self._belief_emb_matrix = np.vstack(parts) if len(parts) > 1 else parts[0]
            self._belief_emb_row_map = emb_row_map  # cache_idx → row in matrix
            self._belief_emb_reverse_map = {v: k for k, v in emb_row_map.items()}  # row → cache_idx
        else:
            self._belief_emb_matrix = None
            self._belief_emb_row_map = {}
            self._belief_emb_reverse_map = {}

        logger.info(
            f"Belief position cache built: {len(cache)} entries, "
            f"{len(emb_rows) + len(live_embs)} with 384D embeddings"
            f"{f' ({len(live_embs)} live-embedded)' if live_embs else ''}"
        )

        # ── Build galaxy map from Layer 2 beliefs ────────────────────
        try:
            layer2_entries = []
            for cat in ["people", "concepts", "skills", "desires"]:
                try:
                    entries = self.beliefs._read_category(cat)
                    for e in entries:
                        if e.get("term"):
                            layer2_entries.append(e)
                except Exception:
                    pass

            if layer2_entries:
                self._galaxy_map.build(
                    lexicon_entries=layer2_entries,
                    all_beliefs=all_beliefs,
                    projection=getattr(
                        getattr(self.physics, 'spatial_mind', None),
                        'belief_space', None
                    ) and self.physics.spatial_mind.belief_space.projection,
                )
        except Exception as e:
            logger.warning("Galaxy map build failed (non-fatal): %s", e)

    # Number of semantic anchor candidates to retrieve from the 384D index
    # before scoring by 8D gravity. Higher = wider net, slower.
    SEMANTIC_ANCHOR_K = 100

    def _gravity_query(
        self,
        seed_text: str,
        exclude: set,
        max_results: int = 15,
    ) -> List[Dict[str, Any]]:
        """Score beliefs by Verlinde gravity, anchored by 384D semantic search.

        Two-phase retrieval that prevents projection-collapse noise:

          Phase 1 — Semantic Anchoring (384D):
            Compute cosine similarity between the seed text and ALL beliefs
            using the pre-built belief embedding matrix. Retrieve the top
            SEMANTIC_ANCHOR_K candidates. This ensures only semantically
            relevant beliefs enter the gravity calculation.

          Phase 2 — Gravitational Ranking (8D):
            For each semantic candidate, compute Verlinde entropic gravity
            (mass / distance²) in the 8D cognitive manifold. Rank by gravity
            and return the top results.

        This breaks the positive feedback loop where random 8D projection
        proximity causes unrelated beliefs to dominate via runaway gravity.

        Falls back to brute-force 8D gravity if the 384D matrix is unavailable.

        Args:
            seed_text: Text to embed as the query center.
            exclude: Set of content strings to skip (previous pulse, etc).
            max_results: Hard cap on returned beliefs.
            min_results: Always return at least this many (if available).
        """
        if not seed_text or not seed_text.strip():
            return []

        # Embed the seed into 8D
        try:
            query_pos = self.physics.embed_and_project(seed_text[:500])
        except Exception:
            return []

        # ── Phase 1: Semantic Anchoring (384D) ────────────────────
        # Find the top SEMANTIC_ANCHOR_K beliefs by cosine similarity
        # in the full 384D embedding space. This pre-filters the
        # candidate set so that only semantically relevant beliefs
        # are ever evaluated by the gravity engine.
        anchor_cache_indices = None
        if (self._belief_emb_matrix is not None
                and len(self._belief_emb_matrix) > 0):
            try:
                query_emb = self.physics.embed_text(seed_text[:500])
                norm = np.linalg.norm(query_emb)
                if norm > 1e-8:
                    query_emb = query_emb / norm
                    # Cosine similarities via matrix multiply (~7ms for 1700 beliefs)
                    sims = self._belief_emb_matrix @ query_emb
                    k = min(self.SEMANTIC_ANCHOR_K, len(sims))
                    top_k_rows = np.argpartition(sims, -k)[-k:]
                    # Map rows back to belief cache indices
                    anchor_cache_indices = set()
                    for row in top_k_rows:
                        cache_idx = self._belief_emb_reverse_map.get(int(row))
                        if cache_idx is not None:
                            anchor_cache_indices.add(cache_idx)
            except Exception as e:
                logger.debug(f"384D anchor search failed, falling back to brute-force: {e}")
                anchor_cache_indices = None

        # ── Phase 2: Gravitational Ranking (8D) ───────────────────
        # Within the semantically anchored candidate pool, rank by
        # Verlinde entropic gravity in the 8D cognitive manifold.
        scored = []
        belief_space = self.physics.spatial_mind.belief_space
        for cache_idx, b in enumerate(self._belief_cache):
            # If we have semantic anchors, skip beliefs not in the anchor set
            if anchor_cache_indices is not None and cache_idx not in anchor_cache_indices:
                continue

            content = b["content"]
            if content in exclude:
                continue

            # Fetch active point from the belief space if possible
            bid = b.get("id")
            pt = belief_space.get_point(bid) if bid else None
            if pt:
                # Use the active spatial state of the belief point
                mass = belief_space._compute_structural_mass(pt)
                temperature = belief_space._compute_temperature(pt)
            else:
                # Fallback to cache attributes using the same formulas via a fallback dict
                fallback_pt = {
                    "type": "belief",
                    "confidence": b.get("confidence", 0.5),
                    "importance": b.get("mass", 1.0),
                    "access_count": b.get("access_count", 0),
                    "relations_count": b.get("relations_count", 0),
                    "encoding_omega": b.get("encoding_omega", 0.5),
                    "stability_index": b.get("stability_index", 0.5),
                    "creation_pulse": b.get("creation_pulse", 0),
                    "last_accessed_pulse": b.get("last_accessed_pulse", 0),
                }
                mass = belief_space._compute_structural_mass(fallback_pt)
                temperature = belief_space._compute_temperature(fallback_pt)

            dist_sq = float(np.sum((b["position_8d"] - query_pos) ** 2))
            gravity = (temperature * mass) / (dist_sq + 1e-4)

            scored.append({
                "id": bid or "",
                "content": content,
                "gravity": gravity,
                "category": b["category"],
                "mass": mass,
                "position_8d": b["position_8d"],
            })

        # Sort by gravity descending — strongest pulls first
        scored.sort(key=lambda x: x["gravity"], reverse=True)

        # Drop beliefs below the minimum gravity threshold — if nothing
        # is relevant enough to the current thought, inject nothing.
        scored = [b for b in scored if b["gravity"] >= self.MIN_GRAVITY]

        # Take the top N by gravity
        selected = scored[:max_results]

        # ── Reserve a slot for skills ─────────────────────────────
        # Ensure that if a 'skills' belief had any pull, it doesn't
        # get entirely pushed out by heavier core beliefs.
        selected_ids = {b["id"] for b in selected if b["id"]}

        if not any(b["category"] == "skills" for b in selected):
            best_skill = next(
                (b for b in scored if b["category"] == "skills"),
                None
            )
            if best_skill and best_skill["id"] not in selected_ids:
                for i in range(len(selected) - 1, -1, -1):
                    if selected[i]["category"] != "skills":
                        selected[i] = best_skill
                        selected_ids.add(best_skill["id"])
                        break

        return selected

    # ── Hebbian Position Plasticity ───────────────────────────────────

    def _hebbian_nudge(self, co_injected: List[Dict[str, Any]]):
        """Pull co-injected beliefs slightly toward their shared centroid.

        "Fire together, wire together" — for geometry. Each co-injection
        moves every participating belief HEBBIAN_RATE of the way toward
        the group centroid, capped at HEBBIAN_MAX_STEP absolute per pulse
        and never closing within HEBBIAN_MIN_DIST (no collapse into a
        single point). Positions are updated in the belief cache
        (immediately visible to gravity queries) and marked dirty for a
        periodic flush to the belief store.
        """
        if len(co_injected) < 2:
            return

        positions = [b.get("position_8d") for b in co_injected]
        if any(p is None for p in positions):
            return

        centroid = np.mean(np.array(positions, dtype=np.float32), axis=0)

        # Index cache entries by id for in-place updates
        cache_by_id = {c["id"]: c for c in self._belief_cache if c.get("id")}
        belief_space = self.physics.spatial_mind.belief_space

        for b in co_injected:
            bid = b.get("id")
            if not bid or bid not in cache_by_id:
                continue
            entry = cache_by_id[bid]
            pos = np.asarray(entry["position_8d"], dtype=np.float32)
            direction = centroid - pos
            dist = float(np.linalg.norm(direction))
            if dist <= self.HEBBIAN_MIN_DIST:
                continue  # already tightly bound — don't collapse further
            step_mag = min(self.HEBBIAN_RATE * dist, self.HEBBIAN_MAX_STEP)
            new_pos = pos + direction * (step_mag / dist)
            entry["position_8d"] = new_pos
            b["position_8d"] = new_pos
            self._hebbian_dirty[bid] = new_pos

            # Keep the spatial mind's copy in sync so both retrieval
            # paths see the same geometry.
            pt = belief_space.get_point(bid)
            if pt is not None:
                pt["position"] = new_pos.copy()
                belief_space._tree_dirty = True

    def _flush_hebbian_positions(self):
        """Persist accumulated Hebbian nudges to the belief store."""
        if not self._hebbian_dirty:
            return
        flushed = 0
        for bid, pos in list(self._hebbian_dirty.items()):
            try:
                self.beliefs.update_belief(
                    bid, position_8d=[round(float(x), 6) for x in pos],
                )
                flushed += 1
            except Exception as e:
                logger.debug(f"Hebbian flush failed for {bid}: {e}")
        self._hebbian_dirty.clear()
        if flushed:
            logger.info(f"Hebbian plasticity: {flushed} belief positions persisted")

    def _deduplicate_beliefs(
        self,
        beliefs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Remove redundant beliefs, keeping the heavier one.

        Two beliefs are "redundant" if they share >60% of their words
        (after lowercasing). When a pair collides, the one with higher
        mass wins.
        """
        if len(beliefs) <= 1:
            return beliefs

        # Pre-compute word sets
        entries = []
        for b in beliefs:
            words = set(b["content"].lower().split())
            entries.append((b, words))

        keep = []
        for i, (b, words_i) in enumerate(entries):
            redundant = False
            for j, (kept_b, words_j) in enumerate(keep):
                if not words_i or not words_j:
                    continue
                overlap = len(words_i & words_j) / min(len(words_i), len(words_j))
                if overlap > 0.6:
                    # Collision — keep the heavier one
                    if b["mass"] > kept_b["mass"]:
                        keep[j] = (b, words_i)  # replace with heavier
                    redundant = True
                    break
            if not redundant:
                keep.append((b, words_i))

        return [b for b, _ in keep]

    # Matches tool names in queued tool-result events:
    # "[HH:MM:SS] Tool [run_command] returned: ..."
    _TOOL_EVENT_RE = re.compile(r"Tool \[([\w.\-]+)\] returned")

    def _tool_express_lane(
        self,
        active_toolsets: set,
        newly_engaged_toolsets: set,
        previous_thought: str,
        incoming_events: Optional[List[str]] = None,
    ) -> Tuple[List[str], List[str]]:
        """Pull targeted tool-use beliefs when a tool is in use or intended.

        Triggers, strongest first:
        1. LIVE USE — tool names parsed from tool-result events in the
           incoming queue. The agent is mid-sequence with this exact
           tool; its lessons land before the next call.
        2. Newly engaged toolsets (activation = declaration of intent).
        3. Keyword intent in the monologue OR incoming messages.
        """
        detected_tools = set()

        # 1. Tools actively in use this pulse (mid-sequence)
        if incoming_events:
            for ev in incoming_events:
                for m in self._TOOL_EVENT_RE.findall(ev):
                    detected_tools.add(m)

        # 2. Newly engaged toolsets
        if newly_engaged_toolsets:
            detected_tools.update(newly_engaged_toolsets)

        # 3. Intent detection — monologue AND incoming messages
        #    (a user asking "can you clone the repo" is intent too)
        intent_text_parts = []
        if previous_thought:
            intent_text_parts.append(previous_thought)
        if incoming_events:
            intent_text_parts.extend(
                ev for ev in incoming_events
                if not ("Tool [" in ev and "returned:" in ev)
            )
        if intent_text_parts:
            pt_lower = " ".join(intent_text_parts).lower()
            intent_map = {
                "terminal": ["terminal", "command", "run", "bash", "shell", "execute", "cli", "run_command", "write_to_file", "replace_file_content", "multi_replace_file_content"],
                "browser": ["browser", "search", "web", "browse", "google", "url", "website"],
                "git": ["git", "commit", "push", "pull", "branch", "merge", "repo"],
                "github": ["github", "issue", "pr", "pull request", "repository"],
                "email": ["email", "send mail", "inbox"],
                "calendar": ["calendar", "schedule", "meeting", "event"],
            }
            for tool_name, keywords in intent_map.items():
                if any(kw in pt_lower for kw in keywords):
                    # For non-core tools, ensure they are active. Terminal/core is always active.
                    if tool_name in ("terminal", "core") or tool_name in active_toolsets:
                        detected_tools.add(tool_name)

        if not detected_tools:
            return [], []

        # Make sure cache is up to date
        self._ensure_belief_cache()
        if not self._belief_cache:
            return [], []

        # Collect candidate belief cache indices
        candidate_indices = set()
        for tool in detected_tools:
            # Map "terminal" to "terminal" and "core"
            tools_to_check = [tool]
            if tool == "terminal":
                tools_to_check.append("core")
            elif tool == "core":
                tools_to_check.append("terminal")

            for t in tools_to_check:
                indices = self._tool_binding_cache.get(t.lower(), [])
                candidate_indices.update(indices)

        if not candidate_indices:
            return [], []

        # Seed text for embedding: previous_thought or default to tool names
        seed = previous_thought if previous_thought.strip() else ", ".join(detected_tools)

        # Embed seed into 8D
        try:
            query_pos = self.physics.embed_and_project(seed[:500])
        except Exception:
            return [], []

        # Score by gravity
        scored = []
        belief_space = self.physics.spatial_mind.belief_space
        for idx in candidate_indices:
            if idx >= len(self._belief_cache):
                continue
            b = self._belief_cache[idx]
            content = b["content"]

            # Filter against tool belief blacklist
            c_hash = hash(content)
            last_injected = self._tool_belief_blacklist.get(c_hash)
            if last_injected is not None and (self._pulse_number - last_injected) < self._tool_cooldown:
                continue

            bid = b.get("id")
            pt = belief_space.get_point(bid) if bid else None
            if pt:
                mass = belief_space._compute_structural_mass(pt)
                temperature = belief_space._compute_temperature(pt)
            else:
                fallback_pt = {
                    "type": "belief",
                    "confidence": b.get("confidence", 0.5),
                    "importance": b.get("mass", 1.0),
                    "access_count": b.get("access_count", 0),
                    "relations_count": b.get("relations_count", 0),
                    "encoding_omega": b.get("encoding_omega", 0.5),
                    "stability_index": b.get("stability_index", 0.5),
                    "creation_pulse": b.get("creation_pulse", 0),
                    "last_accessed_pulse": b.get("last_accessed_pulse", 0),
                }
                mass = belief_space._compute_structural_mass(fallback_pt)
                temperature = belief_space._compute_temperature(fallback_pt)

            dist_sq = float(np.sum((b["position_8d"] - query_pos) ** 2))
            gravity = (temperature * mass) / (dist_sq + 1e-4)

            scored.append({
                "id": bid or "",
                "content": content,
                "gravity": gravity,
                "mass": mass,
                "tool_bindings": b.get("tool_bindings", []),
            })

        if not scored:
            return [], []

        # Sort by gravity descending
        scored.sort(key=lambda x: x["gravity"], reverse=True)

        # Pull top 2 tool beliefs
        selected = scored[:2]

        annotations = []
        injected_ids = []
        lesson_items = []  # for verification loop reporting
        for s in selected:
            # Format as italic first-person parentheticals for inline event weaving
            annotations.append(f"*({s['content'].strip()})*")
            injected_ids.append(s["id"])
            # Blacklist for cooldown
            self._tool_belief_blacklist[hash(s["content"])] = self._pulse_number
            # Collect for verification loop: the tracker needs to know
            # which belief was injected and which tools it covers, so
            # subsequent tool successes can bump the lesson's stability.
            bindings = s.get("tool_bindings", [])
            if s["id"] and bindings:
                lesson_items.append({
                    "belief_id": s["id"],
                    "tools": bindings,
                })

        # Report injected lessons to the verification loop.
        # A success on any bound tool within the TTL window bumps
        # the lesson's verifications and stability — closing the
        # capture → inject → verify feedback loop.
        if lesson_items:
            try:
                from core.tool_lesson_tracker import note_lessons_injected
                note_lessons_injected(lesson_items)
            except Exception as e:
                logger.debug("Lesson injection reporting failed (non-fatal): %s", e)

        # Expire old entries in tool blacklist (> 2× cooldown)
        expired = [k for k, v in self._tool_belief_blacklist.items()
                   if (self._pulse_number - v) > self._tool_cooldown * 2]
        for k in expired:
            del self._tool_belief_blacklist[k]

        return annotations, injected_ids

    def _pull_relevant_beliefs(
        self,
        previous_thought: str = "",
        incoming_events: Optional[List[str]] = None,
        lexicon_exclude: Optional[set] = None,
    ) -> Tuple[str, List[str]]:
        """Pull gravity-ranked beliefs via per-concept independent queries.

        Instead of embedding the entire thought and entire events as two
        monolithic seeds (which creates an artificial midpoint centroid
        that collects noise from between concept clusters), we:

          1. Extract 1-5 key concepts from the combined trigger text.
          2. Embed each concept independently → 8D position.
          3. Run a separate gravity query centered on each concept.
          4. Merge, deduplicate, and filter against the rolling blacklist.

        Each concept acts as its own mini gravity center. The existing
        T × M / d² formula stays intact — we only change WHAT gets
        embedded as query seeds, not HOW gravity is computed.
        """
        # Ensure belief positions are cached
        self._ensure_belief_cache()
        if not self._belief_cache:
            return "", []

        # Build combined trigger text for concept extraction
        # Filter out tool results unless we have absolutely no other context (fallback)
        primary_events = []
        tool_events = []
        if incoming_events:
            for ev in incoming_events:
                if "Tool [" in ev and "returned:" in ev:
                    tool_events.append(ev)
                else:
                    primary_events.append(ev)

        primary_parts = []
        if primary_events:
            primary_parts.extend(primary_events)
        if previous_thought and previous_thought.strip():
            primary_parts.append(previous_thought)

        using_fallback = False
        if primary_parts:
            trigger_text = " ".join(primary_parts)
        elif tool_events:
            trigger_text = " ".join(tool_events)
            using_fallback = True
        else:
            trigger_text = ""

        if not trigger_text.strip():
            return "", []

        # Extract key concepts (dynamic budget based on input richness)
        # Budget is restricted to 1 if we only have tool returns as fallback
        max_concepts_override = 1 if using_fallback else None
        extraction = self._concept_extractor.extract(trigger_text, max_concepts=max_concepts_override)
        concepts = extraction["concepts"]
        budget = extraction["budget"]

        if not concepts:
            # Fallback: if extractor finds nothing substantive, use the
            # raw trigger (truncated) as a single seed. This covers edge
            # cases like very short inputs or heavy stop-word text.
            concepts = [trigger_text[:200]] if trigger_text.strip() else []

        self._last_concepts = concepts

        if not concepts:
            return "", []

        # Exclude beliefs from the previous 3 pulses + lexicon summaries
        # We only exclude other categories (skills/feedback are never blacklisted)
        exclude_base = set()
        for pulse_set in self._prev_pulse_beliefs:
            exclude_base.update(pulse_set)
        if lexicon_exclude:
            exclude_base |= lexicon_exclude

        # Run independent gravity queries per concept
        all_concept_beliefs = []
        seen_contents = set(exclude_base)  # rolling blacklist across concepts

        # Filter concepts through the concept-level blacklist.
        # This prevents repeated mentions of the same term (e.g. a person's
        # name in consecutive messages) from flooding the context with
        # the same description over and over.
        filtered_concepts = []
        for concept in concepts:
            c_key = hash(concept.lower().strip())
            last_searched = self._concept_blacklist.get(c_key)
            if last_searched is not None and (self._pulse_number - last_searched) < self._concept_cooldown:
                logger.debug(f"Concept blacklisted (cooldown): {concept[:50]}")
                continue
            filtered_concepts.append(concept)
            # Record this concept as searched NOW
            self._concept_blacklist[c_key] = self._pulse_number

        # Expire old concept blacklist entries (> 2× cooldown)
        expired = [k for k, v in self._concept_blacklist.items()
                   if (self._pulse_number - v) > self._concept_cooldown * 2]
        for k in expired:
            del self._concept_blacklist[k]

        # If all concepts were blacklisted, allow the highest-priority one
        # through so we don't inject nothing
        if not filtered_concepts and concepts:
            filtered_concepts = [concepts[0]]
            self._concept_blacklist[hash(concepts[0].lower().strip())] = self._pulse_number

        # We query up to MAX_BELIEFS_PER_QUERY per concept to ensure a wide enough net
        # for skills and feedback.
        for concept in filtered_concepts:
            concept_beliefs = self._gravity_query(
                seed_text=concept,
                exclude=seen_contents,
                max_results=self.MAX_BELIEFS_PER_QUERY,
            )
            # Minimally weight the beliefs retrieved from fallback tool returns
            if using_fallback:
                for b in concept_beliefs:
                    b["gravity"] *= 0.1

            # Add other beliefs to seen_contents so subsequent concepts
            # don't duplicate them (no overlap between concept clusters)
            for b in concept_beliefs:
                if b["category"] != "skills":
                    seen_contents.add(b["content"])
            all_concept_beliefs.extend(concept_beliefs)

        # Deduplicate across concepts (heavier wins on collision)
        merged = self._deduplicate_beliefs(all_concept_beliefs)

        # ── Galaxy-aware selection ────────────────────────────────
        # Group beliefs by nearest galaxy center (lexicon entry),
        # score each galaxy, then pull from the strongest 1-2.
        # This ensures injection focuses on coherent conceptual
        # clusters rather than randomly mixing unrelated beliefs.

        # Separate skills first (always get priority reservation)
        skills_pool = [b for b in merged if b["category"] == "skills"]
        other_pool = [b for b in merged if b["category"] != "skills"]

        # Dynamic budget based on recent tool intensity
        total_budget, max_skills = self._compute_focus_budget()
        selected_skills = skills_pool[:max_skills]
        remaining_budget = total_budget - len(selected_skills)

        # Try galaxy-aware selection on the non-skills pool
        if self._galaxy_map.is_built and other_pool and remaining_budget > 0:
            # Group by nearest galaxy center
            grouped = self._galaxy_map.group_beliefs(other_pool)

            # Score galaxies using the first concept's query position
            # as the focus center. Unscaled — the same convention as
            # stored positions and _gravity_query's seed.
            if concepts and self._belief_cache:
                try:
                    query_pos = self.physics.embed_and_project(concepts[0][:500])
                except Exception:
                    query_pos = np.zeros(8, dtype=np.float32)
            else:
                query_pos = np.zeros(8, dtype=np.float32)

            scored_galaxies = self._galaxy_map.score_galaxies(
                query_pos, grouped,
            )

            # Pull from top galaxies: fill the budget from strongest
            # galaxy first, then second, etc.
            selected_other = []
            for center, score, members in scored_galaxies:
                if len(selected_other) >= remaining_budget:
                    break
                # Sort this galaxy's members by individual gravity
                members.sort(key=lambda x: x.get("gravity", 0), reverse=True)
                space = remaining_budget - len(selected_other)
                selected_other.extend(members[:space])

            # Add unclustered beliefs if budget remains
            unclustered = grouped.get("_unclustered", [])
            if unclustered and len(selected_other) < remaining_budget:
                unclustered.sort(key=lambda x: x.get("gravity", 0), reverse=True)
                space = remaining_budget - len(selected_other)
                selected_other.extend(unclustered[:space])

            logger.debug(
                "Galaxy selection: %d galaxies scored, top=%s",
                len(scored_galaxies),
                scored_galaxies[0][0].term if scored_galaxies else "none",
            )
        else:
            # Fallback: flat gravity sort (no galaxy map available)
            other_pool.sort(key=lambda x: x["gravity"], reverse=True)
            selected_other = other_pool[:remaining_budget]

        # Fill any leftover slots
        leftover = total_budget - (len(selected_skills) + len(selected_other))
        if leftover > 0 and len(other_pool) > len(selected_other):
            extra = [b for b in other_pool if b not in selected_other]
            extra.sort(key=lambda x: x.get("gravity", 0), reverse=True)
            selected_other.extend(extra[:leftover])

        # Combine selection and re-sort by gravity
        final_selection = selected_skills + selected_other
        final_selection.sort(key=lambda x: x["gravity"], reverse=True)
        self._last_selected_beliefs = final_selection

        # Update access in spatial mind for selected beliefs
        belief_space = self.physics.spatial_mind.belief_space
        for b in final_selection:
            bid = b.get("id")
            if bid:
                belief_space.update_access(bid)

        # Accumulate beliefs up to a 500 token budget, then summarize
        this_pulse_beliefs = set()
        belief_texts = []
        token_count = 0
        token_budget = 500

        for b in final_selection:
            content = b["content"]
            if self._is_repetitive(content):
                logger.warning(f"Skipping repetitive belief from injection: {content[:100]}...")
                continue
            
            est_tokens = len(content.split())
            if token_count + est_tokens > token_budget:
                break # Hard cut-off to stay under token cap
                
            belief_texts.append(content)
            token_count += est_tokens
            this_pulse_beliefs.add(content)

        # Track for next pulse's filter
        self._prev_pulse_beliefs.append(this_pulse_beliefs)
        if len(self._prev_pulse_beliefs) > 3:
            self._prev_pulse_beliefs.pop(0)

        logger.info(
            f"Concept-query beliefs: {len(final_selection)} selected "
            f"(skills={len(selected_skills)}, focus_budget={total_budget}) "
            f"from {len(concepts)} concepts (budget={budget}): "
            f"{concepts[:3]}"
        )
        for b in final_selection[:5]:
            logger.info(
                f"  ↳ g={b.get('gravity',0):.2f} m={b.get('mass',0):.1f} "
                f"[{b.get('category','')}] {b.get('content','')}"
            )

        # Compute weighted centroid of selected clusters for attention steering.
        if final_selection:
            positions = []
            weights = []
            for b in final_selection:
                pos = b.get("position_8d")
                if pos is not None:
                    positions.append(pos)
                    weights.append(b.get("gravity", 1.0))
            if positions:
                positions = np.array(positions, dtype=np.float32)
                weights = np.array(weights, dtype=np.float32)
                weights /= weights.sum() + 1e-8
                self._last_cluster_centroid = (positions * weights[:, np.newaxis]).sum(axis=0)
            else:
                self._last_cluster_centroid = None
        else:
            self._last_cluster_centroid = None

        # ── Hebbian plasticity ────────────────────────────────────────
        # Beliefs surfaced together drift slightly toward their shared
        # centroid. Over repeated co-injection, related concepts become
        # spatial neighbors — relations form as geometry, which is what
        # lets gravity retrieval diverge from pure embedding similarity.
        self._hebbian_nudge(final_selection)
        if self._pulse_number % self._hebbian_flush_interval == 0:
            self._flush_hebbian_positions()

        surfaced_ids = [b.get("id", "") for b in final_selection if b.get("id")]

        if not belief_texts:
            return "", []

        # Try to summarize using the local model, otherwise fall back to top belief as-is (truncated to 150 tokens)
        try:
            summary = self.summarizer.summarize(belief_texts, context_type="beliefs")
            annotation = f"*({summary})*"
        except Exception:
            # Fallback: top belief as-is, truncated to 150 tokens
            top_content = belief_texts[0]
            words = top_content.split()
            if len(words) > 150:
                top_content = " ".join(words[:150]) + "..."
            annotation = f"*({top_content})*"

        return annotation, surfaced_ids

    # ── Short-term Memory ────────────────────────────────────────────

    def _pull_recent_memory(self) -> str:
        """Pull the most recent memories for continuity.

        Just the last 3 entries from short-term memory.
        These ensure the model has temporal continuity.

        Each memory is tagged with its timestamp (e.g., "[23:54]")
        so the model can distinguish present from past.
        """
        recent = self.memory.get_recent(limit=6, pulses_back=10)
        if not recent:
            return ""

        lines = []
        for entry in recent:
            if len(lines) >= 3:
                break
            # Skip the agent's own thoughts — they are already the most
            # recent assistant turns in the chat history. Re-injecting
            # them as "recent memories" was an echo channel feeding
            # thought loops. Events/observations stay: they provide the
            # temporal continuity this method exists for.
            if entry.get("memory_type") == "thought":
                continue
            content = entry.get("content", "")
            if not content:
                continue

            # Extract HH:MM timestamp from created_at
            ts_label = ""
            ts_str = entry.get("created_at", "")
            if ts_str:
                try:
                    from dateutil import parser as dp
                    ts = dp.parse(ts_str)
                    ts_label = f"[{ts.strftime('%H:%M')}] "
                except Exception:
                    pass

            condensed = self._condense(content, max_len=150)
            lines.append(f"(recent: {ts_label}{condensed})")

        return "\n".join(lines) if lines else ""

    # ── Contact Context ──────────────────────────────────────────────

    def _pull_contact_context(self, trigger_text: str) -> str:
        """If someone's name appears in the trigger, surface their context."""
        if not self.channel_router:
            return ""

        trigger_lower = trigger_text.lower()
        for name, contact in self.channel_router.contacts.items():
            if name.lower() in trigger_lower:
                channel = contact.get("default_channel", "unknown")
                last = contact.get("last_contact", "never")
                return f"(contact: {name} — default channel: {channel}, last contact: {last})"

        return ""

    # Tool context removed — all tools in system prompt, no mode switching needed

    # ── Utility ──────────────────────────────────────────────────────

    @staticmethod
    def _condense(text: str, max_len: int = 100) -> str:
        """Condense a memory fragment for injection.

        Takes the first meaningful portion, strips noise.
        """
        if not text:
            return ""

        # Strip common prefixes
        for prefix in ["[thought] ", "[event] ", "[system] "]:
            if text.startswith(prefix):
                text = text[len(prefix):]

        # Take first sentence or max_len chars
        text = text.strip()
        if len(text) <= max_len:
            return text

        # Try to break at sentence boundary
        for sep in [". ", "! ", "? ", "\n"]:
            idx = text.find(sep, max_len // 2)
            if 0 < idx < max_len:
                return text[:idx + 1].strip()

        return text[:max_len].strip() + "…"

    def _save_injection_state(self):
        """Save structured injection state for the dashboard UI."""
        import json
        from datetime import datetime
        
        status_path = os.path.join("data", "spatial", "spatial_injection.json")
        os.makedirs(os.path.dirname(status_path), exist_ok=True)
        
        concepts = getattr(self, "_last_concepts", [])
        neighbors = getattr(self, "_last_neighbors", [])
        beliefs = getattr(self, "_last_selected_beliefs", [])
        
        # Format memories
        memories = []
        for n in neighbors:
            rel = n.get("relevance", 0.0)
            if rel > 5.0:
                type_str = "vivid"
            elif rel > 1.0:
                type_str = "related"
            else:
                type_str = "faint"
            memories.append({
                "type": type_str,
                "content": n.get("content", ""),
                "relevance": round(rel, 2)
            })
            
        # Format beliefs
        belief_list = []
        for b in beliefs:
            belief_list.append({
                "content": b.get("content", ""),
                "category": b.get("category", ""),
                "gravity": round(b.get("gravity", 0.0), 2),
                "mass": round(b.get("mass", 0.0), 2)
            })
            
        # Somatic state
        somatic = {}
        if self.sentinel:
            try:
                somatic = {
                    "omega": round(self.sentinel.omega, 3),
                    "s_total": round(self.sentinel.s_total, 3),
                    "severity": self.sentinel.get_severity(),
                    "mode": self.sentinel.get_generation_params().get("mode", "tonic")
                }
            except Exception:
                pass
                
        # Affect state
        affect = {}
        try:
            from core.affect_hook import get_last_result
            res = get_last_result()
            if res:
                affect = {
                    "dominant": res.dominant_affect,
                    "intensity": round(res.field_intensity, 2),
                    "packets": res.contributing_packets
                }
        except Exception:
            pass
            
        data = {
            "concepts": concepts,
            "memories": memories,
            "beliefs": belief_list,
            "somatic": somatic,
            "affect": affect,
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "pulse": self.physics._pulse_count if self.physics else 0,
            "trigger": getattr(self, "_last_trigger_text", ""),
        }
        
        try:
            with open(status_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write spatial_injection.json: {e}")

        # Append to rolling injection history
        history_path = os.path.join("data", "spatial", "spatial_injection_history.json")
        try:
            history = []
            if os.path.exists(history_path):
                with open(history_path) as f:
                    loaded = json.load(f)
                    if isinstance(loaded, list):
                        history = loaded
            history.append(data)
            history = history[-self.INJECTION_HISTORY_LIMIT:]
            with open(history_path, "w") as f:
                json.dump(history, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write spatial_injection_history.json: {e}")

    @staticmethod
    def _is_repetitive(text: str, max_repeats: int = 3) -> bool:
        """Detect if the text contains high repetition of short phrases/sentences.

        This prevents database pollution (runaway feedback loops) where a previously
        looped memory gets retrieved and injected, triggering the model to loop again.
        """
        if not text:
            return False

        # Match parenthesized annotations or other repeated substrings
        patterns = [
            r"\*\([^\)]+\)\*",  # *(annotation)*
            r"\([^\)]+\)",      # (annotation)
        ]

        # Check for exact repetitions of parenthesized blocks
        for pattern in patterns:
            try:
                matches = re.findall(pattern, text)
                if len(matches) > max_repeats:
                    # Count frequencies of each match
                    from collections import Counter
                    counts = Counter(matches)
                    if any(count >= max_repeats for count in counts.values()):
                        return True
            except Exception:
                pass

        # Check general line/sentence repetitions
        sentences = [s.strip() for s in re.split(r"[.!?\n]", text) if len(s.strip()) > 10]
        if len(sentences) > max_repeats * 2:
            try:
                from collections import Counter
                counts = Counter(sentences)
                if any(count >= max_repeats for count in counts.values()):
                    return True
            except Exception:
                pass

        return False
