"""
Helix — Belief Cosmology (Spatial Expansion Engine)

Provides two mechanisms to fix the 8D spatial density problem:

1. POSITION SCALING — The JL projection outputs positions with std ~0.09
   per dimension, cramming 1752 beliefs into a ball of radius ~0.2.
   This module applies a data-derived scale factor to spread positions
   out so the gravity formula (mass/d²) can meaningfully discriminate.

2. HUBBLE EXPANSION — Space expands proportionally to belief formation.
   Each new belief slightly inflates all existing positions. This creates
   growing empty space between clusters over time, making proximity
   increasingly meaningful. Older beliefs drift outward naturally.

Galaxies are NOT hardcoded by category. They form dynamically from the
natural clustering of related beliefs. Dense clusters (lexicon entries,
consolidated beliefs) become gravitational centers that pull lighter
beliefs into their orbit.

Position lifecycle:
  1. New belief created → embed_384d → JL_project → scale → base_position_8d
  2. On query, expanded position = base_position * expansion_factor(epoch)
  3. Nightly: flush expanded positions to disk during consolidation

SCALE_FACTOR derivation (from 2026-06-04 audit):
  - Median pairwise distance at scale 1: 0.224
  - At scale 1: gravity(near=0.12) = 69, gravity(far=0.56) = 3.2
  - The gravity RATIO is scale-invariant (21x at any scale)
  - But absolute values matter for the focus budget cutoff:
    At scale 1, even "far" beliefs score 3.2 — they all compete.
    At scale 5, "far" beliefs score 0.13 — naturally filtered by budget.
  - SCALE_FACTOR = 5 chosen so that bottom 50% of beliefs by distance
    have gravity < 0.5 (vs top beliefs at ~2-3), making the focus
    budget of 2-5 beliefs naturally exclude noise.

EXPANSION_PER_BELIEF derivation:
  - Target: positions double after ~1400 new beliefs (roughly 1 week of
    active learning at ~200 beliefs/day)
  - ln(2) / 1400 ≈ 0.0005
"""

import logging
import numpy as np
from typing import Optional

logger = logging.getLogger("helix.core.belief_cosmology")

# ── Scale Factor ─────────────────────────────────────────────────────
# Applied to raw JL positions at creation time. Spreads beliefs from
# a radius-0.2 ball to a radius-1.0 ball. Does not change relative
# distances — just makes absolute distances large enough for the
# gravity formula's discrimination to matter with small focus budgets.
#
# Derived: at scale 5, a budget of 5 beliefs naturally excludes
# bottom-50% candidates by gravity score.

SCALE_FACTOR = 5.0

# ── Expansion ────────────────────────────────────────────────────────
# Space expands with belief formation, not time.
# Each new belief nudges all positions outward.
# After ~1400 new beliefs: positions double.
# After ~2800: positions 4x. Creates meaningful empty space.

EXPANSION_PER_BELIEF = 0.0005


# ── Position Computation ─────────────────────────────────────────────

def compute_position(
    embedding_384d: np.ndarray,
    projection,
) -> np.ndarray:
    """Compute a belief's base 8D position: JL projection × scale.

    This is called ONCE at belief creation. The result is stored as
    base_position_8d and never recomputed.

    Args:
        embedding_384d: Raw 384D embedding vector.
        projection: CognitiveProjection instance (384D → 8D).

    Returns:
        Scaled 8D position vector (np.float32).
    """
    jl_pos = projection.project(embedding_384d)
    return jl_pos * SCALE_FACTOR


def get_expanded_position(
    base_position: np.ndarray,
    creation_epoch: int,
    current_epoch: int,
) -> np.ndarray:
    """Compute current position with Hubble expansion applied.

    Positions drift outward based on how many beliefs have been created
    since this belief was born. Older beliefs are further from the
    galaxy center. Newer beliefs enter closer.

    Args:
        base_position: The belief's base 8D position (JL × scale).
        creation_epoch: Total belief count when this belief was created.
        current_epoch: Current total belief count.

    Returns:
        Expanded 8D position vector.
    """
    base = np.asarray(base_position, dtype=np.float32)
    if current_epoch <= creation_epoch:
        return base

    delta = current_epoch - creation_epoch
    expansion_factor = (1.0 + EXPANSION_PER_BELIEF) ** delta

    return base * expansion_factor


def expansion_factor_for(creation_epoch: int, current_epoch: int) -> float:
    """Return the scalar expansion factor between two epochs.

    Useful for logging and diagnostics.
    """
    if current_epoch <= creation_epoch:
        return 1.0
    delta = current_epoch - creation_epoch
    return (1.0 + EXPANSION_PER_BELIEF) ** delta


