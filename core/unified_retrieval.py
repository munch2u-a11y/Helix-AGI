"""Helix — Unified Retrieval (mRAG foreground + lateral complements)

Combines three deliberately separated retrieval lanes over one tiered corpus:

  Lane A — semantic (memory/mrag/semantic_lane.py). Full-trigger, sentence,
           and RAKE heads query the native 1024D SemanticIndex, fused with
           rarity-weighted exact terms and conceptual-tag overlap.

  Lane B — raw spatial. Verlinde entropic gravity T·m/d² over the 8D
           cognitive manifold, with no semantic pre-filter.

  Lane C — associative cluster transitions. A tiny additive complement
           learned from direct foreground-cluster movement across turns.

Why both. The LoCoMo baseline (documents/locomo_benchmark_report.md) measured
the 384D index at Recall@5 0.378 and the 8D manifold at 0.062, but the
preconscious combining them at 0.145 — the combination was losing to its own
best lane. The cause is scale: fused cosine lives in ~[0,1] while gravity is
unbounded and routinely exceeds 100, so any blended score is really just the
gravity ranking wearing a cosine hat.

The mRAG lane owns foreground order. Spatial and associative results are
additive complements and never re-rank or displace an mRAG hit. RRF remains
available as a diagnostic utility for benchmark comparisons, but it is not
used by the production merge: even scale-free fusion can perturb the
high-accuracy semantic order merely because an item happened to collide in
the lossy 8D projection.

Lane B's real contribution is what Lane A never found at all — lateral,
associative pulls that cosine similarity does not model. Those items are
capped by a complement quota rather than left to compete on score, so the
spatial lane has a guaranteed but bounded voice.

Provenance suppression is what makes the tiers behave like matter: a memory is
an element, and the beliefs formed from it are heavier composite structures.
When a composite and its own constituents both surface, whichever ranked
higher keeps the slot and the other drops. Nothing is written or deleted — the
same memory remains a constituent of every belief that cites it and is fully
retrievable on the next query.
"""

import logging
import os
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from memory.mrag.corpus import HelixCorpus, normalize_ref
from memory.mrag.semantic_lane import SemanticLane, estimate_tokens
from memory.mrag.vector_store import HelixVectorStore
from memory.record_envelope import record_kind_from_index_metadata
from core.context_office import ContextOffice, is_enabled as office_enabled
from core.memory_intake_office import MemoryIntakeOffice

logger = logging.getLogger("helix.core.unified_retrieval")

# Reciprocal rank fusion constant. 60 is the value from the original RRF
# paper and is deliberately large relative to the ranks that matter: it
# flattens the difference between ranks 1 and 2 so a single lane cannot
# dominate on tiny rank gaps, while still ordering decisively across the
# ~10-rank scale the budget actually consumes.
RRF_K = 60

# Two candidates whose (timestamp-stripped) embeddings are at least this
# similar are the same fact restated, not two distinct facts, and only one
# survives. Calibrated by mRAG against real belief clusters: genuine
# restatements measured 0.87-0.95, genuinely distinct facts about the same
# topic measured 0.47-0.66. 0.90 sits above the one confirmed false positive
# (two different screenplays at 0.873).
DUPLICATE_SIMILARITY_THRESHOLD = 0.90

# Cheap pre-filter ahead of the cosine purge, carried over from
# Preconscious._deduplicate_beliefs: two items sharing this fraction of their
# words are near-certainly redundant and are collapsed without an embedding
# comparison.
WORD_OVERLAP_THRESHOLD = 0.6

# Optional legacy adjacency expansion for Tier-0 memories. It is disabled by
# default because temporal contiguity is association, not semantic evidence;
# the raw 8D and transition lanes now own that role. It remains available as a
# migration switch for benchmark parity.
ADJACENCY_RESERVE_FRACTION = 0.20
ADJACENCY_TOP_ANCHORS = 3
ADJACENCY_TURN_WINDOW = 1
ADJACENCY_TURN_WINDOW_TOP1 = 2

# Fallback item cap when no token budget is supplied by the caller.
DEFAULT_MAX_ITEMS = 12

# Dynamic injection budget, carried over from mRAG's _effective_token_ceiling.
# The budget is a multiple of the corpus's own average item length rather than
# a fixed constant, so it scales with how the mind actually writes: a store of
# terse beliefs gets a tight budget, a store of long verbatim tool returns gets
# a proportionally larger one. Bounded by a fraction of the model's context
# window so it stays proportionate on small-context models.
BUDGET_ITEMS_MULTIPLE = 15.0
BUDGET_CONTEXT_FRACTION = 0.15
DEFAULT_CONTEXT_LIMIT = 8192
TYPED_RESERVE_LIMIT = 3
EPISODE_COMPLEMENT_LIMIT = 2
DEFAULT_THOUGHT_LIMIT = 2


def is_enabled() -> bool:
    """Whether the unified pipeline is active.

    Defaults on; set HELIX_UNIFIED_RAG=0 to fall back to the pre-existing
    gravity-only belief retrieval.
    """
    return os.environ.get("HELIX_UNIFIED_RAG", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )


