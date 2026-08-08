#!/usr/bin/env python3
"""
Helix — Unified Retrieval Tests

Covers the merge layer's decisions (core/unified_retrieval.py):
  1. Production merge preserves mRAG order and makes raw 8D additive.
     Scale-free RRF remains covered as a benchmark diagnostic utility.
  2. The complement quota bounding the spatial lane's distinctive voice.
  3. Provenance suppression resolving composite/constituent overlap by rank,
     in BOTH directions.
  4. That none of the above ever mutates the underlying stores.

The merge layer is tested against a stub corpus so the assertions are about
merge logic rather than embedding behaviour; the store-integrity test uses a
real BeliefStore and MemoryManager, since that is the property most worth
checking against the real thing.
"""

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.unified_retrieval import UnifiedRetrieval, RRF_K
from memory.mrag.corpus import normalize_ref


class _StubCorpus:
    """Minimal corpus double: fixed items, real provenance-edge semantics."""

    def __init__(self, items):
        self._items = items
        self._by_id = {i["id"]: i for i in items}
        self.version = 1

    def all_items(self):
        return self._items

    def get(self, item_id):
        return self._by_id.get(item_id)

    def embedding(self, item):
        return None  # forces the duplicate purge onto its word-overlap path

    def conceptual_tags(self, item):
        return []

    def provenance_edges(self, item):
        edges = set()
        for field in ("memory_refs", "component_ids", "relations", "belief_ids"):
            for ref in item.get(field, []) or []:
                normalized = normalize_ref(ref)
                if normalized and normalized != item["id"]:
                    edges.add(normalized)
        return edges

    def get_all_concept_expansions(self):
        return {}

    def get_all_relation_expansions(self):
        return {}

    def record_usage(self, injected_ids, lexicon_hit_ids=None):
        return 0


def _item(item_id, content, tier=1, relevance=1.0, **edges):
    item = {
        "id": item_id,
        "content": content,
        "tier": tier,
        "_category": "memory" if tier == 0 else "propositions",
        "relevance": relevance,
        "term": "",
        "aliases": [],
        "memory_refs": [],
        "component_ids": [],
        "relations": [],
        "belief_ids": [],
        "session_id": None,
        "turn_id": None,
        "event_id": None,
        "chunk_index": None,
        "position_8d": [],
    }
    item.update(edges)
    return item


def _build(items):
    """A UnifiedRetrieval wired to a stub corpus, bypassing __init__."""
    u = UnifiedRetrieval.__new__(UnifiedRetrieval)
    u.corpus = _StubCorpus(items)
    u.vector_store = None
    u.lane_a = None
    u.last_stats = {}
    u.last_lane_a_ids = set()
    return u


class TestSemanticPrimaryMerge(unittest.TestCase):
    """Raw 8D may annotate an mRAG result, never reorder it."""

    def test_spatial_collision_does_not_reorder_mrag(self):
        a, b, s = _item("a", "semantic first"), _item("b", "semantic second"), _item("s", "raw spatial")
        u = _build([a, b, s])

        merged = u._semantic_primary_merge([a, b], [b, s], complement_quota=1)

        self.assertEqual([item["id"] for item in merged], ["a", "b", "s"])
        self.assertEqual(merged[1]["lane"], "both")
        self.assertEqual(merged[2]["lane"], "spatial")

    def test_complement_quota_is_additive(self):
        semantic = [_item("a", "semantic")]
        spatial = [_item(f"s{i}", f"spatial {i}") for i in range(3)]
        u = _build(semantic + spatial)

        merged = u._semantic_primary_merge(semantic, spatial, complement_quota=2)
        self.assertEqual([item["id"] for item in merged], ["a", "s0", "s1"])


class TestAssociativeComplement(unittest.TestCase):
    def test_mrag_ranked_items_are_ineligible_for_association(self):
        foreground = _item("foreground", "guilt foreground")
        semantic_mother = _item("semantic_mother", "mother semantic candidate")
        lateral_memory = _item("mem_lateral", "caps stolen by monkeys", tier=0)
        for item in (semantic_mother, lateral_memory):
            item["cluster"] = "mother_cluster"
        u = _build([foreground, semantic_mother, lateral_memory])
        u.last_lane_a_ids = {"foreground", "semantic_mother"}

        additions = u.associative_additions(
            [{"cluster_id": "mother_cluster", "score": 1.5}],
            existing=[foreground],
            cluster_resolver=lambda item: (item.get("cluster"), np.zeros(8)),
            limit=2,
        )

        self.assertEqual([item["id"] for item in additions], ["mem_lateral"])
        self.assertEqual(additions[0]["lane"], "associative")


