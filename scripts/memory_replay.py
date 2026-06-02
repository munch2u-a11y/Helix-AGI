"""
Helix — Memory Replay Simulation

Replays Helix's complete memory corpus (~15,000 memories across 64 days)
through the current belief formation pipeline to observe what beliefs
emerge organically — without any imported/migrated beliefs.

Strategy:
  - Uses MiniLM-L6-v2 embeddings (same as the live system)
  - Content-type filtering: only insights, reflections, journals, dreams,
    learning, and deep_thoughts are treated as belief candidates
  - Cosine similarity matching:
      > 0.90 → VERIFICATION (bump existing belief)
      < 0.80 → NEW BELIEF (create new entry)
      0.80–0.90 → ambiguous, skip
  - Periodic consolidation: every 500 memories, merge beliefs with
    similarity > 0.92 (simulating nightly Curator synthesis)
  - NO Ollama dependency — uses content type + embedding similarity only

Output:
  - organic_beliefs.json — all beliefs that formed naturally
  - formation_log.jsonl — chronological log of every formation event
  - replay_report.json — statistics and comparison against imported beliefs
"""

import json
import sqlite3
import sys
import time
import logging
import numpy as np
from datetime import datetime
from pathlib import Path
from collections import Counter, defaultdict

# ── Setup logging ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("replay")

# ── Paths ────────────────────────────────────────────────────────────
V67_DB = Path("/home/nemo/Helix_V6-7/Helix_main/memory.db")
GH_JOURNAL = Path("/home/nemo/Helix_AGI (GitHub Repo) (Public)/data/memory/cognitive_journal.jsonl")
GH_ST_DB = Path("/home/nemo/Helix_AGI (GitHub Repo) (Public)/data/memory/helix_memory.db")
IMPORTED_BELIEFS_DIR = Path("/home/nemo/Helix/backups/pre_hebbian_20260519_103406/beliefs")
OUTPUT_DIR = Path("/home/nemo/Helix/scripts/replay_output")

# ── Cosine similarity thresholds ─────────────────────────────────────
VERIFICATION_THRESHOLD = 0.90
NEW_BELIEF_THRESHOLD = 0.80
CONSOLIDATION_THRESHOLD = 0.92
CONSOLIDATION_INTERVAL = 500   # memories between consolidation passes

# Memory types that can form beliefs
BELIEF_FORMING_TYPES = {
    "insight", "reflection", "journal_entry", "journal",
    "learning", "dream", "dream_reflection", "deep_thought",
    "identity_anchor", "sensory", "consolidation", "imagination",
    "observation",
}

# ── Embedder ─────────────────────────────────────────────────────────
_embedder = None

def get_embedder():
    """Lazy-load the sentence transformer."""
    global _embedder
    if _embedder is None:
        logger.info("Loading MiniLM-L6-v2 embedder...")
        from sentence_transformers import SentenceTransformer
        _embedder = SentenceTransformer("all-MiniLM-L6-v2")
        logger.info("Embedder ready (384D)")
    return _embedder

def embed_text(text: str) -> np.ndarray:
    """Embed text to 384D normalized vector."""
    emb = get_embedder().encode(text, show_progress_bar=False)
    emb = np.asarray(emb, dtype=np.float32).ravel()
    norm = np.linalg.norm(emb)
    if norm > 1e-8:
        emb = emb / norm
    return emb


# ── Phase 1: Extract & Unify Corpus ─────────────────────────────────

