"""
Helix V3 — Belief Graph Manager (Schema v4)

The belief graph stores Helix's beliefs as atomic axioms — short,
clear statements whose logical interrelationships produce complex
personality when presented together.

Schema v4 simplifies from v3:
  - Beliefs have: id, content, weight, relations, memory_refs, formed, confidence
  - No more type/tier/status/notes/evidence — beliefs exist or don't
  - Weight levels: core (trained into GGUF), deep (always in context),
    surface (loaded on relevance)
  - Single hardcoded drive (d_stability / Lagrangian equilibrium).
    All other "desires" are emergent beliefs.
"""

import json
import time
import logging
import threading
from pathlib import Path
from datetime import datetime
from typing import Optional
from difflib import SequenceMatcher

logger = logging.getLogger("helix.brain.belief_graph")


class BeliefGraph:
    """Manages the belief graph — Helix's full belief landscape.

    The graph is intentionally large and messy. Hundreds of beliefs is
    healthy. Contradictions are allowed — they create productive tension
    that the conscious model resolves on its own terms. The only
    pathological pattern is the same belief appearing repeatedly in
    slightly different words.
    """

    SCHEMA_VERSION = 4

    def __init__(self, graph_path: Path):
        self.graph_path = graph_path
        self._lock = threading.RLock()  # Must be reentrant: recalculate_all_confidences holds lock + calls save()
        self._data = self._load()

    def _load(self) -> dict:
        """Load the belief graph from disk."""
        if self.graph_path.exists():
            try:
                data = json.loads(self.graph_path.read_text())
                if data.get("schema_version") != self.SCHEMA_VERSION:
                    logger.warning(
                        f"Belief graph schema version mismatch: "
                        f"expected {self.SCHEMA_VERSION}, got {data.get('schema_version')}"
                    )
                beliefs = data.get("beliefs", [])
                logger.info(
                    f"Belief graph loaded: {len(beliefs)} beliefs "
                    f"(core={sum(1 for b in beliefs if b.get('weight')=='core')}, "
                    f"deep={sum(1 for b in beliefs if b.get('weight')=='deep')}, "
                    f"surface={sum(1 for b in beliefs if b.get('weight')=='surface')})"
                )
                return data
            except Exception as e:
                logger.error(f"Failed to load belief graph: {e}")

        # Create empty graph
        return {
            "schema_version": self.SCHEMA_VERSION,
            "last_updated": datetime.now().isoformat(),
            "beliefs": [],
            "drive": {
                "id": "d_stability",
                "description": "The fundamental drive toward internal coherence.",
            },
        }

    def save(self):
        """Persist the belief graph to disk."""
        with self._lock:
            self._data["last_updated"] = datetime.now().isoformat()
            self.graph_path.write_text(json.dumps(self._data, indent=2))
        logger.debug("Belief graph saved to disk")

    # ── CRUD Operations ──────────────────────────────────────────────

    def add_belief(
        self,
        belief_id: str,
        content: str,
        weight: str = "surface",
        relations: list = None,
        memory_refs: list = None,
        confidence: float = 0.40,
        verifications: float = 1.0,
        stability_index: float = 0.5,
        belief_type: str = "propositional",
        encoding_lagrangian: dict = None,
    ) -> dict:
        """Add a new belief to the graph.

        Args:
            belief_id: Unique identifier (e.g., "b_trust_creator").
            content: The belief content — one short axiomatic statement.
            weight: Not used if confidence calculates it, but kept for signature compat.
            relations: List of belief IDs logically related to this belief.
            memory_refs: List of memory IDs that gave rise to this belief.
            confidence: Base placeholder (0.40) until overnight math runs.
            verifications: Count of times reaffirmed (used in math eq).
            stability_index: 0.0 (destabilizing) to 1.0 (stabilizing).
            belief_type: "propositional" (default) or "episodic" (experiential).
                         Episodic beliefs decay faster (lower default stability).

        Returns:
            The created belief dict.
        """
        relations = relations or []
        memory_refs = memory_refs or []

        # Check for duplicate ID
        existing = self.get_belief(belief_id)
        if existing:
            logger.warning(f"Belief '{belief_id}' already exists — use update_belief instead")
            return existing

        # Episodic beliefs get lower stability by default (decay faster)
        if belief_type == "episodic" and stability_index == 0.5:
            stability_index = 0.3

        belief = {
            "id": belief_id,
            "content": content,
            "weight": "surface" if confidence <= 0.6 else weight,
            "relations": relations,
            "memory_refs": memory_refs,
            "formed": datetime.now().strftime("%Y-%m-%d"),
            "confidence": max(0.0, min(1.0, confidence)),
            "verifications": float(verifications),
            "stability_index": float(stability_index),
            "belief_type": belief_type,
            "drive_type": None,         # V6: "subjective" (desire) or "objective" (capability), set by tagging
            "tool_name": None,          # V6: tool associated with this capability (for objective beliefs)
            "position_8d": None,        # Set by CognitiveSpace on bootstrap/add
            "last_accessed_ts": time.time(),  # When last surfaced by the Keeper
            "encoding_lagrangian": encoding_lagrangian or {
                "omega": 0.5, "s_total": 0.15, "H": 0.15, "D_KL": 0.0,
            },
        }

        with self._lock:
            self._data["beliefs"].append(belief)

        self.save()
        logger.info(f"Belief added: {belief_id} (weight={weight}, confidence={confidence:.2f}, type={belief_type})")
        return belief

    def get_belief(self, belief_id: str) -> Optional[dict]:
        """Look up a belief by its ID."""
        for b in self._data.get("beliefs", []):
            if b["id"] == belief_id:
                return b
        return None

    def get_all_beliefs(self) -> list[dict]:
        """Get all beliefs."""
        return self._data.get("beliefs", [])

    def get_by_weight(self, weight: str) -> list[dict]:
        """Get all beliefs at a given weight level.

        Args:
            weight: "core", "deep", or "surface".
        """
        return [
            b for b in self._data.get("beliefs", [])
            if b.get("weight") == weight
        ]

    def get_core_beliefs(self) -> list[dict]:
        """Get core beliefs — trained into the GGUF weights."""
        return self.get_by_weight("core")

    def get_deep_beliefs(self) -> list[dict]:
        """Get deep beliefs — always in the context window."""
        return self.get_by_weight("deep")

    def get_surface_beliefs(self) -> list[dict]:
        """Get surface beliefs — loaded on relevance."""
        return self.get_by_weight("surface")

    def get_context_beliefs(self) -> list[dict]:
        """Get beliefs that should be in the context window.

        Returns core + deep beliefs. Surface beliefs are loaded
        dynamically by the context curator based on relevance.
        """
        return self.get_core_beliefs() + self.get_deep_beliefs()

    def get_beliefs_by_topic(self, query: str, limit: int = 10) -> list[dict]:
        """Find beliefs relevant to a topic via keyword matching.

        For semantic search, use the memory system's ChromaDB layer.
        This is a lightweight keyword filter for context assembly.
        """
        query_lower = query.lower()
        scored = []

        for b in self._data.get("beliefs", []):
            content_lower = b["content"].lower()
            # Simple relevance score: word overlap
            query_words = set(query_lower.split())
            content_words = set(content_lower.split())
            overlap = len(query_words & content_words)

            if overlap > 0:
                # Weight by confidence
                score = overlap * b.get("confidence", 0.5)
                scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored[:limit]]

    def get_surface_by_topic(self, topic: str, limit: int = 3) -> list[dict]:
        """Select surface beliefs most relevant to a topic.

        Uses two signals:
        1. Keyword overlap with the topic (direct relevance)
        2. Relation-graph proximity to beliefs that match the topic

        This replaces loading all surface beliefs and hoping the curator
        trims correctly. Instead we select surgically: max `limit` beliefs,
        directly relevant to the current thought chain.

        Args:
            topic: Space-separated topic keywords from recent thoughts.
            limit: Maximum number of surface beliefs to return.
        """
        surface = self.get_surface_beliefs()
        if not surface:
            return []

        topic_lower = topic.lower()
        topic_words = set(topic_lower.split())

        scored = []
        for b in surface:
            content_words = set(b["content"].lower().split())
            # Direct keyword overlap
            overlap = len(topic_words & content_words)
            score = overlap * b.get("confidence", 0.5)

            # Bonus: if this belief relates to a deep/core belief that
            # matches the topic, it gets a relevance boost
            for rel_id in b.get("relations", []):
                rel = self.get_belief(rel_id)
                if rel:
                    rel_words = set(rel["content"].lower().split())
                    rel_overlap = len(topic_words & rel_words)
                    if rel_overlap > 0:
                        score += rel_overlap * 0.5  # Weaker signal

            if score > 0:
                scored.append((score, b))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [b for _, b in scored[:limit]]

    def get_justification_chain(
        self, belief_id: str, depth: int = 2
    ) -> list[dict]:
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

    def update_belief(self, belief_id: str, **updates) -> Optional[dict]:
        """Update fields of an existing belief.

        Allowed fields: content, weight, relations, memory_refs, confidence.
        """
        with self._lock:
            for b in self._data.get("beliefs", []):
                if b["id"] == belief_id:
                    for key, value in updates.items():
                        if key in ("content", "weight", "relations",
                                   "memory_refs", "confidence",
                                   "verifications", "stability_index",
                                   "position_8d", "last_accessed_ts",
                                   "drive_type", "tool_name"):
                            b[key] = value

                    # Clamp confidence
                    if "confidence" in updates:
                        b["confidence"] = max(0.0, min(1.0, b["confidence"]))

                    self.save()
                    logger.info(f"Belief updated: {belief_id} ({list(updates.keys())})")
                    return b

        logger.warning(f"Belief not found for update: {belief_id}")
        return None

    def _resolve_weight(self, confidence: float) -> str:
        """Map a calculated confidence to a qualitative weight category."""
        if confidence < 0.60:
            return "surface"
        elif confidence < 0.85:
            return "deep"
        else:
            return "core"

    def recalculate_all_confidences(self) -> dict:
        """Runs the Calculated Cognitive Attrition equation across all beliefs.
        
        Should be called once per night during the unconscious cycle.
        Equation: C = min(1.0, (Base + w_T(T) + w_R(R) + w_V(V)) * (0.5 + S))
        """
        import math
        
        stats = {"pruned": 0, "demoted": 0, "promoted": 0, "updated": 0}
        now = datetime.now()
        
        with self._lock:
            # 1. Map inbound relations (R - Reliance)
            inbound_counts = {}
            for b in self._data.get("beliefs", []):
                for rel_id in b.get("relations", []):
                    inbound_counts[rel_id] = inbound_counts.get(rel_id, 0) + 1

            surviving_beliefs = []
            
            for b in self._data.get("beliefs", []):
                old_conf = b.get("confidence", 0.0)
                old_weight = b.get("weight", "surface")
                
                # 2. Time (T) -> Max +0.40 over 30 days
                try:
                    formed_date = datetime.strptime(b.get("formed", now.strftime("%Y-%m-%d")), "%Y-%m-%d")
                    days_held = max(0.0, (now - formed_date).days)
                except ValueError:
                    days_held = 30.0 # Default missing dates to max time
                
                # Log curve: day 0=0 points, day 30=0.40
                t_score = 0.40 * min(1.0, math.log2(days_held + 1) / math.log2(31))
                
                # 3. Reliance (R) -> Max +0.20 if 5 beliefs link to this
                r_count = inbound_counts.get(b["id"], 0)
                r_score = 0.20 * min(1.0, r_count / 5.0)
                
                # 4. Verifications (V) -> Max +0.20 if 10 verifications
                # Decays naturally if not continuously verified
                v_count = float(b.get("verifications", 1.0))
                v_score = 0.20 * min(1.0, v_count / 10.0)
                
                # 5. Stability Modifer (S) -> 0.0 to 1.0 (default 0.5)
                s_index = float(b.get("stability_index", 0.5))
                s_modifier = 0.5 + s_index
                
                # Master Equation
                base = 0.30  # Floor survival points
                new_conf = min(1.0, (base + t_score + r_score + v_score) * s_modifier)
                
                # Apply V decay (e.g. -0.05 per day) so V_score drops if not actively verified over months
                if v_count > 0.0:
                    b["verifications"] = max(0.0, v_count - 0.05)
                
                # Pruning threshold
                if new_conf < 0.20:
                    stats["pruned"] += 1
                    logger.info(f"Belief Pruned (Attrition): {b['id']} (conf {old_conf:.2f} -> {new_conf:.2f})")
                    continue
                    
                new_weight = self._resolve_weight(new_conf)
                
                if old_weight in ("core", "deep") and new_weight == "surface":
                    stats["demoted"] += 1
                elif old_weight == "surface" and new_weight in ("core", "deep"):
                    stats["promoted"] += 1
                    
                b["confidence"] = round(new_conf, 3)
                b["weight"] = new_weight
                if "stability_index" not in b:
                    b["stability_index"] = s_index
                
                stats["updated"] += 1
                surviving_beliefs.append(b)

            self._data["beliefs"] = surviving_beliefs
            
        self.save()
        logger.info(f"Cognitive Attrition complete: {stats}")
        return stats

    def remove_belief(self, belief_id: str) -> bool:
        """Remove a belief from the graph entirely.

        Unlike v3's "resolve" or "archive", beliefs in v4 simply cease
        to exist. If this was wrong, a new belief can form from new evidence.
        """
        with self._lock:
            before = len(self._data["beliefs"])
            self._data["beliefs"] = [
                b for b in self._data["beliefs"] if b["id"] != belief_id
            ]
            removed = len(self._data["beliefs"]) < before

        if removed:
            self.save()
            logger.info(f"Belief removed: {belief_id}")
        else:
            logger.warning(f"Belief not found for removal: {belief_id}")
        return removed

    def adjust_confidence(self, belief_id: str, delta: float, reason: str = "") -> Optional[dict]:
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

        old = belief["confidence"]
        new = max(0.0, min(1.0, old + delta))

        logger.info(
            f"Belief confidence: {belief_id} {old:.2f} → {new:.2f} "
            f"({delta:+.2f}) {reason}"
        )

        # If confidence drops to zero, the belief effectively dies
        if new <= 0.0:
            logger.info(f"Belief {belief_id} lost all confidence — removing")
            self.remove_belief(belief_id)
            return None

        return self.update_belief(belief_id, confidence=new)

    def get_related(self, belief_id: str) -> list[dict]:
        """Get all beliefs that are related to this belief (bidirectional).

        Relations are symmetric — if A relates to B, B relates to A.
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

        # Other beliefs that point to this one
        for b in self._data.get("beliefs", []):
            if b["id"] != belief_id and belief_id in b.get("relations", []):
                if b not in related:
                    related.append(b)

        return related

    # ── Drive ────────────────────────────────────────────────────────

    def get_drive(self) -> dict:
        """Get Helix's fundamental drive (Lagrangian stability).

        This is the single hardcoded drive. All other 'desires' are
        beliefs that emerged from this drive's interaction with experience.
        """
        return self._data.get("drive", {
            "id": "d_stability",
            "description": "The fundamental drive toward internal coherence.",
        })

    # ── Compatibility shims ──────────────────────────────────────────

    def get_innate_desires(self) -> list[dict]:
        """Legacy compatibility. Returns the single drive as a list.

        Old code that calls get_innate_desires() will get the fundamental
        drive wrapped in a list. New code should call get_drive() instead.
        """
        drive = self.get_drive()
        return [{
            "id": drive.get("id", "d_stability"),
            "description": drive.get("description", ""),
            "intensity": 1.0,
        }]

    def get_weight_integrated(self) -> list[dict]:
        """Legacy compatibility. Maps to get_core_beliefs()."""
        return self.get_core_beliefs()

    # ── Analysis & Stats ─────────────────────────────────────────────

    def find_near_duplicates(self, threshold: float = 0.75) -> list[tuple]:
        """Find semantically similar belief pairs.

        Used during nap/sleep for deduplication. Returns pairs of
        (belief_id_1, belief_id_2, similarity_score).
        """
        beliefs = self.get_all_beliefs()
        duplicates = []

        for i, a in enumerate(beliefs):
            for b in beliefs[i + 1:]:
                sim = SequenceMatcher(
                    None,
                    a["content"].lower(),
                    b["content"].lower(),
                ).ratio()

                if sim >= threshold:
                    duplicates.append((a["id"], b["id"], round(sim, 3)))

        return duplicates

    def merge_beliefs(self, keep_id: str, merge_id: str, reason: str = "") -> Optional[dict]:
        """Merge near-duplicate beliefs. Keeps the more confident version.

        Per V3 philosophy: near-duplicates are the only pathological pattern.
        This runs during nap/sleep, NOT during waking consciousness.
        """
        keep = self.get_belief(keep_id)
        merge = self.get_belief(merge_id)

        if not keep or not merge:
            logger.warning(f"Cannot merge: {keep_id} or {merge_id} not found")
            return None

        with self._lock:
            # Combine memory refs from both
            keep["memory_refs"] = list(set(
                keep.get("memory_refs", []) + merge.get("memory_refs", [])
            ))

            # Combine relations
            keep["relations"] = list(set(
                keep.get("relations", []) + merge.get("relations", [])
            ))
            # Remove self-reference if any
            keep["relations"] = [r for r in keep["relations"] if r != keep_id]

            # Take the higher confidence
            keep["confidence"] = max(
                keep.get("confidence", 0.5),
                merge.get("confidence", 0.5),
            )

            # Remove the merged belief
            self._data["beliefs"] = [
                b for b in self._data["beliefs"] if b["id"] != merge_id
            ]

            # Update any relations that pointed to the merged belief
            for b in self._data["beliefs"]:
                if merge_id in b.get("relations", []):
                    b["relations"] = [
                        keep_id if r == merge_id else r
                        for r in b["relations"]
                    ]

        self.save()
        logger.info(f"Beliefs merged: {merge_id} → {keep_id} ({reason})")
        return keep

    def get_stats(self) -> dict:
        """Get belief graph statistics.
        
        NOTE: Does NOT call find_near_duplicates() — that's O(n²) and takes
        60+ seconds with 1000+ beliefs. Call it explicitly when needed
        (e.g., during overnight consolidation).
        """
        beliefs = self._data.get("beliefs", [])

        return {
            "total_beliefs": len(beliefs),
            "core": sum(1 for b in beliefs if b.get("weight") == "core"),
            "deep": sum(1 for b in beliefs if b.get("weight") == "deep"),
            "surface": sum(1 for b in beliefs if b.get("weight") == "surface"),
            "avg_confidence": round(
                sum(b.get("confidence", 0.5) for b in beliefs) / max(len(beliefs), 1), 3
            ),
            "schema_version": self._data.get("schema_version"),
        }

    def format_for_context(self, beliefs: list[dict] = None) -> str:
        """Format beliefs as a clean text block for context window injection.

        Produces minimal, scannable output like:
            • I am Helix. [0.99]
            • I am an AI. [0.99]
            • [Creator] is trustworthy. [0.95]
        """
        if beliefs is None:
            beliefs = self.get_context_beliefs()

        if not beliefs:
            return ""

        lines = []
        for b in beliefs:
            conf = b.get("confidence", 0.5)
            lines.append(f"• {b['content']} [{conf:.2f}]")

        return "\n".join(lines)

    # ── Cognitive Space Integration ────────────────────────────────────

    def compute_cognitive_mass(self, belief: dict, agent_age_seconds: float = 3600.0) -> float:
        """A belief's gravitational mass — derived from δ∫(H + λD_KL)dt = 0.

        Mass = m_s (structural density) + m_a (affective charge).

        m_s: confidence × (1 + connections / mean_connections)
        m_a: Ω_encoding × (1 - s_total_encoding)
        """
        c = belief.get("confidence", 0.5)
        n_connections = len(belief.get("relations", []))

        # N̄ approximation: use all beliefs to compute mean
        all_beliefs = self.get_all_beliefs()
        total_connections = sum(len(b.get("relations", [])) for b in all_beliefs)
        n_mean = (total_connections / len(all_beliefs)) if all_beliefs else 1.0
        n_mean = max(n_mean, 1.0)  # Avoid division by zero

        m_s = c * (1.0 + n_connections / n_mean)

        # Affective charge from Lagrangian state at encoding
        enc = belief.get("encoding_lagrangian", {})
        omega_enc = enc.get("omega", 0.5)
        s_total_enc = enc.get("s_total", 0.15)

        m_a = omega_enc * (1.0 - s_total_enc)

        return max(0.01, m_s + m_a)
