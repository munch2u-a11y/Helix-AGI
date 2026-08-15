#!/usr/bin/env python3
"""Example 03: Action Path Planning & ActionLeg Parsing

This example demonstrates how Helix's ActionPlanner structures multi-step
task requests into outcome-oriented ActionLeg legs or asks clarification questions.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from core.action_planner import ActionPlanner, ActionPlan, ActionLeg


def main():
    print("=== Helix AGI Example 03: Action Path Planning ===")

    mock_model_call = lambda prompt: ""
    planner = ActionPlanner(model_call=mock_model_call)

    # Case 1: Multi-step action request parsing
    raw_plan_text = """
LEG | browser | Navigate to docs and find release notes | DOM shows release notes header
LEG | core | Save summary to release_summary.txt | Read-back matches file content
"""

    plan = planner.parse(
        request="Gather release notes and save summary",
        output=raw_plan_text,
        available=["browser", "core"]
    )

    print(f"[+] Plan Parsed for Request: '{plan.request}'")
    print(f"[+] Total Legs Generated: {len(plan.legs)}")
    for idx, leg in enumerate(plan.legs, 1):
        print(f"    Leg {idx}: [{leg.toolset}] {leg.objective} -> Check: '{leg.success_check}'")

    assert len(plan.legs) == 2
    assert plan.legs[0].toolset == "browser"
    assert plan.legs[1].toolset == "core"

    # Case 2: Material missing input -> ASK / NEED_INPUT question
    clarify_text = "ASK | Which recipient email address should receive the summary report?"
    clarify_plan = planner.parse(
        request="Send the summary report",
        output=clarify_text,
        available=["comms", "core"]
    )

    print(f"\n[+] Clarification Plan Parsed:")
    print(f"    Waiting for Input: {clarify_plan.waiting_for_input}")
    print(f"    Question: '{clarify_plan.question}'")

    assert clarify_plan.waiting_for_input
    assert "recipient email" in clarify_plan.question

    print("\n✓ Action Path planning and clarification logic verified!")


if __name__ == "__main__":
    main()
