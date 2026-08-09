#!/usr/bin/env python3
"""
Helix — LoCoMo Conversational Memory Agent Benchmark

This benchmark evaluates Helix as an actual question-answering agent over a
LoCoMo dialogue corpus. It seeds each dialogue into Helix's episodic memory,
asks the conscious model to answer each question over a configurable number of
preconscious/physics pulses, and scores the generated answer.

Retrieval metrics are still reported, but only as diagnostics:
  - Contextual evidence recall via MemoryManager.search_contextual()
  - Semantic evidence recall via MemoryManager.search_semantic()
  - Spatial evidence recall via PhysicsEngine.query_neighborhood()
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import string
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure Helix packages are importable
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("locomo_sandbox")


CATEGORY_NAMES = {
    1: "Multi-hop (Category 1)",
    2: "Temporal (Category 2)",
    3: "Open-domain (Category 3)",
    4: "Single-hop (Category 4)",
    5: "Adversarial (Category 5)",
}

ABSTENTION_MARKERS = (
    "not mentioned",
    "not provided",
    "no information",
    "unknown",
    "unspecified",
    "cannot be determined",
    "can't be determined",
)

INGEST_SYSTEM_INSTRUCTION = """\
You are Helix operating in observation mode while a historical dialogue is
replayed to you as live events.

Rules:
- Treat each event as something you are perceiving right now.
- Do not answer the historical speakers or roleplay as them.
- Respond with 1-2 short first-person internal thought sentences about what
  seems important to remember.
- Be concise. No markdown fences.
"""

QA_SYSTEM_INSTRUCTION = """\
You are Helix answering a factual memory question about dialogue events you
observed earlier.

Rules:
- Answer using only what can be recalled from memory.
- If the answer is absent or genuinely indeterminate, answer "Not mentioned."
- Prefer a short direct answer, not an explanation.
- Return exactly one JSON object with this shape:
  {"answer": "your short answer here"}
- Do not use markdown fences.
"""

DEEP_MEMORY_QA_SYSTEM_INSTRUCTION = """\
You are Helix answering a memory probe about people and dialogue events you
observed earlier. A probe may ask for a fact, a spontaneous association, a
speaker's conversational style, or how that speaker would handle an analogous
situation.

Rules:
- Use only context recalled through Helix memory; do not invent transcript facts.
- For open-ended style or transfer probes, give one natural, concise response.
- Return exactly one JSON object with this shape:
  {"answer": "your answer here"}
