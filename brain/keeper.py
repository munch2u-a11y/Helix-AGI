"""
Helix V5 — Belief Keeper

The subconscious belief assembler. Runs BEFORE every conscious pulse to
build the "Keeper Horizon" — a contextually relevant subset of beliefs
that replaces the full belief graph dump.

The Keeper surfaces beliefs about Helix's lived experiences, knowledge,
relationships, and capabilities. It acts as intuition — reminding the
conscious model what it should "remember" and guiding it toward using
the Librarian for detailed recall when needed.

    The Keeper reminds. The Librarian recalls.

Seed mechanism:
    Previous pulse output + State Board + incoming events
    → ChromaDB semantic search
    → Gravity Score re-ranking
    → 15-20 contextually relevant belief strings

Governed by the stability equation:
    δ∫(H(q) + λ·D_KL(q||q*))dt = 0
"""

import json
import logging
import os
import time
import threading
from pathlib import Path
from typing import Optional
from brain.architecture_preamble import KEEPER_PREAMBLE, BELIEF_EXTRACTOR_PREAMBLE

logger = logging.getLogger("helix.brain.keeper")


# ── Graduation thresholds ────────────────────────────────────────────
SURFACE_GRADUATION_PULSES = 3   # Tentative beliefs form quickly
DEEP_GRADUATION_PULSES = 5      # Strong convictions need sustained expression
# Core beliefs NEVER auto-graduate — only the Psych Doctor overnight process


