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
    target_record_kinds: Tuple[str, ...]
    evidence_scope: str
    thought_policy: str
    related_record_kinds: Tuple[str, ...]

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

    @staticmethod
    def _record_policy(
        query: str,
        *,
        is_question: bool,
        requires_exact: bool,
        subjects: Tuple[str, ...],
    ) -> Tuple[Tuple[str, ...], str, str, Tuple[str, ...]]:
        """Route evidence roles without asking a model to classify memory."""
        lowered = query.lower()
        cognition = bool(re.search(
            r"\b(?:what|why|how) (?:was|were|did|do|does) (?:i|you|helix)\b.*"
            r"\b(?:think|thinking|feel|feeling|decide|decided|consider|intend|"
            r"intended|plan|planned|want|wanted|reason|because)\b|"
            r"\bwhy did (?:i|you|helix)\b|\bwhat (?:was|were) (?:i|you) thinking\b",
            lowered,
        ))
        outbound = bool(re.search(
            r"\b(?:what|when|where|why|how|did) (?:did )?(?:i|you|helix)\b.*"
            r"\b(?:say|tell|told|message|messaged|send|sent|reply|replied|write|wrote)\b|"
            r"\b(?:what|which) (?:message|reply|email|note) did (?:i|you|helix)\b",
            lowered,
        ))
        communication_verb = bool(re.search(
            r"\b(?:say|said|tell|told|message|messaged|send|sent|write|wrote|reply|replied)\b",
            lowered,
        ))
        inbound = bool(subjects and communication_verb and not outbound)
        tool_report = bool(re.search(
            r"\b(?:tool|sensor|terminal|command|search|api|camera|diagnostic)\b.*"
            r"\b(?:report|reported|return|returned|result|output|show|showed|read|failure|failed|error)\b|"
            r"\b(?:what|which) did (?:the )?(?:tool|sensor|terminal|command|search|api|camera)\b",
            lowered,
        ))
        task_outcome = bool(re.search(
            r"\b(?:task|job|work)\b.*\b(?:complete|completed|finish|finished|outcome|result|failed)\b",
            lowered,
        ))

        if cognition:
            return (
                ("thought",),
                "agent_cognition",
                "primary",
                ("inbound_message", "outbound_message", "tool_observation", "task_outcome"),
            )
        if outbound:
            return (
                ("outbound_message",),
                "delivered_communication",
                "exclude",
                ("inbound_message", "tool_result"),
            )
        if inbound:
            return (
                ("inbound_message",),
                "received_communication",
                "exclude",
                ("outbound_message",),
            )
        if tool_report:
            return (
                ("tool_result", "tool_observation"),
                "tool_report",
                "exclude",
                ("task_outcome",),
            )
        if task_outcome:
            return (
                ("task_outcome", "task_result"),
                "task_outcome",
                "exclude",
                ("tool_result", "tool_observation"),
            )
        return (
            (),
            (
                "exact_factual_evidence" if requires_exact
                else "factual_evidence" if is_question
                else "recognition"
            ),
            "exclude" if is_question else "bounded",
            (),
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
        # Comparative phrasing ("sound less like himself", "looks like X")
        # is not a preference request merely because it contains ``like``.
        if (
            "preference" in facets
            and not re.search(
                r"\bfavou?rite\b|\bprefer(?:s|red|ence)?\b|\benjoys?\b",
                lowered,
            )
            and re.search(r"\b(?:sound|look|feel|seem|more|less)\w*\s+like\b", lowered)
        ):
            facets = tuple(facet for facet in facets if facet != "preference")
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
            or re.search(
                r"\b(?:before|after|last|latest|current|then|next|previously)\b|"
                r"(?<![-\w])first(?![-\w])",
                lowered,
            )
        )
        role_constraint = (
            "relational" if relation_requested
            else "subject_facts" if subjects and is_question
            else "unconstrained"
        )
        (
            target_record_kinds,
            evidence_scope,
            thought_policy,
            related_record_kinds,
        ) = self._record_policy(
            query,
            is_question=is_question,
            requires_exact=requires_exact,
            subjects=subjects,
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
            target_record_kinds=target_record_kinds,
            evidence_scope=evidence_scope,
            thought_policy=thought_policy,
            related_record_kinds=related_record_kinds,
        )
