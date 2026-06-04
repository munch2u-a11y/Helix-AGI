"""Belief Category Migration — old taxonomy → new taxonomy.

Moves belief data files from old category names to new ones:
  self_identity.json → premises.json (appended)
  capabilities.json  → premises.json (appended)
  knowledge.json     → propositions.json (renamed)

Creates empty files for new categories:
  concepts.json (empty)

Files that keep their names: people.json, skills.json, preferences.json, desires.json

Usage:
    cd /home/nemo/Helix
    .venv/bin/python scripts/migrate_categories.py [--dry-run]
"""

import json
import shutil
import sys
import logging
from pathlib import Path
from datetime import datetime

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("migrate_categories")

BELIEFS_DIR = Path("data/beliefs")
BACKUP_DIR = Path(f"backups/pre_category_migration_{datetime.now().strftime('%Y%m%d_%H%M%S')}")


def migrate(dry_run: bool = False):
    """Execute the category migration."""
    
    # Step 0: Create backup
    if not dry_run:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        for f in BELIEFS_DIR.glob("*.json"):
            shutil.copy2(f, BACKUP_DIR / f.name)
        logger.info(f"Backup created: {BACKUP_DIR}")
    
    # Step 1: self_identity.json + capabilities.json → premises.json
    si_file = BELIEFS_DIR / "self_identity.json"
    cap_file = BELIEFS_DIR / "capabilities.json"
    premises_file = BELIEFS_DIR / "premises.json"
    
    premises = []
    
    if si_file.exists():
        si_beliefs = json.loads(si_file.read_text())
        for b in si_beliefs:
            b["_original_category"] = "self_identity"
            b["category"] = "premises"
        premises.extend(si_beliefs)
        logger.info(f"  self_identity.json: {len(si_beliefs)} beliefs → premises.json")
    
    if cap_file.exists():
        cap_beliefs = json.loads(cap_file.read_text())
        for b in cap_beliefs:
            b["_original_category"] = "capabilities"
            b["category"] = "premises"
        premises.extend(cap_beliefs)
        logger.info(f"  capabilities.json:  {len(cap_beliefs)} beliefs → premises.json")
    
    if premises:
        logger.info(f"  premises.json total: {len(premises)} beliefs")
        if not dry_run:
            premises_file.write_text(json.dumps(premises, indent=2))
    
    # Step 2: knowledge.json → propositions.json
    kno_file = BELIEFS_DIR / "knowledge.json"
    prop_file = BELIEFS_DIR / "propositions.json"
    
    if kno_file.exists():
        kno_beliefs = json.loads(kno_file.read_text())
        for b in kno_beliefs:
            b["_original_category"] = "knowledge"
            b["category"] = "propositions"
        logger.info(f"  knowledge.json: {len(kno_beliefs)} beliefs → propositions.json")
        if not dry_run:
            prop_file.write_text(json.dumps(kno_beliefs, indent=2))
    
    # Step 3: Create empty concepts.json
    concepts_file = BELIEFS_DIR / "concepts.json"
    if not concepts_file.exists():
        logger.info("  concepts.json: created (empty)")
        if not dry_run:
            concepts_file.write_text("[]")
    
    # Step 4: Ensure desires.json exists
    desires_file = BELIEFS_DIR / "desires.json"
    if not desires_file.exists():
        logger.info("  desires.json: created (empty)")
        if not dry_run:
            desires_file.write_text("[]")
    
    # Step 5: Remove old files (they're backed up)
    if not dry_run:
        for old_file in [si_file, cap_file, kno_file]:
            if old_file.exists():
                old_file.unlink()
                logger.info(f"  Removed old file: {old_file.name}")
    
    # Final summary
    logger.info(f"\nMigration {'(dry run) ' if dry_run else ''}complete.")
    if not dry_run:
        logger.info(f"Backup at: {BACKUP_DIR}")
        # Verify
        for name in ["premises.json", "propositions.json", "preferences.json",
                      "people.json", "skills.json", "desires.json", "concepts.json"]:
            fpath = BELIEFS_DIR / name
            if fpath.exists():
                count = len(json.loads(fpath.read_text()))
                logger.info(f"  {name:25s} {count:4d} beliefs")
            else:
                logger.warning(f"  {name:25s} MISSING!")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        logger.info("=== DRY RUN ===\n")
    
    logger.info("Belief Category Migration: old taxonomy → new taxonomy\n")
    migrate(dry_run=dry_run)
