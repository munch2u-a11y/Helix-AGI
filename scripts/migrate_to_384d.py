#!/usr/bin/env python3
"""
Helix — One-Time Migration: 8D Projected → 384D Native Embeddings

Migrates all beliefs from position_8d (8 floats) to embedding (384 floats)
by re-embedding each belief's content text through all-MiniLM-L6-v2.

Also updates journal entries and cleans up old state files.

Usage:
    python scripts/migrate_to_384d.py [--dry-run]
"""

import os
import sys
import json
import glob
import shutil
import logging
import argparse
from pathlib import Path
from datetime import datetime

# Ensure project root is on path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("migrate_384d")


def get_embedder():
    """Load the embedding model."""
    from chromadb.utils.embedding_functions import DefaultEmbeddingFunction
    embedder = DefaultEmbeddingFunction()
    logger.info("Embedder loaded (all-MiniLM-L6-v2)")
    return embedder


def migrate_beliefs(data_dir: Path, embedder, dry_run: bool = False):
    """Re-embed all beliefs from content text → 384D."""
    beliefs_dir = data_dir / "beliefs"
    if not beliefs_dir.exists():
        logger.warning(f"No beliefs directory at {beliefs_dir}")
        return 0

    total = 0
    for json_file in sorted(beliefs_dir.glob("*.json")):
        try:
            with open(json_file) as f:
                beliefs = json.load(f)
        except Exception as e:
            logger.error(f"Failed to read {json_file}: {e}")
            continue

        modified = 0
        for belief in beliefs:
            content = belief.get("content", "")
            if not content or len(content) < 3:
                continue

            # Skip if already has 384D embedding
            existing = belief.get("embedding")
            if existing and len(existing) == 384:
                continue

            # Embed content → 384D
            try:
                result = embedder([content])
                embedding = result[0]
                if len(embedding) != 384:
                    logger.warning(f"Unexpected embedding dim {len(embedding)} for belief {belief.get('id')}")
                    continue
                belief["embedding"] = [float(x) for x in embedding]
                modified += 1
            except Exception as e:
                logger.error(f"Embedding failed for {belief.get('id')}: {e}")

        if modified > 0 and not dry_run:
            with open(json_file, "w") as f:
                json.dump(beliefs, f, indent=2, ensure_ascii=False)
            logger.info(f"  {json_file.name}: {modified} beliefs re-embedded")
        elif modified > 0:
            logger.info(f"  [DRY RUN] {json_file.name}: {modified} beliefs would be re-embedded")

        total += modified

    return total


def migrate_journal(data_dir: Path, embedder, dry_run: bool = False):
    """Add 384D embeddings to journal entries that have content."""
    journal_path = data_dir / "cognitive_journal.jsonl"
    if not journal_path.exists():
        logger.info("No journal file found — skipping")
        return 0

    entries = []
    modified = 0
    with open(journal_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
                content = entry.get("content", "")

                # Skip if already has 384D embedding
                existing = entry.get("embedding")
                if existing and len(existing) == 384:
                    entries.append(entry)
                    continue

                # Only embed entries with content
                if content and len(content) >= 5:
                    try:
                        result = embedder([content])
                        entry["embedding"] = [float(x) for x in result[0]]
                        modified += 1
                    except Exception:
                        pass

                entries.append(entry)
            except json.JSONDecodeError:
                entries.append(json.loads(line) if line else {})

    if modified > 0 and not dry_run:
        with open(journal_path, "w") as f:
            for entry in entries:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        logger.info(f"  Journal: {modified} entries re-embedded")
    elif modified > 0:
        logger.info(f"  [DRY RUN] Journal: {modified} entries would be re-embedded")

    return modified


def cleanup_old_state(data_dir: Path, dry_run: bool = False):
    """Remove old 8D state files that are now invalid."""
    old_files = [
        "spatial_state/cognitive_projection.npy",
        "spatial_state/belief_space.json",
        "spatial_state/memory_space.json",
        "spatial_state/belief_space_state.json",
        "spatial_state/memory_space_state.json",
        "spatial_state/attention_center.npy",
        "spatial_state/velocity.npy",
        "spatial_state/identity_center.npy",
        "spatial_state/prev_center.npy",
        "spatial_state/scalars.json",
    ]

    removed = 0
    for rel_path in old_files:
        full_path = data_dir / rel_path
        if full_path.exists():
            if not dry_run:
                full_path.unlink()
                logger.info(f"  Removed: {rel_path}")
            else:
                logger.info(f"  [DRY RUN] Would remove: {rel_path}")
            removed += 1

    return removed


def main():
    parser = argparse.ArgumentParser(description="Migrate Helix from 8D to 384D")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing")
    parser.add_argument("--data-dir", default="data", help="Data directory path")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    if not data_dir.exists():
        logger.error(f"Data directory not found: {data_dir}")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("Helix 8D → 384D Migration")
    logger.info(f"Data dir: {data_dir}")
    logger.info(f"Mode: {'DRY RUN' if args.dry_run else 'LIVE'}")
    logger.info("=" * 60)

    # Load embedder
    embedder = get_embedder()

    # 1. Migrate beliefs
    logger.info("\n[1/3] Migrating beliefs...")
    n_beliefs = migrate_beliefs(data_dir, embedder, args.dry_run)

    # 2. Migrate journal
    logger.info("\n[2/3] Migrating journal entries...")
    n_journal = migrate_journal(data_dir, embedder, args.dry_run)

    # 3. Cleanup old state
    logger.info("\n[3/3] Cleaning up old 8D state files...")
    n_removed = cleanup_old_state(data_dir, args.dry_run)

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Migration Summary:")
    logger.info(f"  Beliefs re-embedded:  {n_beliefs}")
    logger.info(f"  Journal re-embedded:  {n_journal}")
    logger.info(f"  State files removed:  {n_removed}")
    logger.info("=" * 60)

    if args.dry_run:
        logger.info("\nDRY RUN complete. Re-run without --dry-run to apply.")
    else:
        logger.info("\nMigration complete. Restart Helix to use 384D manifold.")


if __name__ == "__main__":
    main()