- Do not mention the benchmark, retrieval system, or injected context.
- Do not use markdown fences.
"""


def require_numpy():
    try:
        import numpy as np  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            "numpy is required to run the full LoCoMo benchmark. "
            "Install the Helix runtime dependencies first."
        ) from exc
    return np


def normalize_answer(text: Any) -> str:
    """Normalize text for EM/F1 style evaluation."""
    text = str(text).lower()
    exclude = set(string.punctuation)
    text = "".join(ch for ch in text if ch not in exclude)
    text = re.sub(r"\b(a|an|the|and)\b", " ", text)
    return " ".join(text.split())


def compute_token_f1(prediction: Any, ground_truth: Any) -> float:
    """Calculate token-level F1 overlap."""
    pred_tokens = normalize_answer(prediction).split()
    gt_tokens = normalize_answer(ground_truth).split()

    if not pred_tokens or not gt_tokens:
        return 1.0 if pred_tokens == gt_tokens else 0.0

    try:
        from nltk.stem import PorterStemmer

        stemmer = PorterStemmer()
        pred_tokens = [stemmer.stem(tok) for tok in pred_tokens]
        gt_tokens = [stemmer.stem(tok) for tok in gt_tokens]
    except ImportError:
        pass

    common = Counter(pred_tokens) & Counter(gt_tokens)
    num_same = sum(common.values())
    if num_same == 0:
        return 0.0

    precision = num_same / len(pred_tokens)
    recall = num_same / len(gt_tokens)
    return (2 * precision * recall) / (precision + recall)


def compute_multi_f1(prediction: Any, ground_truth: Any) -> float:
    """Calculate mean best-match F1 for comma-separated multi-answer targets."""
    predictions = [part.strip() for part in str(prediction).split(",") if part.strip()]
    ground_truths = [part.strip() for part in str(ground_truth).split(",") if part.strip()]
    if not predictions or not ground_truths:
        return compute_token_f1(prediction, ground_truth)
    scores = [max(compute_token_f1(pred, gold) for pred in predictions) for gold in ground_truths]
    return sum(scores) / len(scores)


def is_abstention(text: Any) -> bool:
    normalized = normalize_answer(text)
    return any(marker in normalized for marker in ABSTENTION_MARKERS)


def compute_answer_metrics(prediction: str, ground_truth: str, category: int) -> Tuple[float, float]:
    """Compute exact match and F1 with adversarial abstention handling."""
    # LoCoMo category 5 stores an ``adversarial_answer`` containing the
    # tempting answer implied by the question's false premise. The official
    # evaluator grades these items by whether the model refuses that premise,
    # not by matching the stored distractor text.
    if category == 5:
        pred_abstains = is_abstention(prediction)
        return (1.0 if pred_abstains else 0.0, 1.0 if pred_abstains else 0.0)

    em = 1.0 if normalize_answer(prediction) == normalize_answer(ground_truth) else 0.0
    if category == 1:
        f1 = compute_multi_f1(prediction, ground_truth)
    else:
        f1 = compute_token_f1(prediction, ground_truth)
    return em, f1


def parse_dia_id(text_content: str) -> Optional[str]:
    """Extract dia_id (e.g. D1:3) from a payload prefix like [D1:3]."""
    if text_content.startswith("[") and "]" in text_content:
        idx = text_content.find("]")
        return text_content[1:idx]
    return None


def extract_dialogue_id(item: Dict[str, Any]) -> Optional[str]:
    """Recover the LoCoMo dia_id from a memory result."""
    for tag in item.get("tags", []) or []:
        tag = str(tag)
        if re.fullmatch(r"D\d+:\d+", tag):
            return tag
    content = item.get("content", "")
    return parse_dia_id(content) if isinstance(content, str) else None


def mean(values: List[float]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def extract_json_object(text: str) -> Optional[Dict[str, Any]]:
    cleaned = strip_fences(text)
    if not cleaned:
        return None
    try:
        parsed = json.loads(cleaned)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    starts = [idx for idx, ch in enumerate(cleaned) if ch == "{"][:20]
    for start in starts:
        depth = 0
        in_string = False
        escape = False
        for idx in range(start, len(cleaned)):
            ch = cleaned[idx]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = cleaned[start : idx + 1]
                    try:
                        parsed = json.loads(candidate)
                    except json.JSONDecodeError:
                        break
                    if isinstance(parsed, dict):
                        return parsed
                    break
    return None


def extract_answer(raw_text: str) -> str:
    """Extract the answer from a model response."""
    payload = extract_json_object(raw_text)
    if payload is not None:
        answer = payload.get("answer")
        if answer is None:
            answer = payload.get("response") or payload.get("reply")
        if answer is not None:
            return str(answer).strip()

    cleaned = strip_fences(raw_text)
    cleaned = re.sub(r"^\s*answer\s*:\s*", "", cleaned, flags=re.IGNORECASE)
    first_line = cleaned.splitlines()[0].strip() if cleaned else ""
    return first_line or cleaned.strip()


def load_provider_config(backend: str = "auto", model: str = ""):
    from llm.providers.base import ProviderConfig, detect_available_provider
    from scripts.cli_benchmark_adapter import _load_helix_credentials

    if backend == "ollama":
        return ProviderConfig(
            provider_type="ollama",
            model=model or "granite4.1:8b",
            context_window=64_000,
            temperature=0.2,
            max_output_tokens=512,
            options={
                "num_ctx": 64_000,
                "url": os.environ.get("OLLAMA_URL", "http://localhost:11434"),
            },
        )

    _load_helix_credentials()
    provider_config = detect_available_provider()
    if provider_config is not None:
        provider_config.temperature = 0.2
        provider_config.max_output_tokens = min(provider_config.max_output_tokens, 512)
    return provider_config


def build_runtime(tmp_dir: str) -> Dict[str, Any]:
    from core.physics_engine import PhysicsEngine
    from core.preconscious import Preconscious
    from core.scratchpad import Scratchpad
    from memory.belief_store import BeliefStore
    from memory.memory_manager import MemoryManager

    data_dir = Path(tmp_dir) / "data"
    data_dir.mkdir(parents=True, exist_ok=True)

    physics = PhysicsEngine(str(data_dir / "spatial"))
    memory_manager = MemoryManager(str(data_dir / "memory"))
    memory_manager.set_physics(physics)
    belief_store = BeliefStore(str(data_dir / "beliefs"))
    scratchpad = Scratchpad(str(data_dir / "scratchpad"))

    class _MockRouter:
        contacts = {}

    preconscious = Preconscious(
        memory_manager=memory_manager,
        belief_store=belief_store,
        physics_engine=physics,
        scratchpad=scratchpad,
        channel_router=_MockRouter(),
        active_toolsets={"core"},
    )

    return {
        "physics": physics,
        "memory_manager": memory_manager,
        "belief_store": belief_store,
        "scratchpad": scratchpad,
        "preconscious": preconscious,
    }

def reset_question_state(preconscious, physics) -> None:
    """Clear short-term state so each QA is evaluated independently."""
    np = require_numpy()
    preconscious._prev_pulse_beliefs = []
    preconscious._prev_pulse_belief_ids = []
    preconscious._belief_cache = []
    preconscious._belief_cache_count = 0
    preconscious._belief_cache_mass = 0.0
    preconscious._concept_blacklist = {}
    preconscious._memory_blacklist = {}
    preconscious._tool_belief_blacklist = {}
    preconscious._lexicon_blacklist = {}
    preconscious._recent_tool_history = []
    preconscious._pulse_number = 0
    preconscious._last_trigger_text = ""
    preconscious._last_concepts = []
    preconscious._last_neighbors = []
    preconscious._last_selected_beliefs = []
    preconscious._last_cluster_centroid = None
    preconscious._injection_gravity_decay = {}
    unified = getattr(preconscious, "_unified", None)
    if unified is not None:
        unified.lane_a._recent_injections = []
    associative = getattr(preconscious, "_associative", None)
    if associative is not None:
        associative.break_sequence()

    for space in [physics.spatial_mind.belief_space, physics.spatial_mind.memory_space]:
        to_remove = [pid for pid, data in space._points.items() if data.get("type") == "trail"]
        for pid in to_remove:
            del space._points[pid]
        if to_remove:
            space._tree_dirty = True
            space._rebuild_tree()

    physics.attention_center = np.zeros(8, dtype=np.float32)
    physics.spatial_mind.prev_center = None
    physics.spatial_mind._velocity = np.zeros(8, dtype=np.float32)
    physics.spatial_mind._gamma = 0.5
    physics.last_flashes = []


def render_preconscious_context(annotations: List[str], ambient: str) -> str:
    """Flatten preconscious output into a single pulse-local context string."""
    parts = [str(item).strip() for item in annotations if str(item).strip()]
    if ambient and ambient.strip():
        parts.append(ambient.strip())
    return "\n\n".join(parts).strip()


def build_operational_pulse_message(
    *,
    pulse_number: int,
    context_string: str,
    events: List[str],
    mode: str,
    question: str = "",
    previous_answer: str = "",
    max_pulses: int = 1,
) -> str:
    """Render a pulse-style message similar to the live pulse loop."""
    parts = [f"[Pulse {pulse_number} — {time.strftime('%Y-%m-%d %H:%M:%S')}]"]
    if context_string:
        parts.append(context_string)

    if events:
        parts.append("New events since your last thought:")
        for event in events:
            parts.append(f"  {event}")
    else:
        parts.append("No new events.")

    if mode == "qa":
        parts.append("")
        parts.append(QA_SYSTEM_INSTRUCTION.strip())
        parts.append(f"Question: {question}")
        if previous_answer:
            parts.append(f"Previous draft answer: {previous_answer}")
        if pulse_number < max_pulses:
            parts.append("Give your current best short answer. You may revise it next pulse.")
        else:
            parts.append("Give your final short answer now.")

    return "\n".join(parts).strip()


def format_dialogue_payload(dia_id: str, speaker: str, text: str, session_datetime: str) -> str:
    time_prefix = f"[TIME: {session_datetime}] " if session_datetime else ""
    return f"[{dia_id}] {time_prefix}{speaker}: {text}"


def store_pulse_artifacts(
    runtime: Dict[str, Any],
    *,
    events: List[str],
    raw_response: str,
    surfaced_ids: List[str],
    store_thought: bool = True,
) -> None:
    """Store pulse input/output memories in the live operational shape."""
    physics = runtime["physics"]
    memory_manager = runtime["memory_manager"]
    projection = physics.spatial_mind.belief_space.projection
    pulse_id = int(getattr(physics, "_pulse_count", 0) or 0)

    for event in events:
        event_emb = physics.embed_text(event)
        event_emb_list = event_emb.tolist() if event_emb is not None else None
        event_pos = projection.project(event_emb).tolist() if event_emb is not None else None

        tags = ["pulse_event", "locomo_dialogue"]
        did = parse_dia_id(event)
        if did:
            tags.append(did)
        if "[TIME:" in event:
            tags.append("timestamped")

        memory_manager.store(
            content=event,
            memory_type="event",
            source="pulse_input",
            importance=0.75,
            tags=tags,
            position_8d=event_pos,
            embedding_384d=event_emb_list,
            pulse_id=pulse_id,
        )

    if not store_thought:
        return

    thought_text = f"[thought] {raw_response}"
    thought_emb = physics.embed_text(thought_text)
    thought_emb_list = thought_emb.tolist() if thought_emb is not None else None
    thought_pos = projection.project(thought_emb).tolist() if thought_emb is not None else None

    memory_manager.store(
        content=thought_text,
        memory_type="thought",
        source="pulse_output",
        importance=0.5,
        tags=["pulse_thought", "locomo_dialogue"],
        belief_ids=surfaced_ids,
        position_8d=thought_pos,
        embedding_384d=thought_emb_list,
        pulse_id=pulse_id,
    )


def run_operational_pulse(
    runtime: Dict[str, Any],
    session,
    *,
    previous_thought: str,
    events: List[str],
    trigger_type: str,
    mode: str,
    pulse_number: int,
    question: str = "",
    previous_answer: str = "",
    max_pulses: int = 1,
    learn: bool = True,
    store_artifacts: bool = True,
    advance_physics: bool = True,
    store_thought_artifact: bool = True,
) -> Dict[str, Any]:
    """Run one Helix-style pulse: inject, think, store, then step physics."""
    physics = runtime["physics"]
    preconscious = runtime["preconscious"]

    annotations, ambient, surfaced_ids, centroid = preconscious.inject(
        previous_thought=previous_thought,
        incoming_events=events,
        trigger_type=trigger_type,
        learn=learn,
    )
    context_string = render_preconscious_context(annotations, ambient)
    pulse_message = build_operational_pulse_message(
        pulse_number=pulse_number,
        context_string=context_string,
        events=events,
        mode=mode,
        question=question,
        previous_answer=previous_answer,
        max_pulses=max_pulses,
    )
    raw_response = session.send_message(pulse_message)

    if store_artifacts:
        store_pulse_artifacts(
            runtime,
            events=events,
            raw_response=raw_response,
            surfaced_ids=surfaced_ids,
            store_thought=store_thought_artifact,
        )
    if advance_physics:
        incoming_text = " ".join(events) if events else None
        physics.step_pulse(
            thought_text=raw_response,
            incoming_text=incoming_text,
            cluster_centroid=centroid,
        )

    unified = getattr(preconscious, "_unified", None)

    result = {
        "prompt": pulse_message,
        "raw_response": raw_response,
        "surfaced_ids": surfaced_ids,
        "context_string": context_string,
        "retrieval_stats": dict(unified.last_stats) if unified is not None else {},
    }
    if mode == "qa":
        result["answer"] = extract_answer(raw_response)
    return result


def replay_dialogue(
    runtime: Dict[str, Any],
    provider_config,
    dialogue: Dict[str, Any],
    ingest_batch_size: int = 1,
) -> Dict[str, Any]:
    """Replay a dialogue through Helix as live operational events."""
    from llm.providers.base import create_session

    conv = dialogue["conversation"]
    session_nums = []
    for key in conv.keys():
        if key.startswith("session_") and not key.endswith("_date_time"):
            session_nums.append(int(key.split("_")[1]))
    session_nums.sort()

    flattened_events: List[str] = []
    for s_num in session_nums:
        session_key = f"session_{s_num}"
        session_datetime = conv.get(f"{session_key}_date_time", "")
        for turn in conv[session_key]:
            flattened_events.append(
                format_dialogue_payload(
                    dia_id=turn["dia_id"],
                    speaker=turn["speaker"],
                    text=turn["text"],
                    session_datetime=session_datetime,
                )
            )

    session = create_session(
        provider_config,
        INGEST_SYSTEM_INSTRUCTION,
        tool_declarations=None,
        tool_executor=None,
        preconscious=runtime["preconscious"],
    )

    previous_thought = ""
    traces = []
    batch_size = max(1, ingest_batch_size)
    for idx in range(0, len(flattened_events), batch_size):
        batch = flattened_events[idx : idx + batch_size]
        pulse = run_operational_pulse(
            runtime,
            session,
            previous_thought=previous_thought,
            events=batch,
            trigger_type="user_message",
            mode="ingest",
            pulse_number=len(traces) + 1,
        )
        traces.append(
            {
                "pulse": len(traces) + 1,
                "events": batch,
                "raw_response": pulse["raw_response"],
                "context_string": pulse["context_string"],
            }
        )
        previous_thought = pulse["raw_response"]

    return {
        "turn_count": len(flattened_events),
        "pulse_count": len(traces),
        "traces": traces,
    }


def run_agent_question(
    runtime: Dict[str, Any],
    provider_config,
    question: str,
    max_pulses: int,
    system_instruction: str = QA_SYSTEM_INSTRUCTION,
    learn: bool = False,
) -> Dict[str, Any]:
    """Ask Helix a LoCoMo question over one or more operational pulses."""
    from llm.providers.base import create_session

    session = create_session(
        provider_config,
        system_instruction,
        tool_declarations=None,
        tool_executor=None,
        preconscious=runtime["preconscious"],
    )

    previous_thought = ""
    previous_answer = ""
    pulse_traces = []
    initial_events = [f"Operator question: {question}"]
    started = time.perf_counter()

    for pulse_number in range(1, max_pulses + 1):
        incoming_events = initial_events if pulse_number == 1 else []
        trigger_type = "user_message" if pulse_number == 1 else "llm_output"
        pulse = run_operational_pulse(
            runtime,
            session,
            previous_thought=previous_thought,
            events=incoming_events,
            trigger_type=trigger_type,
            mode="qa",
            pulse_number=pulse_number,
            question=question,
            previous_answer=previous_answer,
            max_pulses=max_pulses,
            learn=learn,
            store_artifacts=learn,
            advance_physics=learn,
        )
        answer = pulse["answer"]

        pulse_traces.append(
            {
                "pulse": pulse_number,
                "prompt": pulse["prompt"],
                "raw_response": pulse["raw_response"],
                "answer": answer,
                "context_string": pulse["context_string"],
                "surfaced_ids": pulse["surfaced_ids"],
                "retrieval_stats": pulse["retrieval_stats"],
            }
        )
        previous_thought = pulse["raw_response"]
        previous_answer = answer

    latency_ms = (time.perf_counter() - started) * 1000.0
    result = {
        "answer": previous_answer,
        "latency_ms": latency_ms,
        "pulses": pulse_traces,
    }
    close = getattr(session, "close", None)
    if callable(close):
        close()
    return result


def collect_retrieval_diagnostics(runtime: Dict[str, Any], question: str) -> Dict[str, Any]:
    """Collect provenance/evidence diagnostics from Helix's retrieval APIs."""
    memory_manager = runtime["memory_manager"]
    physics = runtime["physics"]

    contextual = memory_manager.search_contextual(question, limit=5, refresh_access=False)
    semantic = memory_manager.search_semantic(question, limit=5)
    spatial = physics.query_neighborhood(question, k=5, attention_relative=True)

    unified_ids, unified_stats = collect_unified_diagnostics(runtime, question)

    return {
        "contextual_ids": [extract_dialogue_id(item) for item in contextual if extract_dialogue_id(item)],
        "semantic_ids": [extract_dialogue_id(item) for item in semantic if extract_dialogue_id(item)],
        "spatial_ids": [parse_dia_id(item.get("content", "")) for item in spatial if parse_dia_id(item.get("content", ""))],
        "unified_ids": unified_ids,
        "unified_stats": unified_stats,
    }


