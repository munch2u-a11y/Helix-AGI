"""Gestate/resume MightyMem's native RWKV/cortex within the Helix pulse.

Helix owns cadence, mRAG, physics, foreground inference and host actions. This
adapter owns the joint recurrent state and Loom projection on one worker thread.
It does not invent motor vectors or turn an unverified thought into an outcome.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import time
import uuid
import threading
from typing import Any, Sequence

from core.mindscape_config import ROOT, activate, source_receipt, write_json
from core.pulse_context import ContextContribution, PulseContext, recalled_contribution


def projection(item):
    """Content-address mutable beliefs; retain the canonical Helix source ID."""
    content = str(item["content"])
    digest = hashlib.sha256(content.encode()).hexdigest()
    source_id = str(item["id"])
    envelope = item.get("record_envelope") or {}
    kind = envelope.get("kind") or envelope.get("record_kind") or item.get("record_kind")
    if item.get("memory_type") == "thought" or kind == "thought":
        loom_kind, status, native_kind = "thought", "private", "thought"
    elif kind == "inbound_message":
        loom_kind, status, native_kind = "user", "user_reported", "inbound_message"
    elif kind == "outbound_message":
        loom_kind, status, native_kind = "assistant", "model_inferred", "outbound_message"
    else:
        # Historical status labels and model beliefs do not prove observations.
        loom_kind, status, native_kind = "episode", "unverified", "raw_memory"
    created = item.get("created_at")
    if isinstance(created, str) and created:
        parsed = datetime.fromisoformat(created.replace("Z", "+00:00"))
        created = parsed.replace(tzinfo=parsed.tzinfo or timezone.utc).timestamp()
    return {"id": f"helix:{source_id}:{digest}", "source_id": source_id,
            "content": content, "sha256": digest, "kind": loom_kind,
            "evidence_status": status, "native_kind": native_kind,
            "created_at": float(created) if created else 0.0,
            "metadata": {"helix_source_id": source_id, "source_sha256": digest,
                         "context_role": recalled_contribution(item).section,
                         "historical_projection": True, "record_envelope": envelope}}


def classify_sensed_feeling(sensed: Any, events: Sequence[str], *, delivery_target=None) -> dict[str, Any]:
    """Decode RWKV recurrent cortex dynamics into an explicit sensory-motor feeling.

    Distinguishes between:
      - EXTERNAL_COMMUNICATION: outbound message/response directed at an external recipient.
      - INTERNAL_MONOLOGUE: private self-reflection / inner thought; not to be sent externally.
    """
    from habitus_ai.types import OutputTrunk

    speak_prob = 0.0
    cortex_valence = 0.0
    cortex_confidence = 0.0
    if getattr(sensed, "cortex_proposal", None) is not None:
        speak_prob = float(sensed.cortex_proposal.action_probabilities.get("SPEAK", 0.0))
        cortex_valence = float(getattr(sensed.cortex_proposal, "predicted_valence", 0.0))
        cortex_confidence = float(getattr(sensed.cortex_proposal, "confidence", 0.0))

    cycle = getattr(sensed, "cycle", None)
    selected_outputs = getattr(cycle, "selected_outputs", ()) or ()
    selected_speak = any(
        getattr(item, "trunk", None) == OutputTrunk.SPEAK or str(getattr(item, "trunk", "")) == "SPEAK"
        for item in selected_outputs
    )
    route_speak = "OUT:SPEAK" in (getattr(sensed, "route_ids", ()) or ())
    recurrent = getattr(cycle, "recurrent", None)
    recurrent_express = bool(getattr(recurrent, "should_express", False))

    # Detect if any incoming event is explicitly addressing Helix from outside
    has_inbound_speaker = False
    inbound_speaker_name = None
    inbound_channel = None
    for ev in events:
        text = str(ev).strip()
        lower = text.lower()
        if "is talking to me via" in lower:
            has_inbound_speaker = True
            cleaned = re.sub(r"^(?:\[[^\]]+\]\s*)+", "", text)
            match = re.search(r"^([A-Za-z][\w .'-]{0,39})\s+is talking to me via\s*(\w+)?", cleaned, re.IGNORECASE)
            if match:
                inbound_speaker_name = match.group(1).strip()
                if match.group(2):
                    inbound_channel = match.group(2).strip()
            break
        elif lower.startswith("user:") or lower.startswith("[user]") or "user_message" in lower:
            has_inbound_speaker = True
            inbound_speaker_name = "User"
            inbound_channel = "direct"
            break
        elif any(marker in lower for marker in ("telegram:", "discord:", "[direct]")):
            has_inbound_speaker = True
            inbound_channel = "direct"
            break

    # Determine feeling modality:
    # An external communication is felt if:
    # 1) An inbound speaker addressed us directly
    # 2) Or the recurrent state's desire/pressure indicates should_express with speak affordance/route
    # 3) Or cortex proposal strongly predicts SPEAK (prob >= 0.5)
    is_external = False
    if has_inbound_speaker:
        is_external = True
    elif selected_speak or route_speak or (recurrent_express and speak_prob >= 0.4):
        is_external = True

    outward_requested = is_external
    recipient_source = "received message" if has_inbound_speaker else None
    if not has_inbound_speaker and delivery_target:
        inbound_speaker_name = delivery_target["recipient"]
        inbound_channel = delivery_target["channel"]
        recipient_source = delivery_target["source"]
    speech_available = bool(inbound_speaker_name and inbound_channel)
    is_external = bool(outward_requested and inbound_speaker_name and inbound_channel)
    modality = "EXTERNAL_COMMUNICATION" if is_external else "INTERNAL_MONOLOGUE"

    if speech_available and not has_inbound_speaker:
        feeling_tag = "[Somatic Sensory Feeling: SELF_INITIATED_COMMUNICATION_AVAILABLE]"
        feeling_guidance = (
            f"{feeling_tag}\nNo new message arrived. I can continue thinking privately, act, "
            f"or choose to speak to {inbound_speaker_name} through {inbound_channel}. "
            "Choosing speech does not require being asked a question. Actual returns inform my next thought.")
    elif is_external:
        feeling_tag = "[Somatic Sensory Feeling: EXTERNAL_COMMUNICATION_DIRECTED]"
        feeling_guidance = (
            f"{feeling_tag}\n"
            f"I am hearing {inbound_speaker_name} through {inbound_channel}; speech can reach them. "
            "I can keep thinking privately before choosing whether to speak. "
            "If I need more information or an action, its actual return can inform my next thought."
        )
    else:
        feeling_tag = "[Somatic Sensory Feeling: INTERNAL_MONOLOGUE_ONLY]"
        feeling_guidance = (
            f"{feeling_tag}\n"
            "My thought is private. There is no resolved external recipient for this pulse. "
            "I can continue my line of thought and let new sensations and action returns inform it."
        )

    return {
        "modality": modality,
        "is_external": is_external,
        "outward_requested": outward_requested,
        "speech_available": speech_available,
        "recipient_source": recipient_source,
        "speak_probability": speak_prob,
        "recurrent_express": recurrent_express,
        "selected_speak": selected_speak,
        "route_speak": route_speak,
        "inbound_speaker": inbound_speaker_name,
        "inbound_channel": inbound_channel,
        "predicted_valence": cortex_valence,
        "confidence": cortex_confidence,
        "feeling_tag": feeling_tag,
        "feeling_guidance": feeling_guidance,
    }


class Mindscape:
    def __init__(self, config, data_dir, preconscious, *, local_models=None):
        self.config = activate(config)
        self.preconscious = preconscious
        if preconscious._unified is None:
            raise RuntimeError("Full mindscape cannot start: native Helix mRAG failed to initialize")
        self.directory = Path(data_dir).resolve() / "mindscape"
        self.directory.mkdir(parents=True, exist_ok=True)
        self._owner = (self.directory / "launcher.lock").open("a")
        try:
            fcntl.flock(self._owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            self._owner.close()
            raise RuntimeError(f"Mindscape already has a launcher owner: {self.directory}") from None
        self._worker = ThreadPoolExecutor(max_workers=1, thread_name_prefix="helix-mindscape")
        self._intake = ThreadPoolExecutor(max_workers=1, thread_name_prefix="helix-receptive")
        self.perception_lock = threading.RLock()
        self._receptive_pending = set()
        self._closed = False
        self.native = None
        self.loom = None
        self.session_id = uuid.uuid4().hex
        from core.progress_feedback import ProgressFeedback
        self.progress_feedback = ProgressFeedback()
        self._receipt_lock = threading.Lock()
        self.manifest = {
            "schema": "helix-mindscape-composition-v1",
            "process_id": os.getpid(),
            "status": "initializing",
            "entrypoint": "main.py -> setup_helix -> PulseLoop._pulse",
            "helix": source_receipt(ROOT),
            "mightymem": source_receipt(self.config["mindscape"]["package_path"]),
            "configuration": {key: self.config[key] for key in (
                "composition", "pulse_mode", "local_provider", "local_model", "local_context_window", "mindscape")},
            "stores": {"canonical": str(Path(data_dir).resolve()), "joint_state": str(self.directory / "joint"),
                       "loom_projection": str(self.directory / "loom.sqlite")},
            "route": ["Helix canonical memory and beliefs", "native mRAG and Context Office",
                      "Helix preconscious and 8D physics", "MightyMem Habitus graph and cortex",
                      "RWKV recurrent input and native cortex bridge", "Context Loom compiler",
                      f"local {self.config['local_provider']} foreground", "Helix action/channel path", "canonical post-pulse persistence"],
            "hardware": {"platform": platform.platform(), "neural_device": "cpu"},
            "local_models": local_models,
            "auxiliary_provider": {"provider": self.config["local_provider"], "model": self.config["local_model"],
                                   "route": "isolated local direct session; no remote fallback"},
            "evaluation": {"kind": "composition initialization", "dataset": None, "grader": None,
                           "product_result": None},
            "boundaries": {
                "new_action_or_reasoning_ceiling": None, "sync_record_limit": None,
                "rwkv_chunk_tokens": {"value": self.config["mindscape"]["gradient_learning"]["chunk_tokens"],
                                      "meaning": "configurable training compute/BPTT batch for memory use; all input tokens consumed"},
                "loom_context": {"value": self.config["local_context_window"], "reason": "selected foreground context"},
                "pulse_items": {"value": self.config["mindscape"]["context_item_limit"],
                                "reason": "user-requested cognitive breadth across pulses; whole items only",
                                "overflow": "required current experience fails explicitly; optional sources deferred"},
                "loom_adaptive_shortlist": "disabled; compiler uses selected context",
                "private_evidence": "typed cognitive context only; not factual or action evidence",
                "retrieval_nominations": "all eligible heads and sources; no count/token shortlist before production context admission",
                "foreground_output": "no generation ceiling; complete request checked against selected physical context; incomplete output fails explicitly",
                "embedding_boundary": "declared embedding model context; truncate=false; input too large fails explicitly",
                "provider_failures": "explicit boundary failure; no capped retries or reduced-system fallback on the native route",
                "excluded_legacy_paths": "legacy orchestrated tools, gravity fallback, dual pulse and office-first loops are not part of native Mindscape",
            },
            "capability_status": {
                "rwkv_role": f"native recurrent input/cortex coupling; {self.config['local_provider']} foreground language",
                "non_tool_file_motor": "independent filesystem sensor and typed motor body; explicit user-goal bootstrap, not learned autonomy",
                "gradient_learning": self.config["mindscape"]["gradient_learning"],
                "cortex_plasticity": "native Habitus runtime; no fabricated rewards",
            },
        }
        write_json(self.directory / "composition-manifest.json", self.manifest)
        try:
            self._worker.submit(self._open).result()
            self.sync()
            self._worker.submit(self._checkpoint, "helix-launch-sync").result()
            self.manifest["status"] = "initialized"
            write_json(self.directory / "composition-manifest.json", self.manifest)
        except BaseException as error:
            self.manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
            write_json(self.directory / "composition-manifest.json", self.manifest)
            self._worker.submit(self._release).result()
            self._worker.shutdown(wait=True)
            self._owner.close()
            raise

    def _receipt(self, kind, **values):
        with self._receipt_lock, (self.directory / "receipts.jsonl").open("a") as stream:
            stream.write(json.dumps({"time": time.time(), "kind": kind, **values}, default=str, allow_nan=False) + "\n")

    def foreground_backend(self, model_path):
        if Path(model_path).resolve() != Path(self.config["mindscape"]["rwkv_model"]).resolve():
            raise RuntimeError("Native foreground must use the declared agent-owned checkpoint; no frozen substitute was loaded")
        return self.language_backend

    def _open(self):
        from habitus_ai.continual_mind import ContinualMind
        from context_loom.engine import ContextLoom
        from context_loom.compiler import CompilerConfig, AdaptiveBudgetPolicy
        from context_loom.topical import TopicalTracker
        from core.mindscape_context import MindscapeContextCompiler
        from core.mindscape_lanes import HabitusLane, SemanticBridge
        # Reading a chunk must not inspect only its first four sentences.
        # All sentence heads participate; existing derived-head and candidate
        # policies remain visible inherited boundaries, not coverage claims.
        self.preconscious._unified.lane_a.contextual_sentence_heads = True
        # All production lanes nominate their eligible sources. The compiler
        # owns whole-item admission at the selected physical model boundary.
        self.preconscious.complete_nominations = True
        self.preconscious._unified.complete_nominations = True
        self.preconscious._unified.lane_a.complete_nominations = True
        self.preconscious._unified.vector_store.complete_nominations = True
        if self.preconscious._associative is not None:
            self.preconscious._associative.complete_nominations = True
        office = self.preconscious._unified.context_office
        if office is not None:
            office.complete_nominations = True
            office.MAX_SCOPE_ITEMS = None
        joint = self.directory / "joint"
        resumed = (joint / "LATEST.json").exists()
        if not resumed and self.config["mindscape"]["gestation"] == "resume_only":
            raise RuntimeError(f"Resume required but no joint checkpoint exists: {joint}")
        from core.agent_home import prepare_home
        from core.agent_creation import native_seed, verify_native_profile
        self.home = prepare_home(self.config, state_directory=self.directory)
        requested_seed = native_seed(self.config) if not resumed or self.config.get("creation") else None
        learning = self.config["mindscape"]["gradient_learning"]
        self.native = ContinualMind(model=Path(self.config["mindscape"]["rwkv_model"]),
                                    directory=joint, workspace=Path(self.home["root"]),
                                    gestation_seed=requested_seed,
                                    trainable_blocks=learning["rwkv_tail_blocks"], chunk_tokens=learning["chunk_tokens"])
        self.gestation_receipt = (verify_native_profile(self.native.profile, self.config) if requested_seed else
                                  {"actual": asdict(self.native.profile), "legacy_profile_preserved": True})
        from core.native_learning import NativeGradientLearning, NativeLanguageBackend
        self.learning = NativeGradientLearning(self, learning)
        self.language_backend = NativeLanguageBackend(self)
        from core.mindscape_workspace import NativeWorkspaceBody
        self.body = NativeWorkspaceBody(self.native, self.home["root"], home=self.home)
        self.continuation = json.loads(self.native.mind.store.get_metadata("helix_pulse_continuation", "{}"))
        from core.native_motor import NativeMotorSystem
        self.motor = NativeMotorSystem(self)
        self._admitted_foreground = None
        self._motor_context_id = None
        self._observed_return_id = None
        if str(self.native.backend.device) != "cpu" or str(self.native.runtime.cortex.device) != "cpu":
            raise RuntimeError("Native joint bridge initialized on an undeclared device")
        if self.config['local_provider'] in {'rwkv', 'bicameral_rwkv'}:
            from llm.rwkv_tokens import RWKVTokenCounter
            self.token_counter = RWKVTokenCounter(self.native.backend.encode, self.config['local_model'], thinking=True)
        else:
            from llm.ollama_tokens import OllamaTokenCounter
            self.token_counter = OllamaTokenCounter(self.config["local_model"])
        loaded = (self.manifest.get("local_models") or {}).get("models", [])
        served = next((entry for entry in loaded if entry["model"] == self.config["local_model"]), None)
        if served and served["digest"] != self.token_counter.model_digest:
            raise RuntimeError("Installed tokenizer manifest does not match the model served by Ollama")
        self.loom = ContextLoom(self.directory / "loom.sqlite",
            config=CompilerConfig(model_context_tokens=int(self.config["local_context_window"]),
                                  reserved_output_tokens=0,
                                  adaptive_budget=AdaptiveBudgetPolicy(enabled=False),
                                  render_capability_schemas=False),
            embedding_provider=SemanticBridge(self.preconscious.physics.semantic_encoder),
            install_default_capabilities=False)
        compiler = self.loom.compiler
        self.loom.compiler = MindscapeContextCompiler(
            compiler.store, config=compiler.config,
            embedding_provider=compiler.embedding_provider,
            lanes=compiler.lanes, token_counter=self.token_counter,
            focus_profiles=self.config["mindscape"]["context_focus_profiles"],
            item_limit=self.config["mindscape"]["context_item_limit"],
        )
        self.topical = TopicalTracker(self.loom.store)
        self._current_topic_frame = None
        self.graph_lane = HabitusLane(self.native.mind, on_recall=self._observe_current_paths)
        self.loom.compiler.lanes.append(self.graph_lane)
        with self.loom.store.connection:
            self.loom.store.connection.execute(
                "CREATE TABLE IF NOT EXISTS helix_graph_projection (record_id TEXT PRIMARY KEY)")
        self.manifest["runtime"] = {
            "gestation": "resumed" if resumed else "new",
            "rwkv": self.native.backend.identity,
            "rwkv_parameters": self.native.backend.statistics["weight_tensor_elements"],
            "cortex_parameters": self.native.runtime.cortex.parameter_count,
            "joint_generation": self.native.generation,
            "loom_lanes": [lane.name for lane in self.loom.compiler.lanes],
            "context_compiler": "core.mindscape_context.MindscapeContextCompiler",
            "tokenizer": self.token_counter.provenance,
            "context_layout": "separate-routing-and-native-ability-effects-v9",
            "foreground_format": "ordinary speech or private thought; language has no actuator authority",
            "history_presentation": "delivered assistant prose wrapped losslessly in message JSON; private intentions excluded",
            "recalled_assistant_policy": "older model statements require an explicit past-statement query; actual provider dialogue stays present",
            "context_focus_profiles": self.loom.compiler.focus_profiles,
            "context_focus_status": "configurable bootstrap priorities; not learned RWKV attention",
            "action_intent_source": self.config["mindscape"]["action_intent_source"],
            "action_route": "context-admitted user request -> integer motor signal -> native SELF selected affordance -> workspace actuator -> native sensory return -> next Helix pulse",
            "native_abilities": self.body.abilities,
            "motor_policy": self.motor.policy,
            "motor_route": "actual received user goal -> production context admission -> numeric motor signal -> native SELF authorization -> actuator -> actual sensory return",
            "sensory_interval_seconds": self.motor.interval,
            "agent_home": self.home,
            "gestation_seed": self.gestation_receipt,
            "primary_channel": self.config["primary_channel"],
            "sensory_route": "independent filesystem clock -> persistent raw intake -> native SEE/cortex/RWKV admission -> focus-weighted context; intake continues during inference and execution",
            "module_route": "native authorization -> installed script or production dream engine -> return focus -> consumption/disengage",
            "context_queries": "fresh events; last complete private thought only on idle continuation",
            "context_receipt": "pulse_context.context_assembly plus native loom_packet manifest",
            "inline_annotations": "exact unique passage anchors from actual mRAG sentence-head returns; no truth or permission inference",
            "sentence_coverage": "all nonempty sentence views; inherited candidate/context admission limits remain",
            "mrag": type(self.preconscious._unified.lane_a).__module__,
            "embedding": self.loom.compiler.embedding_provider.identity,
        }
        self._receipt("initialized", **self.manifest["runtime"])
        if not resumed:
            sensory, _, _, _ = self._sense_home("gestation")
            self.native.latest_pulse = self.native.runtime.advance((sensory,))
            self._receipt("home_sensory_admission", helix_pulse="gestation",
                          native_pulse=asdict(self.native.latest_pulse))
            # Preserve the actual gestation before slow historical indexing.
            # A later sync failure must not strand an uncheckpointed mind.
            self._checkpoint("helix-gestation")
        if self.config.get("creation"):
            from core.agent_creation import record_native_gestation
            self._receipt("agent_creation_gestation", manifest=record_native_gestation(
                self.config, self.native.profile, data_dir=self.directory.parent,
                generation=self.native.generation, resumed=resumed))

    def _sense_home(self, pulse):
        from habitus_ai.developmental_runtime import DevelopmentalInput
        from habitus_ai.types import InputTrunk
        scene, text = self.body.workspace.observe_environment(pulse)
        self.foreground_home_observation = {'text': text, 'producer': 'home_filesystem',
                                            'source_ids': [scene['observation_id']]}
        ids = self.native.backend.encode(text)
        if ids:
            self.native.backend.consume(ids)
        sensory = DevelopmentalInput(content=text, lane=InputTrunk.SEE,
            source_id=scene["observation_id"], motor_eligible=False,
            embedding=tuple(self.native.runtime.embedder.embed(text)),
            metadata={"helix_pulse": pulse, "sensor": "home_filesystem", "content_opened": False})
        self._receipt("home_sensory_intake", helix_pulse=pulse, observation=scene,
                      content_sha256=hashlib.sha256(text.encode()).hexdigest(), rwkv_tokens=len(ids))
        self.continuation["body_scene"] = {"id": scene["observation_id"], "action": "sense",
            "path": scene["surroundings"]["path"], "status": "success",
            "output": scene["surroundings"], "source": "actual filesystem sensor"}
        return sensory, scene, text, len(ids)

    def sync(self):
        # Read the actual Helix corpus on its calling thread. Nothing is sampled
        # or replaced by a prepared candidate cache.
        items = [projection(item) for item in self.preconscious._unified.corpus.all_items()]
        return self._worker.submit(self._sync, items).result()

    def _sync(self, items):
        from context_loom.models import RecordKind, EvidenceStatus
        from habitus_ai.types import RecordType, InputTrunk
        added = 0
        indexed = 0
        # A presentation view over current canonical types also covers older
        # projections without rewriting their historical evidence status.
        self.loom.compiler.canonical_roles = {item["id"]: item["metadata"]["context_role"] for item in items}
        heads = json.loads(self.native.mind.store.get_metadata("helix_sync_heads", "{}"))
        for item in items:
            rid = item["id"]
            metadata = item["metadata"]
            previous = heads.get(item["source_id"])
            supersedes = previous if previous and previous != rid else None
            if self.native.mind.store.get_record(rid) is None:
                self.native.mind.remember(item["content"], record_id=rid, event_id=rid,
                    source_id="helix-canonical-projection", record_type=RecordType(item["native_kind"]),
                    timestamp=datetime.fromtimestamp(item["created_at"], timezone.utc).isoformat(),
                    input_trunk=InputTrunk.NOTICE, metadata=metadata, supersedes_id=supersedes,
                    provenance={"source_record_ids": [item["source_id"]], "evidence_status": item["evidence_status"]})
            present = self.loom.store.get_record(rid) is not None
            projected = self.loom.store.connection.execute(
                "SELECT 1 FROM helix_graph_projection WHERE record_id=?", (rid,)).fetchone()
            if not projected:
                self.loom.log(speaker="helix-canonical", kind=RecordKind(item["kind"]),
                    content=item["content"], scope="helix", record_id=rid,
                    created_at=item["created_at"], source_ids=[item["source_id"]], metadata=metadata,
                    evidence_status=EvidenceStatus(item["evidence_status"]), supersedes_id=supersedes)
                self.loom.graph_store.index_record(rid, item["content"])
                with self.loom.store.connection:
                    self.loom.store.connection.execute(
                        "INSERT INTO helix_graph_projection(record_id) VALUES (?)", (rid,))
                indexed += 1
            if not present:
                added += 1
            heads[item["source_id"]] = rid
        self.native.mind.store.set_metadata("helix_sync_heads", json.dumps(heads))
        self._receipt("canonical_sync", source_records=len(items), added=added, graph_indexed=indexed,
                      gradient_updates=0, source_ids=[item["source_id"] for item in items])
        return added

    def receive_event(self, event):
        """Receive user input independently of a currently generating language turn."""
        from core.native_motor import receptive_steps
        try:
            potential = receptive_steps(event)
        except ValueError:
            potential = []  # An explicit rejected request still gets a receipt.
        if potential is None:
            self._receipt("motor_receptor_no_action", input_sha256=hashlib.sha256(event.encode()).hexdigest(),
                          reason="no explicit positive motor request")
            return
        input_id = getattr(event, "event_id", "receptive:" + uuid.uuid4().hex)
        self._receptive_pending.add(input_id)
        self._intake.submit(self._receive_event, event, input_id)

    def _receive_event(self, event, input_id):
        from core.pulse_context import build_pulse_context
        try:
            with self.perception_lock:
                annotations, ambient, _, _ = self.preconscious.inject(
                    previous_thought="", incoming_events=[event], trigger_type="user_message",
                    structured_context=True)
                context = build_pulse_context(pulse=input_id, timestamp=datetime.now().strftime("%H:%M:%S"),
                    events=[event], annotations=annotations, ambient=ambient, include_tool_observations=True)
                self.prepare([event], context.render(), input_id, context=context,
                             input_allowance=int(self.config["local_context_window"]), motor_input_id=input_id)
        except Exception as exc:
            self._receipt("motor_reception_failed", input_id=input_id, input=event,
                          error=f"{type(exc).__name__}: {exc}")
            self.motor_failure = str(exc)
        finally:
            self._receptive_pending.discard(input_id)

    def prepare(self, events, message, pulse, *, context: PulseContext, input_allowance=None, covered_source_hashes=(), motor_input_id=None):
        try:
            self.sync()
            mrag = dict(self.preconscious._unified.last_stats)
            mrag["query"] = getattr(self.preconscious, "_last_retrieval_query", "")
            mrag["passage_hits"] = getattr(self.preconscious._unified.lane_a, "last_anchor_hits", {})
            if context.pulse != pulse:
                raise ValueError("Pulse context does not match current pulse")
            return self._worker.submit(self._prepare, list(events), context, pulse, mrag, input_allowance, covered_source_hashes, motor_input_id).result()
        except Exception as error:
            self.fail(error, events, message, pulse)
            raise

    def fail(self, error, events, message, pulse):
        self.manifest.update(status="failed", error=f"{type(error).__name__}: {error}")
        write_json(self.directory / "composition-manifest.json", self.manifest)
        write_json(self.directory / "pending-failed-pulse.json", {
            "pulse": pulse, "events": list(events), "message": message,
            "error": str(error), "recovery": "resume the last joint checkpoint and explicitly resubmit the preserved input"})

    def _prepare(self, events, context, pulse, mrag, input_allowance=None, covered_source_hashes=(), motor_input_id=None):
        from habitus_ai.developmental_runtime import DevelopmentalInput
        from habitus_ai.types import InputTrunk
        private = self._load_private_continuation()
        if private is not None and not any(item.producer == "foreground_private" for item in context.contributions):
            context = context.extend(private)
        before = hashlib.sha256(self.native.backend.dump_state()).hexdigest()
        inputs = []
        token_count = 0
        if hasattr(self.body.workspace, "observe_environment"):
            if any(item.section == "messages" and item.producer == "pulse_event" for item in context.contributions):
                self.body.workspace.disengage()
            sensory, scene, scene_text, scene_tokens = self._sense_home(pulse)
            inputs.append(sensory)
            token_count += scene_tokens
            context = context.extend(ContextContribution(
                "environment", scene_text, "home_filesystem", (scene["observation_id"],),
                kind="sensory_observation", evidence="current filesystem attributes; contents not opened"))
            active = scene["active_module"]
            if active:
                context = context.extend(ContextContribution(
                    "module", json.dumps(active, ensure_ascii=False), "home_module",
                    kind="interface_state", evidence="controller state; actual output is in the action return"))
        for event in events:
            returns = list(self.continuation.get("motor_returns", ()))
            if self.continuation.get("return"):
                returns.append(self.continuation["return"])
            if any(event == f"Native action [{item['id']}] returned: " + item["content"] for item in returns):
                # Already consumed by ToolRegistry's native return pulse and
                # the RWKV return admission; present it to Helix once without
                # manufacturing a second external experience in Habitus.
                continue
            from core.native_learning import StreamEvent
            if isinstance(event, StreamEvent) and event.event_type in {"user_message", "incoming_message", "telegram_message"}:
                admission = self.learning.external(event.payload, event.event_id, kind="received_language")
                token_count += admission["tokens"]
                if admission["reused"]:
                    continue
            else:
                # Internal controller events advance state, never target weights.
                ids = self.native.backend.encode(event)
                if ids:
                    self.native.backend.consume(ids)
                    token_count += len(ids)
            inputs.append(DevelopmentalInput(content=event, lane=InputTrunk.NOTICE,
                source_id=getattr(event, "event_id", "helix-pulse-event"), motor_eligible=False,
                embedding=tuple(self.native.runtime.embedder.embed(event)),
                metadata={"helix_pulse": pulse, "unverified_event": True}))
        sensed = self.native.runtime.advance(tuple(inputs), allow_idle=not inputs)
        if hasattr(self.body.workspace, "observe_environment"):
            self._receipt("home_sensory_admission", helix_pulse=pulse,
                          observation_id=scene["observation_id"], native_pulse=asdict(sensed))
        self.native.backend.begin_slice()
        self.native.latest_pulse = sensed
        self._current_topic_frame = None

        dashboard_target = ({"recipient": self.config.get("creator_name", "User"),
                             "channel": "dashboard", "source": "configured primary dashboard"}
                            if self.config.get("primary_channel") == "dashboard" else None)
        feeling = classify_sensed_feeling(sensed, events, delivery_target=dashboard_target)
        current_items = [item for item in context.contributions
                         if item.section == "messages" and item.producer == "pulse_event"]
        current_messages = [item.text for item in current_items]
        if current_messages:
            from core.mindscape_intention import (
                requires_workspace_observation,
                extract_workspace_obligations,
                check_obligations_satisfied,
                step_guidance_for_pending,
            )
            old = self.continuation.get("pending", {})
            target = (feeling.get("inbound_speaker"), feeling.get("inbound_channel"))
            if old and (old["recipient"], old["channel"]) != target:
                raise RuntimeError("A different recipient has an unfinished native action; inputs preserved for explicit routing")
            old_ids = old.get("message_ids", ["legacy:" + hashlib.sha256(msg.encode()).hexdigest()
                                              for msg in old.get("messages", ())])
            fresh_items = [item for item in current_items if item.source_ids[0] not in old_ids]
            if old.get("messages") and fresh_items:
                context = context.extend(ContextContribution(
                    "task", "My continuing purpose, from the earlier request:\n" + "\n".join(old["messages"]),
                    "pending_interaction", kind="unresolved_request", evidence="actual received messages"))
            all_messages = old.get("messages", []) + [item.text for item in fresh_items]
            extracted_obl = extract_workspace_obligations(all_messages)
            self.continuation["pending"] = {
                "recipient": target[0], "channel": target[1],
                "messages": all_messages,
                "message_ids": old_ids + [item.source_ids[0] for item in fresh_items],
                "observation_required": old.get("observation_required", False) or any(
                    requires_workspace_observation(message) for message in current_messages),
                "obligations": {
                    "required_abilities": list(extracted_obl["required_abilities"]),
                    "target_paths": list(extracted_obl["target_paths"]),
                },
                "observed_native_attempt": old.get("observed_native_attempt", False),
                "observations": old.get("observations", [])}
            self._save_continuation()
        elif self.continuation.get("pending"):
            from core.mindscape_intention import (
                check_obligations_satisfied,
                step_guidance_for_pending,
            )
            pending = self.continuation["pending"]
            feeling = classify_sensed_feeling(sensed, pending["messages"])
            feeling["recipient_source"] = "persisted unfinished interaction, not a newly received message"
            context = context.extend(ContextContribution(
                "task", "My continuing purpose, from the earlier request:\n" + "\n".join(pending["messages"]),
                "pending_interaction", kind="unresolved_request", evidence="actual received messages"))
        self._observed_return_id = self.continuation.get("return", {}).get("id")
        pending = self.continuation.get("pending", {})
        if self.continuation.get("interface_feedback"):
            context = context.extend(ContextContribution(
                "work", self.continuation["interface_feedback"], "native_interface",
                kind="interface_feedback", evidence="actual dispatch status"))
        # Keep all unresolved work. The real model-context boundary must fail
        # explicitly rather than silently discarding an unfinished observation.
        for observation in pending.get("observations", []):
            if observation["id"] != self._observed_return_id:
                context = context.extend(ContextContribution(
                    "work", "An earlier actual return in this unfinished task:\n" + observation["content"],
                    "native_task_observation", (observation["id"],), "action_observation",
                    "native receipt; success/failure and content remain exactly as returned"))
        admitted_motor_ids = self.motor.admit(current_messages, pulse) if motor_input_id is not None else []
        for item in self.continuation.get("motor_returns", []):
            if not item.get("consumed") and not any(item["content"] in event for event in events):
                event = f"Native action [{item['id']}] returned: " + item["content"]
                events.append(event)
                context = context.extend(ContextContribution("tool_observations", event, "native_body",
                    (item["id"],), "action_observation", "actual native receipt"))
        self._observed_motor_ids = {item["id"] for item in self.continuation.get("motor_returns", [])
                                    if any(item["content"] in event for event in events)}
        self.needs_native_observation = self.motor.pending or bool(self._receptive_pending)
        if self.needs_native_observation:
            feeling.update(is_external=False, modality="INTERNAL_ACTION_REQUIRED",
                           delivery_gate="the independent motor body is processing an actual request or autonomous action")
            feeling["feeling_guidance"] = (
                "My body has an unfinished movement, reading, execution, or autonomous exploratory action. "
                "Its motor loop runs independently of my language stream. I can think privately while waiting. "
                "Actual sensory returns will show the results. My prose does not dispatch actions.")
        self.last_sensed_feeling = feeling
        self.last_sensed_modality = feeling["modality"]

        state = {"habitus_pulse": self.native.mind.pulse,
                 "rwkv_input_tokens": token_count,
                 "sensed_modality": feeling["modality"],
                 "communicative_intent": feeling["is_external"],
                 "speak_salience": round(feeling["speak_probability"], 3),
                 "recurrent_express": feeling["recurrent_express"],
                 "cortex_proposal": asdict(sensed.cortex_proposal) if sensed.cortex_proposal else None,
                 "external_evidence": False}
        context = context.extend(
            ContextContribution("direction", feeling["feeling_guidance"], "habitus_modality",
                                kind="output_direction", evidence="internal state"))
        context = context.extend(ContextContribution(
            "abilities", (f"My body is at /{self.body.workspace.position}. It can move, inspect directory attributes, "
                          "open real files, and run observed Python files in the isolated workshop. "
                          "Its numeric motor signals are separate from speech; language is not executable. "
                          "Results are actual returned observations. Only observed content establishes what a file says."),
            "native_workspace", kind="runtime_affordance", evidence="installed native actuators; bootstrap intention interface"))
        sentinel = getattr(getattr(self, "preconscious", None), "sentinel", None)
        if sentinel is not None and hasattr(sentinel, "get_cognitive_focus_state"):
            from core.context_focus import ContextFocus
            from dataclasses import replace
            focus_state = sentinel.get_cognitive_focus_state(
                feeling=feeling,
                has_pending_obligations=self.needs_native_observation,
            )
            context = replace(context, focus=ContextFocus(focus_state["weights"], "sentinel_thermodynamic"))
        if hasattr(self.body.workspace, "active_module"):
            from core.context_focus import ContextFocus, infer_focus
            from dataclasses import replace
            focus = context.focus or infer_focus(context.query, context.query_source)
            weights = dict(focus.weights)
            weights["module" if self.body.workspace.active_module() else "environment"] = 1.0
            context = replace(context, focus=ContextFocus(weights, focus.source + "+home_interface"))
        context = context.extend(*self.motor.procedure_context(current_messages or pending.get("messages", [])))
        packet = self.loom.compiler.compile_pulse(context, scope="helix", input_allowance=input_allowance,
                                                 covered_source_hashes=covered_source_hashes)
        frame = self._current_topic_frame
        if frame is None:
            raise RuntimeError("Native graph recall did not supply current topic orientation")
        after = hashlib.sha256(self.native.backend.dump_state()).hexdigest()
        self._receipt("pulse_context", helix_pulse=pulse, events=events, rwkv_tokens=token_count,
            joint_state_before=before, joint_state_after=after, habitus_pulse=self.native.mind.pulse,
            sensed_modality=feeling["modality"], communicative_intent=feeling["is_external"],
            foreground_protocol="intention_required" if self.needs_native_observation else "intention_or_message",
            cortex_proposal=asdict(sensed.cortex_proposal) if sensed.cortex_proposal else None,
            graph_field=list(sensed.graph_field), topical=frame.as_dict(),
            recurrent_state=state,
            mrag=mrag, loom_packet=packet.to_dict(), graph_trace=self.graph_lane.trace,
            context_assembly=self.loom.compiler.last_assembly_receipt)
        # Every native branch receives the actual production compiler output
        # before independent motor selection, including without a user request.
        compiled_ids = self.native.backend.encode(packet.rendered)
        state_before = hashlib.sha256(self.native.backend.dump_state()).hexdigest()
        if compiled_ids:
            self.native.backend.consume(compiled_ids)
        self._receipt("motor_context_model_admission", context_id=packet.id,
                      request_ids=admitted_motor_ids, model=self.native.backend.identity,
                      device=str(self.native.backend.device), tokens=len(compiled_ids),
                      content_sha256=hashlib.sha256(packet.rendered.encode()).hexdigest(),
                      joint_state_before=state_before,
                      joint_state_after=hashlib.sha256(self.native.backend.dump_state()).hexdigest(),
                      output="recurrent state, no language decoding")
        self._motor_context_id = packet.id
        self.motor.link_context(admitted_motor_ids, packet.id)
        return packet.rendered

    def _observe_current_paths(self, paths):
        from core.mindscape_lanes import topical_paths
        frame = self.topical.observe_turn(topical_paths(paths))
        self._current_topic_frame = frame
        compiler = self.loom.compiler
        if compiler._pulse_context is None:
            raise RuntimeError("Topic orientation arrived outside its owning context compilation")
        if frame.rendered:
            compiler._pulse_context = compiler._pulse_context.extend(ContextContribution(
                "topical", frame.rendered, "habitus_topical", kind="internal_state",
                evidence="current graph traversal, not external evidence"))

    def finish(self, thought, pulse, *, delivered_external=False, observed_motor_ids=None,
               private_continuation=None):
        try:
            self.sync()
            return self._worker.submit(self._finish, thought, pulse, delivered_external,
                                       observed_motor_ids, private_continuation).result()
        except Exception as error:
            self.fail(error, [], thought, pulse)
            raise

    def _admit_foreground(self, thought, pulse, delivered_external=False, *, channel="foreground"):
        # The recurrent controller must experience its own foreground output.
        # This is internal state advancement, never an external observation or
        # an implicit successful action. No gradients or motor forms are trained.
        from habitus_ai.developmental_runtime import DevelopmentalInput
        from habitus_ai.types import InputTrunk
        identity = (pulse, channel, hashlib.sha256(thought.encode()).hexdigest())
        if self._admitted_foreground == identity:
            return
        before = hashlib.sha256(self.native.backend.dump_state()).hexdigest()
        ids = self.native.backend.encode(thought)
        if ids:
            self.native.backend.consume(ids)
        own_output = DevelopmentalInput(
            content=thought, lane=InputTrunk.NOTICE,
            source_id=f"helix-own-output:{self.session_id}:{pulse}:{channel}", motor_eligible=False,
            embedding=tuple(self.native.runtime.embedder.embed(thought)),
            metadata={"helix_pulse": pulse, "self_generated": True,
                      "external_evidence": False, "delivered_external": bool(delivered_external),
                      "output_channel": channel})
        self.native.latest_pulse = self.native.runtime.advance((own_output,))
        self._receipt("foreground_internal_admission", helix_pulse=pulse, rwkv_tokens=len(ids),
                      output_channel=channel,
                      source_id=own_output.source_id, joint_state_before=before,
                      joint_state_after=hashlib.sha256(self.native.backend.dump_state()).hexdigest(),
                      external_evidence=False, gradient_updates=0)
        self._admitted_foreground = identity

    def _save_continuation(self):
        self.native.mind.store.set_metadata("helix_pulse_continuation", json.dumps(self.continuation, ensure_ascii=False))

    def private_continuation(self):
        """Restore private continuity before retrieval, including after restart."""
        return self._worker.submit(self._load_private_continuation).result()

    def _load_private_continuation(self):
        saved = self.continuation.get("private_thought")
        if saved:
            saved = dict(saved)
            for key in ("source_ids", "anchor_queries"):
                saved[key] = tuple(saved.get(key, ()))
            return ContextContribution(**saved)
        # Older checkpoints kept thoughts inside unfinished interactions. Read
        # only the latest as active cognition; canonical memory retains history.
        thoughts = self.continuation.get("pending", {}).get("thoughts", ())
        if thoughts:
            text = thoughts[-1]
            if text.startswith("[thought]"):
                text = text[len("[thought]"):].lstrip()
            return ContextContribution("thinking", text, "foreground_private",
                                       kind="thought", evidence="legacy private continuation", owner="agent")
        return None

    def pending_events(self):
        def read():
            returned = self.continuation.get("return")
            legacy = ([f"Native action [{returned['id']}] returned: " + returned["content"]]
                      if returned and not returned.get("consumed") else [])
            return legacy + [f"Native action [{item['id']}] returned: " + item["content"]
                             for item in self.continuation.get("motor_returns", []) if not item.get("consumed")]
        return self._worker.submit(read).result()

    def start_motor(self, wake):
        write_json(self.directory / "foreground-health.json", {"status": "ready", "body_receptive": True})
        self.motor.start(wake)

    def stop_motor(self):
        if hasattr(self, "motor"):
            if self.native is not None:
                self.native.backend.cancel_pending()
            self.motor.stop()

    def _admit_motor_target(self, observation_id, observed, handle, path):
        from habitus_ai.developmental_runtime import DevelopmentalInput
        from habitus_ai.types import InputTrunk
        text = json.dumps({"observation": observed, "target_handle": handle, "path": path}, sort_keys=True)
        ids = self.native.backend.encode(text)
        if ids:
            self.native.backend.consume(ids)
        sensory = DevelopmentalInput(content=text, lane=InputTrunk.SEE, source_id=observation_id,
                                     motor_eligible=False, embedding=tuple(self.native.runtime.embedder.embed(text)),
                                     metadata={"sensor": "filesystem_target", "content_opened": False})
        self.native.latest_pulse = self.native.runtime.advance((sensory,))
        self._receipt("motor_target_sensory", observation_id=observation_id, target_handle=handle,
                      path=path, observed=observed, rwkv_tokens=len(ids))

    def _admit_motor_scene(self, frame):
        self._admit_motor_target(frame["observation_id"], frame["surroundings"],
                                 frame["scene_sha256"], frame["surroundings"]["path"])
        self.foreground_home_observation = {"text": json.dumps(frame, sort_keys=True),
                                           "producer": "home_filesystem", "source_ids": [frame["observation_id"]]}
        self.continuation["body_scene"] = {"id": frame["observation_id"], "action": "sense",
            "path": frame["surroundings"]["path"], "status": "success",
            "output": frame["surroundings"], "source": "actual filesystem sensor"}

    def _autonomous_motor_step(self):
        """Native quiet deliberation on the body clock, even during speech inference."""
        if not self._motor_context_id or self._receptive_pending:
            return
        from core.mindscape_intention import resolve_subconscious_action
        self.native.latest_pulse = self.native.runtime.advance((), allow_idle=True)
        self.native.backend.begin_slice()
        trunks = self.get_active_subconscious_trunks()
        observations = list(self.continuation.get("body_observations", {}).values())
        if self.continuation.get("body_scene"):
            observations.append(self.continuation["body_scene"])
        # Explicit requests already have their independent, target-bound jobs.
        # Quiet native selection only resolves observed exploratory targets.
        intention = resolve_subconscious_action({}, observations,
            current_position=self.body.workspace.position, active_trunks=trunks)
        sensed = self.native.latest_pulse
        self._receipt("native_autonomous_decision", context_id=self._motor_context_id,
            native_cycle_id=sensed.cycle.cycle_id, active_trunks=sorted(str(t) for t in trunks),
            disposition="act" if intention else "no_motor_action", intention=intention,
            selection="native quiet pulse; bootstrap observed-target resolver; no foreground completion required")
        if intention:
            self.motor.submit_action(intention["action"], intention["arguments"]["path"],
                                     context_id=self._motor_context_id)

    def _execute_motor(self, signal, arguments):
        from core.native_motor import MotorSignal, MotorOpcode, ACTION
        if not isinstance(signal, MotorSignal) or not signal.context_id:
            raise ValueError("A typed, context-admitted motor signal is required")
        action = ACTION[MotorOpcode(signal.opcode)]
        result = self.body.execute(action, arguments)
        result.update(action=action, intent_source="native_motor_signal", motor_signal=asdict(signal),
                      arguments=arguments)
        tokens = self.learning.returned(result, self.body.last_action_eligibility)
        from core.mindscape_intention import observation_text
        receipt_id = result["receipt"]["receipt_id"]
        self.continuation.setdefault("motor_returns", []).append({
            "id": receipt_id, "content": observation_text(result), "consumed": False})
        self._remember_body_result(result)
        self._save_continuation()
        self._receipt("native_action_return", rwkv_return_tokens=tokens, **result)
        return result

    def has_subconscious_motor_impulse(self) -> bool:
        """Return True if the recurrent cortex or pending obligations register a motor requirement."""
        if getattr(self, "needs_native_observation", False):
            return True
        feeling = getattr(self, "last_sensed_feeling", None) or {}
        if feeling.get("modality") == "INTERNAL_ACTION_REQUIRED":
            return True
        sensed = getattr(getattr(self, "native", None), "latest_pulse", None)
        if sensed is not None:
            cycle = getattr(sensed, "cycle", None)
            selected_outputs = getattr(cycle, "selected_outputs", ()) or ()
            try:
                from habitus_ai.types import OutputTrunk
                if any(getattr(item, "trunk", None) in (OutputTrunk.DO, OutputTrunk.LOOK) for item in selected_outputs):
                    return True
            except Exception:
                pass
        return False

    def get_active_subconscious_trunks(self):
        sensed = getattr(getattr(self, "native", None), "latest_pulse", None)
        if sensed and hasattr(sensed, "cycle"):
            cycle = sensed.cycle
            selected_outputs = getattr(cycle, "selected_outputs", ()) or ()
            return {getattr(item, "trunk", None) for item in selected_outputs if getattr(item, "trunk", None) is not None}
        return set()

    def act(self, thought, pulse):
        """Process private intention or subconscious motor impulse."""
        return self._worker.submit(self._select_and_act, thought, pulse).result()

    def _select_and_act(self, thought, pulse):
        from core.mindscape_intention import (
            parse_natural_or_wire_intention,
            resolve_subconscious_action,
        )
        # Feed the completed output back before selecting, on the same owner
        # as native motor execution and gradient updates. It is not a target.
        self._admit_foreground(thought, pulse)
        if getattr(getattr(self, "motor", None), "pending", False) or getattr(self, "_receptive_pending", ()):
            self._receipt("autonomous_decision", helix_pulse=pulse, disposition="body_busy",
                          reason="existing native work retains its real return")
            return None
        intention = parse_natural_or_wire_intention(thought)
        intention_source = "foreground_intention" if intention is not None else "native_trunk"
        if intention is None and self.has_subconscious_motor_impulse():
            pending = self.continuation.get("pending", {})
            obligations = pending.get("obligations") or {}
            obs_list = list(pending.get("observations", []))
            obs_list.extend(self.continuation.get("body_observations", {}).values())
            if self.continuation.get("body_scene"):
                obs_list.append(self.continuation["body_scene"])
            current_pos = getattr(getattr(getattr(self, "body", None), "workspace", None), "position", ".")
            active_trunks = self.get_active_subconscious_trunks()
            intention = resolve_subconscious_action(
                obligations,
                obs_list,
                current_position=current_pos,
                thought=thought,
                active_trunks=active_trunks,
            )

        sensed = getattr(getattr(self, "native", None), "latest_pulse", None)
        cycle = getattr(sensed, "cycle", None)
        self._receipt("autonomous_decision", helix_pulse=pulse,
            native_cycle_id=getattr(cycle, "cycle_id", None),
            active_trunks=sorted(str(t) for t in self.get_active_subconscious_trunks()),
            disposition="act" if intention else "no_motor_action", intention=intention,
            intention_source=intention_source,
            selection="native selection with bootstrap target resolver; not a learned target decoder")
        if intention is None:
            return None
        self._receipt("autonomous_action_selected", helix_pulse=pulse, intention=intention,
            active_trunks=sorted(str(t) for t in self.get_active_subconscious_trunks()),
            selection="foreground intention or native trunk with actual observed targets; bootstrap target resolver")
        return self._act_intention(intention, thought, pulse)

    def _remember_body_result(self, result):
        """Derived latest-return index; complete history remains in native receipts."""
        receipt = result.get("receipt", {})
        if receipt.get("verified") is not True:
            return
        output = receipt.get("output") or {}
        if not isinstance(output, dict):
            output = {}
        action = result.get("action")
        path = output.get("path") or output.get("position") or receipt.get("arguments", {}).get("path")
        entry = {"id": receipt["receipt_id"], "action": action, "path": path,
                 "status": receipt.get("status"), "verified": True,
                 "output": output, "arguments": receipt.get("arguments", {})}
        observations = self.continuation.setdefault("body_observations", {})
        observations[json.dumps([action, path])] = entry

    def _act(self, thought, pulse):
        from core.mindscape_intention import parse_natural_or_wire_intention
        intention = parse_natural_or_wire_intention(thought)
        return self._act_intention(intention, thought, pulse)

    def _act_intention(self, intention, thought, pulse):
        self._last_native_action_pulse = pulse
        self.continuation.pop("interface_feedback", None)
        self._admit_foreground(thought, pulse)
        action = None
        try:
            if intention is None:
                raise ValueError("No valid intention to execute")
            action = intention["action"]
            result = self.body.execute(action, intention["arguments"])
        except (ValueError, RuntimeError, KeyError) as error:
            result = {"status": "not_completed", "error": str(error), "verified": False}
        result.update(action=action, helix_pulse=pulse, intent_source="subconscious_or_natural",
                      intention_sha256=hashlib.sha256(thought.encode()).hexdigest())
        receipt_id = result.get("receipt", {}).get("receipt_id") or f"native-attempt:{uuid.uuid4().hex}"
        tokens = self.learning.returned(result, getattr(self.body, "last_action_eligibility", None))
        self._remember_body_result(result)
        from core.mindscape_intention import observation_text
        observed_text = observation_text(result)
        self.continuation["return"] = {"id": receipt_id, "content": observed_text, "consumed": False}
        if self.continuation.get("pending"):
            self.continuation["pending"]["observed_native_attempt"] = True
            obs_item = {
                "id": receipt_id,
                "action": action,
                "path": intention.get("arguments", {}).get("path") if intention else None,
                "status": result.get("status") or result.get("receipt", {}).get("status"),
                "verified": bool(result.get("receipt", {}).get("verified")),
                "receipt": result.get("receipt", {}),
                "sha256": ((result.get("receipt", {}).get("output") or {}).get("sha256")
                           if isinstance(result.get("receipt", {}).get("output"), dict) else None),
                "content": observed_text,
            }
            self.continuation["pending"]["observations"].append(obs_item)
        self._save_continuation()
        self.last_sensed_feeling["is_external"] = False
        self.last_sensed_feeling["modality"] = "INTERNAL_ACTION_INTENTION"
        self._receipt("native_action_return", rwkv_return_tokens=tokens, **result)
        return result

    def _finish(self, thought, pulse, delivered_external=False, observed_motor_ids=None,
                private_continuation=None):
        self._admit_foreground(thought, pulse, delivered_external)
        if private_continuation is None:
            # Support native callers that supply a private-only pulse directly.
            private_continuation = self._load_private_continuation()
            if thought.strip().startswith("[thought]") and thought.strip()[len("[thought]"):].strip():
                private_continuation = ContextContribution(
                    "thinking", thought.strip()[len("[thought]"):].lstrip(), "foreground_private",
                    (f"helix-own-output:{self.session_id}:{pulse}",),
                    kind="thought", evidence="private thought, not external evidence", owner="agent")
        if private_continuation is not None:
            previous = self._load_private_continuation()
            saved = asdict(private_continuation)
            if previous != private_continuation and private_continuation.text != thought.removeprefix("[thought] "):
                self._admit_foreground(private_continuation.text, pulse, channel="private")
            self.continuation["private_thought"] = saved
        workspace = getattr(getattr(self, "body", None), "workspace", None)
        returned = self.continuation.get("return")
        for item in self.continuation.get("motor_returns", []):
            if item["id"] in (observed_motor_ids if observed_motor_ids is not None else getattr(self, "_observed_motor_ids", set())):
                item["consumed"] = True
        if returned and returned["id"] == self._observed_return_id:
            returned["consumed"] = True
            if hasattr(workspace, "consume_module"):
                released = workspace.consume_module(returned["id"])
                if released:
                    self._receipt("module_disengaged", reason="result consumed", **released)
        if delivered_external and hasattr(workspace, "disengage"):
            workspace.disengage()
        if delivered_external and not self.needs_native_observation:
            self.continuation.pop("pending", None)
        if private_continuation is not None and self.continuation.get("pending"):
            self.continuation["pending"].pop("thoughts", None)
        if self.needs_native_observation and not hasattr(self, "motor") and getattr(self, "_last_native_action_pulse", None) != pulse:
            from core.mindscape_intention import step_guidance_for_pending
            guidance = step_guidance_for_pending(
                self.continuation.get("pending", {}).get("obligations") or {},
                self.continuation.get("pending", {}).get("observations", []),
                current_position=self.body.workspace.position,
            )
            self.continuation["interface_feedback"] = (
                f"My previous foreground turn was prose; it dispatched no action. {guidance} "
                "To act, return one JSON object with action and arguments, without a message or imagined result. "
                "The controller's actual return will arrive in the next pulse.")
            self._receipt("outward_claim_withheld", helix_pulse=pulse,
                          reason="explicit workspace request has unfulfilled obligations", content_sha256=hashlib.sha256(thought.encode()).hexdigest())
        elif delivered_external:
            self.continuation.pop("interface_feedback", None)
        self._save_continuation()
        feeling = getattr(self, "last_sensed_feeling", None) or {}
        was_external_felt = feeling.get("is_external", False)
        has_outbound_tag = any(tag in thought for tag in ("[REPLY:", "[SPEAK:", "[MESSAGE:", "[response]"))
        is_external_response = bool(
            delivered_external
            or (was_external_felt and not str(thought).startswith(("[internal error:", "[no LLM session")))
            or (has_outbound_tag and delivered_external)
        )

        self._receipt("foreground_return", helix_pulse=pulse, thought=thought,
                      modality="external_response" if is_external_response else "internal_monologue",
                      sensed_modality=feeling.get("modality", "INTERNAL_MONOLOGUE"),
                      external_outcome_verified=bool(delivered_external))
        self._checkpoint(f"helix-pulse-{pulse}")
        return {"is_external_response": is_external_response,
                "modality": "external_response" if is_external_response else "internal_monologue"}

    def _checkpoint(self, label):
        manifest = self.native.save(label=label)
        self._receipt("joint_checkpoint", label=label, generation=manifest["generation"],
                      numeric_state_sha256=manifest["numeric_state_sha256"], files=manifest["files"])
        return manifest

    def _release(self):
        if self.loom is not None:
            self.loom.close()
            self.loom = None
        if self.native is not None:
            self._checkpoint("helix-shutdown")
            self.native.close()
            self.native = None

    def close(self):
        if not self._closed:
            self.stop_motor()
            self._intake.shutdown(wait=True)
            self._closed = True
            try:
                self._worker.submit(self._release).result()
            finally:
                self._worker.shutdown(wait=True)
                self._owner.close()
