"""Helix — Unified Retrieval Corpus

Presents Helix's existing stores as ONE flat pool of retrievable items, which
is what lets a memory and the belief formed from it compete in a single
ranking (see core/unified_retrieval.py).

Three tiers, all in one pool:

  Tier 0 — elements. Verbatim memories from the CognitiveJournal: every event
           and thought written by the pulse loop, unmodified.
  Tier 1 — outer-tier beliefs (premises/propositions/preferences) formed from
           memories by the Curator, which records its sources in memory_refs.
  Tier 2 — inner-tier beliefs (people/skills/desires/concepts) carrying a
           `term`, precipitated nightly. The heaviest structures.

This adapter is READ-ONLY over content. It never merges, rewrites or deletes:
a memory stays whole and independently retrievable no matter how many beliefs
cite it. The only write it performs is reliance telemetry, routed to the
BeliefStore's own counters so the Curator keeps seeing what got used.

Helix's PhysicsEngine registers every belief and memory into the independent
1024D SemanticIndex on ingest, so embeddings are normally read from there.
The journal's legacy 384D vector belongs only to the stable 8D spatial
projection and is never padded or reused for semantic search. If an item is
missing during migration, it is embedded natively on demand.
"""

import logging
import os
import re
from contextlib import nullcontext
from typing import Any, Dict, List, Optional, Set

import numpy as np

from memory.record_envelope import envelope_from_metadata

logger = logging.getLogger("helix.memory.mrag.corpus")

# Belief categories that carry a `term` and are precipitated nightly. Presence
# of `term` is the actual Tier-2 gate (Helix writes no `layer` field); this set
# is the cheap pre-check.
_TIER2_CATEGORIES = {"people", "skills", "desires", "concepts"}

_BARE_NUMBER_RE = re.compile(r'^\d+$')
_BENCHMARK_SCOPE_RE = re.compile(r"\[BENCHMARK ITEM:\s*([^\]]+)\]", re.IGNORECASE)
_TURN_RE = re.compile(r"\[TURN:\s*([^\]]+)\]", re.IGNORECASE)
_SESSION_RE = re.compile(r"\[SESSION:\s*([^\]]+)\]", re.IGNORECASE)


def _tag_value(tags: List[Any], *prefixes: str) -> Optional[str]:
    """Return the first non-empty value for a namespaced metadata tag."""
    for prefix in prefixes:
        marker = prefix.lower() + ":"
        for tag in tags or []:
            value = str(tag or "").strip()
            if value.lower().startswith(marker):
                result = value[len(marker):].strip()
                if result:
                    return result
    return None


def _structured_position(content: str, tags: List[Any], created_at: str, pulse_id: Any):
    """Resolve canonical scope and chronology for read-only office projections."""
    scope_id = _tag_value(tags, "item", "conversation", "thread", "session")
    if not scope_id:
        match = _BENCHMARK_SCOPE_RE.search(content or "")
        scope_id = match.group(1).strip() if match else None

    raw_turn = _tag_value(tags, "turn")
    if raw_turn is None:
        match = _TURN_RE.search(content or "")
        raw_turn = match.group(1).strip() if match else None
    try:
        turn_id: Any = int(raw_turn) if raw_turn is not None else int(pulse_id)
    except (TypeError, ValueError):
        turn_id = raw_turn if raw_turn is not None else pulse_id

    event_id = _tag_value(tags, "event")
    if not event_id:
        session_ref = _tag_value(tags, "session")
        if session_ref and session_ref != scope_id:
            event_id = session_ref
    if not event_id:
        match = _SESSION_RE.search(content or "")
        event_id = match.group(1).strip() if match else None

    if not scope_id:
        scope_id = created_at[:10] if created_at else None
    raw_chunk = _tag_value(tags, "chunk")
    try:
        chunk_index = int(raw_chunk) if raw_chunk is not None else None
    except (TypeError, ValueError):
        chunk_index = None
    return scope_id, turn_id, event_id, chunk_index


