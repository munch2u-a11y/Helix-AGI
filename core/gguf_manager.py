"""
GGUF Manager

A centralized in-process manager for loading and running .gguf micro-models 
via llama-cpp-python. This completely bypasses Ollama, allowing for:
- Task-specific micro-models (like a 1B/2B parameter model for fast YES/NO classifiers)
- Constrained grammar execution (forcing exact outputs and skipping <think> blocks)
- VRAM lifecycle control and queuing.

Usage:
    manager = GGUFManager(models_dir="models/")
    manager.load_model("fast_classifier", "granite-3.1-2b-instruct.Q4_K_M.gguf", n_ctx=1024)
    result = manager.generate("fast_classifier", "Does this thought...", grammar_string="root ::= \"YES\" | \"NO\"")
"""

import os
import threading
import logging
from typing import Dict, Any, Optional

try:
    from llama_cpp import Llama
    from llama_cpp.llama_grammar import LlamaGrammar
    HAS_LLAMA_CPP = True
except ImportError:
    HAS_LLAMA_CPP = False

logger = logging.getLogger(__name__)

class GGUFManager:
    def __init__(self, models_dir: str):
        self.models_dir = models_dir
        self.models: Dict[str, Any] = {}
        # Thread lock for inference to prevent CUDA/RAM out-of-memory if multiple 
        # background threads hit the model at the exact same millisecond.
        self._inference_lock = threading.Lock()
        
    def load_model(self, alias: str, filename: str, n_ctx: int = 2048, n_gpu_layers: int = -1) -> bool:
        """Load a .gguf file into memory and assign it an alias."""
        if not HAS_LLAMA_CPP:
            logger.error("llama-cpp-python is not installed. Cannot load GGUF model.")
            return False
            
        filepath = os.path.join(self.models_dir, filename)
        if not os.path.exists(filepath):
            logger.error(f"GGUF model not found at: {filepath}")
            return False
            
        try:
            logger.info(f"Loading GGUF model '{alias}' from {filename}...")
            # Set verbose=False to keep the console clean from llama.cpp C-level stdout spam
            model = Llama(
                model_path=filepath,
                n_ctx=n_ctx,
                n_gpu_layers=n_gpu_layers,
                verbose=False
            )
            self.models[alias] = model
            logger.info(f"Successfully loaded GGUF model '{alias}'.")
            return True
        except Exception as e:
            logger.error(f"Failed to load GGUF model '{alias}': {e}")
            return False
            
    def generate(self, 
                 alias: str, 
                 prompt: str, 
                 max_tokens: int = 10, 
                 temperature: float = 0.0,
                 grammar_string: Optional[str] = None) -> str:
        """
        Run inference on a loaded model. 
        Thread-safe: queues requests to prevent context clashing.
        """
        if alias not in self.models:
            logger.error(f"Cannot generate: model alias '{alias}' is not loaded.")
            return ""
            
        model = self.models[alias]
        
        # Compile grammar if provided (e.g. to force "YES" or "NO")
        grammar = None
        if grammar_string:
            try:
                grammar = LlamaGrammar.from_string(grammar_string)
            except Exception as e:
                logger.error(f"Failed to compile grammar: {e}")
                
        with self._inference_lock:
            try:
                output = model(
                    prompt,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    grammar=grammar,
                    echo=False
                )
                
                # Parse the output
                if "choices" in output and len(output["choices"]) > 0:
                    text = output["choices"][0]["text"]
                    return text.strip()
                return ""
            except Exception as e:
                logger.error(f"GGUF inference failed on '{alias}': {e}")
                return ""
