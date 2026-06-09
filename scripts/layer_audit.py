"""Belief Layer Audit & Re-sort — fix misplacements from legacy categories.

Moves beliefs to their correct Layer 1/Layer 2 category based on content:
  1. People beliefs without named entities → premises or propositions
  2. Self-observation propositions (My..., I am...) → premises
  3. Skills without tool references → premises (behavioral norms)
  4. Removes exact duplicate IDs
  
Usage:
    cd /home/nemo/Helix
    .venv/bin/python scripts/layer_audit.py --dry-run   # preview changes
    .venv/bin/python scripts/layer_audit.py              # execute changes
"""

import json
import sys
import logging
from pathlib import Path
from collections import Counter

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("layer_audit")

BELIEFS_DIR = Path("data/beliefs")

NAMED_ENTITIES = {
    'user', 'mom', 'david', 'sam', 'valerie', 'marley',
    'zeb', 'mickey', 'freddy', 'patrick', 'antigravity',
    'helix', 'claude', 'archivist', 'storyteller', 'pyclaw',
    'z_cat', 'basin', 'nemo', 'centaurxiv', 'moltbook',
    'qualia', 'telegram', 'discord', 'isotopy', 'el ',
    'fifteenth', 'glugover', 'hal ',
}

TOOL_KEYWORDS = {
    'tool', 'check ', 'use ', 'run ', 'send ', 'email',
    'telegram', 'journalctl', 'systemctl', 'command', 'terminal',
    'calendar', 'search', 'browse', 'look_around', 'listen',
    'screenshot', 'api', 'git', 'ssh', 'systemd', 'python',
    'pip', 'npm', 'piper', 'ollama', 'memory.db', 'sqlite',
    'jsonl', 'cron', 'ntp', 'grep', 'debug',
}


def load_category(name):
    path = BELIEFS_DIR / f"{name}.json"
    if path.exists():
        return json.loads(path.read_text())
    return []


def save_category(name, beliefs):
    path = BELIEFS_DIR / f"{name}.json"
    path.write_text(json.dumps(beliefs, indent=2))


def has_named_entity(content):
    c = content.lower()
    return any(n in c for n in NAMED_ENTITIES)


def has_tool_reference(content):
    c = content.lower()
    return any(kw in c for kw in TOOL_KEYWORDS)


def is_self_observation(content):
    return content.startswith(('My ', 'I am', 'I can', 'I have', 'I must'))


def audit(dry_run=True):
    moves = []  # (belief, from_cat, to_cat, reason)
    removals = []  # (belief, cat, reason)
    
    premises = load_category("premises")
    propositions = load_category("propositions")
    preferences = load_category("preferences")
    people = load_category("people")
    skills = load_category("skills")
    
    # ── 1. People beliefs without named entities ──────────────────
    for b in list(people):
        content = b.get("content", "")
        if not has_named_entity(content):
            if is_self_observation(content):
                moves.append((b, "people", "premises",
                    "Self-observation in people"))
            elif content.startswith(('I should', 'I value', 'I prefer', 'I want')):
                moves.append((b, "people", "preferences",
                    "Preference/norm in people"))
            elif content.startswith(('IF ', 'When ', 'To ')):
                moves.append((b, "people", "premises",
                    "Procedural/conditional in people"))
            else:
                moves.append((b, "people", "propositions",
                    "General knowledge in people"))

    # ── 2. Self-observations in propositions → premises ───────────
    for b in list(propositions):
        content = b.get("content", "")
        if is_self_observation(content):
            moves.append((b, "propositions", "premises",
                "Self-observation in propositions"))

    # ── 3. Skills without tool refs → premises ────────────────────
    for b in list(skills):
        content = b.get("content", "")
        if not has_tool_reference(content):
            if content.startswith(('I should', 'I value', 'I prefer')):
                moves.append((b, "skills", "preferences",
                    "Preference disguised as skill"))
            else:
                moves.append((b, "skills", "premises",
                    "Behavioral norm without tool reference"))

    # ── 4. Deduplicate by ID within each category ─────────────────
    for cat_name, cat_list in [("premises", premises), ("propositions", propositions),
                                ("preferences", preferences), ("people", people),
                                ("skills", skills)]:
        seen_ids = set()
        for b in list(cat_list):
            bid = b.get("id", "")
            if bid in seen_ids:
                removals.append((b, cat_name, f"Duplicate ID: {bid}"))
            else:
                seen_ids.add(bid)
    
    # ── 5. Deduplicate by content across all categories ───────────
    all_contents = {}
    for cat_name, cat_list in [("premises", premises), ("propositions", propositions),
                                ("preferences", preferences), ("people", people),
                                ("skills", skills)]:
        for b in cat_list:
            key = b.get("content", "").strip().lower()[:100]
            if key in all_contents:
                other_cat, other_b = all_contents[key]
                # Keep the one with higher mass
                if b.get("mass", 0) <= other_b.get("mass", 0):
                    removals.append((b, cat_name, 
                        f"Content duplicate of {other_b.get('id','?')} in {other_cat}"))
                # else: the other one should be removed, but we handle that
                # by keeping first-seen
            else:
                all_contents[key] = (cat_name, b)

    # ── Report ────────────────────────────────────────────────────
    logger.info(f"{'=== DRY RUN ===' if dry_run else '=== EXECUTING ==='}\n")
    
    move_summary = Counter()
    for b, from_cat, to_cat, reason in moves:
        move_summary[(from_cat, to_cat)] += 1
    
    logger.info("MOVES:")
    for (from_cat, to_cat), count in sorted(move_summary.items()):
        logger.info(f"  {from_cat:15s} → {to_cat:15s}: {count} beliefs")
    logger.info(f"  TOTAL MOVES: {len(moves)}")
    
    logger.info(f"\nREMOVALS: {len(removals)}")
    for b, cat, reason in removals:
        logger.info(f"  [{cat}] {b.get('id','?')}: {reason}")
    
    if dry_run:
        logger.info("\n(no changes made — run without --dry-run to execute)")
        return
    
    # ── Execute moves ─────────────────────────────────────────────
    cat_data = {
        "premises": premises,
        "propositions": propositions,
        "preferences": preferences,
        "people": people,
        "skills": skills,
    }
    
    # Remove moved beliefs from source
    moved_ids = set()
    for b, from_cat, to_cat, reason in moves:
        bid = b.get("id", "")
        if bid in moved_ids:
            continue
        moved_ids.add(bid)
        
        # Remove from source
        cat_data[from_cat] = [x for x in cat_data[from_cat] if x.get("id") != bid]
        
        # Set correct category tag
        b["category"] = to_cat
        
        # Add to destination
        cat_data[to_cat].append(b)
    
    # Remove duplicates
    removed_ids = set()
    for b, cat, reason in removals:
        bid = b.get("id", "")
        if bid not in removed_ids:
            removed_ids.add(bid)
            cat_data[cat] = [x for x in cat_data[cat] 
                            if x.get("id") != bid or x is not b]
    
    # Save all
    for cat_name, cat_list in cat_data.items():
        save_category(cat_name, cat_list)
        logger.info(f"  Saved {cat_name}: {len(cat_list)} beliefs")
    
    logger.info("\nDone.")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    audit(dry_run=dry_run)