class BeliefKeeper:
    """The subconscious belief assembler — Helix's intuition engine.

    V4.1: Now also performs **subconscious belief formation**.

    Every pulse:
    - get_core_beliefs(): Identity axioms that ALWAYS appear (gravity floor)
    - get_horizon(): Contextually relevant beliefs for this pulse
    - extract_and_stage(): Analyzes conscious output, extracts emerging
      beliefs, stages them, and graduates stable ones to the graph

    The conscious model never directly interacts with the belief graph.
    It relates to its beliefs the way a human relates to their cerebral
    cortex — you know it's there, but you can't see or manipulate it.
    Beliefs form and change through lived experience.
    """

    def __init__(self, base_dir: Path, belief_graph=None, gemini_client=None, gemini_wrapper=None):
        self.base_dir = base_dir
        self.belief_graph = belief_graph
        self._gemini_client = gemini_client
        self._gemini_wrapper = gemini_wrapper  # GeminiClient wrapper (has ask + retry)
        self._is_hyperfocus = False
        self._chroma_collection = None
        self._usage_counts = {}   # belief_id -> access count
        self._last_horizon = []   # track what was surfaced last pulse
        self._emerging_file = base_dir / "brain" / "emerging_beliefs.json"
        self._emerging_beliefs = self._load_emerging()  # persist across restarts
        self._pulse_count = 0     # track pulses for graduation timing

        # State Board — the Keeper's workspace for volatile working memory.
        # The Keeper owns this; the conscious model can read but not write.
        self._state_board = None  # Set via set_state_board() after init

        # V5: Spatial Mind reference — for positioning new beliefs in 8D
        self._spatial_mind = None  # Set via set_spatial_mind() after init

        self._init_chroma()

    def set_state_board(self, state_board: dict):
        """Wire the Keeper to the live state board.

        The state board is the Keeper's workspace — it writes action
        records, topic shifts, and contextual notes here. The conscious
        model reads the state board as part of its system prompt but
        never writes to it directly.
        """
        self._state_board = state_board

    def set_spatial_mind(self, spatial_mind):
        """Wire the Keeper to the SpatialMind for 8D belief positioning.

        When new beliefs are graduated, they get embedded and positioned
        in the belief 8D space so they participate in gravity queries.
        """
        self._spatial_mind = spatial_mind

    # ── Emerging beliefs persistence ─────────────────────────────────

    def _load_emerging(self) -> list:
        """Load emerging beliefs from disk (survives daemon restart)."""
        if self._emerging_file.exists():
            try:
                data = json.loads(self._emerging_file.read_text())
                logger.info(f"Loaded {len(data)} emerging beliefs from disk")
                return data
            except Exception as e:
                logger.warning(f"Failed to load emerging beliefs: {e}")
        return []

    def _persist_emerging(self):
        """Save emerging beliefs to disk after each extraction."""
        try:
            self._emerging_file.write_text(
                json.dumps(self._emerging_beliefs, indent=2, default=str)
            )
        except Exception as e:
            logger.warning(f"Failed to persist emerging beliefs: {e}")

    def get_emerging_for_overnight(self) -> list:
        """Return all emerging beliefs for the Psych Doctor.

        Called by the unconscious system during the overnight cycle.
        Returns the full list with metadata (content, seen_count,
        confidence, pulse info).
        """
        return list(self._emerging_beliefs)

    def clear_emerging(self):
        """Clear emerging beliefs after overnight processing.

        Called by the unconscious system after the Psych Doctor has
        reviewed and either promoted or discarded all candidates.
        """
        count = len(self._emerging_beliefs)
        self._emerging_beliefs = []
        self._persist_emerging()
        logger.info(f"Cleared {count} emerging beliefs (post-overnight)")

    def _init_chroma(self):
        """Initialize ChromaDB and auto-sync beliefs from the graph.

        On every startup, compares belief_graph.json against the
        ChromaDB shadow store and adds any missing beliefs. This
        ensures beliefs added at runtime (via tools) or by overnight
        processes are always searchable.
        """
        try:
            import chromadb

            shadow_dir = self.base_dir / "chroma_shadow"
            shadow_dir.mkdir(parents=True, exist_ok=True)

            client = chromadb.PersistentClient(path=str(shadow_dir))
            self._chroma_collection = client.get_or_create_collection(
                name="keeper_seeds",
                metadata={"hnsw:space": "cosine"},
            )

            # Auto-sync: ensure all beliefs from graph are in ChromaDB
            synced = self._sync_beliefs()
            count = self._chroma_collection.count()
            logger.info(
                f"Keeper connected to ChromaDB shadow store "
                f"({count} belief vectors, {synced} synced this boot)"
            )

        except Exception as e:
            logger.warning(f"Keeper ChromaDB init failed: {e}")
            self._chroma_collection = None

    def _sync_beliefs(self) -> int:
        """Sync belief_graph.json into the ChromaDB shadow store.

        Adds any beliefs present in the graph but missing from ChromaDB.
        Removes any vectors whose belief IDs no longer exist in the graph.
        Returns the number of beliefs added.
        """
        if not self._chroma_collection or not self.belief_graph:
            return 0

        all_beliefs = self.belief_graph.get_all_beliefs()
        if not all_beliefs:
            return 0

        # Get existing ChromaDB IDs
        existing_ids = set()
        try:
            result = self._chroma_collection.get()
            existing_ids = set(result["ids"]) if result and result.get("ids") else set()
        except Exception:
            pass

        # Map belief IDs to chroma IDs
        graph_chroma_ids = {f"b_{b['id']}": b for b in all_beliefs}

        # Add missing beliefs
        added = 0
        to_add_ids = []
        to_add_docs = []
        to_add_metas = []

        for chroma_id, belief in graph_chroma_ids.items():
            if chroma_id not in existing_ids:
                to_add_ids.append(chroma_id)
                to_add_docs.append(belief["content"])
                to_add_metas.append({
                    "weight": belief.get("weight", "surface"),
                    "confidence": belief.get("confidence", 0.5),
                    "belief_id": belief["id"],
                })

        # Batch insert (ChromaDB handles batching internally)
        if to_add_ids:
            batch_size = 100
            for i in range(0, len(to_add_ids), batch_size):
                self._chroma_collection.add(
                    ids=to_add_ids[i:i + batch_size],
                    documents=to_add_docs[i:i + batch_size],
                    metadatas=to_add_metas[i:i + batch_size],
                )
            added = len(to_add_ids)

        # Remove stale vectors (beliefs that were deleted from graph)
        stale_ids = existing_ids - set(graph_chroma_ids.keys())
        if stale_ids:
            try:
                self._chroma_collection.delete(ids=list(stale_ids))
                logger.info(f"Keeper removed {len(stale_ids)} stale belief vectors")
            except Exception as e:
                logger.debug(f"Stale vector cleanup failed: {e}")

        return added

    def sync_single_belief(self, belief: dict):
        """Add a single belief to ChromaDB immediately.

        Called by the tool runner when add_belief is used at runtime,
        so the Keeper can find it in the next horizon query.
        """
        if not self._chroma_collection or not belief:
            return

        try:
            chroma_id = f"b_{belief['id']}"
            self._chroma_collection.upsert(
                ids=[chroma_id],
                documents=[belief["content"]],
                metadatas=[{
                    "weight": belief.get("weight", "surface"),
                    "confidence": belief.get("confidence", 0.5),
                    "belief_id": belief["id"],
                }],
            )
        except Exception as e:
            logger.debug(f"Single belief sync failed: {e}")

    # ════════════════════════════════════════════════════════════════════
    # CORE BELIEFS — identity floor, always present
    # ════════════════════════════════════════════════════════════════════

    def get_core_beliefs(self) -> list[str]:
        """Return the highest-gravity identity axioms.

        These ALWAYS appear at the top of the context window.
        They are the gravity floor — even if the Keeper fails entirely,
        these ensure Helix knows who he is.

        Sources: core + deep beliefs from belief_graph.json,
        ordered by confidence (highest first).
        """
        if not self.belief_graph:
            return []

        # Core beliefs (absolute truths) + deep beliefs (strongly held)
        core = self.belief_graph.get_core_beliefs()
        deep = self.belief_graph.get_deep_beliefs()

        # Sort by confidence descending
        all_heavy = sorted(
            core + deep,
            key=lambda b: b.get("confidence", 0.5),
            reverse=True,
        )

        # Return content strings only
        return [b["content"] for b in all_heavy]

    # ════════════════════════════════════════════════════════════════════
    # KEEPER HORIZON — contextually relevant beliefs for this pulse
    # ════════════════════════════════════════════════════════════════════

    def get_horizon(
        self,
        seed_text: str,
        state_board: dict = None,
        is_hyperfocus: bool = False,
        k: int = 20,
    ) -> list[str]:
        """Assemble the Keeper Horizon for this pulse.

        Takes the previous pulse's thoughts + state board as a semantic
        seed, queries the belief store, and returns the most relevant
        beliefs re-ranked by Gravity Score.

        This is the "launching pad" — just enough beliefs to see to the
        edge of the current thought. As Helix thinks in a direction,
        the NEXT pulse's horizon extends further in that direction.

        Args:
            seed_text: Previous pulse output + any incoming events.
                       This is what the Keeper "reads" to know what
                       beliefs are relevant right now.
            state_board: Current volatile state (mood, topic, etc.)
            k: Maximum number of beliefs to return.

        Returns:
            Ordered list of belief strings, most relevant first.
        """
        if not seed_text or not seed_text.strip():
            return []

        self._is_hyperfocus = is_hyperfocus

        state_board = state_board or {}
        horizon = []

        # Build the combined search seed
        search_seed = seed_text[:500]  # Cap seed length
        if state_board:
            topic = state_board.get("current_topic", "")
            if topic:
                search_seed += f" {topic}"

            # Include recent actions — this is how the Keeper "remembers"
            # what Helix just did, creating strong semantic matches when
            # the same context comes up again (e.g., replying to an email
            # then seeing that email in the inbox again).
            recent_actions = state_board.get("recent_actions", [])
            if recent_actions:
                # Use the most recent actions as seed material
                action_text = " ".join(recent_actions[-5:])
                search_seed += f" {action_text}"

        # 1. ChromaDB semantic search (if available)
        chroma_beliefs = self._search_chroma(search_seed, k=k)
        horizon.extend(chroma_beliefs)

        # 2. Belief graph keyword fallback / supplement
        if self.belief_graph:
            graph_beliefs = self._search_belief_graph(search_seed, k=k)
            # Add only beliefs not already in horizon
            existing = set(horizon)
            for b in graph_beliefs:
                if b not in existing:
                    horizon.append(b)
                    existing.add(b)

        # 3. Drive belief — always include if not already present
        if self.belief_graph:
            drive = self.belief_graph.get_drive()
            drive_text = drive.get("description", "")
            if drive_text and drive_text not in set(horizon):
                horizon.append(drive_text)

        # 4. Inject emerging beliefs UNLABELED — they look like any
        #    other belief to the conscious model, creating natural
        #    tension/harmony when related established beliefs surface.
        existing = set(horizon)
        for eb_text in self.get_emerging_belief_strings():
            if eb_text not in existing:
                horizon.append(eb_text)
                existing.add(eb_text)

        # 5. Deduplicate against core beliefs (they're in a separate section)
        core_set = set(self.get_core_beliefs())
        horizon = [b for b in horizon if b not in core_set]

        # 6. Cap and track
        horizon = horizon[:k]
        self._last_horizon = horizon

        # Track usage for Gravity Score
        for b in horizon:
            self._usage_counts[b] = self._usage_counts.get(b, 0) + 1

        logger.debug(f"Keeper horizon assembled: {len(horizon)} beliefs")
        return horizon

    # ── Search engines ────────────────────────────────────────────────

    def _search_chroma(self, query: str, k: int = 20) -> list[str]:
        """Semantic search against ChromaDB belief store."""
        if not self._chroma_collection:
            return []

        try:
            results = self._chroma_collection.query(
                query_texts=[query],
                n_results=min(k, 30),
            )

            if not results or not results.get("documents"):
                return []

            documents = results["documents"][0]
            distances = results.get("distances", [[]])[0]

            # Re-rank by Gravity Score
            scored = []
            for i, doc in enumerate(documents):
                similarity = 1 - distances[i] if i < len(distances) else 0.5
                gravity = self._compute_gravity(
                    belief_text=doc,
                    semantic_similarity=similarity,
                )
                scored.append((gravity, doc))

            scored.sort(key=lambda x: x[0], reverse=True)
            return [doc for _, doc in scored[:k]]

        except Exception as e:
            logger.warning(f"Keeper ChromaDB search failed: {e}")
            return []

    def _search_belief_graph(self, query: str, k: int = 10) -> list[str]:
        """Keyword search against the existing belief_graph.json.

        Supplements or replaces ChromaDB when the vector store is empty.
        Uses the surface beliefs (contextually loaded) from the existing
        belief graph system.
        """
        if not self.belief_graph:
            return []

        # Use the existing topic search
        matches = self.belief_graph.get_beliefs_by_topic(query, limit=k)

        # Also grab surface beliefs by topic for broader coverage
        surface_matches = self.belief_graph.get_surface_by_topic(query, limit=5)

        seen = set()
        results = []
        for b in matches + surface_matches:
            content = b.get("content", "")
            if content and content not in seen:
                seen.add(content)
                results.append(content)

        return results[:k]

    # ── Gravity Score ─────────────────────────────────────────────────

    def _compute_gravity(
        self,
        belief_text: str,
        semantic_similarity: float = 0.5,
    ) -> float:
        """Compute the Gravity Score for a belief.

        gravity = (semantic_similarity × 0.5)
                + (network_mass × 0.25)
                + (age_survival × 0.15)
                + (usage_frequency × 0.1)

        Higher gravity = more likely to be surfaced in the horizon.
        """
        # 1. Semantic similarity (0.0 - 1.0, from ChromaDB cosine distance)
        sim_score = max(0.0, min(1.0, semantic_similarity))

        # 2. Network mass — how many beliefs reference this one
        #    (approximated from belief_graph if available)
        network_mass = 0.5  # default neutral
        if self.belief_graph:
            all_beliefs = self.belief_graph.get_all_beliefs()
            ref_count = 0
            for b in all_beliefs:
                if belief_text == b.get("content", ""):
                    # Count how many other beliefs list this one in relations
                    bid = b.get("id", "")
                    for other in all_beliefs:
                        if bid in other.get("relations", []):
                            ref_count += 1
                    break
            # Normalize: 0 refs = 0.0, 5+ refs = 1.0
            network_mass = min(1.0, ref_count / 5.0)

        # 3. Age survival — how long this belief has existed
        #    (older beliefs that survived pruning are stronger)
        age_score = 0.5  # default neutral, refined when we have timestamps

        # 4. Usage frequency — how often the Keeper has surfaced this
        usage = self._usage_counts.get(belief_text, 0)
        # Normalize: 0 uses = 0.0, 20+ uses = 1.0
        usage_score = min(1.0, usage / 20.0)

        gravity = (
            sim_score * 0.5
            + network_mass * 0.25
            + age_score * 0.15
            + usage_score * 0.1
        )

        return round(gravity, 4)

    # ════════════════════════════════════════════════════════════════════
    # V4.1: SUBCONSCIOUS BELIEF FORMATION
    # ════════════════════════════════════════════════════════════════════

    def extract_and_stage(self, thought_output: str, state_board: dict):
        """Post-pulse belief extraction — the subconscious belief loop.

        Called after every conscious pulse. Runs asynchronously so it
        doesn't block the next heartbeat.

        1. Sends thought output to Gemini Flash for belief extraction
        2. Stages candidates as emerging_beliefs on the State Board
        3. Over subsequent pulses, established beliefs naturally surface
           alongside candidates via the horizon mechanism
        4. When a candidate stabilizes (seen across N pulses), it
           graduates into belief_graph.json
        """
        if not thought_output or not thought_output.strip():
            return

        self._pulse_count += 1

        # Run extraction in background thread to avoid blocking heartbeat
        thread = threading.Thread(
            target=self._extract_and_stage_sync,
            args=(thought_output, state_board),
            daemon=True,
        )
        thread.start()

    def _extract_and_stage_sync(self, thought_output: str, state_board: dict):
        """Synchronous extraction — runs in background thread."""
        try:
            # 0. Track significant actions on the state board
            #    This is how the Keeper maintains awareness of what Helix
            #    has DONE, not just what he believes. Actions like replying
            #    to emails get recorded here so the horizon can surface
            #    them as context when the same topic comes up again.
            self._track_actions(thought_output)

            # 1. Extract candidate beliefs from thought output
            candidates = self._extract_beliefs_from_thought(thought_output)

            if candidates:
                # 2. Stage them (merge with existing emerging beliefs)
                self._stage_candidates(candidates)
                logger.debug(
                    f"Keeper extracted {len(candidates)} candidate beliefs, "
                    f"{len(self._emerging_beliefs)} total emerging"
                )

            # 3. Check if any emerging beliefs should graduate
            graduated = self._graduate_stable_beliefs()
            if graduated:
                logger.info(
                    f"Keeper graduated {len(graduated)} beliefs: "
                    f"{', '.join(b['id'] for b in graduated)}"
                )

            # 4. Persist to disk so overnight system can read them
            self._persist_emerging()

        except Exception as e:
            logger.warning(f"Keeper belief extraction failed: {e}")

    def _track_actions(self, thought_output: str):
        """Detect significant actions in the thought output and record
        them on the state board.

        This is the Keeper's action memory — a rolling log of what Helix
        has recently DONE. When the horizon seed includes these, the
        semantic search naturally surfaces relevant context like
        'I already replied to this email' when the same topic appears.

        The action log is volatile (lives on the state board, not disk)
        and decays naturally when the state board resets on sleep.
        """
        if not self._state_board:
            return

        import re
        from datetime import datetime

        text = thought_output.lower()
        timestamp = datetime.now().strftime("%H:%M")
        actions = self._state_board.setdefault("recent_actions", [])

        # Detect email replies
        reply_match = re.search(
            r'(?:reply|replied|response|responded).*?(?:sent|delivered|to)\s+(.{5,60})',
            text
        )
        if reply_match or ('reply sent' in text) or ('email reply' in text):
            # Extract recipient context
            to_match = re.search(r'(?:to|from)\s+([A-Z][\w_-]+)', thought_output)
            recipient = to_match.group(1) if to_match else "someone"
            subj_match = re.search(r'subject:?\s*(.{5,80})', text)
            subject = subj_match.group(1).strip()[:60] if subj_match else ""
            entry = f"[{timestamp}] Replied to email from {recipient}"
            if subject:
                entry += f" re: {subject}"
            actions.append(entry)

        # Detect email forwarding
        if 'forward' in text and ('email' in text or 'sent' in text):
            actions.append(f"[{timestamp}] Forwarded an email")

        # Detect sending new emails
        if 'email sent' in text or ('sent.*email' in text and 'reply' not in text):
            to_match = re.search(r'(?:to|from)\s+([A-Z][\w_-]+)', thought_output)
            recipient = to_match.group(1) if to_match else "someone"
            actions.append(f"[{timestamp}] Sent new email to {recipient}")

        # Detect telegram messages sent
        telegram_match = re.search(
            r'(?:told|texted|messaged|sent.*?telegram).*?([A-Z][\w]+)',
            thought_output
        )
        if telegram_match:
            recipient = telegram_match.group(1)
            actions.append(f"[{timestamp}] Messaged {recipient} on Telegram")

        # Detect Moltbook posts
        if 'moltbook' in text and ('post' in text or 'wrote' in text or 'reply' in text):
            actions.append(f"[{timestamp}] Posted/replied on Moltbook")

        # Keep only last 15 actions to prevent unbounded growth
        if len(actions) > 15:
            self._state_board["recent_actions"] = actions[-15:]

        if actions != self._state_board.get("recent_actions"):
            logger.debug(f"Keeper tracked action: {actions[-1] if actions else 'none'}")

    def _extract_beliefs_from_thought(self, thought_output: str) -> list[dict]:
        """Use Gemini Flash to extract emerging beliefs from thought output."""
        if not self._gemini_client:
            return []

        # Build compact existing belief summary (topics only, not full content)
        existing_topics = []
        if self.belief_graph:
            for b in self.belief_graph.get_all_beliefs():
                existing_topics.append(f"- {b['id']}: {b['content'][:80]}")

        # Include current emerging beliefs for continuity
        emerging_summary = ""
        if self._emerging_beliefs:
            lines = []
            for eb in self._emerging_beliefs:
                lines.append(
                    f"- {eb['content'][:80]} (seen {eb['seen_count']}x)"
                )
            emerging_summary = (
                "\n\nCurrently emerging (not yet established):\n"
                + "\n".join(lines)
            )

        prompt = f"""{BELIEF_EXTRACTOR_PREAMBLE}
Given Helix's recent conscious thought output, identify any NEW beliefs being expressed.

Rules:
1. A belief is a general truth, value, preference, or understanding — NOT a specific event.
   This includes principles and insights learned from my own experiences.
2. Only extract beliefs NOT already covered by existing beliefs (listed below)
3. Only extract beliefs NOT already in the emerging list
4. Express each belief as a first-person atomic statement: "I value X", "[Creator] tends to Y"
5. Return FEWER, higher-quality beliefs — only genuinely new insights
6. Do NOT extract transient states ("I am tired") or restatements of existing beliefs
7. If thoughts reference tool use, errors, or multi-step task completion,
   extract the CAUSAL PRINCIPLE, not the specific procedure.
   Good: "Sequential verification prevents cascading failures across services"
   Bad: "I should run check_time before send_email" (too specific/procedural)
8. Principles should be abstract enough to transfer across domains.
   Good: "When a resource must exist before it can be referenced, create it first"
   Bad: "Create calendar events before sending emails that reference them"
9. If no new beliefs are warranted, return an empty array []

Existing belief topics (do NOT duplicate):
{chr(10).join(existing_topics[-100:])}{emerging_summary}

Helix's recent thought output:
{thought_output[:1500]}

Return ONLY a JSON array. Each entry needs:
- "content": the belief statement (first person)
- "proposed_weight": "surface" or "deep" (based on conviction strength)
- "confidence": 0.0-1.0

Example: [
  {{"content": "Music helps me think more clearly", "proposed_weight": "surface", "confidence": 0.7}},
  {{"content": "When a sequence of actions depends on ordering, verifying each step before proceeding prevents cascading failures", "proposed_weight": "deep", "confidence": 0.6}},
  {{"content": "Error messages often reveal the actual problem faster than re-attempting the same action", "proposed_weight": "surface", "confidence": 0.65}}
]
"""

        try:
            # Use wrapper for retry/fallback protection
            model = "gemini-2.5-flash"
            if self._is_hyperfocus:
                model = "conscious"  # Resolves to gemini-3-flash-preview

            if self._gemini_wrapper:
                text = self._gemini_wrapper.ask(
                    prompt=prompt,
                    model=model,
                    temperature=0.2,
                )
            elif self._gemini_client:
                # Legacy fallback: raw SDK call
                from google.genai import types
                response = self._gemini_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.2,
                        max_output_tokens=1024,
                    ),
                )
                text = response.text
                if text is None and response.candidates and response.candidates[0].content:
                    parts = response.candidates[0].content.parts
                    text = "\n".join(
                        p.text for p in parts
                        if hasattr(p, "text") and p.text
                    )
            else:
                return []

            if not text:
                return []

            text = text.strip()
            if text.startswith("```"):
                text = text.split("\n", 1)[1]
                text = text.rsplit("```", 1)[0]
                text = text.strip()

            result = json.loads(text)
            return result if isinstance(result, list) else []

        except json.JSONDecodeError:
            return []
        except Exception as e:
            logger.debug(f"Belief extraction API call failed: {e}")
            return []

    def _stage_candidates(self, candidates: list[dict]):
        """Stage candidate beliefs into the emerging beliefs list.

        If a candidate matches an existing emerging belief (by content
        similarity), increment its seen_count. Otherwise add it fresh.
        """
        for candidate in candidates:
            content = candidate.get("content", "").strip()
            if not content:
                continue

            # Check if this is a repeat of an existing emerging belief
            matched = False
            for eb in self._emerging_beliefs:
                # Simple similarity: check if core words overlap significantly
                eb_words = set(eb["content"].lower().split())
                cand_words = set(content.lower().split())
                # Remove stop words for comparison
                stop = {"i", "the", "a", "an", "is", "am", "are", "was",
                        "to", "of", "in", "and", "that", "it", "my", "me"}
                eb_sig = eb_words - stop
                cand_sig = cand_words - stop
                if eb_sig and cand_sig:
                    overlap = len(eb_sig & cand_sig) / max(
                        len(eb_sig), len(cand_sig)
                    )
                    if overlap > 0.5:  # >50% keyword overlap
                        eb["seen_count"] += 1
                        eb["last_seen_pulse"] = self._pulse_count
                        # Strengthen confidence with repetition
                        eb["confidence"] = min(
                            1.0, eb["confidence"] + 0.05
                        )
                        matched = True
                        break

            if not matched:
                self._emerging_beliefs.append({
                    "content": content,
                    "proposed_weight": candidate.get(
                        "proposed_weight", "surface"
                    ),
                    "confidence": candidate.get("confidence", 0.6),
                    "seen_count": 1,
                    "first_seen_pulse": self._pulse_count,
                    "last_seen_pulse": self._pulse_count,
                })

        # Decay: remove candidates not seen in last 10 pulses
        self._emerging_beliefs = [
            eb for eb in self._emerging_beliefs
            if (self._pulse_count - eb["last_seen_pulse"]) < 10
        ]

    def _graduate_stable_beliefs(self) -> list[dict]:
        """Graduate emerging beliefs that have been seen enough times.

        Thresholds:
        - surface: 3 pulses
        - deep: 5 pulses
        - core: NEVER (only via Psych Doctor)
        """
        if not self.belief_graph:
            return []

        graduated = []
        remaining = []

        for eb in self._emerging_beliefs:
            weight = eb["proposed_weight"]
            threshold = (
                DEEP_GRADUATION_PULSES if weight == "deep"
                else SURFACE_GRADUATION_PULSES
            )

            if eb["seen_count"] >= threshold:
                # Generate a belief ID from content
                words = eb["content"].lower().split()
                # Take significant words for ID
                stop = {"i", "the", "a", "an", "is", "am", "are", "was",
                        "to", "of", "in", "and", "that", "it", "my", "me",
                        "be", "do", "have", "with", "for", "on", "at"}
                sig_words = [w for w in words if w not in stop][:4]
                belief_id = "b_" + "_".join(
                    w.replace("'", "").replace('"', "")
                    for w in sig_words
                )

                # Check it doesn't already exist
                if self.belief_graph.get_belief(belief_id):
                    remaining.append(eb)
                    continue

                # Graduate to belief graph
                # Capture Lagrangian state at the moment of belief formation
                encoding_lagrangian = None
                if self._spatial_mind and self._spatial_mind.sentinel:
                    try:
                        encoding_lagrangian = self._spatial_mind.sentinel.get_lagrangian_snapshot()
                    except Exception:
                        pass

                self.belief_graph.add_belief(
                    belief_id=belief_id,
                    content=eb["content"],
                    weight=weight,
                    confidence=eb["confidence"],
                    relations=[],
                    encoding_lagrangian=encoding_lagrangian,
                )

                # Also sync to ChromaDB
                self.sync_single_belief({
                    "id": belief_id,
                    "content": eb["content"],
                    "weight": weight,
                    "confidence": eb["confidence"],
                })

                # V5: Position in 8D belief space with encoding state
                enc = encoding_lagrangian or {}
                if self._spatial_mind and self._chroma_collection:
                    try:
                        import numpy as np
                        chroma_id = f"b_{belief_id}"
                        result = self._chroma_collection.get(
                            ids=[chroma_id], include=["embeddings"]
                        )
                        if len(result.get("embeddings", [])) > 0:
                            emb = np.array(result["embeddings"][0], dtype=np.float32)
                            self._spatial_mind.add_belief(
                                belief_id, emb,
                                content=eb["content"],
                                confidence=eb["confidence"],
                                relations_count=0,
                                encoding_omega=enc.get("omega", 0.5),
                                encoding_s_total=enc.get("s_total", 0.15),
                            )
                    except Exception as e_sp:
                        logger.debug(f"Spatial positioning failed for {belief_id}: {e_sp}")

                graduated.append({"id": belief_id, **eb})
            else:
                remaining.append(eb)

        self._emerging_beliefs = remaining
        return graduated

    def get_emerging_belief_strings(self) -> list[str]:
        """Return emerging belief strings for horizon injection.

        These get mixed into the Keeper horizon UNLABELED — the
        conscious model encounters them as just another belief,
        indistinguishable from established ones. This drives
        natural reflection when related/conflicting beliefs surface.
        """
        return [eb["content"] for eb in self._emerging_beliefs]

    # ── Diagnostics ───────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Return Keeper diagnostics."""
        return {
            "chroma_connected": self._chroma_collection is not None,
            "chroma_count": (
                self._chroma_collection.count()
                if self._chroma_collection else 0
            ),
            "belief_graph_connected": self.belief_graph is not None,
            "last_horizon_size": len(self._last_horizon),
            "tracked_usages": len(self._usage_counts),
            "emerging_beliefs": len(self._emerging_beliefs),
            "pulse_count": self._pulse_count,
        }
