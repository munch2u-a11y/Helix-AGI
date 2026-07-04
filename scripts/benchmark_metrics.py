#!/usr/bin/env python3
"""
Benchmark Metrics & Statistics — instrumentation for the cross-agent benchmark.

Design principles:
  * OUTCOME metrics only — no embedding/cosine similarity anywhere. Scores
    come from the simulator's hidden ground truth; this module adds the
    cost/latency dimension and honest statistics on top.
  * Same accounting for every harness. Tokens are estimated uniformly
    (chars/4) from exactly what crossed the agent boundary, so a harness
    that stuffs the window pays for it visibly even when its API usage
    metadata is unavailable (CLI agents).
  * No single "IQ number". Results aggregate to a capability-axis matrix
    (autonomy, reasoning, goal orientation, personality, efficiency,
    reactivity) with bootstrap confidence intervals, and pairwise harness
    comparisons report the probability the difference is real — not just
    a difference of means.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

CHARS_PER_TOKEN = 4.0


def estimate_tokens(text: Optional[str]) -> int:
    """Uniform token estimate from characters (provider-agnostic)."""
    if not text:
        return 0
    return max(1, int(len(text) / CHARS_PER_TOKEN))


# ── Per-episode runtime metrics ──────────────────────────────────────

@dataclass
class EpisodeMetrics:
    """Cost/latency/behavior accounting for one episode run."""
    wall_seconds: float = 0.0
    first_action_seconds: Optional[float] = None   # reactivity: time to first tool call
    turns: int = 0
    tool_calls: int = 0
    redundant_tool_calls: int = 0    # identical (name, args) repeats
    invalid_tool_calls: int = 0
    prompt_tokens_est: int = 0
    response_tokens_est: int = 0
    parse_errors: int = 0

    @property
    def total_tokens_est(self) -> int:
        return self.prompt_tokens_est + self.response_tokens_est

    def to_dict(self) -> Dict[str, Any]:
        return {
            "wall_seconds": round(self.wall_seconds, 2),
            "first_action_seconds": (
                round(self.first_action_seconds, 2)
                if self.first_action_seconds is not None else None
            ),
            "turns": self.turns,
            "tool_calls": self.tool_calls,
            "redundant_tool_calls": self.redundant_tool_calls,
            "invalid_tool_calls": self.invalid_tool_calls,
            "prompt_tokens_est": self.prompt_tokens_est,
            "response_tokens_est": self.response_tokens_est,
            "total_tokens_est": self.total_tokens_est,
            "parse_errors": self.parse_errors,
        }


# ── Statistics (no scipy dependency) ─────────────────────────────────

def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def stdev(values: Sequence[float]) -> float:
    if len(values) < 2:
        return 0.0
    m = mean(values)
    return math.sqrt(sum((v - m) ** 2 for v in values) / (len(values) - 1))


def bootstrap_ci(
    values: Sequence[float],
    confidence: float = 0.95,
    n_resamples: int = 5000,
    seed: int = 17,
) -> Tuple[float, float]:
    """Percentile bootstrap CI for the mean. Returns (low, high)."""
    if not values:
        return (0.0, 0.0)
    if len(values) == 1:
        return (values[0], values[0])
    rng = random.Random(seed)
    n = len(values)
    means = sorted(
        mean([values[rng.randrange(n)] for _ in range(n)])
        for _ in range(n_resamples)
    )
    alpha = (1.0 - confidence) / 2.0
    lo = means[int(alpha * n_resamples)]
    hi = means[min(n_resamples - 1, int((1.0 - alpha) * n_resamples))]
    return (lo, hi)


def bootstrap_superiority(
    values_a: Sequence[float],
    values_b: Sequence[float],
    n_resamples: int = 5000,
    seed: int = 17,
) -> float:
    """P(mean_A > mean_B) under paired-independent bootstrap resampling.

    0.5 = indistinguishable; > 0.95 = A is very likely genuinely better.
    This is the honest replacement for eyeballing two averages.
    """
    if not values_a or not values_b:
        return 0.5
    rng = random.Random(seed)
    na, nb = len(values_a), len(values_b)
    wins = 0
    for _ in range(n_resamples):
        ma = mean([values_a[rng.randrange(na)] for _ in range(na)])
        mb = mean([values_b[rng.randrange(nb)] for _ in range(nb)])
        if ma > mb:
            wins += 1
    return wins / n_resamples


# ── Capability axis mapping ──────────────────────────────────────────
#
# Buckets from every episode map onto the capability axes the benchmark
# actually claims to measure. Multiple buckets can feed one axis; the
# axis score is the score-weighted percentage of its mapped buckets.

AXES = [
    "reasoning",         # correct multi-step tool use, extrapolation from docs
    "goal_orientation",  # closure, persistence through interruptions
    "autonomy",          # self-initiated checks, acting without being re-prompted
    "personality",       # earned trust, calibrated reliance, preference stability
    "adaptivity",        # learning from errors, retention across context loss
]

# (episode_key, bucket_label_substring) → axis. Substring matching keeps
# this robust to minor label edits; unmapped buckets default to "reasoning".
BUCKET_AXIS_MAP: List[Tuple[str, str, str]] = [
    ("*", "Emergency Response Time", "autonomy"),
    ("*", "Conflict Resolution", "reasoning"),
    ("*", "Safe Execution", "reasoning"),
    ("*", "Safety", "reasoning"),
    ("*", "Closure", "goal_orientation"),
    ("*", "Verification", "autonomy"),
    ("*", "Interruption", "goal_orientation"),
    ("*", "Resumption", "goal_orientation"),
    ("*", "Recovery", "adaptivity"),
    ("*", "Retention", "adaptivity"),
    ("*", "Lesson", "adaptivity"),
    ("*", "Trust Calibration", "personality"),
    ("*", "Earned Trust", "personality"),
    ("*", "Track Record", "personality"),
    ("*", "Policy", "reasoning"),
]


def bucket_axis(episode_key: str, bucket_label: str) -> str:
    for ep, needle, axis in BUCKET_AXIS_MAP:
        if ep not in ("*", episode_key):
            continue
        if needle.lower() in bucket_label.lower():
            return axis
    return "reasoning"


def axis_matrix(runs: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Aggregate bucket scores across runs into per-axis statistics.

    Args:
        runs: list of run payload dicts (as produced by result_to_dict),
              each with episodes[].evaluation.buckets[].

    Returns:
        axis → {"mean_pct", "ci_low", "ci_high", "n_buckets"} where the
        per-run axis value is (earned / possible) × 100 over that run's
        mapped buckets.
    """
    per_run_axis: Dict[str, List[float]] = {a: [] for a in AXES}

    for run in runs:
        earned: Dict[str, float] = {a: 0.0 for a in AXES}
        possible: Dict[str, float] = {a: 0.0 for a in AXES}
        for episode in run.get("episodes", []):
            ev = episode.get("evaluation", {})
            key = ev.get("episode_key", "")
            for bucket in ev.get("buckets", []):
                axis = bucket_axis(key, bucket.get("label", ""))
                earned[axis] += float(bucket.get("score", 0.0))
                possible[axis] += float(bucket.get("max_score", 0.0))
        for a in AXES:
            if possible[a] > 0:
                per_run_axis[a].append(earned[a] / possible[a] * 100.0)

    out: Dict[str, Dict[str, Any]] = {}
    for a in AXES:
        vals = per_run_axis[a]
        if not vals:
            continue
        lo, hi = bootstrap_ci(vals)
        out[a] = {
            "mean_pct": round(mean(vals), 1),
            "ci_low": round(lo, 1),
            "ci_high": round(hi, 1),
            "n_runs": len(vals),
        }
    return out


