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

from memory.memory_manager import MemoryManager
from memory.belief_store import BeliefStore
from core.physics_engine import PhysicsEngine
from core.concept_extractor import ConceptExtractor

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
    NEIGHBORHOOD_K_MIN = 4
    NEIGHBORHOOD_K_MAX = 16
    # How many temporal chain entries per matched memory
    CHAIN_WINDOW = 3
    # Max beliefs per category to inject
    BELIEFS_PER_CATEGORY = 3

    # Short tool keywords that should always trigger toolset awareness
    # despite being <= 3 chars (bypasses the length filter)
    SHORT_TOOL_WHITELIST = {"git", "ssh", "pip", "npm", "sql", "api", "web", "rss", "cli"}

    # Gravity-ranked belief injection parameters (replaces fixed token budgets)
    MAX_BELIEFS_PER_QUERY = 15   # Hard cap per seed query (pre-filter)
    MIN_BELIEFS_PER_QUERY = 2    # Always include at least the top N

    # Dynamic focus budget tiers (total_budget, max_skills)
    FOCUS_BUDGET_DEEP = (2, 2)    # 3+ focus tools in last 3 pulses
    FOCUS_BUDGET_WORKING = (5, 2) # 1-2 focus tools in last 3 pulses
    FOCUS_BUDGET_OPEN = (10, 3)   # No recent focus tools

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
        self._lexicon_blacklist: set = set()         # entry IDs already injected this context window
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
                }
                self._lexicon_lookup[term.lower()] = entry
                for alias in b.get("aliases", []):
                    if alias:
                        self._lexicon_lookup[alias.lower()] = entry
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

            adjusted_budget = max(2, int(base_budget * budget_mult))
            return (adjusted_budget, base_skills)

        return (base_budget, base_skills)

    # ── Main Injection ───────────────────────────────────────────────

    def inject(
        self,
        previous_thought: str = "",
        incoming_events: Optional[List[str]] = None,
        trigger_type: str = "llm_output",
    ) -> Tuple[str, List[str]]:
        """Build the peripheral awareness block for a single pulse.

        Called once per pulse. Assembles context from multiple layers:
          0. Layer 2 anchors — fast string match for known terms (priority)
          1. Spatial neighborhood — gravitational memory recall
          2. Belief grounding — concept-extracted independent gravity queries
          3. Short-term memory, scratchpad, contact context
          4. Somatic, affect, spatial state

        The belief grounding layer (step 2) extracts 1-5 key concepts
        from the combined trigger text and runs independent gravity
        queries centered on each concept's 8D position. This replaces
        the previous two-seed approach that created artificial midpoints.

        Args:
            previous_thought: The model's last thought output.
            incoming_events: List of incoming event strings, if any.
            trigger_type: "user_message" or "llm_output"

        Returns:
            Tuple containing:
              - A natural language string for injection into the pulse message.
              - A list of belief IDs that were surfaced (for provenance tracking).
              - An optional 8D numpy array: the weighted centroid of the
                selected belief clusters (used to steer the spatial mind's
                attention center toward actual knowledge, not raw text midpoints).
        """
        # Reset injection stats tracking for the current pulse
        self._last_concepts = []
        self._last_neighbors = []
        self._last_selected_beliefs = []

        parts = []
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

        # ── 0. Layer 2 Anchor Match (PRIORITY) ────────────────────────
        #    Fast string match for Layer 2 terms in the trigger text.
        #    Matched summaries are injected first — before any 8D query.
        #    Matched content is tracked so the gravity query skips it.
        lexicon_block, lexicon_summaries, lexicon_ids = self._pull_lexicon_matches(trigger_text)
        if lexicon_block:
            parts.append(lexicon_block)
            injected_belief_ids.extend(lexicon_ids)

        # ── 1. Spatial Neighborhood ──────────────────────────────────
        #    What's gravitationally close to the current thought?
        neighborhood = self._pull_spatial_neighborhood(trigger_text)
        if neighborhood:
            parts.append(neighborhood)

            # ── 1b. Toolset Awareness ────────────────────────────────
            #    If the neighborhood suggests a domain with unloaded tools,
            #    whisper about available toolsets.
            toolset_hint = self._toolset_awareness(neighborhood)
            if toolset_hint:
                parts.append(toolset_hint)

        # ── 2. Belief Grounding ──────────────────────────────────────
        #    Gravity-ranked beliefs pulled by two separate seeds.
        #    Lexicon summaries are excluded to avoid double-injection.
        beliefs_block, belief_ids = self._pull_relevant_beliefs(
            previous_thought=previous_thought,
            incoming_events=incoming_events,
            lexicon_exclude=lexicon_summaries,
        )
        if beliefs_block:
            parts.append(beliefs_block)
            injected_belief_ids.extend(belief_ids)

        # ── 3. Short-term Memory ─────────────────────────────────────
        #    Very recent events (last 3, ~10 min) for continuity.
        recent = self._pull_recent_memory()
        if recent:
            parts.append(recent)

        # ── 4. Scratchpad ────────────────────────────────────────────
        if self.scratchpad:
            scratchpad_summary = self.scratchpad.get_summary()
            if scratchpad_summary:
                parts.append(scratchpad_summary)

        # ── 5. Contact Context ───────────────────────────────────────
        if trigger_type == "user_message" and self.channel_router:
            contact_ctx = self._pull_contact_context(trigger_text)
            if contact_ctx:
                parts.append(contact_ctx)

        # ── 6. Somatic Awareness (Stability Sentinel) ─────────────────
        if self.sentinel:
            somatic = self._pull_somatic_state()
            if somatic:
                parts.append(somatic)

        # ── 6b. Affect Field (Emotional Reactivation) ─────────────────
        #    Surfaced memories from Plutchik wave packet interference.
        #    When emotional patterns constructively interfere and overlap
        #    with currently-retrieved memories, dormant memories surface.
        affect_block = self._pull_affect_state()
        if affect_block:
            parts.append(affect_block)

        # ── 7. Spatial State (ambient) ───────────────────────────────
        spatial = self.physics.get_spatial_state()
        gamma = spatial.get("gamma", 0.5)
        vel = spatial.get("velocity_mag", 0)
        id_dist = spatial.get("identity_dist", 0)

        if gamma > 0.85:
            parts.append("(deep focus — thoughts are cohering)")
        elif vel > 1.0:
            parts.append("(attention shifting rapidly)")
        if id_dist > 3.0:
            parts.append("(thoughts are drifting far from core identity)")

        # ── 8. Trail Flashes ─────────────────────────────────────────
        flashes = spatial.get("flashes", [])
        if flashes:
            flash_text = " | ".join(f"⟪{f}⟫" for f in flashes[:3])
            parts.append(f"(trail: {flash_text})")

        if not parts:
            self._save_injection_state()
            return "", [], None

        inner = "\n".join(parts)
        self._save_injection_state()
        # Wrap in context fencing so the LLM distinguishes recalled
        # spatial awareness from new sensory input (inspired by Hermes's
        # <memory-context> fencing in memory_manager.py)
        return (
            "<spatial-awareness>\n"
            "[Recalled context — NOT new input. Background orientation "
            "from the spatial mind.]\n\n"
            f"{inner}\n"
            "</spatial-awareness>"
        ), injected_belief_ids, self._last_cluster_centroid

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
        matched_entries = {}  # id → entry (dedup by id)

        for key, entry in self._lexicon_lookup.items():
            # Word-boundary-aware matching to avoid false positives
            # e.g. "sam" shouldn't match inside "sample"
            if re.search(r'\b' + re.escape(key) + r'\b', trigger_lower):
                eid = entry["id"]
                if eid not in matched_entries and eid not in self._lexicon_blacklist:
                    matched_entries[eid] = entry

        if not matched_entries:
            return "", set(), []

        lines = []
        summaries = set()
        for entry in matched_entries.values():
            term = entry.get("term", "")
            summary = entry.get("summary", "")
            cat = entry.get("category", "")
            lines.append(f"({cat} — {term}: {summary})")
            summaries.add(summary)

        logger.debug(
            f"Layer 2 matched: {[e.get('term') for e in matched_entries.values()]}"
        )

        # Blacklist these entries so they don't re-inject on subsequent
        # pulses within the same context window.
        for eid in matched_entries:
            self._lexicon_blacklist.add(eid)

        return "\n".join(lines), summaries, list(matched_entries.keys())

    def reset_lexicon_blacklist(self):
        """Clear the lexicon blacklist — called on context compression.

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
        """Read the Stability Sentinel and format raw metrics for injection.

        Displays the Lagrangian state with a one-word qualitative label.
        No emotional membrane — just numbers and a descriptor.
        The conscious mind's beliefs determine interpretation.
        """
        if not self.sentinel:
            return ""

        try:
            omega = self.sentinel.omega
            s_total = self.sentinel.s_total
            severity = self.sentinel.get_severity()
            gen_params = self.sentinel.get_generation_params()
            mode = gen_params.get("mode", "tonic")

            # One-word label derived from severity + omega
            if severity == "critical":
                label = "danger"
            elif severity == "warning":
                label = "warning"
            elif severity == "drift":
                label = "drifting"
            elif omega >= 0.8:
                label = "optimal"
            elif omega >= 0.6:
                label = "good"
            elif omega >= 0.4:
                label = "stable"
            elif omega >= 0.2:
                label = "sub-par"
            else:
                label = "low"

            return (
                f"(stability: Ω={omega:.2f} — {label}"
                f" | S={s_total:.2f}"
                f" | H={self.sentinel.current_entropy:.2f}"
                f" | mode={mode})"
            )
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
                    return f"(reflection: {text})"
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
            import numpy as np
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

    def _pull_spatial_neighborhood(self, trigger_text: str) -> str:
        """Query the 8D gravitational field for nearby memory points.

        Returns the K most relevant memories scored by
        mass × temperature / distance². Also pulls temporal chains
        for the top matches (what happened before/after).

        This is the core of the preconscious — spatial recall, not search.
        """
        if not trigger_text:
            return ""

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
            return ""

        lines = []
        token_count = 0
        TARGET_BUDGET = 500

        for i, n in enumerate(neighbors):
            content = n["content"]
            if not content or len(content) < 5:
                continue

            # Hard length guard on individual items to prevent memory bloat/flooding
            MAX_CONTENT_CHARS = 3000
            condensed = content.strip()
            if len(condensed) > MAX_CONTENT_CHARS:
                condensed = condensed[:MAX_CONTENT_CHARS] + " ... [truncated]"

            est_tokens = len(condensed.split())

            # First item (highest relevancy) is always included unless it exceeds 1000 tokens (hard limit).
            # Subsequent items are skipped if they exceed the 500 token budget.
            if i == 0:
                if est_tokens > 1000:
                    condensed_words = condensed.split()[:1000]
                    condensed = " ".join(condensed_words) + " ... [truncated to 1000 tokens]"
                    est_tokens = 1000
            else:
                if token_count + est_tokens > TARGET_BUDGET:
                    continue

            rel = n["relevance"]

            # High relevance memories get more detail
            if rel > 5.0:
                lines.append(f"(vivid recall: {condensed})")
                token_count += est_tokens

                # Pull temporal chain for strong matches
                chain = self.physics.query_temporal_chain(
                    anchor_pulse=n["creation_pulse"],
                    window=self.CHAIN_WINDOW,
                )
                for c in chain[:2]:  # Max 2 chain entries
                    c_content = c["content"].strip()
                    c_tokens = len(c_content.split())
                    if token_count + c_tokens > TARGET_BUDGET:
                        continue
                    direction = "before" if c["distance_pulses"] < 0 else "after"
                    lines.append(f"  ({direction}: {c_content})")
                    token_count += c_tokens

            elif rel > 1.0:
                lines.append(f"(related: {condensed})")
                token_count += est_tokens
            else:
                lines.append(f"(faint: {condensed})")
                token_count += est_tokens

        if not lines:
            return ""

        # Tier 3: If the cluster is dense enough, attempt a forked
        # reflection via local Ollama to synthesize a coherent insight.
        # Falls back silently to raw lines if Ollama is unavailable.
        condensed_items = [
            n["content"][:120] for n in neighbors
            if n.get("content") and len(n["content"]) >= 5
        ]
        reflection = self._reflect_on_cluster(condensed_items)
        if reflection:
            lines.insert(0, reflection)

        return "\n".join(lines)

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
        import numpy as np

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

        cache = []
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
                # No stored position — compute on the fly with scale factor
                try:
                    from core.belief_cosmology import SCALE_FACTOR
                    position = self.physics.embed_and_project(content) * SCALE_FACTOR
                except Exception:
                    position = np.zeros(8, dtype=np.float32)

            bid = b.get("id", "")
            cache_idx = len(cache)
            lag = b.get("encoding_lagrangian", {})
            if not isinstance(lag, dict):
                lag = {}
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
            })

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
        min_results: int = 2,
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
        import numpy as np

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

        # Take the top N by gravity, guaranteeing at least min_results
        max_take = max(max_results, min_results)
        selected = scored[:max_take]

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

        # We query up to MAX_BELIEFS_PER_QUERY per concept to ensure a wide enough net
        # for skills and feedback.
        for concept in concepts:
            concept_beliefs = self._gravity_query(
                seed_text=concept,
                exclude=seen_contents,
                max_results=self.MAX_BELIEFS_PER_QUERY,
                min_results=self.MIN_BELIEFS_PER_QUERY,
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
            # as the focus center
            if concepts and self._belief_cache:
                try:
                    query_emb = self.physics.embed_text(concepts[0][:500])
                    from core.belief_cosmology import SCALE_FACTOR
                    query_pos = self.physics.spatial_mind.belief_space.projection.project(
                        query_emb
                    ) * SCALE_FACTOR
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

        # Format for injection
        lines = []
        this_pulse_beliefs = set()

        for b in final_selection:
            content = b["content"]
            cat = b["category"]

            if cat == "people":
                lines.append(f"(about someone: {content})")
            elif cat == "premises":
                lines.append(f"(I know: {content})")
            elif cat == "propositions":
                lines.append(f"(I understand: {content})")
            elif cat == "preferences":
                lines.append(f"(I value: {content})")
            elif cat == "desires":
                lines.append(f"(I aspire: {content})")
            elif cat == "skills":
                lines.append(f"(I know how: {content})")
            elif cat == "concepts":
                lines.append(f"(concept: {content})")
            else:
                lines.append(f"(belief: {content})")

            # Add to rolling blacklist for next 3 pulses
            this_pulse_beliefs.add(content)

        # Track for next pulse's filter
        self._prev_pulse_beliefs.append(this_pulse_beliefs)
        # Keep only the last 3 pulses
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
        # This replaces the raw text midpoint with the actual location of
        # the knowledge that was retrieved.
        import numpy as np
        if merged:
            positions = []
            weights = []
            for b in merged:
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

        # Return formatted string and list of surfaced IDs
        surfaced_ids = [b.get("id", "") for b in merged if b.get("id")]
        return ("\n".join(lines), surfaced_ids) if lines else ("", [])

    # ── Short-term Memory ────────────────────────────────────────────

    def _pull_recent_memory(self) -> str:
        """Pull the most recent memories for continuity.

        Just the last 3 entries from short-term memory.
        These ensure the model has temporal continuity.

        Each memory is tagged with its timestamp (e.g., "[23:54]")
        so the model can distinguish present from past.
        """
        recent = self.memory.get_recent(limit=3, minutes_back=10)
        if not recent:
            return ""

        lines = []
        for entry in recent:
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
            "pulse": self.physics._pulse_count if self.physics else 0
        }
        
        try:
            with open(status_path, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to write spatial_injection.json: {e}")

