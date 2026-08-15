#!/usr/bin/env python3
"""Example 01: Basic Memory & Journal Setup

This example demonstrates how to initialize Helix AGI's canonical CognitiveJournal
and Scratchpad working memory structures.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from memory.cognitive_journal import CognitiveJournal
from core.scratchpad import Scratchpad


def main():
    print("=== Helix AGI Example 01: Basic Memory & Journal Setup ===")

    data_dir = ROOT_DIR / "data"
    data_dir.mkdir(exist_ok=True)

    # Initialize canonical storage directory
    memory_dir = data_dir / "memory"
    memory_dir.mkdir(exist_ok=True)
    
    journal = CognitiveJournal(memory_dir)
    records = journal.load_all()

    print(f"[+] Canonical CognitiveJournal initialized at: {journal.path}")
    print(f"[+] Current journal record count: {len(records)}")

    # Initialize Scratchpad working memory
    scratchpad_dir = data_dir / "scratchpad"
    scratchpad = Scratchpad(str(scratchpad_dir))
    note_id = scratchpad.add_note("Pinned system observation for demonstration.")
    
    print(f"[+] Scratchpad note added with ID: {note_id}")
    print(f"[+] Active notes count: {len(scratchpad.get_active_notes())}")

    print("\n✓ Basic memory components initialized successfully.")


if __name__ == "__main__":
    main()
