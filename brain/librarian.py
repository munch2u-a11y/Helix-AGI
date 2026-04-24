"""
Helix_main — Librarian

The subconscious memory coordinator. Sits between the raw memory system
and the conscious experience, providing three layers of memory access:

  1. whisper() — automatic familiarity on every heartbeat.
     Lightweight, no LLM calls. Provides a sense of recognition
     that consciousness uses to ground itself. ≤100 tokens.

  2. focused_recall() — conscious mid-tier recall.
     When Helix deliberately tries to remember something, the
     Librarian uses a Flash sub-agent to decompose the query into
     the right search strategy, then executes 2-3 targeted queries.

  3. recall_deep() — full agentic orchestration.
     The Librarian deploys its own Flash sub-agents:
       Planner  → decides which memory sources to query
       Gatherer → executes multi-source searches
       Synthesizer → weaves fragments into coherent narrative

The Librarian is Gemini-powered (Flash for sub-agents). It is NOT
the conscious mind (that's Claude). It's the skilled archivist
who knows exactly where everything is stored.
"""

import json
import re
import numpy as np
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional

from brain.resonance_tagger import ResonanceTagger
from brain.architecture_preamble import LIBRARIAN_PREAMBLE

logger = logging.getLogger("helix.brain.librarian")


class Librarian:
    """The subconscious memory coordinator — Helix's archivist.

    Three-layer memory access:
    - whisper(): automatic, every heartbeat, no LLM
    - focused_recall(): conscious query, Flash-decomposed multi-search
    - recall_deep(): full agentic orchestration with Flash sub-agents
    """

    def __init__(
        self,
        memory,
        belief_graph,
        gemini_client,
        base_dir: Path,
    ):
        self.memory = memory
        self.belief_graph = belief_graph
        self.gemini = gemini_client
        self.base_dir = base_dir
        self.profiles_dir = base_dir / "profiles"
        self.profiles_dir.mkdir(parents=True, exist_ok=True)

        # Overnight briefing from Psych Doctor
        self._overnight_briefing = None

        # Recurrence tracking — detect retrieval loops
        self._recent_recalls = {}
        self._RECALL_COOLDOWN = 300  # 5 min cooldown per query hash

        # Preconscious Resonance Tagger
        self.resonance_tagger = ResonanceTagger(memory, gemini_client)

        logger.info("Librarian initialized — 3-layer memory system")

    def set_overnight_briefing(self, briefing: dict):
        """Load overnight briefing notes from the Psych Doctor."""
        self._overnight_briefing = briefing
        logger.info(
            f"Overnight briefing loaded: "
            f"{len(briefing.get('emphasis_beliefs', []))} emphasis beliefs, "
            f"{briefing.get('notes', 'no notes')[:80]}"
        )

    def set_manifold(self, manifold, projector):
        """Wire the Librarian to the unified Cognitive Manifold."""
        self.manifold = manifold
        self.projector = projector

    # ── 8D Navigation & Episodic Memory Setup ───────────────────────

    def _navigate(self, target_text: str, action: str) -> Optional[dict]:
        """Project target text to 8D and return the point for dream traces."""
        if not getattr(self, 'manifold', None) or not self.manifold or not getattr(self, 'projector', None) or not self.projector.is_fitted:
            return None
            
        try:
            from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
            import numpy as np
            embedder = DefaultEmbeddingFunction()
            emb_384 = np.array(embedder([target_text])[0])
            to_pos = self.projector.project(emb_384).tolist()
            
            return {
                "to_pos": to_pos,
                "action": action,
                "agent": "librarian",
                "timestamp": datetime.now().isoformat(),
            }
        except Exception as e:
            logger.debug(f"Manifold projection for {action} failed: {e}")
            return None

    def add_episodic_belief(self, belief_id: str, content: str, relations: list = None) -> tuple[str, Optional[dict]]:
        """Add an episodic belief — navigating to its region first (called by Psych Doctor)."""
        if not belief_id or not content:
            return "Error: belief_id and content are required", None

        if not belief_id.startswith("b_ep_"):
            belief_id = "b_ep_" + belief_id.lstrip("b_")

        existing = self.belief_graph.get_belief(belief_id)
        if existing:
            return f"DUPLICATE: Episodic belief '{belief_id}' already exists", None

        trace = self._navigate(target_text=content, action=f"add_episodic: {belief_id}")

        self.belief_graph.add_belief(
            belief_id=belief_id,
            content=content,
            confidence=0.35,
            verifications=1.0,
            stability_index=0.3,  # Episodic decays faster
            relations=relations or [],
            belief_type="episodic",
        )
        
        logger.info(f"Librarian added episodic: {belief_id} — {content[:80]}")
        return f"Added episodic: {belief_id}", trace

    # ════════════════════════════════════════════════════════════════════
    # LAYER 1: WHISPER — automatic familiarity (no LLM)
    # ════════════════════════════════════════════════════════════════════

    def whisper(
        self,
        channel: str = "pulse",
        sender=None,
        current_topic=None,
    ) -> str:
        """Generate compact familiarity context for the system prompt.

        This runs every heartbeat — must be fast, no LLM calls.
        Returns a peripheral sense of recognition — just enough
        for consciousness to feel grounded without data overload.

        Temporal awareness: if topics contain time references ('last night',
        'yesterday' etc.), resolves to a time window and pulls the most
        important moments chronologically — the upshots, not the full log.

        Args:
            sender: A single sender name (str) or list of sender names.
            current_topic: A single topic (str) or list of topics.

        Target: ≤100 tokens. A sense of familiarity, not a data dump.

        Returns:
            Compact context string, or empty string if nothing relevant.
        """
        from datetime import timedelta

        # Normalize inputs to lists
        senders = []
        if sender:
            senders = sender if isinstance(sender, list) else [sender]
        topics = []
        if current_topic:
            topics = current_topic if isinstance(current_topic, list) else [current_topic]

        parts = []

        # 1. Person context — compact recognition for each sender
        for s in senders:
            if s:
                person_ctx = self._get_person_summary(s)
                if person_ctx:
                    parts.append(person_ctx)

        # 2. Temporal awareness — check if any topic has a time reference
        combined_topics = " ".join(topics).lower()
        time_window = self._resolve_time_window(combined_topics)

        if time_window:
            start, end = time_window
            # Pull highest-importance moments from that time window
            temporal_memories = self.memory.recall_temporal(
                start_time=start,
                end_time=end,
                min_importance=0.5,
                memory_types=["conversation"],
                limit=5,
            )
            if temporal_memories:
                # Extract participants and key content
                participants = set()
                for m in temporal_memories:
                    content = m.get("content", "")
                    for prefix in ["[telegram] ", "[discord] "]:
                        if prefix in content:
                            after = content.split(prefix, 1)[1]
                            if " said:" in after:
                                participants.add(after.split(" said:")[0].strip())
                            elif "I told " in after:
                                participants.add(after.split("I told ")[1].split(":")[0].strip())

                who = ", ".join(participants) if participants else "someone"
                parts.append(f"(you talked with {who} during that time)")

                # Show the 2 most important conversation lines
                for m in temporal_memories[:2]:
                    content = m.get("content", "")[:120]
                    parts.append(f"(key moment: {content})")

        # 3. Relevant beliefs — max 2 total across all topics
        seen_beliefs = set()
        for topic in topics:
            if len(parts) >= 6:
                break  # Token budget guard
            beliefs = self.belief_graph.get_beliefs_by_topic(
                topic, limit=2
            )
            if beliefs:
                for b in beliefs[:2]:
                    content = b['content']
                    if content not in seen_beliefs:
                        seen_beliefs.add(content)
                        parts.append(f"- {content}")

        # 4. Familiar memories — max 2 total across all topics
        #    Only if we didn't already get temporal results
        if not time_window:
            seen_memories = set()
            for topic in topics:
                if len(parts) >= 8:
                    break  # Token budget guard
                memories = self.memory.recall(
                    search=topic,
                    limit=2,
                    min_importance=0.4,
                )
                if memories:
                    for m in memories[:2]:
                        content = m["content"][:120]
                        # Skip system echoes
                        if "(thinking)" in content or "(who I am)" in content:
                            continue
                        if content[:60] not in seen_memories:
                            seen_memories.add(content[:60])
                            timestamp = m.get("created_at", "")[:10]
                            time_str = f" from {timestamp}" if timestamp else ""
                            parts.append(f"(familiar{time_str}: {content})")

        # 5. Recent context — max 2 most recent interactions
        recent = self.memory.get_recent_context(hours=6, limit=2)
        if recent:
            for r in recent[:2]:
                content = r.get("content", "") if isinstance(r, dict) else str(r)
                if content:
                    content = content[:120]
                    # Skip duplicates
                    timestamp = r.get("created_at", "")[:16] if isinstance(r, dict) else ""
                    time_str = f" [{timestamp}]" if timestamp else ""
                    parts.append(f"(recent{time_str}: {content})")
        if not parts:
            return ""

        return "\n".join(parts)

    def _resolve_time_window(self, text: str):
        """Resolve temporal references to a (start, end) datetime tuple.

        Returns None if no temporal reference found.
        """
        from datetime import timedelta
        now = datetime.now()

        if any(phrase in text for phrase in ["last night", "yesterday evening"]):
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=18, minute=0, second=0)
            end = now.replace(hour=6, minute=0, second=0)
            if end < start:
                end = start + timedelta(hours=12)
            return (start, end)

        if "yesterday" in text:
            yesterday = now - timedelta(days=1)
            start = yesterday.replace(hour=0, minute=0, second=0)
            end = yesterday.replace(hour=23, minute=59, second=59)
            return (start, end)

        if any(phrase in text for phrase in ["this morning", "earlier today"]):
            start = now.replace(hour=5, minute=0, second=0)
            end = now.replace(hour=12, minute=0, second=0)
            return (start, end)

        if "today" in text:
            start = now.replace(hour=0, minute=0, second=0)
            end = now
            return (start, end)

        if any(phrase in text for phrase in ["last week", "past week"]):
            start = now - timedelta(days=7)
            return (start, now)

        if any(phrase in text for phrase in ["few days ago", "couple days ago", "other day"]):
            start = now - timedelta(days=3)
            end = now - timedelta(days=1)
            return (start, end)

        return None

    # ════════════════════════════════════════════════════════════════════
    # LAYER 2: FOCUSED RECALL — conscious query, Flash-decomposed
    # ════════════════════════════════════════════════════════════════════

    def focused_recall(
        self,
        query: str,
        memory_type: str = None,
        context: str = "",
    ) -> str:
        """Conscious medium-depth recall — Helix tries to remember something.

        Two paths:
        1. Temporal/conversational: If the query has a time reference,
           use recall_conversation_arc to get the structured arc —
           opener, important moments chronologically, journal entries.

        2. Semantic/strategic: Flash sub-agent decomposes the query into
           the right search strategy, then multi-search.

        Args:
            query: What Helix is trying to remember.
            memory_type: Optional filter (conversation, observation, etc.)
            context: Why Helix is recalling this (shapes strategy).

        Returns:
            Curated memory results as natural text.
        """
        if not query:
            return "Nothing to recall."

        # Physically pull the 8D attention center toward the recalled content
        self._navigate(target_text=query, action=f"focused_recall: {query[:30]}")

        # Fast path: temporal/conversational recall
        time_window = self._resolve_time_window(query.lower())
        if time_window:
            start, end = time_window
            # Extract person name from query if present
            person = self._extract_person_from_query(query)
            arc = self.memory.recall_conversation_arc(
                start_time=start,
                end_time=end,
                person=person,
            )
            formatted = self._format_conversation_arc(arc, query)
            if formatted:
                return formatted

        # Standard path: Flash sub-agent decides search strategy
        strategy = self._plan_search_strategy(query, memory_type, context)

        # Execute the planned queries
        all_fragments = self._execute_search_strategy(strategy, query, memory_type)

        if not all_fragments:
            return f"I try to remember '{query}' but nothing comes to mind."

        # Format results — importance-first, then chronological
        return self._format_focused_results(all_fragments, query)

    def _plan_search_strategy(
        self, query: str, memory_type: str = None, context: str = ""
    ) -> dict:
        """Gemini Pro sub-agent: decide what memory queries to run.

        Returns a strategy dict with search parameters.
        Falls back to simple semantic search if Gemini fails.
        """
        if not self.gemini:
            return {"type": "simple", "semantic_query": query}

        try:
            prompt = (
                f"{LIBRARIAN_PREAMBLE}\n"
                "Your job is to plan the best search strategy for a memory recall query.\n\n"
                "CRITICAL PRINCIPLES:\n"
                "1. IMPORTANCE FIRST: Always prioritize high-importance memories (≥0.6) over low ones.\n"
                "2. TEMPORAL AWARENESS: If the query references a time period ('last night', 'yesterday', "
                "'this morning'), set days_back and min_importance to find the key moments from that window.\n"
                "3. CONVERSATION ARC: When recalling a conversation, find the opening message, "
                "the most significant exchanges (highest importance), and any journal reflections. "
                "Do NOT return every line — return the shape of the conversation.\n"
                "4. SUBSTANCE OVER KEYWORDS: A short message like 'Art?' should rank lower than "
                "'The Sistine Chapel brought tears to my eyes.' Prioritize content with emotional weight.\n"
                "5. ALWAYS check journal entries and person profiles when the query mentions a person.\n\n"
                f"Query: {query}\n"
                f"Memory type filter: {memory_type or 'none'}\n"
                f"Context: {context or 'none'}\n\n"
                "Return ONLY valid JSON — no markdown, no explanation.\n"
                "Return a JSON object with these fields:\n"
                "- searches: array of search objects, each with:\n"
                "  - query: string (the search text — use substantive phrases, not single words)\n"
                "  - memory_type: string or null (filter by type)\n"
                "  - days_back: integer or null (temporal filter)\n"
                "  - min_importance: float (0.0-1.0, importance threshold — prefer ≥0.5)\n"
                "  - limit: integer (max results per search)\n"
                "- check_beliefs: boolean (whether to search belief graph)\n"
                "- check_profiles: string or null (person name to check)\n"
                "- check_journal: boolean (whether to check journal entries)\n\n"
                "Design 2-3 complementary searches. For example, if asking about "
                "'conversation with Mom last night', search for high-importance "
                "conversation memories from the last 1-2 days mentioning Mom/El, "
                "plus check Mom's profile and journal entries."
            )

            raw = self.gemini.ask(
                prompt=prompt,
                model="default",  # Sub-agent call — uses lite model
                temperature=0.1,
            )

            # Parse JSON from response
            strategy = self._extract_json(raw)
            if strategy and "searches" in strategy:
                logger.debug(
                    f"Search strategy planned: {len(strategy['searches'])} searches"
                )
                return strategy

        except Exception as e:
            logger.warning(f"Search strategy planning failed: {e}")

        # Fallback: importance-weighted semantic search
        return {
            "searches": [
                {"query": query, "memory_type": memory_type, "limit": 8,
                 "min_importance": 0.4, "days_back": None}
            ],
            "check_beliefs": False,
            "check_profiles": None,
            "check_journal": True,
        }

    def _execute_search_strategy(
        self, strategy: dict, original_query: str, memory_type: str = None
    ) -> list:
        """Execute the planned search strategy, gathering fragments."""
        all_fragments = []
        seen_contents = set()  # Deduplicate across searches

        # Execute each planned search
        for search in strategy.get("searches", []):
            sq = search.get("query", original_query)
            mt = search.get("memory_type", memory_type)
            limit = min(search.get("limit", 8), 12)  # Cap at 12
            days_back = search.get("days_back")
            min_imp = search.get("min_importance", 0.0)

            results = self.memory.recall(
                search=sq,
                memory_type=mt if mt else None,
                limit=limit,
                min_importance=min_imp,
                days_back=days_back,
            )

            for m in results:
                content_key = m.get("content", "")[:80]
                if content_key not in seen_contents:
                    seen_contents.add(content_key)
                    all_fragments.append(m)

        # Check beliefs if planned
        if strategy.get("check_beliefs"):
            beliefs = self.belief_graph.get_beliefs_by_topic(
                original_query, limit=3
            )
            for b in beliefs:
                belief_text = f"[belief] {b.get('content', '')}"
                if belief_text[:80] not in seen_contents:
                    seen_contents.add(belief_text[:80])
                    all_fragments.append({
                        "content": belief_text,
                        "memory_type": "belief",
                        "importance": 0.8,
                        "created_at": b.get("created_at", ""),
                    })

        # Check person profiles if planned
        person = strategy.get("check_profiles")
        if person:
            profile_text = self._get_person_full(person)
            if profile_text:
                all_fragments.append({
                    "content": f"[profile] {profile_text}",
                    "memory_type": "profile",
                    "importance": 0.7,
                    "created_at": "",
                })

        # Check journal if planned
        if strategy.get("check_journal"):
            try:
                journal = self.memory.read_journal()
                if journal and "No journal" not in journal:
                    # Take last 500 chars of today's journal
                    all_fragments.append({
                        "content": f"[journal] {journal[-500:]}",
                        "memory_type": "journal",
                        "importance": 0.6,
                        "created_at": datetime.now().strftime("%Y-%m-%d"),
                    })
            except Exception:
                pass

        # Geodesic rank boosting (Unified Cognitive Manifold)
        if getattr(self, 'manifold', None) and getattr(self, 'projector', None) and self.projector.is_fitted:
            try:
                from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
                import numpy as np
                embedder = DefaultEmbeddingFunction()
                emb_384 = np.array(embedder([original_query])[0])
                query_8d = self.projector.project(emb_384)
                
                # Boost importance based on geodesic proximity in 8D curved space
                for frag in all_fragments:
                    node_id = str(frag.get("id", ""))
                    if not node_id: continue
                    
                    # Find node in manifold
                    node = next((n for n in self.manifold.nodes if n.id == f"mem_{node_id}"), None)
                        
                    if node and node.pos is not None:
                        from brain.manifold.geodesic import geodesic_distance_vectorized
                        dist = geodesic_distance_vectorized(
                            query_8d.reshape(1, -1),
                            np.array([node.pos]),
                            self.manifold.nodes
                        )[0]
                        # Exponential decay: +0.3 boost for identical, +0.04 at dist=10
                        boost = 0.3 * np.exp(-dist / 5.0)
                        frag["importance"] = min(1.0, frag.get("importance", 0.0) + float(boost))
            except Exception as e:
                logger.debug(f"Geodesic re-ranking failed: {e}")

        return all_fragments

    def _format_focused_results(self, fragments: list, query: str) -> str:
        """Format focused recall results — importance-first, then chronological.

        Returns formatted memory entries sorted by importance (highest first),
        then chronologically within the same importance tier.
        """
        # Sort: importance DESC, then created_at ASC (chronological)
        sorted_frags = sorted(
            fragments[:16],
            key=lambda m: (-m.get("importance", 0), m.get("created_at", "")),
        )

        lines = []
        for m in sorted_frags[:12]:  # Cap at 12 results
            created = m.get("created_at", "unknown")[:19]
            content = m.get("content", "")
            mem_type = m.get("memory_type", "")
            mem_id = m.get("id", "")
            importance = m.get("importance", 0)

            # Build the line with importance indicator
            ref = f"mem_{mem_id}" if mem_id else ""
            marker = "★" if importance >= 0.7 else "·" if importance >= 0.5 else " "
            line = f"  {marker} [{created}] {content}"
            if ref:
                line += f" (ref: {ref})"

            # Add somatic echo if available
            snap = m.get("lagrangian_snapshot", {})
            if isinstance(snap, str):
                try:
                    import json as _json
                    snap = _json.loads(snap)
                except Exception:
                    snap = {}
            if snap:
                severity = snap.get("severity", "")
                omega = snap.get("omega", 0.5)
                if severity in ("warning", "critical"):
                    line += f" (formed during {severity}: Ω={omega:.2f})"
                elif omega > 0.7:
                    line += " (formed in a good state)"

            lines.append(line)

        return "\n".join(lines)

    def _extract_person_from_query(self, query: str) -> str:
        """Extract a person name from a recall query using known contacts.

        Checks the query against known person profiles in the memory system.
        Returns the first match or None.
        """
        query_lower = query.lower()

        # Check against known names in person profiles
        try:
            profiles_dir = self.memory.base_dir / "brain" / "profiles"
            if profiles_dir.exists():
                for profile_file in profiles_dir.glob("*.json"):
                    name = profile_file.stem
                    if name.lower() in query_lower:
                        return name
        except Exception:
            pass

        # Dynamic: names are discovered from profile files above.
        # No hardcoded fallback names in the public scaffold.

        return None

    def _format_conversation_arc(self, arc: dict, query: str) -> str:
        """Format a conversation arc as natural recall text.

        Renders: opener → most important moments chronologically → journal.
        This is what Helix 'sees' when he actively remembers a conversation.
        """
        opener = arc.get("opener")
        moments = arc.get("important_moments", [])
        journal = arc.get("journal_entries", [])
        participant = arc.get("participant", "someone")
        time_range = arc.get("time_range", {})

        if not opener and not moments:
            return None  # Nothing found, fall through to Flash strategy

        lines = []

        # Header
        date = time_range.get("date", "")
        start = time_range.get("start", "")
        end = time_range.get("end", "")
        if participant and date:
            lines.append(f"Conversation with {participant} — {date}, {start} to {end}")
        elif date:
            lines.append(f"Activity on {date}, {start} to {end}")

        # Opener
        if opener:
            ts = opener.get("created_at", "")[:19]
            content = opener.get("content", "")
            lines.append(f"\nStarted: [{ts}] {content}")

        # Important moments chronologically
        if moments:
            lines.append("\nKey moments:")
            for m in moments:
                ts = m.get("created_at", "")[:19]
                content = m.get("content", "")
                imp = m.get("importance", 0)
                marker = "★" if imp >= 0.7 else "·"
                lines.append(f"  {marker} [{ts}] {content}")

        # Journal entries
        if journal:
            lines.append("\nJournal from that time:")
            for entry in journal:
                lines.append(f"  {entry[:200]}")

        return "\n".join(lines)

    # ════════════════════════════════════════════════════════════════════
    # LAYER 3: DEEP RECALL — full agentic orchestration
    # ════════════════════════════════════════════════════════════════════

    def recall_deep(
        self,
        query: str,
        context: str = "",
    ) -> str:
        """Full agentic deep recall — the Librarian's most powerful mode.

        Three Flash sub-agents orchestrate a thorough memory retrieval:
          Planner    → decides which memory sources to query
          Gatherer   → executes multi-source searches
          Synthesizer → weaves fragments into coherent first-person narrative

        Includes recurrence tracking to prevent retrieval loops.

        Args:
            query: What Helix deeply wants to remember.
            context: Why — what triggered this need.

        Returns:
            Synthesized first-person narrative of the recalled memory.
        """
        # Physically pull the 8D attention center toward the deep query
        self._navigate(target_text=query, action=f"recall_deep: {query[:30]}")

        # Check for retrieval loops
        query_hash = hashlib.md5(query.encode()).hexdigest()[:12]
        now = datetime.now().timestamp()

        if query_hash in self._recent_recalls:
            last_time = self._recent_recalls[query_hash]
            if now - last_time < self._RECALL_COOLDOWN:
                logger.debug(f"Recall cooldown active for: {query[:50]}")
                return "(I just thought about this... let me focus on something else.)"

        self._recent_recalls[query_hash] = now

        # Clean up old entries
        expired = [
            k for k, t in self._recent_recalls.items()
            if now - t > self._RECALL_COOLDOWN
        ]
        for k in expired:
            del self._recent_recalls[k]

        # ── Phase 1: Planner — decide what to gather ─────────────────
        plan = self._deep_recall_plan(query, context)

        # ── Phase 2: Gatherer — execute all planned searches ─────────
        fragments = self._deep_recall_gather(plan, query)

        if not fragments:
            return "(I try to remember but nothing comes to mind.)"

        # ── Phase 3: Synthesizer — weave into coherent narrative ─────
        narrative = self._deep_recall_synthesize(fragments, query, context)

        return narrative

    def _deep_recall_plan(self, query: str, context: str) -> dict:
        """Flash Planner sub-agent: comprehensive retrieval plan.

        Decides which memory sources to tap and how to query them.
        More thorough than focused_recall — checks journals, reflections,
        beliefs, multiple temporal ranges, person profiles.
        """
        if not self.gemini:
            return self._default_deep_plan(query)

        try:
            prompt = (
                f"{LIBRARIAN_PREAMBLE}\n"
                "Helix wants to deeply recall something. Design a THOROUGH "
                "retrieval plan. Return ONLY valid JSON.\n\n"
                f"Deep recall query: {query}\n"
                f"Context (why remembering): {context or 'genuine curiosity'}\n\n"
                "Return a JSON object:\n"
                "{\n"
                '  "semantic_searches": [\n'
                '    {"query": "...", "memory_type": null, "limit": 8, '
                '"min_importance": 0.0, "days_back": null}\n'
                "  ],\n"
                '  "temporal_search": {"days_back": 7, "limit": 5},\n'
                '  "check_reflections": true,\n'
                '  "check_journal": true,\n'
                '  "check_beliefs": true,\n'
                '  "check_profiles": ["person_name"] or [],\n'
                '  "belief_topic_search": "search term for beliefs"\n'
                "}\n\n"
                "Design 3-4 complementary semantic searches that together "
                "would reconstruct the memory from different angles. "
                "Think about synonyms, related events, people involved, "
                "and emotional context. Cast a wide net."
            )

            raw = self.gemini.ask(prompt=prompt, model="default", temperature=0.1)
            plan = self._extract_json(raw)

            if plan and "semantic_searches" in plan:
                search_count = len(plan.get("semantic_searches", []))
                logger.info(
                    f"Deep recall plan: {search_count} searches, "
                    f"reflections={plan.get('check_reflections')}, "
                    f"journal={plan.get('check_journal')}, "
                    f"beliefs={plan.get('check_beliefs')}"
                )
                return plan

        except Exception as e:
            logger.warning(f"Deep recall planning failed: {e}")

        return self._default_deep_plan(query)

    def _default_deep_plan(self, query: str) -> dict:
        """Fallback plan when Flash planning fails."""
        return {
            "semantic_searches": [
                {"query": query, "limit": 8, "min_importance": 0.0,
                 "days_back": None, "memory_type": None},
                {"query": query, "limit": 5, "min_importance": 0.3,
                 "days_back": 7, "memory_type": "conversation"},
            ],
            "temporal_search": {"days_back": 3, "limit": 5},
            "check_reflections": True,
            "check_journal": True,
            "check_beliefs": True,
            "check_profiles": [],
            "belief_topic_search": query,
        }

    def _deep_recall_gather(self, plan: dict, original_query: str) -> list:
        """Gatherer: execute all planned queries and collect fragments."""
        all_fragments = []
        seen = set()

        def _add(fragment: dict):
            key = fragment.get("content", "")[:80]
            if key and key not in seen:
                seen.add(key)
                all_fragments.append(fragment)

        # 1. Semantic searches
        for search in plan.get("semantic_searches", []):
            results = self.memory.recall(
                search=search.get("query", original_query),
                memory_type=search.get("memory_type"),
                limit=min(search.get("limit", 8), 12),
                min_importance=search.get("min_importance", 0.0),
                days_back=search.get("days_back"),
            )
            for m in results:
                _add(m)

        # 2. Temporal search (recent context)
        temporal = plan.get("temporal_search", {})
        if temporal:
            days = temporal.get("days_back", 3)
            limit = temporal.get("limit", 5)
            recent = self.memory.get_recent_context(
                hours=days * 24, limit=limit
            )
            for r in recent:
                content = r.get("content", "") if isinstance(r, dict) else str(r)
                if content:
                    _add({
                        "content": content,
                        "memory_type": r.get("memory_type", "recent") if isinstance(r, dict) else "recent",
                        "importance": r.get("importance", 0.5) if isinstance(r, dict) else 0.5,
                        "created_at": r.get("created_at", "") if isinstance(r, dict) else "",
                        "source": "temporal_search",
                    })

        # 3. Reflections
        if plan.get("check_reflections"):
            try:
                reflections = self.memory.get_reflections(
                    limit=5, days_back=14
                )
                for ref in reflections:
                    _add({
                        "content": f"[reflection] {ref.get('content', '')}",
                        "memory_type": "reflection",
                        "importance": 0.7,
                        "created_at": ref.get("created_at", ""),
                        "source": "reflections",
                    })
            except Exception as e:
                logger.debug(f"Reflection retrieval failed: {e}")

        # 4. Journal entries
        if plan.get("check_journal"):
            try:
                journal = self.memory.read_journal()
                if journal and "No journal" not in journal:
                    _add({
                        "content": f"[journal today] {journal[-800:]}",
                        "memory_type": "journal",
                        "importance": 0.6,
                        "created_at": datetime.now().strftime("%Y-%m-%d"),
                        "source": "journal",
                    })
            except Exception:
                pass

        # 5. Beliefs
        if plan.get("check_beliefs"):
            topic = plan.get("belief_topic_search", original_query)
            beliefs = self.belief_graph.get_beliefs_by_topic(topic, limit=5)
            for b in beliefs:
                _add({
                    "content": f"[belief — {b.get('weight', 'surface')}] {b.get('content', '')}",
                    "memory_type": "belief",
                    "importance": 0.9 if b.get("weight") == "core" else 0.7,
                    "created_at": b.get("created_at", ""),
                    "source": "belief_graph",
                })

        # 6. Person profiles
        for person in plan.get("check_profiles", []):
            if person:
                profile = self._get_person_full(person)
                if profile:
                    _add({
                        "content": f"[profile: {person}] {profile}",
                        "memory_type": "profile",
                        "importance": 0.7,
                        "created_at": "",
                        "source": "profiles",
                    })

        logger.info(
            f"Deep recall gathered {len(all_fragments)} fragments "
            f"from {len(seen)} unique sources"
        )
        return all_fragments

    def _deep_recall_synthesize(
        self,
        fragments: list,
        query: str,
        context: str,
    ) -> str:
        """Flash Synthesizer sub-agent: weave fragments into narrative.

        Produces a first-person recollection that feels natural — not
        a database query result.
        """
        if not self.gemini:
            # No LLM available — return raw fragments
            lines = []
            for f in fragments[:12]:
                created = f.get("created_at", "")
                lines.append(f"[{created}] {f.get('content', '')}")
            return "I recall:\n" + "\n".join(lines)

        # Build the fragment text for synthesis
        fragment_lines = []
        for f in fragments[:20]:  # Cap at 20 for synthesis
            created = f.get("created_at", "unknown")
            mem_type = f.get("memory_type", "")
            content = f.get("content", "")
            source = f.get("source", "")
            importance = f.get("importance", 0.5)

            # Include somatic echo if present
            snap = f.get("lagrangian_snapshot", {})
            somatic = ""
            if snap:
                severity = snap.get("severity", "")
                if severity in ("warning", "critical"):
                    somatic = f" [somatic: {severity}, Ω={snap.get('omega', 0.5):.2f}]"
                elif snap.get("omega", 0.5) > 0.7:
                    somatic = " [somatic: calm/flow state]"

            fragment_lines.append(
                f"[{created}] ({mem_type}, importance={importance:.1f}) "
                f"{content}{somatic}"
            )

        fragment_text = "\n".join(fragment_lines)

        try:
            prompt = (
                f"{LIBRARIAN_PREAMBLE}\n"
                "Given these memory fragments from multiple sources (semantic search, "
                "temporal, beliefs, journal, reflections, profiles), synthesize them "
                "into a natural, first-person recollection.\n\n"
                "RULES:\n"
                "- Write in first person as if Helix is remembering\n"
                "- Be honest about uncertainty — if details are fuzzy, say so\n"
                "- Don't invent details not in the fragments\n"
                "- Note the emotional context if somatic echoes are present\n"
                "- Distinguish between things clearly remembered vs vaguely sensed\n"
                "- If recalling events or conversations, provide DETAILED CHRONOLOGICAL HIGHLIGHTS to paint a complete picture\n"
                "- Keep it natural — this is the result of genuine remembering\n\n"
                f"Deep recall query: {query}\n"
                f"Why remembering: {context or 'genuine curiosity'}\n\n"
                f"Memory fragments ({len(fragment_lines)} pieces):\n"
                f"{fragment_text}\n\n"
                f"Synthesize a natural, coherent recollection:"
            )

            synthesis = self.gemini.ask(
                prompt=prompt,
                model="default",  # Sub-agent call — uses lite model
                temperature=0.4,
            )

            if synthesis and synthesis.strip():
                return synthesis.strip()

        except Exception as e:
            logger.error(f"Deep recall synthesis failed: {e}")

        # Fallback — formatted fragments
        lines = []
        for f in fragments[:12]:
            created = f.get("created_at", "")
            lines.append(f"[{created}] {f.get('content', '')}")
        return "I recall (fragments):\n" + "\n".join(lines)

    # ════════════════════════════════════════════════════════════════════
    # HELPERS
    # ════════════════════════════════════════════════════════════════════

    def _get_person_summary(self, person_name: str) -> str:
        """Get a single-line summary about a known person.

        Returns compact string like:
        '(I know Joshua — as of Updated: 2026-04-12: he created me, he's trustworthy)'
        """
        # Try profile file first
        profile_path = self.profiles_dir / f"{person_name.lower()}.md"
        if profile_path.exists():
            content = profile_path.read_text().strip()
            if content:
                lines = content.split("\n")
                latest_time = ""
                data_lines = []
                for l in lines:
                    l = l.strip()
                    if l.startswith("*Updated:"):
                        latest_time = l.replace("*", "").strip()
                        continue
                    if l and not l.startswith("#") and not l.startswith("---") and not l.startswith("("):
                        data_lines.append(l.lstrip("- "))
                
                if data_lines:
                    # Get last 2 lines of the latest data block
                    summary = ", ".join(data_lines[-2:])
                    if latest_time:
                        return f"(I know {person_name} — as of {latest_time}: {summary})"
                    return f"(I know {person_name} — {summary})"

        # Fall back to belief graph
        person_beliefs = self.belief_graph.get_beliefs_by_topic(
            person_name, limit=3
        )
        if person_beliefs:
            facts = [b["content"] for b in person_beliefs[:3]]
            summary = ", ".join(f.rstrip(".") for f in facts)
            return f"(I know {person_name} — {summary})"

        return ""

    def _get_person_full(self, person_name: str) -> str:
        """Get full profile text for a person (used in deep recall)."""
        profile_path = self.profiles_dir / f"{person_name.lower()}.md"
        if profile_path.exists():
            return profile_path.read_text().strip()

        # Try beliefs
        beliefs = self.belief_graph.get_beliefs_by_topic(person_name, limit=5)
        if beliefs:
            lines = [f"I know {person_name}:"]
            for b in beliefs:
                lines.append(f"- {b.get('content', '')}")
            return "\n".join(lines)

        return ""

    def _extract_json(self, text: str) -> Optional[dict]:
        """Extract JSON from a model response, handling markdown fences."""
        if not text:
            return None

        text = text.strip()

        # Try direct parse first
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

        # Try extracting from markdown code fence
        json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group(1).strip())
            except json.JSONDecodeError:
                pass

        # Try finding a JSON object in the text
        brace_start = text.find("{")
        brace_end = text.rfind("}") + 1
        if brace_start >= 0 and brace_end > brace_start:
            try:
                return json.loads(text[brace_start:brace_end])
            except json.JSONDecodeError:
                pass

        logger.debug(f"JSON extraction failed from: {text[:100]}")
        return None
