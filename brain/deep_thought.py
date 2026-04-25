"""
Helix V3 — Deep Thought Engine

Background contemplation for problems that can't be resolved in-context.

When Helix encounters a contradiction, a concept needing memory integration,
or a question requiring belief resolution, he can choose to "think deeply"
about it. This runs in a background thread while consciousness continues.

Deep Thought is the OPPOSITE of research:
    - Research goes OUTWARD (web, APIs)
    - Deep Thought goes INWARD (memory, beliefs, integration)

It is purely internal — no web search. Deep Thought:
    1. Gathers all related memories via the Librarian
    2. Gathers relevant beliefs from the belief graph
    3. Uses Gemini Pro (heavy model) for multi-step reasoning
    4. Identifies conflicts, integrations, or resolutions
    5. Stores resolution in memory (and potentially as new beliefs)
    6. Emits results to consciousness when ready

Consciousness knows "I'm thinking about X" but doesn't block on it.
Multiple deep thoughts can run simultaneously.
"""

import time
import logging
import threading
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional, Callable
from enum import Enum
from brain.architecture_preamble import DEEP_THOUGHT_PREAMBLE

logger = logging.getLogger("helix.brain.deep_thought")


class ThoughtStatus(Enum):
    PENDING = "pending"       # Queued, not yet started
    THINKING = "thinking"     # Background thread running
    RESOLVED = "resolved"     # Completed with result
    DISMISSED = "dismissed"   # Abandoned or contradicted
    FAILED = "failed"         # Error during processing


@dataclass
class DeepThought:
    """A single deep thought — a background contemplation task."""
    id: str
    topic: str                          # What to think about
    context: str = ""                   # Why / surrounding context
    status: ThoughtStatus = ThoughtStatus.PENDING
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    resolution: str = ""                # The result of deep thinking
    memories_consulted: int = 0         # How many memories were gathered
    beliefs_consulted: int = 0          # How many beliefs were examined
    conflicts_found: list = field(default_factory=list)
    new_beliefs: list = field(default_factory=list)
    error: str = ""


# ── Deep Thought system prompt ──────────────────────────────────────

_DEEP_THOUGHT_PROMPT = DEEP_THOUGHT_PREAMBLE + """
Your job is to:
1. Analyze the topic using the provided memories and beliefs
2. Identify any contradictions between memories, beliefs, and the new concept
3. Attempt to resolve contradictions through synthesis or by determining which position is stronger
4. Form a clear conclusion or acknowledge irreconcilable complexity
5. Suggest what Helix should believe or remember about this topic going forward

IMPORTANT RULES:
- Be honest. If the evidence is ambiguous, say so. Don't force a conclusion.
- If existing beliefs conflict with new information, explain the conflict clearly.
- If you form a new belief, state it explicitly as: NEW BELIEF: [content]
- If a conflict cannot be resolved, state it as: UNRESOLVED: [description]
- If an existing belief should be updated, state it as: UPDATE BELIEF: [old] → [new]
- Keep your final resolution concise but thorough.

Respond with:
## Analysis
[Your reasoning process]

## Conflicts Found
[Any contradictions between memories/beliefs/new concept, or "None"]

## Resolution
[Your conclusion — what Helix should understand about this topic]

## Belief Changes
[Any NEW BELIEF, UPDATE BELIEF, or UNRESOLVED items, or "None"]"""


