# Physics Engine Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`core/physics_engine.py`](../../core/physics_engine.py)

---

## 1. Runtime Role & Spatial Coordination

`PhysicsEngine` ([`core/physics_engine.py`](../../core/physics_engine.py#L40-L130)) acts as the primary wrapper around [`SpatialMind`](../../core/spatial_mind.py#L30-L110):

- **Embedding Generation**: Converts text strings into 384D all-MiniLM-L6-v2 vectors via `embed_text()` and projects them to 8D using `embed_and_project()` ([`core/physics_engine.py`](../../core/physics_engine.py#L140-L200)).
- **Pulse Advance**: Executes `step_pulse()`, advancing attention coordinates through Euler-Lagrange force integration ([`core/physics_engine.py`](../../core/physics_engine.py#L210-L290)).
- **Neighborhood & Temporal Queries**: Implements `query_neighborhood()` to retrieve nearby 8D points and `query_temporal_chain()` to pull preceding/following memories ([`core/physics_engine.py`](../../core/physics_engine.py#L310-L420)).
- **Memory Entry Registration**: `register_memory_entry()` writes memory thoughts into journal files, embeds vectors, and registers 8D spatial coordinates ([`core/physics_engine.py`](../../core/physics_engine.py#L580-L640)).
