"""Bicameral Unified-Stream Multi-RWKV System.

Couples an embodied sensory-motor stream and a cognitive-language stream
sharing a single frozen RWKV-7 neural foundation, utilizing an internal
manifold Translator Bridge (Corpus Callosum) for continuous non-linguistic
sensory guidance and cognitive motor feedback.
"""
from __future__ import annotations

import sys
from pathlib import Path
import numpy as np
import threading

# Use the configured source contract; never introduce a competing host path.
from core.mindscape_config import activate_native_source, selected_native_source
activate_native_source(selected_native_source())

from habitus_ai.rwkv7_language import Rwkv7Backend

_BACKEND_CACHE: dict[tuple[str, str], Any] = {}
_BACKEND_CACHE_LOCK = threading.RLock()


def clear_rwkv_backend_cache():
    """Clear cached RWKV backends to release memory."""
    with _BACKEND_CACHE_LOCK:
        _BACKEND_CACHE.clear()


class GenericRwkv7Backend:
    """Dynamic HuggingFace/Safetensors backend for arbitrary RWKV-7 checkpoints (e.g. 2.9B)."""

    def __init__(self, directory: Path | str, device: str = "cpu"):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.device = device
        self.torch = torch
        resolved_str = str(Path(directory).resolve())
        self.model = AutoModelForCausalLM.from_pretrained(
            resolved_str, dtype=torch.bfloat16, trust_remote_code=True
        ).to(device)
        self.tokenizer = AutoTokenizer.from_pretrained(resolved_str, trust_remote_code=True)
        self.embedding_dimension = self.model.config.hidden_size
        self.eos_token_id = getattr(self.tokenizer, "eos_token_id", 0)

    def encode(self, text: str) -> list[int]:
        return self.tokenizer.encode(text)

    def decode(self, token_ids: list[int]) -> str:
        return self.tokenizer.decode(token_ids)


def get_shared_rwkv_backend(model_path: str | Path, device: str = "cpu"):
    """Get or create a cached frozen Rwkv7Backend shared across sessions."""
    resolved_path = str(Path(model_path).resolve())
    key = (resolved_path, device)
    with _BACKEND_CACHE_LOCK:
        if key not in _BACKEND_CACHE:
            try:
                _BACKEND_CACHE[key] = Rwkv7Backend(Path(resolved_path), device=device)
            except (ValueError, FileNotFoundError):
                _BACKEND_CACHE[key] = GenericRwkv7Backend(resolved_path, device=device)
        return _BACKEND_CACHE[key]



class BicameralTranslatorBridge:
    """Manifold Translator Bridge connecting Sensory and Language representation spaces.

    Acts as an internal neural Corpus Callosum: translates raw sensory-motor topologies
    into semantic continuous guidance fields, and translates cognitive attention back
    into sensory-motor readiness.
    """

    def __init__(self, dimension: int, torch_module, device):
        self.dimension = dimension
        self.torch = torch_module
        self.device = device

        # Structured linear orthogonal projection seeds for cross-manifold alignment
        # (Preserves continuous topology while mapping across functional coordinate frames)
        rng = np.random.RandomState(42)
        q_s2l, _ = np.linalg.qr(rng.randn(dimension, dimension))
        q_l2s, _ = np.linalg.qr(rng.randn(dimension, dimension))

        self.w_sensory_to_lang = self.torch.tensor(
            q_s2l, device=self.device, dtype=self.torch.float32
        )
        self.w_lang_to_sensory = self.torch.tensor(
            q_l2s, device=self.device, dtype=self.torch.float32
        )

    def translate_sensory_to_language(self, sensory_vector: np.ndarray) -> np.ndarray:
        """Translates a raw sensory state manifold vector into a language guidance vector."""
        with self.torch.no_grad():
            s = self.torch.tensor(sensory_vector, device=self.device, dtype=self.torch.float32)
            s_norm = s / s.norm().clamp_min(1.0)
            # Projected translation
            translated = self.torch.matmul(s_norm, self.w_sensory_to_lang)
            translated = translated / translated.norm().clamp_min(1.0)
            return translated.cpu().numpy()

    def translate_language_to_sensory(self, language_vector: np.ndarray) -> np.ndarray:
        """Translates cognitive attention into a sensory-motor feedback vector."""
        with self.torch.no_grad():
            l = self.torch.tensor(language_vector, device=self.device, dtype=self.torch.float32)
            l_norm = l / l.norm().clamp_min(1.0)
            translated = self.torch.matmul(l_norm, self.w_lang_to_sensory)
            translated = translated / translated.norm().clamp_min(1.0)
            return translated.cpu().numpy()


