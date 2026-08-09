"""Helix context office: deterministic specialist views over canonical memory.

This is the RAGOffice-centered experiment.  It adopts the useful office
metaphor without copying memories into markdown libraries or separate belief
databases.  Every desk is a read-only projection over ``HelixCorpus``:

* Facts binds direct evidence.
* State orders mutable facts and preserves superseded history.
* Relations closes joins, aggregations, and enumerations inside one episode.
* Beliefs connects paraphrased stance questions to stored policy/preferences.
* Causality refuses to substitute event status for a missing reason.

The semantic lane advises the desks and remains the fallback.  The 8D spatial
and learned-transition lanes stay outside the office proof brief so Helix can
retain lateral associations without allowing them to masquerade as evidence.
"""

from __future__ import annotations

import math
import os
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
_ENVELOPE_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")
_SPEAKER_RE = re.compile(r"^[A-Za-z][\w .'-]{0,39}:\s*")

_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "being", "by",
    "can", "could", "did", "do", "does", "for", "from", "had", "has",
    "have", "how", "i", "in", "is", "it", "its", "of", "on", "or",
    "our", "should", "that", "the", "their", "them", "there", "these",
    "this", "those", "to", "was", "we", "were", "what", "when", "where",
    "which", "who", "why", "will", "with", "would", "you", "your",
    "agent", "answer", "current", "currently", "latest", "official",
    "value", "session", "after", "total", "now", "operator", "question",
    "many", "technology", "use", "used", "using", "stance",
}

_IRREGULAR_STEMS = {
    "led": "lead", "leads": "lead", "owned": "own", "owns": "own",
    "preferred": "prefer", "prefers": "prefer", "preferences": "preference",
    "rejected": "reject", "cancelled": "cancel", "canceled": "cancel",
    "dependencies": "dependency",
}


