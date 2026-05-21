"""
Helix — Co-Occurrence Hook (Real-Time Hebbian Belief Wiring)

A post-pulse hook that tracks which beliefs are co-injected into the
context window and strengthens their relational links automatically.
Inspired by Hebbian learning: "beliefs that fire together wire together."

Architecture:
  - Every pulse: accumulate co-occurrence counts for all pairs of
    injected beliefs in a sparse in-memory dict.
  - Every N pulses (or on state transition to RESTING): run HDBSCAN
    on co-occurring beliefs to discover natural clusters, then wire
    bidirectional relations between cluster members.
  - Persist co-occurrence state to disk for crash recovery.

The nightly Curator can then read pre-built relational clusters instead
of running raw UMAP/HDBSCAN from scratch on position vectors.

No LLM calls. CPU-only. Non-blocking.
"""

import json
import logging
import os
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("helix.core.co_occurrence_hook")

# ── Configuration ────────────────────────────────────────────────────

# How many pulses between clustering passes (default trigger)
CLUSTER_INTERVAL = 10

# Minimum co-occurrence count before a relation is considered real
CO_OCCURRENCE_THRESHOLD = 3

# Minimum cluster size for HDBSCAN
MIN_CLUSTER_SIZE = 3

# Daily decay factor for co-occurrence counts (0.95 = 5% decay per day)
DAILY_DECAY_FACTOR = 0.95

# State file for persistence across restarts
STATE_FILENAME = "co_occurrence_state.json"


