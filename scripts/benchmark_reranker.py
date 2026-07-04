#!/usr/bin/env python3
"""
Helix — Cross-Encoder Rerank Benchmark (Phase 1)

Measures the effect of the Phase 1.5 cross-encoder rerank stage on the
preconscious belief query (`Preconscious._gravity_query`). Runs the exact
production retrieval path twice — reranker OFF vs ON — and reports the
change in retrieval precision and per-query latency.

Two modes:

  synthetic (default) — Seeds N labeled beliefs across K distinct topic
    clusters into an isolated belief store, then probes each cluster with
    a query concept. Because every belief's ground-truth topic is known,
    this yields a clean quantitative Precision@k before/after. This is the
    controlled measurement: does the cross-encoder pull the topically
    correct beliefs above the near-miss distractors the bi-encoder blurs?

  real — Loads the actual data/beliefs store and prints a side-by-side
    top-K for a set of probe concepts. Qualitative; use it to eyeball
    whether reranking changes what Helix would actually surface.

Usage:
    venv/bin/python scripts/benchmark_reranker.py                 # synthetic
    venv/bin/python scripts/benchmark_reranker.py --mode real
    venv/bin/python scripts/benchmark_reranker.py --per-topic 8 --topk 5
"""

import argparse
import logging
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("benchmark_reranker")


class _MockRouter:
    contacts: dict = {}


# ── Synthetic labeled belief set ─────────────────────────────────────
# Each topic is a cluster of related beliefs plus a probe concept. Topics
# are chosen to include near-miss lexical overlaps across clusters (e.g.
# "python" the language vs "snake", "current" electrical vs oceanic) —
# exactly where a bi-encoder cosine gate blurs and a cross-encoder should
# separate.
TOPICS = {
    "python_lang": {
        "probe": "writing asynchronous python code",
        "beliefs": [
            "I write Python using asyncio and coroutines for concurrency",
            "I prefer list comprehensions over explicit for-loops in Python",
            "The Python GIL prevents true multithreaded CPU parallelism",
            "I use type hints and dataclasses to structure Python programs",
            "Decorators let me wrap Python functions without editing them",
            "I debug Python with pdb breakpoints rather than print statements",
        ],
    },
    "snakes": {
        "probe": "keeping a pet snake healthy",
        "beliefs": [
            "A ball python is a docile snake that makes a good first pet",
            "Snakes are ectotherms and need an external heat gradient",
            "I feed my snake frozen-thawed mice every two weeks",
            "Shedding in snakes signals healthy growth when it comes off whole",
            "Venomous snakes should never be handled without training",
            "A snake's enclosure needs a humid hide to aid shedding",
        ],
    },
    "astronomy": {
        "probe": "how stars form in a nebula",
        "beliefs": [
            "Stars form when gravity collapses cold molecular clouds",
            "A nebula is an interstellar cloud of dust and ionized gas",
            "The Sun fuses hydrogen into helium in its core",
            "Supernovae seed the galaxy with heavy elements",
            "Red giants form when a star exhausts its core hydrogen",
            "Black holes bend spacetime so light cannot escape",
        ],
    },
    "cooking": {
        "probe": "baking sourdough bread at home",
        "beliefs": [
            "A sourdough starter is wild yeast kept alive with flour and water",
            "I proof bread dough until it doubles before baking",
            "A hot Dutch oven gives sourdough a crisp crust",
            "Kneading develops the gluten that traps fermentation gas",
            "I salt pasta water heavily so it seasons the noodles",
            "Resting steak lets the juices redistribute before slicing",
        ],
    },
    "finance": {
        "probe": "saving for retirement with index funds",
        "beliefs": [
            "I invest in low-cost index funds for long-term retirement growth",
            "Compound interest rewards starting to save as early as possible",
            "An emergency fund should cover three to six months of expenses",
            "Diversification across assets reduces portfolio risk",
            "Paying off high-interest debt beats most investment returns",
            "Dollar-cost averaging smooths out market volatility over time",
        ],
    },
    "ocean_currents": {
        "probe": "how ocean currents move heat around the planet",
        "beliefs": [
            "The Gulf Stream carries warm water from the tropics northward",
            "Thermohaline circulation is driven by temperature and salinity",
            "Ocean currents redistribute heat and regulate coastal climate",
            "Upwelling brings cold nutrient-rich water to the surface",
            "The Coriolis effect deflects currents into large gyres",
            "Tides are driven by the gravitational pull of the moon",
        ],
    },
}