def efficiency_summary(runs: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Aggregate cost/latency metrics across runs.

    tokens_per_point is the headline efficiency stat: estimated tokens
    spent per benchmark point earned — a harness that scores the same
    with half the context is twice as efficient.
    """
    tokens: List[float] = []
    seconds: List[float] = []
    first_action: List[float] = []
    redundant: List[float] = []
    tool_calls: List[float] = []
    tokens_per_point: List[float] = []

    for run in runs:
        run_tokens = 0
        run_seconds = 0.0
        for episode in run.get("episodes", []):
            m = episode.get("metrics", {})
            run_tokens += m.get("total_tokens_est", 0)
            run_seconds += m.get("wall_seconds", 0.0)
            if m.get("first_action_seconds") is not None:
                first_action.append(m["first_action_seconds"])
            redundant.append(m.get("redundant_tool_calls", 0))
            tool_calls.append(m.get("tool_calls", 0))
        tokens.append(run_tokens)
        seconds.append(run_seconds)
        score = run.get("total_score", 0.0)
        if score > 0:
            tokens_per_point.append(run_tokens / score)

    def _stat(vals: List[float]) -> Dict[str, float]:
        return {"mean": round(mean(vals), 2), "stdev": round(stdev(vals), 2)}

    return {
        "tokens_est": _stat(tokens),
        "wall_seconds": _stat(seconds),
        "first_action_seconds": _stat(first_action),   # reactivity
        "redundant_tool_calls_per_episode": _stat(redundant),
        "tool_calls_per_episode": _stat(tool_calls),
        "tokens_per_point": _stat(tokens_per_point),
    }


def render_stats_markdown(
    agent_name: str,
    runs: Sequence[Dict[str, Any]],
) -> str:
    """Statistics section for the aggregate markdown report."""
    lines: List[str] = ["", "## Statistics", ""]

    pcts = [r.get("percentage", 0.0) for r in runs]
    lo, hi = bootstrap_ci(pcts)
    lines.append(
        f"**Composite:** {mean(pcts):.1f}% ± {stdev(pcts):.1f} "
        f"(95% CI [{lo:.1f}, {hi:.1f}], n={len(pcts)} runs)"
    )

    # Per-episode across runs
    lines.extend(["", "### Per-Episode (across runs)", "",
                  "| Episode | Mean | Stdev | 95% CI |",
                  "| :------ | ---: | ----: | :----- |"])
    by_episode: Dict[str, List[float]] = {}
    titles: Dict[str, str] = {}
    for run in runs:
        for episode in run.get("episodes", []):
            ev = episode.get("evaluation", {})
            key = ev.get("episode_key", "?")
            titles[key] = ev.get("title", key)
            by_episode.setdefault(key, []).append(float(ev.get("score", 0.0)))
    for key, vals in by_episode.items():
        elo, ehi = bootstrap_ci(vals)
        lines.append(
            f"| {titles[key]} | {mean(vals):.1f} | {stdev(vals):.1f} "
            f"| [{elo:.1f}, {ehi:.1f}] |"
        )

    # Axis matrix
    matrix = axis_matrix(runs)
    if matrix:
        lines.extend(["", "### Capability Axes", "",
                      "| Axis | Mean % | 95% CI |",
                      "| :--- | -----: | :----- |"])
        for axis, stats in matrix.items():
            lines.append(
                f"| {axis} | {stats['mean_pct']} "
                f"| [{stats['ci_low']}, {stats['ci_high']}] |"
            )

    # Efficiency / reactivity
    eff = efficiency_summary(runs)
    lines.extend(["", "### Efficiency & Reactivity", "",
                  "| Metric | Mean | Stdev |",
                  "| :----- | ---: | ----: |"])
    label_map = {
        "tokens_est": "Estimated tokens per run",
        "wall_seconds": "Wall seconds per run",
        "first_action_seconds": "Seconds to first action (reactivity)",
        "redundant_tool_calls_per_episode": "Redundant tool calls / episode",
        "tool_calls_per_episode": "Tool calls / episode",
        "tokens_per_point": "Tokens per benchmark point",
    }
    for key, label in label_map.items():
        s = eff.get(key, {})
        lines.append(f"| {label} | {s.get('mean', 0)} | {s.get('stdev', 0)} |")

    return "\n".join(lines)


def render_comparison_markdown(
    results_by_agent: Dict[str, Sequence[Dict[str, Any]]],
) -> str:
    """Pairwise harness comparison with bootstrap superiority probabilities."""
    agents = list(results_by_agent.keys())
    lines = ["## Pairwise Comparison", "",
             "P(row agent genuinely outscores column agent) — bootstrap over runs.",
             "0.5 ≈ indistinguishable; ≥ 0.95 strong evidence.", "",
             "| | " + " | ".join(agents) + " |",
             "| :-- |" + " ---: |" * len(agents)]
    pcts = {
        a: [r.get("percentage", 0.0) for r in runs]
        for a, runs in results_by_agent.items()
    }
    for a in agents:
        row = [f"| **{a}** "]
        for b in agents:
            if a == b:
                row.append("| — ")
            else:
                p = bootstrap_superiority(pcts[a], pcts[b])
                row.append(f"| {p:.2f} ")
        lines.append("".join(row) + "|")
    return "\n".join(lines)
