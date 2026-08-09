"""Deterministic front desk for memory retrieval work orders.

The intake desk does not retrieve or answer.  It reduces the current message
to the small set of constraints every downstream retrieval desk needs: the
actual query (without transport wrappers), named subjects, requested facet,
and whether exact, chronological, relational, or profile evidence is useful.
This is the memory equivalent of Helix's tool-call orchestration layer.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Tuple


_OPERATOR_PREFIX_RE = re.compile(r"^\s*operator\s+question\s*:\s*", re.IGNORECASE)
_ENVELOPE_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")
_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "by", "did",
    "do", "does", "for", "from", "had", "has", "have", "how", "i",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "their",
    "them", "this", "to", "was", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your",
    "operator", "question", "tell", "mentioned", "according",
}


def clean_memory_query(message: Any) -> str:
    """Remove pulse/transport framing while preserving the user's wording."""
    value = _ENVELOPE_RE.sub("", str(message or "").strip())
    value = _OPERATOR_PREFIX_RE.sub("", value)
    return " ".join(value.split()).strip()


def _terms(text: str) -> Tuple[str, ...]:
    return tuple(dict.fromkeys(
        token.lower().strip("._-")
        for token in _TOKEN_RE.findall(text)
        if len(token.strip("._-")) > 1
        and token.lower().strip("._-") not in _STOPWORDS
    ))


@dataclass(frozen=True)
class MemoryWorkOrder:
    raw_message: str
    search_query: str
    subjects: Tuple[str, ...]
    possessive_subjects: Tuple[str, ...]
    question_type: str
    requested_facets: Tuple[str, ...]
    relation_terms: Tuple[str, ...]
    search_terms: Tuple[str, ...]
    is_question: bool
    requires_exact: bool
    requires_chronology: bool
    relation_requested: bool
    profile_allowed: bool
    role_constraint: str

    def to_dict(self):
        return asdict(self)


class MemoryIntakeOffice:
    """Compile one incoming message into a provider-free memory work order."""

    _FACETS = (
        ("preference", r"\bfavou?rite\b|\bprefer(?:s|red|ence)?\b|\blikes?\b|\benjoys?\b"),
        ("opinion", r"\bopinion\b|\bstance\b|\bbelie(?:f|ve|ves)\b|\bthinks?\b"),
        ("communication_style", r"\b(?:speaking|communication|conversation) style\b|\bphrase\b|\btone\b|\bdialect\b|\bmannerism\b"),
        ("trait", r"\btraits?\b|\bpersonality\b|\bhabit(?:s|ual)?\b|\busually\b|\bnormally\b|\btend(?:s)? to\b"),
        ("affect", r"\bfeel(?:s|ing)?\b|\bemotion\b|\bmood\b|\bafraid\b|\bangry\b|\bsad\b|\bhappy\b|\bguilt(?:y)?\b|\blove\b|\btrust\b|\bworried\b"),
        ("identity", r"\bidentity\b|\bvalues?\b|\bprinciples?\b|\bwho (?:are|is)\b"),
        ("location", r"\bwhere\b|\blocation\b|\bplace\b"),
        ("time", r"\bwhen\b|\bdate\b|\btime\b|\byear\b|\bmonth\b|\bday\b"),
        ("cause", r"\bwhy\b|\breason\b|\bcause(?:d)?\b|\bbecause\b"),
        ("quantity", r"\bhow many\b|\bnumber of\b|\btotal\b"),
    )
    _RELATION_RE = re.compile(
        r"\b(?:relationship|related|between|together|each other|friend|parent|"
        r"mother|father|sister|brother|partner|team|owner|lead|manage|works? with)\b",
        re.IGNORECASE,
    )

    def review(
        self,
        message: Any,
        *,
        known_entities: Iterable[str] = (),
    ) -> MemoryWorkOrder:
        raw = str(message or "")
        query = clean_memory_query(raw)
        lowered = query.lower()
        known = sorted(
            {" ".join(str(name).split()) for name in known_entities if str(name).strip()},
            key=lambda value: (-len(value), value.lower()),
        )
        subjects = tuple(
            name for name in known
            if re.search(r"\b" + re.escape(name.lower()) + r"\b", lowered)
        )
        possessive = tuple(
            name for name in subjects
            if re.search(r"\b" + re.escape(name.lower()) + r"(?:'s|')\b", lowered)
        )
        facets = tuple(
            facet for facet, pattern in self._FACETS
            if re.search(pattern, lowered, re.IGNORECASE)
        )
        is_question = bool("?" in query or re.match(
            r"^(?:what|when|where|which|who|whose|why|how|did|does|do|is|are|was|were|can|could|would)\b",
            lowered,
        ))
        if "cause" in facets:
            question_type = "causal"
        elif "time" in facets:
            question_type = "temporal"
        elif "location" in facets:
            question_type = "location"
        elif "quantity" in facets:
            question_type = "quantity"
        elif re.search(r"\bwho\b|\bwhose\b", lowered):
            question_type = "entity"
        elif facets:
            question_type = facets[0]
        else:
            question_type = "fact" if is_question else "statement"

        relation_terms = tuple(dict.fromkeys(
            match.group(0).lower()
            for match in self._RELATION_RE.finditer(query)
        ))
        relation_requested = bool(relation_terms or len(subjects) > 1)
        profile_allowed = bool(set(facets) & {
            "preference", "opinion", "communication_style", "trait", "affect", "identity",
        })
        requires_exact = bool(is_question and question_type in {
            "fact", "temporal", "location", "quantity", "entity", "preference",
        })
        requires_chronology = bool(
            question_type == "temporal"
            or re.search(r"\b(?:before|after|first|last|latest|current|then|next|previously)\b", lowered)
        )
        role_constraint = (
            "relational" if relation_requested
            else "subject_facts" if subjects and is_question
            else "unconstrained"
        )
        return MemoryWorkOrder(
            raw_message=raw,
            search_query=query,
            subjects=subjects,
            possessive_subjects=possessive,
            question_type=question_type,
            requested_facets=facets,
            relation_terms=relation_terms,
            search_terms=_terms(query),
            is_question=is_question,
            requires_exact=requires_exact,
            requires_chronology=requires_chronology,
            relation_requested=relation_requested,
            profile_allowed=profile_allowed,
            role_constraint=role_constraint,
        )