class TestRankFusion(unittest.TestCase):
    """RRF must order on rank, never on the lanes' own score scales."""

    def test_rrf_score_is_scale_free(self):
        """Gravity magnitude must not reach the merged order at all.

        Lane B's gravity is unbounded (T·m/d², routinely >100) while Lane A's
        fused cosine sits in ~[0,1]. Blending them is what made the combined
        preconscious rank worse than either lane alone, so the merge sees only
        ranks — the same ranks with wildly different gravity must produce
        byte-identical scores.
        """
        def merged_scores(gravity):
            a, b = _item("a", "alpha"), _item("b", "beta")
            b["gravity"] = gravity
            u = _build([a, b])
            return {m["id"]: m["rrf_score"] for m in u._rrf_merge([a, b], [b])}

        self.assertEqual(merged_scores(5000.0), merged_scores(0.001))

        scores = merged_scores(5000.0)
        # a: lane A rank 0 only. b: lane A rank 1 + lane B rank 0.
        self.assertAlmostEqual(scores["a"], 1.0 / RRF_K)
        self.assertAlmostEqual(scores["b"], 1.0 / (RRF_K + 1) + 1.0 / RRF_K)

    def test_lane_labels(self):
        a, b, c = _item("a", "x"), _item("b", "y"), _item("c", "z")
        u = _build([a, b, c])
        merged = {m["id"]: m for m in u._rrf_merge(lane_a=[a, b], lane_b=[b, c])}

        self.assertEqual(merged["a"]["lane"], "semantic")
        self.assertEqual(merged["b"]["lane"], "both")
        self.assertEqual(merged["c"]["lane"], "spatial")

    def test_both_lanes_beats_single_lane(self):
        """An item both lanes ranked should outrank one only Lane A ranked."""
        a, b, c = _item("a", "x"), _item("b", "y"), _item("c", "z")
        u = _build([a, b, c])
        # c is 3rd in A but 1st in B; b is 2nd in A and unranked in B.
        merged = u._rrf_merge(lane_a=[a, b, c], lane_b=[c])
        self.assertEqual([m["id"] for m in merged], ["c", "a", "b"])


class TestComplementQuota(unittest.TestCase):
    """The spatial lane gets a guaranteed but bounded voice."""

    def test_quota_caps_spatial_only_items(self):
        items = [_item(f"s{i}", f"spatial {i}") for i in range(5)]
        anchor = _item("a", "semantic anchor")
        u = _build(items + [anchor])

        merged = u._rrf_merge(lane_a=[anchor], lane_b=items)
        kept = u._apply_complement_quota(merged, quota=2)

        spatial_only = [k for k in kept if k["lane"] == "spatial"]
        self.assertEqual(len(spatial_only), 2)
        self.assertIn("a", [k["id"] for k in kept])

    def test_items_in_both_lanes_do_not_consume_quota(self):
        shared = [_item(f"x{i}", f"shared {i}") for i in range(4)]
        u = _build(shared)
        merged = u._rrf_merge(lane_a=shared, lane_b=shared)
        kept = u._apply_complement_quota(merged, quota=1)

        # Lane B only re-ranked what Lane A already had; nothing is dropped.
        self.assertEqual(len(kept), 4)

    def test_zero_quota_removes_spatial_only(self):
        a, s = _item("a", "anchor"), _item("s", "spatial only")
        u = _build([a, s])
        merged = u._rrf_merge(lane_a=[a], lane_b=[s])
        kept = u._apply_complement_quota(merged, quota=0)

        self.assertEqual([k["id"] for k in kept], ["a"])