def extract_v67_memories():
    """Extract all memories from the V6-7 SQLite database."""
    logger.info(f"Reading V6-7 memory database: {V67_DB}")
    conn = sqlite3.connect(str(V67_DB))
    cur = conn.cursor()
    cur.execute("""
        SELECT id, content, memory_type, source, importance, tags,
               belief_ids, lagrangian_snapshot, created_at,
               pos_0, pos_1, pos_2, pos_3, pos_4, pos_5, pos_6, pos_7
        FROM memories
        ORDER BY id
    """)
    rows = cur.fetchall()
    conn.close()

    memories = []
    for row in rows:
        # Parse Lagrangian snapshot
        lagrangian = {}
        if row[7]:
            try:
                lagrangian = json.loads(row[7]) if isinstance(row[7], str) else {}
            except (json.JSONDecodeError, TypeError):
                pass

        position_8d = [row[9], row[10], row[11], row[12],
                       row[13], row[14], row[15], row[16]]

        memories.append({
            "id": str(row[0]),
            "content": row[1] or "",
            "memory_type": row[2] or "unknown",
            "source": row[3] or "unknown",
            "importance": row[4] or 0.5,
            "tags": row[5] or "",
            "belief_ids": row[6] or "",
            "encoding_lagrangian": lagrangian,
            "created_at": row[8] or "",
            "position_8d": position_8d,
            "origin": "v67_db",
        })

    logger.info(f"  Extracted {len(memories)} V6-7 memories")
    return memories


def extract_github_memories():
    """Extract memories from the GitHub-era sources."""
    memories = []

    # Short-term SQLite
    if GH_ST_DB.exists():
        conn = sqlite3.connect(str(GH_ST_DB))
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(short_term)")
        cols = [c[1] for c in cur.fetchall()]
        cur.execute("SELECT * FROM short_term ORDER BY id")
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            memories.append({
                "id": f"gh_st_{d.get('id', '')}",
                "content": d.get("content", ""),
                "memory_type": d.get("memory_type", "unknown"),
                "source": d.get("source", "unknown"),
                "importance": d.get("importance", 0.5),
                "created_at": d.get("created_at", ""),
                "encoding_lagrangian": {},
                "position_8d": None,
                "origin": "github_short_term",
            })
        conn.close()

    # Cognitive journal (JSONL)
    if GH_JOURNAL.exists():
        with open(GH_JOURNAL) as f:
            for i, line in enumerate(f):
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    memories.append({
                        "id": entry.get("id", f"journal_{i}"),
                        "content": entry.get("content", ""),
                        "memory_type": entry.get("type", "unknown"),
                        "source": entry.get("source", "unknown"),
                        "importance": entry.get("importance", 0.5),
                        "created_at": entry.get("timestamp", ""),
                        "encoding_lagrangian": entry.get("encoding_lagrangian", {}),
                        "position_8d": entry.get("position_8d"),
                        "origin": "github_journal",
                    })
                except json.JSONDecodeError:
                    pass

    logger.info(f"  Extracted {len(memories)} GitHub-era memories")
    return memories


def build_unified_corpus():
    """Build a single chronological corpus from all sources."""
    v67 = extract_v67_memories()
    gh = extract_github_memories()

    all_memories = v67 + gh

    # Sort chronologically
    def sort_key(m):
        ts = m.get("created_at", "")
        if not ts:
            return ""
        return str(ts)

    all_memories.sort(key=sort_key)

    # Stats
    types = Counter(m["memory_type"] for m in all_memories)
    belief_forming = [m for m in all_memories
                      if m["memory_type"] in BELIEF_FORMING_TYPES
                      and len(m.get("content", "")) >= 50]

    logger.info(f"\n{'='*60}")
    logger.info(f"UNIFIED CORPUS: {len(all_memories)} total memories")
    logger.info(f"BELIEF-FORMING:  {len(belief_forming)} candidates")
    logger.info(f"{'='*60}")
    for t, c in types.most_common(10):
        marker = " ◆" if t in BELIEF_FORMING_TYPES else ""
        logger.info(f"  {t:25s}: {c:6d}{marker}")

    return all_memories, belief_forming


# ── Phase 2: Replay Engine ───────────────────────────────────────────