def _build_preconscious(data_dir: str, enable_reranker: bool):
    from core.physics_engine import PhysicsEngine
    from memory.memory_manager import MemoryManager
    from memory.belief_store import BeliefStore
    from core.preconscious import Preconscious

    physics = PhysicsEngine(data_dir=os.path.join(data_dir, "spatial"))
    memory_manager = MemoryManager(os.path.join(data_dir, "memory"))
    memory_manager.set_physics(physics)
    belief_store = BeliefStore(os.path.join(data_dir, "beliefs"))
    belief_store.set_runtime(physics_engine=physics, memory_manager=memory_manager)

    pre = Preconscious(
        memory_manager=memory_manager,
        belief_store=belief_store,
        physics_engine=physics,
        channel_router=_MockRouter(),
        active_toolsets={"core"},
        enable_reranker=enable_reranker,
    )
    return pre, belief_store


def _seed_synthetic(belief_store, per_topic: int):
    """Seed labeled beliefs. Ground-truth topic = belief_id prefix."""
    count = 0
    for topic, spec in TOPICS.items():
        for i, content in enumerate(spec["beliefs"][:per_topic]):
            belief_store.add_belief(
                category="propositions",
                belief_id=f"syn__{topic}__{i}",
                content=content,
                confidence=0.7,
            )
            count += 1
    return count


def _topic_of(belief_id: str) -> str:
    # id format: syn__<topic>__<i>
    parts = belief_id.split("__")
    return parts[1] if len(parts) >= 2 else ""


def _run_query(pre, seed_text: str, mode: str, k: int):
    """Run the production _gravity_query once in a given relevance mode.

    mode ∈ {"legacy", "cosine", "crossenc"}. Returns (results, ms).
    """
    pre._relevance_mode = mode
    t0 = time.perf_counter()
    results = pre._gravity_query(
        seed_text=seed_text,
        exclude=set(),
        max_results=k,
        min_results=1,
    )
    ms = (time.perf_counter() - t0) * 1000.0
    return results, ms


def run_synthetic(per_topic: int, topk: int):
    with tempfile.TemporaryDirectory() as tmp:
        # Build once; the reranker is a runtime toggle so a single
        # Preconscious (one belief cache) serves both arms of the A/B.
        pre, belief_store = _build_preconscious(tmp, enable_reranker=True)
        n = _seed_synthetic(belief_store, per_topic)
        pre._ensure_belief_cache()  # embed + position the seeded beliefs

        print(f"\nSeeded {n} synthetic beliefs across {len(TOPICS)} topics "
              f"({per_topic}/topic). Probing each topic; Precision@{topk}.")
        print("Modes: legacy = T×M/d² (original) · cosine = T×M×cos384 · "
              "crossenc = T×M×cross-encoder\n")
        modes = ["legacy", "cosine", "crossenc"]
        hdr = f"{'topic':<16}" + "".join(f"{m:>11}" for m in modes) + \
              "".join(f"{m+' ms':>12}" for m in modes)
        print(hdr)
        print("-" * len(hdr))

        agg = {m: {"p": [], "ms": []} for m in modes}
        denom = min(topk, per_topic)
        # Warm the reranker model once so its ~6s lazy load doesn't land
        # in a measured latency cell.
        if pre._reranker is not None:
            _ = pre._reranker.available

        for topic, spec in TOPICS.items():
            probe = spec["probe"]
            row_p, row_ms = {}, {}
            for m in modes:
                res, ms = _run_query(pre, probe, mode=m, k=topk)
                hits = sum(1 for b in res[:topk] if _topic_of(b["id"]) == topic)
                row_p[m] = hits / denom
                row_ms[m] = ms
                agg[m]["p"].append(row_p[m])
                agg[m]["ms"].append(ms)
            line = f"{topic:<16}" + "".join(f"{row_p[m]:>11.2f}" for m in modes) + \
                   "".join(f"{row_ms[m]:>12.1f}" for m in modes)
            print(line)

        def avg(xs):
            return sum(xs) / len(xs) if xs else 0.0

        print("-" * len(hdr))
        mean_line = f"{'MEAN':<16}" + "".join(f"{avg(agg[m]['p']):>11.2f}" for m in modes) + \
                    "".join(f"{avg(agg[m]['ms']):>12.1f}" for m in modes)
        print(mean_line)

        base = avg(agg["legacy"]["p"])
        print(f"\nPrecision@{topk} vs legacy 8D-gravity baseline ({base:.2f}):")
        for m in ("cosine", "crossenc"):
            d = avg(agg[m]["p"]) - base
            print(f"  {m:<9} {avg(agg[m]['p']):.2f}  ({d:+.3f})  "
                  f"+{avg(agg[m]['ms']) - avg(agg['legacy']['ms']):.0f} ms/query")
        if not (pre._reranker and pre._reranker.available):
            print("  NOTE: cross-encoder UNAVAILABLE — crossenc fell back to cosine.")


