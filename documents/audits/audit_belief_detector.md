# Belief Detector Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`core/belief_detector.py`](../../core/belief_detector.py)

---

## 1. Post-Pulse Realization Scanning

`BeliefDetector` ([`core/belief_detector.py`](../../core/belief_detector.py#L40-L380)) scans pulse monologue output for belief-forming realizations:
- **Zero-Cost Local Pass**: Scans thoughts using local model (`granite4.1:8b` via Ollama).
- **Pending Tagging**: Appends candidate belief extractions to `data/pending_beliefs.json` for nightly Curator consolidation.
- **Sentinel Nudges**: Boosts hedonic omega $\Omega$ when new self-discoveries or preferences are detected.
