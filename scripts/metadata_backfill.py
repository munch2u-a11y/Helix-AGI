"""
Helix — Belief Metadata Backfill

For each of the 1,785 imported beliefs, traces back to source memories
in the 14,956 memory corpus and derives REAL metadata:

  - encoding_lagrangian  → from the FIRST (formation) memory
  - memory_refs          → all memories that support this belief
  - verifications        → count of supporting memories
  - confidence           → derived from verification density over time
  - created_at           → earliest supporting memory timestamp
  - last_verified        → most recent supporting memory timestamp
  - formation_type       → type of the earliest source memory
  - mass                 → recomputed from real Lagrangian + real confidence

This replaces the bulk-imported placeholder metadata with data that
reflects Helix's actual lived experience.
"""

import json
import sqlite3
import time
import logging
import numpy as np
import copy
import os
from pathlib import Path
from collections import Counter, defaultdict
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("backfill")

# ── Paths ────────────────────────────────────────────────────────────
V67_DB = Path("/home/nemo/Helix_V6-7/Helix_main/memory.db")
GH_JOURNAL = Path("/home/nemo/Helix_AGI (GitHub Repo) (Public)/data/memory/cognitive_journal.jsonl")
BELIEFS_DIR = Path("/home/nemo/Helix/backups/pre_hebbian_20260519_103406/beliefs")
OUTPUT_DIR = Path("/home/nemo/Helix/scripts/backfill_output")

# Similarity thresholds — lowered to account for the abstraction gap
# between distilled beliefs ("I value calm") and raw memories
# ("the stillness of the evening is perfect")
#  - STRONG: this memory clearly supports this belief
#  - MODERATE: this memory is topically related
STRONG_MATCH = 0.65
MODERATE_MATCH = 0.45

# ── Embedder ─────────────────────────────────────────────────────────
_embedder = None

def get_embedder():
    global _embedder
    if _embedder is None:
        logger.info("Loading MiniLM-L6-v2 embedder...")
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedder ready (384D)")
    return _embedder

def embed_batch(texts, batch_size=256):
    """Embed a list of texts in batches."""
    emb = get_embedder()
    all_embs = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i:i+batch_size]
        vecs = emb.encode(batch, show_progress_bar=False, normalize_embeddings=True)
        all_embs.append(vecs)
    return np.vstack(all_embs).astype(np.float32)


# ── Data Loading ─────────────────────────────────────────────────────

