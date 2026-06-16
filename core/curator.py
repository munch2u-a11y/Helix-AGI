"""
Helix — Curator Engine (Background Dreaming & Belief Crystallization)

Replaces the legacy synchronous DreamEngine.
Implements asynchronous background execution and offloads synthesis to a lightweight auxiliary model.

Key Architectural Upgrades:
1. Background Execution: Runs asynchronously to avoid blocking the main pulse loop.
2. Auxiliary Model: Uses a faster, cheaper model (e.g., Gemini Flash) for synthesis.
3. Strict Belief Spec: Validates output against the belief_format_spec (15-250 chars, specific categories).
4. Co-Occurrence Wiring: Real-time Hebbian wiring via post-pulse hooks replaces batch UMAP/HDBSCAN.
   Nightly Phase 3 reads pre-built relation clusters for compound synthesis.
5. Layer 2 Precipitation: UMAP/HDBSCAN clustering identifies dense belief
   clusters that exceed a density threshold. These are consolidated into
   Layer 2 beliefs (people, skills, desires, concepts).
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

    def __init__(
        self,
        physics_engine,
        belief_store,
        memory_manager,
        llm_client,
        data_dir: str = "data",
    ):
        self.physics = physics_engine
        self.beliefs = belief_store
        self.memory = memory_manager
        self.llm_client = llm_client  # Auxiliary client (e.g., Gemini Flash)
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
            
        except Exception as e:
            logger.error(f"Curator cycle failed: {e}")
            stats["errors"] += 1
        finally:
            with self._lock:
                self._is_running = False
            logger.info("Curator cycle finished.")
            
        return stats

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
        from core.belief_cosmology import EXPANSION_PER_BELIEF
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
        threshold = (1 + EXPANSION_PER_BELIEF) ** total_beliefs
        logger.info(
            "Phase 3.5: %d beliefs, expansion factor %.3f, threshold %.2f",
            total_beliefs, threshold, threshold,
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

            # Extract dominant term for preconscious string matching
            from core.belief_consolidator import _extract_dominant_term
            term = _extract_dominant_term(content) or ""

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
        """Collect memories from structured journals AND thought output logs.
        Skips redundant scanning of the transient scratchpad.
        Returns dicts containing the text and metadata (lagrangian, belief_ids).
        """
        memories = []
        
        # 1. Thought Output Logs (from memory_manager's SQLite DB)
        if self.memory:
            try:
                cutoff_time = (datetime.now() - timedelta(hours=24)).isoformat()
                # MemoryManager uses per-call connections via sqlite3.connect(db_path),
                # not a persistent self.conn. Create our own connection.
                db_path = getattr(self.memory, 'db_path', None)
                if db_path and os.path.exists(db_path):
                    conn = sqlite3.connect(db_path)
                    try:
                        cursor = conn.cursor()
                        cursor.execute(
                            "SELECT id, content, lagrangian_snapshot, belief_ids "
                            "FROM long_term WHERE memory_type='thought' AND created_at >= ?", 
                            (cutoff_time,)
                        )
                        rows = cursor.fetchall()
                        for row in rows:
                            mem_id, content, snap_json, bids_json = row
                            
                            try:
                                snap = json.loads(snap_json) if snap_json else {}
                            except:
                                snap = {}
                                
                            try:
                                bids = json.loads(bids_json) if bids_json else []
                            except:
                                bids = []
                                
                            memories.append({
                                "text": content,
                                "memory_id": mem_id,
                                "lagrangian_snapshot": snap,
                                "belief_ids": bids
                            })
                        logger.info(f"Phase 1: extracted {len(rows)} thoughts from last 24h")
                    finally:
                        conn.close()
                else:
                    logger.warning(f"memory_manager db_path not found: {db_path}")
            except Exception as e:
                logger.error(f"Failed to fetch thought output logs: {e}")
                
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
        """Uses the auxiliary LLM to extract beliefs from raw memories."""
        extracted = []
        
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
           
        Output ONLY a raw JSON list: [{"category": "...", "content": "..."}]
        No markdown, no code fences, no explanation. Just the JSON array.
        """
        
        for mem_obj in memories:
            try:
                response = self.llm_client.generate(prompt=mem_obj["text"], system_instruction=system_prompt)
                raw_text = self._strip_code_fences(response.text)
                parsed = json.loads(raw_text)
                
                # Attach metadata to each extracted belief
                for p in parsed:
                    if not isinstance(p, dict):
                        continue
                    p["memory_refs"] = [mem_obj["memory_id"]] if mem_obj["memory_id"] != -1 else []
                    p["encoding_lagrangian"] = mem_obj.get("lagrangian_snapshot", {})
                    p["injected_belief_ids"] = mem_obj.get("belief_ids", [])
                    
                extracted.extend([p for p in parsed if isinstance(p, dict)])
            except Exception as e:
                logger.error(f"Extraction failed for memory: {e}")
                
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