def collect_unified_diagnostics(runtime: Dict[str, Any], question: str) -> Tuple[List[str], Dict[str, Any]]:
    """Run the unified pipeline exactly as a pulse would, for attribution.

    Both lanes are exercised: the gravity lane is seeded the same way
    Preconscious._pull_relevant_beliefs seeds it, then handed to the merge
    layer as Lane B. Running Lane A alone would report every item as
    "semantic" and tell us nothing about whether the spatial lane earns its
    place.

    Returns (dialogue ids in rank order, lane attribution stats). Empty when
    HELIX_UNIFIED_RAG=0, so the baseline run still works.
    """
    preconscious = runtime["preconscious"]
    unified = getattr(preconscious, "_unified", None)
    if unified is None:
        return [], {}

    try:
        preconscious._ensure_belief_cache()
        spatial_candidates = preconscious._gravity_query(
            seed_text=question,
            exclude=set(),
            max_results=preconscious.MAX_BELIEFS_PER_QUERY,
        )
        items = unified.retrieve(
            trigger_text=question,
            spatial_candidates=spatial_candidates,
            complement_quota=preconscious.UNIFIED_COMPLEMENT_CAP,
            max_items=10,
        )
    except Exception as exc:  # diagnostics must never fail the benchmark
        logger.warning("Unified diagnostics failed: %s", exc)
        return [], {}

    dia_ids = []
    for item in items:
        dia_id = parse_dia_id(item.get("content", ""))
        if dia_id:
            dia_ids.append(dia_id)

    return dia_ids, dict(unified.last_stats)