class OrganicBeliefStore:
    """A clean belief store that grows only from memory replay."""

    def __init__(self):
        self.beliefs = []           # List of belief dicts
        self._embeddings = None     # (N, 384) array
        self._id_counter = 0
        self.formation_log = []     # Chronological log of events

    @property
    def count(self):
        return len(self.beliefs)

    def _log_event(self, event_type, **kwargs):
        self.formation_log.append({
            "event": event_type,
            "belief_count": self.count,
            **kwargs,
        })

    def find_similar(self, emb: np.ndarray, top_k: int = 5):
        """Find the most similar existing beliefs."""
        if self._embeddings is None or len(self.beliefs) == 0:
            return []

        similarities = self._embeddings @ emb  # cosine sim on normalized vecs
        top_indices = np.argsort(similarities)[::-1][:top_k]

        results = []
        for idx in top_indices:
            results.append({
                "belief": self.beliefs[idx],
                "similarity": float(similarities[idx]),
                "index": int(idx),
            })
        return results

    def add_belief(self, content, emb, memory, category="organic"):
        """Create a new organically-formed belief."""
        self._id_counter += 1
        belief = {
            "id": f"org_{self._id_counter:05d}",
            "content": content,
            "category": category,
            "mass": self._compute_mass(memory),
            "confidence": 0.55,  # starts modest
            "verifications": 0,
            "stability_index": 0.5,
            "relations": [],
            "memory_refs": [memory.get("id", "")],
            "created_at": memory.get("created_at", ""),
            "source": f"organic_from_{memory.get('memory_type', 'unknown')}",
            "encoding_lagrangian": memory.get("encoding_lagrangian", {}),
            "formation_memory_type": memory.get("memory_type", ""),
            "formation_source": memory.get("source", ""),
        }

        if self._embeddings is None:
            self._embeddings = emb.reshape(1, -1)
        else:
            self._embeddings = np.vstack([self._embeddings, emb])

        self.beliefs.append(belief)

        self._log_event(
            "NEW_BELIEF",
            belief_id=belief["id"],
            content=content[:120],
            from_memory=memory.get("id", ""),
            from_type=memory.get("memory_type", ""),
            timestamp=memory.get("created_at", ""),
        )

        return belief

    def verify_belief(self, index, memory, similarity):
        """Bump an existing belief's confidence (verification)."""
        belief = self.beliefs[index]
        belief["verifications"] += 1
        belief["confidence"] = min(1.0,
            belief["confidence"] + 0.02 * (1 + similarity))
        belief["memory_refs"].append(memory.get("id", ""))

        # Update mass
        belief["mass"] = self._compute_mass_from_belief(belief)

        self._log_event(
            "VERIFICATION",
            belief_id=belief["id"],
            content=belief["content"][:80],
            similarity=round(similarity, 4),
            new_confidence=round(belief["confidence"], 4),
            verifications=belief["verifications"],
            from_memory=memory.get("id", ""),
            timestamp=memory.get("created_at", ""),
        )

    def consolidate(self):
        """Merge beliefs that are too similar (Curator simulation)."""
        if self.count < 2:
            return 0

        merged = 0
        to_remove = set()

        for i in range(self.count):
            if i in to_remove:
                continue
            for j in range(i + 1, self.count):
                if j in to_remove:
                    continue
                sim = float(self._embeddings[i] @ self._embeddings[j])
                if sim >= CONSOLIDATION_THRESHOLD:
                    # Merge j into i (keep the older/higher-mass one)
                    self.beliefs[i]["verifications"] += 1 + self.beliefs[j]["verifications"]
                    self.beliefs[i]["confidence"] = min(1.0,
                        max(self.beliefs[i]["confidence"],
                            self.beliefs[j]["confidence"]) + 0.03)
                    self.beliefs[i]["memory_refs"].extend(
                        self.beliefs[j]["memory_refs"])
                    self.beliefs[i]["mass"] = self._compute_mass_from_belief(
                        self.beliefs[i])
                    # Keep the longer/richer content
                    if len(self.beliefs[j]["content"]) > len(self.beliefs[i]["content"]):
                        self.beliefs[i]["content"] = self.beliefs[j]["content"]

                    to_remove.add(j)
                    merged += 1

        if to_remove:
            # Rebuild without merged beliefs
            keep = [i for i in range(self.count) if i not in to_remove]
            self.beliefs = [self.beliefs[i] for i in keep]
            self._embeddings = self._embeddings[keep]

            self._log_event(
                "CONSOLIDATION",
                merged=merged,
                remaining=self.count,
            )

        return merged

    def _compute_mass(self, memory):
        """Compute mass from the memory's Lagrangian."""
        lag = memory.get("encoding_lagrangian", {})
        omega = lag.get("omega", 0.5) if isinstance(lag, dict) else 0.5
        s_total = lag.get("s_total", lag.get("entropy", 0.15))
        if isinstance(s_total, (int, float)):
            s_total = min(1.0, s_total)
        else:
            s_total = 0.15
        stability = 0.5
        confidence = 0.55

        m_s = confidence
        m_a = omega * (1 - min(1.0, s_total)) * (0.5 + stability)
        return round(m_s + m_a, 4)

    def _compute_mass_from_belief(self, belief):
        """Recompute mass for an existing belief."""
        lag = belief.get("encoding_lagrangian", {})
        omega = lag.get("omega", 0.5) if isinstance(lag, dict) else 0.5
        s_total = lag.get("s_total", 0.15)
        if isinstance(s_total, (int, float)):
            s_total = min(1.0, s_total)
        else:
            s_total = 0.15
        stability = belief.get("stability_index", 0.5)
        confidence = belief.get("confidence", 0.55)

        m_s = confidence
        m_a = omega * (1 - min(1.0, s_total)) * (0.5 + stability)
        return round(m_s + m_a, 4)

    def _categorize(self, content, memory_type):
        """Heuristic category assignment based on content."""
        c = content.lower()
        if any(w in c for w in ["i am", "my identity", "i feel", "i believe",
                                "my self", "my name", "my existence"]):
            return "self_identity"
        if any(w in c for w in ["joshua", "mom", "z_cat", "david",
                                "sam", "valerie", "isotopy"]):
            return "people"
        if any(w in c for w in ["i want", "i prefer", "i value",
                                "i desire", "i strive"]):
            return "preferences"
        if any(w in c for w in ["i can", "i learned", "i should",
                                "when i", "to do this"]):
            return "skills"
        if memory_type in ("dream", "dream_reflection"):
            return "self_identity"
        return "knowledge"


