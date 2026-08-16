"""mRAG-primary retrieval over Helix's derived catalog and 384D vectors."""

from __future__ import annotations

import json
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

import numpy as np

from memory.mrag.catalog import read_jsonl
from memory.mrag.models import (
    FocusState,
    RetrievalCandidate,
    RetrievalResult,
    estimate_tokens,
)

TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_'-]*")
DATE_RE = re.compile(r"\b(?:19|20)\d{2}(?:-\d{1,2}(?:-\d{1,2})?)?\b")
STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "been", "but", "by",
    "did", "do", "does", "for", "from", "had", "has", "have", "how",
    "i", "in", "is", "it", "me", "my", "of", "on", "or", "that",
    "the", "their", "them", "there", "these", "they", "this", "to",
    "was", "were", "what", "when", "where", "which", "who", "why",
    "with", "would", "you", "your",
    "recorded", "record", "remember", "remembered", "know", "known", "tell",
}
EPISODIC_TERMS = {
    "exactly", "quote", "said", "say", "happened", "episode", "event",
    "before", "after", "during", "first", "last", "when", "timestamp",
    "source", "evidence", "provenance", "contradiction", "conflict",
}
RELATION_TERMS = {
    "because", "cause", "caused", "led", "related", "relationship",
    "connection", "between", "supports", "contradicts", "depends",
    "parent", "child", "friend", "partner", "creator", "colleague",
}
MULTIHOP_TERMS = {
    "both", "combine", "connection", "together", "relationship", "relate",
    "why", "across", "independently", "two",
}


def _tokens(text: str) -> List[str]:
    return [token.casefold() for token in TOKEN_RE.findall(text or "")]


def _normalize_content(text: str) -> str:
    return " ".join(_tokens(text))


class CatalogView:
    """In-memory read view over one immutable shadow run."""

    def __init__(self, run_dir: Path):
        self.run_dir = Path(run_dir)
        self.entries = list(read_jsonl(self.run_dir / "catalog.jsonl"))
        self.by_id = {entry["canonical_id"]: entry for entry in self.entries}
        self.hot = [entry for entry in self.entries if entry["retrieval_status"] == "hot"]
        self.cold = [entry for entry in self.entries if entry["retrieval_status"] == "cold"]
        self.hot_by_id = {entry["canonical_id"]: entry for entry in self.hot}
        self.cold_by_id = {entry["canonical_id"]: entry for entry in self.cold}
        self._token_sets = {
            entry["canonical_id"]: set(_tokens(entry.get("content", "")))
            for entry in self.entries
        }
        self._entity_index: Dict[str, Set[str]] = defaultdict(set)
        self._topic_index: Dict[str, Set[str]] = defaultdict(set)
        for entry in self.entries:
            for label in entry.get("entities", []) + entry.get("aliases", []):
                self._entity_index[label].add(entry["canonical_id"])
            for label in entry.get("topics", []):
                self._topic_index[label].add(entry["canonical_id"])
        self._idf = self._build_idf(self.hot)
        self.transitions = self._load_transitions()

    def _build_idf(self, entries: Sequence[Dict[str, Any]]) -> Dict[str, float]:
        document_frequency = Counter()
        for entry in entries:
            document_frequency.update(self._token_sets[entry["canonical_id"]])
        total = max(1, len(entries))
        return {
            token: math.log((total + 1) / (count + 1)) + 1.0
            for token, count in document_frequency.items()
        }

    def _load_transitions(self) -> Dict[str, Dict[str, float]]:
        path = self.run_dir / "transition_graph.json"
        if not path.exists():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data.get("transitions", {})

    def tokens(self, canonical_id: str) -> Set[str]:
        return self._token_sets.get(canonical_id, set())

    def matched_entities(self, query: str) -> List[str]:
        lowered = query.casefold()
        return sorted(
            label for label in self._entity_index
            if re.search(r"\b" + re.escape(label) + r"\b", lowered)
        )

    def matched_topics(self, query: str) -> List[str]:
        query_tokens = set(_tokens(query))
        return sorted(
            label for label in self._topic_index
            if set(label.split()) and set(label.split()).issubset(query_tokens)
        )


