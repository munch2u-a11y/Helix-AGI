"""Autograd/admission diagnostics, never a substitute for a full-agent result.

The small linear fixture exercises optimizer ownership, persistence and failure
semantics. It does not estimate RWKV behavior, learning quality or performance.
"""
import copy
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

import torch

from core.mindscape import Mindscape
from core.mindscape_config import defaults, resolve, activate_native_source, selected_native_source
from core.native_learning import NativeGradientLearning, NativeLanguageBackend, StreamEvent
from core.pulse_context import build_pulse_context
activate_native_source(selected_native_source())
from habitus_ai.continual_rwkv import ContinualRwkv
from habitus_ai.store import MindStore


def autograd_fixture():
    backend = ContinualRwkv.__new__(ContinualRwkv)
    backend.torch = torch
    backend.model = torch.nn.Linear(4, 4)
    backend._rwkv_parameter_names = {name for name, _ in backend.model.named_parameters()}
    backend.runtime = SimpleNamespace(cortex=SimpleNamespace(model=torch.nn.Linear(4, 4)))
    backend.interface = torch.nn.Linear(4, 4)
    backend.optimizer = torch.optim.AdamW([
        {"params": list(backend.model.parameters())},
        {"params": list(backend.runtime.cortex.model.parameters())},
        {"params": list(backend.interface.parameters())}], lr=0.01)
    backend.cancel_event = threading.Event()
    backend.chunk_tokens = 2
    backend.identity = "linear-autograd-diagnostic"
    backend.state = {"cursor": 0}
    backend.sampling = {}
    backend.counters = dict.fromkeys(("updates", "language_training_tokens", "corpus_training_tokens",
                                     "interaction_training_tokens", "action_updates"), 0)
    backend.encode = lambda text: [byte % 4 for byte in text.encode()]
    backend.consume = lambda ids: 0
    backend.receipt_sink = lambda receipt: None
    backend.dump_state = lambda: json.dumps(backend.state).encode()
    backend.load_state = lambda data: setattr(backend, "state", json.loads(data))
    backend.detach_state = lambda: setattr(backend, "field", backend.field.detach())
    def cognitive():
        hidden = backend.runtime.cortex.model(torch.ones(1, 4))
        backend.field = backend.interface(hidden)
        return {"action_logits": hidden[:, :3], "consequence": hidden[:, 3]}
    backend._cognitive_step = cognitive
    def forward(ids, *, learning=False, inputs_embeds=None):
        inputs = (torch.nn.functional.one_hot(torch.tensor([ids]), 4).float()
                  if inputs_embeds is None else inputs_embeds)
        backend.state["cursor"] += inputs.shape[1]
        return backend.model(inputs + backend.field.unsqueeze(1))
    backend._forward = forward
    backend._cognitive_step()
    return backend


