"""Native owner/observer contracts with real temp files and explicit fake neural receipts.

These fixtures do not instantiate MightyMem, authorize real native actions or
certify sandbox execution. PC acceptance must still use the native test group.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.native_motor import NativeMotorSystem, MotorOpcode, ACTION
from core.native_procedures import NativeProceduralMemory, verified_job
from core.progress_feedback import ProgressFeedback
from core.associative_transitions import AssociativeTransitionMemory


class FixtureWorkspace:
    def __init__(self, root):
        self.root, self.position = root, "."

    def resolve_path(self, value):
        path = ((self.root / value.lstrip("/")) if value.startswith("/") else
                (self.root / self.position / value)).resolve()
        if not path.is_relative_to(self.root):
            raise ValueError("Outside fixture home")
        return path

    def sense(self, arguments):
        path = self.resolve_path(arguments["path"])
        return {"path": path.relative_to(self.root).as_posix()}

    def _attributes(self, path):
        stat = path.stat()
        return {"size": stat.st_size, "modified_ns": stat.st_mtime_ns}


class NativeRobustnessTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.home = self.root / "home"
        (self.home / "workshop").mkdir(parents=True)
        (self.home / "workshop/a.txt").write_text("actual fixture file")
        (self.home / "workshop/job.py").write_text("print('fixture')")
        self.metadata, self.events, self.calls = {}, [], []
        self.owner = SimpleNamespace(
            config={"mindscape": {"sensory_interval_seconds": 1}}, directory=self.root,
            session_id="fixture", body=SimpleNamespace(workspace=FixtureWorkspace(self.home)),
            native=SimpleNamespace(generation=0, mind=SimpleNamespace(store=SimpleNamespace(
                get_metadata=lambda key, default: self.metadata.get(key, default),
                set_metadata=lambda key, value: self.metadata.update({key: value})))),
            progress_feedback=ProgressFeedback(), _admit_motor_target=lambda *args: None,
            _receipt=lambda kind, **values: self.events.append((kind, values)),
            _execute_motor=self.execute, _checkpoint=self.checkpoint)
        self.motor = NativeMotorSystem(self.owner)
        self.pulse = 0

    def checkpoint(self, label):
        self.owner.native.generation += 1
        self.saved_metadata = deepcopy(self.metadata)
        return {"generation": self.owner.native.generation}

    def execute(self, signal, arguments):
        action = ACTION[MotorOpcode(signal.opcode)]
        self.calls.append(action)
        path = self.owner.body.workspace.resolve_path(arguments["path"])
        relative = path.relative_to(self.home).as_posix()
        output = {"path": relative}
        if action == "move":
            self.owner.body.workspace.position = relative
            output = {"position": relative}
        if action in {"open", "run"}:
            output["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
        if action == "open":
            output["content"] = path.read_text()
        if action == "run":
            output["return_code"] = 0
        from dataclasses import asdict
        number = str(len(self.calls))
        return {"action": action, "intent_source": "native_motor_signal",
                "motor_signal": asdict(signal), "arguments": arguments,
                "selected_affordance": f"ability:helix-workspace-{action}",
                "proposal_pulse": "proposal:" + number, "return_pulse": "return:" + number,
                "receipt": {"status": "success", "verified": True, "receipt_id": "receipt:" + number,
                    "return_record_id": "record:" + number, "outcome_id": "outcome:" + number, "output": output}}

    def admit(self, text="Open /workshop/a.txt"):
        self.pulse += 1
        message = f'[10:00:00] User is talking to me via dashboard. They said: "{text}"'
        ids = self.motor.admit([message], self.pulse)
        self.motor.link_context(ids, "context:" + str(self.pulse))
        return self.motor.jobs[-1], message

    def test_complete_checkpointed_job_teaches_advice_without_dispatching_it(self):
        job, message = self.admit()
        self.motor.tick()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(len(self.motor.procedures.episodes), 1)
        notes = self.motor.procedure_context([message])
        self.assertEqual(len(notes), 1)
        self.assertIn("Past native procedure evidence", notes[0].text)
        self.assertEqual(notes[0].section, "procedures")
        self.assertEqual(self.calls, ["open"])
        self.assertEqual(self.owner.progress_feedback.snapshot()["advanced"], 1)

    def test_run_requires_its_real_open_hash_and_settled_return(self):
        job, _ = self.admit("Run /workshop/job.py")
        self.motor.tick()
        self.assertEqual(job["cursor"], 0)
        self.assertFalse(self.motor.procedures.episodes)
        self.motor.tick()
        self.assertEqual(self.calls, ["open", "run"])
        self.assertEqual(len(self.motor.procedures.episodes), 1)
        self.assertEqual(len(verified_job(job)["receipt_ids"]), 2)

    def test_wrong_target_and_unverified_returns_do_not_teach_or_reward(self):
        for wrong in ("target", "verification"):
            job, _ = self.admit()
            def execute(signal, arguments):
                result = self.execute(signal, arguments)
                if wrong == "target":
                    result["receipt"]["output"]["path"] = "workshop/other.txt"
                else:
                    result["receipt"]["verified"] = False
                return result
            self.owner._execute_motor = execute
            self.motor.tick()
            self.assertEqual(job["status"], "blocked")
        self.assertEqual(self.motor.procedures.episodes, [])
        self.assertEqual(self.owner.progress_feedback.snapshot()["advanced"], 0)

    def test_failed_checkpoint_never_teaches_a_procedure(self):
        self.owner._checkpoint = Mock(side_effect=OSError("checkpoint unavailable"))
        job, _ = self.admit()
        self.motor.tick()
        self.assertEqual(job["status"], "blocked")
        self.assertFalse((self.root / "native-procedures.json").exists())
        self.assertEqual(self.owner.progress_feedback.snapshot()["advanced"], 0)

    def test_derived_write_failure_does_not_change_real_completion(self):
        job, _ = self.admit()
        with patch.object(self.motor.procedures, "learn", side_effect=OSError("sidecar unavailable")):
            self.motor.tick()
        self.assertEqual(job["status"], "completed")
        self.assertIn("native_feedback_unavailable", [kind for kind, values in self.events])

    def test_replay_restart_and_older_lineage(self):
        job, message = self.admit()
        self.motor.tick()
        self.assertFalse(self.motor.procedures.learn(job, {"generation": 1}))
        reloaded = NativeProceduralMemory(self.root, self.home)
        self.assertIsNotNone(reloaded.relevant(job["steps"], ".", self.motor.jobs, 1))
        self.assertIsNone(reloaded.relevant(job["steps"], ".", self.motor.jobs, 0))
        self.assertIsNone(reloaded.relevant(job["steps"], ".", [], 1))
        restored = NativeMotorSystem(self.owner)
        self.assertEqual(len(restored.procedure_context([message])), 1)
        altered = deepcopy(job)
        altered["receipts"][0]["receipt"]["output"]["content"] = "changed evidence"
        self.assertIsNone(reloaded.relevant(job["steps"], ".", [altered], 1))

    def test_old_success_counters_and_unrelated_context_do_not_recommend(self):
        job, _ = self.admit()
        self.motor.tick()
        self.assertIsNone(self.motor.procedures.relevant(job["steps"], "workshop", self.motor.jobs, 1))
        self.assertIsNone(self.motor.procedures.relevant([{"opcode": 3, "target": "/different"}], ".", self.motor.jobs, 1))
        old = {**job, "id": "legacy", "receipts": [], "successes": 1000}
        self.assertIsNone(self.motor.procedures.relevant(job["steps"], ".", [old], 1))

    def test_failures_outweigh_a_previously_successful_route(self):
        job, _ = self.admit()
        self.motor.tick()
        self.owner._execute_motor = Mock(side_effect=RuntimeError("not available now"))
        for _ in range(2):
            self.admit()
            self.motor.tick()
        advice = self.motor.procedures.relevant(job["steps"], ".", self.motor.jobs, 1)
        self.assertEqual(advice["verified_successes"], 1)
        self.assertEqual(advice["failures"], 2)
        self.assertFalse(advice["recommended"])

    def test_master_switch_keeps_baseline_motor_and_does_not_create_sidecar(self):
        self.owner.config["mindscape"]["robustness"] = {"enabled": False}
        self.motor = NativeMotorSystem(self.owner)
        job, message = self.admit()
        self.motor.tick()
        self.assertEqual(job["status"], "completed")
        self.assertFalse((self.root / "native-procedures.json").exists())
        self.assertEqual(self.motor.procedure_context([message]), [])
        self.assertEqual(self.owner.progress_feedback.snapshot()["attempts"], 0)

    def test_corrupt_derived_state_is_retained_and_body_remains_usable(self):
        path = self.root / "native-procedures.json"
        path.write_text("[]")
        self.motor = NativeMotorSystem(self.owner)
        self.assertIsNone(self.motor.procedures)
        job, _ = self.admit()
        self.motor.tick()
        self.assertEqual(job["status"], "completed")
        self.assertEqual(path.read_text(), "[]")

    def test_native_authorization_and_return_ids_are_mandatory_for_learning(self):
        job, _ = self.admit()
        self.motor.tick()
        for field in ("selected_affordance", "return_pulse"):
            invalid = deepcopy(job)
            invalid["receipts"][0].pop(field)
            with self.assertRaises(ValueError):
                verified_job(invalid)


    def test_read_only_pc_inspection_checks_published_database_and_support(self):
        import sqlite3
        from scripts.inspect_native_robustness import inspect
        job, _ = self.admit()
        self.motor.tick()
        data = self.root / "selected"
        joint = data / "mindscape/joint"
        checkpoint = joint / "checkpoint-000001"
        checkpoint.mkdir(parents=True)
        database = checkpoint / "mind.sqlite"
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT)")
            connection.execute("INSERT INTO metadata VALUES (?, ?)", ("helix_motor_jobs", json.dumps(self.motor.jobs)))
        manifest = {"generation": 1, "files": {"mind.sqlite": hashlib.sha256(database.read_bytes()).hexdigest()}}
        manifest_path = checkpoint / "manifest.json"
        manifest_path.write_text(json.dumps(manifest))
        (joint / "LATEST.json").write_text(json.dumps({"checkpoint": checkpoint.name,
            "manifest_sha256": hashlib.sha256(manifest_path.read_bytes()).hexdigest()}))
        (data / "mindscape/native-procedures.json").write_bytes((self.root / "native-procedures.json").read_bytes())
        before = {str(path): path.read_bytes() for path in data.rglob("*") if path.is_file()}
        config = {"data_dir": str(data), "mindscape": {"home": str(self.home)}}
        result = inspect(config)
        self.assertEqual(result["status"], "inspected")
        self.assertEqual(len(result["supported_procedures"]), 1)
        self.assertTrue(result["supported_procedures"][0]["recommended"])
        self.assertEqual(before, {str(path): path.read_bytes() for path in data.rglob("*") if path.is_file()})
        with database.open("ab") as stream:
            stream.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            inspect(config)

    def test_unsettled_native_returns_do_not_earn_progress_credit(self):
        job, _ = self.admit()
        def execute(signal, arguments):
            result = self.execute(signal, arguments)
            result.pop("selected_affordance")
            return result
        self.owner._execute_motor = execute
        self.motor.tick()
        self.assertFalse(self.motor.procedures.episodes)
        self.assertEqual(self.owner.progress_feedback.snapshot()["advanced"], 0)


class RetainedAssociationTests(unittest.TestCase):
    def test_recall_does_not_reinforce_itself_or_rewrite_canonical_positions(self):
        import numpy as np
        with tempfile.TemporaryDirectory() as directory:
            memory = AssociativeTransitionMemory(directory)
            a, b = np.eye(8)[0], np.eye(8)[1]
            for _ in range(2):
                memory.break_sequence()
                memory.observe("a", a)
                memory.observe("b", b)
            edges = dict(memory.edges)
            for _ in range(20):
                self.assertEqual(memory.recall("a")[0]["cluster_id"], "b")
            self.assertEqual(memory.edges, edges)
            np.testing.assert_array_equal(a, np.eye(8)[0])
            np.testing.assert_array_equal(b, np.eye(8)[1])
