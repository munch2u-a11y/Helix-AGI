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
                    lexicon_path=self.data_dir / "beliefs" / "lexicon.json",
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

            # Phase 5: Lexicon Synchronization (term frequency + mass threshold)
            logger.info("Curator Phase 5: Lexicon Synchronization")
            try:
                lexicon_updates = self._sync_lexicon()
                stats["lexicon_created"] = lexicon_updates.get("created", 0)
                stats["lexicon_updated"] = lexicon_updates.get("updated", 0)
            except Exception as e:
                logger.error(f"Lexicon sync failed (continuing): {e}")

            # Phase 6: Journal Compaction
            logger.info("Curator Phase 6: Journal Compaction")
            try:
                if hasattr(self.memory, "compact_journal"):
                    stats["journal_compacted"] = self.memory.compact_journal()
                else:
                    logger.warning("memory_manager does not support journal compaction yet.")
            except Exception as e:
                logger.error(f"Journal compaction failed (continuing): {e}")
            
        except Exception as e:
            logger.error(f"Curator cycle failed: {e}")
            stats["errors"] += 1
        finally:
            with self._lock:
                self._is_running = False
            logger.info("Curator cycle finished.")
            
        return stats

    def _sync_lexicon(self) -> Dict[str, int]:
        """Phase 5: Sync the Lexicon star map with the belief graph.

        Two deterministic triggers (no LLM decision-making):

        1. Term Frequency: If a proper noun appears in 5+ beliefs but
           has no Lexicon entry, gather those beliefs and send them
           through the standard merge LLM (same prompt, 500-char cap)
           to synthesize a Lexicon summary.

        2. Mass Threshold: If any single belief crosses mass >= 5.0
           and its dominant term has no Lexicon entry, same treatment.

        All routing is pure Python. The LLM only does natural language
        synthesis — it doesn't know about the Lexicon.
        """
        from collections import Counter
        from core.belief_consolidator import (
            _tokenize, _is_proper_noun, _divert_to_lexicon,
            _call_gemini, _LEXICON_MASS_THRESHOLD,
            _LEXICON_TERM_FREQ_THRESHOLD, _LEXICON_MAX_LENGTH,
        )

        lexicon_path = self.data_dir / "beliefs" / "lexicon.json"
        stats = {"created": 0, "updated": 0}

        # Load current lexicon terms to know what's already covered
        try:
            with open(lexicon_path, "r", encoding="utf-8") as f:
                lex_entries = json.load(f)
        except Exception:
            lex_entries = []

        covered_terms = set()
        for entry in lex_entries:
            covered_terms.add(entry.get("term", "").lower())
            for alias in entry.get("aliases", []):
                covered_terms.add(alias.lower())

        # Load all beliefs
        all_beliefs = self.beliefs.get_all_beliefs_flat()

        # ── Extract multi-word terms + filter noise ──────────────────
        # 1. Strip possessive 's from words (Jean-Luc's → Jean-Luc)
        # 2. Detect multi-word terms (consecutive capitalized words)
        # 3. Track article usage: "the X" = named entity, "a/an X" = generic
        # 4. A term is noise if "a/an" precedes it more than "the" does

        from collections import defaultdict
        term_stats = defaultdict(lambda: {
            "display": "",        # original-case form
            "total": 0,           # total occurrences
            "mid_sentence": 0,    # occurrences NOT at sentence start
            "preceded_by_the": 0, # preceded by "the" (named entity signal)
            "preceded_by_a": 0,   # preceded by "a/an" (generic noun signal)
            "belief_ids": set(),  # which beliefs mention it
        })

        # Track which single words are part of multi-word terms
        # so we can grant them mid-sentence credit from their compound
        multiword_members = defaultdict(set)  # word_lower -> set of compound_lowers

        for b_idx, b in enumerate(all_beliefs):
            content = b.get("content", "")
            sentences = re.split(r'[.!?:;—]\s+', content)
            for sentence in sentences:
                raw_words = sentence.split()
                cleaned = []
                for w in raw_words:
                    c = re.sub(r"[^A-Za-z0-9_'-]", '', w)
                    # Strip possessive 's
                    if c.endswith("'s"):
                        c = c[:-2]
                    cleaned.append(c)

                i = 0
                while i < len(cleaned):
                    w = cleaned[i]
                    if len(w) > 1 and w[0].isupper() and not w.isupper():
                        # Look ahead for consecutive capitalized words
                        term_parts = [w]
                        j = i + 1
                        while j < len(cleaned):
                            nw = cleaned[j]
                            if len(nw) > 1 and nw[0].isupper() and not nw.isupper():
                                term_parts.append(nw)
                                j += 1
                            else:
                                break

                        term_str = " ".join(term_parts)
                        term_lower = term_str.lower()

                        ts = term_stats[term_lower]
                        if not ts["display"]:
                            ts["display"] = term_str
                        ts["total"] += 1
                        ts["belief_ids"].add(b_idx)

                        is_mid = i > 0
                        if is_mid:
                            ts["mid_sentence"] += 1

                        # Track article type
                        if i > 0:
                            prev = cleaned[i - 1].lower().strip("'\"()")
                            if prev == "the":
                                ts["preceded_by_the"] += 1
                            elif prev in ("a", "an"):
                                ts["preceded_by_a"] += 1

                        # Multi-word: record absorption + grant mid-sentence
                        # credit to component words
                        if len(term_parts) > 1:
                            for part in term_parts:
                                part_lower = part.lower()
                                multiword_members[part_lower].add(term_lower)
                                absorbed_key = f"_absorbed_{part_lower}"
                                term_stats[absorbed_key]["total"] += 1

                        i = j
                    else:
                        i += 1

        # Pass 2: Filter to genuine proper nouns/terms
        term_beliefs = {}
        for term_lower, ts in term_stats.items():
            if term_lower.startswith("_absorbed_"):
                continue

            # Minimum term length (filters "The", "An", "If", etc.)
            if len(term_lower.replace(" ", "")) < 3:
                continue

            # Mid-sentence check (with multi-word promotion):
            # A word passes if it appears mid-sentence itself, OR if
            # any multi-word term containing it appears mid-sentence
            has_mid = ts["mid_sentence"] > 0
            if not has_mid and " " not in term_lower:
                for compound_lower in multiword_members.get(term_lower, set()):
                    if term_stats[compound_lower]["mid_sentence"] > 0:
                        has_mid = True
                        break
            if not has_mid:
                continue

            # Indefinite article filter:
            # If "a/an" precedes this term MORE than "the" does,
            # it's likely a generic noun, not a coined concept.
            # "the Sentinel" = named. "a memory" = generic.
            if ts["preceded_by_a"] > ts["preceded_by_the"] and ts["preceded_by_a"] >= 2:
                continue

            # Skip if already in Lexicon
            if term_lower in covered_terms:
                continue

            # Absorption: skip single words mostly part of multi-word terms
            if " " not in term_lower:
                absorbed_count = term_stats.get(
                    f"_absorbed_{term_lower}", {}
                ).get("total", 0)
                # If the word has NO direct mid-sentence appearances
                # (only promoted via compounds), absorb it entirely
                if absorbed_count > 0 and ts["mid_sentence"] == 0:
                    continue
                # Also absorb if 40%+ of appearances are inside compounds
                if absorbed_count > 0 and absorbed_count >= ts["total"] * 0.4:
                    continue

            # Gather the actual belief contents
            belief_contents = [
                all_beliefs[idx].get("content", "")
                for idx in ts["belief_ids"]
            ]
            if len(belief_contents) >= _LEXICON_TERM_FREQ_THRESHOLD:
                term_beliefs[term_lower] = {
                    "term": ts["display"],
                    "beliefs": belief_contents,
                }

        for term_lower, data in term_beliefs.items():
            if len(data["beliefs"]) >= _LEXICON_TERM_FREQ_THRESHOLD:
                # Synthesize a summary from the top beliefs about this term
                belief_texts = data["beliefs"][:8]  # Cap at 8 for prompt size
                prompt = (
                    f"Combine these related statements about '{data['term']}' "
                    f"into ONE comprehensive summary (max {_LEXICON_MAX_LENGTH} chars). "
                    f"Plain text only, no markdown.\n\n"
                    + "\n".join(f"- {t}" for t in belief_texts)
                )
                summary = _call_gemini(prompt, system="You write concise summaries.")
                if summary:
                    summary = summary[:_LEXICON_MAX_LENGTH]
                    existed = any(
                        e.get("term", "").lower() == term_lower for e in lex_entries
                    )
                    _divert_to_lexicon(
                        term=data["term"],
                        summary=summary,
                        lexicon_path=lexicon_path,
                    )
                    if existed:
                        stats["updated"] += 1
                    else:
                        stats["created"] += 1

        # ── Trigger 2: Mass Threshold ────────────────────────────────
        for b in all_beliefs:
            if b.get("mass", 0) >= _LEXICON_MASS_THRESHOLD:
                words = _tokenize(b.get("content", ""))
                proper = [w for w in words if _is_proper_noun(w)]
                if not proper:
                    continue

                # Use the dominant proper noun
                from collections import Counter as C2
                counts = C2(w.lower() for w in proper)
                dominant_lower, _ = counts.most_common(1)[0]

                if dominant_lower not in covered_terms:
                    # This high-mass belief's term isn't in the Lexicon yet
                    # Gather all beliefs mentioning this term for synthesis
                    related = [
                        ob.get("content", "") for ob in all_beliefs
                        if dominant_lower in ob.get("content", "").lower()
                    ][:8]

                    prompt = (
                        f"Combine these related statements about '{proper[0]}' "
                        f"into ONE comprehensive summary (max {_LEXICON_MAX_LENGTH} chars). "
                        f"Plain text only, no markdown.\n\n"
                        + "\n".join(f"- {t}" for t in related)
                    )
                    summary = _call_gemini(prompt, system="You write concise summaries.")
                    if summary:
                        _divert_to_lexicon(
                            term=proper[0],
                            summary=summary[:_LEXICON_MAX_LENGTH],
                            lexicon_path=lexicon_path,
                        )
                        stats["created"] += 1
                        # Mark as covered so we don't re-process
                        covered_terms.add(dominant_lower)

        logger.info(
            "Lexicon sync complete: %d created, %d updated",
            stats["created"], stats["updated"],
        )
        return stats

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
           - self_identity: (I am...)
           - people: ([Name]...)
           - knowledge: Facts about the world
           - capabilities: (I can...)
           - skills: (To [goal]: [step sequence])
           - preferences: (I want/prefer/value...)
           - feedback: [Lesson]. [Why]. [How to apply]
           
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
                        "category": "feedback",
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
            # Allow up to 300 for feedback
            max_len = 300 if b.get('category') == 'feedback' else 250
            if len(content) < 15 or len(content) > max_len:
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
            candidate = {
                "content": b['content'],
                "category": b.get('category', 'knowledge'),
                "status": "pending",
                "detected_at": datetime.now().isoformat()
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
