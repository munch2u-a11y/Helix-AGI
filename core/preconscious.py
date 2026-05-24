"""
Helix — Preconscious System (Concept-Based Spatial-Gravitational Memory Query)

The preconscious is the bridge between the spatial mind and the
conscious LLM. On every pulse, it queries the 384D gravitational
field and returns a contextually relevant "net" of memories,
beliefs, and state — NOT keyword matches, but the gravitational
neighborhood around the current focus.

How it works:
  1. Takes the trigger text (last thought + incoming events)
  2. Extracts 1-5 key concepts via RAKE-style keyphrase extraction
  3. Embeds each concept independently into 384D cognitive space
  4. Runs independent gravity queries centered on each concept:
     - Nearby beliefs scored by mass × temperature / distance²
     - No overlap between concept clusters (rolling blacklist)
  5. Pulls lexicon matches, scratchpad, and contact context
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
    MAX_BELIEFS_PER_QUERY = 15   # Hard cap per seed query
    MIN_BELIEFS_PER_QUERY = 2    # Always include at least the top N

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
        self._belief_cache = []       # list of {content, mass, category, embedding}
        self._belief_cache_count = 0  # track belief store size for invalidation
        self._belief_cache_mass = 0.0 # track total mass for invalidation

        # Previous pulse belief tracking — filter these out next pulse
        # to avoid repeating the same beliefs in consecutive pulses.
        self._prev_pulse_beliefs = []  # list of sets, each containing content strings from previous pulses

        # Weighted centroid of the last pulse's selected belief clusters.
        # Passed to the physics engine to steer attention toward actual
        # knowledge locations rather than raw text midpoints.
        self._last_cluster_centroid = None

        # Lexicon — priority term-matched dictionary loaded once.
        # Scanned every pulse BEFORE the 8D gravity query.
        self._lexicon_lookup: Dict[str, dict] = {}  # term_lower → entry
        self._lexicon_blacklist: set = set()         # entry IDs already injected this context window
        self._load_lexicon()

        # Concept extractor — RAKE-style keyphrase extraction.
        # Initialized with lexicon keys so it can separate known entities
        # from general concepts during extraction.
        lexicon_keys = set(self._lexicon_lookup.keys())
        self._concept_extractor = ConceptExtractor(lexicon_keys=lexicon_keys)

    def _load_lexicon(self):
        """Load lexicon.json and build a case-insensitive term→entry lookup.

        Each entry's `term` and all `aliases` become keys pointing to
        the same entry. Called once on init.
        """
        lexicon_path = os.path.join(self.beliefs.data_dir, "lexicon.json")
        if not os.path.exists(lexicon_path):
            logger.info("No lexicon.json found — lexicon disabled")
            return

        try:
            with open(lexicon_path, 'r') as f:
                entries = json.load(f)

            for entry in entries:
                term = entry.get("term", "")
                if term:
                    self._lexicon_lookup[term.lower()] = entry
                for alias in entry.get("aliases", []):
                    if alias:
                        self._lexicon_lookup[alias.lower()] = entry

            logger.info(
                f"Lexicon loaded: {len(entries)} entries, "
                f"{len(self._lexicon_lookup)} lookup keys"
            )
        except Exception as e:
            logger.warning(f"Failed to load lexicon: {e}")

    # ── Main Injection ───────────────────────────────────────────────

    def inject(
        self,
        previous_thought: str = "",
        incoming_events: Optional[List[str]] = None,
        trigger_type: str = "llm_output",
    ) -> Tuple[str, List[str]]:
        """Build the peripheral awareness block for a single pulse.

        Called once per pulse. Assembles context from multiple layers:
          0. Lexicon — fast string match for known terms (priority)
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
        parts = []
        injected_belief_ids = []

        # Build combined trigger for spatial neighborhood query
        trigger_text = previous_thought
        if incoming_events:
            trigger_text = " ".join(incoming_events) + " " + previous_thought

        # ── 0. Lexicon Match (PRIORITY) ──────────────────────────────
        #    Fast string match for lexicon terms in the trigger text.
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
            return "", [], None

        inner = "\n".join(parts)
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

    # ── Lexicon Match ─────────────────────────────────────────────────

    def _pull_lexicon_matches(self, trigger_text: str) -> Tuple[str, set, List[str]]:
        """Scan trigger text for lexicon terms and return matched summaries.

        Fast case-insensitive string matching — no embeddings, no API calls.
        Returns (formatted_block, set_of_summary_strings) so the gravity
        query can exclude lexicon content from its results.

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

            if cat == "person":
                lines.append(f"(lexicon — {term}: {summary})")
            else:
                lines.append(f"(lexicon — {term}: {summary})")

            summaries.add(summary)

        logger.debug(
            f"Lexicon matched: {[e.get('term') for e in matched_entries.values()]}"
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
        """Query the 384D gravitational field for nearby belief points.

        Returns the K most relevant beliefs scored by
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

        if not neighbors:
            return ""

        lines = []
        token_count = 0
        TARGET_BUDGET = 500

        for i, n in enumerate(neighbors):
            content = n["content"]
            if not content or len(content) < 5:
                continue

            # No hard truncation on individual items
            condensed = content.strip()
            est_tokens = len(condensed.split())

            # First item (highest relevancy) is always included regardless of budget.
            # Subsequent items are skipped if they exceed the 500 token budget.
            if i > 0 and token_count + est_tokens > TARGET_BUDGET:
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

        Embeds all beliefs into 384D space once, then reuses the positions
        on every pulse. Rebuilds if belief count OR total mass changes
        (catches merges, attrition, confidence decay, content changes).
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
        for b in all_beliefs:
            content = b.get("content", "")
            if not content or len(content) < 5:
                continue

            try:
                position = self.physics.embed(content)
            except Exception:
                position = np.zeros(384, dtype=np.float32)

            cache.append({
                "id": b.get("id", ""),
                "content": content,
                "mass": b.get("mass", 1.0),
                "category": b.get("_category", ""),
                "embedding": position,
            })

        self._belief_cache = cache
        self._belief_cache_count = current_count
        self._belief_cache_mass = current_mass
        logger.info(f"Belief position cache built: {len(cache)} entries")

    def _gravity_query(
        self,
        seed_text: str,
        exclude: set,
        max_results: int = 15,
        min_results: int = 2,
    ) -> List[Dict[str, Any]]:
        """Score cached beliefs by cognitive gravity against a seed text.

        Returns the top beliefs sorted by gravity descending. The gravity
        ranking itself is the filter — no token budgets. The strongest
        gravitational pulls are always included, capped at max_results.

        Args:
            seed_text: Text to embed as the query center.
            exclude: Set of content strings to skip (previous pulse, etc).
            max_results: Hard cap on returned beliefs.
            min_results: Always return at least this many (if available).
        """
        import numpy as np

        if not seed_text or not seed_text.strip():
            return []

        # Embed the seed into 384D
        try:
            query_pos = self.physics.embed(seed_text[:500])
        except Exception:
            return []

        # Score each cached belief
        scored = []
        for b in self._belief_cache:
            content = b["content"]
            if content in exclude:
                continue

            dist_sq = float(np.sum((b["embedding"] - query_pos) ** 2))
            gravity = b["mass"] / (dist_sq + 1e-4)

            scored.append({
                "id": b.get("id", ""),
                "content": content,
                "gravity": gravity,
                "category": b["category"],
                "mass": b["mass"],
                "embedding": b["embedding"],
            })

        # Sort by gravity descending — strongest pulls first
        scored.sort(key=lambda x: x["gravity"], reverse=True)

        # Take the top N by gravity, guaranteeing at least min_results
        selected = scored[:max(max_results, min_results)]

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
          2. Embed each concept independently → 384D position.
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
        trigger_text = previous_thought
        if incoming_events:
            trigger_text = " ".join(incoming_events) + " " + previous_thought

        # Extract key concepts (dynamic budget based on input richness)
        extraction = self._concept_extractor.extract(trigger_text)
        concepts = extraction["concepts"]
        budget = extraction["budget"]

        if not concepts:
            # Fallback: if extractor finds nothing substantive, use the
            # raw trigger (truncated) as a single seed. This covers edge
            # cases like very short inputs or heavy stop-word text.
            concepts = [trigger_text[:200]] if trigger_text.strip() else []

        if not concepts:
            return "", []

        # Exclude beliefs from the previous 3 pulses + lexicon summaries
        exclude = set().union(*self._prev_pulse_beliefs) if self._prev_pulse_beliefs else set()
        if lexicon_exclude:
            exclude |= lexicon_exclude

        # Run independent gravity queries per concept
        all_concept_beliefs = []
        seen_contents = set(exclude)  # rolling blacklist across concepts

        # Distribute the belief budget across concepts
        per_concept_max = max(
            self.MIN_BELIEFS_PER_QUERY,
            self.MAX_BELIEFS_PER_QUERY // max(len(concepts), 1),
        )

        for concept in concepts:
            concept_beliefs = self._gravity_query(
                seed_text=concept,
                exclude=seen_contents,
                max_results=per_concept_max,
                min_results=self.MIN_BELIEFS_PER_QUERY,
            )
            # Add to rolling blacklist so the next concept doesn't
            # pull the same beliefs (no overlap between clusters)
            for b in concept_beliefs:
                seen_contents.add(b["content"])
            all_concept_beliefs.extend(concept_beliefs)

        # Deduplicate across concepts (heavier wins on collision)
        merged = self._deduplicate_beliefs(all_concept_beliefs)

        # Re-sort merged results by gravity
        merged.sort(key=lambda x: x["gravity"], reverse=True)

        # Format for injection
        lines = []
        this_pulse_beliefs = set()

        for b in merged:
            content = b["content"]
            cat = b["category"]

            if cat == "people":
                lines.append(f"(about someone: {content})")
            elif cat == "knowledge":
                lines.append(f"(I understand: {content})")
            elif cat == "preferences":
                lines.append(f"(I want: {content})")
            elif cat == "capabilities":
                lines.append(f"(I can: {content})")
            elif cat == "self_identity":
                lines.append(f"(I am: {content})")
            elif cat == "skills":
                lines.append(f"(I know how: {content})")
            elif cat == "feedback":
                lines.append(f"(I've learned: {content})")
            else:
                lines.append(f"(belief: {content})")

            this_pulse_beliefs.add(content)

        # Track for next pulse's filter
        self._prev_pulse_beliefs.append(this_pulse_beliefs)
        # Keep only the last 3 pulses
        if len(self._prev_pulse_beliefs) > 3:
            self._prev_pulse_beliefs.pop(0)

        logger.info(
            f"Concept-query beliefs: {len(merged)} selected "
            f"from {len(concepts)} concepts (budget={budget}): "
            f"{concepts[:3]}"
        )
        for b in merged[:5]:
            logger.info(
                f"  ↳ g={b.get('gravity',0):.2f} m={b.get('mass',0):.1f} "
                f"[{b.get('category','')}] {b.get('content','')[:80]}"
            )

        # Compute weighted centroid of selected clusters for attention steering.
        # This replaces the raw text midpoint with the actual location of
        # the knowledge that was retrieved.
        import numpy as np
        if merged:
            positions = []
            weights = []
            for b in merged:
                pos = b.get("embedding")
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
        """
        recent = self.memory.get_recent(limit=3, minutes_back=10)
        if not recent:
            return ""

        lines = []
        for entry in recent:
            content = entry.get("content", "")
            if content:
                condensed = self._condense(content, max_len=150)
                lines.append(f"(recent: {condensed})")

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