def run_real(topk: int, probes):
    data_dir = "data"
    if not os.path.isdir(os.path.join(data_dir, "beliefs")):
        print(f"No belief store at {data_dir}/beliefs — run from repo root.")
        return
    pre, _ = _build_preconscious_real(data_dir)
    pre._ensure_belief_cache()
    n = len(pre._belief_cache)
    print(f"\nLoaded {n} real beliefs. Side-by-side top-{topk} per probe.\n")
    if pre._reranker is not None:
        _ = pre._reranker.available

    for probe in probes:
        base, base_ms = _run_query(pre, probe, mode="legacy", k=topk)
        rr, rr_ms = _run_query(pre, probe, mode="crossenc", k=topk)
        print(f"── probe: {probe!r}  (legacy {base_ms:.0f}ms | crossenc {rr_ms:.0f}ms)")
        print(f"   {'LEGACY (T×M/d²)':<40} {'CROSSENC (T×M×relevance)':<40}")
        for i in range(topk):
            b = base[i]["content"][:36] if i < len(base) else ""
            r = rr[i]["content"][:36] if i < len(rr) else ""
            print(f"   {i+1}. {b:<37} {i+1}. {r}")
        print()


def _build_preconscious_real(data_dir):
    from core.physics_engine import PhysicsEngine
    from memory.memory_manager import MemoryManager
    from memory.belief_store import BeliefStore
    from core.preconscious import Preconscious

    physics = PhysicsEngine(data_dir=os.path.join(data_dir, "spatial"))
    memory_manager = MemoryManager(os.path.join(data_dir, "memory"))
    memory_manager.set_physics(physics)
    belief_store = BeliefStore(os.path.join(data_dir, "beliefs"))
    belief_store.set_runtime(physics_engine=physics, memory_manager=memory_manager)
    pre = Preconscious(
        memory_manager=memory_manager,
        belief_store=belief_store,
        physics_engine=physics,
        channel_router=_MockRouter(),
        active_toolsets={"core"},
        enable_reranker=True,
    )
    return pre, belief_store


def main():
    ap = argparse.ArgumentParser(description="Helix cross-encoder rerank benchmark")
    ap.add_argument("--mode", choices=["synthetic", "real"], default="synthetic")
    ap.add_argument("--per-topic", type=int, default=6,
                    help="synthetic beliefs seeded per topic (max 6)")
    ap.add_argument("--topk", type=int, default=5, help="top-K to score")
    ap.add_argument("--probe", action="append", default=None,
                    help="real mode: probe concept (repeatable)")
    args = ap.parse_args()

    if args.mode == "synthetic":
        run_synthetic(per_topic=min(args.per_topic, 6), topk=args.topk)
    else:
        probes = args.probe or [
            "asynchronous programming in python",
            "what do I value about autonomy",
            "how memory and beliefs are stored",
        ]
        run_real(topk=args.topk, probes=probes)


if __name__ == "__main__":
    main()
