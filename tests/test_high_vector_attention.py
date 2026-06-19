import os
import sys
import unittest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.high_vector_attention import HighVectorAttention

class MockProjection:
    def project(self, emb):
        return np.ones(8, dtype=np.float32) * 0.1

class MockBeliefSpace:
    def __init__(self):
        self.projection = MockProjection()
        self.points = {}

    def get_point(self, bid):
        return self.points.get(bid)

    def _compute_structural_mass(self, pt):
        if isinstance(pt, dict):
            return pt.get("importance", 1.0)
        return getattr(pt, "importance", 1.0)

    def _compute_temperature(self, pt):
        if isinstance(pt, dict):
            return pt.get("confidence", 0.5) * 2.0
        return getattr(pt, "confidence", 0.5) * 2.0


class TestHighVectorAttention(unittest.TestCase):
    def setUp(self):
        self.hva = HighVectorAttention(
            num_layers=32,
            num_heads=4,
            embed_dim=384,
            cosine_floor=0.25,
            top_k=5,
            alpha=3.0,
        )
        self.belief_space = MockBeliefSpace()

        # Build mock beliefs
        self.belief_cache = [
            {
                "id": "b1",
                "content": "Semantic match A",
                "category": "premises",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.8,
                "mass": 1.0,
                "delta_omega": 0.0,
            },
            {
                "id": "b2",
                "content": "Semantic match B with high potency",
                "category": "propositions",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.8,
                "mass": 1.0,
                "delta_omega": 0.9, # high potency
            },
            {
                "id": "b3",
                "content": "Cold semantic match",
                "category": "preferences",
                "position_8d": np.ones(8, dtype=np.float32) * 0.5,
                "confidence": 0.1, # cold temp
                "mass": 0.2,
                "delta_omega": 0.0,
            },
            {
                "id": "b4",
                "content": "Unrelated noise belief",
                "category": "knowledge",
                "position_8d": np.ones(8, dtype=np.float32) * 2.0,
                "confidence": 0.5,
                "mass": 0.5,
                "delta_omega": 0.0,
            }
        ]

        # 384D embedding matrix (N, 384)
        # We will make b1 and b2 highly correlated with the query
        # b3 moderately correlated, b4 anti-correlated
        self.query_emb = np.zeros(384, dtype=np.float32)
        self.query_emb[0] = 1.0

        b1_emb = np.zeros(384, dtype=np.float32)
        b1_emb[0] = 0.9
        b1_emb[1] = np.sqrt(1 - 0.9**2)

        b2_emb = np.zeros(384, dtype=np.float32)
        b2_emb[0] = 0.8
        b2_emb[1] = np.sqrt(1 - 0.8**2)

        b3_emb = np.zeros(384, dtype=np.float32)
        b3_emb[0] = 0.3
        b3_emb[1] = np.sqrt(1 - 0.3**2)

        b4_emb = np.zeros(384, dtype=np.float32)
        b4_emb[0] = -0.5  # anti-correlated
        b4_emb[1] = np.sqrt(1 - (-0.5)**2)

        self.belief_emb_matrix = np.vstack([b1_emb, b2_emb, b3_emb, b4_emb])
        self.belief_emb_row_map = {0: 0, 1: 1, 2: 2, 3: 3}

    def test_single_layer_produces_valid_output(self):
        """Output is 384D, has no NaN/Inf."""
        Q = self.query_emb.copy()
        K = self.belief_emb_matrix[:2]
        V = self.belief_emb_matrix[:2]
        mod_signals = {
            'gravity': np.ones(2, dtype=np.float32),
            'potency': np.ones(2, dtype=np.float32),
            'temperature': np.ones(2, dtype=np.float32),
            'mass': np.ones(2, dtype=np.float32),
        }
        Q_next, weights = self.hva._layer_forward(Q, K, V, mod_signals)
        self.assertEqual(Q_next.shape, (384,))
        self.assertFalse(np.isnan(Q_next).any())
        self.assertFalse(np.isinf(Q_next).any())

    def test_32_layers_converge(self):
        """Query doesn't explode or collapse after 32 layers."""
        results = self.hva.forward(
            query_text="test query",
            belief_cache=self.belief_cache,
            belief_emb_matrix=self.belief_emb_matrix,
            belief_emb_row_map=self.belief_emb_row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        self.assertGreater(len(results), 0)
        # Check that top result is valid and has valid scores
        self.assertFalse(np.isnan(results[0]["gravity"]))

    def test_cosine_floor_filters_noise(self):
        """Beliefs below 0.25 cosine are excluded."""
        # b4 has cosine similarity of -0.5 (below 0.25)
        results = self.hva.forward(
            query_text="test query",
            belief_cache=self.belief_cache,
            belief_emb_matrix=self.belief_emb_matrix,
            belief_emb_row_map=self.belief_emb_row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        result_ids = [r["id"] for r in results]
        self.assertNotIn("b4", result_ids)
        self.assertIn("b1", result_ids)
        self.assertIn("b2", result_ids)
        self.assertIn("b3", result_ids)

    def test_high_potency_surfaces(self):
        """Belief with high |Δω| ranks higher than semantically-closer low-Δω belief."""
        # b1 has cosine similarity 0.9, delta_omega 0.0
        # b2 has cosine similarity 0.8, delta_omega 0.9
        results = self.hva.forward(
            query_text="test query",
            belief_cache=self.belief_cache,
            belief_emb_matrix=self.belief_emb_matrix,
            belief_emb_row_map=self.belief_emb_row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        # b2 should rank higher than b1 due to potency amplification and head weight contribution
        self.assertEqual(results[0]["id"], "b2")

    def test_temporal_head_prefers_recent(self):
        """Hot (recent) beliefs ranked above cold ones with equal semantic score."""
        # Let's create two beliefs with equal semantic scores but different temperatures
        belief_cache = [
            {
                "id": "b_hot",
                "content": "Hot content",
                "category": "premises",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.9, # hot temp
                "mass": 0.5,
                "delta_omega": 0.0,
            },
            {
                "id": "b_cold",
                "content": "Cold content",
                "category": "premises",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.1, # cold temp
                "mass": 0.5,
                "delta_omega": 0.0,
            }
        ]
        b_emb = np.zeros(384, dtype=np.float32)
        b_emb[0] = 0.8
        b_emb[1] = np.sqrt(1 - 0.8**2)

        emb_matrix = np.vstack([b_emb, b_emb])
        row_map = {0: 0, 1: 1}

        results = self.hva.forward(
            query_text="test query",
            belief_cache=belief_cache,
            belief_emb_matrix=emb_matrix,
            belief_emb_row_map=row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        self.assertEqual(results[0]["id"], "b_hot")

    def test_trust_head_prefers_massive(self):
        """High-mass beliefs ranked above low-mass ones with equal semantic score."""
        belief_cache = [
            {
                "id": "b_massive",
                "content": "Massive content",
                "category": "premises",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.5,
                "mass": 2.0, # massive
                "delta_omega": 0.0,
            },
            {
                "id": "b_light",
                "content": "Light content",
                "category": "premises",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.5,
                "mass": 0.1, # light
                "delta_omega": 0.0,
            }
        ]
        b_emb = np.zeros(384, dtype=np.float32)
        b_emb[0] = 0.8
        b_emb[1] = np.sqrt(1 - 0.8**2)

        emb_matrix = np.vstack([b_emb, b_emb])
        row_map = {0: 0, 1: 1}

        results = self.hva.forward(
            query_text="test query",
            belief_cache=belief_cache,
            belief_emb_matrix=emb_matrix,
            belief_emb_row_map=row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        self.assertEqual(results[0]["id"], "b_massive")

    def test_blacklist_exclusion(self):
        """Excluded beliefs never appear in results."""
        results = self.hva.forward(
            query_text="test query",
            belief_cache=self.belief_cache,
            belief_emb_matrix=self.belief_emb_matrix,
            belief_emb_row_map=self.belief_emb_row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude={"Semantic match A"},
        )
        result_ids = [r["id"] for r in results]
        self.assertNotIn("b1", result_ids)

    def test_empty_input_returns_empty(self):
        """Graceful handling of empty/null inputs."""
        results = self.hva.forward(
            query_text="",
            belief_cache=[],
            belief_emb_matrix=None,
            belief_emb_row_map={},
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        self.assertEqual(results, [])

    def test_uniform_fallback(self):
        """When all scores are zero, returns uniform distribution."""
        # Test case: weights are zero or sum to 0
        w = np.zeros(5, dtype=np.float32)
        norm_w = self.hva._normalize(w)
        self.assertTrue(np.allclose(norm_w, 0.2))

    def test_residual_connection_preserves_query(self):
        """After 32 layers, output still correlates with input query."""
        # Running the full loop starting from Q = query_emb.
        # We want to check that Q_next still correlates positively with Q.
        Q = self.query_emb.copy()
        K = self.belief_emb_matrix[:3]
        V = self.belief_emb_matrix[:3]
        mod_signals = {
            'gravity': np.ones(3, dtype=np.float32),
            'potency': np.ones(3, dtype=np.float32),
            'temperature': np.ones(3, dtype=np.float32),
            'mass': np.ones(3, dtype=np.float32),
        }
        for _ in range(32):
            Q, _ = self.hva._layer_forward(Q, K, V, mod_signals)
        # Cosine similarity with original query should be positive
        cos = np.dot(Q, self.query_emb) / (np.linalg.norm(Q) * np.linalg.norm(self.query_emb))
        self.assertGreater(cos, 0.0)

    def test_quasi_related_surfacing(self):
        """Low-cosine but high-Δω belief surfaces through layer refinement."""
        # Belief with low-cosine similarity (0.3) but very high delta_omega (100.0)
        # We want to see if it is surfaced relative to its initial semantic score.
        belief_cache = [
            {
                "id": "b_high_potency_low_cosine",
                "content": "Low cosine high delta_omega",
                "category": "premises",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.5,
                "mass": 1.0,
                "delta_omega": 100.0,
            },
            {
                "id": "b_high_cosine_low_potency",
                "content": "High cosine low delta_omega",
                "category": "premises",
                "position_8d": np.ones(8, dtype=np.float32) * 0.1,
                "confidence": 0.5,
                "mass": 1.0,
                "delta_omega": 0.0,
            }
        ]

        b1_emb = np.zeros(384, dtype=np.float32)
        b1_emb[0] = 0.3 # low cosine
        b1_emb[1] = np.sqrt(1 - 0.3**2)

        b2_emb = np.zeros(384, dtype=np.float32)
        b2_emb[0] = 0.4 # higher cosine
        b2_emb[1] = np.sqrt(1 - 0.4**2)

        emb_matrix = np.vstack([b1_emb, b2_emb])
        row_map = {0: 0, 1: 1}

        results = self.hva.forward(
            query_text="test query",
            belief_cache=belief_cache,
            belief_emb_matrix=emb_matrix,
            belief_emb_row_map=row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        # The low cosine but extremely high potency belief should rank #1
        self.assertEqual(results[0]["id"], "b_high_potency_low_cosine")

    def test_head_weight_diagnostics(self):
        """Per-head weight breakdown is returned correctly."""
        results = self.hva.forward(
            query_text="test query",
            belief_cache=self.belief_cache,
            belief_emb_matrix=self.belief_emb_matrix,
            belief_emb_row_map=self.belief_emb_row_map,
            belief_space=self.belief_space,
            query_embedding=self.query_emb,
            exclude=set(),
        )
        first_res = results[0]
        self.assertIn("head_weights", first_res)
        self.assertIn("semantic", first_res["head_weights"])
        self.assertIn("potency", first_res["head_weights"])
        self.assertIn("temporal", first_res["head_weights"])
        self.assertIn("trust", first_res["head_weights"])
        # sum of weights for any head across all candidates should sum to 1.0
        total_semantic = sum(r["head_weights"]["semantic"] for r in results)
        self.assertAlmostEqual(total_semantic, 1.0, places=4)
        total_gravity = sum(r["gravity"] for r in results)
        self.assertAlmostEqual(total_gravity, 1.0, places=4)


if __name__ == "__main__":
    unittest.main()
