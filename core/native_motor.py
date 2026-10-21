"""Non-language body control, independent of foreground token generation.

The bootstrap receptor accepts explicit user movement/reading/execution requests.
It is a transparent goal policy, not a claim of learned motor competence. Signals
are integer opcodes bound to observed filesystem targets; model prose is never an
input. Existing native SELF authorization and sensory returns remain mandatory.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import IntEnum
import hashlib
import json
from pathlib import Path
import re
import threading
import time
import uuid
import shlex
import queue


class MotorOpcode(IntEnum):
    MOVE = 1
    SENSE = 2
    OPEN = 3
    RUN = 4


ACTION = {MotorOpcode.MOVE: "move", MotorOpcode.SENSE: "sense",
          MotorOpcode.OPEN: "open", MotorOpcode.RUN: "run"}


@dataclass(frozen=True)
class MotorSignal:
    opcode: int
    target_handle: str
    request_id: str
    context_id: str
    observation_id: str


VERB = r"(?:go\s+to|move(?:\s+to)?|navigate(?:\s+to)?|enter|cd|open|read|run|execute|inspect|list|sense)"
LEADER = re.compile(r"^(?:please\s+|(?:can|could|would)\s+you\s+|then\s+|and\s+)*", re.I)
COMMAND = re.compile(rf"^({VERB})\s+(.+)$", re.I | re.S)


def receptive_steps(message):
    """A deliberately explicit bootstrap grammar on actual received user input.

    None means ordinary conversation. Negated/ambiguous commands are rejected,
    never completed by guessing filenames, program contents or a default script.
    Preserve path spelling and the order of every requested target.
    """
    text = str(message).split("They said:", 1)[-1].strip()
    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1]
    text = re.sub(r"^(?:hello|hi|hey)\b[^.!?]*[.!?]\s*", "", text, count=1, flags=re.I)
    text = re.sub(r"^I am [\w -]+\.\s*", "", text, count=1, flags=re.I)
    text = LEADER.sub("", text).strip()
    if not COMMAND.match(text):
        return None
    if re.search(r"\b(?:not|never|cannot|can't|don't|won't|unable)\b", text, re.I):
        raise ValueError("Negated movement/execution request: no motor actions admitted")
    text = re.split(r"\s+and\s+(?:tell|report|show)\b", text, maxsplit=1, flags=re.I)[0]
    chunks = re.split(rf"\s*(?:;|\b(?:and\s+then|and|then)\b)\s*(?=(?:please\s+)?{VERB}\b)", text, flags=re.I)
    steps, last_file = [], None
    for chunk in chunks:
        m = COMMAND.fullmatch(LEADER.sub("", chunk).strip())
        if not m:
            raise ValueError("Unrecognized motor request; give explicit actions and target paths")
        verb, supplied = m.groups()
        action = ("move" if re.match(r"go|move|navigate|enter|cd", verb, re.I) else
                  "open" if verb.lower() in {"open", "read"} else
                  "run" if verb.lower() in {"run", "execute"} else "sense")
        supplied = supplied.strip().rstrip("?!").strip()
        if supplied not in {".", ".."} and supplied.endswith("."):
            supplied = supplied[:-1]
        bound_reference = supplied.lower() in {"it", "that file", "that script"}
        if bound_reference:
            if last_file is None:
                raise ValueError("No explicitly named file for 'it'")
            supplied = last_file
        tokens = [supplied] if bound_reference else shlex.split(supplied)
        if not tokens or any(tokens[i].lower() != "and" for i in range(1, len(tokens), 2)) or len(tokens) % 2 == 0:
            raise ValueError("Use explicit paths; quote filenames containing spaces")
        targets = tokens[::2]
        if len(targets) > 1 and action != "open":
            raise ValueError("Give each movement or execution action its own explicit target")
        for target in targets:
            target = target.strip()
            quoted = len(target) >= 2 and target[0] == target[-1] and target[0] in "\"'"
            if quoted:
                target = target[1:-1]
            if not target:
                raise ValueError("A motor action needs an explicit target")
            steps.append({"opcode": int({"move": MotorOpcode.MOVE, "sense": MotorOpcode.SENSE,
                                         "open": MotorOpcode.OPEN, "run": MotorOpcode.RUN}[action]),
                          "target": target})
            if action == "open":
                last_file = target
    return steps


class NativeMotorSystem:
    def __init__(self, owner):
        self.owner = owner
        self.store = owner.native.mind.store
        self.jobs = json.loads(self.store.get_metadata("helix_motor_jobs", "[]"))
        self.stop_event = threading.Event()
        self.thread = None
        self.sensor_thread = None
        self.frames = queue.Queue()
        self.wake = lambda: None
        self.sequence = 0
        self.last_scene_hash = None
        self.policy = "autonomous-and-receptive-v1; integer motor signals; native SELF authorization"
        from core.robustness import options
        self.robustness = options(owner.config)
        self.procedures = None
        if self.robustness["procedure_learning"] or self.robustness["procedure_recall"]:
            try:
                from core.native_procedures import NativeProceduralMemory
                self.procedures = NativeProceduralMemory(owner.directory, owner.body.workspace.root)
            except (OSError, ValueError) as exc:
                owner._receipt("native_procedure_unavailable", error=str(exc),
                               policy="derived sidecar retained; native body remains available")
        unfinished = [j for j in self.jobs if j["status"] == "awaiting_context"]
        for job in unfinished:
            job["status"] = "blocked"
            job["error"] = "Previous context admission was interrupted; resend this preserved request to continue"
        if unfinished:
            self._save()

    def _save(self, *, publish=True):
        from core.agent_home import write_home_json
        self.store.set_metadata("helix_motor_jobs", json.dumps(self.jobs))
        if not publish:
            return
        write_home_json(self.owner.directory / "motor-state.json", {
            "policy": self.policy, "sensory_cadence_seconds": self.interval,
            "last_sensor_sequence": self.sequence, "updated_at": time.time(), "jobs": self.jobs})

    @property
    def interval(self):
        return float(self.owner.config["mindscape"]["sensory_interval_seconds"])

    @property
    def pending(self):
        return any(j["status"] in {"awaiting_context", "ready", "acting"} for j in self.jobs)

    def admit(self, messages, pulse):
        ids = []
        op_map = {"move": MotorOpcode.MOVE, "sense": MotorOpcode.SENSE,
                  "open": MotorOpcode.OPEN, "run": MotorOpcode.RUN, "read": MotorOpcode.OPEN}
        for index, message in enumerate(messages):
            # 1. Internal cognitive intention represented as a dictionary
            if isinstance(message, dict) and "action" in message:
                act = message.get("action")
                if act not in op_map:
                    continue
                args = message.get("arguments") or {}
                target = args.get("path") or args.get("target") or "."
                steps = [{"opcode": int(op_map[act]), "target": str(target)}]
                key = f"subconscious:{self.owner.session_id}:{pulse}:{index}"
                if any(j["input_id"] == key for j in self.jobs):
                    continue
                job = {
                    "id": "motor:" + uuid.uuid4().hex,
                    "input_id": key,
                    "message": json.dumps(message),
                    "steps": steps,
                    "cursor": 0,
                    "receipts": [],
                    "status": "ready",
                    "error": None,
                    "context_id": f"subconscious:{self.sequence}:{time.time()}",
                    "created_at": time.time(),
                }
                self.jobs.append(job)
                ids.append(job["id"])
                self.owner._receipt("motor_request_admitted", **job, policy=self.policy)
                continue

            # 2. String messages: user messages or internal cognitive/receptive command strings
            if not isinstance(message, str):
                continue

            # Skip action observation returns / receipts / notices
            if re.match(r"^(?:\[[^\]]+\]\s*)?(?:Native action|The proposed native action|Action returned)\b", message):
                continue

            is_user_msg = bool(re.match(r"^(?:\[[^\]]+\]\s*)?[\w .'-]+ is talking to me via \w+\. They said:", message))

            if is_user_msg:
                key = f"{self.owner.session_id}:{pulse}:{index}"
                if any(j["input_id"] == key for j in self.jobs):
                    continue
                try:
                    steps = receptive_steps(message)
                    if steps is None:
                        continue
                    error = None
                except ValueError as exc:
                    steps, error = [], str(exc)
                job = {"id": "motor:" + uuid.uuid4().hex, "input_id": key,
                       "message": message, "steps": steps, "cursor": 0, "receipts": [],
                       "status": "blocked" if error else "awaiting_context", "error": error,
                       "context_id": None, "created_at": time.time()}
                self.jobs.append(job)
                ids.append(job["id"])
                self.owner._receipt("motor_request_admitted", **job, policy=self.policy)
            else:
                key = f"internal:{self.owner.session_id}:{pulse}:{index}"
                if any(j["input_id"] == key for j in self.jobs):
                    continue
                steps = None
                try:
                    steps = receptive_steps(message)
                except ValueError:
                    steps = None

                if steps is None:
                    from core.mindscape_intention import parse_natural_or_wire_intention
                    parsed = parse_natural_or_wire_intention(message)
                    if parsed and isinstance(parsed, dict) and parsed.get("action") in op_map:
                        act = parsed["action"]
                        args = parsed.get("arguments") or {}
                        target = args.get("path") or args.get("target") or "."
                        steps = [{"opcode": int(op_map[act]), "target": str(target)}]

                if steps is not None:
                    job = {
                        "id": "motor:" + uuid.uuid4().hex,
                        "input_id": key,
                        "message": message,
                        "steps": steps,
                        "cursor": 0,
                        "receipts": [],
                        "status": "ready",
                        "error": None,
                        "context_id": f"internal:{self.sequence}:{time.time()}",
                        "created_at": time.time(),
                    }
                    self.jobs.append(job)
                    ids.append(job["id"])
                    self.owner._receipt("motor_request_admitted", **job, policy=self.policy)

        if ids:
            self._save()
        return ids

    def submit_action(self, action: str, target: str, context_id: str | None = None) -> str:
        """Submit an autonomous or self-directed motor action directly."""
        op_map = {"move": MotorOpcode.MOVE, "sense": MotorOpcode.SENSE,
                  "open": MotorOpcode.OPEN, "run": MotorOpcode.RUN}
        if action not in op_map:
            raise ValueError(f"Unsupported action: {action}. Choose from {list(op_map.keys())}")
        step = {"opcode": int(op_map[action]), "target": target}
        job_id = "motor:" + uuid.uuid4().hex
        ctx_id = context_id or f"autonomous:{self.sequence}:{time.time()}"
        job = {
            "id": job_id,
            "input_id": f"self-directed:{time.time()}",
            "message": f"Autonomous {action} on {target}",
            "steps": [step],
            "cursor": 0,
            "receipts": [],
            "status": "ready",
            "error": None,
            "context_id": ctx_id,
            "created_at": time.time(),
        }
        self.jobs.append(job)
        self._save()
        self.owner._receipt("motor_action_submitted", **job, policy=self.policy)
        return job_id

    def link_context(self, ids, context_id):
        for job in self.jobs:
            if job["id"] in ids:
                job["context_id"] = context_id
                if job["status"] == "awaiting_context":
                    job["status"] = "ready"
        if ids:
            self._save()

    def start(self, wake):
        if self.thread is not None:
            return
        self.wake = wake
        self.thread = threading.Thread(target=self._run, name="helix-sensory-motor", daemon=True)
        self.sensor_thread = threading.Thread(target=self._sense_loop, name="helix-filesystem-sensor", daemon=True)
        self.sensor_thread.start()
        self.thread.start()

    def sample(self):
        """The sensor remains live even while the native executor runs a script."""
        from core.agent_home import write_home_json
        workspace = self.owner.body.workspace
        self.sequence += 1
        position = workspace.position
        scene = workspace.sense({"path": "/" + position})
        scene["position"] = position
        stable = {**scene, "entries": [x for x in scene.get("entries", []) if x["name"] != "intakes"]}
        stable.pop("modified_ns", None)
        digest = hashlib.sha256(json.dumps(stable, sort_keys=True).encode()).hexdigest()
        changed = digest != self.last_scene_hash
        if changed:
            frame = {"observation_id": "body-sense:" + uuid.uuid4().hex, "time_ns": time.time_ns(),
                     "surroundings": scene, "content_opened": False, "scene_sha256": digest}
            write_home_json(workspace.root / "intakes" / (frame["observation_id"].replace(":", "-") + ".json"), frame)
            self.frames.put(frame)
            self.last_scene_hash = digest
        self.owner._receipt("sensory_tick", sequence=self.sequence, time_ns=time.time_ns(),
                            scene_sha256=digest, changed=changed, position=scene["position"],
                            cadence_seconds=self.interval)

    def _sense_loop(self):
        while not self.stop_event.is_set():
            try:
                self.sample()
            except Exception as exc:
                self.owner._receipt("sensory_system_failed", error=f"{type(exc).__name__}: {exc}")
                self.owner.motor_failure = str(exc)
                self.stop_event.set()
                self.wake()
                return
            self.stop_event.wait(self.interval)

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.owner._worker.submit(self.tick).result()
            except Exception as exc:
                if self.stop_event.is_set():
                    self.owner._receipt("motor_system_stopped", reason="explicit lifecycle stop")
                    return
                self.owner._receipt("motor_system_failed", error=f"{type(exc).__name__}: {exc}")
                self.owner.motor_failure = str(exc)
                self.wake()
                return
            self.stop_event.wait(self.interval)

    def stop(self):
        self.stop_event.set()
        self.owner.body.workspace.cancel_execution()
        if self.thread is not None and self.thread is not threading.current_thread():
            self.thread.join()
        if self.sensor_thread is not None and self.sensor_thread is not threading.current_thread():
            self.sensor_thread.join()

    def tick(self):
        workspace = self.owner.body.workspace
        while not self.frames.empty():
            frame = self.frames.get_nowait()
            self.owner._admit_motor_scene(frame)
        if self.stop_event.is_set():
            return
        job = next((j for j in self.jobs if j["status"] in {"ready", "acting"}), None)
        if job is None:
            decide = getattr(self.owner, "_autonomous_motor_step", None)
            if decide is not None:
                decide()
            job = next((j for j in self.jobs if j["status"] in {"ready", "acting"}), None)
            if job is None:
                return
        job["status"] = "acting"
        job.setdefault("start_position", workspace.position)
        step = job["steps"][job["cursor"]]
        result, checkpoint, step_verified = None, None, False
        try:
            target = workspace.resolve_path(step["target"])
            relative = target.relative_to(workspace.root).as_posix()
            observed = workspace.sense({"path": "/" + target.parent.relative_to(workspace.root).as_posix()}) if target != workspace.root else workspace.sense({"path": "."})
            target_state = workspace._attributes(target)
            target_handle = hashlib.sha256(json.dumps({"path": relative, "attributes": target_state}, sort_keys=True).encode()).hexdigest()
            observation_id = "motor-target:" + uuid.uuid4().hex
            self.owner._admit_motor_target(observation_id, observed, target_handle, relative)
            opcode = MotorOpcode(step["opcode"])
            # RUN always obtains a real fresh content/hash observation first.
            previous = next((x for x in reversed(job["receipts"]) if x.get("action") == "open" and
                             x.get("receipt", {}).get("output", {}).get("path") == relative), None)
            prerequisite = opcode == MotorOpcode.RUN and previous is None
            signal = MotorSignal(int(MotorOpcode.OPEN if prerequisite else opcode), target_handle,
                                 job["id"], job["context_id"], observation_id)
            arguments = {"path": "/" + relative}
            if opcode == MotorOpcode.RUN and not prerequisite:
                arguments["expected_sha256"] = previous["receipt"]["output"]["sha256"]
            result = self.owner._execute_motor(signal, arguments)
            job["receipts"].append(result)
            receipt = result.get("receipt", {})
            if receipt.get("status") != "success" or not receipt.get("verified"):
                raise RuntimeError("Native action did not succeed: " + json.dumps(result))
            output = receipt.get("output", {})
            returned_path = output.get("position") if signal.opcode == MotorOpcode.MOVE else output.get("path")
            if returned_path != relative:
                raise RuntimeError("Native return target differs from requested target")
            if signal.opcode == MotorOpcode.RUN and output.get("return_code") != 0:
                raise RuntimeError("Script did not exit successfully")
            step_verified = True
            if not prerequisite:
                job["cursor"] += 1
            if job["cursor"] == len(job["steps"]):
                job["status"] = "completed"
                job["completed_at"] = time.time()
                # Keep the public state acting until the matching neural and
                # graph state is durably committed. A receipt alone is not a
                # restartable mind checkpoint.
                job["completion_checkpoint"] = "motor-request-" + job["id"].replace(":", "-")
                self._save(publish=False)
                checkpoint = self.owner._checkpoint(job["completion_checkpoint"])
                self.owner._receipt("motor_request_completed", request_id=job["id"], context_id=job["context_id"],
                                    receipt_ids=[x["receipt"]["receipt_id"] for x in job["receipts"]])
        except Exception as exc:
            job["status"], job["error"] = "blocked", f"{type(exc).__name__}: {exc}"
            self.owner._receipt("motor_request_blocked", request_id=job["id"], error=job["error"])
        self._save()
        self._observe_outcome(job, result, checkpoint, step_verified)
        self.wake()

    def _observe_outcome(self, job, result, checkpoint, step_verified):
        """Derived feedback cannot change an action's completion or authorize work."""
        try:
            feedback = getattr(self.owner, "progress_feedback", None)
            if self.robustness["progress_feedback"] and feedback is not None:
                from core.native_procedures import matching_native_return
                receipt = (result or {}).get("receipt", {})
                settled = matching_native_return(result, job) if result else False
                blocked = job["status"] == "blocked"
                feedback.record(receipt.get("receipt_id") or "blocked:" + job["id"],
                                advanced=step_verified and settled and not blocked, failed=blocked,
                                target=(job["id"], (result or {}).get("action"),
                                        receipt.get("output", {}).get("path")),
                                content=hashlib.sha256(json.dumps(receipt.get("output"), sort_keys=True).encode()).hexdigest())
            if (self.robustness["procedure_learning"] and self.procedures is not None
                    and job["status"] == "completed" and isinstance(checkpoint, dict)):
                learned = self.procedures.learn(job, checkpoint)
                self.owner._receipt("native_procedure_observed", request_id=job["id"],
                                    learned=learned, checkpoint_generation=checkpoint["generation"],
                                    policy="advisory; fresh observations and native SELF required")
        except Exception as exc:
            try:
                self.owner._receipt("native_feedback_unavailable", request_id=job["id"], error=str(exc))
            except OSError:
                import logging
                logging.getLogger(__name__).exception("Native feedback unavailable; motor result retained")

    def procedure_context(self, messages):
        if not self.robustness["procedure_recall"] or self.procedures is None:
            return []
        from core.pulse_context import ContextContribution
        notes = []
        for message in messages:
            try:
                steps = receptive_steps(message)
                if not steps:
                    continue
                recalled = self.procedures.relevant(steps, self.owner.body.workspace.position,
                                                   self.jobs, self.owner.native.generation)
                if recalled:
                    text = "Past native procedure evidence (advisory, not a new request or permission):\n" + json.dumps(recalled, sort_keys=True)
                    notes.append(ContextContribution("procedures", text, "native_procedure_memory",
                        tuple(recalled["receipt_ids"] + recalled["failed_job_ids"]),
                        "procedure", "checkpoint-supported past outcomes; current preconditions unverified", "agent"))
            except (ValueError, TypeError, KeyError) as exc:
                self.owner._receipt("native_procedure_recall_unavailable", error=str(exc))
        return notes
