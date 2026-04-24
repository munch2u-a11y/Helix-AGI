"""
Helix 8D Manifold — Nightly Gravitational Convergence Pipeline

This pipeline replaces the flat 'Psych Doctor' overnight script.
Instead of LLM-based abstract reflection, this uses orbital mechanics
and manifold physics to update the cognitive space:

1. PCA Refit: Extracts latest ChromoDB embeddings and recomputes the 8D
   projection matrix, ensuring the space smoothly coordinates as new memories
   accumulate.
2. Mass Recalculation: Updates belief masses based on how many memories orbit them.
   More orbiting episodic memories = higher belief mass.
3. Memory Drift: Unused memories drift outward; used memories drift inward.
4. Singularity Forger: Identifies extremely dense areas (black hole proxies)
   and triggers deep LLM synthesis of a new core axiom.
"""

import logging
import numpy as np
from pathlib import Path
from datetime import datetime

from brain.manifold.projector import ManifoldProjector
from brain.manifold.manifold import CognitiveManifold

logger = logging.getLogger("helix.manifold.convergence")


class ConvergencePipeline:
    def __init__(self, memory, belief_graph, base_dir: Path):
        self.memory = memory
        self.belief_graph = belief_graph
        self.manifold_dir = base_dir / "brain" / "manifold"
        self.projector = ManifoldProjector(self.manifold_dir)
        self.manifold = CognitiveManifold()
        
    def run_nightly_cycle(self) -> dict:
        """Run the full overnight gravitational pipeline."""
        logger.info("Starting Nightly Convergence Pipeline...")
        
        results = {
            "pca_refit": False,
            "reprojected_count": 0,
            "mass_updates": 0,
            "singularities_forged": 0
        }
        
        # 1. PCA Re-fit & Reprojection
        results.update(self._refit_projection())
        
        # 2. Build the current manifold
        beliefs = self.belief_graph.get_all_beliefs() if self.belief_graph else []
        memories = self.memory.get_all_with_positions() if self.memory else []
        self.manifold.rebuild_index(beliefs, memories)
        
        # 3. Mass Recalculation & Orbit Assignment
        mass_updates = self._recalculate_masses()
        results["mass_updates"] = mass_updates
        
        # 4. Singularity Forging (Cluster Collapse screening)
        singularities = self._forge_singularities()
        results["singularities_forged"] = singularities
        
        logger.info(f"Convergence Pipeline complete: {results}")
        return results
        
    def _refit_projection(self) -> dict:
        """Re-fit the PCA matrix and reproject all nodes."""
        from brain.manifold.populate import extract_chroma_embeddings
        import sqlite3
        
        logger.info("Extracting embeddings for PCA re-fit...")
        db_path = self.memory.base_dir / "chroma_db"
        embeddings_list = []
        
        # We need numpy arrays to re-fit
        if db_path.exists():
            import chromadb
            client = chromadb.PersistentClient(path=str(db_path))
            for collection_name in client.list_collections():
                col = client.get_collection(collection_name.name)
                data = col.get(include=["embeddings"])
                if data["embeddings"]:
                    embeddings_list.extend(data["embeddings"])
                    
        shadow_path = self.memory.base_dir / "chroma_shadow"
        if shadow_path.exists():
            import chromadb
            client = chromadb.PersistentClient(path=str(shadow_path))
            for collection_name in client.list_collections():
                col = client.get_collection(collection_name.name)
                data = col.get(include=["embeddings"])
                if data["embeddings"]:
                    embeddings_list.extend(data["embeddings"])

        if len(embeddings_list) < 100:
            logger.warning("Not enough embeddings to re-fit PCA meaningfully.")
            return {"pca_refit": False, "reprojected_count": 0}
            
        logger.info(f"Re-fitting 8D projection matrix from {len(embeddings_list)} embeddings...")
        X = np.array(embeddings_list)
        self.projector.fit(X)
        self.projector.save()
        
        # Re-project memory SQLite db
        logger.info("Reprojecting memories...")
        reprojected = 0
        conn = sqlite3.connect(str(self.memory.db_path))
        try:
            conn.row_factory = sqlite3.Row
            cur = conn.cursor()
            cur.execute("SELECT id, content FROM memories")
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            embedder = DefaultEmbeddingFunction()
            
            # Batch process
            batch_size = 500
            rows = cur.fetchall()
            for i in range(0, len(rows), batch_size):
                batch = rows[i:i+batch_size]
                contents = [r['content'] for r in batch]
                if not contents: continue
                embs = embedder(contents)
                pos = self.projector.project(np.array(embs))
                
                updates = []
                for idx, r in enumerate(batch):
                    p = pos[idx].tolist()
                    updates.append((p[0], p[1], p[2], p[3], p[4], p[5], p[6], p[7], r['id']))
                    reprojected += 1
                
                cur.executemany('''
                    UPDATE memories 
                    SET pos_0=?, pos_1=?, pos_2=?, pos_3=?, pos_4=?, pos_5=?, pos_6=?, pos_7=?
                    WHERE id=?
                ''', updates)
            conn.commit()
        except Exception as e:
            logger.error(f"Memory reprojection failed: {e}")
        finally:
            conn.close()
            
        # Re-project beliefs
        logger.info("Reprojecting belief graph...")
        # Since belief graph loads embeddings natively via embedder when we pass content,
        # we can just update pos_8d where needed, or let dynamic loading do it.
        # But we want to persist it.
        if self.belief_graph:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            embedder = DefaultEmbeddingFunction()
            for b_id, b_data in self.belief_graph._graph.get("beliefs", {}).items():
                content = b_data.get("content", "")
                if content:
                    emb = embedder([content])[0]
                    p = self.projector.project(np.array(emb)).tolist()
                    b_data["pos_8d"] = p
                    reprojected += 1
            self.belief_graph._save()
            
        return {"pca_refit": True, "reprojected_count": reprojected}

    def _recalculate_masses(self) -> int:
        """Update belief mass based on how many memories orbit it."""
        from brain.manifold.geodesic import geodesic_distance_vectorized
        
        # Get all memories and all beliefs
        mem_nodes = [n for n in self.manifold.nodes if n.node_type == "memory"]
        belief_nodes = [n for n in self.manifold.nodes if n.node_type == "belief"]
        
        if not mem_nodes or not belief_nodes:
            return 0
            
        # Count orbiting memories (distance < 5.0)
        updates = 0
        for b_node in belief_nodes:
            if b_node.pos is None: continue
            
            b_pos = b_node.pos.reshape(1, -1)
            orbit_count = 0
            for m_node in mem_nodes:
                if m_node.pos is None: continue
                # simple euclidean check to save time before exact geodesic
                if np.linalg.norm(b_pos[0] - m_node.pos) < 5.0:
                    orbit_count += 1
            
            # Update mass based on orbit (base mass 1.0 + orbit log scaling)
            new_mass = 1.0 + np.log1p(orbit_count)
            
            bel_id = b_node.id
            if bel_id.startswith("b_"):
                b_data = self.belief_graph.get_belief(bel_id)
                if b_data:
                    # Apply the mass update to confidence or a new mass field
                    b_data["manifold_mass"] = float(new_mass)
                    updates += 1
                    
        if updates > 0:
            self.belief_graph._save()
            
        return updates

    def _forge_singularities(self) -> int:
        """Identify excessively dense belief clusters and merge/collapse."""
        # TODO: Implement full LLM synthesis for clusters
        # For now, it just screens.
        return 0

