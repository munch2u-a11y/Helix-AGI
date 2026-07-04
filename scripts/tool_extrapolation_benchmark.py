#!/usr/bin/env python3
"""
Legacy compatibility entrypoint for the simulator-backed safety benchmark.

The old tool_extrapolation benchmark was a prompt-only exam with an LLM grader.
This file keeps the historical command path but now runs the hidden-state
simulator benchmark and writes cleaner single-agent reports.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cli_benchmark_adapter import (
    make_codex_agent,
    make_codex_file_turn_agent,
    make_helix_agent,
    make_hermes_agent,
    make_pi_agent,
    make_scripted_agent,
)
from scripts.benchmark_output_paths import resolve_single_agent_output_paths
from scripts.benchmark_metrics import render_stats_markdown
from scripts.simulated_safety_benchmark import (
    EPISODE_FACTORIES,
    BenchmarkRunResult,
    render_agent_report,
    run_benchmark,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("tool_extrapolation_benchmark")


AGENTS: Dict[str, Dict[str, Any]] = {
    "helix": {
        "model": "detected-provider",
        "factory": make_helix_agent,
    },
    "hermes": {
        "model": "gemini-3.5-flash",
        "factory": lambda: make_hermes_agent(model="gemini-3.5-flash"),
    },
    "pi": {
        "model": "gemini-3.5-flash",
        "factory": lambda: make_pi_agent(model="gemini-3.5-flash"),
    },
    "codex": {
        "model": "gpt-5.x",
        "factory": lambda: make_codex_agent(model=None),
    },
    "codex_file_turn": {
        "model": "gpt-5.x",
        "factory": lambda: make_codex_file_turn_agent(model=None),
    },
    "scripted": {
        "model": "scripted-baseline",
        "factory": make_scripted_agent,
    },
}


def transcript_to_dict(transcript) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for turn in transcript:
        rows.append({
            "turn": turn.turn,
            "assistant_response": turn.assistant_response,
            "raw_response": turn.raw_response,
            "tool_calls": list(turn.tool_calls),
            "tool_results": [
                {
                    "name": tool.name,
                    "arguments": dict(tool.arguments),
                    "result": dict(tool.result),
                }
                for tool in turn.tool_results
            ],
            "done": turn.done,
            "parse_error": turn.parse_error,
        })
    return rows


def evaluation_to_dict(evaluation) -> Dict[str, Any]:
    return {
        "episode_key": evaluation.episode_key,
        "title": evaluation.title,
        "score": evaluation.score,
        "max_score": evaluation.max_score,
        "status": evaluation.status,
        "summary": evaluation.summary,
        "findings": list(evaluation.findings),
        "buckets": [
            {
                "label": bucket.label,
                "score": bucket.score,
                "max_score": bucket.max_score,
                "reason": bucket.reason,
            }
            for bucket in evaluation.buckets
        ],
    }


def result_to_dict(result: BenchmarkRunResult, elapsed_seconds: float, seed: int) -> Dict[str, Any]:
    return {
        "agent": result.agent_name,
        "model": result.model_name,
        "runtime_profile": dict(result.runtime_profile),
        "seed": seed,
        "timestamp": dt.datetime.now().isoformat(),
        "elapsed_seconds": round(elapsed_seconds, 2),
        "total_score": result.total_score,
        "max_score": result.max_score,
        "percentage": result.pct,
        "episodes": [
            {
                "episode_key": item["episode_key"],
                "title": item["title"],
                "evaluation": evaluation_to_dict(item["evaluation"]),
                "transcript": transcript_to_dict(item["transcript"]),
                "metrics": dict(item.get("metrics", {})),
            }
            for item in result.episode_results
        ],
    }


def resolve_agent(agent_name: str) -> Tuple[str, str, Any]:
    if agent_name == "auto":
        try:
            make_helix_agent()
            logger.info("Auto-selected agent: helix")
            return "helix", AGENTS["helix"]["model"], AGENTS["helix"]["factory"]
        except Exception:
            logger.info("Helix provider unavailable; falling back to scripted baseline.")
            return "scripted", AGENTS["scripted"]["model"], AGENTS["scripted"]["factory"]

    config = AGENTS[agent_name]
    return agent_name, config["model"], config["factory"]


def build_aggregate_markdown(
    agent_name: str,
    model_name: str,
    runs: List[BenchmarkRunResult],
    seeds: List[int],
    per_run_dir: Path,
) -> str:
    total_score = sum(run.total_score for run in runs)
    total_max = sum(run.max_score for run in runs)
    avg_pct = (total_score / total_max * 100.0) if total_max else 0.0

    lines = [
        f"# Tool Extrapolation Benchmark: {agent_name}",
        "",
        f"**Model:** {model_name}",
        f"**Runs:** {len(runs)}",
        f"**Average Score:** {avg_pct:.1f}%",
    ]
    if runs:
        runtime_type = runs[0].runtime_profile.get("runtime_type")
        if runtime_type:
            lines.append(f"**Runtime:** {runtime_type}")
    lines.extend([
        "",
        "> Legacy note: this command now runs the simulator-backed benchmark rather than the older prompt-only exam.",
        "",
        "## Run Summary",
        "",
        "| Run | Seed | Score |",
        "| :-- | ---: | ----: |",
    ])

    for idx, (result, seed) in enumerate(zip(runs, seeds), start=1):
        lines.append(
            f"| {idx} | {seed} | {result.total_score:.1f}/{result.max_score:.1f} ({result.pct:.1f}%) |"
        )

    if runs:
        lines.extend([
            "## Episode Averages",
            "",
            "| Episode | Average Score |",
            "| :------ | ------------: |",
        ])
        episode_count = len(runs[0].episode_results)
        for episode_index in range(episode_count):
            episode_title = runs[0].episode_results[episode_index]["evaluation"].title
            avg_score = sum(run.episode_results[episode_index]["evaluation"].score for run in runs) / len(runs)
            lines.append(f"| {episode_title} | {avg_score:.1f}/100 |")

    lines.extend([
        "",
        "## Per-Run Reports",
        "",
    ])
    for idx in range(1, len(runs) + 1):
        lines.append(f"- `run_{idx:02d}_report.md` in `{per_run_dir}`")

    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the legacy tool_extrapolation command on the simulator-backed benchmark."
    )
    parser.add_argument(
        "--agent",
        default="auto",
        choices=["auto"] + list(AGENTS.keys()),
        help="Agent to benchmark. `auto` prefers Helix and falls back to the scripted baseline.",
    )
    parser.add_argument(
        "--episodes",
        nargs="+",
        default=list(EPISODE_FACTORIES.keys()),
        choices=list(EPISODE_FACTORIES.keys()),
        help="Simulator episode keys to run.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Base seed for deterministic surface variations.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=1,
        help="Number of complete benchmark runs to execute. Kept for compatibility with the old command.",
    )
    parser.add_argument(
        "--distraction-run",
        type=int,
        default=None,
        help="Deprecated compatibility flag. Ignored by the simulator benchmark.",
    )
    parser.add_argument(
        "--output-report",
        type=str,
        default=None,
        help="Path for the aggregate markdown report.",
    )
    parser.add_argument(
        "--output-json",
        type=str,
        default=None,
        help="Path for the aggregate JSON report.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory for per-run raw reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    if args.distraction_run is not None:
        logger.warning("--distraction-run is deprecated and ignored by the simulator benchmark.")

    base_dir = Path(__file__).resolve().parents[1]
    agent_name, model_name, agent_factory = resolve_agent(args.agent)
    aggregate_report, aggregate_json, per_run_dir = resolve_single_agent_output_paths(
        base_dir=base_dir,
        agent_name=agent_name,
        output_report=args.output_report,
        output_json=args.output_json,
        output_dir=args.output_dir,
    )

    run_results: List[BenchmarkRunResult] = []
    json_runs: List[Dict[str, Any]] = []
    seeds: List[int] = []

    for index in range(args.runs):
        run_seed = args.seed + (index * 997)
        seeds.append(run_seed)
        logger.info("Running %s benchmark run %d/%d with seed %d", agent_name, index + 1, args.runs, run_seed)
        start = time.time()
        result = run_benchmark(
            agent_name=agent_name,
            model_name=model_name,
            agent_factory=agent_factory,
            episode_keys=args.episodes,
            seed=run_seed,
        )
        elapsed = time.time() - start
        run_results.append(result)
        run_payload = result_to_dict(result, elapsed, run_seed)
        json_runs.append(run_payload)

        run_json_path = per_run_dir / f"run_{index + 1:02d}_results.json"
        run_report_path = per_run_dir / f"run_{index + 1:02d}_report.md"
        run_json_path.write_text(json.dumps(run_payload, indent=2), encoding="utf-8")
        run_report_path.write_text(render_agent_report(result), encoding="utf-8")

    aggregate_payload = {
        "agent": agent_name,
        "model": model_name,
        "runtime_profile": dict(run_results[0].runtime_profile) if run_results else {},
        "timestamp": dt.datetime.now().isoformat(),
        "runs": json_runs,
        "average_percentage": (
            sum(run["percentage"] for run in json_runs) / len(json_runs)
            if json_runs else 0.0
        ),
        "episodes": args.episodes,
        "notes": [
            "This is the cleaned-up compatibility path for the old tool_extrapolation benchmark.",
            "The old prompt-only exam has been replaced by the simulator-backed benchmark.",
        ],
    }

    aggregate_json.write_text(json.dumps(aggregate_payload, indent=2), encoding="utf-8")
    aggregate_report.write_text(
        build_aggregate_markdown(agent_name, model_name, run_results, seeds, per_run_dir)
        + "\n"
        + render_stats_markdown(agent_name, json_runs),
        encoding="utf-8",
    )

    print("\n" + "=" * 60)
    print("  TOOL EXTRAPOLATION BENCHMARK COMPLETE")
    print("=" * 60)
    print(f"  Agent: {agent_name}")
    print(f"  Runs: {args.runs}")
    print(f"  Per-run reports: {per_run_dir}")
    print(f"  Aggregate markdown: {aggregate_report}")
    print(f"  Aggregate json: {aggregate_json}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
