#!/usr/bin/env python3
"""Helpers for timestamped benchmark output paths."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Optional, Tuple


def timestamp_slug(now: Optional[dt.datetime] = None) -> str:
    current = now or dt.datetime.now()
    return current.strftime("%Y%m%d_%H%M%S")


def resolve_single_agent_output_paths(
    *,
    base_dir: Path,
    agent_name: str,
    output_report: Optional[str],
    output_json: Optional[str],
    output_dir: Optional[str],
) -> Tuple[Path, Path, Path]:
    stamp = timestamp_slug()
    root = base_dir / "documents" / "benchmark" / "tool_extrapolation" / f"{stamp}_{agent_name}"

    aggregate_report = Path(output_report) if output_report else root / "aggregate_report.md"
    aggregate_json = Path(output_json) if output_json else root / "aggregate_results.json"
    per_run_dir = Path(output_dir) if output_dir else root / "runs"

    per_run_dir.mkdir(parents=True, exist_ok=True)
    aggregate_report.parent.mkdir(parents=True, exist_ok=True)
    aggregate_json.parent.mkdir(parents=True, exist_ok=True)
    return aggregate_report, aggregate_json, per_run_dir


def resolve_comparative_output_dir(*, base_dir: Path, output_dir: Optional[str]) -> Path:
    if output_dir:
        out_dir = Path(output_dir)
    else:
        out_dir = base_dir / "documents" / "benchmark" / "comparative" / timestamp_slug()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir
