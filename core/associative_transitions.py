"""Sequence-sensitive associative memory over Helix's 8D cluster space.

The semantic manifold should not be rewritten merely because several facts
were retrieved together.  A retrieval set is usually a bag assembled for one
prompt, so pulling every member toward one centroid destroys distinctions the
semantic lane worked to preserve.

This module learns a narrower signal: direct movement from one active cluster
to the next.  Repeated A -> B transitions create a directed edge and gently
move only the two *cluster prototypes* in a separate 8D associative overlay.
Individual belief and memory positions are never changed.

The result is deliberately a third retrieval lane rather than a replacement
for mRAG.  mRAG supplies the accurate foreground; this overlay supplies a
small, additive "what this usually makes me think of next" complement.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("helix.core.associative_transitions")


STATE_FILENAME = "associative_transitions.json"
STATE_VERSION = 1

# One accidental transition is not a habit.  Two observations are enough to
# surface a faint association; repetition makes it steadily stronger.
ACTIVATION_THRESHOLD = 2.0

# Very slow forgetting.  A repeatedly reinforced childhood association can
# survive for years, while a one-off edge still eventually disappears.
DAILY_DECAY_FACTOR = 0.999

# Plasticity applies to cluster prototypes only.  The caps are intentionally
# smaller than the old per-belief Hebbian step.
CLUSTER_NUDGE_RATE = 0.015
CLUSTER_MAX_STEP = 0.005
CLUSTER_MIN_DISTANCE = 0.025

MAX_EDGE_WEIGHT = 100.0
MAX_EDGES = 20_000
PERSIST_INTERVAL = 10


class AssociativeTransitionMemory:
    """Persistent directed transition graph with an 8D cluster overlay."""

    def __init__(self, data_dir: str | Path = "data"):
        self.data_dir = Path(data_dir)
        self.state_path = self.data_dir / STATE_FILENAME

        # (source_cluster, destination_cluster) -> decayed observation count
        self.edges: Dict[Tuple[str, str], float] = {}
        # Learned cluster prototypes.  These begin at the cluster's canonical
        # 8D centroid, then move only in this overlay.
        self.positions: Dict[str, np.ndarray] = {}

        self._previous_cluster: Optional[str] = None
        self._previous_position: Optional[np.ndarray] = None
        self._observations_since_persist = 0
        self._last_decay_at = time.time()
        self._load_state()

    # ------------------------------------------------------------------
    # Learning
    # ------------------------------------------------------------------

    def observe(
        self,
        cluster_id: Optional[str],
        position_8d: Optional[Iterable[float]],
    ) -> bool:
        """Observe the single foreground cluster active on this turn.

        Only the transition from the prior foreground cluster to this one is
        learned.  The other items injected on either turn are intentionally
        ignored: this prevents mRAG result bags and associative recalls from
        teaching themselves back into the graph.

        Returns True when a cross-cluster transition was recorded.
        """
        cluster_id = str(cluster_id or "").strip()
        pos = self._coerce_position(position_8d)
        if not cluster_id or pos is None:
            self._previous_cluster = None
            self._previous_position = None
            return False

        self._maybe_decay()
        self._ensure_position(cluster_id, pos)

        learned = False
        became_active = False
        previous = self._previous_cluster
        if previous and previous != cluster_id:
            if self._previous_position is not None:
                self._ensure_position(previous, self._previous_position)
            edge = (previous, cluster_id)
            old_weight = self.edges.get(edge, 0.0)
            self.edges[edge] = min(
                MAX_EDGE_WEIGHT,
                old_weight + 1.0,
            )
            became_active = old_weight < ACTIVATION_THRESHOLD <= self.edges[edge]
            self._nudge_cluster_pair(previous, cluster_id)
            learned = True

        self._previous_cluster = cluster_id
        # Keep the canonical position from this activation for recovery if a
        # caller later clears or prunes the overlay node.
        self._previous_position = pos.copy()
        self._observations_since_persist += 1

        if len(self.edges) > MAX_EDGES:
            self._prune_edges()
        # Do not leave the first usable association only in RAM. Subsequent
        # refinements batch normally to avoid a filesystem write every pulse.
        if became_active or self._observations_since_persist >= PERSIST_INTERVAL:
            self.save()
        return learned

    def break_sequence(self) -> None:
        """Prevent the next observation from forming a false long-gap edge."""
        self._previous_cluster = None
        self._previous_position = None

    # ------------------------------------------------------------------
    # Recall
    # ------------------------------------------------------------------

    def recall(
        self,
        source_cluster: Optional[str],
        *,
        limit: int = 2,
    ) -> List[Dict[str, Any]]:
        """Return learned destination clusters for ``source_cluster``.

        Direct transitions dominate.  A weaker two-hop path allows a learned
        A -> B -> C sequence to make C faintly available from A, which is how
        chains such as guilt -> mother -> relationships can remain relational
        without making every co-injected item a neighbor.
        """
        source = str(source_cluster or "").strip()
        if not source or limit <= 0:
            return []

        self._maybe_decay()
        direct: Dict[str, float] = {}
        for (edge_source, destination), weight in self.edges.items():
            if edge_source == source and weight >= ACTIVATION_THRESHOLD:
                direct[destination] = max(direct.get(destination, 0.0), weight)

        scored: Dict[str, Dict[str, Any]] = {}
        for destination, weight in direct.items():
            confidence = self._confidence(weight)
            scored[destination] = {
                "cluster_id": destination,
                "score": 1.0 + confidence,
                "edge_weight": weight,
                "hops": 1,
                "distance_8d": self._overlay_distance(source, destination),
            }

        # Bounded two-hop spreading.  It is always weaker than a direct edge,
        # and every leg must independently cross the activation threshold.
        for middle, first_weight in direct.items():
            first_confidence = self._confidence(first_weight)
            for (edge_source, destination), second_weight in self.edges.items():
                if edge_source != middle or destination == source:
                    continue
                if second_weight < ACTIVATION_THRESHOLD:
                    continue
                path_score = 0.45 * first_confidence * self._confidence(second_weight)
                current = scored.get(destination)
                if current is None or path_score > current["score"]:
                    scored[destination] = {
                        "cluster_id": destination,
                        "score": path_score,
                        "edge_weight": min(first_weight, second_weight),
                        "hops": 2,
                        "via": middle,
                        "distance_8d": self._overlay_distance(source, destination),
                    }

        # The learned 8D distance is a tie-breaker, not a free association by
        # itself.  No graph support means no recall, so initial JL projection
        # collisions cannot invent a subconscious link.
        ranked = list(scored.values())
        ranked.sort(key=lambda x: (-x["score"], x["distance_8d"], x["cluster_id"]))
        return ranked[:limit]

    def get_stats(self) -> Dict[str, Any]:
        strong = sum(1 for weight in self.edges.values() if weight >= ACTIVATION_THRESHOLD)
        return {
            "edges": len(self.edges),
            "active_edges": strong,
            "clusters": len(self.positions),
            "previous_cluster": self._previous_cluster,
        }

    # ------------------------------------------------------------------
    # 8D overlay
    # ------------------------------------------------------------------

    @staticmethod
    def _coerce_position(position: Optional[Iterable[float]]) -> Optional[np.ndarray]:
        if position is None:
            return None
        try:
            arr = np.asarray(list(position), dtype=np.float32).reshape(-1)
        except (TypeError, ValueError):
            return None
        if arr.size != 8 or not np.all(np.isfinite(arr)):
            return None
        return arr

    def _ensure_position(self, cluster_id: str, canonical: np.ndarray) -> None:
        if cluster_id not in self.positions:
            self.positions[cluster_id] = canonical.copy()

    def _nudge_cluster_pair(self, source: str, destination: str) -> None:
        source_pos = self.positions.get(source)
        destination_pos = self.positions.get(destination)
        if source_pos is None or destination_pos is None:
            return

        delta = destination_pos - source_pos
        distance = float(np.linalg.norm(delta))
        if distance <= CLUSTER_MIN_DISTANCE or distance <= 1e-8:
            return

        total_step = min(CLUSTER_NUDGE_RATE * distance, CLUSTER_MAX_STEP)
        # Symmetric movement keeps the overlay's global center stable.  The
        # graph edge remains directed even though spatial binding is mutual.
        half_step = 0.5 * total_step
        unit = delta / distance
        self.positions[source] = source_pos + unit * half_step
        self.positions[destination] = destination_pos - unit * half_step

    def _overlay_distance(self, source: str, destination: str) -> float:
        a = self.positions.get(source)
        b = self.positions.get(destination)
        if a is None or b is None:
            return float("inf")
        return float(np.linalg.norm(a - b))

    @staticmethod
    def _confidence(weight: float) -> float:
        # Saturating reinforcement: early repetition matters most and an old
        # story cannot acquire unbounded dominance merely by being repeated.
        return 1.0 - math.exp(-max(0.0, weight) / 4.0)

    # ------------------------------------------------------------------
    # Decay and persistence
    # ------------------------------------------------------------------

    def _maybe_decay(self, now: Optional[float] = None) -> None:
        now = float(now if now is not None else time.time())
        elapsed_days = max(0.0, (now - self._last_decay_at) / 86_400.0)
        if elapsed_days < 1.0:
            return

        factor = DAILY_DECAY_FACTOR ** elapsed_days
        for edge in list(self.edges):
            decayed = self.edges[edge] * factor
            if decayed < 0.25:
                del self.edges[edge]
            else:
                self.edges[edge] = decayed
        self._last_decay_at = now

    def _prune_edges(self) -> None:
        keep = sorted(self.edges.items(), key=lambda pair: pair[1], reverse=True)[:MAX_EDGES]
        self.edges = dict(keep)

    def save(self) -> None:
        payload = {
            "schema_version": STATE_VERSION,
            "saved_at": time.time(),
            "last_decay_at": self._last_decay_at,
            "edges": [
                {"source": src, "destination": dst, "weight": weight}
                for (src, dst), weight in sorted(self.edges.items())
            ],
            "positions": {
                cluster_id: [round(float(x), 7) for x in position]
                for cluster_id, position in sorted(self.positions.items())
            },
        }
        try:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            temp_path = self.state_path.with_suffix(self.state_path.suffix + ".tmp")
            with temp_path.open("w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.state_path)
            self._observations_since_persist = 0
        except Exception as exc:
            logger.warning("Failed to persist associative transitions: %s", exc)

    def _load_state(self) -> None:
        if not self.state_path.exists():
            return
        try:
            with self.state_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if payload.get("schema_version") != STATE_VERSION:
                logger.warning("Ignoring unknown associative state schema")
                return

            for record in payload.get("edges", []):
                source = str(record.get("source", "")).strip()
                destination = str(record.get("destination", "")).strip()
                weight = float(record.get("weight", 0.0))
                if source and destination and source != destination and weight > 0.0:
                    self.edges[(source, destination)] = min(weight, MAX_EDGE_WEIGHT)

            for cluster_id, raw_position in payload.get("positions", {}).items():
                position = self._coerce_position(raw_position)
                if cluster_id and position is not None:
                    self.positions[str(cluster_id)] = position

            self._last_decay_at = float(payload.get("last_decay_at", time.time()))
            self._maybe_decay()
            logger.info(
                "Associative transitions loaded: %d edges across %d clusters",
                len(self.edges), len(self.positions),
            )
        except Exception as exc:
            logger.warning("Failed to load associative transitions: %s", exc)
