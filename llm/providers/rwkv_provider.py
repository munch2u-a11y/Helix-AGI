"""Bicameral RWKV-7 Chat Session Provider."""
from __future__ import annotations

import json
import hashlib
import time
from llm.rwkv_tokens import RWKVTokenCounter
import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from core.bicameral_rwkv import BicameralRWKV
from llm.providers.base import ChatSession

logger = logging.getLogger("helix.llm.providers.rwkv")


class BicameralRWKVSession(ChatSession):
    def __init__(
        self,
        model_path: str,
        system_instruction: str = "",
        temperature: float = 0.7,
        max_output_tokens: int | None = None,
        backend=None,
        options: Optional[Dict[str, Any]] = None,
    ):
        self.model_path = Path(model_path) if model_path else None
        self.model = str(self.model_path)
        self.system_instruction = system_instruction
        self.temperature = temperature
        self.max_output_tokens = max_output_tokens
        self.options = options or {}
        self.compiled_context_only = False
        self.history: List[Dict[str, str]] = []

        # Instantiate or bind BicameralRWKV
        self.system = BicameralRWKV(
            model_path=self.model_path,
            device="cpu",
            backend=backend,
        )
        self.context_format = None
        self.context_decoder = None
        model_str = str(self.model_path) if self.model_path else "."
        native_stream = getattr(self.system.backend, 'native_stream', False) is True
        self.context_counter = RWKVTokenCounter(self.system.backend.encode, model_str,
                                               thinking=True if native_stream else None)
        self.last_context_receipt = {}
        self.last_context_output_kind = None
        self.last_contemplation = ""
        self._pending_context_response = None

    def _generate(self, message, role="context"):
        self.last_context_receipt = {}
        self.last_contemplation = ""
        self.last_context_output_kind = None
        native_stream = getattr(self.system.backend, "native_stream", False) is True
        if hasattr(self.system.backend, "begin_generation"):
            self.system.backend.begin_generation()
        messages = self.context_messages(message, role=role)
        receipt = self.context_counter.check_request(messages, int(self.options.get('input_context_tokens', 8192)))
        prompt = self.context_counter.render_messages(messages)
        receipt.update(model=self.model, device=str(self.system.device),
                       prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(), started_at=time.time())
        sensory = self.options.pop('current_sensory_items', [])
        for item in sensory:
            self.system.sensory_observe(item['text'])
        receipt['sensory_admissions'] = sensory
        self.last_contemplation = ''
        self.last_context_output_kind = None
        progress_path = self.options.get('generation_progress_path')
        if progress_path:
            def progress(value):
                from core.mindscape_config import write_json
                native_learning = (self.system.backend.generation_receipt()
                                   if hasattr(self.system.backend, 'generation_receipt') else None)
                write_json(Path(progress_path), {**value, 'time': time.time(), 'status': 'incomplete',
                                                'prompt_sha256': receipt['prompt_sha256'],
                                                'started_at': receipt['started_at'], 'model': self.model,
                                                'output_token_cap': self.max_output_tokens,
                                                'native_learning': native_learning})
            self.system.generation_progress = progress
        raw = self.system.generate_language(
            prompt, max_new_tokens=self.max_output_tokens, temperature=self.temperature,
            coupling_gain=float(self.options.get('coupling_gain', 0.15)),
            membrane_state=self.options.get('membrane_state'),
            membrane_gain=float(self.options.get('membrane_gain', 0.0)),
            repetition_penalty=float(self.options.get('repetition_penalty', 1.25)),
            repetition_window=int(self.options.get('repetition_window', 512)),
            on_boundary='raise' if native_stream else self.options.get('on_boundary', 'stop'),
            stop_sequences=self.options.get(
                'stop_sequences',
                ("<|endoftext|>", "<|im_end|>", "\nUser:") if native_stream else (
                    "<|endoftext|>",
                    "<|im_end|>",
                    "\nUser:",
                    "\n\n[",
                    "\n[Pulse",
                    "\n[MODE:",
                    "\n\n###",
                    "\n###",
                    "\n---\n",
                    "\n## ",
                    "\n# ",
                    "\n\n# ",
                ),
            ),
        )

        generation = dict(getattr(self.system, 'last_generation_receipt', {}) or {})
        if 'prompt_tokens' not in generation:
            raise RuntimeError('RWKV returned without actual generation accounting; no receipt can be inferred')
        elif generation['prompt_tokens'] != receipt['prompt_tokens']:
            raise RuntimeError('RWKV request accounting differs from evaluated input')
        from core.mindscape_intention import extract_contemplation_and_actualization
        generated_raw = raw
        assistant_prefill = '<think' if prompt.endswith('Assistant: <think') else ''
        raw = assistant_prefill + raw
        contemplation, actualized = extract_contemplation_and_actualization(raw)
        self.last_contemplation = contemplation
        receipt.update(generation, raw_generated=generated_raw, assistant_prefill=assistant_prefill,
                       raw_foreground=raw, contemplation=contemplation,
                       completed_at=time.time(), evaluated_prompt_tokens=generation['prompt_tokens'])
        self._last_token_count = receipt['prompt_tokens'] + receipt['generated_tokens']
        self.last_context_receipt = receipt
        if hasattr(self.system.backend, "generation_receipt"):
            receipt["native_learning"] = self.system.backend.generation_receipt()
        if progress_path:
            from core.mindscape_config import write_json
            write_json(Path(progress_path), {**receipt, 'status': 'complete'})
        return raw, actualized

    def send_message(self, message):
        raw, actualized = self._generate(message, role="user")
        if not actualized:
            raise RuntimeError('RWKV produced only private contemplation; no public reply completed')
        self.history.extend([{'role': 'user', 'content': message}, {'role': 'assistant', 'content': actualized}])
        return actualized

    def send_context(self, message):
        raw, actualized = self._generate(message, role="context")
        if self.context_decoder:
            thought, kind = self.context_decoder(raw)
            if kind in {'contemplation', 'empty'}:
                thought = '[thought] ' + self.last_contemplation
            self.last_context_output_kind = kind
        else:
            thought = actualized or ('[thought] ' + self.last_contemplation)
        self.last_context_receipt['output_kind'] = self.last_context_output_kind
        self._pending_context_response = thought
        return thought

    def finish_context(self, current_messages: List[str], response: str, *, delivered: bool) -> None:
        if response != self._pending_context_response:
            raise ValueError("No matching completed RWKV response to commit")
        self.history.extend({"role": "user", "content": msg} for msg in current_messages)
        if delivered:
            self.history.append({"role": "assistant", "content": response})
        self._pending_context_response = None

    def pulse_input_allowance(self) -> int:
        remaining = int(self.options.get("input_context_tokens", 8192)) - self.context_counter.count_messages(self.context_messages(""))
        if remaining <= 0:
            raise RuntimeError("Configured RWKV input allowance exhausted; no history was clipped")
        return remaining

    def covered_source_hashes(self) -> set:
        import hashlib
        if self.compiled_context_only:
            return set()
        return {hashlib.sha256(item["content"].encode()).hexdigest() for item in self.history}

    def get_history_size(self) -> int:
        return sum(len(item.get("content", "")) for item in self.history)

    def context_messages(self, message, role="context"):
        history = [] if self.compiled_context_only else self.history
        return ([{'role': 'system', 'content': self.system_instruction}]
                + [dict(item) for item in history]
                + ([{'role': role, 'content': message}] if message else []))

    def _build_prompt(self, current_message, role="context"):
        return self.context_counter.render_messages(self.context_messages(current_message, role=role))

    def get_last_token_count(self):
        return getattr(self, '_last_token_count', 0)

    def get_history(self):
        return [dict(item) for item in self.history]

    def close(self):
        self.system = None

    def cancel_pending(self):
        self.system.cancel_event.set()
