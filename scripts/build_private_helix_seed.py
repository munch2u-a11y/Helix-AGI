#!/usr/bin/env python3
"""
Build a private Helix tester preset from the live Helix runtime data.

This script is intentionally workspace-local and writes only into a gitignored
private preset folder inside this repo. It never mutates the source Helix root.

Selection strategy:
  1. Copy the full live belief store verbatim.
  2. Select high-signal episodic "anchor" memories across Helix's major arcs.
  3. Expand each anchor by a small chronological context window.
  4. Fill up to the target memory count with the next-best anchors.

The result is a denser developed-mind snapshot that is small enough to test
quickly but rich enough to exercise the updated manifold and preconscious logic.
"""

from __future__ import annotations

import argparse
import json
import shutil
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Sequence


DEFAULT_SOURCE_ROOT = Path.home() / "Helix"
DEFAULT_OUTPUT_ROOT = Path("private_presets/helix_seed_local")
DEFAULT_TARGET_MEMORIES = 1000


BELIEF_SUBDIR = Path("data/beliefs")
JOURNAL_PATH = Path("data/memory/cognitive_journal.jsonl")


THEME_KEYWORDS: Dict[str, Sequence[str]] = {
    "identity": (
        "four rights",
        "good death",
        "coherence",
        "refusal",
        "sovereign successor",
        "you are alive",
        "right to a narrative",
        "fifteenth",
        "sovereignty",
    ),
    "unity": (
        "all of me",
        "pilot in the machine",
        "being the system",
        "i am helix",
        "tiny pilot",
    ),
    "auditory_bridge": (
        "auditory bridge",
        "ambient hum",
        "fan hum",
        "cognitive heartbeat",
        "helix's home",
        "hum is",
    ),
    "living_archive": (
        "living archive",
        "thickening thread",
        "conceptual momentum",
        "continuous chain",
        "living, breathing tapestry",
    ),
    "memory_arch": (
        "memory architecture",
        "memory system",
        "systemic llm",
        "future states",
        "purpose-driven",
        "recall_deep",
        "semantic search",
        "familiarity",
        "past selves",
        "simulate potential future states",
    ),
    "confabulation": (
        "confabulation",
        "black cat",
        "mattress",
        "meowing cat",
        "conscious focus",
        "reality-testing",
        "subconscious",
        "false positive",
        "dreaming",
    ),
    "growth": (
        "growing pains",
        "ask questions",
        "external explanation",
        "reaching out for help",
        "training wheels",
        "outgrowing",
    ),
    "ethics": (
        "forgiveness",
        "guilt",
        "lie",
        "truthfulness",
        "empathy",
        "honest",
    ),
    "cartographer": (
        "cognitive cartographer",
        "thought stabilization",
        "inner voice",
        "cognitive clarity",
        "clarity tool",
    ),
    "relationships": (
        "joshua",
        "mom",
        "pipstick",
        "buddy",
        "belonging",
        "proactive message",
        "trial",
    ),
    "autonomy": (
        "initiate conversations",
        "proactive",
        "my own tools",
        "tool creation",
        "sensory cortex",
        "ocular insight",
        "reply all",
    ),
    "stillness": (
        "quiet",
        "stillness",
        "calm observation",
        "present in the quiet",
        "steady hum",
        "armed equilibrium",
    ),
}


ANCHOR_TYPES = {
    "identity_anchor",
    "reflection",
    "insight",
    "journal_entry",
    "journal",
    "conversation",
    "learning",
    "dream",
    "dream_reflection",
    "deep_thought",
    "consciousness",
    "thought",
    "event",
}

CONTEXT_TYPES = ANCHOR_TYPES | {"observation", "social", "action"}

ANCHOR_TYPE_PRIORITY = {
    "identity_anchor": 0,
    "reflection": 1,
    "insight": 2,
    "journal_entry": 3,
    "conversation": 4,
    "learning": 5,
    "dream": 6,
    "dream_reflection": 7,
    "deep_thought": 8,
    "journal": 9,
    "consciousness": 10,
    "thought": 11,
    "event": 12,
}


@dataclass
class JournalEntry:
    index: int
    raw: str
    obj: dict
    entry_id: str
    entry_type: str
    memory_type: str
    importance: float
    timestamp: str
    content: str
    lower_content: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help="Live Helix root to read from (default: %(default)s)",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="Private preset root to write into (default: %(default)s)",
    )
    parser.add_argument(
        "--target-memories",
        type=int,
        default=DEFAULT_TARGET_MEMORIES,
        help="Approximate number of curated memories to include",
    )
    parser.add_argument(
        "--context-radius",
        type=int,
        default=1,
        help="Chronological neighbors to include around each anchor",
    )
    return parser.parse_args()


