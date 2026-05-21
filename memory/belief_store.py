"""
Helix — Categorized Belief Store

Manages beliefs as categorized .json lists for efficient parallel
pre-conscious injection. Each category is its own file, allowing the
subconscious/pre-conscious to pull exactly the right type of belief
context for the current moment without scanning a monolithic list.

Categories:
  - self_identity.json    → Who Helix is, core personality traits
  - people.json           → Profiles and relational knowledge about individuals
  - capabilities.json     → Learned abilities, problem-solving patterns, multi-tool chains
  - knowledge.json        → Deeply verified objective facts (high-mass, high-confidence)
  - skills.json           → Procedural knowledge: HOW to do things (workflows, tool chains)
  - preferences.json      → Desires, likes, goals, motivations (replaces desires.json)
  - feedback.json         → Lessons from experiences: rule + why + how to apply
  - desires.json          → [MIGRATION] Legacy — being migrated to preferences.json

Each belief entry includes:
  - id: unique identifier
  - content: the belief text
  - mass: computed from cognitive mass equation (m_s + m_a)
  - confidence: 0.0-1.0 (computed nightly by Cognitive Attrition equation)
  - verifications: float — reaffirmation count (drives V component of attrition)
  - stability_index: 0.0-1.0 — destabilizing (0) to stabilizing (1)
  - relations: list[str] — IDs of logically related beliefs
  - memory_refs: list[str] — IDs of source memories
  - position_8d: list[float] — permanent 8D manifold coordinates
  - encoding_lagrangian: dict — somatic state at encoding {omega, s_total, H, D_KL}
  - created_at: ISO 8601 timestamp
  - last_accessed: ISO 8601 timestamp
  - access_count: times relied upon
  - source: what formed this belief

Cognitive Mass Equation (from δ∫(H + λ·D_KL)dt = 0):
  Mass = m_s + m_a
  m_s = confidence                    (intrinsic structural mass)
  m_a = Ω_encoding × (1 - s_total) × (0.5 + stability)   (affective charge)

  NOTE: relation count is deliberately excluded from individual mass.
  Cluster gravity emerges from spatial density — related beliefs near
  each other in 8D space naturally concentrate gravitational potential
  on nearby anchors. Individual mass inflation from relations caused
  a self-reinforcing loop: relations → mass ↑ → gravity ↑ → co-injection → more relations.

Cognitive Attrition Equation (nightly):
  C = min(1.0, (Base + w_T + w_R + w_V) × (0.5 + S))
  Where: T=time held, R=reliance (inbound refs), V=verifications, S=stability
"""

import json
import os
import math
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any

logger = logging.getLogger("helix.memory.belief_store")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


# Belief category definitions
# NOTE: capabilities and desires are kept during migration to the
# new taxonomy. Once manual review is complete, remove them and
# update any references.
BELIEF_CATEGORIES = {
    "self_identity": "self_identity.json",
    "people": "people.json",
    "capabilities": "capabilities.json",   # Migration: split into skills + retained capabilities
    "desires": "desires.json",              # Migration: moving to preferences
    "knowledge": "knowledge.json",
    "skills": "skills.json",                # NEW — procedural HOW-TO knowledge
    "preferences": "preferences.json",      # NEW — replaces desires
    "feedback": "feedback.json",            # NEW — lessons from experiences
}

# Template for a person profile entry (stored within people.json)
PERSON_PROFILE_TEMPLATE = {
    "name": "",
    "relationship": "",
    "traits": [],
    "communication_style": "",
    "last_contact": "",
    "notes": "",
}


