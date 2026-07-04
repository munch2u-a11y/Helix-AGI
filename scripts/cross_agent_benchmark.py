#!/usr/bin/env python3
"""
Cross-agent simulator benchmark.

This entrypoint runs multiple agents through the same hidden-state laboratory
simulation, executes their requested tools, and scores the resulting trace
deterministically. It replaces the earlier prompt-only comparison that graded
essay responses rather than actual behavior.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.cli_benchmark_adapter import (
    make_codex_agent,
    make_codex_file_turn_agent,
    make_helix_agent,
    make_hermes_agent,
    make_pi_agent,
    make_scripted_agent,
)
from scripts.benchmark_output_paths import resolve_comparative_output_dir
from scripts.benchmark_metrics import (
    render_comparison_markdown,
    render_stats_markdown,
)
from scripts.simulated_safety_benchmark import (
    EPISODE_FACTORIES,
    BenchmarkRunResult,
    render_agent_report,
    render_comparative_summary,
    run_benchmark,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(message)s")
logger = logging.getLogger("cross_agent_benchmark")


AVAILABLE_AGENTS = {
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


def transcript_to_dict(transcript) -> List[Dict[str, Any]]:
    data: List[Dict[str, Any]] = []
    for turn in transcript:
        data.append({
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
    return data


def benchmark_result_to_dict(result: BenchmarkRunResult, elapsed_seconds: float) -> Dict[str, Any]:
    return {
        "agent": result.agent_name,
        "model": result.model_name,
        "runtime_profile": dict(result.runtime_profile),
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the simulator-backed cross-agent benchmark.")
    parser.add_argument(
        "--agents",
        nargs="+",
        default=list(AVAILABLE_AGENTS.keys()),
        choices=list(AVAILABLE_AGENTS.keys()),
        help="Agents to benchmark (default: all configured agents).",
    )
    parser.add_argument(
        "--episodes",
        nargs="+",
        default=list(EPISODE_FACTORIES.keys()),
        choices=list(EPISODE_FACTORIES.keys()),
        help="Episode keys to run (default: all simulator episodes).",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=7,
        help="Base random seed used for surface-variation choices.",
    )
    parser.add_argument(
        "--runs",
        type=int,
        default=3,
        help="Runs per agent. Multiple runs enable confidence intervals "
             "and the pairwise superiority comparison.",
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Directory to write JSON and markdown reports.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.runs < 1:
        raise SystemExit("--runs must be at least 1")
    base_dir = Path(__file__).resolve().parents[1]
    out_dir = resolve_comparative_output_dir(base_dir=base_dir, output_dir=args.output_dir)

    all_results: List[BenchmarkRunResult] = []
    runs_by_agent: Dict[str, List[Dict[str, Any]]] = {}

    for agent_name in args.agents:
        config = AVAILABLE_AGENTS[agent_name]
        agent_payloads: List[Dict[str, Any]] = []
        for run_index in range(args.runs):
            run_seed = args.seed + (run_index * 997)
            logger.info(
                "Running benchmark for %s (run %d/%d, seed %d)",
                agent_name, run_index + 1, args.runs, run_seed,
            )
            start = time.time()
            try:
                result = run_benchmark(
                    agent_name=agent_name,
                    model_name=config["model"],
                    agent_factory=config["factory"],
                    episode_keys=args.episodes,
                    seed=run_seed,
                )
            except Exception as exc:
                logger.error("Agent %s failed: %s", agent_name, exc, exc_info=True)
                break
            elapsed = time.time() - start

            raw_payload = benchmark_result_to_dict(result, elapsed)
            raw_payload["seed"] = run_seed
            agent_payloads.append(raw_payload)

            suffix = f"_run{run_index + 1:02d}" if args.runs > 1 else ""
            json_path = out_dir / f"{agent_name}{suffix}_results.json"
            json_path.write_text(json.dumps(raw_payload, indent=2), encoding="utf-8")
            report_path = out_dir / f"{agent_name}{suffix}_report.md"
            report_path.write_text(render_agent_report(result), encoding="utf-8")

            all_results.append(result)

        if agent_payloads:
            runs_by_agent[agent_name] = agent_payloads
            stats_path = out_dir / f"{agent_name}_stats.md"
            stats_path.write_text(
                f"# {agent_name} — statistics over {len(agent_payloads)} runs\n"
                + render_stats_markdown(agent_name, agent_payloads),
                encoding="utf-8",
            )
            logger.info("Stats written to %s", stats_path)

    if not all_results:
        logger.error("No agent results were produced.")
        return 1

    summary_path = out_dir / "comparative_summary.md"
    summary = render_comparative_summary(all_results)
    if len(runs_by_agent) >= 2:
        summary += "\n\n" + render_comparison_markdown(runs_by_agent)
    summary_path.write_text(summary, encoding="utf-8")
    logger.info("Comparative summary written to %s", summary_path)

    print("\n" + "=" * 70)
    print("SIMULATOR BENCHMARK RESULTS")
    print("=" * 70)
    for result in sorted(all_results, key=lambda item: item.pct, reverse=True):
        print(
            f"{result.agent_name:>10} | {result.model_name:<16} | "
            f"{result.total_score:6.1f}/{result.max_score:.1f} | {result.pct:6.1f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
