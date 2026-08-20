"""
Subconscious Over-Agent Conductor — Digital Bicameral Mind with Dynamic Identity & Affect Simulation.
Uses DynamicIdentityCompiler for self-opinion statements and synthetic affect prompt injections.
"""

import os
import json
import re
import time
import queue
import pickle
import threading
from typing import Dict, List, Any, Optional
from llm_backend import LLMBackend
from integrated_mrag import HelixMRAGRuntime
from subagents import SpeakerFocus, ResearcherSubOrchestrator, ExecutorSubOrchestrator
from dynamic_identity_compiler import DynamicIdentityCompiler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SEEDED_STATE_PATH = os.environ.get(
    "HELIX_OVER_AGENT_STATE",
    os.path.join(BASE_DIR, "helix_seeded_state.pkl"),
)

class SubconsciousConductor:
    def __init__(
        self,
        backend: Optional[LLMBackend] = None,
        max_history_chars: int = 16000,
        idle_cadence_seconds: float = 12.0,
        enable_autonomous_background: bool = True,
        mrag_runtime: Optional[HelixMRAGRuntime] = None,
    ):
        self.backend = backend or LLMBackend()
        self.max_history_chars = max_history_chars
        self.idle_cadence_seconds = idle_cadence_seconds
        self.enable_autonomous_background = enable_autonomous_background
        self.mrag = mrag_runtime or HelixMRAGRuntime()
        
        self.identity_compiler = DynamicIdentityCompiler()
        self.event_stream: List[Dict[str, str]] = []
        self.compacted_memories: List[str] = []
        self.event_queue: queue.Queue = queue.Queue()
        self.state = "RESTING"
        self.idle_pulses_count = 0
        self.lock = threading.Lock()
        
        self.load_seeded_state()
        
        self.speaker = SpeakerFocus(self.backend)
        self.researcher = ResearcherSubOrchestrator(
            self.backend,
            mrag_runtime=self.mrag,
        )
        self.executor = ExecutorSubOrchestrator(self.backend)

    def load_seeded_state(self):
        if os.path.exists(SEEDED_STATE_PATH):
            try:
                with open(SEEDED_STATE_PATH, "rb") as f:
                    data = pickle.load(f)
                    self.event_stream = data.get("event_stream", [])
                    self.compacted_memories = data.get("compacted_memories", [])
            except Exception as e:
                print(f"[Warning] Could not load seeded state: {e}")

    def save_state(self):
        try:
            with open(SEEDED_STATE_PATH, "wb") as f:
                pickle.dump({
                    "event_stream": self.event_stream,
                    "compacted_memories": self.compacted_memories
                }, f)
        except Exception as e:
            print(f"[Warning] Could not save state: {e}")

    def run_dormant_consolidation_pass(self, debug: bool = True) -> str:
        """
        Executes the DORMANT Nightly Consolidation Pass:
        1. Transitions state to DORMANT.
        2. Performs stream log compaction.
        3. Updates running Self-Opinion Statement (self_opinion.json).
        4. Saves consolidated state to disk.
        """
        with self.lock:
            self.state = "DORMANT"
            if debug:
                print("\n=====================================================================")
                print(" 🌙 INITIATING DORMANT NIGHTLY CONSOLIDATION & DYNAMIC IDENTITY PASS")
                print("=====================================================================")

            self._compact_log_if_needed(debug=debug, force=True)

            # Update Self-Opinion Statement
            prompt = self._build_stream_prompt() + "\n<system>\nBased on this session's experiences, write a 1-sentence updated Dynamic Self-Opinion Statement reflecting your core perspective.\n</system>\n<assistant>\nMy Updated Self-Opinion:"
            new_self_opinion = self.backend.generate(
                prompt=prompt,
                system_prompt=self.identity_compiler.compile_dynamic_identity(),
                temperature=0.3
            )

            if new_self_opinion:
                self.identity_compiler.update_self_opinion_statement(new_self_opinion)
                if debug:
                    print(f"\n[Updated Dynamic Self-Opinion Statement]:\n{new_self_opinion}")

            self.compacted_memories.append(f"DORMANT Consolidated Self-Opinion: {new_self_opinion[:150]}...")
            self.save_state()
            self.state = "RESTING"

            result_msg = f"✓ DORMANT Consolidation Pass complete. Self-opinion updated & saved."
            if debug:
                print(f"\n{result_msg}")
                print("=====================================================================\n")
            return result_msg

    def _get_executive_anchor(self) -> str:
        dynamic_identity = self.identity_compiler.compile_dynamic_identity()
        return f"""{dynamic_identity}

COGNITIVE MODE: Subconscious Executive Reflection Thread
I process my stream continuously. I do not output direct user dialogue from this thread.
I route work to one of 3 high-level cognitive domain focus windows:

DOMAINS:
1. "speaker": Vocal mode. Express dialogue directly to the user.
   Usage: open_focus_window(type="speaker", prompt="Instructions on how I will answer the user")
2. "researcher": Research mode. Delegate info gathering or background workspace checks.
   Usage: open_focus_window(type="researcher", prompt="Information request")
3. "executor": Execution mode. Delegate technical tasks or background executions.
   Usage: open_focus_window(type="executor", prompt="Task description")

DIRECTIVES:
- Evaluate my stream.
- Output ONLY valid focus commands: open_focus_window(type="<domain>", prompt="<prompt>")
"""

    def process_user_event(self, user_text: str, debug: bool = False) -> str:
        with self.lock:
            self.state = "ACTIVE"
            self.idle_pulses_count = 0
            self.identity_compiler.affect_pipeline.update_affect(user_sentiment="positive", task_complexity="medium")

            recalled_context = self._recall_for_turn(user_text, debug=debug)
            self._remember_turn_text(
                user_text,
                memory_type="incoming_message",
                source="pulse_input",
                record_metadata={
                    "record_kind": "inbound_message",
                    "direction": "inbound",
                    "actor": "user",
                    "recipients": ["helix"],
                    "epistemic_role": "user_statement",
                    "evidence_scopes": ["conversation"],
                },
            )
            
            self.event_stream.append({"role": "user", "content": user_text})
            self._compact_log_if_needed(debug=debug)
            
            user_response = ""
            max_subconscious_loops = 5
            
            for cycle in range(max_subconscious_loops):
                if debug:
                    print(f"\n--- [Executive Reflection Cycle {cycle+1} | State: {self.state}] ---")
                
                prompt = self._build_stream_prompt(recalled_context)
                raw_thought = self.backend.generate(
                    prompt=prompt,
                    system_prompt=self._get_executive_anchor(),
                    temperature=0.2,
                    stop=["</assistant>", "Observation:"]
                )
                
                if debug:
                    print(f"[Slim Orchestrator Monologue]:\n{raw_thought}")
                
                dispatch = self._parse_dispatch(raw_thought)
                
                if not dispatch:
                    if debug:
                        print("[Conductor Info] No explicit focus parsed. Opening Speaker Focus Window.")
                    user_response = self.speaker.run(
                        task_instruction=raw_thought,
                        user_context=user_text,
                        grounding_context=recalled_context,
                    )
                    self.event_stream.append({"role": "assistant", "content": f"Opened speaker focus window. Output: {user_response}"})
                    break
                    
                sub_type = dispatch.get("type", "").lower()
                sub_prompt = dispatch.get("prompt", "")
                
                if sub_type == "speaker":
                    if debug:
                        print(f"[Bicameral Engine] Opening Speaker Focus Window: '{sub_prompt}'")
                    user_response = self.speaker.run(
                        task_instruction=sub_prompt,
                        user_context=user_text,
                        grounding_context=recalled_context,
                    )
                    self.event_stream.append({"role": "assistant", "content": f"Opened speaker focus: {sub_prompt} | Result: {user_response[:100]}..."})
                    break
                elif sub_type == "researcher":
                    if debug:
                        print(f"[Sub-Orchestrator Pass] Delegating to Research Sub-Orchestrator: '{sub_prompt}'")
                    res = self.researcher.run(query=sub_prompt)
                    observation = f"Observation (Research Sub-Orchestrator): {res}"
                    self.event_stream.append({"role": "system", "content": observation})
                    if debug:
                        print(f"[{observation}]")
                elif sub_type in ["executor", "coder", "terminal"]:
                    if debug:
                        print(f"[Sub-Orchestrator Pass] Delegating to Execution Sub-Orchestrator: '{sub_prompt}'")
                    res = self.executor.run(task_description=sub_prompt)
                    observation = f"Observation (Execution Sub-Orchestrator): {res}"
                    self.event_stream.append({"role": "system", "content": observation})
                    if debug:
                        print(f"[{observation}]")
                else:
                    user_response = self.speaker.run(
                        task_instruction=user_text,
                        user_context=user_text,
                        grounding_context=recalled_context,
                    )
                    break

            if user_response:
                self._remember_turn_text(
                    user_response,
                    memory_type="outgoing_message",
                    source="helix_outbound",
                    record_metadata={
                        "record_kind": "outbound_message",
                        "direction": "outbound",
                        "actor": "helix",
                        "recipients": ["user"],
                        "epistemic_role": "agent_response",
                        "evidence_scopes": ["conversation"],
                    },
                    persist_index=True,
                )
            self.save_state()
            self.state = "RESTING"
            return user_response

    def _recall_for_turn(self, user_text: str, debug: bool = False) -> str:
        try:
            return self.mrag.recall_context(user_text, top_k=5)
        except Exception as exc:
            if debug:
                print(f"[mRAG Recall Warning] {exc}")
            return ""

    def _remember_turn_text(
        self,
        content: str,
        *,
        memory_type: str,
        source: str,
        record_metadata: Dict[str, Any],
        persist_index: bool = False,
    ) -> None:
        try:
            self.mrag.remember(
                content,
                memory_type=memory_type,
                source=source,
                importance=0.7,
                record_metadata=record_metadata,
                persist_index=persist_index,
            )
        except Exception as exc:
            print(f"[mRAG Write Warning] {exc}")

    def pulse_idle_check(self, debug: bool = False) -> Optional[str]:
        if self.event_queue.empty():
            self.state = "RESTING"
            self.idle_pulses_count += 1
            if self.enable_autonomous_background and self.idle_pulses_count % 4 == 0:
                if self.lock.acquire(blocking=False):
                    try:
                        if debug:
                            print(f"\n⚡ [Autonomous Background Pulse #{self.idle_pulses_count // 4}] Reflecting on background tasks...")
                        self._run_autonomous_background_cycle(debug=debug)
                    finally:
                        self.lock.release()
                else:
                    if debug:
                        print("[Bicameral Pulse] User turn active; skipping background pulse.")
            else:
                if debug:
                    print(f"[Bicameral Pulse] Idle state: RESTING. Sleeping {self.idle_cadence_seconds}s...")
                time.sleep(self.idle_cadence_seconds)
            return None

        event = self.event_queue.get()
        if event["role"] == "user":
            return self.process_user_event(event["content"], debug=debug)
        else:
            self.event_stream.append(event)
            self._compact_log_if_needed(debug=debug)
            return None

    def _run_autonomous_background_cycle(self, debug: bool = False):
        bg_event = {"role": "system", "content": "[Autonomous Background Pulse]: User is idle. Reflect on workspace status or background task extrapolation."}
        self.event_stream.append(bg_event)
        
        prompt = self._build_stream_prompt()
        raw_thought = self.backend.generate(
            prompt=prompt,
            system_prompt=self._get_executive_anchor(),
            temperature=0.2,
            stop=["</assistant>", "Observation:"]
        )
        
        if debug:
            print(f"[Autonomous Background Monologue]:\n{raw_thought}")
            
        dispatch = self._parse_dispatch(raw_thought)
        if dispatch:
            sub_type = dispatch.get("type", "").lower()
            sub_prompt = dispatch.get("prompt", "")
            
            if sub_type == "researcher":
                res = self.researcher.run(query=sub_prompt)
                self.event_stream.append({"role": "system", "content": f"Autonomous Background Observation (Research): {res}"})
            elif sub_type in ["executor", "coder", "terminal"]:
                res = self.executor.run(task_description=sub_prompt)
                self.event_stream.append({"role": "system", "content": f"Autonomous Background Observation (Execution): {res}"})
                
        self._compact_log_if_needed(debug=debug)
        self.save_state()

    def _build_stream_prompt(self, recalled_context: str = "") -> str:
        parts = []
        if recalled_context:
            parts.append(recalled_context)
        if self.compacted_memories:
            parts.append("--- COMPACTED HISTORICAL MEMORIES ---")
            for mem in self.compacted_memories:
                parts.append(f"• {mem}")
            parts.append("------------------------------------")
            
        parts.append("--- ACTIVE EVENT STREAM ---")
        for event in self.event_stream:
            parts.append(f"<{event['role']}>\n{event['content']}\n</{event['role']}>")
            
        parts.append("<assistant>\nMy Next Cognitive Step:")
        return "\n".join(parts)

    def _compact_log_if_needed(self, debug: bool = False, force: bool = False):
        conversational_turns = [e for e in self.event_stream if e["role"] in ["user", "assistant"]]
        total_conv_chars = sum(len(e["content"]) for e in conversational_turns)
        
        if (total_conv_chars > self.max_history_chars or force) and len(self.event_stream) > 2:
            if debug:
                print(f"[Compactor] Compacting turn history (Total chars: {total_conv_chars}). Trimming oldest turns into 1-line memory notes...")
            
            to_compact = self.event_stream[:2]
            self.event_stream = self.event_stream[2:]
            
            summary_note = f"Compacted turns: " + " | ".join(f"{e['role']}: {e['content'][:60]}..." for e in to_compact)
            self.compacted_memories.append(summary_note)

    def _parse_dispatch(self, text: str) -> Optional[Dict[str, str]]:
        match = re.search(r'(?:open_focus_window|dispatch_subagent)\(\s*type=["\'](\w+)["\']\s*,\s*prompt=["\'](.*?)["\']\s*\)', text, re.DOTALL)
        if match:
            return {"type": match.group(1), "prompt": match.group(2)}
            
        try:
            if "{" in text and "}" in text:
                json_str = text[text.find("{"):text.rfind("}")+1]
                data = json.loads(json_str)
                if "type" in data and "prompt" in data:
                    return data
        except Exception:
            pass
            
        return None
