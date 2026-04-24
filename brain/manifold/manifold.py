import numpy as np
import logging
from typing import Optional, List, Dict, Any

from .geodesic import compute_curvature_field, geodesic_distance_vectorized

logger = logging.getLogger("helix.brain.manifold")

class ManifoldNode:
    """Wrapper for either a belief or a memory in the 8D manifold."""
    def __init__(self, node_id: str, node_type: str, content: str, pos: np.ndarray, meta: dict = None):
        if pos is None or len(pos) != 8:
            # Fallback to origin if no valid position
            pos = np.zeros(8)
            
        self.id = node_id
        self.node_type = node_type # 'belief' or 'memory'
        self.content = content
        self.pos = pos
        self.meta = meta or {}

class CognitiveManifold:
    """
    The Unified Cognitive Manifold.
    Maintains the 8D non-Euclidean spatial index of beliefs and memories.
    """
    def __init__(self):
        self.nodes: List[ManifoldNode] = []
        self._positions_cache = None
        
        # Volatile nodes (reset every heartbeat)
        self.volatile_nodes: List[ManifoldNode] = []
        
        # Curvature fields
        self.curvature_data = {}
        
    def rebuild_index(self, beliefs: list[dict], memories: list[dict]):
        """Rebuild the spatial index from beliefs and memories."""
        self.nodes.clear()
        
        for b in beliefs:
            meta = {
                "mass": b.get("mass", 0.1), # Set dynamically later
                "verifications": b.get("verifications", 1.0),
                "stability": b.get("stability_index", 0.5)
            }
            # Handle list to np.array conversion
            pos = b.get("position_8d")
            pos_arr = np.array(pos) if pos is not None else np.zeros(8)
            self.nodes.append(ManifoldNode(b["id"], "belief", b.get("content", ""), pos_arr, meta))
            
        for m in memories:
            meta = {
                "importance": m.get("importance", 0.5),
                "created_at": m.get("created_at", "")
            }
            # For memories, pos might come from pos_0..pos_7
            pos = m.get("position_8d")
            pos_arr = np.array(pos) if pos is not None else np.zeros(8)
            self.nodes.append(ManifoldNode(f"mem_{m['id']}", "memory", m.get("content", ""), pos_arr, meta))
            
        self._update_combined_nodes()
        
        # Precompute the curvature field based ONLY on beliefs and volatile nodes
        self._recompute_curvature()
        logger.info(f"Manifold rebuilt with {len(self.nodes)} core nodes")
        
    def add_volatile_node(self, node_id: str, node_type: str, content: str, pos: np.ndarray, mass: float = 10.0):
        """Inject a high-mass temporary node (like live sensory streams)."""
        meta = {"mass": mass, "volatile": True}
        self.volatile_nodes.append(ManifoldNode(node_id, node_type, content, pos, meta))
        self._update_combined_nodes()
        self._recompute_curvature()
        
    def clear_volatile_nodes(self):
        """Clear all temporary nodes."""
        if self.volatile_nodes:
            self.volatile_nodes.clear()
            self._update_combined_nodes()
            self._recompute_curvature()
            
    def _update_combined_nodes(self):
        """Update the internal array of all active nodes (permanent + volatile)."""
        combined = self.nodes + self.volatile_nodes
        if combined:
            self._positions_cache = np.array([n.pos for n in combined])
        else:
            self._positions_cache = None
            
    def _recompute_curvature(self):
        """Recompute gravitational fields considering permanent and volatile nodes."""
        # Convert our nodes back to dicts for compute_curvature_field, which expects dicts
        # BUT wait, compute_curvature_field expects dicts with "position_8d" and "mass"
        # We'll just build a lightweight representation.
        gravity_wells = []
        for n in self.nodes:
            if n.node_type == "belief":
                gravity_wells.append({
                    "id": n.id,
                    "position_8d": n.pos.tolist(),
                    "mass": n.meta.get("mass", 0.1)
                })
        for n in self.volatile_nodes:
            gravity_wells.append({
                "id": n.id,
                "position_8d": n.pos.tolist(),
                "mass": n.meta.get("mass", 10.0)
            })
            
        self.curvature_data = compute_curvature_field(gravity_wells)
        
    def get_nearest(self, position_8d: np.ndarray, n: int = 15, node_types: list = None) -> List[tuple[ManifoldNode, float]]:
        """
        Unified retrieval: Returns mixed beliefs and memories by geodesic distance.
        """
        if len(self.nodes) == 0:
            return []
            
        if self._positions_cache is None or len(self._positions_cache) != len(self.nodes):
            self._positions_cache = np.array([n.pos for n in self.nodes])
            
        types_set = set(node_types) if node_types else None
        
        # Euclidean top-N (we query a bit more to re-rank with geodesic)
        query_n = min(n * 5, len(self.nodes))
        euc_dists = np.linalg.norm(self._positions_cache - position_8d, axis=1)
        
        # Get indices of top query_n candidates
        candidate_indices = np.argsort(euc_dists)[:query_n]
        
        # Filter by type before computing geodesic (saves time)
        filtered_indices = []
        for idx in candidate_indices:
            if types_set is None or self.nodes[idx].node_type in types_set:
                filtered_indices.append(idx)
                
        if not filtered_indices:
            return []
            
        filtered_indices = np.array(filtered_indices)
        candidate_positions = self._positions_cache[filtered_indices]
        
        # Compute Geodesic
        if "heavy_positions" in self.curvature_data:
            geo_dists = geodesic_distance_vectorized(
                position_8d, 
                candidate_positions,
                self.curvature_data["heavy_positions"],
                self.curvature_data["heavy_curvatures"],
                self.curvature_data["norm_factor"]
            )
        else:
            # Fallback to euclidean if curvature not ready
            geo_dists = np.linalg.norm(candidate_positions - position_8d, axis=1)
            
        # Sort by Geodesic
        geo_order = np.argsort(geo_dists)
        
        results = []
        combined = self.nodes + self.volatile_nodes
        for i in range(min(n, len(geo_order))):
            orig_idx = filtered_indices[geo_order[i]]
            results.append((combined[orig_idx], float(geo_dists[geo_order[i]])))
            
        return results
