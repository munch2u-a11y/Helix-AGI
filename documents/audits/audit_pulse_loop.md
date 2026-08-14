# Pulse Loop Audit

**Status:** Current Runtime Audit · **Last Verified Against Source:** 2026-08-14 · **Branch:** `main`

**Scope:** [`core/pulse_loop.py`](file:///home/nemo/_mrag_composite_test/core/pulse_loop.py)

---

## 1. Runtime Role & State Machine

The `PulseLoop` ([`core/pulse_loop.py`](file:///home/nemo/_mrag_composite_test/core/pulse_loop.py#L120-L280)) owns the event queue, LLM chat session, cadence state transitions, context compression policy, and post-pulse hook dispatch.

### Runtime State Cadences
| State | Cadence | Trigger |
|---|---|---|
| `ACTIVE` | 10 seconds | Incoming user message / critical event |
| `REGULAR` | 30 seconds | 2 minutes without incoming events |
| `RESTING` | 15 minutes (configurable) | 10 minutes in `REGULAR` without activity |
| `DORMANT` | 60-second wake check | Active hours sleep window |

---

## 2. Event Ingestion & Preconscious Context Assembly

In `_pulse()` ([`core/pulse_loop.py`](file:///home/nemo/_mrag_composite_test/core/pulse_loop.py#L810-L1230)):
1. **Event Drain**: Dequeues pending user messages, stability alerts, and tool returns.
2. **Preconscious Injection**: Calls `Preconscious.inject()` to assemble:
   - Layer 2 anchor matches.
   - 1024D Semantic mRAG + Bounded 8D Spatial Complements.
   - Multi-Hop Traversal (`retrieve_multihop`).
   - Organic Tone Induction (`Personal Opinions:` block).
   - Context Office Desks & Shared Bid Arbitration.
3. **Conscious Prompt Assembly**: Combines inbound events, preconscious context, and ambient state notes.
4. **LLM Function Execution**: Executes model inference, parses function calls, and dispatches tools via `ToolExecutor` and [`tools/tool_registry.py`](file:///home/nemo/_mrag_composite_test/tools/tool_registry.py#L30-L110).
5. **Memory Storage & Physics Step**: Persists thought snapshots to [`cognitive_journal.jsonl`](file:///home/nemo/_mrag_composite_test/memory/cognitive_journal.py) and advances spatial attention coordinates ([`core/physics_engine.py`](file:///home/nemo/_mrag_composite_test/core/physics_engine.py#L210-L290)).
6. **Post-Pulse Hook Dispatch**: Runs `BeliefDetector`, `WorkflowDetector`, `EngagementHook`, `AffectHook`, and `CoOccurrenceHook`.

---

## 3. Tool Failure Trapping & Lesson Tracking

When tool calls fail during execution, `_pulse()` notifies `ToolLessonTracker` ([`core/tool_lesson_tracker.py`](file:///home/nemo/_mrag_composite_test/core/tool_lesson_tracker.py#L20-L90)). Operational lessons are captured, deduplicated, and queued for nightly Curator consolidation ($G=2.5$), crystallizing into `skills` beliefs for future sessions.
