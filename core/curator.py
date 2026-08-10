"""
Helix — Curator Engine (Background Dreaming & Belief Crystallization)

Replaces the legacy synchronous DreamEngine.
Implements asynchronous background execution and offloads synthesis to a lightweight auxiliary model.

Key Architectural Upgrades:
1. Background Execution: Runs asynchronously to avoid blocking the main pulse loop.
2. Auxiliary Model: Uses an isolated provider-aware session for synthesis.
3. Strict Belief Spec: Validates output against the belief_format_spec (15-250 chars, specific categories).
4. Co-Occurrence Wiring: Real-time Hebbian wiring via post-pulse hooks replaces batch UMAP/HDBSCAN.
   Nightly Phase 3 reads pre-built relation clusters for compound synthesis.
5. Layer 2 Precipitation: UMAP/HDBSCAN clustering identifies dense belief
   clusters that exceed the gravitational binding threshold (tied to expansion
   rate). These collapse into Layer 2 beliefs (people, skills, desires, concepts).
"""

import json
import re
import logging
import sqlite3
import os
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict, Any
import threading

# Co-occurrence clustering is now handled in real-time by
# core/co_occurrence_hook.py (Hebbian wiring). The nightly cycle
# reads pre-built clusters instead of running UMAP/HDBSCAN here.

logger = logging.getLogger("helix.core.curator")

import warnings
warnings.filterwarnings("ignore", category=UserWarning)