def normalize_ref(ref: Any) -> Optional[str]:
    """Resolve a provenance reference to a corpus item id.

    `memory_refs` stores raw journal ids (`17`, `"17"`) while the SemanticIndex
    and this corpus key memories as `mem_17` (PhysicsEngine.memory_point_id).
    Belief references are already ids and pass through unchanged. Without this
    translation every memory_refs edge silently fails to match and provenance
    suppression never fires.
    """
    if ref is None:
        return None
    if isinstance(ref, bool):
        return None
    if isinstance(ref, int):
        # -1 is the Curator's "no source memory" sentinel (curator.py:984),
        # not a journal id.
        return f"mem_{ref}" if ref >= 0 else None
    ref = str(ref).strip()
    if not ref or ref == "-1":
        return None
    if ref.startswith("mem_"):
        return ref
    if _BARE_NUMBER_RE.match(ref):
        return f"mem_{ref}"
    return ref


class HelixCorpus:
    """One flat, tiered pool over BeliefStore + CognitiveJournal + SemanticIndex."""

    def __init__(
        self,
        belief_store,
        memory_manager=None,
        physics_engine=None,
        include_memories: bool = True,
        max_memories: Optional[int] = None,
    ):
        self._beliefs = belief_store
        self._memory = memory_manager
        self._physics = physics_engine
        self.include_memories = include_memories
        # None = no cap. When set, only the most recent N memories are pooled;
        # useful for bounding query latency on very long-lived minds at the
        # cost of deep recall.
        self.max_memories = max_memories

        # Monotonic mutation counter. Consumers (the semantic lane's sync)
        # skip work when this has not moved.
        self.version = 0

        self._items: List[Dict[str, Any]] = []
        self._by_id: Dict[str, Dict[str, Any]] = {}

        # Belief-side invalidation: the same (count, total mass) signal
        # Preconscious._ensure_belief_cache uses, which catches merges,
        # attrition and confidence decay rather than only add/remove.
        self._belief_count = -1
        self._belief_mass = -1.0

        # Journal-side invalidation: the journal is append-only, so we track a
        # byte offset and read only what is new. compact() rewrites the file
        # smaller, which we detect and treat as a full reload.
        self._journal_offset = 0
        self._belief_items: List[Dict[str, Any]] = []
        self._memory_items: List[Dict[str, Any]] = []

        self._tags_cache: Dict[str, List[str]] = {}

    # ── Pool ─────────────────────────────────────────────────────────

    def all_items(self) -> List[Dict[str, Any]]:
        """The full pool, rebuilt only when a store has actually changed."""
        self._refresh()
        return self._items

    def get(self, item_id: str) -> Optional[Dict[str, Any]]:
        self._refresh()
        return self._by_id.get(item_id)

    def _refresh(self):
        beliefs_changed = self._refresh_beliefs()
        memories_changed = self._refresh_memories()
        if not (beliefs_changed or memories_changed):
            return

        self._items = self._belief_items + self._memory_items
        self._by_id = {item["id"]: item for item in self._items}
        self.version += 1

        logger.debug(
            "Corpus rebuilt: %d items (%d beliefs, %d memories)",
            len(self._items), len(self._belief_items), len(self._memory_items),
        )

    def _refresh_beliefs(self) -> bool:
        try:
            all_beliefs = self._beliefs.get_all_beliefs_flat()
        except Exception as e:
            logger.warning("Belief pool refresh failed: %s", e)
            return False

        count = len(all_beliefs)
        mass = sum(b.get("mass", 1.0) for b in all_beliefs)
        if count == self._belief_count and abs(mass - self._belief_mass) < 0.01:
            return False

        items = []
        for b in all_beliefs:
            content = b.get("content", "")
            bid = b.get("id")
            if not bid or not content or len(content) < 5:
                continue
            category = b.get("_category", "")
            term = b.get("term", "") or ""
            tier = 2 if (term and category in _TIER2_CATEGORIES) else 1
            lagrangian = b.get("encoding_lagrangian", {}) or {}
            if not isinstance(lagrangian, dict):
                lagrangian = {}
            items.append({
                "id": bid,
                "content": content,
                "tier": tier,
                "_category": category,
                "relevance": b.get("mass", 1.0),
                "term": term,
                "aliases": b.get("aliases", []) or [],
                "tags": b.get("tags", []) or [],
                "memory_refs": b.get("memory_refs", []) or [],
                "component_ids": b.get("component_ids", []) or [],
                "relations": b.get("relations", []) or [],
                "belief_ids": [],
                "formation_type": b.get("formation_type", ""),
                "maintenance_session": b.get("maintenance_session", ""),
                "position_8d": b.get("position_8d") or [],
                "created_at": b.get("created_at", ""),
                "source": b.get("source", ""),
                "record_kind": "belief",
                "direction": "internal",
                "visibility": "private",
                "epistemic_role": "derived_belief",
                "evidence_scopes": ["derived_belief"],
                "action_status": "derived",
                "retrieval_text": content,
                "caused_by": list(b.get("memory_refs", []) or []),
                # These fields must survive the mRAG adapter.  The semantic
                # lane primarily ranks for factual accuracy, while the
                # associative complement uses the original affect/stability
                # state to choose which representative of a learned cluster
                # is most salient.
                "confidence": b.get("confidence", 0.5),
                "stability_index": b.get("stability_index", 0.5),
                "encoding_lagrangian": lagrangian,
                "affective_salience": self._affective_salience(lagrangian),
                # Beliefs have no conversational position — adjacency is a
                # Tier-0 mechanic only.
                "session_id": None,
                "scope_id": None,
                "turn_id": None,
                "event_id": None,
                "chunk_index": None,
            })

        self._belief_items = items
        self._belief_count = count
        self._belief_mass = mass
        self._tags_cache = {
            k: v for k, v in self._tags_cache.items()
            if k in {i["id"] for i in items} or k.startswith("mem_")
        }
        return True

    def _refresh_memories(self) -> bool:
        if not self.include_memories or self._memory is None:
            return False

        journal = getattr(self._memory, "journal", None)
        path = getattr(journal, "path", None) if journal else None
        if path is None or not path.exists():
            return False

        journal_lock = getattr(journal, "_lock", None)
        with journal_lock if journal_lock is not None else nullcontext():
            try:
                size = os.path.getsize(path)
            except OSError:
                return False

            if size == self._journal_offset:
                return False
            if size < self._journal_offset:
                # compact() rewrote the file — everything must be re-read.
                self._journal_offset = 0
                self._memory_items = []

            new_entries = self._read_journal_from(path, self._journal_offset)
        if not new_entries:
            return False

        for entry in new_entries:
            if entry.get("type") != "memory":
                continue
            content = entry.get("content", "")
            journal_id = entry.get("id", "")
            if not journal_id or not content or len(content) < 5:
                continue
            meta = entry.get("metadata", {}) or {}
            lagrangian = entry.get("lagrangian", {}) or {}
            if not isinstance(lagrangian, dict):
                lagrangian = {}
            point_id = meta.get("point_id") or f"mem_{journal_id}"
            pulse_id = entry.get("pulse_id", 0)
            created_at = meta.get("created_at") or entry.get("timestamp") or ""
            tags = meta.get("tags", []) or []
            scope_id, turn_id, event_id, chunk_index = _structured_position(
                content, tags, created_at, pulse_id,
            )
            envelope = envelope_from_metadata(content, meta)
            item = {
                "id": point_id,
                "content": content,
                "tier": 0,
                "_category": "memory",
                # Memories carry importance rather than cognitive mass; it
                # plays the same role as a tie-breaker in ranking.
                "relevance": meta.get("importance", 0.5),
                "term": "",
                "aliases": [],
                "tags": tags,
                "memory_refs": [],
                "component_ids": [],
                "relations": [],
                "belief_ids": meta.get("belief_ids", []) or [],
                "position_8d": entry.get("position_8d") or [],
                "created_at": created_at,
                "source": meta.get("source", ""),
                "memory_type": meta.get("memory_type", ""),
                "stability_index": meta.get("stability_index", 0.5),
                "encoding_lagrangian": lagrangian,
                "affective_salience": self._affective_salience(lagrangian),
                # Strong importer boundaries win; ordinary Helix memories
                # retain the creation-date/pulse fallback.
                "session_id": scope_id,
                "scope_id": scope_id,
                "turn_id": turn_id,
                "event_id": event_id,
                "chunk_index": chunk_index,
                "pulse_id": pulse_id,
                "record_envelope": envelope,
            }
            item.update(envelope)
            self._memory_items.append(item)

        # The journal appends a new line per update rather than mutating, so
        # the same id can appear more than once; keep the newest.
        deduped: Dict[str, Dict[str, Any]] = {}
        for item in self._memory_items:
            deduped[item["id"]] = item
        self._memory_items = list(deduped.values())

        if self.max_memories is not None and len(self._memory_items) > self.max_memories:
            self._memory_items = self._memory_items[-self.max_memories:]

        self._journal_offset = size
        return True

    @staticmethod
    def _affective_salience(lagrangian: Dict[str, Any]) -> float:
        """Return bounded encoding-state intensity, independent of valence.

        A calm/stable memory and an acutely destabilizing one can both matter.
        Using distance from the omega baseline plus systemic load preserves
        that distinction without making affect compete directly with mRAG's
        semantic score.

        Surprise is folded in as a third term, so a pulse where stability
        moved sharply encodes heavier than a routine one. That is how a
        correction earns durability without anyone counting repetitions.

        Note on D_KL: deliberately NOT used. Despite reading like prediction
        error, compute_kl_divergence measures the gap between the gravity
        distribution at current attention and the one at the identity centre
        — how far attention wandered from self, not how wrong an expectation
        turned out to be. A live run measured it spanning only 0.094-0.173,
        so it carries almost no discriminating range either.
        """
        try:
            omega = max(0.0, min(1.0, float(lagrangian.get("omega", 0.5))))
            s_total = max(0.0, min(1.0, float(lagrangian.get("s_total", 0.15))))
            surprise = HelixCorpus._surprise(lagrangian)
            return min(
                1.0,
                (2.0 * abs(omega - 0.5) * 0.50)
                + (s_total * 0.25)
                + (surprise * 0.25),
            )
        except (TypeError, ValueError):
            return 0.0

    # Normaliser for pulse-to-pulse stability change. Set from a live run:
    # typical |delta_s| 0.185, notable 0.481, largest observed 0.691. Dividing
    # by the observed maximum puts a routine pulse near 0.26 and a genuinely
    # large shift at 1.0.
    _SURPRISE_SCALE = 0.7

    @staticmethod
    def _surprise(lagrangian: Dict[str, Any]) -> float:
        """How much stability moved since the previous pulse, 0-1.

        Magnitude, not sign: something unexpectedly working is as surprising
        as something unexpectedly failing, and both deserve to be recalled.
        Records written before delta_s existed report 0.0 and are simply
        unweighted rather than penalised.
        """
        try:
            delta = abs(float(lagrangian.get("delta_s", 0.0)))
        except (TypeError, ValueError):
            return 0.0
        return min(1.0, delta / HelixCorpus._SURPRISE_SCALE)

    @staticmethod
    def _read_journal_from(path, offset: int) -> List[Dict[str, Any]]:
        """Read journal entries starting at a byte offset.

        Deliberately skips CognitiveJournal.load_all(), which re-reads and
        re-checksums the entire file. The journal grows every pulse, so a full
        reload per query would dominate retrieval cost on any long-lived mind.
        Checksums are verified by the journal on write; a torn final line is
        handled by the per-line JSON guard below.
        """
        import json

        entries: List[Dict[str, Any]] = []
        try:
            with open(path, "r", encoding="utf-8") as f:
                f.seek(offset)
                for raw in f:
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        entry = json.loads(raw)
                    except json.JSONDecodeError:
                        continue
                    entry.pop("checksum", None)
                    entries.append(entry)
        except OSError as e:
            logger.warning("Journal read failed at offset %d: %s", offset, e)
        return entries

    # ── Embeddings ───────────────────────────────────────────────────

    def embedding(self, item: Dict[str, Any]) -> Optional[np.ndarray]:
        """The item's native semantic L2-normalized embedding.

        SemanticIndex first (already normalized, written on ingest), then a
        native 1024D document embedding on the fly. The journal's 384D spatial
        vector is deliberately ineligible.
        """
        cached = item.get("_embedding")
        if cached is not None:
            return cached

        emb = None
        index = getattr(self._physics, "semantic_index", None) if self._physics else None
        item_id = item["id"]
        if index is not None and index.contains(item_id):
            emb = index._embeddings[index._id_to_idx[item_id]]

        if emb is None and self._physics is not None:
            try:
                from memory.mrag.semantic_lane import strip_timestamp_prefix
                emb = self._physics.embed_semantic_text(
                    strip_timestamp_prefix(
                        item.get("retrieval_text") or item.get("content", "")
                    ),
                    is_query=False,
                )
            except Exception as e:
                logger.debug("On-the-fly embed failed for %s: %s", item_id, e)
                return None

        if emb is None:
            return None

        emb = np.asarray(emb, dtype=np.float32)
        norm = float(np.linalg.norm(emb))
        if norm > 1e-8:
            emb = emb / norm
        item["_embedding"] = emb
        return emb

    # ── Conceptual tags ──────────────────────────────────────────────

    def conceptual_tags(self, item: Dict[str, Any]) -> List[str]:
        """spaCy conceptual tags, computed on first use and cached.

        Tagging the whole pool eagerly would put a spaCy parse in front of
        every corpus rebuild; only items that actually reach scoring get one.
        """
        item_id = item["id"]
        tags = self._tags_cache.get(item_id)
        if tags is not None:
            return tags
        try:
            from memory.mrag.tagger import extract_tags
            from memory.mrag.semantic_lane import strip_timestamp_prefix
            tags = extract_tags(strip_timestamp_prefix(
                item.get("retrieval_text") or item.get("content", "")
            )[:1000])
        except Exception as e:
            logger.debug("Tagging failed for %s: %s", item_id, e)
            tags = []
        self._tags_cache[item_id] = tags
        return tags

    # ── Provenance ───────────────────────────────────────────────────

    def provenance_edges(self, item: Dict[str, Any]) -> Set[str]:
        """Every corpus item this one is compositionally linked to.

        Union of the constituent edges the Curator writes (memory_refs →
        Tier-0 sources, component_ids → constituent beliefs, relations →
        related beliefs) and the reverse edge memories carry (belief_ids).
        Direction is deliberately not distinguished: the merge layer resolves
        who wins by rank, so it only needs to know that two items describe the
        same underlying material.
        """
        edges: Set[str] = set()
        for field in ("memory_refs", "component_ids", "relations", "belief_ids"):
            for ref in item.get(field, []) or []:
                normalized = normalize_ref(ref)
                if normalized and normalized != item["id"]:
                    edges.add(normalized)
        return edges

    # ── Expansion maps (write-path features not yet ported) ──────────

    def get_all_concept_expansions(self) -> Dict[str, List[str]]:
        """Learned category -> concrete-instance vocabulary.

        Empty until mRAG's learn_concept_expansion is ported onto Helix's
        write path; the lane's built-in defaults and lexicon-derived
        expansions cover the same role meanwhile.
        """
        return {}

    def get_all_relation_expansions(self) -> Dict[str, Dict[str, List[str]]]:
        """Learned (subject, relation) -> named-entity vocabulary. See above."""
        return {}

    # ── Telemetry ────────────────────────────────────────────────────

    def record_usage(self, injected_ids: List[str], lexicon_hit_ids: Optional[List[str]] = None):
        """Route reliance telemetry to Helix's own counters.

        Beliefs get touch_belief (access_count + last_accessed), which is what
        the Curator reads when deciding what to precipitate. Memories are
        skipped: their access tracking lives in the spatial mind, and the
        gravity lane already calls update_access on what it surfaces.
        """
        touched = 0
        for item_id in injected_ids or []:
            if not item_id or item_id.startswith("mem_"):
                continue
            try:
                belief = self._beliefs.get_belief(item_id)
                if belief:
                    self._beliefs.touch_belief(belief.get("_category", ""), item_id)
                    touched += 1
            except Exception as e:
                logger.debug("Usage telemetry failed for %s: %s", item_id, e)
        return touched