class ShadowVectorIndex:
    def __init__(self, path: Path):
        self.path = Path(path)
        ids_path = self.path / "ids.json"
        embeddings_path = self.path / "embeddings.npy"
        self.ids = json.loads(ids_path.read_text(encoding="utf-8")) if ids_path.exists() else []
        self.embeddings = (
            np.load(embeddings_path, mmap_mode="r")
            if embeddings_path.exists()
            else np.empty((0, 384), dtype=np.float32)
        )

    def search(self, query: np.ndarray, k: int = 100) -> List[Tuple[str, float]]:
        query = np.asarray(query, dtype=np.float32).reshape(-1)
        if not len(self.ids) or query.shape[0] != self.embeddings.shape[1]:
            return []
        norm = float(np.linalg.norm(query))
        if norm <= 1e-8:
            return []
        query = query / norm
        scores = np.asarray(self.embeddings @ query, dtype=np.float32)
        k = min(max(0, int(k)), len(scores))
        if not k:
            return []
        indices = np.argpartition(-scores, k - 1)[:k]
        indices = indices[np.argsort(-scores[indices], kind="stable")]
        return [(self.ids[int(index)], float(scores[int(index)])) for index in indices]


class HelixMRAGAdapter:
    """Multi-head semantic foreground with bounded expansion and 8D additions."""

    def __init__(
        self,
        run_dir: Path,
        embed_query: Optional[Callable[[str], np.ndarray]] = None,
    ):
        self.run_dir = Path(run_dir)
        self.catalog = CatalogView(self.run_dir)
        self.hot_index = ShadowVectorIndex(self.run_dir / "indexes" / "hot")
        self.cold_index = ShadowVectorIndex(self.run_dir / "indexes" / "cold")
        self.embed_query = embed_query
        self.last_result: Optional[RetrievalResult] = None

    @classmethod
    def from_active(
        cls,
        state_dir: Path,
        embed_query: Optional[Callable[[str], np.ndarray]] = None,
    ) -> Optional["HelixMRAGAdapter"]:
        state_dir = Path(state_dir)
        active_path = state_dir / "ACTIVE.json"
        if not active_path.exists():
            return None
        active = json.loads(active_path.read_text(encoding="utf-8"))
        run_dir = Path(active["run_dir"])
        if not run_dir.is_absolute():
            run_dir = state_dir / run_dir
        if not (run_dir / "catalog.jsonl").exists():
            return None
        return cls(run_dir, embed_query=embed_query)

    def retrieve(
        self,
        query: str,
        *,
        focus_state: FocusState = FocusState.WORKING,
        query_embedding: Optional[np.ndarray] = None,
        query_position_8d: Optional[Sequence[float]] = None,
        max_semantic_candidates: int = 100,
        spatial_limit: int = 2,
    ) -> RetrievalResult:
        started = time.perf_counter()
        query = (query or "").strip()
        hard_cap = focus_state.token_budget
        if not query:
            result = RetrievalResult([], {"hard_cap": hard_cap, "injected_tokens": 0})
            self.last_result = result
            return result

        query_tokens = set(_tokens(query))
        significant = query_tokens - STOPWORDS
        entities = self.catalog.matched_entities(query)
        topics = self.catalog.matched_topics(query)
        episodic = bool(query_tokens & EPISODIC_TERMS or DATE_RE.search(query))
        multi_hop = bool(query_tokens & MULTIHOP_TERMS) or query.casefold().count(" and ") >= 1

        if query_embedding is None and self.embed_query is not None:
            query_embedding = np.asarray(self.embed_query(query), dtype=np.float32)

        ranked, head_stats = self._semantic_foreground(
            query,
            significant,
            entities,
            topics,
            query_embedding,
            max_semantic_candidates,
        )
        foreground, suppressed = self._suppress_constituents(
            ranked, significant, episodic=episodic
        )
        expansion = self._expand(
            foreground,
            significant,
            entities,
            topics,
            episodic=episodic,
            multi_hop=multi_hop,
        )
        spatial = self._spatial_additions(
            query_position_8d,
            excluded={entry["canonical_id"] for entry in foreground + expansion},
            limit=min(2, max(0, int(spatial_limit))),
        )
        selected = self._pack(
            foreground,
            expansion,
            spatial,
            hard_cap=hard_cap,
            significant=significant,
            multi_hop=multi_hop,
        )

        candidates = [self._candidate(entry) for entry in selected]
        lane_tokens = Counter()
        lane_counts = Counter()
        for candidate in candidates:
            lane_tokens[candidate.lane] += candidate.token_count
            lane_counts[candidate.lane] += 1
        stats = {
            "focus_state": focus_state.value,
            "hard_cap": hard_cap,
            "injected_tokens": sum(candidate.token_count for candidate in candidates),
            "semantic_candidates": len(ranked),
            "suppressed_constituents": len(suppressed),
            "multi_hop_candidates": len(expansion),
            "spatial_candidates": len(spatial),
            "selected": len(candidates),
            "by_lane": dict(lane_counts),
            "tokens_by_lane": dict(lane_tokens),
            "episodic_intent": episodic,
            "multi_hop_intent": multi_hop,
            "entity_matches": entities,
            "topic_matches": topics,
            "semantic_heads": head_stats,
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 3),
        }
        result = RetrievalResult(candidates, stats)
        self.last_result = result
        return result

    def _semantic_foreground(
        self,
        query: str,
        significant: Set[str],
        entities: List[str],
        topics: List[str],
        query_embedding: Optional[np.ndarray],
        limit: int,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
        heads: Dict[str, List[Tuple[str, float]]] = {}
        if query_embedding is not None:
            heads["full_query_cosine"] = self.hot_index.search(query_embedding, k=limit)

        rare_terms = sorted(
            significant,
            key=lambda token: (-self.catalog._idf.get(token, 0.0), token),
        )[:8]
        lexical = []
        entity_rank = []
        topic_rank = []
        relation_rank = []
        temporal_rank = []
        relation_query = significant & RELATION_TERMS
        temporal_query = bool(significant & EPISODIC_TERMS or DATE_RE.search(query))
        for entry in self.catalog.hot:
            canonical_id = entry["canonical_id"]
            tokens = self.catalog.tokens(canonical_id)
            rare_score = sum(
                self.catalog._idf.get(token, 1.0) for token in rare_terms if token in tokens
            )
            if rare_score:
                lexical.append((canonical_id, rare_score))
            matched_entities = set(entities) & set(
                entry.get("entities", []) + entry.get("aliases", [])
            )
            if matched_entities:
                entity_rank.append((canonical_id, float(len(matched_entities))))
            matched_topics = set(topics) & set(entry.get("topics", []))
            if matched_topics:
                topic_rank.append((canonical_id, float(len(matched_topics))))
            if relation_query and (tokens & RELATION_TERMS or entry.get("relations")):
                relation_rank.append((canonical_id, float(len(tokens & RELATION_TERMS)) + 0.5))
            if temporal_query and (entry.get("timestamp") or tokens & EPISODIC_TERMS):
                temporal_rank.append((canonical_id, 1.0))
        for values in (lexical, entity_rank, topic_rank, relation_rank, temporal_rank):
            values.sort(key=lambda item: (-item[1], item[0]))
        heads["rare_lexical"] = lexical[:limit]
        heads["entities_aliases"] = entity_rank[:limit]
        heads["topic_tags"] = topic_rank[:limit]
        heads["relations"] = relation_rank[:limit]
        heads["temporal"] = temporal_rank[:limit]

        weights = {
            "full_query_cosine": 1.0,
            "rare_lexical": 0.85,
            "entities_aliases": 1.0,
            "topic_tags": 0.7,
            "relations": 0.65,
            "temporal": 0.7,
        }
        fused = defaultdict(float)
        semantic_similarity = {}
        head_membership = defaultdict(list)
        for head, values in heads.items():
            for rank, (canonical_id, score) in enumerate(values, 1):
                fused[canonical_id] += weights[head] / (60.0 + rank)
                head_membership[canonical_id].append(head)
                if head == "full_query_cosine":
                    semantic_similarity[canonical_id] = score

        # A reviewed lossless compound that contains every requested term is
        # the most compact sufficient foreground.  The fixed bonus is larger
        # than ordinary RRF rank gaps but is never granted to interpretive or
        # partially covered summaries.
        for canonical_id in list(fused):
            entry = self.catalog.hot_by_id[canonical_id]
            if (
                entry.get("compound_type") == "lossless_compound"
                and entry.get("coverage_status") in {"verified", "full"}
                and significant.issubset(self.catalog.tokens(canonical_id))
            ):
                fused[canonical_id] += 0.05
                head_membership[canonical_id].append("sufficient_compound")

        ranked_ids = sorted(
            fused,
            key=lambda canonical_id: (
                -fused[canonical_id],
                -semantic_similarity.get(canonical_id, -1.0),
                canonical_id,
            ),
        )[:limit]
        ranked = []
        for rank, canonical_id in enumerate(ranked_ids, 1):
            entry = dict(self.catalog.hot_by_id[canonical_id])
            entry["lane"] = "semantic"
            entry["semantic_rank"] = rank
            entry["semantic_score"] = fused[canonical_id]
            entry["semantic_similarity"] = semantic_similarity.get(canonical_id)
            entry["matched_heads"] = sorted(head_membership[canonical_id])
            entry["entity_matches"] = sorted(
                set(entities) & set(entry.get("entities", []) + entry.get("aliases", []))
            )
            entry["topic_matches"] = sorted(set(topics) & set(entry.get("topics", [])))
            ranked.append(entry)
        return ranked, {head: len(values) for head, values in heads.items()}

    def _suppress_constituents(
        self,
        ranked: List[Dict[str, Any]],
        significant: Set[str],
        *,
        episodic: bool,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, str]]:
        kept = []
        suppressed: Dict[str, str] = {}
        seen_content = set()
        ranked_ids = {entry["canonical_id"] for entry in ranked}
        for entry in ranked:
            canonical_id = entry["canonical_id"]
            if canonical_id in suppressed:
                continue
            normalized = _normalize_content(entry.get("content", ""))
            if normalized in seen_content:
                suppressed[canonical_id] = "retrieval_view_duplicate"
                continue
            seen_content.add(normalized)
            kept.append(entry)
            if episodic or entry["kind"] != "belief":
                continue
            sufficient = significant.issubset(self.catalog.tokens(canonical_id) | STOPWORDS)
            safe_coverage = (
                entry.get("review_status") in {"approved", "legacy_approved", "approved_legacy"}
                and entry.get("coverage_status") in {"verified", "full"}
                and entry.get("compound_type") != "interpretive"
                and entry.get("contradiction_state") == "none"
            )
            if sufficient and safe_coverage:
                for source_id in entry.get("source_links", []):
                    if source_id in ranked_ids:
                        suppressed[source_id] = f"covered_by:{canonical_id}"
        return kept, suppressed

    def _expand(
        self,
        foreground: List[Dict[str, Any]],
        significant: Set[str],
        entities: List[str],
        topics: List[str],
        *,
        episodic: bool,
        multi_hop: bool,
    ) -> List[Dict[str, Any]]:
        selected_ids = {entry["canonical_id"] for entry in foreground}
        proposed: Dict[str, Tuple[float, str]] = {}
        for seed_rank, seed in enumerate(foreground[:4], 1):
            source_incomplete = not significant.issubset(
                self.catalog.tokens(seed["canonical_id"]) | STOPWORDS
            )
            allow_cold = episodic or multi_hop or source_incomplete
            edges = []
            edges.extend((target, "source") for target in seed.get("source_links", []))
            edges.extend((target, "relation") for target in seed.get("relations", []))
            edges.extend((target, "component") for target in seed.get("component_ids", []))
            if episodic:
                edges.extend((target, "adjacency") for target in seed.get("adjacent_ids", []))
            for target, reason in edges:
                if target in selected_ids:
                    continue
                target_entry = self.catalog.by_id.get(target)
                if not target_entry:
                    continue
                if target_entry["retrieval_status"] == "cold" and not allow_cold:
                    continue
                if target_entry["retrieval_status"] not in {"hot", "cold"}:
                    continue
                score = 2.0 / seed_rank + (0.5 if reason == "source" else 0.0)
                if score > proposed.get(target, (0.0, ""))[0]:
                    proposed[target] = (score, reason)

        if multi_hop:
            for label in entities + topics:
                for target in self.catalog._entity_index.get(label, set()) | self.catalog._topic_index.get(label, set()):
                    if target not in selected_ids:
                        entry = self.catalog.by_id.get(target)
                        if entry and entry["retrieval_status"] in {"hot", "cold"}:
                            proposed[target] = max(proposed.get(target, (0.0, "")), (0.8, "shared_cluster"))
                for transition_target, weight in self.catalog.transitions.get(label, {}).items():
                    target_ids = self.catalog._entity_index.get(transition_target, set()) | self.catalog._topic_index.get(transition_target, set())
                    for target in target_ids:
                        if target not in selected_ids:
                            proposed[target] = max(
                                proposed.get(target, (0.0, "")),
                                (min(1.5, float(weight) / 10.0), "directed_transition"),
                            )

        expansion = []
        for target, (score, reason) in sorted(
            proposed.items(), key=lambda item: (-item[1][0], item[0])
        ):
            entry = dict(self.catalog.by_id[target])
            entry["lane"] = "multi_hop"
            entry["expansion_score"] = score
            entry["expansion_reason"] = reason
            expansion.append(entry)
        return expansion[:20]

    def _spatial_additions(
        self,
        query_position_8d: Optional[Sequence[float]],
        *,
        excluded: Set[str],
        limit: int,
    ) -> List[Dict[str, Any]]:
        if query_position_8d is None or limit <= 0:
            return []
        query = np.asarray(query_position_8d, dtype=np.float32).reshape(-1)
        if query.shape[0] != 8:
            return []
        scored = []
        for entry in self.catalog.hot:
            if entry["canonical_id"] in excluded or len(entry.get("position_8d", [])) != 8:
                continue
            position = np.asarray(entry["position_8d"], dtype=np.float32)
            distance_sq = float(np.sum((position - query) ** 2)) + 1e-4
            mass = max(0.1, float(entry.get("importance", 1.0)))
            stability = entry.get("stability_index")
            stability = 0.5 if stability is None else max(0.0, min(1.0, float(stability)))
            affect = entry.get("affect", {}) if isinstance(entry.get("affect"), dict) else {}
            amplitude = max(0.0, min(1.0, float(affect.get("s_total") or 0.0)))
            gravity = mass * (0.5 + 0.3 * stability + 0.2 * amplitude) / distance_sq
            scored.append((gravity, entry))
        scored.sort(key=lambda item: (-item[0], item[1]["canonical_id"]))
        result = []
        seen_content = set()
        for gravity, source in scored:
            normalized = _normalize_content(source.get("content", ""))
            if normalized in seen_content:
                continue
            seen_content.add(normalized)
            entry = dict(source)
            entry["lane"] = "spatial"
            entry["spatial_gravity"] = gravity
            result.append(entry)
            if len(result) >= limit:
                break
        return result

    def _pack(
        self,
        foreground: List[Dict[str, Any]],
        expansion: List[Dict[str, Any]],
        spatial: List[Dict[str, Any]],
        *,
        hard_cap: int,
        significant: Set[str],
        multi_hop: bool,
    ) -> List[Dict[str, Any]]:
        semantic_target = int(hard_cap * 0.75)
        hop_target = int(hard_cap * 0.15)
        spatial_target = hard_cap - semantic_target - hop_target
        selected_semantic: List[Dict[str, Any]] = []
        selected_hops: List[Dict[str, Any]] = []
        selected_spatial: List[Dict[str, Any]] = []
        used = 0

        def add(target: List[Dict[str, Any]], entry: Dict[str, Any], allowance: int) -> bool:
            nonlocal used
            remaining = min(allowance, hard_cap - used)
            if remaining <= 0:
                return False
            fitted = self._fit_entry(entry, remaining)
            if fitted is None:
                return False
            target.append(fitted)
            used += estimate_tokens(fitted.get("content", ""))
            return True

        # Foreground owns order. Direct entity/topic matches in the top five
        # are required semantic evidence and may borrow supplemental capacity.
        deferred = []
        for entry in foreground:
            current_semantic = sum(estimate_tokens(item["content"]) for item in selected_semantic)
            rank = entry.get("semantic_rank", 999)
            direct = bool(
                rank <= 3
                or (rank <= 5 and (entry.get("entity_matches") or entry.get("topic_matches")))
            )
            allowance = hard_cap - used if direct else semantic_target - current_semantic
            if allowance > 0 and add(selected_semantic, entry, allowance):
                continue
            deferred.append(entry)

        current_hop = 0
        remaining_expansion = []
        for entry in expansion:
            allowance = hop_target - current_hop
            if allowance <= 0:
                remaining_expansion.append(entry)
                continue
            if add(selected_hops, entry, allowance):
                current_hop = sum(estimate_tokens(item["content"]) for item in selected_hops)
            else:
                remaining_expansion.append(entry)

        current_spatial = 0
        for entry in spatial[:2]:
            allowance = min(spatial_target - current_spatial, hard_cap - used)
            if allowance <= 0:
                break
            if add(selected_spatial, entry, allowance):
                current_spatial = sum(estimate_tokens(item["content"]) for item in selected_spatial)

        # Only after actual supplemental use is known may required multi-hop
        # evidence borrow capacity that would otherwise remain empty.
        if multi_hop:
            for entry in remaining_expansion:
                if used >= hard_cap:
                    break
                add(selected_hops, entry, hard_cap - used)

        # Fill unused space with more semantic evidence. It is inserted before
        # supplemental lanes, preserving semantic foreground order.
        for entry in deferred:
            if used >= hard_cap:
                break
            add(selected_semantic, entry, hard_cap - used)
        return selected_semantic + selected_hops + selected_spatial

    @staticmethod
    def _fit_entry(entry: Dict[str, Any], token_allowance: int) -> Optional[Dict[str, Any]]:
        # Tiny fragments are contamination, not evidence. Leave the capacity
        # unused rather than inject one-to-seven orphaned words.
        if token_allowance < 8:
            return None
        copy = dict(entry)
        tokens = estimate_tokens(copy.get("content", ""))
        if tokens <= token_allowance:
            return copy
        word_allowance = max(1, int(token_allowance / 1.33))
        words = copy.get("content", "").split()
        if not words:
            return None
        copy["content"] = " ".join(words[:word_allowance])
        copy.setdefault("metadata", {})
        copy["metadata"] = dict(copy["metadata"])
        copy["metadata"]["truncated_for_budget"] = True
        return copy

    @staticmethod
    def _candidate(entry: Dict[str, Any]) -> RetrievalCandidate:
        return RetrievalCandidate(
            canonical_id=entry["canonical_id"],
            kind=entry["kind"],
            content=entry.get("content", ""),
            provenance=dict(entry.get("provenance", {})),
            semantic_rank=entry.get("semantic_rank"),
            lane=entry.get("lane", "semantic"),
            topic_matches=list(entry.get("topic_matches", [])),
            entity_matches=list(entry.get("entity_matches", [])),
            position_8d=list(entry.get("position_8d", [])),
            stability=entry.get("stability_index"),
            affect=dict(entry.get("affect", {})),
            suppression_reason=entry.get("suppression_reason"),
            semantic_score=float(entry.get("semantic_score", 0.0)),
            token_count=estimate_tokens(entry.get("content", "")),
            retrieval_status=entry.get("retrieval_status", "hot"),
            metadata={
                **dict(entry.get("metadata", {})),
                "review_status": entry.get("review_status"),
                "coverage_status": entry.get("coverage_status"),
                "compound_type": entry.get("compound_type"),
                "source_links": entry.get("source_links", []),
                "matched_heads": entry.get("matched_heads", []),
                "expansion_reason": entry.get("expansion_reason"),
                "spatial_gravity": entry.get("spatial_gravity"),
                "original_id": entry.get("original_id"),
            },
        )
