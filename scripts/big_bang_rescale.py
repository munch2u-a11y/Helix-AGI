"""Big Bang — Rescale all existing belief positions by SCALE_FACTOR.

One-time migration script. Run while Helix is stopped.

For each belief across all categories:
  1. If it has a position_8d: multiply by SCALE_FACTOR (5.0)
  2. If it has no position_8d: embed and project with scaling
  3. Store the result as both position_8d and base_position_8d
  4. Set creation_epoch = 0 (all existing beliefs are "epoch 0")

Usage:
    cd /home/nemo/Helix
    .venv/bin/python scripts/big_bang_rescale.py [--dry-run]
"""

import json
import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.belief_cosmology import SCALE_FACTOR

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("big_bang")

BELIEFS_DIR = Path("data/beliefs")
CATEGORIES = [
    "premises", "propositions", "preferences",
    "people", "skills", "desires", "concepts",
]


def rescale_positions(dry_run: bool = False):
    """Rescale all existing positions by SCALE_FACTOR."""
    
    # Lazy-load physics engine only if we need to embed
    physics = None
    
    total_scaled = 0
    total_embedded = 0
    total_skipped = 0
    
    for cat in CATEGORIES:
        fpath = BELIEFS_DIR / f"{cat}.json"
        if not fpath.exists():
            logger.info(f"  {cat}: file not found, skipping")
            continue
        
        beliefs = json.loads(fpath.read_text())
        modified = False
        
        for b in beliefs:
            pos = b.get("position_8d")
            
            if pos and len(pos) == 8:
                # Scale existing position
                b["position_8d"] = [round(x * SCALE_FACTOR, 6) for x in pos]
                b["base_position_8d"] = b["position_8d"].copy()
                b["creation_epoch"] = 0
                total_scaled += 1
                modified = True
            else:
                # Need to embed from scratch
                content = b.get("content", "")
                if not content or len(content) < 5:
                    total_skipped += 1
                    continue
                    
                if physics is None:
                    logger.info("  Loading physics engine for embedding...")
                    from core.physics_engine import PhysicsEngine
                    physics = PhysicsEngine()
                
                try:
                    from core.belief_cosmology import compute_position
                    emb = physics.embed_text(content)
                    pos_new = compute_position(
                        emb, physics.spatial_mind.belief_space.projection
                    )
                    b["position_8d"] = [round(float(x), 6) for x in pos_new]
                    b["base_position_8d"] = b["position_8d"].copy()
                    b["creation_epoch"] = 0
                    total_embedded += 1
                    modified = True
                except Exception as e:
                    logger.warning(f"  Failed to embed {b.get('id', '?')}: {e}")
                    total_skipped += 1
        
        if modified and not dry_run:
            fpath.write_text(json.dumps(beliefs, indent=2))
            logger.info(f"  {cat}: {len(beliefs)} beliefs written")
        else:
            logger.info(f"  {cat}: {len(beliefs)} beliefs {'(dry run)' if dry_run else ''}")
    
    logger.info(f"\nBig Bang complete:")
    logger.info(f"  Scaled:   {total_scaled}")
    logger.info(f"  Embedded: {total_embedded}")
    logger.info(f"  Skipped:  {total_skipped}")
    logger.info(f"  Scale factor: {SCALE_FACTOR}x")


if __name__ == "__main__":
    dry_run = "--dry-run" in sys.argv
    if dry_run:
        logger.info("=== DRY RUN — no files will be modified ===\n")
    
    logger.info(f"Big Bang: rescaling all belief positions by {SCALE_FACTOR}x\n")
    rescale_positions(dry_run=dry_run)
