"""Advisory native habits derived from checkpointed jobs, never action authority.

The sidecar contains references to native evidence, not a second factual store.
Every recall revalidates support against jobs in the currently restored native
lineage. Restoring an older checkpoint cannot retain a future recommendation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path, PurePosixPath

from core.agent_home import write_home_json

ACTIONS = {1: "move", 2: "sense", 3: "open", 4: "run"}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def plan_key(home, position, steps):
    return digest({"home": str(Path(home).resolve()), "position": position, "steps": steps})


def matching_native_return(result, job):
    signal, receipt = result.get("motor_signal", {}), result.get("receipt", {})
    action = result.get("action")
    return bool(
        result.get("intent_source") == "native_motor_signal"
        and signal.get("request_id") == job["id"]
        and signal.get("context_id") == job["context_id"]
        and signal.get("observation_id") and signal.get("target_handle")
        and ACTIONS.get(signal.get("opcode")) == action
        and result.get("selected_affordance") == f"ability:helix-workspace-{action}"
        and result.get("return_pulse") and result.get("proposal_pulse")
        and receipt.get("status") == "success" and receipt.get("verified") is True
        and receipt.get("return_record_id") and receipt.get("outcome_id") and receipt.get("receipt_id"))


def verified_job(job):
    """Check sequence, targets, native authorization/return identity and RUN hash."""
    if (job.get("status") != "completed" or not job.get("context_id")
            or not job.get("steps") or job.get("cursor") != len(job["steps"])):
        raise ValueError("A completed context-admitted native job is required")
    position = job.get("start_position")
    if not isinstance(position, str):
        raise ValueError("Native procedure is missing its starting room")
    expected = []
    for step in job["steps"]:
        action = ACTIONS[step["opcode"]]
        raw = step["target"]
        parts = [] if raw.startswith("/") else list(PurePosixPath(position).parts)
        for part in PurePosixPath(raw).parts:
            if part in {"/", "."}:
                continue
            if part == "..":
                if not parts:
                    raise ValueError("Procedure path leaves its home")
                parts.pop()
            else:
                parts.append(part)
        target = "/".join(parts) or "."
        expected.append((action, target))
        if action == "move":
            position = target
    cursor, opened, receipt_ids = 0, {}, []
    for result in job["receipts"]:
        signal, receipt = result.get("motor_signal", {}), result.get("receipt", {})
        action = result.get("action")
        output = receipt.get("output", {})
        path = output.get("position") if action == "move" else output.get("path")
        if not matching_native_return(result, job) or receipt["receipt_id"] in receipt_ids:
            raise ValueError("Native procedure lacks matching authorization and return evidence")
        receipt_ids.append(receipt["receipt_id"])
        if cursor >= len(expected):
            raise ValueError("Unexpected native action after the requested sequence")
        wanted_action, wanted_path = expected[cursor]
        prerequisite = wanted_action == "run" and action == "open" and path == wanted_path
        if not prerequisite and (action, path) != expected[cursor]:
            raise ValueError("Native procedure returned a different action or target")
        if action == "open":
            if not isinstance(output.get("sha256"), str) or len(output["sha256"]) != 64:
                raise ValueError("An OPEN return needs its observed content hash")
            opened[path] = output["sha256"]
        if action == "run":
            if (output.get("return_code") != 0 or path not in opened
                    or output.get("sha256") != opened[path]
                    or result.get("arguments", {}).get("expected_sha256") != opened[path]):
                raise ValueError("RUN lacks matching observed script content and successful return")
        if not prerequisite:
            cursor += 1
    if cursor != len(expected):
        raise ValueError("The requested sequence is not fully supported")
    return {"receipt_ids": receipt_ids, "observed_content_sha256": opened,
            "receipt_sha256": digest(job["receipts"])}


class NativeProceduralMemory:
    def __init__(self, directory, home):
        self.path = Path(directory) / "native-procedures.json"
        self.home = str(Path(home).resolve())
        data = json.loads(self.path.read_text()) if self.path.exists() else {"schema": 1, "episodes": []}
        if (not isinstance(data, dict) or data.get("schema") != 1
                or not isinstance(data.get("episodes"), list)
                or any(not isinstance(item, dict) for item in data["episodes"])):
            raise ValueError("Invalid native procedure sidecar; retained for inspection")
        self.episodes = data["episodes"]

    def learn(self, job, checkpoint):
        proof = verified_job(job)
        generation = checkpoint.get("generation")
        if isinstance(generation, bool) or not isinstance(generation, int) or generation < 0:
            raise ValueError("Procedure learning needs a successful joint checkpoint generation")
        if not job.get("completion_checkpoint"):
            raise ValueError("Missing completion checkpoint label")
        episode = {
            "job_id": job["id"], "key": plan_key(self.home, job["start_position"], job["steps"]),
            "home": self.home, "start_position": job["start_position"], "steps": deepcopy(job["steps"]),
            "checkpoint_generation": generation, "checkpoint_label": job["completion_checkpoint"],
            "context_id": job["context_id"], **proof,
        }
        if any(item.get("job_id") == job["id"] for item in self.episodes):
            return False
        updated = self.episodes + [episode]
        write_home_json(self.path, {"schema": 1, "episodes": updated})
        self.episodes = updated
        return True

    def relevant(self, steps, position, jobs, generation):
        key = plan_key(self.home, position, steps)
        by_id = {job["id"]: job for job in jobs}
        supported = []
        seen_jobs = set()
        failures = [job["id"] for job in jobs if job.get("status") == "blocked"
                    and job.get("start_position") == position and job.get("steps") == steps]
        for episode in self.episodes:
            if episode.get("key") != key or episode.get("home") != self.home:
                continue
            job = by_id.get(episode.get("job_id"), {})
            try:
                proof = verified_job(job)
                if (proof["receipt_sha256"] != episode["receipt_sha256"]
                        or job["context_id"] != episode["context_id"]
                        or job.get("completion_checkpoint") != episode["checkpoint_label"]
                        or episode["checkpoint_generation"] > generation):
                    continue
            except (ValueError, KeyError, TypeError):
                continue
            if episode["job_id"] not in seen_jobs:
                supported.append(episode)
                seen_jobs.add(episode["job_id"])
        if not supported and not failures:
            return None
        return {
            "steps": deepcopy(steps), "start_position": position,
            "verified_successes": len(supported), "failures": len(failures),
            "reliability": (len(supported) + 1) / (len(supported) + len(failures) + 2),
            "recommended": bool(supported) and len(supported) >= len(failures),
            "support_job_ids": [item["job_id"] for item in supported],
            "receipt_ids": [rid for item in supported for rid in item["receipt_ids"]],
            "failed_job_ids": failures,
            "preconditions": "Same home, starting room and exact requested plan. Reobserve current targets/content; obtain fresh native SELF authorization. Past success grants no permission.",
        }