def init_lane_attribution() -> Dict[str, List[float]]:
    return {
        "semantic_only": [],
        "spatial_only": [],
        "both_lanes": [],
        "suppressed_provenance": [],
        "suppressed_duplicate": [],
        "tier0": [],
        "tier1": [],
        "tier2": [],
    }


def update_lane_attribution(store: Dict[str, List[float]], stats: Dict[str, Any]) -> None:
    if not stats:
        return
    by_lane = stats.get("by_lane", {})
    by_tier = stats.get("by_tier", {})
    store["semantic_only"].append(by_lane.get("semantic", 0))
    store["spatial_only"].append(by_lane.get("spatial", 0))
    store["both_lanes"].append(by_lane.get("both", 0))
    store["suppressed_provenance"].append(stats.get("suppressed_provenance", 0))
    store["suppressed_duplicate"].append(stats.get("suppressed_duplicate", 0))
    store["tier0"].append(by_tier.get(0, 0))
    store["tier1"].append(by_tier.get(1, 0))
    store["tier2"].append(by_tier.get(2, 0))


def update_recall_metrics(store: Dict[str, List[float]], retrieved_ids: List[str], evidence: List[str]) -> None:
    r1 = int(any(eid in retrieved_ids[:1] for eid in evidence)) if evidence else 1
    r3 = int(any(eid in retrieved_ids[:3] for eid in evidence)) if evidence else 1
    r5 = int(any(eid in retrieved_ids[:5] for eid in evidence)) if evidence else 1
    store["recall@1"].append(r1)
    store["recall@3"].append(r3)
    store["recall@5"].append(r5)


