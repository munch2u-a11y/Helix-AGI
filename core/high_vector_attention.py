import logging
import numpy as np
from typing import List, Dict, Any, Set

logger = logging.getLogger("helix.high_vector_attention")

class HighVectorAttention:
    def __init__(
        self,
        num_layers: int = 32,
        num_heads: int = 4,
        embed_dim: int = 384,
        cosine_floor: float = 0.25,
        top_k: int = 5,
        alpha: float = 3.0,
    ):
        self.num_layers = num_layers
        self.num_heads = num_heads
        self.embed_dim = embed_dim
        self.cosine_floor = cosine_floor
        self.top_k = top_k
        self.alpha = alpha

    def _layer_norm(self, x: np.ndarray, eps: float = 1e-6) -> np.ndarray:
        mean = x.mean()
        std = x.std()
        return (x - mean) / (std + eps)

    def _normalize(self, weights: np.ndarray) -> np.ndarray:
        total = weights.sum()
        if total < 1e-10:
            return np.ones_like(weights) / len(weights)
        return weights / total

    def _layer_forward(
        self,
        Q: np.ndarray,
        K: np.ndarray,
        V: np.ndarray,
        mod_signals: Dict[str, np.ndarray],
    ) -> tuple:
        """One attention layer with 4 modulation channels.
        
        Q: (384,)    - refined query vector
        K: (M, 384)  - belief/memory key embeddings (L2-normalized)
        V: (M, 384)  - potency-modulated value embeddings
        mod_signals: dict of (M,) arrays
        
        Returns:
            Q_next: (384,) - refined query
            weights: dict of (M,) arrays for each head
        """
        # Shared semantic scores (computed once)
        raw_scores = K @ Q / np.sqrt(self.embed_dim)
        raw_scores = np.maximum(raw_scores, 0) # ReLU gate: ignore anti-correlated

        # 4 modulation channels -> 4 weight distributions
        w_semantic = self._normalize(raw_scores * mod_signals['gravity'])
        w_potency  = self._normalize(raw_scores * mod_signals['potency'])
        w_temporal = self._normalize(raw_scores * mod_signals['temperature'])
        w_trust    = self._normalize(raw_scores * mod_signals['mass'])

        # Each channel aggregates values independently
        c_semantic = w_semantic @ V   # (384,)
        c_potency  = w_potency  @ V   # (384,)
        c_temporal = w_temporal @ V   # (384,)
        c_trust    = w_trust    @ V   # (384,)

        # Average across heads
        context = (c_semantic + c_potency + c_temporal + c_trust) / 4.0

        # Residual connection + LayerNorm
        Q_next = self._layer_norm(Q + context)
        
        weights = {
            'gravity': w_semantic,
            'potency': w_potency,
            'temperature': w_temporal,
            'mass': w_trust,
        }
        return Q_next, weights

    def forward(
        self,
        query_text: str,
        belief_cache: List[Dict[str, Any]],
        belief_emb_matrix: np.ndarray,
        belief_emb_row_map: Dict[int, int],
        belief_space: Any,
        query_embedding: np.ndarray,
        exclude: Set[str],
    ) -> List[Dict[str, Any]]:
        """Run the full attention stack over candidate beliefs."""
        if not belief_cache or belief_emb_matrix is None or len(belief_emb_matrix) == 0:
            return []

        # 1. Build candidate pool using cosine floor filter and exclude list
        candidates = []
        for cache_idx, b in enumerate(belief_cache):
            content = b.get("content", "")
            if not content or content in exclude:
                continue

            row_idx = belief_emb_row_map.get(cache_idx)
            if row_idx is None or row_idx >= len(belief_emb_matrix):
                continue

            e_i = belief_emb_matrix[row_idx]
            cos_sim = float(np.dot(e_i, query_embedding))
            if cos_sim >= self.cosine_floor:
                candidates.append((cache_idx, b, e_i, cos_sim))

        if not candidates:
            return []

        # 2. Compute modulation signals for all candidates
        # Project query embedding to 8D position
        try:
            query_pos = belief_space.projection.project(query_embedding)
        except Exception as e:
            logger.debug(f"Query 8D projection failed: {e}")
            query_pos = np.zeros(8, dtype=np.float32)

        K_list = []
        V_list = []
        gravity_list = []
        potency_list = []
        temp_list = []
        mass_list = []

        for cache_idx, b, e_i, cos_sim in candidates:
            bid = b.get("id")
            pt = belief_space.get_point(bid) if bid else None
            if pt:
                mass = belief_space._compute_structural_mass(pt)
                temperature = belief_space._compute_temperature(pt)
            else:
                fallback_pt = {
                    "type": "belief",
                    "confidence": b.get("confidence", 0.5),
                    "importance": b.get("mass", 1.0),
                    "access_count": b.get("access_count", 0),
                    "relations_count": b.get("relations_count", 0),
                    "encoding_omega": b.get("encoding_omega", 0.5),
                    "stability_index": b.get("stability_index", 0.5),
                    "creation_pulse": b.get("creation_pulse", 0),
                    "last_accessed_pulse": b.get("last_accessed_pulse", 0),
                }
                mass = belief_space._compute_structural_mass(fallback_pt)
                temperature = belief_space._compute_temperature(fallback_pt)

            dist_sq = float(np.sum((b["position_8d"] - query_pos) ** 2))
            gravity = (temperature * mass) / (dist_sq + 1e-4)
            potency = abs(b.get("delta_omega", 0.0))

            # Value vector potency amplification: V_i = e_i * (1 + alpha * |delta_omega_i|)
            V_i = e_i * (1.0 + self.alpha * potency)

            K_list.append(e_i)
            V_list.append(V_i)
            gravity_list.append(gravity)
            potency_list.append(potency)
            temp_list.append(temperature)
            mass_list.append(mass)

        K = np.array(K_list, dtype=np.float32)  # (M, 384)
        V = np.array(V_list, dtype=np.float32)  # (M, 384)

        mod_signals = {
            'gravity': np.array(gravity_list, dtype=np.float32),
            'potency': np.array(potency_list, dtype=np.float32),
            'temperature': np.array(temp_list, dtype=np.float32),
            'mass': np.array(mass_list, dtype=np.float32),
        }

        # 3. Run L layers of attention forward pass
        Q = query_embedding.copy()
        last_weights = None

        for layer in range(self.num_layers):
            Q, last_weights = self._layer_forward(Q, K, V, mod_signals)

        # 4. Final scoring using the last layer's weights
        scored_candidates = []
        for idx, (cache_idx, b, e_i, cos_sim) in enumerate(candidates):
            w_semantic = float(last_weights['gravity'][idx])
            w_potency = float(last_weights['potency'][idx])
            w_temporal = float(last_weights['temperature'][idx])
            w_trust = float(last_weights['mass'][idx])
            
            # Average weight across all heads
            final_weight = (w_semantic + w_potency + w_temporal + w_trust) / 4.0

            scored_candidates.append({
                "id": b.get("id", ""),
                "content": b.get("content", ""),
                "gravity": final_weight,  # keep key name for preconscious compatibility
                "category": b.get("category", ""),
                "mass": float(mass_list[idx]),
                "position_8d": b.get("position_8d"),
                "attention_score": final_weight,
                "head_weights": {
                    "semantic": w_semantic,
                    "potency": w_potency,
                    "temporal": w_temporal,
                    "trust": w_trust,
                }
            })

        # Sort by final attention score descending
        scored_candidates.sort(key=lambda x: x["gravity"], reverse=True)

        return scored_candidates
