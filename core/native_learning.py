"""Agent-owned gradient admission and foreground access to the learned model.

All mutable neural work runs on Mindscape's existing serial owner. External
observations train prediction; actual settled receipts train consequences.
Private text and recalled context advance state without becoming targets.
"""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace


class StreamEvent(str):
    """A normal event string with ingress identity outside its untrusted text."""
    def __new__(cls, text, *, event_id, event_type, payload):
        value = super().__new__(cls, text)
        value.event_id = event_id
        value.event_type = event_type
        value.payload = payload
        return value

    def __getnewargs_ex__(self):
        return ((str(self),), {"event_id": self.event_id, "event_type": self.event_type, "payload": self.payload})


class NativeGradientLearning:
    def __init__(self, owner, policy):
        self.owner = owner
        self.backend = owner.native.backend
        self.policy = dict(policy)
        self.admissions = json.loads(owner.native.mind.store.get_metadata("helix_gradient_admissions", "{}"))
        self.active = None
        self.backend.configure_learning(policy)
        self.backend.receipt_sink = self._record_update

    def _save(self):
        self.owner.native.mind.store.set_metadata("helix_gradient_admissions", json.dumps(self.admissions))

    def _record_update(self, receipt):
        bound = {**receipt, "admission_id": self.active,
                 "weight_owner": str(self.owner.directory / "joint")}
        self.owner.native._record_learning(bound)
        emitted = dict(bound)
        emitted["update_kind"] = emitted.pop("kind")
        self.owner._receipt("gradient_update", **emitted)

    def _admit(self, admission_id, content, kind, operation):
        digest = hashlib.sha256(content.encode()).hexdigest()
        existing = self.admissions.get(admission_id)
        if existing:
            if existing["payload_sha256"] != digest or existing["input_kind"] != kind:
                raise RuntimeError("A learning admission ID was reused with different content or ownership")
            if existing["status"] != "completed":
                raise RuntimeError(f"Learning admission {admission_id} is unfinished; inspect its recorded updates before recovery")
            self.owner._receipt("gradient_admission_reused", admission_id=admission_id, **existing)
            return {"tokens": 0, "reused": True}
        before = self.backend.weight_report() if self.policy["enabled"] else None
        entry = {"input_kind": kind, "status": "started", "payload_sha256": digest,
                 "updates_before": self.backend.counters["updates"]}
        self.admissions[admission_id] = entry
        self._save()
        self.active = admission_id
        try:
            tokens = operation()
            entry.update(status="completed", tokens=tokens,
                         updates_after=self.backend.counters["updates"],
                         weights_before=before,
                         weights_after=self.backend.weight_report() if before is not None else None)
        except BaseException as error:
            entry.update(status="failed", error=f"{type(error).__name__}: {error}",
                         updates_after=self.backend.counters["updates"])
            self._save()
            self.owner._receipt("gradient_admission_failed", admission_id=admission_id, **entry)
            raise
        finally:
            self.active = None
        self._save()
        self.owner._receipt("gradient_admission", admission_id=admission_id, policy=self.policy, **entry)
        return {"tokens": entry["tokens"], "reused": False}

    def external(self, content, source_id, *, kind):
        def consume():
            ids = self.backend.encode(content)
            if ids:
                if self.policy["enabled"]:
                    self.backend.learn_tokens(ids, source=kind + ":" + source_id)
                else:
                    self.backend.consume(ids)
            return len(ids)
        return self._admit(source_id, content, kind, consume)

    def capture_action(self):
        if not self.policy["enabled"]:
            return None
        return {"state": self.backend.dump_state(), "graph": self.backend._graph_vectors()}

    def returned(self, result, eligibility):
        receipt = result.get("receipt", {})
        action = result.get("action")
        if (receipt.get("verified") is not True or not receipt.get("receipt_id")
                or not receipt.get("return_record_id") or not receipt.get("outcome_id")
                or not result.get("return_pulse") or not result.get("proposal_pulse")
                or result.get("selected_affordance") != f"ability:helix-workspace-{action}"):
            self.owner._receipt("gradient_return_excluded", action=action,
                                reason="no matching, settled native observation; no outcome supervision applied")
            text = json.dumps({"status": result.get("status"), "error": result.get("error")}, sort_keys=True)
            ids = self.backend.encode(text)
            if ids:
                self.backend.consume(ids)
            return len(ids)
        source_id = receipt["receipt_id"]
        # Arguments/proposals are generated intentions, not observed targets.
        observed = json.dumps({"status": receipt.get("status"), "output": receipt.get("output"),
                               "error": receipt.get("error")}, sort_keys=True, ensure_ascii=False)
        admitted = self.external(observed, source_id + ":observation", kind="native_observation")
        if self.policy["enabled"]:
            from habitus_ai.types import OutputTrunk
            trunk = OutputTrunk.LOOK if action in {"sense", "open"} else OutputTrunk.DO
            def update():
                self.backend.learn_action(trunk, success=receipt.get("status") == "success",
                                          receipt_id=source_id, eligibility=eligibility)
                return 0
            self._admit(source_id + ":outcome", observed, "native_outcome", update)
        return admitted["tokens"]


class NativeLanguageBackend:
    """Separate foreground recurrent states over the agent's actual weights.

    Each forward is serialized with native updates. No frozen model cache or
    inference replica is substituted for the checkpointed learning lineage.
    """
    def __init__(self, owner):
        self.owner = owner
        self.native_stream = True
        backend = owner.native.backend
        for name in ("torch", "device", "model", "tokenizer", "embedding_dimension", "eos_token_id", "identity"):
            setattr(self, name, getattr(backend, name))
        self.versions = {}

    def encode(self, text):
        return self.owner.native.backend.encode(text)

    def decode(self, ids):
        return self.owner.native.backend.decode(ids)

    def begin_generation(self):
        self.versions = {}

    def generation_receipt(self):
        return {"weight_owner": str(self.owner.directory / "joint"), "model": self.identity,
                "versions_used": list(self.versions.values()),
                "execution": "native serial owner; independent foreground recurrent state"}

    def forward_branch(self, *, state, input_ids=None, inputs_embeds=None, **kwargs):
        return self.owner._worker.submit(self._forward, state, input_ids, inputs_embeds).result()

    def _forward(self, state, input_ids, inputs_embeds):
        backend = self.owner.native.backend
        if backend.cancel_event.is_set():
            raise RuntimeError("Native foreground cancelled by explicit lifecycle stop")
        current = backend.state
        try:
            backend.state = state if state is not None else backend.model.rwkv7.allocate_state(
                1, backend.device, backend.torch.bfloat16)
            for layer in getattr(backend.state, "layers", ())[getattr(backend, "first_trainable", 0):]:
                for slot in (backend.state.ATT_SHIFT, backend.state.FFN_SHIFT):
                    layer.recurrent_states[slot] = layer.recurrent_states[slot].float()
            ids = input_ids[0].tolist() if input_ids is not None else None
            logits = backend._forward(ids, inputs_embeds=inputs_embeds)
            version = backend.counters["updates"]
            record = self.versions.setdefault(version, {"gradient_update": version, "forward_calls": 0, "input_tokens": 0})
            record["forward_calls"] += 1
            record["input_tokens"] += len(ids) if ids is not None else inputs_embeds.shape[1]
            return SimpleNamespace(logits=logits, state=backend.state)
        finally:
            backend.state = current