class TestProvenanceSuppression(unittest.TestCase):
    """Composite and constituent collapse to one, higher rank winning."""

    def test_composite_outranking_absorbs_constituents(self):
        composite = _item(
            "ppl_sarah", "Sarah — climber, moved to Denver, leads 5.10.",
            tier=2, memory_refs=[1, 2],
        )
        m1 = _item("mem_1", "Sarah: I led my first 5.10 today!", tier=0)
        m2 = _item("mem_2", "Sarah: I moved to Denver last spring.", tier=0)
        u = _build([composite, m1, m2])

        kept, suppressed = u._suppress_by_provenance([composite, m1, m2])

        self.assertEqual([k["id"] for k in kept], ["ppl_sarah"])
        self.assertEqual(suppressed, {"mem_1", "mem_2"})

    def test_constituent_outranking_absorbs_composite(self):
        """The specific record wins when the question is specific."""
        composite = _item(
            "ppl_sarah", "Sarah — climber, moved to Denver.",
            tier=2, memory_refs=[1],
        )
        m1 = _item("mem_1", "Sarah: I led my first 5.10 today!", tier=0)
        u = _build([composite, m1])

        # m1 ranked first this time.
        kept, suppressed = u._suppress_by_provenance([m1, composite])

        self.assertEqual([k["id"] for k in kept], ["mem_1"])
        self.assertEqual(suppressed, {"ppl_sarah"})

    def test_each_edge_type_fires(self):
        for field, ref in (
            ("memory_refs", 7),
            ("component_ids", "bel_child"),
            ("relations", "bel_child"),
            ("belief_ids", "bel_child"),
        ):
            with self.subTest(field=field):
                parent = _item("bel_parent", "parent belief", **{field: [ref]})
                child_id = "mem_7" if field == "memory_refs" else "bel_child"
                child = _item(child_id, "child item")
                u = _build([parent, child])

                kept, suppressed = u._suppress_by_provenance([parent, child])
                self.assertEqual([k["id"] for k in kept], ["bel_parent"])
                self.assertEqual(suppressed, {child_id})

    def test_unlinked_items_both_survive(self):
        a = _item("a", "wholly unrelated one")
        b = _item("b", "entirely different other")
        u = _build([a, b])

        kept, suppressed = u._suppress_by_provenance([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(suppressed, set())

    def test_edge_to_absent_item_is_ignored(self):
        """A ref to something not in the pool must not suppress anything."""
        parent = _item("bel_parent", "parent", memory_refs=[99])
        other = _item("mem_1", "unrelated memory", tier=0)
        u = _build([parent, other])

        kept, suppressed = u._suppress_by_provenance([parent, other])
        self.assertEqual(len(kept), 2)
        self.assertEqual(suppressed, set())


class TestNormalizeRef(unittest.TestCase):
    """memory_refs holds raw journal ids; the corpus keys memories mem_<id>."""

    def test_accepted_forms_converge(self):
        self.assertEqual(normalize_ref(17), "mem_17")
        self.assertEqual(normalize_ref("17"), "mem_17")
        self.assertEqual(normalize_ref("mem_17"), "mem_17")

    def test_belief_ids_pass_through(self):
        self.assertEqual(normalize_ref("pre_20260515_001"), "pre_20260515_001")

    def test_sentinels_and_empties_are_dropped(self):
        # -1 is the Curator's "no source memory" marker (curator.py:984).
        for value in (-1, "-1", None, "", "   ", True):
            with self.subTest(value=value):
                self.assertIsNone(normalize_ref(value))


class TestDuplicatePurge(unittest.TestCase):
    def test_word_overlap_collapses_restatement(self):
        a = _item("a", "Maria volunteers at a homeless shelter every week")
        b = _item("b", "Maria volunteers at a homeless shelter every weekend")
        u = _build([a, b])

        kept, purged = u._purge_near_duplicates([a, b])
        self.assertEqual([k["id"] for k in kept], ["a"])
        self.assertEqual(purged, {"b"})

    def test_distinct_facts_on_one_topic_survive(self):
        a = _item("a", "Maria donated a car to the shelter")
        b = _item("b", "Maria organized a holiday meal for forty guests")
        u = _build([a, b])

        kept, purged = u._purge_near_duplicates([a, b])
        self.assertEqual(len(kept), 2)
        self.assertEqual(purged, set())


class TestBudgetDoesNotResurrectDropped(unittest.TestCase):
    """Adjacency pulls neighbours by position, so it must respect the
    dedup passes or a suppressed constituent walks straight back in."""

    def test_blocked_ids_stay_out(self):
        anchor = _item("mem_1", "anchor memory", tier=0)
        neighbor = _item("mem_2", "neighbour memory", tier=0)
        u = _build([anchor, neighbor])

        class _LaneStub:
            @staticmethod
            def adjacent_chunks(a, window):
                return [neighbor]

        u.lane_a = _LaneStub()

        without_block = u._fill_budget(
            [anchor], max_items=5, token_budget=None, expand_adjacency=True,
        )
        self.assertIn("mem_2", [i["id"] for i in without_block])

        with_block = u._fill_budget(
            [anchor], max_items=5, token_budget=None, blocked={"mem_2"},
            expand_adjacency=True,
        )
        self.assertEqual([i["id"] for i in with_block], ["mem_1"])


class TestComplementIsAdditive(unittest.TestCase):
    """The spatial lane must only ever GROW the injection.

    If its items competed for the same slots, enabling the spatial lane could
    push a semantic hit out and cost recall — the one regression this pipeline
    cannot accept.
    """

    def test_spatial_items_do_not_displace_semantic_ones(self):
        semantic = [_item(f"a{i}", f"semantic hit number {i}") for i in range(4)]
        spatial = [_item("s1", "lateral association one"),
                   _item("s2", "lateral association two")]
        u = _build(semantic + spatial)

        for item in semantic:
            item["lane"] = "semantic"
        for item in spatial:
            item["lane"] = "spatial"

        # max_items is exactly the semantic count, so any competition for
        # slots would show up as a dropped semantic item.
        selected = u._fill_budget(semantic + spatial, max_items=4, token_budget=None)
        selected_ids = [i["id"] for i in selected]

        for item in semantic:
            self.assertIn(item["id"], selected_ids)
        self.assertIn("s1", selected_ids)
        self.assertIn("s2", selected_ids)
        self.assertEqual(len(selected), 6)

    def test_token_budget_does_not_starve_the_complement(self):
        semantic = [_item(f"a{i}", "semantic " + "word " * 50) for i in range(3)]
        spatial = [_item("s1", "lateral association")]
        for item in semantic:
            item["lane"] = "semantic"
        spatial[0]["lane"] = "spatial"
        u = _build(semantic + spatial)

        selected = u._fill_budget(semantic + spatial, max_items=10, token_budget=60)
        self.assertIn("s1", [i["id"] for i in selected])


class TestStoreIntegrity(unittest.TestCase):
    """Retrieval must never mutate what it reads. A memory stays a
    constituent of every belief citing it, however often it's suppressed."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="helix_unified_test_")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_retrieval_leaves_stores_untouched(self):
        from core.physics_engine import PhysicsEngine
        from memory.memory_manager import MemoryManager
        from memory.belief_store import BeliefStore

        physics = PhysicsEngine(os.path.join(self.tmp, "spatial"))
        memory = MemoryManager(os.path.join(self.tmp, "memory"))
        memory.set_physics(physics)
        beliefs = BeliefStore(os.path.join(self.tmp, "beliefs"))
        beliefs.set_runtime(physics_engine=physics, memory_manager=memory)

        m1 = memory.store(content="Sarah: I led my first 5.10 route today!",
                          memory_type="event", source="pulse_input", pulse_id=1,
                          lagrangian_snapshot={"omega": 0.25, "s_total": 0.6})
        m2 = memory.store(content="Sarah: I moved to Denver last spring.",
                          memory_type="event", source="pulse_input", pulse_id=2)
        beliefs.add_belief("people", "ppl_sarah",
                           "Sarah — climber, moved to Denver, leads 5.10.",
                           confidence=0.95, mass=5.0, memory_refs=[m1, m2],
                           term="Sarah", stability_index=0.8,
                           encoding_lagrangian={"omega": 0.7, "s_total": 0.1})

        unified = UnifiedRetrieval(belief_store=beliefs, memory_manager=memory,
                                   physics_engine=physics)

        before_beliefs = len(beliefs.get_all_beliefs_flat())
        before_memories = sum(1 for i in unified.corpus.all_items() if i["tier"] == 0)

        results = unified.retrieve("Who is Sarah and what does she climb?",
                                   complement_quota=2, max_items=5)
        self.assertTrue(results, "expected at least one retrieved item")
        # The composite outranks its sources here, so they are suppressed...
        self.assertGreater(unified.last_stats["suppressed_provenance"], 0)

        # ...but remain present and fully linked in storage.
        after_beliefs = len(beliefs.get_all_beliefs_flat())
        after_memories = sum(1 for i in unified.corpus.all_items() if i["tier"] == 0)
        self.assertEqual(before_beliefs, after_beliefs)
        self.assertEqual(before_memories, after_memories)

        sarah = beliefs.get_belief("ppl_sarah")
        self.assertEqual(len(sarah.get("memory_refs", [])), 2)
        corpus_sarah = unified.corpus.get("ppl_sarah")
        self.assertEqual(corpus_sarah["stability_index"], 0.8)
        self.assertEqual(corpus_sarah["encoding_lagrangian"]["omega"], 0.7)
        self.assertGreater(unified.corpus.get("mem_%s" % m1)["affective_salience"], 0.0)
        for mid in ("mem_%s" % m1, "mem_%s" % m2):
            self.assertIsNotNone(unified.corpus.get(mid),
                                 "%s must stay independently retrievable" % mid)


def run_unified_retrieval_tests():
    print("Running Unified Retrieval Test Suite...")
    print("=" * 70)

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for case in (
        TestSemanticPrimaryMerge,
        TestAssociativeComplement,
        TestRankFusion,
        TestComplementQuota,
        TestProvenanceSuppression,
        TestNormalizeRef,
        TestDuplicatePurge,
        TestBudgetDoesNotResurrectDropped,
        TestComplementIsAdditive,
        TestStoreIntegrity,
    ):
        suite.addTests(loader.loadTestsFromTestCase(case))

    result = unittest.TextTestRunner(verbosity=2).run(suite)

    print("\n" + "=" * 70)
    print(f"Tests run: {result.testsRun}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print(f"Success: {result.wasSuccessful()}")

    return result.wasSuccessful()


if __name__ == "__main__":
    sys.exit(0 if run_unified_retrieval_tests() else 1)
