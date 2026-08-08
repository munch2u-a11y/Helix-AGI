#!/usr/bin/env python3
"""
Helix Benchmark Adapter — Concrete Implementation

Wraps the Helix cognitive architecture (PhysicsEngine, BeliefStore,
MemoryManager, Preconscious) behind the ``BenchmarkAdapter`` interface
so the benchmark runner can drive it without direct Helix imports.
"""

import os
import sys
import tempfile
from pathlib import Path

import numpy as np

# Ensure Helix packages are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.benchmark_adapter import BenchmarkAdapter


class HelixBenchmarkAdapter(BenchmarkAdapter):
    """Adapter that boots a temporary Helix mind for each benchmark iteration.

    Creates an isolated temp directory with a full PhysicsEngine,
    MemoryManager, BeliefStore, Scratchpad, and Preconscious.  All state
    is destroyed when ``teardown()`` is called.
    """

    def __init__(self, provider_config):
        self._provider_config = provider_config
        self._tmp_dir = None
        self._physics = None
        self._memory_manager = None
        self._belief_store = None
        self._scratchpad = None
        self._preconscious = None
        self._beliefs_dir = None

    # ── Lifecycle ────────────────────────────────────────────────────

    def _ensure_initialized(self):
        """Lazily boot the Helix mind on first use."""
        if self._tmp_dir is not None:
            return

        from core.physics_engine import PhysicsEngine
        from memory.memory_manager import MemoryManager
        from memory.belief_store import BeliefStore
        from core.scratchpad import Scratchpad
        from core.preconscious import Preconscious
        import shutil

        self._tmp_dir = tempfile.mkdtemp(prefix="helix_bench_")
        data_dir = os.path.join(self._tmp_dir, "data")
        os.makedirs(data_dir, exist_ok=True)

        # Copy the local seed preset if it exists
        repo_root = Path(__file__).resolve().parents[1]
        preset_dir = repo_root / "private_presets" / "helix_seed_local"
        if preset_dir.exists():
            for item in os.listdir(preset_dir):
                s = preset_dir / item
                d = os.path.join(data_dir, item)
                if s.is_dir():
                    shutil.copytree(s, d, dirs_exist_ok=True)
                else:
                    shutil.copy2(s, d)

        self._physics = PhysicsEngine(os.path.join(data_dir, "spatial"))
        self._memory_manager = MemoryManager(os.path.join(data_dir, "memory"))
        self._memory_manager.set_physics(self._physics)
        self._beliefs_dir = os.path.join(data_dir, "beliefs")
        self._belief_store = BeliefStore(self._beliefs_dir)
        self._scratchpad = Scratchpad(os.path.join(data_dir, "scratchpad"))

        class _MockRouter:
            contacts = {}

        self._preconscious = Preconscious(
            memory_manager=self._memory_manager,
            belief_store=self._belief_store,
            physics_engine=self._physics,
            scratchpad=self._scratchpad,
            channel_router=_MockRouter(),
            active_toolsets={"core"},
        )

    def teardown(self):
        """Remove the temporary directory tree."""
        if self._tmp_dir:
            import shutil
            shutil.rmtree(self._tmp_dir, ignore_errors=True)
            self._tmp_dir = None
            self._physics = None
            self._memory_manager = None
            self._belief_store = None
            self._scratchpad = None
            self._preconscious = None

    # ── Session ──────────────────────────────────────────────────────

    def create_session(self, system_instruction, tool_declarations, executor):
        from llm.providers.base import create_session
        self._ensure_initialized()
        return create_session(
            self._provider_config,
            system_instruction,
            tool_declarations,
            executor,
            preconscious=self._preconscious,
        )

    # ── Seeding ──────────────────────────────────────────────────────

    def seed_beliefs(self, beliefs_dict):
        import json
        self._ensure_initialized()
        os.makedirs(self._beliefs_dir, exist_ok=True)
        for cat, data in beliefs_dict.items():
            with open(os.path.join(self._beliefs_dir, f"{cat}.json"), "w") as f:
                json.dump(data, f, indent=2)

    def seed_memories(self, memories_list):
        self._ensure_initialized()
        for mem in memories_list:
            self._memory_manager.store(
                content=mem["content"],
                memory_type=mem["memory_type"],
                source=mem["source"],
                importance=mem["importance"],
                tags=mem.get("tags", []),
                lagrangian_snapshot=mem.get("lagrangian_snapshot"),
            )

    # ── Bootstrap ────────────────────────────────────────────────────

    def bootstrap(self):
        self._ensure_initialized()
        self._physics.bootstrap_from_stores(self._belief_store, self._memory_manager)

    # ── Context Injection / Retrieval ────────────────────────────────

    def inject_context(self, previous_thought, events, trigger_type):
        self._ensure_initialized()
        annotations, ambient, surfaced_ids, centroid = self._preconscious.inject(
            previous_thought=previous_thought,
            incoming_events=events,
            trigger_type=trigger_type,
        )
        parts = [str(item).strip() for item in annotations if str(item).strip()]
        if ambient and str(ambient).strip():
            parts.append(str(ambient).strip())
        context_string = "\n\n".join(parts).strip()
        extra = {
            "annotations": annotations,
            "ambient": ambient,
            "centroid": centroid,
        }
        return context_string, surfaced_ids, extra

    def reset_context(self):
        self._ensure_initialized()
        self._preconscious._prev_pulse_beliefs = []
        self._preconscious._belief_cache = []
        self._preconscious._belief_cache_count = 0
        self._preconscious._belief_cache_mass = 0.0

        for space in [
            self._physics.spatial_mind.belief_space,
            self._physics.spatial_mind.memory_space,
        ]:
            to_remove = [
                pid for pid, data in space._points.items()
                if data.get("type") == "trail"
            ]
            for pid in to_remove:
                del space._points[pid]
            if to_remove:
                space._tree_dirty = True
                space._rebuild_tree()

        self._physics.attention_center = np.zeros(8, dtype=np.float32)
        self._physics.spatial_mind.prev_center = None
        self._physics.spatial_mind._velocity = np.zeros(8, dtype=np.float32)
        self._physics.spatial_mind._gamma = 0.5

    # ── Belief Management ────────────────────────────────────────────

    def store_belief(self, content, category="propositions",
                     source="benchmark_stage", mass=1.5, confidence=1.0):
        self._ensure_initialized()
        from core.belief_cosmology import SCALE_FACTOR

        belief_id = self._belief_store.generate_id(category)
        position = (self._physics.embed_and_project(content) * SCALE_FACTOR).tolist()
        self._belief_store.add_belief(
            category=category,
            belief_id=belief_id,
            content=content,
            mass=mass,
            confidence=confidence,
            source=source,
            position_8d=position,
        )
        return belief_id

    # ── Physics ──────────────────────────────────────────────────────

    def step_physics(self, thought_text, incoming_text):
        self._ensure_initialized()
        self._physics.step_pulse(
            thought_text=thought_text,
            incoming_text=incoming_text,
        )

    # ── Accessors (for benchmark internals that need raw objects) ─────

    @property
    def memory_manager(self):
        self._ensure_initialized()
        return self._memory_manager

    @property
    def belief_store(self):
        self._ensure_initialized()
        return self._belief_store