class CoOccurrenceTracker:
    """Tracks belief co-injection patterns and wires relations.

    Accumulates pairwise co-occurrence counts every pulse, then
    periodically clusters them and updates the belief store's
    relation fields.

    Attributes:
        co_counts: Sparse dict mapping frozenset({id_a, id_b}) → count
        belief_store: Reference to the BeliefStore for writing relations
        data_dir: Path to data directory for state persistence
        _pulses_since_cluster: Counter for triggering cluster passes
        _last_decay_day: Day number of last decay application
    """

    def __init__(
        self,
        belief_store,
        data_dir: str = "data",
        cognitive_space=None,
    ):
        """Initialize the co-occurrence tracker.

        Args:
            belief_store: BeliefStore instance for reading/writing relations
            data_dir: Directory for state persistence
            cognitive_space: Optional CognitiveSpace instance for Hebbian
                drift (updating 8D positions of related beliefs)
        """
        self.belief_store = belief_store
        self.data_dir = Path(data_dir)
        self.cognitive_space = cognitive_space
        self.co_counts: Dict[frozenset, float] = defaultdict(float)
        self._pulses_since_cluster = 0
        self._last_decay_day = time.localtime().tm_yday
        self._last_cluster_time = 0.0

        # Load persisted state if available
        self._load_state()

    # ── Pulse Accumulation ───────────────────────────────────────────

    def accumulate(self, belief_ids: List[str]) -> None:
        """Record co-occurrence for all pairs of injected beliefs.

        Called every pulse with the list of belief IDs that were
        co-present in the preconscious injection.

        Args:
            belief_ids: List of belief IDs injected this pulse
        """
        if len(belief_ids) < 2:
            return

        # Deduplicate
        unique_ids = list(set(belief_ids))

        # Increment co-occurrence count for all pairs
        for id_a, id_b in combinations(unique_ids, 2):
            pair = frozenset({id_a, id_b})
            self.co_counts[pair] += 1.0

        self._pulses_since_cluster += 1

    def should_cluster(self, pulse_state: str = "REGULAR") -> bool:
        """Check if it's time to run a clustering pass.

        Triggers on:
          1. Every CLUSTER_INTERVAL pulses (default 10), OR
          2. When the system transitions to RESTING state

        Args:
            pulse_state: Current pulse loop state (ACTIVE/REGULAR/RESTING)

        Returns:
            True if a clustering pass should run
        """
        # Trigger on state transition to RESTING
        if pulse_state == "RESTING" and self._pulses_since_cluster > 0:
            return True

        # Trigger on interval
        if self._pulses_since_cluster >= CLUSTER_INTERVAL:
            return True

        return False

    # ── Clustering Pass ──────────────────────────────────────────────

    def run_cluster_pass(self) -> Dict[str, Any]:
        """Run HDBSCAN on co-occurring beliefs and wire relations.

        Returns stats about what was discovered and wired.
        """
        self._pulses_since_cluster = 0
        self._last_cluster_time = time.time()

        # Apply daily decay if needed
        self._maybe_decay()

        # Filter to pairs above threshold
        strong_pairs = {
            pair: count
            for pair, count in self.co_counts.items()
            if count >= CO_OCCURRENCE_THRESHOLD
        }

        if len(strong_pairs) < 3:
            logger.debug(
                "Co-occurrence: %d strong pairs (need 3+), skipping cluster",
                len(strong_pairs),
            )
            self._save_state()
            return {"clusters": 0, "relations_added": 0, "strong_pairs": len(strong_pairs)}

        # Build adjacency for HDBSCAN
        clusters = self._cluster_pairs(strong_pairs)

        # Wire relations for each cluster
        relations_added = 0
        for cluster_ids in clusters:
            added = self._wire_cluster_relations(cluster_ids)
            relations_added += added

        logger.info(
            "Co-occurrence clustering: %d clusters, %d relations wired "
            "from %d strong pairs (threshold=%d)",
            len(clusters), relations_added,
            len(strong_pairs), CO_OCCURRENCE_THRESHOLD,
        )

        # Persist state
        self._save_state()

        return {
            "clusters": len(clusters),
            "relations_added": relations_added,
            "strong_pairs": len(strong_pairs),
            "cluster_sizes": [len(c) for c in clusters],
        }

    def _cluster_pairs(
        self, strong_pairs: Dict[frozenset, float]
    ) -> List[List[str]]:
        """Cluster co-occurring beliefs using HDBSCAN.

        Builds a distance matrix from co-occurrence counts and
        runs HDBSCAN to find natural groupings.

        Args:
            strong_pairs: Filtered pairs above co-occurrence threshold

        Returns:
            List of clusters, each a list of belief IDs
        """
        # Collect all unique belief IDs from strong pairs
        all_ids = set()
        for pair in strong_pairs:
            all_ids.update(pair)
        all_ids = sorted(all_ids)  # Deterministic ordering
        id_to_idx = {bid: i for i, bid in enumerate(all_ids)}
        n = len(all_ids)

        if n < MIN_CLUSTER_SIZE:
            return []

        try:
            import numpy as np
            import hdbscan

            # Build distance matrix (inverse of co-occurrence = distance)
            # High co-occurrence → small distance
            dist_matrix = np.ones((n, n), dtype=np.float64)
            np.fill_diagonal(dist_matrix, 0.0)

            max_count = max(strong_pairs.values()) if strong_pairs else 1.0

            for pair, count in strong_pairs.items():
                ids = sorted(pair)
                if len(ids) == 2:
                    i = id_to_idx.get(ids[0])
                    j = id_to_idx.get(ids[1])
                    if i is not None and j is not None:
                        # Distance = 1 - (count / max_count)
                        # High co-occurrence → close to 0
                        dist = 1.0 - (count / max_count)
                        dist_matrix[i][j] = dist
                        dist_matrix[j][i] = dist

            # Run HDBSCAN on precomputed distance matrix
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=MIN_CLUSTER_SIZE,
                metric="precomputed",
            )
            labels = clusterer.fit_predict(dist_matrix)

            # Group by label
            clusters: Dict[int, List[str]] = defaultdict(list)
            for idx, label in enumerate(labels):
                if label != -1:  # Skip noise
                    clusters[label].append(all_ids[idx])

            return list(clusters.values())

        except ImportError:
            logger.warning("hdbscan not available — falling back to threshold-based clustering")
            return self._fallback_cluster(strong_pairs, all_ids)
        except Exception as e:
            logger.error("HDBSCAN clustering failed: %s", e)
            return self._fallback_cluster(strong_pairs, all_ids)

    def _fallback_cluster(
        self, strong_pairs: Dict[frozenset, float], all_ids: List[str]
    ) -> List[List[str]]:
        """Simple connected-component clustering when HDBSCAN unavailable.

        Groups beliefs that are transitively connected by strong co-occurrence.
        """
        # Build adjacency list
        adj: Dict[str, Set[str]] = defaultdict(set)
        for pair in strong_pairs:
            ids = list(pair)
            if len(ids) == 2:
                adj[ids[0]].add(ids[1])
                adj[ids[1]].add(ids[0])

        # BFS to find connected components
        visited: Set[str] = set()
        clusters = []

        for start in all_ids:
            if start in visited:
                continue
            component = []
            queue = [start]
            while queue:
                node = queue.pop(0)
                if node in visited:
                    continue
                visited.add(node)
                component.append(node)
                for neighbor in adj.get(node, set()):
                    if neighbor not in visited:
                        queue.append(neighbor)

            if len(component) >= MIN_CLUSTER_SIZE:
                clusters.append(component)

        return clusters

    # ── Relation Wiring ──────────────────────────────────────────────

    def _wire_cluster_relations(self, cluster_ids: List[str]) -> int:
        """Add bidirectional relations between all beliefs in a cluster.

        Only adds new relations — existing relations are preserved.
        After wiring, applies Hebbian drift: related beliefs are pulled
        slightly closer together in 8D space, proportional to their
        co-occurrence count.

        Returns the number of new relations added.

        Args:
            cluster_ids: List of belief IDs in this cluster
        """
        added = 0

        for bid in cluster_ids:
            belief = self.belief_store.get_belief(bid)
            if not belief:
                continue

            existing_relations = set(belief.get("relations", []))
            new_relations = set(cluster_ids) - {bid} - existing_relations

            if new_relations:
                merged = list(existing_relations | new_relations)
                self.belief_store.update_belief(bid, relations=merged)
                added += len(new_relations)
                logger.debug(
                    "Wired %d new relations for %s (total: %d)",
                    len(new_relations), bid, len(merged),
                )

        # Apply Hebbian drift: pull related beliefs closer in 8D space
        if self.cognitive_space and added > 0:
            self._apply_hebbian_drift(cluster_ids)

        return added

    def _apply_hebbian_drift(self, cluster_ids: List[str]) -> None:
        """Apply positional drift to pull co-occurring beliefs closer in 8D.

        For each pair in the cluster, compute a small attractive displacement
        proportional to the pair's co-occurrence count. This makes the manifold
        self-organizing: beliefs that genuinely co-occur drift together over
        time, improving gravity query accuracy.

        The drift is localized and relative:
          - Proportional to the specific pair's co-occurrence strength
          - Normalized by current distance (closer pairs drift less)
          - No arbitrary global cap — manifold degeneration is prevented
            by the concept extractor (independent queries) and mass
            decoupling (no self-reinforcing inflation)
        """
        import numpy as np

        # Base drift fraction per unit of co-occurrence
        # At co_count=3 (threshold), drift = 0.3%
        # At co_count=10, drift = 1.0%
        # At co_count=30, drift = 3.0%
        DRIFT_PER_COCOUNT = 0.001  # 0.1% per co-occurrence count

        drifted = 0
        for id_a, id_b in combinations(cluster_ids, 2):
            pair = frozenset({id_a, id_b})
            co_count = self.co_counts.get(pair, 0)

            if co_count < CO_OCCURRENCE_THRESHOLD:
                continue  # Only drift for genuinely co-occurring pairs

            pt_a = self.cognitive_space.get_point(id_a)
            pt_b = self.cognitive_space.get_point(id_b)

            if pt_a is None or pt_b is None:
                continue

            pos_a = pt_a["position"]
            pos_b = pt_b["position"]

            # Vector from A to B
            delta = pos_b - pos_a
            dist = float(np.linalg.norm(delta))

            if dist < 1e-6:
                continue  # Already co-located

            # Drift fraction scales with co-occurrence count
            drift_frac = DRIFT_PER_COCOUNT * co_count

            # Apply symmetric drift: both beliefs move toward each other
            displacement = delta * (drift_frac / 2.0)
            pt_a["position"] = (pos_a + displacement).astype(np.float32)
            pt_b["position"] = (pos_b - displacement).astype(np.float32)
            drifted += 1

        if drifted > 0:
            self.cognitive_space._tree_dirty = True
            logger.info(
                "Hebbian drift: %d pairs shifted in 8D space",
                drifted,
            )

    # ── Decay ────────────────────────────────────────────────────────

    def _maybe_decay(self) -> None:
        """Apply daily decay to co-occurrence counts.

        Prevents ancient co-occurrences from dominating current patterns.
        Only applies once per calendar day.
        """
        today = time.localtime().tm_yday
        if today == self._last_decay_day:
            return

        days_elapsed = today - self._last_decay_day
        if days_elapsed < 0:
            days_elapsed += 365  # Year boundary

        decay = DAILY_DECAY_FACTOR ** days_elapsed

        decayed_count = 0
        to_remove = []
        for pair, count in self.co_counts.items():
            new_count = count * decay
            if new_count < 0.5:  # Prune near-zero entries
                to_remove.append(pair)
            else:
                self.co_counts[pair] = new_count
                decayed_count += 1

        for pair in to_remove:
            del self.co_counts[pair]

        self._last_decay_day = today
        logger.info(
            "Co-occurrence decay applied (factor=%.3f, %dd): "
            "%d decayed, %d pruned",
            decay, days_elapsed, decayed_count, len(to_remove),
        )

    # ── Persistence ──────────────────────────────────────────────────

    def _save_state(self) -> None:
        """Persist co-occurrence counts to disk."""
        state_path = self.data_dir / STATE_FILENAME
        try:
            # Convert frozenset keys to sorted tuples for JSON
            serializable = {
                "co_counts": {
                    "|".join(sorted(pair)): count
                    for pair, count in self.co_counts.items()
                },
                "last_decay_day": self._last_decay_day,
                "last_cluster_time": self._last_cluster_time,
            }
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(serializable, f, indent=2)
        except Exception as e:
            logger.warning("Failed to save co-occurrence state: %s", e)

    def _load_state(self) -> None:
        """Load persisted co-occurrence state from disk."""
        state_path = self.data_dir / STATE_FILENAME
        if not state_path.exists():
            return

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Reconstruct frozenset keys from "id_a|id_b" strings
            for key_str, count in data.get("co_counts", {}).items():
                ids = key_str.split("|")
                if len(ids) == 2:
                    self.co_counts[frozenset(ids)] = float(count)

            self._last_decay_day = data.get("last_decay_day", time.localtime().tm_yday)
            self._last_cluster_time = data.get("last_cluster_time", 0.0)

            logger.info(
                "Co-occurrence state loaded: %d pairs from %s",
                len(self.co_counts), state_path,
            )
        except Exception as e:
            logger.warning("Failed to load co-occurrence state: %s", e)

    # ── Cluster Data for Nightly Curator ──────────────────────────────

    def get_current_clusters(self) -> List[List[str]]:
        """Return current belief clusters for the nightly Curator.

        The Curator's Phase 3 calls this instead of running UMAP/HDBSCAN
        from scratch. Returns clusters from the latest co-occurrence data.
        """
        strong_pairs = {
            pair: count
            for pair, count in self.co_counts.items()
            if count >= CO_OCCURRENCE_THRESHOLD
        }

        if len(strong_pairs) < 3:
            return []

        return self._cluster_pairs(strong_pairs)