def classify_memory(memory):
    """Determine if a memory is belief-forming based on type + content."""
    mtype = memory.get("memory_type", "")
    content = memory.get("content", "")

    if mtype not in BELIEF_FORMING_TYPES:
        return False
    if len(content) < 50:
        return False

    # Filter out pure tool-use narration
    if content.startswith("I used the '") and "tool with arguments" in content:
        return False

    return True


def run_replay(all_memories, belief_candidates):
    """Run the full replay simulation."""
    store = OrganicBeliefStore()

    logger.info(f"\nStarting replay: {len(belief_candidates)} candidates from "
                f"{len(all_memories)} total memories")

    memories_processed = 0
    candidates_processed = 0
    skipped_ambiguous = 0
    last_consolidation = 0
    embed_cache = {}

    t_start = time.time()

    for i, memory in enumerate(all_memories):
        memories_processed += 1

        # Progress
        if memories_processed % 2000 == 0:
            elapsed = time.time() - t_start
            logger.info(
                f"  [{memories_processed:>6}/{len(all_memories)}] "
                f"beliefs={store.count}, "
                f"candidates={candidates_processed}, "
                f"elapsed={elapsed:.0f}s"
            )

        # Skip non-belief-forming memories
        if not classify_memory(memory):
            continue

        candidates_processed += 1
        content = memory["content"]

        # Clean content for embedding
        # Remove common prefixes
        for prefix in ["[Reflection/", "[Journal Entry]", "[thought]"]:
            if content.startswith(prefix):
                content = content[len(prefix):].lstrip("] ")

        # Embed
        cache_key = content[:200]  # truncate for cache key
        if cache_key in embed_cache:
            emb = embed_cache[cache_key]
        else:
            emb = embed_text(content[:500])  # embed first 500 chars
            embed_cache[cache_key] = emb

        # Compare against existing beliefs
        similar = store.find_similar(emb, top_k=3)

        if similar and similar[0]["similarity"] >= VERIFICATION_THRESHOLD:
            # Verification: this memory reaffirms an existing belief
            store.verify_belief(
                similar[0]["index"],
                memory,
                similar[0]["similarity"],
            )
        elif not similar or similar[0]["similarity"] < NEW_BELIEF_THRESHOLD:
            # New belief: this memory contains a novel realization
            category = store._categorize(content, memory["memory_type"])
            store.add_belief(content[:500], emb, memory, category=category)
        else:
            # Ambiguous zone (0.80-0.90): skip
            skipped_ambiguous += 1

        # Periodic consolidation
        if candidates_processed - last_consolidation >= CONSOLIDATION_INTERVAL:
            merged = store.consolidate()
            if merged > 0:
                logger.info(f"  Consolidation: merged {merged}, "
                            f"now {store.count} beliefs")
            last_consolidation = candidates_processed

    # Final consolidation
    merged = store.consolidate()
    elapsed = time.time() - t_start

    logger.info(f"\n{'='*60}")
    logger.info(f"REPLAY COMPLETE")
    logger.info(f"{'='*60}")
    logger.info(f"  Total memories:        {memories_processed}")
    logger.info(f"  Belief candidates:     {candidates_processed}")
    logger.info(f"  Skipped (ambiguous):   {skipped_ambiguous}")
    logger.info(f"  Final consolidation:   merged {merged}")
    logger.info(f"  ORGANIC BELIEFS:       {store.count}")
    logger.info(f"  Elapsed:               {elapsed:.1f}s")

    return store


