#!/usr/bin/env python3
"""Example 04: Record Envelope & Typed Memory Decoration

This example demonstrates how Helix decorates canonical journal records with
provider-free build_record_envelope metadata to support typed evidence retrieval.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from memory.record_envelope import build_record_envelope, ACTION_EVIDENCE_KINDS


def main():
    print("=== Helix AGI Example 04: Record Envelope & Typed Memory Decoration ===")

    # Sample canonical journal record
    content = "Tool [browser] returned: Successfully observed title 'Helix AGI Documentation'."
    memory_type = "tool_result"
    source = "pulse_input"
    tags = ["tool:browser", "verified:true"]

    # Wrap in record envelope
    envelope = build_record_envelope(
        content=content,
        memory_type=memory_type,
        source=source,
        tags=tags
    )

    print(f"[+] Record Kind: {envelope.get('record_kind')}")
    print(f"[+] Epistemic Role: {envelope.get('epistemic_role')}")
    print(f"[+] Action Status: {envelope.get('action_status')}")
    print(f"[+] Is Action Evidence Kind: {envelope.get('record_kind') in ACTION_EVIDENCE_KINDS}")

    assert envelope.get('record_kind') == "tool_result"
    assert envelope.get('record_kind') in ACTION_EVIDENCE_KINDS

    print("\n✓ build_record_envelope evidence assertion decoration verified successfully!")


if __name__ == "__main__":
    main()