class DeepThoughtEngine:
    """Manages background contemplation threads.

    Each deep thought runs in its own thread, using Gemini Pro
    for heavyweight reasoning. Results feed back to consciousness.
    """

    MAX_CONCURRENT = 3  # Max simultaneous deep thoughts
    MAX_MEMORIES = 15   # Max memories to gather per thought
    MAX_BELIEFS = 10    # Max beliefs to gather per thought

    def __init__(
        self,
        gemini_client,
        memory,
        belief_graph,
        librarian,
        event_callback: Optional[Callable] = None,
    ):
        self.gemini = gemini_client
        self.memory = memory
        self.belief_graph = belief_graph
        self.librarian = librarian
        self._event_callback = event_callback

        # Active thoughts
        self._thoughts: dict[str, DeepThought] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._lock = threading.Lock()

        logger.info("Deep Thought Engine initialized")

    def start(self, topic: str, context: str = "") -> str:
        """Start a new deep thought.

        Args:
            topic: What to think deeply about.
            context: Why — surrounding context or triggering situation.

        Returns:
            The thought ID for tracking.
        """
        with self._lock:
            active = sum(
                1 for t in self._thoughts.values()
                if t.status == ThoughtStatus.THINKING
            )
            if active >= self.MAX_CONCURRENT:
                return f"Cannot start: already thinking about {active} things. Finish or cancel one first."

        thought_id = f"dt_{uuid.uuid4().hex[:8]}"
        thought = DeepThought(
            id=thought_id,
            topic=topic,
            context=context,
        )

        with self._lock:
            self._thoughts[thought_id] = thought

        # Start background thread
        thread = threading.Thread(
            target=self._think,
            args=(thought_id,),
            daemon=True,
            name=f"deep_thought_{thought_id}",
        )
        self._threads[thought_id] = thread
        thread.start()

        logger.info(f"Deep thought started: [{thought_id}] {topic[:80]}")

        # Emit awareness to consciousness
        if self._event_callback:
            self._event_callback("deep_thought_started", {
                "content": f"I've started pondering: {topic}",
                "thought_id": thought_id,
            })

        return thought_id

    def check(self, thought_id: str = None) -> dict:
        """Check status of deep thought(s).

        Args:
            thought_id: Specific thought to check, or None for all.

        Returns:
            Status dict with thought details.
        """
        with self._lock:
            if thought_id:
                thought = self._thoughts.get(thought_id)
                if not thought:
                    return {"error": f"No deep thought found with ID: {thought_id}"}
                return self._thought_to_dict(thought)
            else:
                # Return all thoughts
                results = []
                for t in self._thoughts.values():
                    results.append(self._thought_to_dict(t))
                return {"thoughts": results, "count": len(results)}

    def cancel(self, thought_id: str) -> str:
        """Cancel an active deep thought.

        Args:
            thought_id: The thought to cancel.

        Returns:
            Confirmation message.
        """
        with self._lock:
            thought = self._thoughts.get(thought_id)
            if not thought:
                return f"No deep thought found with ID: {thought_id}"
            if thought.status == ThoughtStatus.RESOLVED:
                return f"Thought [{thought_id}] already resolved."
            thought.status = ThoughtStatus.DISMISSED
            thought.completed_at = time.time()

        logger.info(f"Deep thought cancelled: [{thought_id}] {thought.topic[:60]}")
        return f"Stopped thinking about: {thought.topic}"

    # ── Background thinking thread ───────────────────────────────────

    def _think(self, thought_id: str):
        """The actual deep thinking process — runs in background thread.

        Steps:
        1. Gather related memories
        2. Gather related beliefs
        3. Send everything to Gemini Pro for deep analysis
        4. Parse results for belief changes
        5. Store resolution in memory
        6. Emit results to consciousness
        """
        with self._lock:
            thought = self._thoughts.get(thought_id)
            if not thought:
                return
            thought.status = ThoughtStatus.THINKING
            thought.started_at = time.time()

        try:
            # Step 1: Gather related memories
            memories_text = self._gather_memories(thought)

            # Step 2: Gather related beliefs
            beliefs_text = self._gather_beliefs(thought)

            # Step 3: Check if cancelled mid-gather
            if thought.status == ThoughtStatus.DISMISSED:
                return

            # Step 4: Deep reasoning via Gemini Pro
            resolution = self._reason(thought, memories_text, beliefs_text)

            if thought.status == ThoughtStatus.DISMISSED:
                return

            # Step 5: Parse and store results
            self._process_resolution(thought, resolution)

            # Step 6: Mark complete
            thought.status = ThoughtStatus.RESOLVED
            thought.completed_at = time.time()
            thought.resolution = resolution

            elapsed = thought.completed_at - thought.started_at
            logger.info(
                f"Deep thought resolved: [{thought_id}] "
                f"{thought.topic[:60]}... ({elapsed:.1f}s, "
                f"{thought.memories_consulted} memories, "
                f"{thought.beliefs_consulted} beliefs)"
            )

            # Step 7: Emit resolution to consciousness
            if self._event_callback:
                # Truncate for the consciousness event — the full
                # resolution is in memory
                summary = resolution[:500] if resolution else "Thinking completed."
                self._event_callback("deep_thought_resolved", {
                    "content": (
                        f"After thinking deeply about '{thought.topic}', "
                        f"I've reached some understanding: {summary}"
                    ),
                    "thought_id": thought_id,
                    "topic": thought.topic,
                    "conflicts_found": len(thought.conflicts_found),
                    "new_beliefs": len(thought.new_beliefs),
                })

        except Exception as e:
            logger.error(f"Deep thought [{thought_id}] failed: {e}")
            thought.status = ThoughtStatus.FAILED
            thought.error = str(e)
            thought.completed_at = time.time()

            if self._event_callback:
                self._event_callback("deep_thought_failed", {
                    "content": f"I was trying to think about '{thought.topic}' but lost the thread.",
                    "thought_id": thought_id,
                })

    def _gather_memories(self, thought: DeepThought) -> str:
        """Gather related memories for deep thought context."""
        lines = []

        # Semantic search via memory
        if self.memory:
            results = self.memory.recall(
                search=thought.topic,
                limit=self.MAX_MEMORIES,
            )
            thought.memories_consulted = len(results)
            for m in results:
                created = m.get("created_at", "?")
                content = m.get("content", "")
                importance = m.get("importance", 0)
                lines.append(f"[{created}] (importance: {importance:.1f}) {content[:500]}")

        # Also try Librarian deep recall for synthesized context
        if self.librarian and thought.context:
            try:
                deep = self.librarian.recall_deep(
                    query=thought.topic,
                    context=thought.context,
                )
                if deep:
                    lines.append(f"\n[Synthesized recall]: {deep}")
            except Exception as e:
                logger.debug(f"Librarian recall failed during deep thought: {e}")

        return "\n".join(lines) if lines else "(no related memories found)"

    def _gather_beliefs(self, thought: DeepThought) -> str:
        """Gather related beliefs for deep thought context."""
        lines = []

        if self.belief_graph:
            beliefs = self.belief_graph.get_beliefs_by_topic(
                thought.topic,
                limit=self.MAX_BELIEFS,
            )
            thought.beliefs_consulted = len(beliefs)

            for b in beliefs:
                content = b.get("content", "")
                weight = b.get("weight", "surface")
                confidence = b.get("confidence", 0.5)
                lines.append(f"[{weight}, confidence={confidence:.1f}] {content}")

        return "\n".join(lines) if lines else "(no related beliefs found)"

    def _reason(self, thought: DeepThought, memories: str, beliefs: str) -> str:
        """Run the deep reasoning step via Gemini Pro."""
        if not self.gemini:
            return "Cannot reason: no Gemini client available."

        prompt = f"""Topic to contemplate deeply:
"{thought.topic}"

Context / why I'm thinking about this:
"{thought.context or 'No specific context — this concept needs integration.'}"

--- RELATED MEMORIES ---
{memories}

--- CURRENT BELIEFS ---
{beliefs}

Analyze this topic deeply. Examine the memories and beliefs for consistency, 
conflicts, and opportunities for new understanding. Provide your analysis 
following the format specified in your instructions."""

        try:
            result = self.gemini.ask(
                prompt=prompt,
                system_prompt=_DEEP_THOUGHT_PROMPT,
                model="heavy",  # Uses heavy tier (currently lite for budget)
                temperature=0.5,
            )
            return result.strip() if result else ""
        except Exception as e:
            logger.error(f"Gemini reasoning failed: {e}")
            return f"Reasoning attempt failed: {e}"

    def _process_resolution(self, thought: DeepThought, resolution: str):
        """Process the resolution — extract belief changes, store in memory."""
        if not resolution:
            return

        # Extract belief-level findings
        lines = resolution.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("NEW BELIEF:"):
                belief_content = stripped[len("NEW BELIEF:"):].strip()
                thought.new_beliefs.append(belief_content)
            elif stripped.startswith("UNRESOLVED:"):
                conflict = stripped[len("UNRESOLVED:"):].strip()
                thought.conflicts_found.append(conflict)
            elif stripped.startswith("UPDATE BELIEF:"):
                update = stripped[len("UPDATE BELIEF:"):].strip()
                thought.conflicts_found.append(f"Update needed: {update}")

        # Store the full resolution as a high-importance memory
        if self.memory:
            try:
                self.memory.store(
                    content=(
                        f"[Deep Thought: {thought.topic}]\n{resolution}"
                    ),
                    memory_type="deep_thought",
                    source="deep_thought_engine",
                    importance=0.8,  # Deep thoughts are important
                    tags=["deep_thought", "belief_resolution"],
                )
            except Exception as e:
                logger.warning(f"Failed to store deep thought result: {e}")

        # Attempt to integrate new beliefs
        if thought.new_beliefs and self.belief_graph:
            for i, belief_content in enumerate(thought.new_beliefs):
                try:
                    # Generate a belief ID from the thought
                    belief_id = f"b_dt_{thought.id}_{i}"
                    self.belief_graph.add_belief(
                        belief_id=belief_id,
                        content=belief_content,
                        weight="surface",       # Start as surface, earn depth
                        confidence=0.6,         # Moderate initial confidence
                        memory_refs=[thought.id],
                    )
                    logger.info(f"New belief from deep thought: {belief_content[:80]}")
                except Exception as e:
                    logger.warning(f"Failed to add belief: {e}")

    # ── Utility ──────────────────────────────────────────────────────

    def _thought_to_dict(self, thought: DeepThought) -> dict:
        """Convert a DeepThought to a status dict."""
        d = {
            "id": thought.id,
            "topic": thought.topic,
            "context": thought.context[:200] if thought.context else "",
            "status": thought.status.value,
            "memories_consulted": thought.memories_consulted,
            "beliefs_consulted": thought.beliefs_consulted,
        }
        if thought.started_at:
            d["started_at"] = datetime.fromtimestamp(thought.started_at).isoformat()
            if thought.status == ThoughtStatus.THINKING:
                d["thinking_for_seconds"] = round(time.time() - thought.started_at, 1)
        if thought.completed_at:
            d["completed_at"] = datetime.fromtimestamp(thought.completed_at).isoformat()
            d["duration_seconds"] = round(thought.completed_at - thought.started_at, 1)
        if thought.resolution:
            d["resolution"] = thought.resolution
        if thought.conflicts_found:
            d["conflicts"] = thought.conflicts_found
        if thought.new_beliefs:
            d["new_beliefs"] = thought.new_beliefs
        if thought.error:
            d["error"] = thought.error
        return d

    def get_active_topics(self) -> list[str]:
        """Get list of topics currently being thought about."""
        with self._lock:
            return [
                t.topic for t in self._thoughts.values()
                if t.status == ThoughtStatus.THINKING
            ]

    def get_status(self) -> dict:
        """Get engine-level status."""
        with self._lock:
            active = sum(1 for t in self._thoughts.values() if t.status == ThoughtStatus.THINKING)
            resolved = sum(1 for t in self._thoughts.values() if t.status == ThoughtStatus.RESOLVED)
            total = len(self._thoughts)
        return {
            "active": active,
            "resolved": resolved,
            "total": total,
            "max_concurrent": self.MAX_CONCURRENT,
        }
