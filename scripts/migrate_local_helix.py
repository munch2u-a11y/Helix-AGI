#!/usr/bin/env python3
"""
Helix AGI — Migration Script for Local Helix Data

Copies data from a source Helix data directory to the active workspace data/ directory,
normalizes all belief schemas, and deduplicates identical beliefs while preserving
relational integrity.
"""

import os
import sys
import json
import shutil
from pathlib import Path
from datetime import datetime

# Add project root to sys.path
BASE_DIR = Path(__file__).parent.parent.resolve()
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from memory.belief_store import BeliefStore

SOURCE_DATA_DIR = Path.home() / "Helix" / "data"
TARGET_DATA_DIR = BASE_DIR / "data"

def backup_existing_data():
    if not TARGET_DATA_DIR.exists():
        return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = BASE_DIR / f"data_backup_{timestamp}"
    print(f"[*] Backing up existing target data directory to {backup_dir}...")
    shutil.copytree(TARGET_DATA_DIR, backup_dir)
    print(f"    ✓ Backup completed.")

def copy_source_data():
    print(f"[*] Copying data from {SOURCE_DATA_DIR} to {TARGET_DATA_DIR}...")
    if TARGET_DATA_DIR.exists():
        shutil.rmtree(TARGET_DATA_DIR)
    shutil.copytree(SOURCE_DATA_DIR, TARGET_DATA_DIR)
    print(f"    ✓ Data directories copied.")

def migrate_and_deduplicate():
    print("[*] Starting beliefs normalization and deduplication...")
    belief_store = BeliefStore(str(TARGET_DATA_DIR / "beliefs"))
    
    categories = ["premises", "propositions", "preferences", "people", "concepts", "skills", "desires"]
    
    # Map of removed belief ID -> kept belief ID
    merge_map = {}
    
    # Pass 1: Load, normalize, and identify duplicates within each category
    category_beliefs = {}
    
    for cat in categories:
        file_path = TARGET_DATA_DIR / "beliefs" / f"{cat}.json"
        if not file_path.exists():
            print(f"    ! File not found: {file_path} — skipping")
            continue
            
        try:
            with open(file_path, "r") as f:
                raw_list = json.load(f)
        except Exception as e:
            print(f"    ❌ Failed to load {file_path}: {e}")
            continue
            
        print(f"  Processing {cat} ({len(raw_list)} beliefs loaded)...")
        
        normalized_list = []
        for b in raw_list:
            if "content" not in b:
                b["content"] = b.get("summary", b.get("description", ""))
            if not b.get("content") and b.get("term"):
                b["content"] = f"Concept definition for {b['term']}"
            normalized = belief_store._normalize_belief(b, category=cat, preserve_mass=True)
            normalized_list.append(normalized)
            
        # Group by content string (normalized) to find duplicates
        seen_contents = {}
        unique_beliefs = []
        
        for b in normalized_list:
            content_key = b.get("content", "").strip().lower()
            b_id = b["id"]
            
            if content_key in seen_contents:
                # Duplicate found!
                existing = seen_contents[content_key]
                existing_id = existing["id"]
                
                print(f"    - Merging duplicate belief '{b_id}' -> '{existing_id}'")
                
                # Merge metadata
                existing["access_count"] += b.get("access_count", 0)
                
                # Merge lists
                existing["relations"] = list(dict.fromkeys(existing.get("relations", []) + b.get("relations", [])))
                existing["memory_refs"] = list(dict.fromkeys(existing.get("memory_refs", []) + b.get("memory_refs", [])))
                existing["tags"] = list(dict.fromkeys(existing.get("tags", []) + b.get("tags", [])))
                
                # Take max of scalars
                existing["confidence"] = max(existing["confidence"], b["confidence"])
                existing["stability_index"] = max(existing["stability_index"], b["stability_index"])
                existing["verifications"] = max(existing["verifications"], b["verifications"])
                existing["mass"] = max(existing["mass"], b["mass"])
                
                # Track the ID mapping
                merge_map[b_id] = existing_id
            else:
                seen_contents[content_key] = b
                unique_beliefs.append(b)
                
        category_beliefs[cat] = unique_beliefs

    # Pass 2: Clean up relations to replace merged IDs and remove duplicates/self-references
    print("[*] Rebuilding relation references after merges...")
    for cat, beliefs in category_beliefs.items():
        for b in beliefs:
            updated_relations = []
            for r_id in b.get("relations", []):
                # Replace if it was merged, otherwise keep
                target_id = merge_map.get(r_id, r_id)
                # Avoid self-reference and duplicates
                if target_id != b["id"] and target_id not in updated_relations:
                    updated_relations.append(target_id)
            b["relations"] = updated_relations

    # Pass 3: Write files back to disk
    for cat, beliefs in category_beliefs.items():
        file_path = TARGET_DATA_DIR / "beliefs" / f"{cat}.json"
        try:
            with open(file_path, "w") as f:
                json.dump(beliefs, f, indent=2)
            print(f"    ✓ Saved {cat}.json ({len(beliefs)} unique beliefs)")
        except Exception as e:
            print(f"    ❌ Failed to save {cat}.json: {e}")

    # Pass 4: Re-initialize SpatialMind to refresh identity center
    try:
        from core.spatial_mind import SpatialMind
        # Mock physics engine to allow spatial mind to load
        spatial = SpatialMind(base_dir=TARGET_DATA_DIR)
        b_loaded, m_loaded = spatial.load_state()
        print(f"    ✓ SpatialMind loaded successfully ({b_loaded} beliefs, {m_loaded} memories).")
        print(f"    ✓ Identity center (x*) refreshed at: {spatial._identity_center.tolist()[:3]}...")
    except Exception as e:
        print(f"    ⚠️ Warning: SpatialMind reload/identity refresh encountered: {e}")

def main():
    if not SOURCE_DATA_DIR.exists():
        print(f"❌ Source data directory does not exist: {SOURCE_DATA_DIR}")
        sys.exit(1)
        
    backup_existing_data()
    copy_source_data()
    migrate_and_deduplicate()
    print("\n🎉 Migration and deduplication complete successfully!")

if __name__ == "__main__":
    main()