class UnifiedRetrieval:
    """mRAG-primary retrieval with bounded lateral complements."""

    def __init__(
        self,
        belief_store,
        memory_manager=None,
        physics_engine=None,
        include_memories: bool = True,
        max_memories: Optional[int] = None,
    ):
        self.belief_store = belief_store
        self.memory_manager = memory_manager
        self.physics_engine = physics_engine
        self.corpus = HelixCorpus(
            belief_store=belief_store,
            memory_manager=memory_manager,
            physics_engine=physics_engine,
            include_memories=include_memories,
            max_memories=max_memories,
        )
        self.vector_store = HelixVectorStore(physics_engine)
        self.lane_a = SemanticLane(self.corpus, self.vector_store)
        self.context_office = ContextOffice(self.corpus) if office_enabled() else None
        self.intake = MemoryIntakeOffice()
        self.last_work_order = None
        self.enable_mrag_adjacency = os.environ.get(
            "HELIX_MRAG_ADJACENCY", "0"
        ).strip().lower() in ("1", "true", "yes", "on")
        profile = os.environ.get("HELIX_MRAG_PROFILE", "local").strip().lower()
        self.profile = "frontier" if profile in ("frontier", "gpt") else "local"
        default_context = 128_000 if self.profile == "frontier" else DEFAULT_CONTEXT_LIMIT
        default_multiple = 30.0 if self.profile == "frontier" else BUDGET_ITEMS_MULTIPLE
        try:
            self.context_limit = max(
                1024, int(os.environ.get("HELIX_MRAG_CONTEXT_LIMIT", default_context))
            )
        except (TypeError, ValueError):
            self.context_limit = default_context
        try:
            self.budget_items_multiple = max(
                1.0,
                float(os.environ.get("HELIX_MRAG_BUDGET_ITEM_MULTIPLE", default_multiple)),
            )
        except (TypeError, ValueError):
            self.budget_items_multiple = default_multiple

    def _get_spatial_mind(self):
        if self.physics_engine and hasattr(self.physics_engine, "spatial_mind"):
            return self.physics_engine.spatial_mind
        if self.memory_manager and hasattr(self.memory_manager, "_physics") and hasattr(self.memory_manager._physics, "spatial_mind"):
            return self.memory_manager._physics.spatial_mind
        return None

        # Diagnostics from the most recent retrieve(), read by the benchmark
        # harness for lane attribution.
        self.last_stats: Dict[str, Any] = {}
        self.last_lane_a_ids: Set[str] = set()
        self._token_budget_cache: Dict[Tuple[int, int], int] = {}

    # ── Main entry point ─────────────────────────────────────────────

    def retrieve(
        self,
        trigger_text: str,
        spatial_candidates: Optional[List[Dict[str, Any]]] = None,
        complement_quota: int = 2,
        max_items: int = DEFAULT_MAX_ITEMS,
        token_budget: Optional[int] = None,
        exclude: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Select mRAG foreground and append the raw spatial complement.

        Args:
            trigger_text: The text to retrieve against.
            spatial_candidates: Raw Lane B output (id + gravity) from the 8D
                belief and memory fields, in gravity order.
                None or empty runs Lane A alone.
            complement_quota: Max items admitted that Lane A did not rank at
                all. Callers pass Preconscious._compute_focus_budget()'s
                allowance so the spatial voice narrows during deep tool work.
            max_items: Hard cap on returned items.
            token_budget: Content-token ceiling. None uses max_items only.
            exclude: Item ids to drop outright (the caller's own blacklists).

        Returns:
            Selected items. mRAG order is unchanged; bounded spatial results
            are appended. Each carries lane/tier/rank diagnostics.
        """
        trigger_text = (trigger_text or "").strip()
        if not trigger_text:
            self.last_stats = {}
            self.last_lane_a_ids = set()
            return []

        exclude = exclude or set()

        known_entities = (
            self.context_office.cases.known_names()
            if self.context_office is not None and self.context_office.cases is not None
            else ()
        )
        work_order = self.intake.review(
            trigger_text, known_entities=known_entities,
        )
        self.last_work_order = work_order
        search_query = work_order.search_query or trigger_text

        semantic_lane_a = [
            item for item in self.lane_a.retrieve(search_query)
            if item["id"] not in exclude
        ]
        semantic_lane_a = self._route_record_roles(
            search_query, semantic_lane_a, work_order,
        )
        office_stats: Dict[str, Any] = {"enabled": False}
        if self.context_office is not None:
            brief = self.context_office.prepare(
                search_query,
                semantic_lane_a,
                max_items=max_items,
                work_order=work_order,
            )
            lane_a = [
                item for item in brief.items
                if item.get("office_verified") or item.get("id") not in exclude
            ]
            office_stats = brief.diagnostics
        else:
            lane_a = semantic_lane_a
        lane_a = self._apply_record_policy(lane_a, work_order)
        lane_b_ranked = self._prepare_spatial(spatial_candidates or [], exclude)
        lane_b_ranked = self._apply_record_policy(lane_b_ranked, work_order)
        self.last_lane_a_ids = {item["id"] for item in lane_a}

        merged = self._semantic_primary_merge(lane_a, lane_b_ranked, complement_quota)
        merged.extend(self._episode_additions(
            merged, work_order, limit=EPISODE_COMPLEMENT_LIMIT,
        ))
        merged, suppressed_ids = self._suppress_by_provenance(merged)
        merged, duplicate_ids = self._purge_near_duplicates(merged)

        # Adjacency expansion pulls conversational neighbours by position, not
        # by score, so it would happily re-add the very constituents
        # suppression just dropped — a memory is always adjacent to itself in
        # the turn index. Both exclusion sets are threaded through so the
        # budget phase cannot undo either dedup pass.
        blocked = suppressed_ids | duplicate_ids
        selected = self._fill_budget(
            merged,
            max_items,
            token_budget,
            blocked,
            expand_adjacency=self.enable_mrag_adjacency,
        )

        lane_counts = {"semantic": 0, "spatial": 0, "both": 0}
        for item in selected:
            lane_counts[item.get("lane", "semantic")] = lane_counts.get(item.get("lane", "semantic"), 0) + 1
        self.last_stats = {
            "lane_a_candidates": len(lane_a),
            "lane_b_candidates": len(lane_b_ranked),
            "merged_candidates": len(merged),
            "selected": len(selected),
            "suppressed_provenance": len(suppressed_ids),
            "suppressed_duplicate": len(duplicate_ids),
            "by_lane": lane_counts,
            "by_tier": {
                tier: sum(1 for i in selected if i.get("tier") == tier)
                for tier in (0, 1, 2)
            },
            "lexicon_hits": sorted(self.lane_a.last_lexicon_matches),
            "semantic_heads": list(self.lane_a.last_search_heads),
            "retrieval_profile": self.profile,
            "memory_work_order": work_order.to_dict(),
            "context_office": office_stats,
        }

        logger.debug(
            "Unified retrieval: %d selected (A-only=%d B-only=%d both=%d), "
            "suppressed %d by provenance, %d as duplicates",
            len(selected), lane_counts.get("semantic", 0),
            lane_counts.get("spatial", 0), lane_counts.get("both", 0),
            len(suppressed_ids), len(duplicate_ids),
        )

        spatial_mind = self._get_spatial_mind()
        for item in selected:
            if spatial_mind:
                item["salience_metadata"] = spatial_mind.get_salience_metadata(item.get("id"), item)
            else:
                stability = float(item.get("stability_index", item.get("confidence", 0.5)))
                aff = float(item.get("affective_salience", item.get("importance", 0.5)))
                grav = float(item.get("gravity", 1.0))
                rel = float(item.get("relations_count", 0))
                trans = min(1.0, max(0.0, (0.5 * 0.6) + (min(rel, 10) / 10.0 * 0.4)))
                item["salience_metadata"] = {
                    "stability": round(max(0.0, min(1.0, stability)), 2),
                    "affective_salience": round(max(0.0, min(1.0, aff)), 2),
                    "gravity": round(max(0.0, grav), 2),
                    "transition_weight": round(max(0.0, min(1.0, trans)), 2),
                }

        return selected

<<<<<<< HEAD
    # ── Evidence-role routing ───────────────────────────────────────

    def _route_record_roles(
        self,
        query: str,
        semantic_items: List[Dict[str, Any]],
        work_order,
    ) -> List[Dict[str, Any]]:
        """Reserve semantic foreground for the evidence role a query asks for.

        The global mRAG ranking remains intact within each partition.  A
        filtered search over the same SemanticIndex fills role-specific gaps;
        this is a typed read view, not a second store or a cross-lane score.
        """
        targets = set(getattr(work_order, "target_record_kinds", ()) or ())
        if not targets:
            return self._apply_record_policy(semantic_items, work_order)

        typed: List[Dict[str, Any]] = []
        seen: Set[str] = set()

        def admit(item: Optional[Dict[str, Any]], *, similarity: Optional[float] = None):
            if not item or item.get("id") in seen:
                return
            if item.get("record_kind") not in targets:
                return
            item["typed_evidence_match"] = True
            if similarity is not None:
                item["typed_similarity"] = float(similarity)
            typed.append(item)
            seen.add(item["id"])

        for item in semantic_items:
            admit(item)

        filtered_search = getattr(self.vector_store, "query_top_k_filtered", None)
        if callable(filtered_search) and len(typed) < TYPED_RESERVE_LIMIT:
            query_embedding = self.vector_store.embed_text(query)
            results = filtered_search(
                query_embedding,
                k=max(TYPED_RESERVE_LIMIT * 3, TYPED_RESERVE_LIMIT),
                filter_fn=lambda _item_id, metadata: (
                    record_kind_from_index_metadata(metadata) in targets
                ),
            )
            minimum = float(getattr(self.lane_a, "min_semantic_similarity", 0.12))
            query_terms = set(getattr(work_order, "search_terms", ()) or ())
            for item_id, similarity in results:
                item = self.corpus.get(item_id)
                item_terms = set(str(
                    (item or {}).get("retrieval_text") or (item or {}).get("content", "")
                ).lower().split())
                literal = bool(query_terms & item_terms)
                if float(similarity) < minimum and not literal:
                    continue
                admit(item, similarity=similarity)
                if len(typed) >= TYPED_RESERVE_LIMIT:
                    break

        remaining = [item for item in semantic_items if item.get("id") not in seen]
        return self._apply_record_policy(typed + remaining, work_order)

    @staticmethod
    def _apply_record_policy(
        items: List[Dict[str, Any]],
        work_order,
    ) -> List[Dict[str, Any]]:
        policy = str(getattr(work_order, "thought_policy", "bounded") or "bounded")
        targets = set(getattr(work_order, "target_record_kinds", ()) or ())
        result: List[Dict[str, Any]] = []
        thought_count = 0
        for item in items:
            kind = item.get("record_kind")
            if kind != "thought":
                result.append(item)
                continue
            if "thought" in targets or policy == "primary":
                result.append(item)
                continue
            if policy == "exclude":
                continue
            if thought_count < DEFAULT_THOUGHT_LIMIT:
                result.append(item)
                thought_count += 1
        return result

    def _episode_additions(
        self,
        selected: List[Dict[str, Any]],
        work_order,
        *,
        limit: int,
    ) -> List[Dict[str, Any]]:
        """Append exact causal/turn neighbors around the best typed anchor."""
        related_kinds = set(
            getattr(work_order, "related_record_kinds", ()) or ()
        )
        if not related_kinds or limit <= 0:
            return []
        targets = set(getattr(work_order, "target_record_kinds", ()) or ())
        anchors = [
            item for item in selected
            if item.get("record_kind") in targets
        ][:1]
        if not anchors:
            return []

        anchor = anchors[0]
        anchor_id = anchor.get("id")
        anchor_pulse = anchor.get("pulse_id")
        direct_ids = set(anchor.get("caused_by") or [])
        candidates: List[Tuple[int, float, str, Dict[str, Any]]] = []
        selected_ids = {item.get("id") for item in selected}
        for item in self.corpus.all_items():
            item_id = item.get("id")
            if not item_id or item_id in selected_ids:
                continue
            if item.get("record_kind") not in related_kinds:
                continue
            reverse_causes = set(item.get("caused_by") or [])
            directly_linked = item_id in direct_ids or anchor_id in reverse_causes
            same_pulse = bool(
                anchor_pulse not in (None, 0, "0")
                and item.get("pulse_id") == anchor_pulse
            )
            if not directly_linked and not same_pulse:
                continue
            candidates.append((
                0 if directly_linked else 1,
                -float(item.get("relevance", 0.0)),
                str(item_id),
                item,
            ))
        additions: List[Dict[str, Any]] = []
        for _link_rank, _negative_relevance, _item_id, item in sorted(candidates):
            item["lane"] = "episode"
            item["episode_anchor"] = anchor_id
            item["rrf_score"] = 0.0
            additions.append(item)
            if len(additions) >= limit:
                break
        return additions

    def retrieve_multihop(
        self,
        trigger_text: str,
        spatial_candidates: Optional[List[Dict[str, Any]]] = None,
        complement_quota: int = 2,
        max_items: int = DEFAULT_MAX_ITEMS,
        token_budget: Optional[int] = None,
        exclude: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Multi-hop recall using the 8D gravity field to choose the next recall query.

        Hop 1: Semantic mRAG retrieves foreground evidence.
        Basin lookup: Query 8D gravity field around Hop 1 evidence to discover
                     nearby high-gravity concept basins missed by initial query.
        Hop 2: Formulate directed recall query from basin terms and retrieve Hop 2 candidates.
        """
        exclude = exclude or set()
        hop1_selected = self.retrieve(
            trigger_text=trigger_text,
            spatial_candidates=spatial_candidates,
            complement_quota=complement_quota,
            max_items=max_items,
            token_budget=token_budget,
            exclude=exclude,
        )

        if not hop1_selected:
            return []

        spatial_mind = self._get_spatial_mind()
        basin_terms = []
        if spatial_mind:
            basin_terms = spatial_mind.get_gravity_basin_keywords(hop1_selected, max_terms=4)

        if not basin_terms:
            return hop1_selected

        hop1_ids = {item["id"] for item in hop1_selected}
        next_query = f"{trigger_text} {' '.join(basin_terms)}"

        hop2_exclude = exclude | hop1_ids
        hop2_selected = self.retrieve(
            trigger_text=next_query,
            spatial_candidates=spatial_candidates,
            complement_quota=complement_quota,
            max_items=max_items,
            token_budget=token_budget,
            exclude=hop2_exclude,
        )

        combined = list(hop1_selected)
        for item in hop2_selected:
            if item["id"] not in hop1_ids and len(combined) < max_items:
                item["lane"] = "multihop"
                combined.append(item)

        return combined

    def format_personal_opinions(
        self, candidates: List[Dict[str, Any]], limit: int = 4
    ) -> str:
        """Extract and format 1st-person subjective statements / feelings to induce tone.

        Uses backend salience, affect fields, and category signals (premises, preferences, feelings)
        to select top subjective opinion statements. Injected cleanly under 'Personal Opinions:'
        without sending raw numbers or metadata labels to the model.
        """
        opinions = []
        seen_contents = set()

        for item in candidates:
            content = (item.get("content") or "").strip()
            if not content or content in seen_contents:
                continue

            sal = item.get("salience_metadata", {})
            aff = float(sal.get("affective_salience", item.get("affective_salience", 0.0)))
            grav = float(sal.get("gravity", item.get("gravity", 0.0)))
            category = item.get("category", "")

            is_subjective = (
                any(w in content.lower() for w in ["i ", "my ", "me ", "myself", "we ", "our "])
                or category in ("premises", "preferences", "people")
                or aff > 0.5
                or grav > 1.2
            )

            if is_subjective:
                score = (aff * 0.4) + (grav * 0.6) + (0.5 if category == "premises" else 0.0)
                opinions.append((score, content))
                seen_contents.add(content)

        opinions.sort(key=lambda x: x[0], reverse=True)

        if not opinions:
            return ""

        formatted_lines = ["Personal Opinions:"]
        for _, text in opinions[:limit]:
            formatted_lines.append(f'- "{text}"')

        return "\n".join(formatted_lines)
>>>>>>> main

    def associative_additions(
        self,
        cluster_scores: List[Dict[str, Any]],
        existing: List[Dict[str, Any]],
        cluster_resolver,
        *,
        limit: int = 2,
        exclude: Optional[Set[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Choose a small affect-aware complement from learned clusters.

        Candidates already found by mRAG are deliberately ineligible.  This
        lane exists to recover non-semantic associations, not to provide one
        more vote for the semantic answer.  Existing selections always come
        first through provenance and duplicate suppression, so an association
        can add context but cannot displace foreground recall.
        """
        if not cluster_scores or limit <= 0:
            return []

        exclude_ids = set(exclude or set())
        exclude_ids |= {item.get("id") for item in existing if item.get("id")}
        exclude_ids |= self.last_lane_a_ids
        score_by_cluster = {
            record.get("cluster_id"): float(record.get("score", 0.0))
            for record in cluster_scores if record.get("cluster_id")
        }

        pool: List[Dict[str, Any]] = []
        for item in self.corpus.all_items():
            item_id = item.get("id")
            if not item_id or item_id in exclude_ids:
                continue
            try:
                cluster_id, _position = cluster_resolver(item)
            except Exception:
                continue
            association_score = score_by_cluster.get(cluster_id)
            if association_score is None:
                continue

            candidate = dict(item)
            candidate["lane"] = "associative"
            candidate["association_cluster"] = cluster_id
            candidate["association_score"] = association_score
            candidate["rrf_score"] = 0.0
            candidate["lane_a_rank"] = None
            candidate["lane_b_rank"] = None
            candidate["salience_score"] = self._metadata_salience(candidate)
            pool.append(candidate)

        pool.sort(key=lambda item: (
            -item.get("association_score", 0.0),
            -item.get("salience_score", 0.0),
            -item.get("relevance", 0.0),
            item.get("id", ""),
        ))

        # First take one representative per associated cluster; then use any
        # remaining quota with tier diversity (episodic memory vs belief).
        proposed: List[Dict[str, Any]] = []
        used_clusters: Set[str] = set()
        for item in pool:
            cluster_id = item.get("association_cluster")
            if cluster_id in used_clusters:
                continue
            proposed.append(item)
            used_clusters.add(cluster_id)
            if len(proposed) >= limit:
                break

        if len(proposed) < limit:
            used_ids = {item["id"] for item in proposed}
            present_kinds = {"memory" if item.get("tier") == 0 else "belief" for item in proposed}
            for item in pool:
                if item["id"] in used_ids:
                    continue
                kind = "memory" if item.get("tier") == 0 else "belief"
                if kind in present_kinds and len(present_kinds) < 2:
                    continue
                proposed.append(item)
                used_ids.add(item["id"])
                present_kinds.add(kind)
                if len(proposed) >= limit:
                    break

        # Existing foreground wins every collision because it is ordered first.
        combined, _ = self._suppress_by_provenance(existing + proposed)
        combined, _ = self._purge_near_duplicates(combined)
        existing_ids = {item.get("id") for item in existing}
        additions = [item for item in combined if item.get("id") not in existing_ids]
        return additions[:limit]

    @staticmethod
    def _metadata_salience(item: Dict[str, Any]) -> float:
        """Late salience score for the non-semantic lane only."""
        relevance = max(0.0, float(item.get("relevance", 0.0)))
        bounded_relevance = relevance / (1.0 + relevance)
        stability = max(0.0, min(1.0, float(item.get("stability_index", 0.5))))
        affect = max(0.0, min(1.0, float(item.get("affective_salience", 0.0))))
        return (0.50 * bounded_relevance) + (0.30 * stability) + (0.20 * affect)

    def effective_token_budget(self, context_limit: Optional[int] = None) -> int:
        """The injection's content-token ceiling.

        A profile-dependent multiple of the corpus's average item length
        (15x local, 30x frontier), bounded by BUDGET_CONTEXT_FRACTION of the
        context window. Replaces the fixed 500-token cap the gravity-only path
        used, which was sized for two or three summarized beliefs and is far
        too tight once verbatim memories are in the pool — the ported lane's
        recall depends on being able to actually inject what it retrieved.
        """
        items = self.corpus.all_items()
        limit = context_limit or self.context_limit
        cache_key = (getattr(self.corpus, "version", -1), int(limit))
        cached = self._token_budget_cache.get(cache_key)
        if cached is not None:
            return cached
        if items:
            total = sum(estimate_tokens(i.get("content", "")) for i in items)
            avg = total / len(items)
        else:
            avg = 30.0
        budget = int(min(
            self.budget_items_multiple * avg,
            limit * BUDGET_CONTEXT_FRACTION,
        ))
        # Corpus versions are monotonic; retain only the current version's
        # context-limit variants.
        self._token_budget_cache = {
            key: value for key, value in self._token_budget_cache.items()
            if key[0] == cache_key[0]
        }
        self._token_budget_cache[cache_key] = budget
        return budget

    # ── Lane B normalization ─────────────────────────────────────────

    def _prepare_spatial(
        self,
        spatial_candidates: List[Dict[str, Any]],
        exclude: Set[str],
    ) -> List[Dict[str, Any]]:
        """Map Lane B's gravity output onto corpus items.

        The raw lane scores points from the live belief and memory fields,
        which use the same IDs as the corpus. Resolving each hit to the shared
        item dict prevents one record arriving through two lanes from being
        treated as two candidates.
        """
        prepared = []
        seen: Set[str] = set()
        for cand in spatial_candidates:
            cid = cand.get("id")
            if not cid or cid in exclude or cid in seen:
                continue
            item = self.corpus.get(cid)
            if item is None:
                continue
            item["gravity"] = cand.get("gravity", 0.0)
            prepared.append(item)
            seen.add(cid)
        return prepared

    # ── Merge ────────────────────────────────────────────────────────

    def _semantic_primary_merge(
        self,
        lane_a: List[Dict[str, Any]],
        lane_b: List[Dict[str, Any]],
        complement_quota: int,
    ) -> List[Dict[str, Any]]:
        """Preserve mRAG ordering and append raw-8D-only candidates."""
        spatial_rank = {item["id"]: rank for rank, item in enumerate(lane_b)}
        merged: List[Dict[str, Any]] = []

        for rank, item in enumerate(lane_a):
            item["lane_a_rank"] = rank
            item["lane_b_rank"] = spatial_rank.get(item["id"])
            item["lane"] = "both" if item["lane_b_rank"] is not None else "semantic"
            # Rank-monotonic diagnostic value; it is never used to reorder.
            item["rrf_score"] = 1.0 / (RRF_K + rank)
            merged.append(item)

        if complement_quota <= 0:
            return merged

        semantic_ids = {item["id"] for item in lane_a}
        spatial_only = [item for item in lane_b if item["id"] not in semantic_ids]
        spatial_only.sort(key=lambda item: (
            -float(item.get("gravity", 0.0)),
            -self._metadata_salience(item),
            item["id"]
        ))
        for rank, item in enumerate(spatial_only[:complement_quota]):
            item["lane_a_rank"] = None
            item["lane_b_rank"] = spatial_rank.get(item["id"], rank)
            item["lane"] = "spatial"
            item["rrf_score"] = 0.0
            merged.append(item)
        return merged

    def _rrf_merge(
        self,
        lane_a: List[Dict[str, Any]],
        lane_b: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Reciprocal rank fusion across the two lanes.

        rrf(item) = 1/(K + rank_a) + 1/(K + rank_b), a missing lane
        contributing nothing. Ranks are 0-based positions within each lane's
        own ordering, so the two incomparable score scales never meet.
        """
        rank_a = {item["id"]: rank for rank, item in enumerate(lane_a)}
        rank_b = {item["id"]: rank for rank, item in enumerate(lane_b)}

        merged: Dict[str, Dict[str, Any]] = {}
        for item in lane_a:
            merged[item["id"]] = item
        for item in lane_b:
            merged.setdefault(item["id"], item)

        scored = []
        for item_id, item in merged.items():
            ra = rank_a.get(item_id)
            rb = rank_b.get(item_id)
            score = 0.0
            if ra is not None:
                score += 1.0 / (RRF_K + ra)
            if rb is not None:
                score += 1.0 / (RRF_K + rb)

            item["lane_a_rank"] = ra
            item["lane_b_rank"] = rb
            item["rrf_score"] = score
            if ra is not None and rb is not None:
                item["lane"] = "both"
            elif ra is not None:
                item["lane"] = "semantic"
            else:
                item["lane"] = "spatial"
            scored.append(item)

        # Ties broken by relevance (cognitive mass for beliefs, importance for
        # memories) so the heavier structure wins an exact rank tie.
        scored.sort(key=lambda i: (-i["rrf_score"], -i.get("relevance", 0.0)))
        return scored

    def _apply_complement_quota(
        self,
        merged: List[Dict[str, Any]],
        quota: int,
    ) -> List[Dict[str, Any]]:
        """Cap items Lane A never ranked.

        These are the spatial lane's genuine contribution — associations
        gravity found that cosine did not. They're valuable precisely because
        they're not semantically obvious, which is also why they need a
        ceiling.

        The cap bounds how many arrive; it does NOT decide whether they
        displace semantic hits. They don't: _fill_budget gives them their own
        slots on top of the semantic selection, so adding the spatial lane can
        only ever grow the injection, never trade away recall. Items both
        lanes ranked cost nothing against the quota — Lane B merely re-ranked
        something Lane A already had.
        """
        if quota <= 0:
            return [item for item in merged if item.get("lane") != "spatial"]

        kept = []
        complement_used = 0
        for item in merged:
            if item.get("lane") == "spatial":
                if complement_used >= quota:
                    continue
                complement_used += 1
            kept.append(item)
        return kept

    # ── Provenance suppression ───────────────────────────────────────

    def _suppress_by_provenance(
        self,
        merged: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Set[str]]:
        """Collapse composite/constituent pairs, higher rank wins.

        Walking in merged-rank order means the winner is decided by relevance,
        not by tier: a Tier-2 belief that outranks its source memories absorbs
        them, and a verbatim memory that outranks the belief built from it
        keeps the slot instead. That is the whole point of putting them in one
        pool — asking "what grade did she lead?" should surface the specific
        record, while asking "who is Sarah?" should surface the profile.

        Retrieval-only. Nothing is merged, rewritten or deleted.
        """
        present = {item["id"] for item in merged}

        # The edge map must be SYMMETRIC. Provenance is written in one
        # direction only: the Curator records memory_refs on the belief it
        # forms, and the source memory learns nothing about it (the memory was
        # written first, and is never rewritten). Walking only each winner's
        # own outward edges would therefore make suppression work in exactly
        # one direction — a composite could absorb its constituents, but a
        # verbatim memory that outranked its parent belief would leave that
        # belief in the pool, and the pair would both inject.
        linked: Dict[str, Set[str]] = {}
        for item in merged:
            item_id = item["id"]
            for edge in self.corpus.provenance_edges(item):
                if edge == item_id or edge not in present:
                    continue
                linked.setdefault(item_id, set()).add(edge)
                linked.setdefault(edge, set()).add(item_id)

        kept: List[Dict[str, Any]] = []
        suppressed: Set[str] = set()

        for item in merged:
            item_id = item["id"]
            if item_id in suppressed:
                continue
            kept.append(item)
            # This item won its slot; everything compositionally linked to it
            # that is still in the pool loses, whichever way the edge points.
            suppressed |= linked.get(item_id, set())

        return kept, suppressed

    # ── Duplicate purge ──────────────────────────────────────────────

    def _purge_near_duplicates(
        self,
        candidates: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], Set[str]]:
        """Collapse the same fact restated, keeping the higher-ranked copy.

        Distinct from provenance suppression: an agent that genuinely
        volunteers every week should keep every distinct episodic event
        (donated a car, organized a meal — real, different facts). What
        collapses here is the literal restatement of one fact across sessions,
        which competes for the same slots without adding information.

        Runs cross-lane, which is why it lives here rather than inside either
        lane — a duplicate pair often arrives one item per lane.
        """
        kept: List[Dict[str, Any]] = []
        kept_words: List[set] = []
        kept_embs: List[Optional[np.ndarray]] = []
        purged: Set[str] = set()

        for item in candidates:
            content = item.get("content", "")
            words = set(content.lower().split())
            # Transient office-state bids are already typed. They should not
            # trigger an embedding call merely to pass duplicate suppression.
            emb = None if item.get("tier") == -1 else self.corpus.embedding(item)

            duplicate = False
            for idx, prior_words in enumerate(kept_words):
                prior = kept[idx]
                protected_roles = {
                    "current_state", "state_history", "calculation_member",
                    "relation_member", "catalog_member", "causal_member",
                }
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
                if words and prior_words:
                    overlap = len(words & prior_words) / min(len(words), len(prior_words))
                    if overlap > WORD_OVERLAP_THRESHOLD:
                        duplicate = True
                        break
                prior_emb = kept_embs[idx]
                if emb is not None and prior_emb is not None:
                    sim = self.vector_store.cosine_similarity(emb, prior_emb)
                    if sim >= DUPLICATE_SIMILARITY_THRESHOLD:
                        duplicate = True
                        break

            if duplicate:
                purged.add(item["id"])
                continue

            kept.append(item)
            kept_words.append(words)
            kept_embs.append(emb)

        return kept, purged

    # ── Budget ───────────────────────────────────────────────────────

    def _fill_budget(
        self,
        candidates: List[Dict[str, Any]],
        max_items: int,
        token_budget: Optional[int],
        blocked: Optional[Set[str]] = None,
        expand_adjacency: bool = False,
    ) -> List[Dict[str, Any]]:
        """Fill the budget from the ranking, reserving a slice for adjacency.

        Phase 0 sets the spatial lane's complement aside. Those items are
        ADDITIVE: they get their own slots after the semantic selection is
        complete, so turning the spatial lane on can only grow the injection,
        never push a semantic hit out of it. Letting them compete for the same
        budget is what would put the ported lane's recall at risk, which is
        the one thing this pipeline must not do.

        Phase 1 fills from the merged ranking. If the legacy adjacency switch
        is explicitly enabled, it holds back ADJACENCY_RESERVE_FRACTION when
        Tier-0 memories are present; otherwise mRAG stays strictly semantic.
        Phase 2 optionally pulls conversational neighbours of top memories.
        Phase 3 returns any unused reserve to the ranking.
        Phase 4 appends the complement.
        """
        if not candidates:
            return []

        complement = (
            [c for c in candidates if c.get("lane") == "episode"]
            + [c for c in candidates if c.get("lane") == "spatial"]
        )
        candidates = [
            c for c in candidates if c.get("lane") not in {"episode", "spatial"}
        ]
        if not candidates:
            # Nothing semantic to anchor on; the complement becomes the result.
            candidates, complement = complement, []

        adjacency_possible = expand_adjacency and any(
            item.get("tier") == 0 for item in candidates
        )
        base_items = max_items
        base_tokens = token_budget
        if adjacency_possible:
            base_items = max(1, int(max_items * (1.0 - ADJACENCY_RESERVE_FRACTION)))
            if token_budget is not None:
                base_tokens = int(token_budget * (1.0 - ADJACENCY_RESERVE_FRACTION))

        selected: List[Dict[str, Any]] = []
        overflow: List[Dict[str, Any]] = []
        tokens = 0

        for item in candidates:
            item_tokens = estimate_tokens(item.get("content", ""))
            if not selected:
                # Always include the top-ranked item, whatever its size.
                selected.append(item)
                tokens += item_tokens
                continue
            if len(selected) >= base_items:
                overflow.append(item)
                continue
            if (
                base_tokens is not None
                and tokens + item_tokens > base_tokens
                and not item.get("office_bid_atomic")
            ):
                overflow.append(item)
                continue
            selected.append(item)
            tokens += item_tokens

        # Phase 2 — adjacency around the top Tier-0 anchors. `blocked` carries
        # everything the dedup passes removed; without it a suppressed
        # constituent walks straight back in as its own anchor's neighbour.
        selected_ids = {item["id"] for item in selected} | (blocked or set())
        if adjacency_possible:
            anchors = [i for i in selected if i.get("tier") == 0][:ADJACENCY_TOP_ANCHORS]
            for rank, anchor in enumerate(anchors):
                window = ADJACENCY_TURN_WINDOW_TOP1 if rank == 0 else ADJACENCY_TURN_WINDOW
                for neighbor in self.lane_a.adjacent_chunks(anchor, window):
                    nid = neighbor.get("id")
                    if nid in selected_ids:
                        continue
                    n_tokens = estimate_tokens(neighbor.get("content", ""))
                    if len(selected) >= max_items:
                        break
                    if token_budget is not None and tokens + n_tokens > token_budget:
                        continue
                    neighbor.setdefault("lane", "adjacency")
                    neighbor.setdefault("rrf_score", 0.0)
                    neighbor["tier"] = 0
                    selected.append(neighbor)
                    selected_ids.add(nid)
                    tokens += n_tokens

        # Phase 3 — return unused reserve to the ranking.
        for item in overflow:
            if item["id"] in selected_ids:
                continue
            item_tokens = estimate_tokens(item.get("content", ""))
            if len(selected) >= max_items:
                break
            if token_budget is not None and tokens + item_tokens > token_budget:
                continue
            selected.append(item)
            selected_ids.add(item["id"])
            tokens += item_tokens

        # Phase 4 — append exact episode neighbors, then the spatial
        # complement. These slots are extra by construction and each source is
        # independently bounded before reaching this method.
        for item in complement:
            if item["id"] in selected_ids:
                continue
            selected.append(item)
            selected_ids.add(item["id"])

        return selected

    # ── Telemetry passthrough ────────────────────────────────────────

    def note_injected(self, ids: List[str]):
        """Record what actually reached an injection.

        Feeds Lane A's repetition demotion and Helix's own reliance counters,
        which the Curator reads when deciding what to precipitate.
        """
        self.lane_a.note_injected(ids)
        try:
            self.corpus.record_usage(ids, sorted(self.lane_a.last_lexicon_matches))
        except Exception as e:
            logger.debug("Usage telemetry failed: %s", e)
