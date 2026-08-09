"""A bounded Affect desk for Context Office prompt construction."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Sequence, Set


_AFFECT_QUERY = re.compile(
    r"\b(?:feel|feeling|emotion|mood|afraid|fear|angry|anger|sad|sadness|"
    r"happy|joy|guilt|guilty|love|trust|worry|worried|upset|comfort|"
    r"apolog(?:y|ize)|relationship)\b",
    re.IGNORECASE,
)


class AffectOffice:
    """Turn numerical affect and resonant recall into optional context bids.

    This desk never calls a model and never invents a factual claim. It emits
    at most one current-state bid and two emotionally reactivated memories.
    """

    MAX_RESONANT = 2

    def propose(
        self,
        query: str,
        corpus_by_id: Mapping[str, Dict[str, Any]],
        existing: Sequence[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        try:
            from core.affect_hook import get_last_result
            result = get_last_result()
        except (ImportError, RuntimeError):
            result = None
        if result is None:
            return []

        explicit = bool(_AFFECT_QUERY.search(str(query or "")))
        notable = (
            result.dominant_affect != "neutral"
            and float(result.field_intensity) >= 0.45
        )
        diverse = float(result.cognitive_diversity_signal) >= 0.55
        existing_salience = max(
            (float(item.get("affective_salience") or 0.0) for item in existing),
            default=0.0,
        )
        if not (explicit or notable or diverse or existing_salience >= 0.68):
            return []

        proposals: List[Dict[str, Any]] = []
        if explicit or notable or diverse:
            parts = [f"current affect is {result.dominant_affect}"]
            if notable or explicit:
                parts.append(f"intensity {float(result.field_intensity):.2f}")
            if diverse:
                parts.append(
                    f"novelty pressure {float(result.cognitive_diversity_signal):.2f}"
                )
            proposals.append({
                "id": "office_affect_state",
                "content": "; ".join(parts) + ".",
                "tier": -1,
                "office_role": "affect_state",
                "office_desk": "affect",
                "office_verified": False,
                "relevance": 1.0 if explicit else 0.64,
                "confidence": 0.98,
                "stability_index": 0.55,
                "affective_salience": max(
                    float(result.field_intensity), existing_salience
                ),
            })

        present: Set[str] = {str(item.get("id", "")) for item in existing}
        for memory_id in result.surfaced_memories:
            memory_id = str(memory_id)
            if memory_id in present:
                continue
            source = corpus_by_id.get(memory_id)
            if source is None and memory_id.startswith("mem_"):
                source = corpus_by_id.get(memory_id[4:])
            if source is None:
                continue
            item = dict(source)
            item["office_role"] = "affective_resonance"
            item["office_desk"] = "affect"
            item["office_verified"] = False
            item["relevance"] = max(float(item.get("relevance") or 0.0), 0.62)
            item["affective_salience"] = max(
                float(item.get("affective_salience") or 0.0),
                float(result.reactivation_strength),
            )
            proposals.append(item)
            if len(proposals) >= self.MAX_RESONANT + 1:
                break
        return proposals
