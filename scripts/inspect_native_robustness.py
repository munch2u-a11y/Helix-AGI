#!/usr/bin/env python3
"""Read-only inspection of procedure support in the published joint checkpoint."""
from contextlib import closing
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.native_procedures import NativeProceduralMemory
from core.runtime_paths import RuntimePaths
from core.robustness import options


def file_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect(config, root=ROOT):
    paths = RuntimePaths.from_config(config, root=root)
    checkpoint = paths.latest_checkpoint()
    result = {"options": options(config), "data_dir": str(paths.data), "home": str(paths.home),
              "checkpoint": str(checkpoint) if checkpoint else None, "supported_procedures": []}
    if checkpoint is None:
        result["status"] = "no_checkpoint"
        return result
    joint = paths.data / "mindscape/joint"
    pointer = json.loads((joint / "LATEST.json").read_text())
    manifest_bytes = (checkpoint / "manifest.json").read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != pointer["manifest_sha256"]:
        raise ValueError("Joint checkpoint manifest does not match LATEST.json")
    manifest = json.loads(manifest_bytes)
    database = checkpoint / "mind.sqlite"
    if file_sha256(database) != manifest["files"]["mind.sqlite"]:
        raise ValueError("Joint checkpoint database checksum differs from its manifest")
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        row = connection.execute("SELECT value FROM metadata WHERE key='helix_motor_jobs'").fetchone()
    jobs = json.loads(row[0]) if row else []
    memory = NativeProceduralMemory(paths.data / "mindscape", paths.home)
    seen = set()
    for job in jobs:
        if job.get("start_position") is None:
            continue
        advice = memory.relevant(job["steps"], job["start_position"], jobs, manifest["generation"])
        key = json.dumps([job["steps"], job["start_position"]], sort_keys=True)
        if advice and key not in seen:
            result["supported_procedures"].append(advice)
            seen.add(key)
    result.update(status="inspected", checkpoint_generation=manifest["generation"],
                  checkpoint_jobs=len(jobs), recorded_episodes=len(memory.episodes),
                  verification_scope="manifest and SQLite checksum; no neural-file checksum or inference")
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config/config.json")
    args = parser.parse_args(argv)
    try:
        result = inspect(json.loads(args.config.read_text()))
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 1
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "inspected" else 2


if __name__ == "__main__":
    raise SystemExit(main())