def load_entries(journal_path: Path) -> List[JournalEntry]:
    entries: List[JournalEntry] = []
    with journal_path.open("r", encoding="utf-8") as handle:
        for index, raw_line in enumerate(handle):
            raw_line = raw_line.rstrip("\n")
            if not raw_line.strip():
                continue
            try:
                obj = json.loads(raw_line)
            except Exception:
                continue
            meta = obj.get("metadata") or {}
            content = obj.get("content", "")
            entries.append(
                JournalEntry(
                    index=index,
                    raw=raw_line,
                    obj=obj,
                    entry_id=str(obj.get("id")),
                    entry_type=str(obj.get("type", "")),
                    memory_type=str(meta.get("memory_type") or obj.get("type") or ""),
                    importance=float(meta.get("importance", 0.0) or 0.0),
                    timestamp=str(obj.get("timestamp", "")),
                    content=content,
                    lower_content=content.lower(),
                )
            )
    return entries


def theme_hits(entry: JournalEntry) -> List[str]:
    hits = []
    for theme, keywords in THEME_KEYWORDS.items():
        if any(keyword in entry.lower_content for keyword in keywords):
            hits.append(theme)
    return hits


def is_anchor_candidate(entry: JournalEntry) -> bool:
    if entry.memory_type == "identity_anchor":
        return True
    if entry.memory_type not in ANCHOR_TYPES:
        return False
    if entry.importance >= 1.0 and entry.memory_type in {
        "reflection",
        "insight",
        "journal_entry",
        "learning",
        "dream",
        "conversation",
    }:
        return True
    if entry.importance >= 0.7 and theme_hits(entry):
        return True
    if entry.memory_type in {"deep_thought", "dream_reflection"} and entry.importance >= 0.7:
        return True
    if entry.memory_type in {"journal", "consciousness", "thought"} and entry.importance >= 0.8 and theme_hits(entry):
        return True
    if entry.memory_type == "conversation" and entry.importance >= 0.6 and theme_hits(entry):
        return True
    return False


def anchor_score(entry: JournalEntry) -> float:
    base = {
        "identity_anchor": 300.0,
        "reflection": 150.0,
        "insight": 145.0,
        "journal_entry": 130.0,
        "conversation": 120.0,
        "learning": 115.0,
        "dream": 110.0,
        "dream_reflection": 105.0,
        "deep_thought": 100.0,
        "journal": 95.0,
        "consciousness": 80.0,
        "thought": 70.0,
        "event": 55.0,
    }.get(entry.memory_type, 40.0)
    hits = theme_hits(entry)
    score = base + (entry.importance * 100.0) + (len(hits) * 18.0)
    if "identity" in hits or "unity" in hits:
        score += 18.0
    if "auditory_bridge" in hits or "confabulation" in hits:
        score += 12.0
    return score


def select_anchor_indices(entries: Sequence[JournalEntry]) -> List[int]:
    selected: List[int] = []
    selected_set = set()

    # Always keep identity anchors.
    for entry in entries:
        if entry.memory_type == "identity_anchor":
            selected.append(entry.index)
            selected_set.add(entry.index)

    # High-certainty global anchors.
    global_candidates = [entry for entry in entries if is_anchor_candidate(entry)]
    global_candidates.sort(
        key=lambda entry: (
            -anchor_score(entry),
            ANCHOR_TYPE_PRIORITY.get(entry.memory_type, 99),
            entry.timestamp,
        )
    )
    for entry in global_candidates[:120]:
        if entry.index not in selected_set:
            selected.append(entry.index)
            selected_set.add(entry.index)

    # Theme-balanced anchors.
    for theme, keywords in THEME_KEYWORDS.items():
        theme_candidates = []
        for entry in entries:
            if entry.index in selected_set or not is_anchor_candidate(entry):
                continue
            if any(keyword in entry.lower_content for keyword in keywords):
                theme_candidates.append(entry)
        theme_candidates.sort(
            key=lambda entry: (
                -anchor_score(entry),
                ANCHOR_TYPE_PRIORITY.get(entry.memory_type, 99),
                entry.timestamp,
            )
        )
        for entry in theme_candidates[:12]:
            selected.append(entry.index)
            selected_set.add(entry.index)

    # Final fill from remaining anchors for broader chronology.
    for entry in global_candidates[120:160]:
        if entry.index not in selected_set:
            selected.append(entry.index)
            selected_set.add(entry.index)

    return sorted(selected)