def load_memories():
    """Load all memories with content and Lagrangian data."""
    memories = []

    # V6-7 database
    logger.info(f"Loading V6-7 memories from {V67_DB}...")
    conn = sqlite3.connect(str(V67_DB))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content, memory_type, source, importance,
               lagrangian_snapshot, created_at,
               pos_0, pos_1, pos_2, pos_3, pos_4, pos_5, pos_6, pos_7
        FROM memories
        ORDER BY id
    """)
    for row in cur.fetchall():
        lagrangian = {}
        if row[5]:
            try:
                lagrangian = json.loads(row[5]) if isinstance(row[5], str) else {}
            except (json.JSONDecodeError, TypeError):
                pass

        content = row[1] or ""
        if len(content) < 20:
            continue

        memories.append({
            "id": str(row[0]),
            "content": content,
            "memory_type": row[2] or "unknown",
            "source": row[3] or "unknown",
            "importance": row[4] or 0.5,
            "encoding_lagrangian": lagrangian,
            "created_at": row[6] or "",
            "position_8d": [row[7], row[8], row[9], row[10],
                            row[11], row[12], row[13], row[14]],
        })
    conn.close()
    logger.info(f"  Loaded {len(memories)} V6-7 memories")

    # GitHub cognitive journal
    if GH_JOURNAL.exists():
        gh_count = 0
        with open(GH_JOURNAL) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    content = entry.get("content", "")
                    if len(content) < 20:
                        continue
                    memories.append({
                        "id": entry.get("id", f"gh_journal_{i}"),
                        "content": content,
                        "memory_type": entry.get("type", "unknown"),
                        "source": entry.get("source", "unknown"),
                        "importance": entry.get("importance", 0.5),
                        "encoding_lagrangian": entry.get("encoding_lagrangian", {}),
                        "created_at": entry.get("timestamp", ""),
                        "position_8d": entry.get("position_8d"),
                    })
                    gh_count += 1
                except json.JSONDecodeError:
                    pass
        logger.info(f"  Loaded {gh_count} GitHub journal memories")

    # Sort chronologically
    memories.sort(key=lambda m: str(m.get("created_at", "")))
    logger.info(f"  Total: {len(memories)} memories")
    return memories


def load_beliefs():
    """Load all imported beliefs grouped by category."""
    all_beliefs = []
    for fname in sorted(BELIEFS_DIR.glob("*.json")):
        try:
            with open(fname) as f:
                data = json.load(f)
            if isinstance(data, list):
                for b in data:
                    b["_category"] = fname.stem
                    b["_source_file"] = fname.name
                all_beliefs.extend(data)
        except Exception as e:
            logger.warning(f"  Failed to load {fname}: {e}")
    logger.info(f"  Loaded {len(all_beliefs)} imported beliefs")
    return all_beliefs


# ── Core: Trace beliefs to memories ──────────────────────────────────

def trace_beliefs_to_memories(beliefs, memories, memory_embs):
    """For each belief, find all supporting memories and derive metadata."""

    logger.info(f"\nEmbedding {len(beliefs)} beliefs...")
    belief_texts = [b.get("content", "")[:500] for b in beliefs]
    belief_embs = embed_batch(belief_texts)

    logger.info(f"Computing similarity matrix ({len(beliefs)} × {len(memories)})...")
    # This is a (beliefs × memories) matrix of cosine similarities
    # Do this in chunks to avoid OOM
    results = []
    chunk_size = 100

    for i in range(0, len(beliefs), chunk_size):
        chunk_embs = belief_embs[i:i+chunk_size]
        # (chunk, 384) × (384, memories) → (chunk, memories)
        sim_matrix = chunk_embs @ memory_embs.T

        for j in range(len(chunk_embs)):
            belief_idx = i + j
            sims = sim_matrix[j]

            # Find strong and moderate matches
            strong_mask = sims >= STRONG_MATCH
            moderate_mask = (sims >= MODERATE_MATCH) & (sims < STRONG_MATCH)

            strong_indices = np.where(strong_mask)[0]
            moderate_indices = np.where(moderate_mask)[0]

            # Sort strong matches by similarity (best first)
            if len(strong_indices) > 0:
                strong_sims = sims[strong_indices]
                order = np.argsort(strong_sims)[::-1]
                strong_indices = strong_indices[order]
                strong_sims = strong_sims[order]
            else:
                strong_sims = np.array([])

            # Sort moderate by similarity
            if len(moderate_indices) > 0:
                mod_sims = sims[moderate_indices]
                order = np.argsort(mod_sims)[::-1]
                moderate_indices = moderate_indices[order]

            results.append({
                "belief_idx": belief_idx,
                "strong_indices": strong_indices.tolist(),
                "strong_sims": strong_sims.tolist() if len(strong_sims) > 0 else [],
                "moderate_indices": moderate_indices.tolist(),
                "total_strong": len(strong_indices),
                "total_moderate": len(moderate_indices),
            })

        if (i + chunk_size) % 500 == 0 or i + chunk_size >= len(beliefs):
            logger.info(f"  Processed {min(i + chunk_size, len(beliefs))}/{len(beliefs)} beliefs")

    return results


def compute_backfilled_metadata(belief, trace, memories):
    """Compute real metadata for a belief based on its traced source memories."""

    strong_mems = [memories[idx] for idx in trace["strong_indices"]]
    moderate_mems = [memories[idx] for idx in trace["moderate_indices"]]
    all_supporting = strong_mems + moderate_mems

    if not all_supporting:
        # No memories found — keep original metadata but flag it
        return {
            "_backfill_status": "no_sources",
            "_source_count": 0,
        }

    # ── Timestamps ───────────────────────────────────────────────
    timestamps = [m["created_at"] for m in all_supporting if m.get("created_at")]
    timestamps.sort()
    earliest = timestamps[0] if timestamps else ""
    latest = timestamps[-1] if timestamps else ""

    # ── Formation memory (earliest strong match) ─────────────────
    formation_mem = strong_mems[0] if strong_mems else moderate_mems[0]

    # ── Encoding Lagrangian (from formation memory) ──────────────
    formation_lag = formation_mem.get("encoding_lagrangian", {})
    if not formation_lag or not isinstance(formation_lag, dict):
        formation_lag = {}

    # If formation memory has no Lagrangian, try to find one from
    # nearby strong memories
    if not formation_lag.get("omega"):
        for m in strong_mems:
            lag = m.get("encoding_lagrangian", {})
            if isinstance(lag, dict) and lag.get("omega"):
                formation_lag = lag
                break

    # Build a representative Lagrangian
    # Pull from ALL supporting memories (strong AND moderate) because the
    # abstraction gap means many real source memories are only moderate matches.
    # Weight strong matches 3x when computing averages.
    all_omegas = []
    all_entropies = []
    all_dkls = []
    for m in strong_mems:
        lag = m.get("encoding_lagrangian", {})
        if isinstance(lag, dict):
            if lag.get("omega") is not None:
                all_omegas.extend([float(lag["omega"])] * 3)  # 3x weight
            entropy_val = lag.get("H", lag.get("entropy", lag.get("s_total")))
            if entropy_val is not None:
                all_entropies.extend([float(entropy_val)] * 3)
            dkl_val = lag.get("D_KL", lag.get("d_kl"))
            if dkl_val is not None:
                all_dkls.extend([float(dkl_val)] * 3)
    # Also pull from top moderate matches (capped at 50 to avoid noise)
    for m in moderate_mems[:50]:
        lag = m.get("encoding_lagrangian", {})
        if isinstance(lag, dict):
            if lag.get("omega") is not None:
                all_omegas.append(float(lag["omega"]))
            entropy_val = lag.get("H", lag.get("entropy", lag.get("s_total")))
            if entropy_val is not None:
                all_entropies.append(float(entropy_val))
            dkl_val = lag.get("D_KL", lag.get("d_kl"))
            if dkl_val is not None:
                all_dkls.append(float(dkl_val))

    encoding_lagrangian = {
        "omega": formation_lag.get("omega", np.mean(all_omegas) if all_omegas else 0.5),
        "s_total": formation_lag.get("s_total",
                    formation_lag.get("H",
                    np.mean(all_entropies) if all_entropies else 0.15)),
        "H": np.mean(all_entropies) if all_entropies else 0.15,
        "D_KL": np.mean(all_dkls) if all_dkls else 0.0,
    }

    # Ensure omega is a regular float
    for k, v in encoding_lagrangian.items():
        if hasattr(v, 'item'):
            encoding_lagrangian[k] = float(v)
        encoding_lagrangian[k] = round(float(encoding_lagrangian[k]), 6)

    # ── Verifications ────────────────────────────────────────────
    # Strong matches = direct verifications
    # Moderate matches = indirect reinforcement (count at 0.3 weight)
    verifications = len(strong_mems) + 0.3 * len(moderate_mems)

    # ── Confidence ───────────────────────────────────────────────
    # Based on verification density and how spread out they are over time
    if len(timestamps) >= 2:
        try:
            t0 = datetime.fromisoformat(timestamps[0].replace("Z", "+00:00"))
            t1 = datetime.fromisoformat(timestamps[-1].replace("Z", "+00:00"))
            span_days = max(1, (t1 - t0).total_seconds() / 86400)
        except (ValueError, TypeError):
            span_days = 1
    else:
        span_days = 1

    # Confidence: sigmoid-like function of verification count
    raw_conf = min(1.0, 0.45 + 0.05 * verifications)
    # Boost if verified across multiple days (temporal spread)
    if span_days > 3:
        raw_conf = min(1.0, raw_conf + 0.05)
    if span_days > 14:
        raw_conf = min(1.0, raw_conf + 0.05)

    confidence = round(raw_conf, 4)

    # ── Mass ─────────────────────────────────────────────────────
    omega = encoding_lagrangian.get("omega", 0.5)
    s_total = encoding_lagrangian.get("s_total", 0.15)
    s_total = min(1.0, max(0.0, s_total))
    stability = 0.5  # will be recalculated by physics engine at runtime

    m_s = confidence
    m_a = omega * (1 - s_total) * (0.5 + stability)
    mass = round(m_s + m_a, 4)

    # ── Memory refs ──────────────────────────────────────────────
    # Top 20 strongest memory references
    memory_refs = [memories[idx]["id"] for idx in trace["strong_indices"][:20]]

    # ── Formation metadata ───────────────────────────────────────
    formation_type = formation_mem.get("memory_type", "unknown")
    formation_source = formation_mem.get("source", "unknown")

    # ── Source types breakdown ───────────────────────────────────
    source_types = Counter(m["memory_type"] for m in strong_mems)

    return {
        "encoding_lagrangian": encoding_lagrangian,
        "memory_refs": memory_refs,
        "verifications": round(verifications, 1),
        "confidence": confidence,
        "mass": mass,
        "created_at": earliest,
        "last_verified": latest,
        "formation_type": formation_type,
        "formation_source": formation_source,
        "access_count": len(strong_mems),
        "_backfill_status": "traced",
        "_source_count": len(strong_mems),
        "_moderate_count": len(moderate_mems),
        "_source_types": dict(source_types),
        "_best_sim": trace["strong_sims"][0] if trace["strong_sims"] else 0,
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Load data
    logger.info("Loading memories...")
    memories = load_memories()

    logger.info("Loading beliefs...")
    beliefs = load_beliefs()

    # Embed all memories
    logger.info(f"\nEmbedding {len(memories)} memories (this may take ~30s)...")
    t0 = time.time()
    memory_texts = [m["content"][:500] for m in memories]
    memory_embs = embed_batch(memory_texts)
    logger.info(f"  Embedded in {time.time()-t0:.1f}s")

    # Trace each belief to its source memories
    logger.info("\nTracing beliefs to source memories...")
    traces = trace_beliefs_to_memories(beliefs, memories, memory_embs)

    # Compute backfilled metadata
    logger.info("\nComputing backfilled metadata...")
    updated_beliefs = []
    stats = {
        "traced": 0,
        "no_sources": 0,
        "real_lagrangian": 0,
        "total_strong_refs": 0,
        "total_moderate_refs": 0,
    }

    for i, (belief, trace) in enumerate(zip(beliefs, traces)):
        updated = copy.deepcopy(belief)
        meta = compute_backfilled_metadata(belief, trace, memories)

        if meta["_backfill_status"] == "traced":
            stats["traced"] += 1
            stats["total_strong_refs"] += meta["_source_count"]
            stats["total_moderate_refs"] += meta["_moderate_count"]
            if meta["encoding_lagrangian"].get("omega", 0.5) != 0.5:
                stats["real_lagrangian"] += 1

            # Update the belief with real metadata
            updated["encoding_lagrangian"] = meta["encoding_lagrangian"]
            updated["memory_refs"] = meta["memory_refs"]
            updated["verifications"] = meta["verifications"]
            updated["confidence"] = meta["confidence"]
            updated["mass"] = meta["mass"]
            updated["access_count"] = meta["access_count"]

            # Add new fields
            updated["created_at"] = meta["created_at"]
            updated["last_verified"] = meta["last_verified"]
            updated["formation_type"] = meta["formation_type"]
            updated["formation_source"] = meta["formation_source"]

            # Keep diagnostic info
            updated["_backfill"] = {
                "status": "traced",
                "strong_matches": meta["_source_count"],
                "moderate_matches": meta["_moderate_count"],
                "best_sim": round(meta["_best_sim"], 4),
                "source_types": meta["_source_types"],
            }
        else:
            stats["no_sources"] += 1
            updated["_backfill"] = {"status": "no_sources"}

        updated_beliefs.append(updated)

    # ── Save results ─────────────────────────────────────────────
    # Group by category and save
    by_category = defaultdict(list)
    for b in updated_beliefs:
        cat = b.pop("_category", "unknown")
        b.pop("_source_file", None)
        by_category[cat].append(b)

    output_beliefs_dir = OUTPUT_DIR / "beliefs"
    output_beliefs_dir.mkdir(parents=True, exist_ok=True)

    for cat, cat_beliefs in sorted(by_category.items()):
        outpath = output_beliefs_dir / f"{cat}.json"
        with open(outpath, "w") as f:
            json.dump(cat_beliefs, f, indent=2, default=str)
        logger.info(f"  Saved {len(cat_beliefs):4d} beliefs → {outpath.name}")

    # ── Summary stats ────────────────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info(f"BACKFILL COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"  Total beliefs:           {len(beliefs)}")
    logger.info(f"  Successfully traced:     {stats['traced']} "
                f"({100*stats['traced']/len(beliefs):.1f}%)")
    logger.info(f"  No source memories:      {stats['no_sources']}")
    logger.info(f"  With real Lagrangian:     {stats['real_lagrangian']} "
                f"({100*stats['real_lagrangian']/max(1,stats['traced']):.1f}% of traced)")
    logger.info(f"  Total strong refs:       {stats['total_strong_refs']}")
    logger.info(f"  Total moderate refs:     {stats['total_moderate_refs']}")
    logger.info(f"  Avg strong refs/belief:  "
                f"{stats['total_strong_refs']/max(1,stats['traced']):.1f}")

    # ── Before/After comparison ──────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info(f"BEFORE vs AFTER COMPARISON")
    logger.info(f"{'='*60}")

    # Mass
    old_masses = [b.get("mass", 0) for b in beliefs]
    new_masses = [b.get("mass", 0) for b in updated_beliefs]
    logger.info(f"  Mass:        avg {np.mean(old_masses):.3f} → {np.mean(new_masses):.3f}")
    logger.info(f"               max {max(old_masses):.3f} → {max(new_masses):.3f}")

    # Confidence
    old_conf = [b.get("confidence", 0) for b in beliefs]
    new_conf = [b.get("confidence", 0) for b in updated_beliefs]
    logger.info(f"  Confidence:  avg {np.mean(old_conf):.3f} → {np.mean(new_conf):.3f}")

    # Lagrangian
    old_real_lag = sum(1 for b in beliefs
                       if b.get("encoding_lagrangian", {}).get("omega", 0.5) != 0.5)
    new_real_lag = stats["real_lagrangian"]
    logger.info(f"  Real Lagrangian: {old_real_lag} → {new_real_lag}")

    # Memory refs
    old_refs = sum(1 for b in beliefs if b.get("memory_refs"))
    new_refs = sum(1 for b in updated_beliefs if b.get("memory_refs"))
    logger.info(f"  With memory refs: {old_refs} → {new_refs}")

    # Verifications
    old_verif = [b.get("verifications", 0) for b in beliefs]
    new_verif = [b.get("verifications", 0) for b in updated_beliefs]
    logger.info(f"  Verifications: avg {np.mean(old_verif):.1f} → {np.mean(new_verif):.1f}")

    # ── Top beliefs by new mass ──────────────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info(f"TOP 20 BELIEFS BY BACKFILLED MASS")
    logger.info(f"{'='*60}")
    by_mass = sorted(updated_beliefs, key=lambda b: b.get("mass", 0), reverse=True)
    for b in by_mass[:20]:
        bf = b.get("_backfill", {})
        logger.info(
            f"  m={b['mass']:.2f} c={b['confidence']:.2f} "
            f"v={b.get('verifications',0):.0f} "
            f"refs={bf.get('strong_matches',0):3d} "
            f"ω={b.get('encoding_lagrangian',{}).get('omega',0):.3f} "
            f"| {b.get('content','')[:80]}"
        )

    # ── Beliefs with most memory support ─────────────────────────
    logger.info(f"\n{'='*60}")
    logger.info(f"TOP 20 BELIEFS BY MEMORY SUPPORT (strongest grounding)")
    logger.info(f"{'='*60}")
    by_refs = sorted(updated_beliefs,
                     key=lambda b: b.get("_backfill", {}).get("strong_matches", 0),
                     reverse=True)
    for b in by_refs[:20]:
        bf = b.get("_backfill", {})
        cat = ""
        for cat_name, cat_beliefs in by_category.items():
            if b in cat_beliefs:
                cat = cat_name
                break
        logger.info(
            f"  refs={bf.get('strong_matches',0):3d}+{bf.get('moderate_matches',0):3d} "
            f"m={b['mass']:.2f} "
            f"sim={bf.get('best_sim',0):.3f} "
            f"| {b.get('content','')[:85]}"
        )

    # Save summary report
    report = {
        "stats": stats,
        "before_after": {
            "mass_avg": [round(np.mean(old_masses), 3), round(np.mean(new_masses), 3)],
            "confidence_avg": [round(np.mean(old_conf), 3), round(np.mean(new_conf), 3)],
            "real_lagrangian": [old_real_lag, new_real_lag],
            "with_memory_refs": [old_refs, new_refs],
            "verifications_avg": [round(np.mean(old_verif), 1), round(np.mean(new_verif), 1)],
        },
    }
    with open(OUTPUT_DIR / "backfill_report.json", "w") as f:
        json.dump(report, f, indent=2, default=str)

    logger.info(f"\n✓ Backfill complete. Output in {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