class NativeLearningDiagnostics(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.store = MindStore(self.directory / "state.sqlite", space_id="gradient-diagnostic", dimension=4)
        self.addCleanup(self.store.close)
        self.backend = autograd_fixture()
        self.receipts = []
        self.owner = SimpleNamespace(directory=self.directory, native=SimpleNamespace(
            backend=self.backend, mind=SimpleNamespace(store=self.store),
            _record_learning=lambda receipt: self.receipts.append(receipt)),
            _receipt=lambda kind, **values: self.receipts.append({"kind": kind, **values}))
        self.policy = resolve(defaults())["mindscape"]["gradient_learning"]
        self.learning = NativeGradientLearning(self.owner, self.policy)

    def test_subconscious_gradients_flow_while_rwkv_parameters_stay_frozen(self):
        before = self.backend.weight_report()
        self.learning.external("an actual received string", "ingress:a", kind="received_language")
        after = self.backend.weight_report()
        self.assertEqual(before["rwkv"], after["rwkv"])
        self.assertNotEqual(before["cortex"], after["cortex"])
        self.assertNotEqual(before["interface"], after["interface"])
        updates = [row for row in self.receipts if row["kind"] == "joint_gradient_update"]
        self.assertTrue(updates)
        self.assertTrue(all(row["admission_id"] == "ingress:a" for row in updates))
        self.assertTrue(all(row["gradient_norms"]["rwkv"] == 0 for row in updates))

    def test_same_ingress_is_trained_once_but_repeated_real_messages_are_distinct(self):
        self.learning.external("same words", "ingress:a", kind="received_language")
        count = self.backend.counters["updates"]
        self.assertTrue(self.learning.external("same words", "ingress:a", kind="received_language")["reused"])
        self.assertEqual(self.backend.counters["updates"], count)
        self.learning.external("same words", "ingress:b", kind="received_language")
        self.assertGreater(self.backend.counters["updates"], count)
        with self.assertRaisesRegex(RuntimeError, "different content"):
            self.learning.external("changed words", "ingress:a", kind="received_language")

    def test_partial_update_is_explicit_and_cannot_be_replayed_as_a_fresh_event(self):
        original = self.backend._forward
        calls = []
        def fail_after_one_chunk(*args, **kwargs):
            calls.append(1)
            if len(calls) == 2:
                raise RuntimeError("diagnostic numerical failure")
            return original(*args, **kwargs)
        self.backend._forward = fail_after_one_chunk
        with self.assertRaisesRegex(RuntimeError, "numerical failure"):
            self.learning.external("several chunks", "ingress:partial", kind="received_language")
        self.assertEqual(self.backend.counters["updates"], 1)
        restored_ledger = NativeGradientLearning(self.owner, self.policy)
        with self.assertRaisesRegex(RuntimeError, "unfinished"):
            restored_ledger.external("several chunks", "ingress:partial", kind="received_language")
        self.assertEqual(self.backend.counters["updates"], 1)

    def test_generated_private_text_does_not_become_its_own_training_target(self):
        adapter = Mindscape.__new__(Mindscape)
        adapter.native = self.owner.native
        adapter.native.runtime = SimpleNamespace(embedder=SimpleNamespace(embed=lambda text: [0.1] * 4),
                                                 advance=lambda inputs: None)
        adapter.session_id = "diagnostic"
        adapter._admitted_foreground = None
        adapter._receipt = self.owner._receipt
        before = self.backend.weight_report()
        adapter._admit_foreground("I imagine that I successfully opened a file.", 1, channel="private")
        self.assertEqual(self.backend.counters["updates"], 0)
        self.assertEqual(self.backend.weight_report(), before)

    def test_unverified_result_cannot_supply_outcome_supervision(self):
        self.learning.returned({"action": "run", "status": "completed", "output": "claimed success"}, None)
        self.assertEqual(self.backend.counters["updates"], 0)
        self.assertTrue(any(row["kind"] == "gradient_return_excluded" for row in self.receipts))

    def test_failed_verified_action_trains_consequence_without_rewarding_its_trunk(self):
        self.backend.learn_action("DO", success=False, receipt_id="real-failure")
        update = next(row for row in self.receipts if row["kind"] == "joint_gradient_update")
        self.assertFalse(update["trunk_supervision"])
        self.assertFalse(update["success"])

    def test_optimizer_and_policy_survive_checkpoint_payload_restore(self):
        self.learning.external("received words", "ingress:checkpoint", kind="received_language")
        payload = copy.deepcopy(self.backend.checkpoint_payload())
        path = self.directory / "neural.pt"
        torch.save(payload, path)
        restored = autograd_fixture()
        restored.restore_payload(torch.load(path, weights_only=True))
        self.assertEqual(restored.weight_report(), self.backend.weight_report())
        self.assertFalse(any(value.requires_grad for value in restored.trainable_rwkv().values()))
        self.backend.learn_tokens([0, 1, 2], source="next external event")
        restored.learn_tokens([0, 1, 2], source="next external event")
        self.assertEqual(restored.weight_report(), self.backend.weight_report())

    def test_stream_event_identity_survives_context_copy_and_identical_message_text(self):
        first = StreamEvent("User is talking to me via direct. They said: same", event_id="ingress:1",
                            event_type="user_message", payload="same")
        second = StreamEvent(str(first), event_id="ingress:2", event_type="user_message", payload="same")
        frame = build_pulse_context(pulse=1, timestamp="now", events=[first, second])
        saved = asdict(frame)
        self.assertEqual(saved["contributions"][0]["text"].event_id, "ingress:1")
        self.assertNotEqual(frame.contributions[0].source_ids, frame.contributions[1].source_ids)

    def test_foreground_uses_same_weights_with_independent_state_on_serial_owner(self):
        self.backend.device = "cpu"
        self.backend.tokenizer = object()
        self.backend.config = SimpleNamespace(hidden_size=4)
        self.backend.eos_token_id = 0
        self.backend.decode = lambda ids: "decoded"
        with ThreadPoolExecutor(max_workers=1) as worker:
            self.owner._worker = worker
            def initialize_owner():
                store = MindStore(":memory:", space_id="serial-owner-diagnostic", dimension=4)
                self.owner.native.mind.store = store
                return NativeGradientLearning(self.owner, self.policy)
            learning = worker.submit(initialize_owner).result()
            foreground = NativeLanguageBackend(self.owner)
            original_state = self.backend.state
            branch = {"cursor": 100}
            result = foreground.forward_branch(state=branch, input_ids=torch.tensor([[0, 1]]))
            self.assertIs(foreground.model, self.backend.model)
            self.assertEqual(result.state["cursor"], 102)
            self.assertIs(self.backend.state, original_state)
            try:
                worker.submit(learning.external, "new received words", "ingress:while-speaking",
                              kind="received_language").result()
                foreground.forward_branch(state=result.state, input_ids=torch.tensor([[2]]))
                self.assertEqual(len(foreground.generation_receipt()["versions_used"]), 2)
            finally:
                worker.submit(self.owner.native.mind.store.close).result()

