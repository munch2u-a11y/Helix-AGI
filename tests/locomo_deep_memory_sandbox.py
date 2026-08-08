#!/usr/bin/env python3
"""Progressive LoCoMo-style benchmark for learned associations and behavior.

Unlike the ordinary LoCoMo factual exam, this runner pauses after each
conversation session and asks fresh, non-teaching probes.  It measures:

* direct factual recall (a control signal),
* acquisition of an arbitrary ordered association,
* recognition/production of one speaker's dialect markers,
* transfer of that speaker's tactful persuasion pattern to a new situation.

The included fixture is synthetic and LoCoMo-shaped so its arbitrary relation
and style ground truth are fully controlled.  It does not redistribute or
silently modify the upstream LoCoMo dataset.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.locomo_sandbox import (
    DEEP_MEMORY_QA_SYSTEM_INSTRUCTION,
    INGEST_SYSTEM_INSTRUCTION,
    build_runtime,
    compute_token_f1,
    format_dialogue_payload,
    load_provider_config,
    reset_question_state,
    run_agent_question,
    run_operational_pulse,
)


logger = logging.getLogger("locomo_deep_memory")

DEFAULT_DATASET = Path(__file__).parent / "fixtures" / "locomo_learned_associations.json"


class ScriptedObservationSession:
    """Cheap, content-neutral ingestion for retrieval-system isolation."""

    def send_message(self, _message: str) -> str:
        return "I am observing the event and its place in the sequence."

    def get_history_size(self) -> int:
        return 0


def _normalized(text: Any) -> str:
    return " ".join(re.findall(r"[a-z0-9']+", str(text).lower()))


def score_probe(prediction: str, probe: Dict[str, Any]) -> float:
    """Score a factual, association, style, or behavior-transfer answer."""
    scoring = probe.get("scoring", {}) or {}
    method = scoring.get("method", "token_f1")
    if method == "token_f1":
        return compute_token_f1(prediction, probe.get("answer", ""))

    normalized = _normalized(prediction)
    if method == "contains_any":
        terms = [_normalized(term) for term in scoring.get("terms", [])]
        return 1.0 if any(term and term in normalized for term in terms) else 0.0

    if method == "marker_groups":
        groups = scoring.get("groups", [])
        if not groups:
            return 0.0
        matched = 0
        for alternatives in groups:
            if any(
                (needle := _normalized(marker)) and needle in normalized
                for marker in alternatives
            ):
                matched += 1
        return matched / len(groups)

    raise ValueError(f"Unknown deep-memory scoring method: {method}")


def validate_dataset(data: Any) -> List[str]:
    """Return schema errors for the progressive LoCoMo extension."""
    errors: List[str] = []
    if not isinstance(data, list) or not data:
        return ["dataset must be a non-empty JSON list"]

    for sample_index, sample in enumerate(data):
        prefix = f"sample[{sample_index}]"
        if not isinstance(sample, dict):
            errors.append(f"{prefix} must be an object")
            continue
        conversation = sample.get("conversation")
        probes = sample.get("qa")
        if not isinstance(conversation, dict):
            errors.append(f"{prefix}.conversation must be an object")
            continue
        if not isinstance(probes, list) or not probes:
            errors.append(f"{prefix}.qa must be a non-empty list")
            continue

        sessions = session_numbers(conversation)
        if not sessions:
            errors.append(f"{prefix}.conversation has no session_N arrays")
        for session_num in sessions:
            turns = conversation.get(f"session_{session_num}")
            if not isinstance(turns, list) or not turns:
                errors.append(f"{prefix}.session_{session_num} must be non-empty")
                continue
            for turn_index, turn in enumerate(turns):
                if not all(turn.get(key) for key in ("dia_id", "speaker", "text")):
                    errors.append(
                        f"{prefix}.session_{session_num}[{turn_index}] lacks dia_id/speaker/text"
                    )

        probe_ids = set()
        for probe_index, probe in enumerate(probes):
            pfx = f"{prefix}.qa[{probe_index}]"
            probe_id = probe.get("probe_id")
            if not probe_id:
                errors.append(f"{pfx} lacks probe_id")
            elif probe_id in probe_ids:
                errors.append(f"{pfx} duplicates probe_id={probe_id}")
            probe_ids.add(probe_id)
            checkpoint = probe.get("checkpoint")
            if checkpoint not in sessions:
                errors.append(f"{pfx}.checkpoint={checkpoint} is not a conversation session")
            if not probe.get("question") or not probe.get("probe_type"):
                errors.append(f"{pfx} lacks question/probe_type")
            method = (probe.get("scoring") or {}).get("method", "token_f1")
            if method not in {"token_f1", "contains_any", "marker_groups"}:
                errors.append(f"{pfx} uses unknown scoring method {method}")
    return errors


def session_numbers(conversation: Dict[str, Any]) -> List[int]:
    numbers = []
    for key, value in conversation.items():
        match = re.fullmatch(r"session_(\d+)", key)
        if match and isinstance(value, list):
            numbers.append(int(match.group(1)))
    return sorted(numbers)


def configure_retrieval(profile: str, association_memory: bool, context_limit: int) -> str:
    selected = profile
    if selected not in {"local", "frontier"}:
        raise ValueError(f"Unknown retrieval profile: {profile}")
    os.environ["HELIX_MRAG_PROFILE"] = selected
    os.environ["HELIX_MRAG_CONTEXT_LIMIT"] = str(max(1024, context_limit))
    os.environ["HELIX_ASSOCIATIVE_MEMORY"] = "1" if association_memory else "0"
    return selected


def _provider_for_backend(backend: str, model: str, context_limit: int):
    if backend == "codex-subscription":
        from llm.providers.base import ProviderConfig

        return ProviderConfig(
            provider_type="codex_subscription",
            model=model,
            context_window=context_limit,
            temperature=0.2,
            max_output_tokens=2048,
            options={"timeout": int(os.environ.get("HELIX_CODEX_TIMEOUT", "600"))},
        )
    provider = load_provider_config()
    if provider is not None and model:
        provider.model = model
    return provider


def _close_session(session: Any) -> None:
    close = getattr(session, "close", None)
    if callable(close):
        close()


def _association_stats(runtime: Dict[str, Any]) -> Dict[str, Any]:
    associative = getattr(runtime["preconscious"], "_associative", None)
    return associative.get_stats() if associative is not None else {
        "edges": 0,
        "active_edges": 0,
        "clusters": 0,
        "previous_cluster": None,
    }


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def run_progressive_evaluation(
    *,
    dataset_path: str,
    backend: str = "auto",
    model: str = "",
    retrieval_profile: str = "local",
    association_memory: bool = True,
    context_limit: int = 128_000,
    max_pulses: int = 1,
    ingest_mode: str = "scripted",
    num_samples: Optional[int] = None,
    save_path: Optional[str] = None,
    details_path: Optional[str] = None,
    dry_run: bool = False,
) -> bool:
    dataset_file = Path(dataset_path)
    if not dataset_file.exists():
        logger.error("Dataset not found: %s", dataset_file)
        return False
    data = json.loads(dataset_file.read_text(encoding="utf-8"))
    errors = validate_dataset(data)
    if errors:
        for error in errors:
            logger.error("Dataset error: %s", error)
        return False

    selected_samples = data[: num_samples or len(data)]
    if dry_run:
        probes = sum(len(sample["qa"]) for sample in selected_samples)
        sessions = sum(len(session_numbers(sample["conversation"])) for sample in selected_samples)
        print(
            f"Deep-memory dataset valid: {len(selected_samples)} sample(s), "
            f"{sessions} checkpoints, {probes} probes."
        )
        return True

    profile = configure_retrieval(retrieval_profile, association_memory, context_limit)
    provider = _provider_for_backend(backend, model, context_limit)
    if provider is None:
        logger.error("No provider detected. Use --backend codex-subscription or configure a Helix provider.")
        return False

    from llm.providers.base import create_session

    details: List[Dict[str, Any]] = []
    checkpoint_graphs: Dict[Tuple[str, int], Dict[str, Any]] = {}
    started = time.time()

    for sample in selected_samples:
        sample_id = sample["sample_id"]
        conversation = sample["conversation"]
        probes_by_checkpoint: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        for probe in sample["qa"]:
            probes_by_checkpoint[int(probe["checkpoint"])].append(probe)

        with tempfile.TemporaryDirectory(prefix="helix_deep_memory_") as tmp_dir:
            runtime = build_runtime(tmp_dir)
            if ingest_mode == "connector":
                ingest_session = create_session(
                    provider,
                    INGEST_SYSTEM_INSTRUCTION,
                    tool_declarations=None,
                    tool_executor=None,
                    preconscious=runtime["preconscious"],
                )
            else:
                ingest_session = ScriptedObservationSession()

            previous_thought = ""
            ingest_pulse = 0
            try:
                for checkpoint in session_numbers(conversation):
                    if checkpoint > 1:
                        associative = getattr(runtime["preconscious"], "_associative", None)
                        if associative is not None:
                            associative.break_sequence()

                    session_key = f"session_{checkpoint}"
                    session_datetime = conversation.get(f"{session_key}_date_time", "")
                    for turn in conversation[session_key]:
                        ingest_pulse += 1
                        event = format_dialogue_payload(
                            turn["dia_id"], turn["speaker"], turn["text"], session_datetime,
                        )
                        pulse = run_operational_pulse(
                            runtime,
                            ingest_session,
                            previous_thought=previous_thought,
                            events=[event],
                            trigger_type="user_message",
                            mode="ingest",
                            pulse_number=ingest_pulse,
                            learn=True,
                            store_artifacts=True,
                            advance_physics=True,
                            store_thought_artifact=(ingest_mode == "connector"),
                        )
                        previous_thought = (
                            pulse["raw_response"] if ingest_mode == "connector" else ""
                        )

                    checkpoint_graphs[(sample_id, checkpoint)] = _association_stats(runtime)
                    reset_question_state(runtime["preconscious"], runtime["physics"])

                    for probe in probes_by_checkpoint.get(checkpoint, []):
                        result = run_agent_question(
                            runtime,
                            provider,
                            probe["question"],
                            max_pulses=max(1, max_pulses),
                            system_instruction=DEEP_MEMORY_QA_SYSTEM_INSTRUCTION,
                            learn=False,
                        )
                        score = score_probe(result["answer"], probe)
                        final_pulse = result["pulses"][-1]
                        retrieval_stats = final_pulse.get("retrieval_stats", {})
                        details.append({
                            "sample_id": sample_id,
                            "checkpoint": checkpoint,
                            "probe_id": probe["probe_id"],
                            "probe_type": probe["probe_type"],
                            "question": probe["question"],
                            "gold_answer": probe.get("answer", ""),
                            "prediction": result["answer"],
                            "score": score,
                            "evidence": probe.get("evidence", []),
                            "latency_ms": round(result["latency_ms"], 2),
                            "context_string": final_pulse.get("context_string", ""),
                            "retrieval_stats": retrieval_stats,
                            "association_graph": checkpoint_graphs[(sample_id, checkpoint)],
                            "pulses": result["pulses"],
                        })
                        logger.info(
                            "%s checkpoint=%d probe=%s score=%.3f",
                            sample_id, checkpoint, probe["probe_id"], score,
                        )
                        reset_question_state(runtime["preconscious"], runtime["physics"])
            finally:
                _close_session(ingest_session)

    by_type: Dict[str, List[float]] = defaultdict(list)
    by_checkpoint: Dict[int, List[float]] = defaultdict(list)
    for row in details:
        by_type[row["probe_type"]].append(row["score"])
        by_checkpoint[row["checkpoint"]].append(row["score"])

    provider_label = f"{provider.provider_type} / {provider.model or 'account-default'}"
    report = [
        "# Helix Progressive Deep-Memory Benchmark",
        "",
        f"- Date: {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- Provider: {provider_label}",
        f"- mRAG profile: {profile}",
        f"- Associative memory: {'on' if association_memory else 'off'}",
        f"- Ingestion mode: {ingest_mode}",
        f"- Samples: {len(selected_samples)}",
        f"- Probes: {len(details)}",
        f"- Elapsed: {time.time() - started:.1f}s",
        "",
        "Exam turns are retrieval-only: they are not stored, do not step physics, and do not reinforce association edges.",
        "",
        "## Scores by capability",
        "",
        "| Capability | Probes | Mean score |",
        "|---|---:|---:|",
    ]
    for probe_type in sorted(by_type):
        report.append(f"| {probe_type} | {len(by_type[probe_type])} | {_mean(by_type[probe_type]):.3f} |")

    report.extend([
        "",
        "## Progressive acquisition",
        "",
        "| Checkpoint | All-probe mean | Association score | Active graph edges | Assoc. surfaced |",
        "|---:|---:|---:|---:|---:|",
    ])
    checkpoints = sorted(by_checkpoint)
    for checkpoint in checkpoints:
        checkpoint_rows = [row for row in details if row["checkpoint"] == checkpoint]
        association_rows = [
            row for row in checkpoint_rows if row["probe_type"] == "arbitrary_association"
        ]
        active_edges = max(
            (row["association_graph"].get("active_edges", 0) for row in checkpoint_rows),
            default=0,
        )
        assoc_injected = sum(
            row["retrieval_stats"].get("associative_selected", 0)
            + row["retrieval_stats"].get("associative_satisfied_existing", 0)
            for row in association_rows
        )
        report.append(
            f"| {checkpoint} | {_mean(row['score'] for row in checkpoint_rows):.3f} | "
            f"{_mean(row['score'] for row in association_rows):.3f} | {active_edges} | {assoc_injected} |"
        )

    report.extend([
        "",
        "## Probe results",
        "",
        "| Checkpoint | Probe | Type | Score | Prediction |",
        "|---:|---|---|---:|---|",
    ])
    for row in details:
        prediction = row["prediction"].replace("|", "\\|").replace("\n", " ")
        report.append(
            f"| {row['checkpoint']} | {row['probe_id']} | {row['probe_type']} | "
            f"{row['score']:.3f} | {prediction} |"
        )

    report_output = "\n".join(report)
    print(report_output)
    if save_path:
        path = Path(save_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(report_output, encoding="utf-8")
    if details_path:
        path = Path(details_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(details, indent=2), encoding="utf-8")
    return True


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(description="Progressive learned-memory benchmark")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--backend", choices=("auto", "codex-subscription"), default="auto")
    parser.add_argument("--model", default="", help="Optional provider/Codex model; empty uses the account default")
    parser.add_argument("--retrieval-profile", choices=("local", "frontier"), default=None)
    parser.add_argument("--context-limit", type=int, default=128_000)
    parser.add_argument("--association-memory", choices=("on", "off"), default="on")
    parser.add_argument("--ingest-mode", choices=("scripted", "connector"), default="scripted")
    parser.add_argument("--max-pulses", type=int, default=1)
    parser.add_argument("--num-samples", type=int, default=None)
    parser.add_argument("--save-results", default="benchmark_results/deep_memory_report.md")
    parser.add_argument("--save-details", default="benchmark_results/deep_memory_details.json")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    profile = args.retrieval_profile or (
        "frontier" if args.backend == "codex-subscription" else "local"
    )
    success = run_progressive_evaluation(
        dataset_path=args.dataset,
        backend=args.backend,
        model=args.model,
        retrieval_profile=profile,
        association_memory=args.association_memory == "on",
        context_limit=max(1024, args.context_limit),
        max_pulses=max(1, args.max_pulses),
        ingest_mode=args.ingest_mode,
        num_samples=args.num_samples,
        save_path=args.save_results,
        details_path=args.save_details,
        dry_run=args.dry_run,
    )
    raise SystemExit(0 if success else 1)


if __name__ == "__main__":
    main()