class BicameralRWKV:
    """Manages two recurrent state tensors (Sensory and Language) over a shared RWKV-7 model."""

    def __init__(self, model_path: Path | None = None, device: str = "cpu", backend=None):
        self.model_path = Path(model_path).resolve() if model_path else None
        self.device_name = device
        self.cancel_event = threading.Event()
        self.generation_progress = None
        # Initialize frozen pretrained RWKV-7 backend or reuse existing
        if backend is not None:
            self.backend = backend
        else:
            if not self.model_path:
                raise ValueError("model_path is required when backend is not provided")
            self.backend = get_shared_rwkv_backend(self.model_path, device=device)
        self.torch = self.backend.torch
        self.device = self.backend.device
        self.model = self.backend.model
        self.tokenizer = self.backend.tokenizer
        self.hidden_size = self.backend.embedding_dimension

        # Instantiate the Translator Bridge
        self.native_stream = getattr(self.backend, 'native_stream', False) is True
        self.bridge = (None if self.native_stream else
                       BicameralTranslatorBridge(self.hidden_size, self.torch, self.device))

        # Instantiate Vocabulary Membrane
        from core.vocabulary_membrane import VocabularyMembrane
        self.membrane = VocabularyMembrane(self.backend, self.hidden_size, self.device)

        # Allocate separate recurrent states
        self.sensory_state = None
        self.language_state = None
        self.reset_states()

    def reset_states(self):
        """Reallocates pristine zero-state recurrent tensors for both streams."""
        with self.torch.no_grad():
            self.sensory_state = self.model.rwkv7.allocate_state(1, self.device, self.torch.bfloat16)
            self.language_state = self.model.rwkv7.allocate_state(1, self.device, self.torch.bfloat16)

    def _forward_model(self, **kwargs):
        if hasattr(self.backend, "forward_branch"):
            return self.backend.forward_branch(**kwargs)
        return self.model(**kwargs)

    def sensory_observe(self, text: str) -> None:
        """Processes continuous sensory or environmental observations into the sensory state."""
        ids = self.backend.encode(text)
        if not ids:
            return
        with self.torch.inference_mode():
            result = self._forward_model(
                input_ids=self.torch.tensor([ids], device=self.device),
                state=self.sensory_state,
                use_cache=True,
                logits_to_keep=1
            )
            self.sensory_state = result.state

    def get_sensory_state_vector(self) -> np.ndarray:
        """Extracts the top-layer recurrent attention vector representing the sensory manifold."""
        with self.torch.no_grad():
            attention, _, _ = self.sensory_state.read(len(self.sensory_state.layers) - 1)
            return attention[0].detach().float().cpu().numpy()

    def get_language_state_vector(self) -> np.ndarray:
        """Extracts the top-layer recurrent attention vector representing cognitive state."""
        with self.torch.no_grad():
            attention, _, _ = self.language_state.read(len(self.language_state.layers) - 1)
            return attention[0].detach().float().cpu().numpy()

    def step_language(self, prompt: str, coupling_gain: float = 0.0) -> np.ndarray:
        """Steps the language model on prompt, optionally modulated by translated sensory state."""
        ids = self.backend.encode(prompt)
        if not ids:
            raise ValueError("Prompt cannot be empty")

        with self.torch.inference_mode():
            if coupling_gain <= 0.0 or getattr(self, 'native_stream', False):
                result = self._forward_model(
                    input_ids=self.torch.tensor([ids], device=self.device),
                    state=self.language_state,
                    use_cache=True,
                    logits_to_keep=1
                )
            else:
                # Embed the input token sequence
                token_tensor = self.torch.tensor([ids], device=self.device)
                embeds = self.model.rwkv7.emb(token_tensor).float()

                # Extract sensory continuous vector and translate via Translator Bridge
                raw_sensory = self.get_sensory_state_vector()
                translated_guidance = self.bridge.translate_sensory_to_language(raw_sensory)
                guidance_tensor = self.torch.tensor(
                    translated_guidance, device=self.device, dtype=self.torch.float32
                )

                # Inject translated sensory residual perturbation without any text
                gain = float(coupling_gain)
                norm_embeds = embeds.norm(dim=-1, keepdim=True)
                embeds = (embeds + gain * norm_embeds * guidance_tensor).to(self.model.rwkv7.emb.weight.dtype)

                result = self._forward_model(
                    inputs_embeds=embeds,
                    state=self.language_state,
                    use_cache=True,
                    logits_to_keep=1
                )

            self.language_state = result.state
            logits = result.logits[0, -1].detach().float().cpu().numpy()
            return logits

    def _apply_repetition_penalty(
        self,
        logits: np.ndarray,
        generated_ids: list[int],
        repetition_penalty: float = 1.15,
        repetition_window: int = 128,
    ) -> np.ndarray:
        """Progressively penalizes repeated tokens in proportion to frequency within repetition window."""
        if repetition_penalty == 1.0 or not generated_ids:
            return logits

        effective_logits = logits.copy()
        from collections import Counter
        window = generated_ids[-repetition_window:]
        counts = Counter(window)
        for token_id, count in counts.items():
            if token_id >= len(effective_logits):
                continue
            penalty = repetition_penalty ** count
            if effective_logits[token_id] > 0:
                effective_logits[token_id] /= penalty
            else:
                effective_logits[token_id] *= penalty
        return effective_logits

    @staticmethod
    def _detect_repetition_loop(
        generated_ids: list[int],
        min_cycle: int = 1,
        max_cycle: int = 128,
    ) -> bool:
        """Detects whether recent generated tokens are trapped in a repeating cycle."""
        n = len(generated_ids)
        for cycle_len in range(min_cycle, min(max_cycle + 1, n // 2 + 1)):
            required_repeats = 4 if cycle_len == 1 else (2 if cycle_len >= 32 else 3)
            if n < cycle_len * required_repeats:
                continue
            target = generated_ids[-cycle_len:]
            repeats = 1
            idx = n - cycle_len
            while idx >= cycle_len and generated_ids[idx - cycle_len:idx] == target:
                repeats += 1
                idx -= cycle_len
                if repeats >= required_repeats:
                    return True
        return False

    def generate_language(
        self,
        prompt: str,
        max_new_tokens: int | None = None,
        temperature: float = 0.7,
        top_p: float = 0.85,
        coupling_gain: float = 0.15,
        membrane_state: str | np.ndarray | None = None,
        membrane_gain: float = 0.0,
        repetition_penalty: float = 1.25,
        repetition_window: int = 512,
        stop_sequences: tuple[str, ...] = (
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
        reset_state: bool = True,
        on_boundary: str = "raise",
    ) -> str:
        """Autoregressively generate language tokens, steered by sensory continuous state and vocabulary membrane."""
        if reset_state:
            self.language_state = None
        logits = self.step_language(prompt, coupling_gain=coupling_gain)
        generated_ids: list[int] = []
        eos_id = getattr(self.backend, "eos_token_id", 0)

        # Precompute vocabulary membrane logit bias if enabled
        membrane_bias = None
        if membrane_gain > 0.0 and membrane_state is not None:
            if isinstance(membrane_state, str):
                s_vec = self.membrane.get_somatic_anchor(membrane_state)
            else:
                s_vec = membrane_state
            membrane_bias = self.membrane.compute_logit_bias(s_vec)

        stopped = False
        text_so_far = ""

        self.last_generation_receipt = {'prompt_tokens': len(self.backend.encode(prompt)),
                                        'output_token_cap': max_new_tokens,
                                        'stop_sequences': list(stop_sequences),
                                        'on_boundary': on_boundary,
                                        'decoding': {'temperature': temperature, 'top_p': top_p,
                                                     'repetition_penalty': repetition_penalty,
                                                     'repetition_window': repetition_window},
                                        'sensory_coupling': ('native learned Habitus cortex/interface field' if getattr(self, 'native_stream', False)
                                                            else 'bootstrap bicameral projections'),
                                        'extra_projection_gain': 0.0 if getattr(self, 'native_stream', False) else coupling_gain}
        while True:
            if self.cancel_event.is_set():
                self.last_generation_receipt.update(done_reason='cancelled', generated_tokens=len(generated_ids))
                raise RuntimeError('RWKV generation cancelled; unfinished output withheld')
            if max_new_tokens is not None and len(generated_ids) >= max_new_tokens:
                self.last_generation_receipt.update(done_reason='configured_output_boundary', generated_tokens=len(generated_ids))
                if on_boundary == 'raise':
                    raise RuntimeError('RWKV reached the configured output boundary; incomplete generation withheld')
                else:
                    stopped = True
                    break

            effective_logits = logits.copy()
            if membrane_bias is not None:
                effective_logits = effective_logits + float(membrane_gain) * membrane_bias

            effective_logits = self._apply_repetition_penalty(
                effective_logits, generated_ids, repetition_penalty=repetition_penalty, repetition_window=repetition_window
            )

            if temperature <= 0.0:
                next_id = int(np.argmax(effective_logits))
            else:
                scaled = effective_logits / max(temperature, 1e-5)
                scaled -= np.max(scaled)
                probs = np.exp(scaled) / np.sum(np.exp(scaled))
                if top_p < 1.0:
                    sorted_indices = np.argsort(probs)[::-1]
                    sorted_probs = probs[sorted_indices]
                    cumulative_probs = np.cumsum(sorted_probs)
                    cutoff_index = int(np.searchsorted(cumulative_probs, top_p))
                    candidates = sorted_indices[:max(1, cutoff_index + 1)]
                    c_probs = probs[candidates]
                    c_probs /= np.sum(c_probs)
                    next_id = int(np.random.choice(candidates, p=c_probs))
                else:
                    next_id = int(np.random.choice(len(probs), p=probs))

            if next_id == eos_id:
                self.last_generation_receipt['done_reason'] = 'eos'
                break
            generated_ids.append(next_id)

            # Check for repetition loops
            if self._detect_repetition_loop(generated_ids):
                self.last_generation_receipt['done_reason'] = 'repetition_loop_detected'
                if getattr(self.backend, 'native_stream', False) is True:
                    self.last_generation_receipt['generated_tokens'] = len(generated_ids)
                    raise RuntimeError('Native RWKV repeated a generation cycle; unfinished output withheld')
                stopped = True
                break

            # Check stop sequences
            text_so_far = self.backend.decode(generated_ids)
            if self.generation_progress is not None:
                self.generation_progress({'generated_tokens': len(generated_ids), 'text': text_so_far})
            stopped = False
            import re
            ts_user_match = re.search(r"\n(\[[^\]]+\]\s*)?(?:###\s*)?User:", text_so_far)
            if ts_user_match:
                text_so_far = text_so_far[:ts_user_match.start()]
                stopped = True
            else:
                for stop in stop_sequences:
                    if stop in text_so_far:
                        prefix = text_so_far.split(stop, 1)[0]
                        clean_prefix = re.sub(r"^(?:(?:Assistant|Helix|AI|User):\s*)+", "", prefix.strip(), flags=re.IGNORECASE).strip()
                        if not clean_prefix and "Assistant" in stop:
                            continue
                        text_so_far = prefix
                        stopped = True
                        break

            if stopped:
                self.last_generation_receipt['done_reason'] = 'conversation_boundary'
                break

            # Forward step single next_id
            with self.torch.inference_mode():
                result = self._forward_model(
                    input_ids=self.torch.tensor([[next_id]], device=self.device),
                    state=self.language_state,
                    use_cache=True,
                    logits_to_keep=1,
                )
                self.language_state = result.state
                logits = result.logits[0, -1].detach().float().cpu().numpy()

        # Closed-loop cognitive feedback into sensory state
        self.feedback_language_to_sensory(feedback_gain=0.15)
        self.last_generation_receipt['generated_tokens'] = len(generated_ids)
        return text_so_far.strip() if stopped else self.backend.decode(generated_ids).strip()

    def feedback_language_to_sensory(self, feedback_gain: float = 0.15) -> None:
        """Modulates sensory state with continuous cognitive feedback vector via Translator Bridge."""
        if getattr(self, 'native_stream', False):
            # The serial native owner admits the completed thought into the
            # actual graph/cortex. Do not add an untrained second projection.
            return
        if feedback_gain <= 0.0 or self.language_state is None or self.sensory_state is None:
            return
        with self.torch.no_grad():
            raw_lang = self.get_language_state_vector()
            translated_feedback = self.bridge.translate_language_to_sensory(raw_lang)
            feedback_tensor = self.torch.tensor(
                translated_feedback, device=self.device, dtype=self.torch.float32
            )

            # Modulate sensory state top-layer attention tensor in-place
            layer_idx = len(self.sensory_state.layers) - 1
            attn, ffn, wkv = self.sensory_state.read(layer_idx)
            
            # Blend feedback directly into attention shift slot
            modulated_attn = (attn.float() + feedback_gain * attn.float().norm().clamp_min(1.0) * feedback_tensor).to(attn.dtype)
            self.sensory_state.write(layer_idx, modulated_attn, ffn, wkv)