def is_enabled() -> bool:
    return os.environ.get("HELIX_CONTEXT_OFFICE", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


def _stem(token: str) -> str:
    token = token.lower().strip("._-")
    if not token:
        return ""
    if token in _IRREGULAR_STEMS:
        return _IRREGULAR_STEMS[token]
    if token.isdigit() or len(token) <= 3:
        return token
    if token.endswith("ies") and len(token) > 4:
        return token[:-3] + "y"
    if token.endswith("ing") and len(token) > 5:
        root = token[:-3]
        if len(root) > 2 and root[-1] == root[-2]:
            root = root[:-1]
        return root
    if token.endswith("ed") and len(token) > 4:
        return token[:-2]
    if token.endswith("es") and len(token) > 4:
        return token[:-2]
    if token.endswith("s") and not token.endswith("ss") and len(token) > 3:
        return token[:-1]
    return token


def _payload(text: Any) -> str:
    value = str(text or "").strip()
    value = _ENVELOPE_RE.sub("", value)
    value = _SPEAKER_RE.sub("", value)
    return " ".join(value.split()).strip()


def _terms(text: Any, *, drop_stopwords: bool = False) -> List[str]:
    result: List[str] = []
    for raw in _TOKEN_RE.findall(str(text or "")):
        lowered = raw.lower().strip("._-")
        if len(lowered) < 2 and not lowered.isdigit():
            continue
        if drop_stopwords and lowered in _STOPWORDS:
            continue
        term = _stem(raw)
        if not term or (drop_stopwords and term in _STOPWORDS):
            continue
        result.append(term)
    return result


@dataclass(frozen=True)
class OfficePlan:
    intents: Tuple[str, ...]
    desks: Tuple[str, ...]
    terms: Tuple[str, ...]
    subject: str
    structured: bool
    expand_scope: bool
    prefer_latest: bool

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class OfficeResult:
    items: List[Dict[str, Any]]
    diagnostics: Dict[str, Any]


def _belief_subject(query: str) -> str:
    match = re.search(
        r"\b(?:stance|opinion|belief|preference)\s+"
        r"(?:on|about|toward|towards|for)\s+(.+?)(?:\?|$)",
        _payload(query),
        re.IGNORECASE,
    )
    return "" if not match else " ".join(match.group(1).split()).strip(" .?!")


def plan_office(query: str) -> OfficePlan:
    lowered = " ".join(str(query or "").lower().split())
    intents: List[str] = []
    desks: List[str] = []

    if re.search(r"\bhow many\b|\bin total\b|\btotal after\b", lowered):
        intents.append("aggregation")
        desks.append("relations")
    if re.search(r"\bwho\b.*\b(?:team|person|agent|owner)\b.*\b(?:own|lead|manage)", lowered):
        intents.append("relation_path")
        desks.append("relations")
    if re.search(r"\bwhich\b|\blist\b|\bwhat are\b|\ball (?:the )?", lowered):
        intents.append("enumeration")
        desks.append("catalog")
    if re.search(
        r"\bcurrent(?:ly)?\b|\blatest\b|\bnow\b|\bno longer\b|"
        r"\bcurrent status\b|\bcurrent value\b|\bcurrently want\b|\bofficial deadline\b",
        lowered,
    ):
        intents.append("current_state")
        desks.append("state")
    if re.search(r"\bstance\b|\bopinion\b|\bbelie(?:f|ve)\b|\bprefer(?:s|ence)?\b", lowered):
        intents.append("belief_state")
        desks.append("beliefs")
    if re.search(r"\bwhy\b|\bwhat (?:was|is) the reason\b|\bwhat caused\b", lowered):
        intents.append("causal_explanation")
        desks.append("causality")
    if not intents:
        intents.append("direct_fact")
        desks.append("facts")

    terms = tuple(dict.fromkeys(_terms(query, drop_stopwords=True)))
    structured = any(intent != "direct_fact" for intent in intents)
    expand_scope = any(intent in {
        "aggregation", "relation_path", "enumeration", "current_state",
        "causal_explanation",
    } for intent in intents)
    prefer_latest = "current_state" in intents and not any(
        intent in intents for intent in ("aggregation", "relation_path", "enumeration")
    )
    return OfficePlan(
        intents=tuple(dict.fromkeys(intents)),
        desks=tuple(dict.fromkeys(desks)),
        terms=terms,
        subject=_belief_subject(query),
        structured=structured,
        expand_scope=expand_scope,
        prefer_latest=prefer_latest,
    )


def _belief_implication(subject: str, content: Any) -> str:
    if not subject:
        return ""
    value = _payload(content).lower()
    subject_terms = set(_terms(subject, drop_stopwords=True))
    content_terms = set(_terms(value))
    explicit_negative = re.search(
        r"\b(?:avoid|avoids|reject|rejects|dislike|dislikes|oppose|opposes|"
        r"against|not suitable|no longer|never use|does not want)\b",
        value,
    )
    contrastive = re.search(
        r"\b(?:prefer|prefers|favor|favors)\b.*(?:\binstead of\b|\bover\b|\bnon-)",
        value,
    )
    protected_opposite = (
        any(term.startswith("un") and len(term) > 4 for term in subject_terms)
        and re.search(r"\b(?:require|requires|enforce|enforces|insist|insists)\b", value)
    )
    if explicit_negative or contrastive or protected_opposite:
        return f'negative stance toward "{subject}"'
    if subject_terms & content_terms and re.search(
        r"\b(?:prefer|prefers|favor|favors|approve|approves|embrace|embraces|require|requires)\b",
        value,
    ):
        return f'positive stance toward "{subject}"'
    return ""


class ContextOffice:
    """Coordinate deterministic desk projections into one evidence brief."""

    MIN_SCOPE_COVERAGE = 0.60
    MAX_SCOPE_ITEMS = 12

    def __init__(self, corpus):
        self.corpus = corpus
        self._version: Optional[int] = None
        self._items: List[Dict[str, Any]] = []
        self._by_id: Dict[str, Dict[str, Any]] = {}
        self._payloads: Dict[str, str] = {}
        self._counts: Dict[str, Counter] = {}
        self._docs: Dict[str, Set[str]] = defaultdict(set)
        self._scopes: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self._ordinal: Dict[str, int] = {}

    def sync(self) -> None:
        items = self.corpus.all_items()
        version = getattr(self.corpus, "version", None)
        if version is not None and version == self._version:
            return
        self._items = list(items)
        self._by_id = {str(item.get("id")): item for item in items if item.get("id")}
        self._payloads = {}
        self._counts = {}
        self._docs = defaultdict(set)
        self._scopes = defaultdict(list)
        self._ordinal = {}

        for ordinal, item in enumerate(items):
            item_id = str(item.get("id", ""))
            if not item_id:
                continue
            payload = _payload(item.get("content", ""))
            counts = Counter(_terms(payload))
            self._payloads[item_id] = payload
            self._counts[item_id] = counts
            self._ordinal[item_id] = ordinal
            for term in counts:
                self._docs[term].add(item_id)
            if item.get("tier") == 0:
                scope = str(item.get("scope_id") or item.get("session_id") or item_id)
                self._scopes[scope].append(item)
        for records in self._scopes.values():
            records.sort(key=self._chronology_key)
        self._version = version

    def prepare(
        self,
        query: str,
        semantic_items: Sequence[Dict[str, Any]],
        *,
        max_items: int,
    ) -> OfficeResult:
        self.sync()
        plan = plan_office(query)
        semantic = [dict(item) for item in semantic_items]
        if not plan.terms:
            return OfficeResult(
                items=semantic,
                diagnostics=self._diagnostics(plan, False, "no_query_terms"),
            )

        direct_scores = self._score_items(plan.terms)
        score_map = dict(direct_scores)
        scope: Optional[str] = None
        coverage = 0.0
        scope_score = 0.0
        evidence: List[Dict[str, Any]] = []
        binding = "none"

        if plan.structured:
            scope, coverage, scope_score = self._best_scope(plan.terms, direct_scores)
            if scope is not None and coverage >= self.MIN_SCOPE_COVERAGE:
                causal_ok = (
                    "causal_explanation" not in plan.intents or self._scope_has_cause(scope)
                )
                if causal_ok:
                    evidence = self._episode_brief(scope, plan, score_map)
                    binding = "lexical_episode"
        else:
            for item_id, score in direct_scores[:3]:
                matched, item_coverage = self._coverage(plan.terms, {item_id})
                if matched and item_coverage >= 0.999:
                    item = dict(self._by_id[item_id])
                    self._mark(item, "direct_fact", "facts", None, score, plan, True)
                    evidence.append(item)
                    binding = "lexical_fact"
                    if item.get("tier") == 0:
                        scope = str(item.get("scope_id") or item.get("session_id") or item_id)
                        coverage = item_coverage
                        scope_score = score

        # The Beliefs desk may accept mRAG's strongest paraphrase as its one
        # subject binding. It then returns that complete canonical episode,
        # rather than turning semantic neighbors into multiple opinions.
        if (
            not evidence and "belief_state" in plan.intents and semantic
            and semantic[0].get("tier") == 0
        ):
            anchor = semantic[0]
            candidate_scope = str(anchor.get("scope_id") or anchor.get("session_id") or "")
            if candidate_scope and candidate_scope in self._scopes:
                scope = candidate_scope
                for original in self._scopes[candidate_scope][:self.MAX_SCOPE_ITEMS]:
                    item = dict(original)
                    self._mark(
                        item, "belief_source", "beliefs", candidate_scope,
                        0.0, plan, True,
                    )
                    evidence.append(item)
                binding = "semantic_belief_episode"

        # The Causality desk treats an unexplained event as an absent relation,
        # not as weak evidence for a reason.
        if "causal_explanation" in plan.intents and not evidence:
            semantic = []

        if plan.subject:
            for item in evidence:
                item["office_subject"] = plan.subject
                implication = _belief_implication(plan.subject, item.get("content", ""))
                if implication:
                    item["office_implication"] = implication

        verified = bool(evidence)
        selected: List[Dict[str, Any]] = []
        selected_ids: Set[str] = set()
        for item in evidence:
            item_id = str(item.get("id", ""))
            if item_id and item_id not in selected_ids:
                selected.append(item)
                selected_ids.add(item_id)

        if verified and scope is not None:
            for item in semantic:
                item_id = str(item.get("id", ""))
                if not item_id or item_id in selected_ids:
                    continue
                same_scope = str(item.get("scope_id") or item.get("session_id") or "") == scope
                matched, item_coverage = self._coverage(plan.terms, {item_id})
                supporting_belief = (
                    item.get("tier") in (1, 2) and matched and item_coverage >= 0.60
                )
                if not (same_scope or supporting_belief):
                    continue
                desk = "beliefs" if supporting_belief else "episode"
                role = "supporting_belief" if supporting_belief else "episode_support"
                self._mark(item, role, desk, scope, score_map.get(item_id, 0.0), plan, True)
                selected.append(item)
                selected_ids.add(item_id)
        else:
            for item in semantic:
                item_id = str(item.get("id", ""))
                if not item_id or item_id in selected_ids:
                    continue
                role = "unverified_semantic" if plan.structured else "semantic_recall"
                self._mark(item, role, "semantic_advisor", None, 0.0, plan, False)
                selected.append(item)
                selected_ids.add(item_id)

        selected = selected[:max_items]
        return OfficeResult(
            items=selected,
            diagnostics=self._diagnostics(
                plan, verified, "brief_bound" if verified else "no_verified_brief",
                binding=binding, scope=scope, coverage=coverage, score=scope_score,
                evidence_selected=len(evidence),
                semantic_retained=max(0, len(selected) - len(evidence)),
            ),
        )

    def _episode_brief(
        self,
        scope: str,
        plan: OfficePlan,
        scores: Dict[str, float],
    ) -> List[Dict[str, Any]]:
        source = list(self._scopes.get(scope, []))[:self.MAX_SCOPE_ITEMS]
        ordered = list(reversed(source)) if plan.prefer_latest else source
        result: List[Dict[str, Any]] = []
        for index, original in enumerate(ordered):
            item = dict(original)
            if plan.prefer_latest:
                role, desk = ("current_state", "state") if index == 0 else ("state_history", "state")
            elif "aggregation" in plan.intents:
                role, desk = "calculation_member", "relations"
            elif "relation_path" in plan.intents:
                role, desk = "relation_member", "relations"
            elif "enumeration" in plan.intents:
                role, desk = "catalog_member", "catalog"
            elif "belief_state" in plan.intents:
                role, desk = "belief_source", "beliefs"
            elif "causal_explanation" in plan.intents:
                role, desk = "causal_member", "causality"
            else:
                role, desk = "episode_support", "episode"
            self._mark(
                item, role, desk, scope,
                scores.get(str(item.get("id")), 0.0), plan, True,
            )
            result.append(item)
        return result

    def _score_items(self, query_terms: Sequence[str]) -> List[Tuple[str, float]]:
        total_docs = max(1, len(self._counts))
        weights = {
            term: 1.0 + math.log((1.0 + total_docs) / (1.0 + len(self._docs.get(term, ()))))
            for term in query_terms
        }
        total_weight = sum(weights.values()) or 1.0
        candidates: Set[str] = set()
        for term in query_terms:
            candidates |= self._docs.get(term, set())
        scored: List[Tuple[str, float]] = []
        for item_id in candidates:
            counts = self._counts.get(item_id, Counter())
            matched = [term for term in query_terms if counts.get(term, 0)]
            if not matched:
                continue
            coverage = sum(weights[term] for term in matched) / total_weight
            frequency = sum(min(2, max(0, counts[term] - 1)) for term in matched) * 0.12
            score = (5.0 * coverage) + frequency
            scored.append((item_id, score))
        scored.sort(key=lambda pair: (-pair[1], self._ordinal.get(pair[0], 10**9)))
        return scored

    def _best_scope(
        self,
        query_terms: Sequence[str],
        scores: Sequence[Tuple[str, float]],
    ) -> Tuple[Optional[str], float, float]:
        grouped: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        for item_id, score in scores:
            item = self._by_id.get(item_id, {})
            if item.get("tier") != 0:
                continue
            scope = str(item.get("scope_id") or item.get("session_id") or item_id)
            grouped[scope].append((item_id, score))
        ranked: List[Tuple[str, float, float]] = []
        for scope, matches in grouped.items():
            item_ids = {
                str(item.get("id")) for item in self._scopes.get(scope, []) if item.get("id")
            }
            _matched, coverage = self._coverage(query_terms, item_ids)
            best = max(score for _item_id, score in matches)
            bonus = 0.18 * sum(score for _item_id, score in matches[1:])
            ranked.append((scope, coverage, best + (2.0 * coverage) + bonus))
        if not ranked:
            return None, 0.0, 0.0
        ranked.sort(key=lambda row: (-row[2], -row[1], row[0]))
        return ranked[0]

    def _coverage(
        self,
        query_terms: Sequence[str],
        item_ids: Iterable[str],
    ) -> Tuple[Set[str], float]:
        present: Set[str] = set()
        for item_id in item_ids:
            present |= set(self._counts.get(str(item_id), {}))
        matched = {term for term in query_terms if term in present}
        return matched, (len(matched) / len(query_terms)) if query_terms else 0.0

    def _scope_has_cause(self, scope: str) -> bool:
        causal = re.compile(
            r"\b(?:because|reason|caused by|due to|owing to|as a result of|so that)\b",
            re.IGNORECASE,
        )
        return any(
            causal.search(self._payloads.get(str(item.get("id", "")), ""))
            for item in self._scopes.get(scope, [])
        )

    def _chronology_key(self, item: Dict[str, Any]) -> Tuple[int, str, int]:
        try:
            turn = int(item.get("turn_id"))
        except (TypeError, ValueError):
            turn = self._ordinal.get(str(item.get("id", "")), 0)
        return turn, str(item.get("created_at", "")), self._ordinal.get(str(item.get("id", "")), 0)

    @staticmethod
    def _mark(
        item: Dict[str, Any],
        role: str,
        desk: str,
        scope: Optional[str],
        score: float,
        plan: OfficePlan,
        verified: bool,
    ) -> None:
        item["office_role"] = role
        item["office_desk"] = desk
        item["office_scope"] = scope
        item["office_score"] = round(float(score), 6)
        item["office_intents"] = list(plan.intents)
        item["office_verified"] = bool(verified)

    @staticmethod
    def _diagnostics(
        plan: OfficePlan,
        verified: bool,
        reason: str,
        *,
        binding: str = "none",
        scope: Optional[str] = None,
        coverage: float = 0.0,
        score: float = 0.0,
        evidence_selected: int = 0,
        semantic_retained: int = 0,
    ) -> Dict[str, Any]:
        return {
            "enabled": True,
            "plan": plan.to_dict(),
            "desks": list(plan.desks),
            "verified": bool(verified),
            "reason": reason,
            "binding_method": binding,
            "scope": scope,
            "scope_coverage": round(float(coverage), 6),
            "scope_score": round(float(score), 6),
            "evidence_selected": int(evidence_selected),
            "semantic_retained": int(semantic_retained),
        }