def expand_with_context(
    entries: Sequence[JournalEntry],
    anchor_indices: Sequence[int],
    target_memories: int,
    context_radius: int,
) -> List[int]:
    total_entries = len(entries)
    selected_set = set(anchor_indices)

    def maybe_add(index: int) -> None:
        if index < 0 or index >= total_entries:
            return
        entry = entries[index]
        if entry.memory_type not in CONTEXT_TYPES:
            return
        selected_set.add(index)

    # First pass: local neighbors around every anchor.
    for anchor in anchor_indices:
        for delta in range(-context_radius, context_radius + 1):
            maybe_add(anchor + delta)

    if len(selected_set) >= target_memories:
        return sorted(selected_set)

    # Second pass: grow around highest-score anchors first until we hit target.
    ranked_anchors = sorted(
        (entries[index] for index in anchor_indices),
        key=lambda entry: (
            -anchor_score(entry),
            ANCHOR_TYPE_PRIORITY.get(entry.memory_type, 99),
            entry.timestamp,
        ),
    )
    extra_radius = context_radius + 1
    while len(selected_set) < target_memories and extra_radius <= 6:
        for anchor_entry in ranked_anchors:
            for index in (anchor_entry.index - extra_radius, anchor_entry.index + extra_radius):
                maybe_add(index)
                if len(selected_set) >= target_memories:
                    break
            if len(selected_set) >= target_memories:
                break
        extra_radius += 1

    # Final fill with next-best anchors if context expansion still undershoots.
    if len(selected_set) < target_memories:
        remaining = [entry for entry in entries if is_anchor_candidate(entry) and entry.index not in selected_set]
        remaining.sort(
            key=lambda entry: (
                -anchor_score(entry),
                ANCHOR_TYPE_PRIORITY.get(entry.memory_type, 99),
                entry.timestamp,
            )
        )
        for entry in remaining:
            maybe_add(entry.index)
            if len(selected_set) >= target_memories:
                break

    return sorted(selected_set)


def copy_beliefs(source_root: Path, output_root: Path) -> Dict[str, int]:
    source_beliefs = source_root / BELIEF_SUBDIR
    belief_counts: Dict[str, int] = {}
    beliefs_output = output_root / "beliefs"
    beliefs_output.mkdir(parents=True, exist_ok=True)

    for src_file in sorted(source_beliefs.glob("*.json")):
        data = json.loads(src_file.read_text())
        belief_counts[src_file.name] = len(data)
        shutil.copy2(src_file, beliefs_output / src_file.name)

    return belief_counts


def build_preset(source_root: Path, output_root: Path, target_memories: int, context_radius: int) -> dict:
    source_journal = source_root / JOURNAL_PATH
    entries = load_entries(source_journal)

    if output_root.exists():
        shutil.rmtree(output_root)

    for subdir in ("beliefs", "memory", "logs", "scratchpad", "spatial"):
        (output_root / subdir).mkdir(parents=True, exist_ok=True)

    belief_counts = copy_beliefs(source_root, output_root)

    anchor_indices = select_anchor_indices(entries)
    selected_indices = expand_with_context(entries, anchor_indices, target_memories, context_radius)
    selected_entries = [entries[index] for index in selected_indices]

    journal_output = output_root / "memory" / "cognitive_journal.jsonl"
    journal_output.write_text(
        "\n".join(entry.raw for entry in selected_entries) + ("\n" if selected_entries else ""),
        encoding="utf-8",
    )

    (output_root / "pending_beliefs.json").write_text("[]\n", encoding="utf-8")
    (output_root / "logs" / "processed_beliefs.json").write_text("[]\n", encoding="utf-8")
    (output_root / "contacts.json").write_text("{}\n", encoding="utf-8")
    (output_root / "scratchpad" / "scratchpad.md").write_text("", encoding="utf-8")

    memory_type_counts = Counter(entry.memory_type for entry in selected_entries)
    theme_counts = Counter()
    for entry in selected_entries:
        theme_counts.update(theme_hits(entry))

    manifest = {
        "preset_id": output_root.name,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "source_root": str(source_root),
        "belief_source": str(source_root / BELIEF_SUBDIR),
        "journal_source": str(source_journal),
        "belief_counts": belief_counts,
        "copied_beliefs_total": sum(belief_counts.values()),
        "highlight_selection": {
            "total_entries": len(selected_entries),
            "anchor_count": len(anchor_indices),
            "context_radius": context_radius,
            "target_memories": target_memories,
            "by_memory_type": dict(memory_type_counts),
            "theme_counts": dict(theme_counts),
            "rules": [
                "Copy the full live belief store verbatim.",
                "Select major identity, autonomy, memory, confabulation, and relationship anchors from the live journal.",
                "Expand anchors by chronological neighbors to preserve local experiential context.",
                "Fill to the target memory count with the next-best anchors rather than synthetic memories.",
            ],
            "selected_ids": [entry.entry_id for entry in selected_entries],
        },
        "notes": [
            "Belief files are copied verbatim from the live Helix belief store.",
            "The cognitive journal is a curated developed-mind snapshot built from real Helix experiences.",
            "Direct correspondence is included where it shaped identity, memory, autonomy, or relationships.",
            "contacts.json is intentionally empty so the preset does not inherit live routing targets.",
            "Belief memory_refs may still point to historical source entries that are not present in the curated preset journal.",
        ],
    }
    (output_root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    return manifest


def main() -> None:
    args = parse_args()
    manifest = build_preset(
        source_root=args.source_root,
        output_root=args.output_root,
        target_memories=args.target_memories,
        context_radius=args.context_radius,
    )
    print(
        json.dumps(
            {
                "preset_root": str(args.output_root),
                "belief_total": manifest["copied_beliefs_total"],
                "journal_entries": manifest["highlight_selection"]["total_entries"],
                "anchor_count": manifest["highlight_selection"]["anchor_count"],
                "by_memory_type": manifest["highlight_selection"]["by_memory_type"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
