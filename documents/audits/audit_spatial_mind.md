# Spatial Mind Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`core/spatial_mind.py`](../../core/spatial_mind.py)

---

## 1. Runtime Role & Dual-Space Ownership

`SpatialMind` ([`core/spatial_mind.py`](../../core/spatial_mind.py#L30-L110)) manages dual 8D fields:

- **`belief_space`**: High-mass semantic belief field (~1K points).
- **`memory_space`**: Fast-accumulating episodic memory field (~12K+ points).
- **Gravity Basin Keyword Discovery (`get_gravity_basin_keywords`)**: Extracts keywords from 8D spatial clusters around Hop 1 evidence to drive `retrieve_multihop()` Hop 2 queries ([`core/spatial_mind.py`](../../core/spatial_mind.py#L420-L480)).
- **State Serialization**: `save_state()` and `load_state()` persist spatial coordinates to `data/spatial/` ([`core/spatial_mind.py`](../../core/spatial_mind.py#L500-L580)).
