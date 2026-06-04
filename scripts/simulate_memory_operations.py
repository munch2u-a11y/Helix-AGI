"""
Memory Operations Simulator

Simulates memory system operations:
- Memory load/save cycles
- Memory promotion logic (short-term → long-term → core)
- Semantic indexing patterns
- Data persistence and integrity verification
"""

import os
import sys
import json
import time
import tempfile
import shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class MemorySimulator:
    """Simulates the memory manager's core operations."""

    def __init__(self, data_dir):
        self.data_dir = data_dir
        os.makedirs(data_dir, exist_ok=True)
        self.memories = []
        self.next_id = 1
        self.promotions = {"short_term": 0, "long_term": 0, "core": 0}

    def create_memory(self, content, importance=0.5, source="pulse"):
        """Create a new short-term memory."""
        memory = {
            "id": self.next_id,
            "content": content,
            "importance": importance,
            "source": source,
            "created_at": datetime.now().isoformat(),
            "tier": "short_term",
            "access_count": 0,
        }
        self.memories.append(memory)
        self.next_id += 1
        return memory

    def promote_memory(self, memory_id, target_tier):
        """Promote a memory to a higher tier."""
        for m in self.memories:
            if m["id"] == memory_id:
                old_tier = m["tier"]
                m["tier"] = target_tier
                self.promotions[target_tier] = self.promotions.get(target_tier, 0) + 1
                return True
        return False

    def search(self, query, limit=5):
        """Simple keyword search across memories."""
        query_lower = query.lower()
        results = []
        for m in self.memories:
            if query_lower in m["content"].lower():
                score = m["importance"] + (m["access_count"] * 0.1)
                results.append({"memory": m, "score": score})
                m["access_count"] += 1
        results.sort(key=lambda r: r["score"], reverse=True)
        return results[:limit]

    def save_to_disk(self):
        """Persist all memories to disk."""
        path = os.path.join(self.data_dir, "memories.json")
        with open(path, "w") as f:
            json.dump(self.memories, f, indent=2)
        return len(self.memories)

    def load_from_disk(self):
        """Load memories from disk."""
        path = os.path.join(self.data_dir, "memories.json")
        if os.path.exists(path):
            with open(path) as f:
                self.memories = json.load(f)
            return len(self.memories)
        return 0

    def get_stats(self):
        """Get memory system statistics."""
        tier_counts = {}
        for m in self.memories:
            tier = m.get("tier", "unknown")
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
        return {
            "total_memories": len(self.memories),
            "tier_breakdown": tier_counts,
            "promotions": self.promotions.copy(),
        }


def run_memory_simulation():
    """Run memory operations simulation."""
    print("\n" + "=" * 70)
    print("MEMORY OPERATIONS SIMULATOR")
    print("=" * 70)

    temp_dir = tempfile.mkdtemp()

    try:
        sim = MemorySimulator(os.path.join(temp_dir, "memory"))

        # ── Phase 1: Create memories ─────────────────────────────
        print("\n[1] Creating 50 memories...")
        t0 = time.time()

        sample_contents = [
            "User asked about the weather forecast for tomorrow.",
            "I found that the API returns JSON with a 'temperature' field.",
            "The conversation shifted to discussing architecture patterns.",
            "User mentioned they prefer dark mode interfaces.",
            "I learned that FAISS requires float32 vectors for indexing.",
            "The terminal command 'htop' is not installed on this system.",
            "User expressed frustration with the slow response time.",
            "I successfully sent a reply through Telegram.",
            "The belief store has 340 entries across 7 categories.",
            "Memory consolidation during sleep cycle found 12 duplicates.",
        ]

        for i in range(50):
            content = sample_contents[i % len(sample_contents)]
            importance = 0.3 + (i % 5) * 0.15  # Vary importance 0.3-0.9
            sim.create_memory(f"[Pulse {i+1}] {content}", importance=importance)

        elapsed = time.time() - t0
        print(f"  Created 50 memories in {elapsed*1000:.1f}ms")

        # ── Phase 2: Search ──────────────────────────────────────
        print("\n[2] Running search queries...")
        queries = ["weather", "terminal", "belief", "user", "API"]
        for query in queries:
            results = sim.search(query, limit=3)
            print(f"  '{query}': {len(results)} results")
            for r in results:
                print(f"    score={r['score']:.2f}: {r['memory']['content'][:60]}...")

        # ── Phase 3: Promote memories ────────────────────────────
        print("\n[3] Promoting high-importance memories...")
        promoted = 0
        for m in sim.memories:
            if m["importance"] >= 0.7 and m["tier"] == "short_term":
                sim.promote_memory(m["id"], "long_term")
                promoted += 1
        print(f"  Promoted {promoted} memories to long_term")

        # Promote the very best to core
        core_promoted = 0
        for m in sim.memories:
            if m["importance"] >= 0.85 and m["tier"] == "long_term":
                sim.promote_memory(m["id"], "core")
                core_promoted += 1
        print(f"  Promoted {core_promoted} memories to core")

        # ── Phase 4: Persistence ─────────────────────────────────
        print("\n[4] Testing persistence...")
        saved = sim.save_to_disk()
        print(f"  Saved {saved} memories to disk")

        # Create a new simulator and load
        sim2 = MemorySimulator(os.path.join(temp_dir, "memory"))
        loaded = sim2.load_from_disk()
        print(f"  Loaded {loaded} memories from disk")

        # Verify integrity
        assert loaded == saved, f"Integrity check failed: saved={saved}, loaded={loaded}"
        print(f"  ✓ Integrity verified: {loaded} == {saved}")

        # ── Phase 5: Statistics ──────────────────────────────────
        print("\n[5] Final Statistics:")
        stats = sim.get_stats()
        print(f"  Total memories: {stats['total_memories']}")
        for tier, count in stats['tier_breakdown'].items():
            print(f"  {tier}: {count}")
        print(f"  Promotions: {stats['promotions']}")

        print("\n" + "=" * 70)
        print("✓ MEMORY SIMULATION COMPLETE")
        print("=" * 70)

    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


if __name__ == "__main__":
    run_memory_simulation()
