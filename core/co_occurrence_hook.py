"""
Helix — Co-Occurrence Hook (Passive Belief Co-Injection Tracker)

A post-pulse hook that tracks which beliefs are co-injected into the
context window. Accumulates pairwise co-occurrence statistics that the
nightly Curator reads to discover natural synthesis clusters.

This hook is a PASSIVE OBSERVER. It:
  ✓ Counts pairwise co-injection frequency
  ✓ Provides clusters to the Curator via get_current_clusters()
  ✓ Persists co-occurrence state for crash recovery
  ✗ Does NOT write relations to the belief store
  ✗ Does NOT move belief positions in 8D space
  ✗ Does NOT modify any belief properties

The Curator's Phase 3 (compound synthesis) calls get_current_clusters()
during the sleep cycle to find genuine convergence points for LLM-based
insight generation. The co-occurrence data tells the Curator "these
beliefs keep appearing together in the attention field" — the Curator
decides whether that convergence is meaningful.

No LLM calls. CPU-only. Non-blocking.
"""

import json
import logging
import time
from collections import defaultdict
from itertools import combinations
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger("helix.core.co_occurrence_hook")

# ── Configuration ────────────────────────────────────────────────────

# Minimum co-occurrence count before a pair is considered significant
CO_OCCURRENCE_THRESHOLD = 3

# Minimum cluster size for HDBSCAN
MIN_CLUSTER_SIZE = 3

# Daily decay factor for co-occurrence counts (0.95 = 5% decay per day)
DAILY_DECAY_FACTOR = 0.95

# State file for persistence across restarts
STATE_FILENAME = "co_occurrence_state.json"

# How often to persist state (in accumulation calls)
PERSIST_INTERVAL = 50


class CoOccurrenceTracker:
    """Passively tracks belief co-injection patterns.

    Accumulates pairwise co-occurrence counts every pulse. The nightly
    Curator reads clusters via get_current_clusters() for compound
    synthesis. This tracker never writes to the belief store or
    modifies the cognitive manifold.

    Attributes:
        co_counts: Sparse dict mapping frozenset({id_a, id_b}) → count
        data_dir: Path to data directory for state persistence
        _accumulations_since_persist: Counter for periodic state saves
        _last_decay_day: Day number of last decay application
    """

    def __init__(
        self,
        data_dir: str = "data",
    ):
        """Initialize the co-occurrence tracker.

        Args:
            data_dir: Directory for state persistence
        """
        self.data_dir = Path(data_dir)
        self.co_counts: Dict[frozenset, float] = defaultdict(float)
        self._accumulations_since_persist = 0
        self._last_decay_day = time.localtime().tm_yday

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

        self._accumulations_since_persist += 1

        # Periodic state persistence
        if self._accumulations_since_persist >= PERSIST_INTERVAL:
            self._maybe_decay()
            self._save_state()
            self._accumulations_since_persist = 0

    # ── Clustering (on-demand, for Curator) ──────────────────────────

    def get_current_clusters(self) -> List[List[str]]:
        """Return current belief clusters for the nightly Curator.

        The Curator's Phase 3 calls this to discover natural convergence
        points for compound synthesis. Clusters are built from the
        accumulated co-occurrence data using HDBSCAN.

        Returns:
            List of clusters, each a list of belief IDs
        """
        strong_pairs = {
            pair: count
            for pair, count in self.co_counts.items()
            if count >= CO_OCCURRENCE_THRESHOLD
        }

        if len(strong_pairs) < 3:
            return []

        return self._cluster_pairs(strong_pairs)

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
            }
            state_path.parent.mkdir(parents=True, exist_ok=True)
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

            logger.info(
                "Co-occurrence state loaded: %d pairs from %s",
                len(self.co_counts), state_path,
            )
        except Exception as e:
            logger.warning("Failed to load co-occurrence state: %s", e)

    # ── Stats ────────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get tracker statistics for diagnostics."""
        strong = sum(1 for c in self.co_counts.values() if c >= CO_OCCURRENCE_THRESHOLD)
        return {
            "total_pairs": len(self.co_counts),
            "strong_pairs": strong,
            "max_count": max(self.co_counts.values()) if self.co_counts else 0,
            "accumulations_since_persist": self._accumulations_since_persist,
        }


# ── Hook Function (registered in main.py) ────────────────────────────

# Module-level tracker instance (set during registration)
_tracker: Optional[CoOccurrenceTracker] = None


def register_co_occurrence_hook(
    data_dir: str = "data",
) -> CoOccurrenceTracker:
    """Create and register the co-occurrence post-pulse hook.

    Call this during startup to wire the hook into the pulse loop.
    The hook is a passive observer — it only accumulates co-occurrence
    counts and never modifies beliefs or manifold positions.

    Args:
        data_dir: Directory for state persistence

    Returns:
        The CoOccurrenceTracker instance (for Curator access)
    """
    global _tracker

    from core.post_pulse_hooks import register_hook

    _tracker = CoOccurrenceTracker(data_dir=data_dir)

    def _co_occurrence_hook(ctx) -> None:
        """Post-pulse hook: accumulate co-occurrence counts (observe only)."""
        if not ctx.injected_belief_ids:
            return
        _tracker.accumulate(ctx.injected_belief_ids)

    register_hook(_co_occurrence_hook, name="co_occurrence_tracker")
    logger.info("Co-occurrence hook registered (passive observer)")

    return _tracker


def get_tracker() -> Optional[CoOccurrenceTracker]:
    """Get the module-level tracker instance (for Curator access)."""
    return _tracker
