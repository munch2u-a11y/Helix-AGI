"""Small contracts and shared-budget arbitration for Context Office desks.

The office is intentionally deterministic by default.  A desk receives only
its task, the present query, and a bounded candidate slice.  It returns bids;
it does not own a permanent section of the final prompt.
"""

from __future__ import annotations

import math
import re
from collections import Counter
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
        reserve_ids: Iterable[str] = (),
        max_profile_items: int = 2,
    ) -> List[Dict[str, Any]]:
        limit = max(0, int(max_items))
        if not limit:
            return []
        active = set(active_desks)
        protected = {str(item_id) for item_id in proof_ids if item_id}
        reserved_order = [str(item_id) for item_id in reserve_ids if item_id]
        reserved = set(reserved_order) - protected
        prepared: List[Dict[str, Any]] = []
        desk_candidates: Dict[str, int] = {}
        for rank, source in enumerate(items):
            item = dict(source)
            desk = str(item.get("office_desk") or "semantic_advisor")
            contract = DESK_CONTRACTS.get(desk, DESK_CONTRACTS["semantic_advisor"])
            desk_candidates[desk] = desk_candidates.get(desk, 0) + 1
            if (
                desk_candidates[desk] > contract.max_candidates
                and str(item.get("id", "")) not in protected | reserved
            ):
                continue
            score, cost, reason = self._bid(item, rank, active)
            item["office_bid_score"] = round(score, 6)
            item["office_bid_cost"] = round(cost, 3)
            item["office_bid_reason"] = reason
            item["office_bid_atomic"] = str(item.get("id", "")) in protected
            item["office_bid_reserved"] = str(item.get("id", "")) in reserved
            prepared.append(item)

        # Proof members compete as one bundle. Their internal chronology is
        # preserved, while the remaining slots are shared by all other desks.
        proof = [item for item in prepared if str(item.get("id", "")) in protected]
        prepared_by_id = {
            str(item.get("id", "")): item for item in prepared if item.get("id")
        }
        reserve = [
            prepared_by_id[item_id] for item_id in reserved_order
            if item_id in prepared_by_id and item_id not in protected
        ]
        others = [
            item for item in prepared
            if str(item.get("id", "")) not in protected | reserved
        ]
        chosen = proof[:limit]
        chosen.extend(reserve[:max(0, limit - len(chosen))])
        slots = limit - len(chosen)
        desk_counts: Dict[str, int] = {}
        profile_count = sum(
            1 for item in chosen if item.get("formation_type") == "session_profile"
        )
        while slots > 0 and others:
            eligible = [
                index for index, item in enumerate(others)
                if item.get("formation_type") != "session_profile"
                or profile_count < max(0, int(max_profile_items))
            ]
            if not eligible:
                break
            best_index = max(
                eligible,
                key=lambda index: (
                    others[index]["office_bid_score"]
                    - (0.035 * desk_counts.get(str(others[index].get("office_desk", "")), 0))
                ) / others[index]["office_bid_cost"],
            )
            candidate = others.pop(best_index)
            content = str(candidate.get("content") or candidate.get("statement") or candidate.get("text") or "")
            if self._is_internally_repetitive(content):
                candidate["office_bid_blocked"] = "repetitive"
                continue
            if self._is_redundant(candidate, chosen):
                candidate["office_bid_blocked"] = "redundant"
                continue

            chosen.append(candidate)
            desk = str(candidate.get("office_desk", ""))
            desk_counts[desk] = desk_counts.get(desk, 0) + 1
            if candidate.get("formation_type") == "session_profile":
                profile_count += 1
            slots -= 1
        return chosen

    @staticmethod
    def _is_internally_repetitive(text: str, max_repeats: int = 3) -> bool:
        """Detect runaway feedback loops within a single candidate's text."""
        if not text:
            return False
        patterns = [
            r"\*\([^\)]+\)\*",
            r"\([^\)]+\)",
            r"\[[^\]]+\]",
        ]
        for pattern in patterns:
            try:
                matches = re.findall(pattern, text)
                if len(matches) >= max_repeats:
                    counts = Counter(matches)
                    if any(count >= max_repeats for count in counts.values()):
                        return True
            except Exception:
                pass

        sentences = [s.strip().lower() for s in re.split(r"[.!?\n;]", text) if len(s.strip()) > 8]
        if len(sentences) >= max_repeats:
            counts = Counter(sentences)
            if any(count >= max_repeats for count in counts.values()):
                return True

        words = re.findall(r"\w+", text.lower())
        if len(words) >= 12:
            ngrams = [tuple(words[i : i + 4]) for i in range(len(words) - 3)]
            counts = Counter(ngrams)
            if any(count >= max_repeats for count in counts.values()):
                return True

        return False

    @staticmethod
    def _is_redundant(
        item: Dict[str, Any],
        chosen: Sequence[Dict[str, Any]],
        threshold: float = 0.70,
    ) -> bool:
        """Check if candidate item redundantly repeats an already chosen item."""
        content = str(item.get("content") or item.get("statement") or item.get("text") or "").strip()
        if not content:
            return False
        content_lower = content.lower()
        words = set(re.findall(r"\w+", content_lower))

        protected_roles = {
            "current_state", "state_history", "calculation_member",
            "relation_member", "catalog_member", "causal_member",
        }

        for prior in chosen:
            if (
                item.get("office_verified")
                and prior.get("office_verified")
                and item.get("office_scope")
                and item.get("office_scope") == prior.get("office_scope")
                and (
                    item.get("office_role") in protected_roles
                    or prior.get("office_role") in protected_roles
                )
            ):
                continue

            prior_content = str(prior.get("content") or prior.get("statement") or prior.get("text") or "").strip()
            if not prior_content:
                continue
            if content_lower == prior_content.lower():
                return True

            prior_words = set(re.findall(r"\w+", prior_content.lower()))
            if len(words) >= 4 and len(prior_words) >= 4:
                overlap = len(words & prior_words) / len(words | prior_words)
                if overlap >= threshold:
                    return True

        return False


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