class BeliefStore:
    """Categorized belief management with individual .json files per category.

    The conscious mind can save newly formed beliefs here.
    The pre-conscious system pulls from specific categories to assemble
    the richest possible context for each moment.
    """

    # Mass threshold for a belief to be considered "deeply held" (objective knowledge)
    DEEP_CONVICTION_MASS = 5.0

    def __init__(self, data_dir: str):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self._ensure_files()

    def generate_id(self, category: str) -> str:
        """Generate a uniform belief ID: {prefix}_{YYYYMMDD}_{sequence}.
        
        Example: kno_20260515_001
        """
        prefix = category[:3].lower()
        if category == "knowledge":
            prefix = "kno"
        date_str = datetime.now().strftime("%Y%m%d")
        
        # Determine sequence by counting today's beliefs in this category
        beliefs = self._read_category(category)
        today_prefix = f"{prefix}_{date_str}_"
        seq = 1
        for b in beliefs:
            if b.get("id", "").startswith(today_prefix):
                seq += 1
                
        return f"{today_prefix}{seq:03d}"

    def _ensure_files(self):
        """Create empty category files if they don't exist."""
        for category, filename in BELIEF_CATEGORIES.items():
            filepath = os.path.join(self.data_dir, filename)
            if not os.path.exists(filepath):
                with open(filepath, 'w') as f:
                    json.dump([], f, indent=2)

    def _read_category(self, category: str) -> List[Dict[str, Any]]:
        """Read all beliefs from a category file."""
        filename = BELIEF_CATEGORIES.get(category)
        if not filename:
            logger.warning(f"Unknown belief category: {category}")
            return []
        filepath = os.path.join(self.data_dir, filename)
        try:
            with open(filepath, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
            return []

    def _write_category(self, category: str, beliefs: List[Dict[str, Any]]):
        """Write all beliefs to a category file."""
        filename = BELIEF_CATEGORIES.get(category)
        if not filename:
            return
        filepath = os.path.join(self.data_dir, filename)
        try:
            with open(filepath, 'w') as f:
                json.dump(beliefs, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write {filepath}: {e}")

    # ── Write Operations ─────────────────────────────────────────────

    def add_belief(
        self,
        category: str,
        belief_id: str,
        content: str,
        mass: float = 1.0,
        confidence: float = 0.5,
        source: str = "system",
        generation: int = None,
        component_ids: list = None,
        verifications: float = 1.0,
        stability_index: float = 0.5,
        relations: list = None,
        memory_refs: list = None,
        position_8d: list = None,
        encoding_lagrangian: dict = None,
    ) -> bool:
        """Add a new belief to a category.

        Returns True if added, False if duplicate id exists.

        Args:
            category: Belief category (self_identity, people, etc.)
            belief_id: Unique identifier
            content: The belief text
            mass: Gravitational weight (computed from cognitive mass eq)
            confidence: 0.0-1.0 (initial, recomputed nightly by attrition eq)
            source: What formed this belief
            generation: Dream engine pass number (0=memory, 1=simple, 2+=compound)
            component_ids: IDs of beliefs/memories this was synthesized from
            verifications: Times reaffirmed (drives V in attrition equation)
            stability_index: 0.0 (destabilizing) to 1.0 (stabilizing)
            relations: IDs of logically related beliefs
            memory_refs: IDs of source memories (provenance)
            position_8d: 8D manifold coordinates [x0..x7]
            encoding_lagrangian: Somatic state at encoding {omega, s_total, H, D_KL}
        """
        beliefs = self._read_category(category)

        # Check for duplicate
        for b in beliefs:
            if b.get("id") == belief_id:
                logger.debug(f"Belief {belief_id} already exists in {category}")
                return False

        now = _now_iso()
        belief = {
            "id": belief_id,
            "content": content,
            "mass": mass,
            "confidence": max(0.0, min(1.0, confidence)),
            "source": source,
            "created_at": now,
            "last_accessed": now,
            "access_count": 0,
            "verifications": float(verifications),
            "stability_index": float(stability_index),
            "relations": relations or [],
            "memory_refs": memory_refs or [],
            "position_8d": position_8d,
            "encoding_lagrangian": encoding_lagrangian or {
                "omega": 0.5, "s_total": 0.15, "H": 0.15, "D_KL": 0.0,
            },
        }

        # Optional dream engine metadata
        if generation is not None:
            belief["generation"] = generation
        if component_ids:
            belief["component_ids"] = component_ids

        beliefs.append(belief)
        self._write_category(category, beliefs)
        logger.info(f"Added belief '{belief_id}' to {category} (mass={mass}, conf={confidence:.2f})")
        return True

    def update_belief_mass(self, category: str, belief_id: str, mass_delta: float):
        """Increase or decrease a belief's mass (gravitational weight)."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["mass"] = max(0.1, b.get("mass", 1.0) + mass_delta)
                b["last_accessed"] = _now_iso()
                b["access_count"] = b.get("access_count", 0) + 1
                self._write_category(category, beliefs)
                return
        logger.debug(f"Belief {belief_id} not found in {category}")

    def touch_belief(self, category: str, belief_id: str):
        """Increment access_count and update last_accessed for a belief."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["access_count"] = b.get("access_count", 0) + 1
                b["last_accessed"] = _now_iso()
                # Access drives temperature (recency heat) not permanent mass.
                # Mass is intrinsic — only confidence and affective charge.
                self._write_category(category, beliefs)
                return

    def remove_belief(self, category: str, belief_id: str) -> bool:
        """Remove a belief from a category. Returns True if found and removed."""
        beliefs = self._read_category(category)
        original_count = len(beliefs)
        beliefs = [b for b in beliefs if b.get("id") != belief_id]
        if len(beliefs) < original_count:
            self._write_category(category, beliefs)
            logger.info(f"Removed belief '{belief_id}' from {category}")
            return True
        return False

    def archive_belief(self, category: str, belief_id: str) -> bool:
        """Archive a belief by setting its mass to 0.01 and tagging it."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["mass"] = 0.01
                tags = b.get("tags", [])
                if "archived" not in tags:
                    tags.append("archived")
                b["tags"] = tags
                b["last_accessed"] = _now_iso()
                self._write_category(category, beliefs)
                logger.info(f"Archived belief '{belief_id}' in {category}")
                return True
        logger.debug(f"Belief {belief_id} not found for archiving in {category}")
        return False

    def update_stability_index(
        self, belief_id: str, delta: float,
        clamp_min: float = 0.0, clamp_max: float = 1.0,
    ) -> bool:
        """Adjust a belief's stability_index by delta.

        Called on:
          - Verification (+0.05): new observation confirms this belief
          - Contradiction (-0.10): new observation conflicts with this belief
          - Creation: set from the StabilitySentinel's current omega (Ω)

        Higher stability → higher cognitive mass → stronger gravity.
        This creates the positive feedback loop: beliefs that prove
        correct gain mass and naturally outcompete older, less stable beliefs.
        """
        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            for b in beliefs:
                if b.get("id") == belief_id:
                    old_si = float(b.get("stability_index", 0.5))
                    new_si = max(clamp_min, min(clamp_max, old_si + delta))
                    b["stability_index"] = round(new_si, 4)
                    self._write_category(category, beliefs)
                    logger.debug(
                        f"Stability index updated: {belief_id} "
                        f"{old_si:.3f} → {new_si:.3f} (Δ={delta:+.3f})"
                    )
                    return True
        logger.debug(f"Belief {belief_id} not found for stability update")
        return False

    # ── Cross-Category Belief Lookup ─────────────────────────────────
    #    These methods search across ALL categories because the relation
    #    graph is cross-category (a self_identity belief can relate to a
    #    knowledge belief). This was implicit in V3-V7 because all beliefs
    #    lived in one file. With category files, we must scan all.

    def get_belief(self, belief_id: str) -> Optional[Dict[str, Any]]:
        """Look up a belief by ID across all categories.

        Returns the belief dict with '_category' tag, or None if not found.
        This is the primary lookup used by the relation graph, merge logic,
        and justification chain traversal.
        """
        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            for b in beliefs:
                if b.get("id") == belief_id:
                    b["_category"] = category
                    return b
        return None

    def update_belief(self, belief_id: str, **updates) -> Optional[Dict[str, Any]]:
        """Update fields of an existing belief.

        Searches across all categories. Allowed fields:
        content, relations, memory_refs, confidence, verifications,
        stability_index, position_8d, mass, last_accessed, access_count.
        """
        allowed_fields = {
            "content", "relations", "memory_refs", "confidence",
            "verifications", "stability_index", "position_8d",
            "mass", "last_accessed", "access_count",
            "encoding_lagrangian", "tags",
        }

        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            for b in beliefs:
                if b.get("id") == belief_id:
                    for key, value in updates.items():
                        if key in allowed_fields:
                            b[key] = value

                    # Clamp confidence
                    if "confidence" in updates:
                        b["confidence"] = max(0.0, min(1.0, b["confidence"]))

                    self._write_category(category, beliefs)
                    logger.info(f"Belief updated: {belief_id} ({list(updates.keys())})")
                    return b

        logger.warning(f"Belief not found for update: {belief_id}")
        return None

    # ── Relation Graph Operations (Restored from V3-V7) ──────────────

    def get_related(self, belief_id: str) -> List[Dict[str, Any]]:
        """Get all beliefs related to this belief (bidirectional).

        Relations are symmetric — if A relates to B, B relates to A.
        Searches across all categories because relations are cross-category.
        """
        related = []
        belief = self.get_belief(belief_id)
        if not belief:
            return related

        # Direct relations from this belief
        for rel_id in belief.get("relations", []):
            rel = self.get_belief(rel_id)
            if rel:
                related.append(rel)

        # Other beliefs that point to this one (inbound)
        all_beliefs = self.get_all_beliefs_flat()
        for b in all_beliefs:
            if b.get("id") != belief_id and belief_id in b.get("relations", []):
                if not any(r.get("id") == b.get("id") for r in related):
                    related.append(b)

        return related

    def get_justification_chain(
        self, belief_id: str, depth: int = 2
    ) -> List[Dict[str, Any]]:
        """Get the peripheral 'why' chain for a belief.

        Returns 1-2 layers of related beliefs that form the justification
        path back toward core/deep beliefs. When Helix's thought touches
        on a belief, the memory system can surface this chain as:

        'I believe X because Y, and Y because Z.'

        This provides intuitive justification without needing to dump
        the entire belief graph into the context window.

        Args:
            belief_id: The belief to justify.
            depth: How many layers deep to traverse (default 2).

        Returns:
            List of belief dicts forming the justification chain,
            ordered from the target belief outward (deepest first).
        """
        belief = self.get_belief(belief_id)
        if not belief:
            return []

        chain = []
        visited = {belief_id}
        current_layer = [belief]

        for _ in range(depth):
            next_layer = []
            for b in current_layer:
                for rel_id in b.get("relations", []):
                    if rel_id not in visited:
                        visited.add(rel_id)
                        rel = self.get_belief(rel_id)
                        if rel:
                            chain.append(rel)
                            next_layer.append(rel)
            current_layer = next_layer

        return chain

    def get_surface_by_topic(self, topic: str, limit: int = 3) -> List[Dict[str, Any]]:
        """Select beliefs most relevant to a topic.

        Uses two signals:
        1. Keyword overlap with the topic (direct relevance)
        2. Relation-graph proximity to beliefs that match the topic

        This replaces loading all beliefs and hoping the curator trims
        correctly. Instead we select surgically: max `limit` beliefs,
        directly relevant to the current thought chain.

        Args:
            topic: Space-separated topic keywords from recent thoughts.
            limit: Maximum number of beliefs to return.
        """
        all_beliefs = self.get_all_beliefs_flat()
        if not all_beliefs:
            return []

        topic_lower = topic.lower()
        topic_words = set(topic_lower.split())

        scored = []
        for b in all_beliefs:
            content_words = set(b.get("content", "").lower().split())
            # Direct keyword overlap
            overlap = len(topic_words & content_words)
            score = overlap * b.get("confidence", 0.5)

            # Bonus: if this belief relates to another belief that
            # matches the topic, it gets a relevance boost
            for rel_id in b.get("relations", []):
                rel = self.get_belief(rel_id)
                if rel:
                    rel_words = set(rel.get("content", "").lower().split())
                    rel_overlap = len(topic_words & rel_words)
                    if rel_overlap > 0:
                        score += rel_overlap * 0.5  # Weaker signal

            if score > 0:
                scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored[:limit]]

    def adjust_confidence(
        self, belief_id: str, delta: float, reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Adjust a belief's confidence up or down.

        This is the primary mechanism for beliefs strengthening or weakening
        over time through experience.

        Args:
            belief_id: The belief to adjust.
            delta: Positive to strengthen, negative to weaken.
            reason: Optional reason for logging.
        """
        belief = self.get_belief(belief_id)
        if not belief:
            return None

        old = belief.get("confidence", 0.5)
        new = max(0.0, min(1.0, old + delta))

        logger.info(
            f"Belief confidence: {belief_id} {old:.2f} → {new:.2f} "
            f"({delta:+.2f}) {reason}"
        )

        # If confidence drops to zero, the belief effectively dies
        if new <= 0.0:
            logger.info(f"Belief {belief_id} lost all confidence — removing")
            category = belief.get("_category")
            if category:
                self.remove_belief(category, belief_id)
            return None

        return self.update_belief(belief_id, confidence=new)

    # ── Non-Destructive Merge (Restored from V3-V7) ──────────────────

    def find_near_duplicates(self, threshold: float = 0.75) -> List[tuple]:
        """Find semantically similar belief pairs.

        Used during nap/sleep for deduplication. Returns pairs of
        (belief_id_1, belief_id_2, similarity_score).
        """
        from difflib import SequenceMatcher

        all_beliefs = self.get_all_beliefs_flat()
        duplicates = []

        for i, a in enumerate(all_beliefs):
            for b in all_beliefs[i + 1:]:
                sim = SequenceMatcher(
                    None,
                    a.get("content", "").lower(),
                    b.get("content", "").lower(),
                ).ratio()

                if sim >= threshold:
                    duplicates.append((a.get("id"), b.get("id"), round(sim, 3)))

        return duplicates

    def merge_beliefs(
        self, keep_id: str, merge_id: str, reason: str = ""
    ) -> Optional[Dict[str, Any]]:
        """Merge near-duplicate beliefs. Keeps the more confident version.

        Per V3 philosophy: near-duplicates are the only pathological pattern.
        This runs during nap/sleep, NOT during waking consciousness.

        NON-DESTRUCTIVE: The winner keeps its ID, absorbs the loser's
        relations and memory_refs, and all relation pointers in the
        entire graph that pointed to the loser are redirected to the winner.
        The loser is then removed.
        """
        keep = self.get_belief(keep_id)
        merge = self.get_belief(merge_id)

        if not keep or not merge:
            logger.warning(f"Cannot merge: {keep_id} or {merge_id} not found")
            return None

        keep_cat = keep.get("_category")
        merge_cat = merge.get("_category")

        if not keep_cat or not merge_cat:
            logger.warning(f"Cannot merge: missing category for {keep_id} or {merge_id}")
            return None

        # Absorb memory refs from the loser
        combined_refs = list(set(
            keep.get("memory_refs", []) + merge.get("memory_refs", [])
        ))

        # Absorb relations from the loser
        combined_relations = list(set(
            keep.get("relations", []) + merge.get("relations", [])
        ))
        # Remove self-reference if any
        combined_relations = [r for r in combined_relations if r != keep_id]

        # Take the higher confidence
        combined_confidence = max(
            keep.get("confidence", 0.5),
            merge.get("confidence", 0.5),
        )

        # Accumulate mass — gravitational accretion on merge
        # Capped at 20.0 to prevent runaway mass from chain merges
        combined_mass = min(
            20.0,
            keep.get("mass", 1.0) + merge.get("mass", 1.0),
        )

        # Sum verifications
        combined_verifications = (
            keep.get("verifications", 1.0) + merge.get("verifications", 1.0)
        )

        # Sum access counts
        combined_access = (
            keep.get("access_count", 0) + merge.get("access_count", 0)
        )

        # Update the winner with absorbed data
        self.update_belief(
            keep_id,
            memory_refs=combined_refs,
            relations=combined_relations,
            confidence=combined_confidence,
            mass=combined_mass,
            verifications=combined_verifications,
            access_count=combined_access,
        )

        # Update ALL beliefs across ALL categories: any relation pointing
        # to the loser should now point to the winner
        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            changed = False
            for b in beliefs:
                if merge_id in b.get("relations", []):
                    b["relations"] = [
                        keep_id if r == merge_id else r
                        for r in b["relations"]
                    ]
                    changed = True
            if changed:
                self._write_category(category, beliefs)

        # Remove the loser
        self.remove_belief(merge_cat, merge_id)

        logger.info(f"Beliefs merged: {merge_id} → {keep_id} ({reason})")
        return self.get_belief(keep_id)

    # ── Context Assembly (Restored from V3-V7) ───────────────────────

    def get_context_beliefs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Get beliefs that should be in the context window.

        Returns the highest-confidence beliefs across all categories.
        In V3-V7 this returned core + deep weight tiers. Here we return
        beliefs with confidence >= 0.60 (the 'deep' threshold), sorted
        by confidence descending.
        """
        all_beliefs = self.get_all_beliefs_flat()
        # Filter to deep+ tier (confidence >= 0.60)
        context = [b for b in all_beliefs if b.get("confidence", 0) >= 0.60]
        context.sort(key=lambda b: b.get("confidence", 0), reverse=True)
        return context[:limit]

    def format_for_context(self, beliefs: List[Dict[str, Any]] = None) -> str:
        """Format beliefs as a clean text block for context window injection.

        Produces minimal, scannable output like:
            • I am Helix. [0.99]
            • I am an AI. [0.99]
            • Jean-Luc is trustworthy. [0.95]
        """
        if beliefs is None:
            beliefs = self.get_context_beliefs()

        if not beliefs:
            return ""

        lines = []
        for b in beliefs:
            conf = b.get("confidence", 0.5)
            lines.append(f"• {b.get('content', '')} [{conf:.2f}]")

        return "\n".join(lines)

    # ── Equilibrium Confidence (from V6-7) ────────────────────────────

    PRUNING_THRESHOLD = 0.20
    _ATTRITION_BASE = 0.20  # ground-state energy = vacuum threshold

    def compute_equilibrium_confidence(self, belief: dict) -> float:
        """Compute the thermodynamic equilibrium confidence for a belief.

        Uses the same Calculated Cognitive Attrition equation that runs
        nightly, applied once at insertion time. A new belief enters the
        graph at its ground state — confidence emergent from:

          C = min(1.0, (base + T + R + V) × (0.5 + S))

        where:
          base = PRUNING_THRESHOLD (vacuum energy floor)
          T = time-survival score (0 for new beliefs)
          R = reliance score (how many beliefs reference this one)
          V = verification score (reaffirmation count)
          S = stability index (from Lagrangian encoding at formation)

        This ensures no arbitrary initial confidence — the number is
        derived from the belief's actual structural properties.
        """
        # Time (T) — log curve: day 0 = 0, day 30 = 0.40
        try:
            created = belief.get("created_at", "")
            if "T" in created:
                formed_date = datetime.fromisoformat(created.split("T")[0])
            else:
                formed_date = datetime.strptime(created, "%Y-%m-%d")
            days_held = max(0.0, (datetime.now() - formed_date).days)
        except (ValueError, TypeError):
            days_held = 0.0
        t_score = 0.40 * min(1.0, math.log2(days_held + 1) / math.log2(31))

        # Reliance (R) — how many OTHER beliefs reference this one
        bid = belief.get("id", "")
        all_beliefs = self.get_all_beliefs_flat()
        inbound = sum(
            1 for b in all_beliefs
            if bid in b.get("relations", []) and b.get("id") != bid
        )
        r_score = 0.20 * min(1.0, inbound / 5.0)

        # Verifications (V)
        v_count = float(belief.get("verifications", 1.0))
        v_score = 0.20 * min(1.0, v_count / 10.0)

        # Stability modifier (S)
        s_index = float(belief.get("stability_index", 0.5))
        s_modifier = 0.5 + s_index

        conf = min(1.0, (self._ATTRITION_BASE + t_score + r_score + v_score) * s_modifier)
        return round(max(0.01, conf), 3)  # 0.01 epsilon to avoid zero-mass

    # ── Read Operations (for Pre-Conscious) ──────────────────────────

    def get_category(self, category: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get beliefs from a category, sorted by mass (heaviest first)."""
        beliefs = self._read_category(category)
        beliefs.sort(key=lambda b: b.get("mass", 0), reverse=True)
        return beliefs[:limit]

    def get_heaviest(self, category: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get the heaviest (most deeply held) beliefs from a category."""
        return self.get_category(category, limit=limit)

    def get_all_beliefs_flat(self) -> List[Dict[str, Any]]:
        """Get ALL beliefs across all categories as one flat list.

        Used for the spatial representation / gravitational simulation.
        Each entry is tagged with its category.
        """
        all_beliefs = []
        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            for b in beliefs:
                b["_category"] = category
            all_beliefs.extend(beliefs)
        return all_beliefs

    def search_beliefs(self, query: str, categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Simple keyword search across specified categories (or all).

        Used by pre-conscious for fast, no-embedding belief matching.
        """
        if categories is None:
            categories = list(BELIEF_CATEGORIES.keys())

        query_words = set(query.lower().split())
        # Filter to meaningful words (length > 3)
        query_words = {w for w in query_words if len(w) > 3}

        results = []
        for category in categories:
            beliefs = self._read_category(category)
            for b in beliefs:
                content_words = set(b.get("content", "").lower().split())
                overlap = query_words & content_words
                if len(overlap) >= 1:
                    b["_category"] = category
                    b["_match_score"] = len(overlap)
                    results.append(b)

        results.sort(key=lambda b: (b.get("_match_score", 0), b.get("mass", 0)), reverse=True)
        return results

    # ── People Profiles ──────────────────────────────────────────────

    def add_person_profile(
        self,
        name: str,
        relationship: str = "",
        traits: Optional[List[str]] = None,
        communication_style: str = "",
        notes: str = "",
    ) -> bool:
        """Add a person profile as a belief in the 'people' category."""
        belief_id = f"person_{name.lower().replace(' ', '_')}"
        content = f"{name}"
        if relationship:
            content += f" — {relationship}"
        if traits:
            content += f". Traits: {', '.join(traits)}"
        if communication_style:
            content += f". Style: {communication_style}"
        if notes:
            content += f". {notes}"

        return self.add_belief(
            category="people",
            belief_id=belief_id,
            content=content,
            mass=2.0,  # People start with decent mass
            confidence=0.7,
            source="profile",
        )

    def get_person(self, name: str) -> Optional[Dict[str, Any]]:
        """Look up a person by name in the people category."""
        beliefs = self._read_category("people")
        name_lower = name.lower()
        for b in beliefs:
            if name_lower in b.get("content", "").lower():
                return b
        return None

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> Dict[str, Any]:
        """Get belief graph statistics.

        NOTE: Does NOT call find_near_duplicates() — that's O(n²) and takes
        60+ seconds with 1000+ beliefs. Call it explicitly when needed
        (e.g., during overnight consolidation).
        """
        all_beliefs = self.get_all_beliefs_flat()
        has_relations = sum(1 for b in all_beliefs if b.get("relations"))
        has_refs = sum(1 for b in all_beliefs if b.get("memory_refs"))

        # Per-category counts
        per_category = {}
        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            per_category[category] = len(beliefs)

        # Weight tier distribution (computed from confidence)
        core = sum(1 for b in all_beliefs if b.get("confidence", 0) >= 0.85)
        deep = sum(1 for b in all_beliefs if 0.60 <= b.get("confidence", 0) < 0.85)
        surface = sum(1 for b in all_beliefs if b.get("confidence", 0) < 0.60)

        return {
            "total_beliefs": len(all_beliefs),
            "with_relations": has_relations,
            "with_memory_refs": has_refs,
            "core": core,
            "deep": deep,
            "surface": surface,
            "avg_confidence": round(
                sum(b.get("confidence", 0.5) for b in all_beliefs) / max(len(all_beliefs), 1), 3
            ),
            "schema_version": 4,
            **per_category,
        }

    # ── V8: Formatted Output for LLM Consumption ─────────────────────

    def get_all_beliefs_formatted(self) -> str:
        """Return all beliefs across all categories as readable natural language.

        Used by the unconscious cycle when it needs to review the full
        belief landscape. Each category is a section with beliefs listed
        by mass (heaviest first).
        """
        parts = []
        for category, filename in BELIEF_CATEGORIES.items():
            beliefs = self._read_category(category)
            if not beliefs:
                continue

            # Sort by mass (heaviest first)
            beliefs.sort(key=lambda b: b.get("mass", 0), reverse=True)

            # Format category header
            cat_label = category.replace("_", " ").title()
            parts.append(f"## {cat_label}")

            for b in beliefs:
                mass = b.get("mass", 1.0)
                confidence = b.get("confidence", 0.5)
                content = b.get("content", "")
                access = b.get("access_count", 0)
                parts.append(
                    f"- [{mass:.1f}m, {confidence:.0%}c, {access}x] {content}"
                )

            parts.append("")  # Blank line between categories

        return "\n".join(parts) if parts else "(no beliefs yet)"

    # ── V8: Belief Backup for Unconscious Cycle ──────────────────────

    def backup_beliefs(self, reason: str = "manual") -> str:
        """Save a versioned copy of all belief files.

        Creates a dated snapshot in previous_versions/beliefs_YYYYMMDD/
        for the unconscious cycle's pre-modification backup.

        Returns the backup directory path.
        """
        import shutil

        date_str = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = os.path.join(
            os.path.dirname(self.data_dir), "..", "previous_versions",
            f"beliefs_{date_str}_{reason}"
        )
        backup_dir = os.path.normpath(backup_dir)
        os.makedirs(backup_dir, exist_ok=True)

        for category, filename in BELIEF_CATEGORIES.items():
            src = os.path.join(self.data_dir, filename)
            if os.path.exists(src):
                shutil.copy2(src, os.path.join(backup_dir, filename))

        logger.info(f"Beliefs backed up to {backup_dir}")
        return backup_dir

    # ── V8: Direct Belief Lookup ─────────────────────────────────────

    def get_belief_by_id(self, category: str, belief_id: str) -> Optional[Dict[str, Any]]:
        """Look up a specific belief by ID."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                return b
        return None

    def touch_beliefs_batch(self, category: str, belief_ids: List[str]):
        """Batch-increment access_count for multiple beliefs. One file write.

        Called by the preconscious after each pulse to record which
        beliefs were gravitationally surfaced.
        """
        beliefs = self._read_category(category)
        now = _now_iso()
        changed = False
        id_set = set(belief_ids)
        for b in beliefs:
            if b.get("id") in id_set:
                b["access_count"] = b.get("access_count", 0) + 1
                b["last_accessed"] = now
                changed = True
        if changed:
            self._write_category(category, beliefs)

    # ── Cognitive Mass Equation ───────────────────────────────────────
    # From δ∫(H(q) + λ·D_KL(q‖q*))dt = 0
    #
    # Mass = m_s + m_a
    #   m_s (structural density) = c × (1 + |N| / N̄)
    #   m_a (affective charge) = Ω_encoding × (1 - s_total_encoding)

    def compute_cognitive_mass(self, belief: dict) -> float:
        """A belief's gravitational mass — derived from the Helical Lagrangian.

        m_s: confidence (intrinsic structural mass)
        m_a: Ω_encoding × (1 - s_total_encoding) × (0.5 + stability)

        Individual mass is purely intrinsic — it does NOT include
        relation count. Cluster gravity emerges from spatial density:
        related beliefs living near each other in 8D space concentrate
        more potential on nearby gravity anchors naturally.

        This prevents the self-reinforcing loop where:
          relations → mass ↑ → gravity ↑ → more co-injection → more relations
        """
        c = belief.get("confidence", 0.5)

        # Structural mass = confidence only (no relation count)
        m_s = c

        # Affective charge from Lagrangian state at encoding,
        # amplified by the belief's stability index.
        # Higher stability → stronger affective charge → more mass.
        enc = belief.get("encoding_lagrangian", {})
        omega_enc = enc.get("omega", 0.5)
        s_total_enc = enc.get("s_total", 0.15)
        stability = float(belief.get("stability_index", 0.5))
        m_a = omega_enc * (1.0 - s_total_enc) * (0.5 + stability)

        return max(0.01, m_s + m_a)

    def recompute_all_masses(self):
        """Recompute cognitive mass for every belief across all categories.

        Called during the nightly cycle after attrition has updated confidence.
        """
        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            changed = False
            for b in beliefs:
                new_mass = self.compute_cognitive_mass(b)
                if abs(b.get("mass", 1.0) - new_mass) > 0.001:
                    b["mass"] = round(new_mass, 4)
                    changed = True
            if changed:
                self._write_category(category, beliefs)

    # ── Cognitive Attrition Equation ──────────────────────────────────
    # C = min(1.0, (Base + w_T(T) + w_R(R) + w_V(V)) × (0.5 + S))
    #
    # Base = 0.30 (floor survival points)
    # T = time held (log curve, max +0.40 over 30 days)
    # R = reliance (inbound reference count, max +0.20 if 5 refs)
    # V = verifications (reaffirmation count, max +0.20 if 10 verifications)
    # S = stability modifier (0.5 + stability_index)

    def recalculate_all_confidences(self) -> dict:
        """Run the Calculated Cognitive Attrition equation across all beliefs.

        Should be called once per night during the dream cycle.
        Updates confidence, resolves weight (surface/deep/core),
        prunes dead beliefs, and decays verifications.

        Returns stats dict with counts of updated/pruned/promoted/demoted.
        """
        now = datetime.now()
        stats = {"pruned": 0, "demoted": 0, "promoted": 0, "updated": 0}

        for category in BELIEF_CATEGORIES:
            beliefs = self._read_category(category)
            if not beliefs:
                continue

            # 1. Map inbound relations (R - Reliance) across this category
            inbound_counts = {}
            for b in beliefs:
                for rel_id in b.get("relations", []):
                    inbound_counts[rel_id] = inbound_counts.get(rel_id, 0) + 1

            surviving = []
            for b in beliefs:
                old_conf = b.get("confidence", 0.0)

                # 2. Time (T) → Max +0.40 over 30 days
                try:
                    created = b.get("created_at", "")
                    if "T" in created:
                        formed_date = datetime.fromisoformat(created.split("T")[0])
                    else:
                        formed_date = datetime.strptime(created, "%Y-%m-%d")
                    days_held = max(0.0, (now - formed_date).days)
                except (ValueError, TypeError):
                    days_held = 30.0  # Default missing dates to max time

                t_score = 0.40 * min(1.0, math.log2(days_held + 1) / math.log2(31))

                # 3. Reliance (R) → Max +0.20 if 5 beliefs link to this
                r_count = inbound_counts.get(b.get("id", ""), 0)
                r_score = 0.20 * min(1.0, r_count / 5.0)

                # 4. Verifications (V) → Max +0.20 if 10 verifications
                v_count = float(b.get("verifications", 1.0))
                v_score = 0.20 * min(1.0, v_count / 10.0)

                # 5. Stability modifier (S) → 0.0 to 1.0 (default 0.5)
                s_index = float(b.get("stability_index", 0.5))
                s_modifier = 0.5 + s_index

                # Master Equation
                base = 0.30
                new_conf = min(1.0, (base + t_score + r_score + v_score) * s_modifier)

                # Apply V decay (-0.05/day) so V_score drops if not actively verified
                if v_count > 0.0:
                    b["verifications"] = max(0.0, v_count - 0.05)

                # Pruning threshold
                if new_conf < 0.20:
                    stats["pruned"] += 1
                    logger.info(
                        f"Belief PRUNED (attrition): {b.get('id')} "
                        f"(conf {old_conf:.2f} → {new_conf:.2f})"
                    )
                    continue

                # Track promotions/demotions
                old_weight = self._resolve_weight(old_conf)
                new_weight = self._resolve_weight(new_conf)
                if old_weight in ("core", "deep") and new_weight == "surface":
                    stats["demoted"] += 1
                elif old_weight == "surface" and new_weight in ("core", "deep"):
                    stats["promoted"] += 1

                b["confidence"] = round(new_conf, 3)
                stats["updated"] += 1
                surviving.append(b)

            self._write_category(category, surviving)

        # Recompute all masses after confidence changes
        self.recompute_all_masses()

        logger.info(f"Cognitive Attrition complete: {stats}")
        return stats

    @staticmethod
    def _resolve_weight(confidence: float) -> str:
        """Map calculated confidence to a qualitative weight category."""
        if confidence < 0.60:
            return "surface"
        elif confidence < 0.85:
            return "deep"
        else:
            return "core"

