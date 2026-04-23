from pathlib import Path
from typing import List, Dict, Callable

class ConsciousProvider:
    """Abstract base class for running the main conscious loop."""
    
    # Max number of sequential tool-call pulses before safety exit
    SEQUENTIAL_CHAIN_LIMIT = 15

    def __init__(self, config: dict, base_dir: Path, cost_tracker=None):
        self.config = config
        self.base_dir = base_dir
        self._cost_tracker = cost_tracker  # typically GeminiClient for shared logging
        self.chat_history = []

    def reset_history(self):
        """Clear session chat history."""
        self.chat_history = []

    def log_cost(self, model: str, input_tokens: int, output_tokens: int, cost: float, elapsed: float, prompt_preview: str, provider: str):
        """Log cost locally using the shared tracker."""
        if self._cost_tracker and hasattr(self._cost_tracker, '_log_call'):
            self._cost_tracker._log_call(
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                elapsed=elapsed,
                prompt_preview=prompt_preview,
                provider=provider
            )

    def think(
        self, 
        user_message: str, 
        system_prompt: str, 
        tools: list, 
        tool_runner, 
        emit_callback: Callable, 
        heartbeat_count: int,
        hyperfocus: bool = False
    ) -> str:
        raise NotImplementedError("Providers must implement think()")
