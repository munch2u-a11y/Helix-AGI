"""
Helix — Categorized Belief Store (LLM-Agnostic)

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

This version of the BeliefStore is LLM-agnostic, as its core functionality
relies on file operations and data management, not direct LLM interaction.
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

    def get_belief(self, category: str, belief_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a single belief by ID from a category."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["last_accessed"] = _now_iso()
                b["access_count"] = b.get("access_count", 0) + 1
                self._write_category(category, beliefs) # Persist access update
                return b
        return None

    def get_beliefs_by_category(self, category: str) -> List[Dict[str, Any]]:
        """Retrieve all beliefs for a given category."""
        beliefs = self._read_category(category)
        # Update access count for all beliefs retrieved (as they are implicitly accessed)
        now = _now_iso()
        for b in beliefs:
            b["last_accessed"] = now
            b["access_count"] = b.get("access_count", 0) + 1
        self._write_category(category, beliefs)
        return beliefs

    def get_all_beliefs(self) -> List[Dict[str, Any]]:
        """Retrieve all beliefs across all categories."""
        all_beliefs = []
        for category in BELIEF_CATEGORIES.keys():
            all_beliefs.extend(self.get_beliefs_by_category(category))
        return all_beliefs

    def remove_belief(self, category: str, belief_id: str) -> bool:
        """Remove a belief by ID from a category."""
        beliefs = self._read_category(category)
        original_count = len(beliefs)
        beliefs = [b for b in beliefs if b.get("id") != belief_id]
        if len(beliefs) < original_count:
            self._write_category(category, beliefs)
            logger.info(f"Removed belief '{belief_id}' from {category}")
            return True
        logger.debug(f"Belief {belief_id} not found in {category} for removal.")
        return False

    def update_belief_confidence(self, category: str, belief_id: str, new_confidence: float) -> bool:
        """Update the confidence of an existing belief."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["confidence"] = max(0.0, min(1.0, new_confidence))
                b["last_accessed"] = _now_iso()
                self._write_category(category, beliefs)
                logger.debug(f"Updated confidence for '{belief_id}' in {category} to {new_confidence:.2f}")
                return True
        logger.debug(f"Belief {belief_id} not found in {category} for confidence update.")
        return False

    def update_belief_relations(self, category: str, belief_id: str, new_relations: List[str]) -> bool:
        """Update the relations list for an existing belief."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["relations"] = list(set(new_relations)) # Ensure unique relations
                b["last_accessed"] = _now_iso()
                self._write_category(category, beliefs)
                logger.debug(f"Updated relations for '{belief_id}' in {category}")
                return True
        logger.debug(f"Belief {belief_id} not found in {category} for relations update.")
        return False

    def update_belief_memory_refs(self, category: str, belief_id: str, new_memory_refs: List[str]) -> bool:
        """Update the memory_refs list for an existing belief."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["memory_refs"] = list(set(new_memory_refs)) # Ensure unique refs
                b["last_accessed"] = _now_iso()
                self._write_category(category, beliefs)
                logger.debug(f"Updated memory refs for '{belief_id}' in {category}")
                return True
        logger.debug(f"Belief {belief_id} not found in {category} for memory_refs update.")
        return False

    def update_belief_position(self, category: str, belief_id: str, new_position_8d: List[float]) -> bool:
        """Update the 8D position for an existing belief."""
        beliefs = self._read_category(category)
        for b in beliefs:
            if b.get("id") == belief_id:
                b["position_8d"] = new_position_8d
                b["last_accessed"] = _now_iso()
                self._write_category(category, beliefs)
                logger.debug(f"Updated 8D position for '{belief_id}' in {category}")
                return True
        logger.debug(f"Belief {belief_id} not found in {category} for position update.")
        return False

    def get_total_mass(self) -> float:
        """Calculate the total cognitive mass across all beliefs."""
        total_mass = 0.0
        for category in BELIEF_CATEGORIES.keys():
            beliefs = self._read_category(category)
            for b in beliefs:
                total_mass += b.get("mass", 0.0)
        return total_mass

    def get_mass_weighted_centroid(self, category: Optional[str] = None) -> Optional[List[float]]:
        """Calculate the mass-weighted 8D centroid for a category or all beliefs.

        Args:
            category: Optional category name. If None, computes for all beliefs.

        Returns:
            An 8D list representing the centroid, or None if no beliefs.
        """
        all_positions = []
        all_masses = []

        if category:
            beliefs = self._read_category(category)
        else:
            beliefs = self.get_all_beliefs() # This already updates access counts

        for b in beliefs:
            pos = b.get("position_8d")
            mass = b.get("mass")
            if pos is not None and len(pos) == 8 and mass is not None and mass > 0:
                all_positions.append(np.array(pos))
                all_masses.append(mass)

        if not all_positions:
            return None

        # Convert to numpy arrays for vectorized operations
        positions_array = np.array(all_positions)
        masses_array = np.array(all_masses).reshape(-1, 1) # Reshape for broadcasting

        weighted_sum = np.sum(positions_array * masses_array, axis=0)
        total_mass = np.sum(masses_array)

        if total_mass == 0:
            return None

        centroid = weighted_sum / total_mass
        return centroid.tolist()

    def get_random_belief(self, category: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve a random belief from a category or all beliefs.

        Mainly for testing/demonstration or if a creative spark is needed.
        """
        import random
        if category:
            beliefs = self._read_category(category)
        else:
            beliefs = self.get_all_beliefs()

        if not beliefs:
            return None

        selected_belief = random.choice(beliefs)

        # Update access count
        if selected_belief:
            self.update_belief_mass(
                category=selected_belief["category"],
                belief_id=selected_belief["id"],
                mass_delta=0 # just to trigger access update
            )
        return selected_belief


    def get_beliefs_by_ids(self, ids: List[str]) -> List[Dict[str, Any]]:
        """Retrieve beliefs by a list of IDs. Optimized for multiple lookups.
        
        Returns beliefs in the order of the input IDs, if found.
        """
        # Create a reverse lookup for quick access to beliefs by ID
        # This is efficient if `ids` is long and there are many beliefs
        # but for small lists or frequent calls, direct iteration is fine.
        id_to_belief: Dict[str, Dict[str, Any]] = {}
        for cat_name in BELIEF_CATEGORIES.keys():
            for belief in self._read_category(cat_name):
                id_to_belief[belief.get("id")] = belief
        
        found_beliefs = []
        now = _now_iso()
        
        for belief_id in ids:
            belief = id_to_belief.get(belief_id)
            if belief:
                # Update access count for the retrieved belief
                belief["last_accessed"] = now
                belief["access_count"] = belief.get("access_count", 0) + 1
                # Note: This will re-write the category file for each accessed belief.
                # For performance, might consider batching writes or only writing on exit.
                # For current scale, this is acceptable.
                self._write_category(belief["category"], self._read_category(belief["category"]))
                found_beliefs.append(belief)

        return found_beliefs


    def get_identity_centroid(self) -> Optional[List[float]]:
        """Returns the mass-weighted centroid of all self_identity beliefs."""
        return self.get_mass_weighted_centroid(category="self_identity")

    def get_random_knowledge(self) -> Optional[Dict[str, Any]]:
        """Retrieve a random knowledge belief."""
        return self.get_random_belief(category="knowledge")

    def get_random_skill(self) -> Optional[Dict[str, Any]]:
        """Retrieve a random skill belief."""
        return self.get_random_belief(category="skills")


# ── Attrition (Nightly Call) ────────────────────────────────────────

def run_attrition_pass(belief_store: BeliefStore, current_date: Optional[datetime] = None) -> None:
    """Applies cognitive attrition to all beliefs.

    This function should be called nightly, e.g., by the dream engine.
    It recalculates confidence based on age, verifications, relations,
    and stability. Beliefs below a confidence threshold are pruned.

    Args:
        belief_store: The BeliefStore instance to operate on.
        current_date: Optional. For testing; defaults to now.
    """
    logger.info("Starting nightly cognitive attrition pass...")
    now = current_date or datetime.now().astimezone()

    pruned_count = 0
    updated_count = 0
    total_beliefs = 0

    for category, filename in BELIEF_CATEGORIES.items():
        beliefs = belief_store._read_category(category)
        new_beliefs = []

        for belief in beliefs:
            total_beliefs += 1
            created_at_str = belief.get("created_at")
            if not created_at_str:
                # Skip beliefs without creation date
                new_beliefs.append(belief)
                continue

            try:
                created_at = datetime.fromisoformat(created_at_str)
            except ValueError:
                logger.warning(f"Invalid created_at format for belief {belief.get('id')}: {created_at_str}")
                new_beliefs.append(belief)
                continue

            # --- Attrition Components ---
            # T: Time Held Decay (exponential decay based on age)
            age_days = (now - created_at).days
            time_decay_factor = math.exp(-age_days / 365.0) # ~37% confidence after 1 year

            # R: Reliance (inbound references) — represented by access_count
            # Higher access_count means higher reliance, less decay
            reliance_factor = min(1.0, belief.get("access_count", 0) / 10.0) # Max 1.0 at 10 accesses

            # V: Verifications (explicit reaffirmations) — directly reduces decay
            verification_factor = min(1.0, belief.get("verifications", 0.0) / 5.0) # Max 1.0 at 5 verifications

            # S: Stability (encoding stability) — beliefs formed in stable states are more robust
            encoding_lagrangian = belief.get("encoding_lagrangian", {})
            s_total_at_encoding = encoding_lagrangian.get("s_total", 0.15) # Default to low instability
            stability_factor = _clamp(1.0 - s_total_at_encoding, 0.0, 1.0)

            # --- Composite Confidence Calculation ---
            # Base confidence + (weighted sum of factors) * stability_factor
            # The 0.2 is a floor to prevent immediate decay for new beliefs
            base_confidence = 0.2
            w_T = time_decay_factor * 0.3
            w_R = reliance_factor * 0.3
            w_V = verification_factor * 0.2

            new_confidence = base_confidence + w_T + w_R + w_V
            new_confidence *= (0.5 + stability_factor) # Stability has a strong amplifying/dampening effect

            new_confidence = _clamp(new_confidence, 0.0, 1.0)

            belief["confidence"] = new_confidence

            # Update mass based on new confidence (not directly by attrition, but related)
            # Recalculate mass from scratch to capture all current factors
            omega_at_encoding = encoding_lagrangian.get("omega", 0.5)
            stability_index = belief.get("stability_index", 0.5)
            m_s = new_confidence
            m_a = omega_at_encoding * (1 - s_total_at_encoding) * (0.5 + stability_index)
            belief["mass"] = m_s + m_a

            updated_count += 1

            if new_confidence >= 0.20:
                new_beliefs.append(belief)
            else:
                pruned_count += 1
                logger.debug(f"Pruned belief {belief.get('id')} (confidence={new_confidence:.2f})")

        belief_store._write_category(category, new_beliefs)

    logger.info(
        f"Cognitive attrition pass complete: "
        f"{updated_count} beliefs updated, {pruned_count} beliefs pruned."
    )



def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value to [lo, hi]."""
    return max(lo, min(hi, v))