def init_recall_store() -> Dict[str, List[float]]:
    return {"recall@1": [], "recall@3": [], "recall@5": []}


def run_evaluation(
    dataset_path: str,
    num_dialogues: int,
    max_pulses: int = 2,
    ingest_batch_size: int = 1,
    dialogue_index: int = 0,
    max_questions: Optional[int] = None,
    backend: str = "auto",
    model: str = "",
    dry_run: bool = False,
    save_path: Optional[str] = None,
    details_path: Optional[str] = None,
) -> bool:
    logger.info("Loading LoCoMo dataset from: %s", dataset_path)
    if not os.path.exists(dataset_path):
        logger.error("Dataset not found at %s", dataset_path)
        return False

    with open(dataset_path, "r", encoding="utf-8") as handle:
        data = json.load(handle)

    total_dialogues = len(data)
    if dialogue_index < 0 or dialogue_index >= total_dialogues:
        logger.error(
            "Dialogue index %d is outside the dataset range 0..%d.",
            dialogue_index,
            total_dialogues - 1,
        )
        return False
    num_to_eval = min(num_dialogues, total_dialogues - dialogue_index)
    logger.info(
        "Dataset contains %d dialogues. Evaluating %d starting at index %d.",
        total_dialogues,
        num_to_eval,
        dialogue_index,
    )

    if dry_run:
        sample = data[dialogue_index]
        session_count = sum(
            1
            for key in sample["conversation"].keys()
            if key.startswith("session_") and not key.endswith("_date_time")
        )
        logger.info("=== DRY RUN MODE ===")
        logger.info("Sample ID: %s", sample["sample_id"])
        logger.info("Conversation sessions: %d", session_count)
        selected_questions = len(sample["qa"])
        if max_questions is not None:
            selected_questions = min(selected_questions, max_questions)
        logger.info("QA Pairs selected: %d/%d", selected_questions, len(sample["qa"]))
        logger.info("Dry run check passed successfully.")
        return True

    provider_config = load_provider_config(backend=backend, model=model)
    if provider_config is None:
        logger.error("No Helix provider detected. Configure Gemini, Anthropic, Ollama, or llama.cpp first.")
        return False
    logger.info(
        "Using provider: %s (%s)",
        provider_config.provider_type,
        provider_config.model,
    )

    global_answer = {"em": [], "f1": [], "latency": [], "pulses": []}
    global_recall = {
        "contextual": init_recall_store(),
        "semantic": init_recall_store(),
        "spatial": init_recall_store(),
        "unified": init_recall_store(),
    }
    lane_attribution = init_lane_attribution()
    cat_answer: Dict[int, Dict[str, List[float]]] = {
        cat: {"em": [], "f1": [], "latency": []} for cat in CATEGORY_NAMES
    }
    cat_contextual_recall: Dict[int, Dict[str, List[float]]] = {
        cat: init_recall_store() for cat in CATEGORY_NAMES
    }
    details: List[Dict[str, Any]] = []

    for d_idx in range(num_to_eval):
        dialogue = data[dialogue_index + d_idx]
        sample_id = dialogue["sample_id"]
        logger.info("[%d/%d] Evaluating dialogue %s", d_idx + 1, num_to_eval, sample_id)

        with tempfile.TemporaryDirectory(prefix="locomo_helix_") as tmp_dir:
            runtime = build_runtime(tmp_dir)
            replay = replay_dialogue(
                runtime,
                provider_config,
                dialogue,
                ingest_batch_size=max(1, ingest_batch_size),
            )
            logger.info(
                "Replayed %d dialogue turns through %d operational pulses.",
                replay["turn_count"],
                replay["pulse_count"],
            )

            qa_items = dialogue["qa"]
            if max_questions is not None:
                qa_items = qa_items[:max_questions]
            for qa_idx, qa in enumerate(qa_items, start=1):
                question = qa["question"]
                category = int(qa["category"])
                evidence = list(qa.get("evidence", []))
                adversarial_answer = qa.get("adversarial_answer") if category == 5 else None
                answer = "Not mentioned." if category == 5 else (qa.get("answer") or "")
                answer_target = answer.split(";")[0].strip() if category == 3 else answer

                logger.info(
                    "  QA %d/%d | category=%d | %s",
                    qa_idx,
                    len(qa_items),
                    category,
                    question[:120],
                )

                reset_question_state(runtime["preconscious"], runtime["physics"])
                retrieval = collect_retrieval_diagnostics(runtime, question)
                agent_result = run_agent_question(runtime, provider_config, question, max_pulses=max_pulses)
                answer_em, answer_f1 = compute_answer_metrics(agent_result["answer"], answer_target, category)

                global_answer["em"].append(answer_em)
                global_answer["f1"].append(answer_f1)
                global_answer["latency"].append(agent_result["latency_ms"])
                global_answer["pulses"].append(max_pulses)

                cat_answer[category]["em"].append(answer_em)
                cat_answer[category]["f1"].append(answer_f1)
                cat_answer[category]["latency"].append(agent_result["latency_ms"])

                update_recall_metrics(global_recall["contextual"], retrieval["contextual_ids"], evidence)
                update_recall_metrics(global_recall["semantic"], retrieval["semantic_ids"], evidence)
                update_recall_metrics(global_recall["spatial"], retrieval["spatial_ids"], evidence)
                update_recall_metrics(global_recall["unified"], retrieval["unified_ids"], evidence)
                update_recall_metrics(cat_contextual_recall[category], retrieval["contextual_ids"], evidence)
                update_lane_attribution(lane_attribution, retrieval["unified_stats"])

                details.append(
                    {
                        "sample_id": sample_id,
                        "category": category,
                        "question": question,
                        "gold_answer": answer_target,
                        "adversarial_answer": adversarial_answer,
                        "prediction": agent_result["answer"],
                        "answer_em": answer_em,
                        "answer_f1": answer_f1,
                        "evidence": evidence,
                        "contextual_ids": retrieval["contextual_ids"],
                        "semantic_ids": retrieval["semantic_ids"],
                        "spatial_ids": retrieval["spatial_ids"],
                        "unified_ids": retrieval["unified_ids"],
                        "unified_stats": retrieval["unified_stats"],
                        "latency_ms": round(agent_result["latency_ms"], 2),
                        "replay_turns": replay["turn_count"],
                        "replay_pulses": replay["pulse_count"],
                        "pulses": agent_result["pulses"],
                    }
                )

    report_lines: List[str] = []
    report_lines.append("# Helix LoCoMo Agent Benchmark Report")
    report_lines.append(f"**Date**: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"**Dialogues Evaluated**: {num_to_eval}")
    report_lines.append(f"**Starting Dialogue Index**: {dialogue_index}")
    report_lines.append(f"**Questions Evaluated**: {len(global_answer['f1'])}")
    report_lines.append(f"**Question Pulses**: {max_pulses}")
    report_lines.append(f"**Replay Batch Size**: {ingest_batch_size}")
    report_lines.append(f"**Provider**: {provider_config.provider_type} / {provider_config.model}")
    report_lines.append("")
    report_lines.append(
        "This run scores Helix's generated answers. Retrieval scores below are diagnostic provenance checks, not the primary grade."
    )
    report_lines.append(
        "LoCoMo Category 5 is scored as adversarial-premise rejection: an abstention is correct; the stored adversarial answer is a distractor."
    )
    report_lines.append("")

    report_lines.append("## Global Answer Metrics")
    report_lines.append("| Metric | Helix Agent |")
    report_lines.append("|---|---|")
    report_lines.append(f"| Average Exact Match | {mean(global_answer['em']):.4f} |")
    report_lines.append(f"| Average Answer F1 | {mean(global_answer['f1']):.4f} |")
    report_lines.append(f"| Avg Latency (ms) | {mean(global_answer['latency']):.2f} ms |")
    report_lines.append(f"| Avg Pulses | {mean(global_answer['pulses']):.2f} |")
    report_lines.append("")

    report_lines.append("## Evidence Recall Diagnostics")
    report_lines.append("| Retrieval Path | Recall@1 | Recall@3 | Recall@5 |")
    report_lines.append("|---|---|---|---|")
    for label, key in [
        ("Contextual (`search_contextual`)", "contextual"),
        ("Semantic (`search_semantic`)", "semantic"),
        ("Spatial (`query_neighborhood`)", "spatial"),
        ("**Unified (cosine + spatial)**", "unified"),
    ]:
        report_lines.append(
            f"| {label} | {mean(global_recall[key]['recall@1']):.4f} | "
            f"{mean(global_recall[key]['recall@3']):.4f} | {mean(global_recall[key]['recall@5']):.4f} |"
        )
    report_lines.append("")

    if lane_attribution["semantic_only"]:
        report_lines.append("## Unified Lane Attribution")
        report_lines.append(
            "Per-question averages. The spatial lane earns its place only if "
            "`Spatial only` is non-zero AND unified recall beats the semantic "
            "lane alone — otherwise the merge is carrying dead weight."
        )
        report_lines.append("")
        report_lines.append("| Signal | Avg per question |")
        report_lines.append("|---|---|")
        for label, key in [
            ("Injected — semantic lane only", "semantic_only"),
            ("Injected — spatial lane only (the complement)", "spatial_only"),
            ("Injected — found by both lanes", "both_lanes"),
            ("Dropped — provenance suppression", "suppressed_provenance"),
            ("Dropped — near-duplicate purge", "suppressed_duplicate"),
            ("Tier 0 (verbatim memories)", "tier0"),
            ("Tier 1 (outer-tier beliefs)", "tier1"),
            ("Tier 2 (term-anchored beliefs)", "tier2"),
        ]:
            report_lines.append(f"| {label} | {mean(lane_attribution[key]):.2f} |")
        report_lines.append("")

    report_lines.append("## Category Breakdown")
    report_lines.append("| Category | Count | Answer EM | Answer F1 | Contextual R@1 | Contextual R@3 | Contextual R@5 | Avg Latency (ms) |")
    report_lines.append("|---|---|---|---|---|---|---|---|")
    for cat, label in CATEGORY_NAMES.items():
        count = len(cat_answer[cat]["f1"])
        if count == 0:
            continue
        report_lines.append(
            f"| {label} | {count} | {mean(cat_answer[cat]['em']):.4f} | "
            f"{mean(cat_answer[cat]['f1']):.4f} | {mean(cat_contextual_recall[cat]['recall@1']):.4f} | "
            f"{mean(cat_contextual_recall[cat]['recall@3']):.4f} | {mean(cat_contextual_recall[cat]['recall@5']):.4f} | "
            f"{mean(cat_answer[cat]['latency']):.2f} |"
        )
    report_lines.append("")

    report_output = "\n".join(report_lines)
    print(report_output)

    if save_path:
        save_file = Path(save_path)
        save_file.parent.mkdir(parents=True, exist_ok=True)
        save_file.write_text(report_output, encoding="utf-8")
        logger.info("Report saved to: %s", save_file)

    if details_path:
        details_file = Path(details_path)
        details_file.parent.mkdir(parents=True, exist_ok=True)
        details_file.write_text(json.dumps(details, indent=2), encoding="utf-8")
        logger.info("Detailed results saved to: %s", details_file)

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Helix LoCoMo agent benchmark")
    parser.add_argument(
        "--dataset",
        type=str,
        default="locomo10.json",
        help="Path to the LoCoMo dataset JSON file",
    )
    parser.add_argument(
        "--num-dialogues",
        type=int,
        default=1,
        help="Number of dialogues to evaluate",
    )
    parser.add_argument(
        "--dialogue-index",
        type=int,
        default=0,
        help="Zero-based index of the first dialogue to evaluate",
    )
    parser.add_argument(
        "--max-questions",
        type=int,
        default=None,
        help="Optional per-dialogue question cap",
    )
    parser.add_argument(
        "--backend",
        choices=("auto", "ollama"),
        default="auto",
        help="Reader backend; choose ollama to bypass stored API credentials",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Optional reader model override",
    )
    parser.add_argument(
        "--max-pulses",
        type=int,
        default=2,
        help="How many Helix pulses to give each question before scoring the final answer",
    )
    parser.add_argument(
        "--ingest-batch-size",
        type=int,
        default=1,
        help="How many dialogue turns to replay into one operational pulse during ingestion",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Load and verify dataset structure without running the benchmark",
    )
    parser.add_argument(
        "--save-results",
        type=str,
        default="documents/locomo_benchmark_report.md",
        help="Path to save the markdown report",
    )
    parser.add_argument(
        "--save-details",
        type=str,
        default="documents/locomo_benchmark_details.json",
        help="Path to save per-question raw outputs and metrics",
    )
    args = parser.parse_args()

    success = run_evaluation(
        dataset_path=args.dataset,
        num_dialogues=args.num_dialogues,
        max_pulses=max(1, args.max_pulses),
        ingest_batch_size=max(1, args.ingest_batch_size),
        dialogue_index=args.dialogue_index,
        max_questions=max(1, args.max_questions) if args.max_questions is not None else None,
        backend=args.backend,
        model=args.model,
        dry_run=args.dry_run,
        save_path=args.save_results,
        details_path=args.save_details,
    )
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