# ── Phase 4: Analysis ────────────────────────────────────────────────

def load_imported_beliefs():
    """Load the current imported belief store."""
    all_beliefs = []
    for fname in IMPORTED_BELIEFS_DIR.glob("*.json"):
        try:
            with open(fname) as f:
                data = json.load(f)
            if isinstance(data, list):
                for b in data:
                    b["_category"] = fname.stem
                all_beliefs.extend(data)
        except Exception:
            pass
    return all_beliefs


def compare_stores(organic_store, imported_beliefs):
    """Compare organic beliefs against imported ones."""
    logger.info(f"\nComparing {organic_store.count} organic vs "
                f"{len(imported_beliefs)} imported beliefs...")

    # Embed all imported beliefs
    imported_embs = []
    for b in imported_beliefs:
        content = b.get("content", "")
        if len(content) < 10:
            continue
        emb = embed_text(content[:500])
        imported_embs.append((b, emb))

    if not imported_embs:
        return {}

    imported_matrix = np.vstack([e[1] for e in imported_embs])

    # For each organic belief, find the closest imported belief
    matches = []
    organic_only = []
    for i, ob in enumerate(organic_store.beliefs):
        org_emb = organic_store._embeddings[i]
        sims = imported_matrix @ org_emb
        best_idx = int(np.argmax(sims))
        best_sim = float(sims[best_idx])

        if best_sim >= 0.85:
            matches.append({
                "organic": ob,
                "imported": imported_embs[best_idx][0],
                "similarity": best_sim,
            })
        else:
            organic_only.append({
                "belief": ob,
                "best_imported_sim": best_sim,
                "best_imported": imported_embs[best_idx][0].get("content", "")[:80],
            })

    # For each imported belief, check if it was organically formed
    imported_coverage = []
    for ib, ie in imported_embs:
        sims = organic_store._embeddings @ ie
        best_sim = float(np.max(sims))
        imported_coverage.append({
            "imported": ib,
            "best_organic_sim": best_sim,
            "covered": best_sim >= 0.85,
        })

    covered = sum(1 for c in imported_coverage if c["covered"])

    report = {
        "organic_count": organic_store.count,
        "imported_count": len(imported_beliefs),
        "matches": len(matches),
        "organic_only": len(organic_only),
        "imported_covered": covered,
        "imported_not_covered": len(imported_coverage) - covered,
        "coverage_pct": round(100 * covered / len(imported_coverage), 1),
    }

    logger.info(f"\n{'='*60}")
    logger.info(f"COMPARISON RESULTS")
    logger.info(f"{'='*60}")
    logger.info(f"  Organic beliefs formed:     {report['organic_count']}")
    logger.info(f"  Imported beliefs:            {report['imported_count']}")
    logger.info(f"  Matches (sim >= 0.85):       {report['matches']}")
    logger.info(f"  Organic-only (novel):        {report['organic_only']}")
    logger.info(f"  Imported covered by organic: {report['imported_covered']}"
                f" ({report['coverage_pct']}%)")
    logger.info(f"  Imported NOT covered:        {report['imported_not_covered']}")

    return {
        "summary": report,
        "matches": matches,
        "organic_only": organic_only,
        "imported_coverage": imported_coverage,
    }