# ═══════════════════════════════════════════════════════════════════════
# Dynamic Galaxy Formation
#
# Galaxies are NOT hardcoded by category. They form dynamically from
# lexicon entries, which serve as gravitational star-centers. Each
# lexicon entry gets a position (mass-weighted centroid of beliefs
# that reference it). Beliefs orbit near the galaxy center they
# relate to most.
#
# When querying: FAISS finds candidates → group by nearest galaxy →
# score each galaxy → pull from the strongest one(s).
# ═══════════════════════════════════════════════════════════════════════

class GalaxyCenter:
    """A gravitational center in the 8D manifold.

    Typically corresponds to a lexicon entry — a dense concept or person
    that multiple beliefs reference. Galaxy centers have high mass
    (proportional to their member belief count) and serve as the
    anchor points that beliefs orbit around.
    """
    __slots__ = ("id", "term", "summary", "category", "position",
                 "mass", "member_count")

    def __init__(
        self,
        lex_id: str,
        term: str,
        summary: str,
        category: str,
        position: np.ndarray,
        mass: float,
        member_count: int,
    ):
        self.id = lex_id
        self.term = term
        self.summary = summary
        self.category = category
        self.position = np.asarray(position, dtype=np.float32)
        self.mass = mass
        self.member_count = member_count

    def __repr__(self):
        return (
            f"GalaxyCenter({self.term!r}, mass={self.mass:.1f}, "
            f"members={self.member_count})"
        )