class Curator:
    """The background belief crystallization and memory consolidation system.
    
    Triggered by the pulse_loop during dormancy, it spawns a background thread
    to process recent logs, extract beliefs, cluster them, and update the belief_store
    without blocking Helix's active context window.
    """

    # Mean pairwise binding gravity a cluster must exceed to collapse
    # into a Layer 2 belief (see _precipitate_layer2 for derivation).
    PRECIPITATION_THRESHOLD = 3.0

    def __init__(
        self,
        physics_engine,
        belief_store,
        memory_manager,
        llm_client,
        data_dir: str = "data",
        case_office=None,
    ):
        self.physics = physics_engine
        self.beliefs = belief_store
        self.memory = memory_manager
        self.llm_client = llm_client  # Auxiliary client (e.g., Gemini Flash)
        self.case_office = case_office
        self.data_dir = Path(data_dir)
        
        self.log_dir = self.data_dir / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # Concurrency safety
        self._is_running = False
        self._lock = threading.Lock()

    def run_nightly_cycle_async(self):
        """Spawns the nightly cycle in a background thread to prevent blocking the main pulse loop."""
        with self._lock:
            if self._is_running:
                logger.warning("Curator cycle already running. Skipping.")
                return
            self._is_running = True
            
        thread = threading.Thread(target=self._run_nightly_cycle, daemon=True)
        thread.start()
        logger.info("Started background Curator cycle thread.")

    def _run_nightly_cycle(self) -> Dict[str, Any]:
        """Execute the full background belief crystallization pipeline.

        Phases:
          1.   Collect Raw Memories (journals + thought logs)
          2.   Gemini Extraction & Classification → new_beliefs list
          2.5  Consolidation — merge new beliefs against existing store
          3.   UMAP/HDBSCAN Compounding (higher-order synthesis)
          4.   Validate & Integrate (only PASSed beliefs from 2.5)
        """
        stats = {
            "extracted": 0,
            "consolidated_merged": 0,
            "consolidated_passed": 0,
            "compounded": 0,
            "errors": 0
        }
        
        try:
            logger.info("Curator Phase 0: Entity Case Maintenance")
            try:
                stats["case_maintenance"] = self._run_case_maintenance()
            except Exception as e:
                logger.error("Entity case maintenance failed (continuing): %s", e)
                stats["case_maintenance"] = {"errors": 1}

            logger.info("Curator Phase 1: Collecting Raw Memories")
            raw_memories = self._collect_raw_memories()
            
            logger.info("Curator Phase 2: Gemini Extraction & Classification")
            new_beliefs = self._extract_beliefs(raw_memories)
            stats["extracted"] = len(new_beliefs)

            # Phase 2.2: Relation Building (Dual Filter)
            logger.info("Curator Phase 2.2: Relation Building")
            try:
                from core.belief_consolidator import build_relations
                for nb in new_beliefs:
                    injected_ids = nb.pop("injected_belief_ids", [])
                    nb["relations"] = build_relations(nb, injected_ids, self.beliefs)
            except Exception as e:
                logger.error(f"Relation building failed (continuing): {e}")

            # Phase 2.5: Consolidation — merge overlapping beliefs
            logger.info("Curator Phase 2.5: Belief Consolidation")
            try:
                from core.belief_consolidator import consolidate_new_beliefs

                consolidation = consolidate_new_beliefs(
                    new_beliefs=new_beliefs,
                    belief_store=self.beliefs,
                )
                stats["consolidated_merged"] = consolidation.get("merged", 0)
                stats["consolidated_passed"] = consolidation.get("passed", 0)

                # Only genuinely new beliefs proceed to integration
                new_beliefs = consolidation.get("passed_beliefs", new_beliefs)

            except Exception as e:
                logger.error(f"Consolidation phase failed (continuing): {e}")
                # On failure, all beliefs pass through unmerged
            
            logger.info("Curator Phase 3: Relation-Graph Compound Synthesis")
            compound_beliefs = self._synthesize_from_clusters()
            stats["compounded"] = len(compound_beliefs)
            
            logger.info("Curator Phase 4: Validating & Integrating")
            all_beliefs = new_beliefs + compound_beliefs
            validated_beliefs = self._validate_and_format(all_beliefs)
            self._integrate_to_store(validated_beliefs)

            # Phase 3.5: Layer 2 Precipitation (gravitational collapse)
            logger.info("Curator Phase 3.5: Layer 2 Precipitation")
            try:
                precipitated = self._precipitate_layer2()
                stats["precipitated"] = len(precipitated)
            except Exception as e:
                logger.error(f"Layer 2 precipitation failed (continuing): {e}")

            # Phase 6: Process Pending Beliefs
            #   The Curator writes candidates to pending_beliefs.json in Phase 4.
            #   The batch_service formats, validates, and commits them to the
            #   belief store. Must run AFTER Phase 4 — not as a parallel thread.
            logger.info("Curator Phase 6: Pending Belief Integration")
            try:
                from core.batch_service import process_pending_beliefs
                batch_stats = process_pending_beliefs(
                    self.beliefs,
                    physics_engine=self.physics,
                )
                stats["beliefs_integrated"] = batch_stats.get("beliefs_written", 0)
                stats["beliefs_rejected"] = batch_stats.get("rejected", 0)
            except Exception as e:
                logger.error(f"Pending belief integration failed: {e}")

            # Phase 7: Compile Tool Notes (Lane 1 of tool learning)
            #   Deterministic — the heaviest tool-bound beliefs (including
            #   any written tonight in Phase 6) become short "Learned:"
            #   notes on the tool schema descriptions. Runs AFTER
            #   integration and attrition so it reflects tonight's state.
            logger.info("Curator Phase 7: Tool Note Compilation")
            try:
                stats["tool_notes"] = self._compile_tool_notes()
            except Exception as e:
                logger.error(f"Tool note compilation failed: {e}")
            
        except Exception as e:
            logger.error(f"Curator cycle failed: {e}")
            stats["errors"] += 1
        finally:
            with self._lock:
                self._is_running = False
            logger.info("Curator cycle finished.")
            
        return stats

    def _run_case_maintenance(self) -> Dict[str, Any]:
        """File recent exact inputs/outputs and form source-linked summaries."""
        if self.case_office is None:
            return {"status": "disabled", "cycles": 0}
        from core.session_memory_maintenance import SessionMemoryMaintenance

        recent = []
        for item in self.case_office.corpus.all_items():
            if item.get("tier") != 0 or item.get("source") not in {
                "pulse_input", "pulse_output", "office_speaker", "focus_worker",
            }:
                continue
            created = str(item.get("created_at") or "")
            try:
                parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
                if parsed.tzinfo is not None:
                    parsed = parsed.astimezone().replace(tzinfo=None)
                if parsed < datetime.now() - timedelta(hours=24):
                    continue
            except (TypeError, ValueError):
                pass
            recent.append(item)
        if not recent:
            return {"status": "empty", "cycles": 0}

        grouped: Dict[str, List[Dict[str, Any]]] = {}
        for item in recent:
            session_id = str(
                item.get("session_id") or item.get("scope_id") or "recent"
            )
            grouped.setdefault(session_id, []).append(item)

        def worker(request):
            if not self.llm_client:
                return {}
            response = self.llm_client.generate(
                prompt=json.dumps(request, ensure_ascii=False),
                system_instruction=(
                    "Organize the session using explicit support only. Return JSON with "
                    "people, session, and views. People contain source-linked facets. "
                    "Session contains a concise overture and key_details. Views contain "
                    "subject/topic/relation kind, key, overture, key_details, and source_ids. "
                    "Every derived item cites source_ids; max two items per facet."
                ),
            )
            text = self._strip_code_fences(getattr(response, "text", "") or "")
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {}

        maintenance = SessionMemoryMaintenance(
            cases=self.case_office,
            belief_store=self.beliefs,
            worker=worker if self.llm_client else None,
        )
        cycle_stats = []
        # The coordinator, not individual desks, bounds board work.
        for session_id in sorted(grouped)[-32:]:
            cycle_stats.append(maintenance.run(session_id, grouped[session_id]))
        return {
            "status": "complete",
            "cycles": len(cycle_stats),
            "references_linked": sum(
                int(item.get("references_linked", 0)) for item in cycle_stats
            ),
            "profiles_written": sum(
                int(item.get("profiles_written", 0)) for item in cycle_stats
            ),
            "worker_failures": sum(
                1 for item in cycle_stats if item.get("worker_error")
            ),
        }

    # ── Entity Profile Maintenance ────────────────────────────────────

    def _find_existing_layer2_term(self, term: str):
        """Find the best existing Layer 2 entry for a term (or None).

        Prefers a consolidated profile entry; otherwise the heaviest
        same-term entry. Returns the belief dict tagged with _category.
        """
        tl = term.lower()
        best = None
        for cat in ("people", "concepts", "skills", "desires"):
            try:
                for b in self.beliefs._read_category(cat):
                    bt = (b.get("term") or "").lower()
                    aliases = {a.lower() for a in (b.get("aliases") or []) if a}
                    if bt != tl and tl not in aliases:
                        continue
                    b["_category"] = cat
                    if b.get("formation_type") == "profile_consolidation":
                        return b  # profiles always win
                    if best is None or b.get("mass", 1.0) > best.get("mass", 1.0):
                        best = b
            except Exception:
                continue
        return best

    def _merge_into_entity(self, existing, new_content, cand, members,
                           all_mem_refs=None):
        """Merge a precipitated realization into an existing entity entry.

        The LLM integrates the new understanding into the existing
        profile text (bounded); everything else is deterministic:
        mass accretes, verifications bump, refs/relations union.

        Returns the existing entry's id on success, None on failure.
        """
        existing_id = existing.get("id", "")
        old_content = existing.get("content", "")
        if not existing_id or not self.llm_client:
            return None

        prompt = (
            "EXISTING PROFILE:\n" + old_content + "\n\n"
            "NEW REALIZATION:\n" + new_content + "\n\n"
            "Integrate the new realization into the profile. Keep "
            "everything from the existing profile that is not directly "
            "superseded. Max 500 chars, plain text, same voice. "
            "Output ONLY the updated profile text."
        )
        try:
            response = self.llm_client.generate(
                prompt=prompt,
                system_instruction=(
                    "You maintain entity profiles by integrating new "
                    "understanding. Preserve existing wording where "
                    "possible. Output only the profile text."
                ),
            )
            merged = (response.text or "").strip().strip('"')[:500]
            if len(merged) < 40:
                raise ValueError("merged profile too short")
        except Exception as e:
            logger.error("Entity merge LLM failed for %s: %s", existing_id, e)
            return None

        # Deterministic bookkeeping
        refs = list(dict.fromkeys(
            (existing.get("memory_refs") or [])
            + [r for m in members for r in (m.get("memory_refs") or [])]
        ))[:80]
        relations = list(dict.fromkeys(
            (existing.get("relations") or [])
            + [m.get("id", "") for m in members if m.get("id")]
        ))[:60]
        new_mass = min(20.0, float(existing.get("mass", 1.0)) + 0.5 * float(cand["total_mass"]))

        self.beliefs.update_belief(
            existing_id,
            content=merged,
            mass=new_mass,
            verifications=float(existing.get("verifications", 1.0)) + 1.0,
            memory_refs=refs,
            relations=relations,
        )

        # Wire component beliefs to the entity anchor
        for m in members:
            rels = m.get("relations", []) or []
            if existing_id not in rels:
                rels.append(existing_id)
                self.beliefs.update_belief(m.get("id", ""), relations=rels)

        # Refresh the live manifold + semantic index with the new text
        if self.physics:
            try:
                emb = self.physics.embed_text(merged)
                pos = self.physics.embed_and_project(merged)
                self.beliefs.update_belief(
                    existing_id,
                    position_8d=[round(float(x), 6) for x in pos],
                )
                self.physics._register_point(
                    point_id=existing_id,
                    emb=emb,
                    point_type="belief",
                    spatial_kwargs={
                        "confidence": existing.get("confidence", 0.6),
                        "importance": new_mass,
                        "content": merged,
                    },
                    semantic_metadata={
                        "content": merged[:500],
                        "type": "belief",
                        "confidence": existing.get("confidence", 0.6),
                        "importance": new_mass,
                        "category": existing.get("_category", ""),
                    },
                )
            except Exception as e:
                logger.warning("Entity merge manifold refresh failed: %s", e)

        logger.info(
            "⭐ ENTITY DEEPENED [%s] %s: %s",
            existing.get("_category", ""), existing_id, merged[:80],
        )
        return existing_id

    # ── Tool Note Compilation (Phase 7) ──────────────────────────────

    # Per-tool budget for compiled notes
    TOOL_NOTES_MAX = 3          # notes per tool
    TOOL_NOTE_MAX_CHARS = 140   # per note

    def _compile_tool_notes(self) -> int:
        """Compile the strongest tool-bound beliefs into tool descriptions.

        Deterministic: no LLM. For each tool, take the top beliefs bound
        to it by mass × confidence, condense each to one short line, and
        write them to data/tool_learned_notes.json + the live registry.

        Beliefs are the source of truth — the description is a compiled
        view. A lesson that stops being verified loses confidence via
        nightly attrition and drops out of the description naturally.

        Returns the number of tools that received notes.
        """
        all_beliefs = self.beliefs.get_all_beliefs_flat()

        by_tool: Dict[str, list] = {}
        for b in all_beliefs:
            bindings = b.get("tool_bindings", [])
            if not isinstance(bindings, list):
                continue
            for t in bindings:
                if isinstance(t, str) and t.strip():
                    by_tool.setdefault(t.strip(), []).append(b)

        notes: Dict[str, list] = {}
        for tool, beliefs in by_tool.items():
            beliefs.sort(
                key=lambda b: b.get("mass", 1.0) * b.get("confidence", 0.5),
                reverse=True,
            )
            tool_notes = []
            for b in beliefs[: self.TOOL_NOTES_MAX]:
                content = (b.get("content", "") or "").strip()
                if not content:
                    continue
                if len(content) > self.TOOL_NOTE_MAX_CHARS:
                    # Cut at a sentence boundary if one exists in range
                    cut = content[: self.TOOL_NOTE_MAX_CHARS]
                    period = cut.rfind(". ")
                    if period > self.TOOL_NOTE_MAX_CHARS // 2:
                        cut = cut[: period + 1]
                    else:
                        cut = cut.rstrip() + "…"
                    content = cut
                tool_notes.append(content)
            if tool_notes:
                notes[tool] = tool_notes

        # Persist for boot-time reload
        notes_path = self.data_dir / "tool_learned_notes.json"
        try:
            notes_path.write_text(json.dumps({
                "updated_at": datetime.now().isoformat(),
                "notes": notes,
            }, indent=2))
        except Exception as e:
            logger.error("Failed to write tool notes file: %s", e)

        # Apply to the live registry (session declarations rebuild on
        # the morning wake — see pulse_loop DORMANT → RESTING).
        applied = 0
        try:
            from tools.tool_registry import registry
            applied = registry.apply_learned_notes(notes)
        except Exception as e:
            logger.warning("Could not apply notes to registry: %s", e)

        logger.info(
            "Phase 7: %d tools have learned notes (%d applied to registry)",
            len(notes), applied,
        )
        return applied

    def _precipitate_layer2(self) -> List[Dict[str, Any]]:
        """Phase 3.5: Gravitational collapse of Layer 1 clusters into Layer 2.

        1. Re-embed all L1 beliefs (384D via all-MiniLM-L6-v2)
        2. UMAP 384D → 5D for clustering
        3. HDBSCAN to find natural semantic clusters
        4. Compute mean pairwise binding gravity (8D) per cluster
        5. Precipitate clusters exceeding expansion-factor threshold

        Precipitation threshold = (1 + EXPANSION_PER_BELIEF)^total_beliefs
        This ties directly to the Hubble expansion rate — a cluster must be
        gravitationally bound against the cumulative drift.
        """
        import numpy as np
        from itertools import combinations

        # ── Step 0: Load all beliefs and check viability ─────────────
        all_beliefs = self.beliefs.get_all_beliefs_flat()
        beliefs_with_pos = [
            b for b in all_beliefs
            if b.get("position_8d") and len(b.get("position_8d", [])) == 8
        ]

        if len(beliefs_with_pos) < 20:
            logger.info("Phase 3.5: Too few positioned beliefs (%d) — skipping", len(beliefs_with_pos))
            return []

        total_beliefs = len(all_beliefs)
        # Fixed binding-gravity threshold. The previous formula
        # (1 + EXPANSION_PER_BELIEF) ** total_beliefs assumed Hubble
        # expansion inflates positions over time — but expansion was
        # never applied to any position, so the threshold grew
        # exponentially against static gravity and precipitation would
        # have silently stopped (~150 at 10k beliefs). 3.0 matches the
        # formula's value at the belief count where precipitation was
        # last observed working.
        threshold = self.PRECIPITATION_THRESHOLD
        logger.info(
            "Phase 3.5: %d beliefs, binding-gravity threshold %.2f",
            total_beliefs, threshold,
        )

        # ── Step 1: Re-embed from text content (384D) ────────────────
        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            embedder = DefaultEmbeddingFunction()
        except Exception as e:
            logger.error("Phase 3.5: Embedder unavailable: %s", e)
            return []

        texts = [b.get("content", "") for b in beliefs_with_pos]
        embeddings_384 = []
        batch_size = 128
        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            embs = embedder(batch)
            embeddings_384.extend(embs)

        matrix_384 = np.array(embeddings_384, dtype=np.float32)
        logger.info("Phase 3.5: Embedded %d beliefs (384D)", len(matrix_384))

        # ── Step 2: UMAP 384D → 5D ──────────────────────────────────
        try:
            import umap
            reducer = umap.UMAP(
                n_components=5, n_neighbors=15,
                min_dist=0.05, random_state=42,
            )
            embedding_5d = reducer.fit_transform(matrix_384)
        except Exception as e:
            logger.error("Phase 3.5: UMAP failed: %s", e)
            return []

        # ── Step 3: HDBSCAN clustering ───────────────────────────────
        try:
            import hdbscan
            clusterer = hdbscan.HDBSCAN(
                min_cluster_size=4, min_samples=3,
            )
            labels = clusterer.fit_predict(embedding_5d)
        except Exception as e:
            logger.error("Phase 3.5: HDBSCAN failed: %s", e)
            return []

        n_clusters = len(set(labels)) - (1 if -1 in labels else 0)
        noise = list(labels).count(-1)
        logger.info(
            "Phase 3.5: %d clusters found, %d noise points",
            n_clusters, noise,
        )

        # ── Step 4: Evaluate clusters for precipitation ──────────────
        positions = np.array(
            [b["position_8d"] for b in beliefs_with_pos], dtype=np.float32,
        )

        candidates = []
        cluster_audit = []

        for label in sorted(set(labels)):
            if label == -1:
                continue

            member_idx = np.where(labels == label)[0]
            members = [beliefs_with_pos[i] for i in member_idx]
            member_pos = positions[member_idx]
            member_masses = np.array([b.get("mass", 1.0) for b in members])

            # Compute mean pairwise binding gravity in 8D
            total_grav = 0.0
            pair_count = 0
            n = len(members)
            # Sample for large clusters
            sample_n = min(n, 30)
            if n <= 30:
                idxs = list(range(n))
            else:
                idxs = list(np.random.choice(n, 30, replace=False))

            for i, j in combinations(idxs, 2):
                d = float(np.linalg.norm(member_pos[i] - member_pos[j]))
                g = (member_masses[i] * member_masses[j]) / (d ** 2 + 1e-4)
                total_grav += g
                pair_count += 1

            mean_gravity = total_grav / max(pair_count, 1)
            total_mass = float(member_masses.sum())

            # Check if >50% of members already reference a Layer 2 entry
            layer2_referenced = 0
            for m in members:
                for rel in m.get("relations", []):
                    if any(rel.startswith(p) for p in ("ppl_", "skl_", "des_", "con_")):
                        layer2_referenced += 1
                        break
            already_precipitated = layer2_referenced > len(members) * 0.5

            cluster_info = {
                "cluster_id": int(label),
                "member_count": len(members),
                "member_ids": [m.get("id", "") for m in members],
                "mean_binding_gravity": round(mean_gravity, 2),
                "total_mass": round(total_mass, 2),
                "exceeds_threshold": mean_gravity > threshold,
                "already_precipitated": already_precipitated,
                "precipitated_as": None,
            }
            cluster_audit.append(cluster_info)

            if mean_gravity > threshold and not already_precipitated:
                candidates.append({
                    "cluster_info": cluster_info,
                    "members": members,
                    "member_pos": member_pos,
                    "member_masses": member_masses,
                    "mean_gravity": mean_gravity,
                    "total_mass": total_mass,
                })

        # Sort by binding gravity (densest first)
        candidates.sort(key=lambda x: -x["mean_gravity"])

        logger.info(
            "Phase 3.5: %d clusters exceed threshold (%.2f), %d eligible",
            sum(1 for c in cluster_audit if c["exceeds_threshold"]),
            threshold,
            len(candidates),
        )

        # ── Step 5: LLM synthesis + write Layer 2 ────────────────────
        precipitated = []

        for cand in candidates:
            members = cand["members"]
            member_pos = cand["member_pos"]
            member_masses = cand["member_masses"]

            # Build precipitation prompt
            belief_texts = [m.get("content", "") for m in members[:12]]
            prompt = (
                "These beliefs have been gravitationally clustering in my "
                "cognitive field. They represent fragments of a single deeper "
                "understanding. Collapse them into ONE dense realization — "
                "the concept beneath the language.\n\n"
                "BELIEFS:\n"
                + "\n".join(f"- {t}" for t in belief_texts)
                + "\n\nRules:\n"
                "- Extract the UNDERLYING CONCEPT, not a summary\n"
                "- Max 500 chars, plain text, no markdown\n"
                "- Assign category:\n"
                "    concepts: A consolidated conceptual understanding\n"
                "    people: A relational understanding of a person\n"
                "    skills: A proven procedure (To [goal]: [steps])\n"
                "    desires: A deep aspiration or long-term goal\n\n"
                "Output EXACTLY 2 lines:\n"
                "CATEGORY: [category]\n"
                "CONTENT: [the precipitated belief]\n"
            )

            try:
                response = self.llm_client.generate(
                    prompt=prompt,
                    system_instruction=(
                        "You collapse belief clusters into dense conceptual "
                        "anchors. Output exactly 2 lines: CATEGORY and CONTENT."
                    ),
                )
                raw = response.text.strip()
            except Exception as e:
                logger.error("Phase 3.5: LLM call failed: %s", e)
                continue

            # Parse response
            category = None
            content = None
            for line in raw.split("\n"):
                line = line.strip()
                if line.upper().startswith("CATEGORY:"):
                    cat = line.split(":", 1)[1].strip().lower().replace(" ", "_")
                    if cat in ("concepts", "people", "skills", "desires"):
                        category = cat
                elif line.upper().startswith("CONTENT:"):
                    content = line.split(":", 1)[1].strip().strip('"')

            if not category or not content or len(content) < 15:
                logger.warning("Phase 3.5: Failed to parse LLM output: %s", raw[:200])
                continue

            content = content[:500]  # Enforce Layer 2 max length

            # Compute centroid position (mass-weighted)
            weights = member_masses / (member_masses.sum() + 1e-8)
            centroid = (member_pos * weights[:, np.newaxis]).sum(axis=0)

            # Extract dominant term for preconscious string matching.
            # Corpus check keeps sentence-start captures ('Cognitive',
            # 'Internal') from becoming anchors that match every pulse.
            from core.belief_consolidator import (
                _extract_dominant_term, term_survives_corpus_check,
            )
            term = _extract_dominant_term(content) or ""
            if term and not term_survives_corpus_check(
                term, (b.get("content", "") for b in all_beliefs)
            ):
                logger.info("Phase 3.5: term '%s' failed corpus check — anchor suppressed", term)
                term = ""

            # ── Known entity? Deepen the profile instead of fragmenting ──
            # Precipitating a new same-term sibling is how one entity
            # became 94 scattered entries. If this term already has a
            # Layer 2 entry, merge tonight's realization INTO it.
            if term:
                existing = self._find_existing_layer2_term(term)
                if existing is not None:
                    merged_id = self._merge_into_entity(
                        existing, content, cand, members, all_mem_refs=None,
                    )
                    if merged_id:
                        precipitated.append({
                            "id": merged_id,
                            "category": existing.get("_category", ""),
                            "content": content,
                            "mass": cand["total_mass"],
                            "component_count": len(members),
                            "binding_gravity": cand["mean_gravity"],
                            "merged": True,
                        })
                        cand["cluster_info"]["precipitated_as"] = f"{merged_id} (merged)"
                        continue
                    # Merge failed — fall through and skip rather than
                    # spawn a duplicate entity entry. The realization
                    # survives in its Layer 1 component beliefs.
                    logger.warning(
                        "Phase 3.5: merge into existing '%s' failed — skipping to avoid fragmentation",
                        term,
                    )
                    continue

            # Aggregate metadata from cluster members
            member_omegas = []
            member_s_totals = []
            all_mem_refs = []
            member_stabilities = []

            for m in members:
                # stability_index
                member_stabilities.append(m.get("stability_index", 0.5))
                # encoding_lagrangian
                lag = m.get("encoding_lagrangian", {})
                if not isinstance(lag, dict):
                    lag = {}
                member_omegas.append(lag.get("omega", m.get("stability_index", 0.5)))
                member_s_totals.append(lag.get("s_total", 0.15))
                # memory_refs
                for r in m.get("memory_refs", []):
                    if r not in all_mem_refs:
                        all_mem_refs.append(r)

            # Compute means
            mean_stability = float(np.mean(member_stabilities)) if member_stabilities else 0.5
            mean_omega = float(np.mean(member_omegas)) if member_omegas else 0.5
            mean_s_total = float(np.mean(member_s_totals)) if member_s_totals else 0.15

            encoding_lag = {
                "omega": mean_omega,
                "s_total": mean_s_total,
                "H": 0.15,
                "D_KL": 0.0,
            }

            # Generate belief ID and write
            belief_id = self.beliefs.generate_id(category)
            stored = self.beliefs.add_belief(
                category=category,
                belief_id=belief_id,
                content=content,
                mass=cand["total_mass"],  # Summed mass — gravitational collapse
                confidence=0.6,
                source="precipitation_" + datetime.now().strftime("%Y-%m-%d"),
                stability_index=mean_stability,
                encoding_lagrangian=encoding_lag,
                memory_refs=all_mem_refs,
                position_8d=centroid.tolist(),
                term=term,
                aliases=[],
                formation_type="precipitation",
                component_ids=[m.get("id", "") for m in members],
                cluster_binding_gravity=cand["mean_gravity"],
            )

            if stored:
                # Register in the live manifold + semantic index so the
                # new anchor is retrievable without a restart.
                if self.physics:
                    try:
                        emb = self.physics.embed_text(content)
                        self.physics._register_point(
                            point_id=belief_id,
                            emb=emb,
                            point_type="belief",
                            spatial_kwargs={
                                "confidence": 0.6,
                                "importance": cand["total_mass"],
                                "content": content,
                                "encoding_omega": mean_omega,
                                "encoding_s_total": mean_s_total,
                                "stability_index": mean_stability,
                            },
                            semantic_metadata={
                                "content": content[:500],
                                "type": "belief",
                                "confidence": 0.6,
                                "importance": cand["total_mass"],
                                "category": category,
                            },
                        )
                    except Exception as e:
                        logger.warning(
                            "Phase 3.5: manifold registration failed for %s: %s",
                            belief_id, e,
                        )

                # Wire component beliefs to the new Layer 2 anchor
                for m in members:
                    existing_relations = m.get("relations", [])
                    if belief_id not in existing_relations:
                        existing_relations.append(belief_id)
                        self.beliefs.update_belief(
                            m.get("id", ""),
                            relations=existing_relations,
                        )

                precipitated.append({
                    "id": belief_id,
                    "category": category,
                    "content": content,
                    "mass": cand["total_mass"],
                    "component_count": len(members),
                    "binding_gravity": cand["mean_gravity"],
                })
                cand["cluster_info"]["precipitated_as"] = belief_id

                logger.info(
                    "⭐ PRECIPITATED [%s] %s (N=%d, G=%.1f, M=%.1f): %s",
                    category, belief_id, len(members),
                    cand["mean_gravity"], cand["total_mass"],
                    content[:80],
                )

        # ── Save cluster audit log ───────────────────────────────────
        try:
            audit_path = self.data_dir / "logs" / "manifold_clusters.json"
            audit_path.parent.mkdir(parents=True, exist_ok=True)
            audit_data = {
                "timestamp": datetime.now().isoformat(),
                "total_beliefs": total_beliefs,
                "expansion_factor": round(threshold, 4),
                "precipitation_threshold": round(threshold, 4),
                "clusters_found": n_clusters,
                "noise_points": noise,
                "precipitated": len(precipitated),
                "clusters": cluster_audit,
            }
            with open(audit_path, "w", encoding="utf-8") as f:
                json.dump(audit_data, f, indent=2)
            logger.info(
                "Phase 3.5 complete: %d precipitated, audit saved",
                len(precipitated),
            )
        except Exception as e:
            logger.error("Failed to save cluster audit: %s", e)

        return precipitated

    def _collect_raw_memories(self) -> List[Dict[str, Any]]:
        """Collect memories from the CognitiveJournal (JSONL) AND markdown journals.
        Returns dicts containing the text and metadata (lagrangian, belief_ids).
        """
        memories = []
        cutoff_time = (datetime.now() - timedelta(hours=24)).isoformat()

        # 1. CognitiveJournal (JSONL) — primary memory source
        #    The MemoryManager now uses CognitiveJournal (append-only JSONL),
        #    not the legacy SQLite DB. Read entries directly from the journal.
        if self.memory:
            try:
                journal = getattr(self.memory, 'journal', None)
                if journal and hasattr(journal, 'path') and journal.path.exists():
                    collected = 0
                    with journal.path.open("r", encoding="utf-8") as f:
                        for raw_line in f:
                            raw_line = raw_line.strip()
                            if not raw_line:
                                continue
                            try:
                                entry = json.loads(raw_line)
                            except json.JSONDecodeError:
                                continue

                            # Filter to last 24h
                            entry_ts = entry.get("timestamp", "")
                            # Compare ISO timestamps (both formats work with string comparison)
                            if entry_ts and entry_ts < cutoff_time:
                                continue

                            # Extract content and metadata
                            content = entry.get("content", "")
                            if not content or len(content) < 20:
                                continue

                            # Skip low-value system entries
                            entry_type = entry.get("type", "")
                            metadata = entry.get("metadata", {})
                            source = metadata.get("source", "")

                            # Only extract from the agent's actual thoughts and outbound messages.
                            # pulse_input = raw sensory data, system events, executive decisions (noise)
                            # pulse_output = the agent's monologue/thoughts (signal)
                            # helix_outbound = messages the agent sent (signal)
                            if source not in ("pulse_output", "helix_outbound"):
                                continue

                            # Include thoughts, memories, and events — skip pure system noise
                            snap = entry.get("lagrangian", {})
                            bids = metadata.get("belief_ids", [])

                            memories.append({
                                "text": content,
                                "memory_id": entry.get("id", -1),
                                "lagrangian_snapshot": snap,
                                "belief_ids": bids if isinstance(bids, list) else []
                            })
                            collected += 1

                    logger.info(f"Phase 1: extracted {collected} entries from CognitiveJournal (last 24h)")
                else:
                    logger.warning("memory_manager has no accessible CognitiveJournal")
            except Exception as e:
                logger.error(f"Failed to read CognitiveJournal: {e}")

        # 2. Journals (from project root journals directory)
        #    Journals live at ./journals/, not data/journals/
        try:
            journal_path = Path("journals")
            if not journal_path.exists():
                # Fallback: try relative to data_dir parent
                journal_path = self.data_dir.parent / "journals"
            if journal_path.exists():
                journal_count = 0
                for jfile in journal_path.glob("*.md"):
                    # Only read journals modified in the last 24h
                    if jfile.stat().st_mtime > datetime.now().timestamp() - 86400:
                        with open(jfile, "r", encoding="utf-8") as f:
                            memories.append({
                                "text": f"Journal {jfile.name}: {f.read()}",
                                "memory_id": -1,
                                "lagrangian_snapshot": {},
                                "belief_ids": []
                            })
                            journal_count += 1
                logger.info(f"Phase 1: collected {journal_count} recent journals")
            else:
                logger.warning(f"No journals directory found at {journal_path}")
        except Exception as e:
            logger.error(f"Failed to fetch journals: {e}")
            
        logger.info(f"Phase 1 total: {len(memories)} raw memories collected")
        return memories

    @staticmethod
    def _strip_code_fences(text: str) -> str:
        """Strip markdown code fences (```json ... ```) from LLM output."""
        text = text.strip()
        if text.startswith("```"):
            # Remove opening fence line
            first_nl = text.index("\n") if "\n" in text else len(text)
            text = text[first_nl + 1:]
        if text.endswith("```"):
            text = text[:-3].rstrip()
        return text

    def _extract_beliefs(self, memories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Uses the auxiliary LLM to extract beliefs from raw memories.

        Batches memories into groups to minimize API calls. Each batch is
        sent as a single prompt with numbered entries, and the LLM returns
        beliefs for the entire batch.
        """
        extracted = []
        BATCH_SIZE = 15  # ~15 memories per call balances context vs. call count

        # This prompt enforces the belief_format_spec.md
        system_prompt = """
        You are the Curator. Extract durable beliefs from the provided memories.
        Strict Rules:
        1. Plain text only (no markdown, no bold, no asterisks, no numbers).
        2. Single statement per belief.
        3. Length: 15-250 characters.
        4. Must fall into one of these categories:
           - premises: Foundational truths, axioms, self-observations, abilities (I am..., I can..., [declarative fact])
           - propositions: Learned or derived facts, conditional rules, knowledge about others ([Name]..., If X then Y)
           - preferences: Values, likes, behavioral norms (I want/prefer/value...)
        5. Skip trivial system logs, sensor readings, and status messages.
           Only extract genuinely meaningful beliefs worth remembering.
        6. For each belief, include the source memory index (0-based) in a "src" field.
        7. Each belief MUST STAND ALONE with zero surrounding context — name the
           specific person, tool, or project; never "this", "that issue", or
           "the recent problem". It will be recalled months from now.
        8. Preserve the original wording where possible — reformat the memory's
           own phrasing into a belief, do not reinterpret it.
           
        Output ONLY a raw JSON list: [{"category": "...", "content": "...", "src": 0}]
        No markdown, no code fences, no explanation. Just the JSON array.
        If no meaningful beliefs can be extracted, return an empty array: []
        """

        # Chunk memories into batches
        batches = [memories[i:i + BATCH_SIZE] for i in range(0, len(memories), BATCH_SIZE)]
        logger.info(f"Phase 2: processing {len(memories)} memories in {len(batches)} batches (batch_size={BATCH_SIZE})")

        for batch_idx, batch in enumerate(batches):
            try:
                # Build numbered prompt with all memories in this batch
                prompt_lines = [f"Extract beliefs from these {len(batch)} memories:\n"]
                for j, mem_obj in enumerate(batch):
                    # Truncate very long memories to avoid context overflow
                    text = mem_obj["text"][:1500]
                    prompt_lines.append(f"--- Memory {j} ---")
                    prompt_lines.append(text)
                prompt_lines.append(f"\n--- End of {len(batch)} memories ---")

                prompt = "\n".join(prompt_lines)
                response = self.llm_client.generate(prompt=prompt, system_instruction=system_prompt)
                raw_text = self._strip_code_fences(response.text)
                parsed = json.loads(raw_text)

                # Attach metadata to each extracted belief
                for p in parsed:
                    if not isinstance(p, dict):
                        continue
                    # Map src index back to the original memory in this batch
                    src_idx = p.pop("src", 0)
                    if 0 <= src_idx < len(batch):
                        source_mem = batch[src_idx]
                    else:
                        source_mem = batch[0]

                    p["memory_refs"] = [source_mem["memory_id"]] if source_mem["memory_id"] != -1 else []
                    p["encoding_lagrangian"] = source_mem.get("lagrangian_snapshot", {})
                    p["injected_belief_ids"] = source_mem.get("belief_ids", [])

                extracted.extend([p for p in parsed if isinstance(p, dict)])
                logger.info(f"Phase 2: batch {batch_idx + 1}/{len(batches)} → {len(parsed)} beliefs")

            except json.JSONDecodeError as e:
                logger.warning(f"Phase 2: batch {batch_idx + 1} JSON parse failed: {e}")
            except Exception as e:
                logger.error(f"Phase 2: batch {batch_idx + 1} extraction failed: {e}")

        logger.info(f"Phase 2: total {len(extracted)} beliefs extracted from {len(memories)} memories")
        return extracted

    def _synthesize_from_clusters(self) -> List[Dict[str, Any]]:
        """Synthesizes higher-order insights from pre-built co-occurrence clusters.

        Reads clusters built by the real-time co_occurrence_hook (Hebbian wiring)
        and sends each cluster to the LLM for compound belief synthesis.
        Falls back to direct relation-graph traversal if no co-occurrence
        tracker is available.
        """
        # Try to get pre-built clusters from the co-occurrence hook
        clusters = []
        try:
            from core.co_occurrence_hook import get_tracker
            tracker = get_tracker()
            if tracker:
                clusters = tracker.get_current_clusters()
                logger.info("Phase 3: Found %d pre-built co-occurrence clusters", len(clusters))
        except ImportError:
            logger.warning("Co-occurrence hook not available — skipping compound synthesis")
        except Exception as e:
            logger.error("Failed to read co-occurrence clusters: %s", e)

        if not clusters:
            # Fallback: find beliefs with 3+ existing relations (already wired)
            existing = self.beliefs.get_all_beliefs_flat()
            well_connected = [
                b for b in existing
                if len(b.get("relations", [])) >= 3
            ]
            if well_connected:
                # Group by shared relations (simple connected-component approach)
                logger.info(
                    "Phase 3 fallback: %d well-connected beliefs for synthesis",
                    len(well_connected),
                )
                # Each well-connected belief + its relations = a mini-cluster
                for b in well_connected[:5]:  # Cap at 5 to avoid API spam
                    cluster = [b["id"]] + b.get("relations", [])[:6]
                    clusters.append(cluster)

        if not clusters:
            logger.info("Phase 3: No clusters found — skipping compound synthesis")
            return []

        # Synthesize per cluster (same LLM logic as before)
        compounds = []
        for cluster_ids in clusters:
            # Fetch belief contents for the cluster
            cluster_beliefs = []
            for bid in cluster_ids:
                belief = self.beliefs.get_belief(bid)
                if belief and belief.get("content"):
                    cluster_beliefs.append(belief["content"])

            if len(cluster_beliefs) < 2:
                continue

            prompt = "Synthesize these related beliefs into ONE single higher-order realization.\n"
            prompt += "Do not restate the premises. Extract the novel realization.\n"
            prompt += "Follow strict format rules: 15-250 chars, plain text, no markdown.\n"
            prompt += "\n".join(cluster_beliefs)

            try:
                response = self.llm_client.generate(prompt=prompt)
                raw_text = self._strip_code_fences(response.text)
                content = raw_text.strip().replace("**", "")
                if content and 15 <= len(content) <= 300:
                    compounds.append({
                        "category": "propositions",
                        "content": content,
                        "source": "co_occurrence_synthesis",
                    })
            except Exception as e:
                logger.error("Compound synthesis failed for cluster: %s", e)

        return compounds

    def _validate_and_format(self, beliefs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enforces the belief_format_spec.md rules."""
        valid = []
        for b in beliefs:
            content = b.get('content', '').strip()
            
            # Rule 1: Strip markdown
            content = content.replace('**', '').replace('*', '').replace('→', '').strip()
            # Remove numbered prefixes if any
            if content and content[0].isdigit() and content[1:3] == '. ':
                content = content[3:].strip()
                
            # Rule 3: Length
            if len(content) < 15 or len(content) > 250:
                continue
                
            b['content'] = content
            valid.append(b)
            
        return valid

    def _integrate_to_store(self, beliefs: List[Dict[str, Any]]):
        """Pass beliefs to pending_beliefs.json for batch_service integration, and run attrition."""
        pending_file = self.data_dir / "pending_beliefs.json"
        existing_pending = []
        if pending_file.exists():
            try:
                existing_pending = json.loads(pending_file.read_text())
            except Exception:
                pass
                
        for b in beliefs:
            encoding_lag = b.get("encoding_lagrangian", {})
            stability = encoding_lag.get("omega", 0.5)
            candidate = {
                "content": b['content'],
                "category": b.get('category', 'propositions'),
                "status": "pending",
                "detected_at": datetime.now().isoformat(),
                "memory_refs": b.get("memory_refs", []),
                "encoding_lagrangian": encoding_lag,
                "stability_index": b.get("stability_index", stability),
            }
            existing_pending.append(candidate)
            
        try:
            pending_file.write_text(json.dumps(existing_pending, indent=2))
        except Exception as e:
            logger.error(f"Failed to write pending beliefs: {e}")
            
        # Run Attrition Phase
        try:
            attrition_stats = self.beliefs.recalculate_all_confidences()
            logger.info(f"Attrition pass complete: {attrition_stats}")
        except Exception as e:
            logger.error(f"Failed to run attrition: {e}")