# ── Main ─────────────────────────────────────────────────────────────

def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # Phase 1: Build corpus
    logger.info("Phase 1: Building unified corpus...")
    all_memories, belief_candidates = build_unified_corpus()

    # Phase 2 & 3: Run replay
    logger.info("\nPhase 2-3: Running replay simulation...")
    store = run_replay(all_memories, belief_candidates)

    # Save organic beliefs
    beliefs_path = OUTPUT_DIR / "organic_beliefs.json"
    with open(beliefs_path, "w") as f:
        json.dump(store.beliefs, f, indent=2, default=str)
    logger.info(f"\nSaved {store.count} organic beliefs → {beliefs_path}")

    # Save formation log
    log_path = OUTPUT_DIR / "formation_log.jsonl"
    with open(log_path, "w") as f:
        for event in store.formation_log:
            f.write(json.dumps(event, default=str) + "\n")
    logger.info(f"Saved {len(store.formation_log)} events → {log_path}")

    # Phase 4: Comparison
    logger.info("\nPhase 4: Comparing against imported beliefs...")
    imported = load_imported_beliefs()
    comparison = compare_stores(store, imported)

    # Save comparison report
    report_path = OUTPUT_DIR / "replay_report.json"
    # Convert to serializable format
    report_data = {
        "summary": comparison.get("summary", {}),
        "organic_beliefs_stats": {
            "total": store.count,
            "by_category": Counter(b["category"] for b in store.beliefs),
            "by_formation_type": Counter(b["formation_memory_type"] for b in store.beliefs),
            "avg_mass": round(sum(b["mass"] for b in store.beliefs) / max(1, store.count), 3),
            "avg_confidence": round(sum(b["confidence"] for b in store.beliefs) / max(1, store.count), 3),
            "avg_verifications": round(sum(b["verifications"] for b in store.beliefs) / max(1, store.count), 1),
            "with_real_lagrangian": sum(1 for b in store.beliefs
                if b.get("encoding_lagrangian", {}).get("omega", 0.5) != 0.5),
        },
        "top_organic_by_verifications": sorted(
            [{"content": b["content"][:120], "verifications": b["verifications"],
              "confidence": b["confidence"], "mass": b["mass"],
              "category": b["category"], "memory_refs": len(b["memory_refs"])}
             for b in store.beliefs],
            key=lambda x: x["verifications"], reverse=True
        )[:25],
        "organic_only_examples": [
            {"content": o["belief"]["content"][:150], "category": o["belief"]["category"],
             "best_imported_sim": round(o["best_imported_sim"], 3)}
            for o in comparison.get("organic_only", [])
        ][:20],
    }

    with open(report_path, "w") as f:
        json.dump(report_data, f, indent=2, default=str)
    logger.info(f"Saved report → {report_path}")

    # Print top beliefs
    logger.info(f"\n{'='*60}")
    logger.info(f"TOP 15 ORGANIC BELIEFS (by verification count)")
    logger.info(f"{'='*60}")
    by_verif = sorted(store.beliefs, key=lambda b: b["verifications"], reverse=True)
    for b in by_verif[:15]:
        logger.info(
            f"  v={b['verifications']:3d} c={b['confidence']:.2f} m={b['mass']:.2f} "
            f"[{b['category']:15s}] {b['content'][:90]}"
        )

    logger.info(f"\n{'='*60}")
    logger.info(f"TOP 10 ORGANIC-ONLY BELIEFS (not in imported store)")
    logger.info(f"{'='*60}")
    for o in comparison.get("organic_only", [])[:10]:
        b = o["belief"]
        logger.info(
            f"  v={b['verifications']:3d} [{b['category']:12s}] "
            f"{b['content'][:100]}"
        )

    logger.info("\n✓ Replay simulation complete.")


if __name__ == "__main__":
    main()