class GalaxyMap:
    """Dynamic map of galaxy centers in the 8D belief manifold.

    Built from the lexicon and belief store. Each lexicon entry becomes
    a galaxy center positioned at the mass-weighted centroid of the
    beliefs that reference it.

    Usage:
        galaxy_map = GalaxyMap()
        galaxy_map.build(lexicon_entries, all_beliefs, projection)
        nearest = galaxy_map.find_nearest(query_position)
        groups = galaxy_map.group_beliefs(scored_beliefs)
    """

    # Minimum beliefs referencing a term for it to qualify as a galaxy
    MIN_MEMBERS = 2

    # Mass multiplier: galaxy mass = member_count * MASS_PER_MEMBER
    # A galaxy with 10 members has mass 30 (10 * 3.0)
    # compared to individual beliefs at mass ~1.0
    MASS_PER_MEMBER = 3.0

    # Maximum mass cap to prevent runaway gravity
    MAX_GALAXY_MASS = 100.0

    def __init__(self):
        self.centers: list[GalaxyCenter] = []
        self._center_positions = None  # Nx8 matrix for fast distance
        self._built = False

    def build(
        self,
        lexicon_entries: list[dict],
        all_beliefs: list[dict],
        projection,
        physics_engine=None,
    ):
        """Build galaxy centers from lexicon entries and belief positions.

        For each lexicon entry, finds all beliefs mentioning that term
        and computes the mass-weighted centroid as the galaxy position.

        Args:
            lexicon_entries: List of lexicon dicts (id, term, summary, category).
            all_beliefs: List of all belief dicts (content, position_8d, mass).
            projection: CognitiveProjection instance for embedding terms.
            physics_engine: PhysicsEngine for embedding text (fallback).
        """
        import re

        self.centers = []

        for entry in lexicon_entries:
            term = entry.get("term", "")
            if not term or len(term) < 2:
                continue

            # Skip common articles and noise terms
            if term.lower() in ("the", "a", "an", "is", "it", "this", "that"):
                continue

            lex_id = entry.get("id", "")
            summary = entry.get("summary", "")
            category = entry.get("category", "")

            # Find beliefs that reference this term
            term_lower = term.lower()
            term_pattern = re.compile(r'\b' + re.escape(term_lower) + r'\b')

            member_positions = []
            member_masses = []

            for b in all_beliefs:
                content = b.get("content", "")
                if not content:
                    continue
                if not term_pattern.search(content.lower()):
                    continue

                pos = b.get("position_8d")
                if pos and len(pos) == 8:
                    member_positions.append(pos)
                    member_masses.append(b.get("mass", 1.0))

            if len(member_positions) < self.MIN_MEMBERS:
                continue

            # Compute mass-weighted centroid
            positions = np.array(member_positions, dtype=np.float32)
            masses = np.array(member_masses, dtype=np.float32)
            weights = masses / (masses.sum() + 1e-8)
            centroid = (positions * weights[:, np.newaxis]).sum(axis=0)

            # Galaxy mass scales with member count but caps out
            galaxy_mass = min(
                len(member_positions) * self.MASS_PER_MEMBER,
                self.MAX_GALAXY_MASS,
            )

            self.centers.append(GalaxyCenter(
                lex_id=lex_id,
                term=term,
                summary=summary,
                category=category,
                position=centroid,
                mass=galaxy_mass,
                member_count=len(member_positions),
            ))

        # Build position matrix for fast nearest-galaxy lookups
        if self.centers:
            self._center_positions = np.array(
                [c.position for c in self.centers], dtype=np.float32,
            )
        else:
            self._center_positions = np.zeros((0, 8), dtype=np.float32)

        self._built = True
        logger.info(
            "GalaxyMap built: %d centers from %d lexicon entries. "
            "Top: %s",
            len(self.centers),
            len(lexicon_entries),
            ", ".join(
                f"{c.term}({c.member_count})"
                for c in sorted(
                    self.centers, key=lambda c: c.member_count, reverse=True,
                )[:5]
            ),
        )

    def find_nearest(
        self,
        position: np.ndarray,
        top_k: int = 3,
    ) -> list[GalaxyCenter]:
        """Find the K galaxy centers closest to a given position.

        Args:
            position: 8D query position.
            top_k: Number of nearest centers to return.

        Returns:
            List of GalaxyCenter objects, sorted by distance ascending.
        """
        if not self._built or len(self.centers) == 0:
            return []

        pos = np.asarray(position, dtype=np.float32)
        dists = np.linalg.norm(self._center_positions - pos, axis=1)
        k = min(top_k, len(self.centers))
        nearest_indices = np.argpartition(dists, k)[:k]
        nearest_indices = nearest_indices[np.argsort(dists[nearest_indices])]

        return [self.centers[i] for i in nearest_indices]

    def group_beliefs(
        self,
        scored_beliefs: list[dict],
    ) -> dict[str, list[dict]]:
        """Group scored beliefs by their nearest galaxy center.

        Each belief is assigned to the galaxy center closest to its
        8D position. Returns a dict mapping galaxy_id → list of beliefs.

        Beliefs not near any galaxy go into the "_unclustered" group.

        Args:
            scored_beliefs: List of dicts with 'position_8d' field.

        Returns:
            Dict mapping galaxy_id → list of belief dicts.
        """
        if not self._built or len(self.centers) == 0:
            return {"_unclustered": scored_beliefs}

        groups: dict[str, list[dict]] = {c.id: [] for c in self.centers}
        groups["_unclustered"] = []

        for b in scored_beliefs:
            pos = b.get("position_8d")
            if pos is None:
                groups["_unclustered"].append(b)
                continue

            pos_arr = np.asarray(pos, dtype=np.float32)
            dists = np.linalg.norm(
                self._center_positions - pos_arr, axis=1,
            )
            nearest_idx = int(np.argmin(dists))
            nearest_center = self.centers[nearest_idx]

            groups[nearest_center.id].append(b)

        return groups

    def score_galaxies(
        self,
        query_position: np.ndarray,
        grouped_beliefs: dict[str, list[dict]],
    ) -> list[tuple[GalaxyCenter, float, list[dict]]]:
        """Score galaxies by combined relevance of their members.

        For each galaxy, the score is:
          galaxy_gravity + sum(member_gravity_scores) / member_count

        This ensures galaxies with more high-gravity members rank higher,
        but a single very strong match can also elevate a small galaxy.

        Args:
            query_position: 8D position of the current query/thought.
            grouped_beliefs: Output of group_beliefs().

        Returns:
            List of (GalaxyCenter, score, beliefs) tuples, sorted by
            score descending.
        """
        if not self._built:
            return []

        query_pos = np.asarray(query_position, dtype=np.float32)
        results = []

        for center in self.centers:
            members = grouped_beliefs.get(center.id, [])
            if not members:
                continue

            # Galaxy center gravity to the query
            dist_sq = float(np.sum((center.position - query_pos) ** 2))
            galaxy_gravity = center.mass / (dist_sq + 1e-4)

            # Sum of member gravity scores (already computed by _gravity_query)
            member_gravity_sum = sum(b.get("gravity", 0) for b in members)
            avg_member_gravity = member_gravity_sum / len(members)

            # Combined score: galaxy pull + average member pull
            score = galaxy_gravity + avg_member_gravity

            results.append((center, score, members))

        # Sort by score descending
        results.sort(key=lambda x: x[1], reverse=True)
        return results

    def get_center_by_id(self, lex_id: str) -> Optional[GalaxyCenter]:
        """Look up a galaxy center by its lexicon ID."""
        for c in self.centers:
            if c.id == lex_id:
                return c
        return None

    @property
    def is_built(self) -> bool:
        return self._built