# ── Hook Function (registered in main.py / daemon.py) ────────────────

# Module-level tracker instance (set during registration)
_tracker: Optional[CoOccurrenceTracker] = None


def register_co_occurrence_hook(
    belief_store,
    data_dir: str = "data",
    cognitive_space=None,
) -> CoOccurrenceTracker:
    """Create and register the co-occurrence post-pulse hook.

    Call this during startup to wire the hook into the pulse loop.

    Args:
        belief_store: BeliefStore instance
        data_dir: Directory for state persistence
        cognitive_space: Optional CognitiveSpace instance for Hebbian drift

    Returns:
        The CoOccurrenceTracker instance (for Curator access)
    """
    global _tracker

    from core.post_pulse_hooks import register_hook

    _tracker = CoOccurrenceTracker(
        belief_store=belief_store,
        data_dir=data_dir,
        cognitive_space=cognitive_space,
    )

    def _co_occurrence_hook(ctx) -> None:
        """Post-pulse hook: accumulate co-occurrences, cluster periodically."""
        if not ctx.injected_belief_ids:
            return

        _tracker.accumulate(ctx.injected_belief_ids)

        # Determine current state from spatial_state or pulse cadence
        pulse_state = ctx.spatial_state.get("pulse_state", "REGULAR")

        if _tracker.should_cluster(pulse_state):
            stats = _tracker.run_cluster_pass()
            if stats.get("relations_added", 0) > 0:
                logger.info(
                    "Hebbian wiring pass: %d relations added across %d clusters",
                    stats["relations_added"], stats["clusters"],
                )

    register_hook(_co_occurrence_hook, name="co_occurrence_tracker")
    logger.info("Co-occurrence hook registered (interval=%d pulses)", CLUSTER_INTERVAL)

    return _tracker


def get_tracker() -> Optional[CoOccurrenceTracker]:
    """Get the module-level tracker instance (for Curator access)."""
    return _tracker
