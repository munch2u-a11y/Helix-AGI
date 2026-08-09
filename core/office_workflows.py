"""Small contracts and shared-budget arbitration for Context Office desks.

The office is intentionally deterministic by default.  A desk receives only
its task, the present query, and a bounded candidate slice.  It returns bids;
it does not own a permanent section of the final prompt.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Set


@dataclass(frozen=True)
class DeskContract:
    name: str
    instruction: str
    max_candidates: int

    def request(self, query: str, candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        """Return the complete, deliberately small worker request."""
        return {
            "desk": self.name,
            "task": self.instruction,
            "query": str(query or "").strip(),
            "candidates": [
                {
                    "id": item.get("id"),
                    "content": item.get("content", ""),
                    "confidence": item.get("confidence"),
                    "stability": item.get("stability_index"),
                    "affect": item.get("affective_salience"),
                }
                for item in candidates[:self.max_candidates]
            ],
        }


DESK_CONTRACTS: Dict[str, DeskContract] = {
    "facts": DeskContract(
        "facts", "Bid only exact answer-bearing records. Preserve source IDs.", 8,
    ),
    "state": DeskContract(
        "state", "Bid the current state and only history needed to disambiguate it.", 10,
    ),
    "relations": DeskContract(
        "relations", "Bid the smallest complete source chain or calculation set.", 12,
    ),
    "catalog": DeskContract(
        "catalog", "Bid complete set members and necessary counterevidence.", 12,
    ),
    "beliefs": DeskContract(
        "beliefs", "Bid relevant preferences, opinions, traits, or learned behaviors with confidence and sources.", 8,
    ),
    "causality": DeskContract(
        "causality", "Bid stated causes only. Do not infer a reason from an event.", 8,
    ),
    "affect": DeskContract(
        "affect", "Bid affect only when it can materially change this response.", 4,
    ),
    "identity": DeskContract(
        "identity", "Bid identity context only when this turn depends on identity, values, history, or characteristic behavior.", 6,
    ),
    "case": DeskContract(
        "case", "Bid exact or source-linked records from the explicitly named entity case.", 10,
    ),
    "semantic_advisor": DeskContract(
        "semantic_advisor", "Bid answer-relevant recall. Mark unsupported candidates unverified.", 12,
    ),
}


def worker_request(
    desk: str,
    query: str,
    candidates: Sequence[Dict[str, Any]],
) -> Dict[str, Any]:
    """Build an optional worker call without examples or repeated identity."""
    contract = DESK_CONTRACTS.get(desk, DESK_CONTRACTS["semantic_advisor"])
    return contract.request(query, candidates)


class OfficeArbiter:
    """Rank desk bids into one shared context budget.

    Verified multi-record proof members are one atomic bid: retaining half of
    a join or calculation would save tokens while making the answer worse.
    All other memories, beliefs, preferences, traits, and affect candidates
    compete item-by-item.
    """

    def allocate(
        self,
        items: Sequence[Dict[str, Any]],
        *,
        active_desks: Iterable[str],
        max_items: int,
        proof_ids: Iterable[str] = (),
    ) -> List[Dict[str, Any]]:
        limit = max(0, int(max_items))
        if not limit:
            return []
        active = set(active_desks)
        protected = {str(item_id) for item_id in proof_ids if item_id}
        prepared: List[Dict[str, Any]] = []
        desk_candidates: Dict[str, int] = {}
        for rank, source in enumerate(items):
            item = dict(source)
            desk = str(item.get("office_desk") or "semantic_advisor")
            contract = DESK_CONTRACTS.get(desk, DESK_CONTRACTS["semantic_advisor"])
            desk_candidates[desk] = desk_candidates.get(desk, 0) + 1
            if (
                desk_candidates[desk] > contract.max_candidates
                and str(item.get("id", "")) not in protected
            ):
                continue
            score, cost, reason = self._bid(item, rank, active)
            item["office_bid_score"] = round(score, 6)
            item["office_bid_cost"] = round(cost, 3)
            item["office_bid_reason"] = reason
            item["office_bid_atomic"] = str(item.get("id", "")) in protected
            prepared.append(item)

        # Proof members compete as one bundle. Their internal chronology is
        # preserved, while the remaining slots are shared by all other desks.
        proof = [item for item in prepared if str(item.get("id", "")) in protected]
        others = [item for item in prepared if str(item.get("id", "")) not in protected]
        chosen = proof[:limit]
        slots = limit - len(chosen)
        desk_counts: Dict[str, int] = {}
        while slots > 0 and others:
            best_index = max(
                range(len(others)),
                key=lambda index: (
                    others[index]["office_bid_score"]
                    - (0.035 * desk_counts.get(str(others[index].get("office_desk", "")), 0))
                ) / others[index]["office_bid_cost"],
            )
            winner = others.pop(best_index)
            chosen.append(winner)
            desk = str(winner.get("office_desk", ""))
            desk_counts[desk] = desk_counts.get(desk, 0) + 1
            slots -= 1
        return chosen

    @staticmethod
    def _unit(value: Any, default: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return default
        if not math.isfinite(number):
            return default
        if number > 1.0:
            number = number / (number + 4.0)
        return max(0.0, min(1.0, number))

    def _bid(
        self,
        item: Dict[str, Any],
        rank: int,
        active_desks: Set[str],
    ) -> tuple[float, float, str]:
        desk = str(item.get("office_desk") or "semantic_advisor")
        verified = bool(item.get("office_verified"))
        lexical = self._unit(item.get("office_score"), 0.0)
        retrieval = self._unit(item.get("relevance"), 1.0 / (rank + 2.0))
        relevance = max(lexical, retrieval, 1.0 / (rank + 2.0))
        task_fit = 1.0 if desk in active_desks else (
            0.72 if desk in {"beliefs", "affect", "identity", "case"} else 0.56
        )
        confidence = 0.99 if verified else self._unit(item.get("confidence"), 0.58)
        stability = self._unit(item.get("stability_index"), 0.50)
        affect = self._unit(item.get("affective_salience"), 0.0)
        importance = self._unit(item.get("importance", item.get("mass")), 0.45)
        score = (
            0.34 * relevance
            + 0.27 * task_fit
            + 0.18 * confidence
            + 0.08 * stability
            + 0.07 * importance
            + 0.06 * affect
        )
        words = len(str(item.get("content", "")).split())
        cost = max(1.0, words / 36.0)
        reasons = ["task-fit" if task_fit >= 0.9 else "supporting"]
        if verified:
            reasons.append("verified")
        if affect >= 0.60:
            reasons.append("affectively-salient")
        if stability >= 0.70:
            reasons.append("stable")
        return score, cost, ", ".join(reasons)
