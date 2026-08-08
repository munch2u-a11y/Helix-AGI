"""Read-only mRAG context assembly for identity-shared task focus."""

from __future__ import annotations

import logging
import threading
from typing import Dict, List

from core.unified_retrieval import UnifiedRetrieval
from memory.mrag.semantic_lane import estimate_tokens

logger = logging.getLogger("helix.core.task_cognition.context")


class TaskContextBuilder:
    """Give focus threads the same stores without mutating conscious recall state."""

    def __init__(self, belief_store, memory_manager, physics_engine):
        self.physics = physics_engine
        self.retrieval = UnifiedRetrieval(
            belief_store=belief_store,
            memory_manager=memory_manager,
            physics_engine=physics_engine,
        )
        self._lock = threading.RLock()

    def retrieve(self, query: str, *, max_items: int = 20, token_budget: int = 6000) -> List[Dict]:
        # Focus threads use mRAG's semantic foreground over the shared corpus.
        # Raw 8D attention and transition learning remain owned by the serial
        # main pulse: a parallel focus must not move, reinforce, or race the
        # conscious attention trajectory merely because it performed a lookup.
        spatial = []
        with self._lock:
            return self.retrieval.retrieve(
                trigger_text=query,
                spatial_candidates=spatial,
                complement_quota=2,
                max_items=max_items,
                token_budget=token_budget,
            )

    def render(self, query: str, *, max_items: int = 20, token_budget: int = 6000) -> str:
        items = self.retrieve(query, max_items=max_items, token_budget=token_budget)
        if not items:
            return "(No matching stored context surfaced.)"
        lines = []
        spent = 0
        for item in items:
            content = " ".join(str(item.get("content", "")).split())
            cost = estimate_tokens(content)
            if not content or spent + cost > token_budget:
                continue
            lane = item.get("lane", "semantic")
            lines.append(f"- [{lane}; {item.get('id', '')}] {content}")
            spent += cost
        return "\n".join(lines) if lines else "(No matching stored context surfaced.)"
