import sys
from pathlib import Path
import logging
import numpy as np
import json
import sqlite3

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("helix.manifold.populate")

# Setup paths
base_dir = Path(__file__).resolve().parent.parent.parent
sys.path.append(str(base_dir))

from brain.manifold.projector import ManifoldProjector

def get_all_chroma_embeddings():
    """Extract embeddings from both shadow and root chroma databases using chromadb client."""
    import chromadb
    embeddings = []
    ids = []
    
    paths = [
        base_dir / "chroma_db",
        base_dir / "chroma_shadow"
    ]
    
    for db_path in paths:
        if not db_path.exists():
            continue
            
        try:
            client = chromadb.PersistentClient(path=str(db_path))
            for c_name in client.list_collections():
                col = client.get_collection(c_name.name if hasattr(c_name, 'name') else c_name)
                # Fetch all in chunks to avoid memory explosion if very large
                data = col.get(include=["embeddings"])
                if data and data.get("embeddings") is not None:
                    embs = data["embeddings"]
                    doc_ids = data["ids"]
                    for d_id, e in zip(doc_ids, embs):
                        embs_arr = np.array(e, dtype=np.float32)
                        if len(embs_arr) == 384:
                            embeddings.append(embs_arr)
                            ids.append(d_id)
        except Exception as e:
            logger.error(f"Error querying {db_path}: {e}")
            
    return ids, np.array(embeddings)


def main():
    logger.info("Starting Cognitive Manifold population script...")
    
    # 1. Get all 384D embeddings available
    logger.info("Extracting embeddings from ChromaDB storage...")
    ids, embeddings = get_all_chroma_embeddings()
    logger.info(f"Loaded {len(embeddings)} vectors of dimension {embeddings.shape[1] if len(embeddings) > 0 else 0}")
    
    if len(embeddings) < 8:
        logger.error("Not enough embeddings to fit PCA(8).")
        return
        
    manifold_dir = base_dir / "brain" / "manifold"
    projector = ManifoldProjector(manifold_dir)
    
    # 2. Fit PCA
    projector.fit(embeddings)
    
    # 3. Project all vectors
    logger.info("Projecting all embeddings to 8D...")
    projected = projector.project(embeddings)
    
    # 4. Map back to ID
    projected_map = {doc_id: list(float(v) for v in p) for doc_id, p in zip(ids, projected)}
    
    # 5. Update SQLite memories table with 8D positions
    logger.info("Updating SQLite memories with 8D positions...")
    memory_db_path = base_dir / "memory.db"
    
    if memory_db_path.exists():
        conn = sqlite3.connect(str(memory_db_path))
        cur = conn.cursor()
        
        updates = 0
        for doc_id, p in projected_map.items():
            if str(doc_id).startswith("mem_"):
                try:
                    mem_id = int(str(doc_id).replace("mem_", ""))
                    # The pos_0 .. pos_7 columns exist according to our verification
                    cur.execute(
                        "UPDATE memories SET pos_0=?, pos_1=?, pos_2=?, pos_3=?, pos_4=?, pos_5=?, pos_6=?, pos_7=? WHERE id=?",
                        (*p, mem_id)
                    )
                    updates += 1
                except ValueError:
                    pass
        conn.commit()
        conn.close()
        logger.info(f"Updated {updates} memory entries in SQLite with 8D positions.")
    
    # 6. Update belief graph 8D positions
    logger.info("Embedding and projecting beliefs...")
    belief_path = base_dir / "tests" / "belief_graph_v5_replayed.json"
    if belief_path.exists():
        import json
        from chromadb.utils import embedding_functions
        
        with open(belief_path, "r") as f:
            data = json.load(f)
            
        embedder = embedding_functions.DefaultEmbeddingFunction()
        
        updates = 0
        batch_size = 100
        beliefs = data.get("beliefs", [])
        
        for i in range(0, len(beliefs), batch_size):
            batch = beliefs[i:i+batch_size]
            texts = [b.get("content", "") for b in batch]
            
            # Embed
            embs_384 = embedder(texts)
            
            # Project to 8D
            embs_8d = projector.project(np.array(embs_384))
            
            # Update beliefs in memory
            for j, b in enumerate(batch):
                b["position_8d"] = [float(x) for x in embs_8d[j]]
                updates += 1
                
        with open(belief_path, "w") as f:
            json.dump(data, f, indent=2)
            
        logger.info(f"Embedded and projected {updates} beliefs successfully.")

    logger.info("Manifold population complete.")

if __name__ == "__main__":
    main()
