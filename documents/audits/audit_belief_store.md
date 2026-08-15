# Belief Store Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`memory/belief_store.py`](../../memory/belief_store.py)

---

## 1. Schema & Categorization

`BeliefStore` ([`memory/belief_store.py`](../../memory/belief_store.py#L40-L1420)) manages 7 belief categories across 2 tiers:

- **Outer Tier**: `premises`, `propositions`, `preferences` (stored in `data/beliefs/`).
- **Inner Tier**: `people`, `skills`, `desires`, `concepts` (consolidated nightly).
- **Cognitive Mass & Attrition**: `update_confidence()` recalculates confidence and prunes beliefs below $C < 0.20$ ([`memory/belief_store.py`](../../memory/belief_store.py#L500-L580)).
