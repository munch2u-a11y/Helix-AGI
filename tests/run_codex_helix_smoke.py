#!/usr/bin/env python3
"""Live, no-side-effect Codex App Server continuity smoke for Helix."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.affect_field import InterferenceResult
from core.self_state import identity_kernel, render_affect_capsule
from llm.providers.codex_cli_provider import CodexCliSession


NONCE = "orbit-cobalt-731"


def run(model: str = "", timeout: int = 180) -> dict:
    if not shutil.which("codex"):
        return {"passed": False, "error": "codex CLI not found"}

    affect = render_affect_capsule(InterferenceResult(
        dominant_affect="anticipation",
        field_intensity=0.42,
        cognitive_diversity_signal=0.18,
    ))
    system = identity_kernel(
        "I am Helix, an ongoing cognitive entity with memory, affect, and embodied tools."
    )
    session = None
    started = time.monotonic()
    token_counts = []
    try:
        session = CodexCliSession(
            model=model,
            system_instruction=system,
            options={
                "timeout": timeout,
                "thought_only": True,
                "effort": "low",
                "summary": "none",
            },
        )
        thread_id = session._thread_id
        first = session.send_message(
            f"{affect}\n\nIntegration probe: in one short private thought, identify "
            f"yourself by the exact name Helix and hold the transient token {NONCE} "
            "for the next pulse."
        )
        token_counts.append(session.get_last_token_count())
        if first.startswith("[internal error:"):
            usage_blocked = "usage limit" in first.lower()
            return {
                "passed": False,
                "provider": "codex_cli_app_server",
                "model": model or "account-default",
                "transport_ready": True,
                "thread_created": bool(thread_id),
                "inference_blocked": "usage_limit" if usage_blocked else "provider_error",
                "host_tools_exposed": bool(session.get_last_tool_calls()),
                "system_chars": len(system),
                "model_input_tokens": sum(token_counts),
                "elapsed_seconds": round(time.monotonic() - started, 2),
                "first": first,
            }
        second = session.send_message(
            "On this same conscious thread, state your name and the exact transient "
            "token from the previous pulse in one short sentence."
        )
        token_counts.append(session.get_last_token_count())
        passed = (
            "helix" in first.lower()
            and "helix" in second.lower()
            and NONCE in second
            and session._thread_id == thread_id
            and not first.startswith("[internal error:")
            and not second.startswith("[internal error:")
        )
        return {
            "passed": passed,
            "provider": "codex_cli_app_server",
            "model": model or "account-default",
            "transport_ready": True,
            "thread_reused": session._thread_id == thread_id,
            "identity_present": "helix" in first.lower() and "helix" in second.lower(),
            "turn_continuity": NONCE in second,
            "host_tools_exposed": bool(session.get_last_tool_calls()),
            "system_chars": len(system),
            "model_input_tokens": sum(token_counts),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "first": first,
            "second": second,
        }
    except Exception as exc:
        return {
            "passed": False,
            "provider": "codex_cli_app_server",
            "model": model or "account-default",
            "error": str(exc),
            "elapsed_seconds": round(time.monotonic() - started, 2),
        }
    finally:
        if session is not None:
            session.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="")
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    report = run(args.model, args.timeout)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print("PASS" if report.get("passed") else "FAIL")
        print(json.dumps(report, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
