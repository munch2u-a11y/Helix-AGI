"""
Helix — LLM Orchestrator (Thin Wrapper)

This is now a thin wrapper around PulseLoop for backward compatibility
and for any direct API calls needed outside the pulse system
(e.g., the conscious 'remember' tool's deep semantic search).

The primary cognitive loop is in core/pulse_loop.py.
Previous request-response version archived in:
  previous_versions/orchestrator_20260503_request_response.py
"""

from typing import Optional
from core.pulse_loop import PulseLoop
from memory.memory_manager import MemoryManager


class LLMOrchestrator:
    """Thin wrapper providing convenience methods around the pulse loop."""

    def __init__(self, pulse_loop: PulseLoop, memory_manager: MemoryManager):
        self.pulse_loop = pulse_loop
        self.memory = memory_manager

    def send_user_message(self, message: str, sender: str = "User", channel: str = "direct"):
        """Inject a user message as an event into the pulse loop."""
        self.pulse_loop.emit("user_message", {
            "sender": sender,
            "content": message,
            "channel": channel,
        })

    def conscious_remember(self, query: str, limit: int = 10):
        """Deep memory search — uses ChromaDB/long-term (not pre-conscious).

        This is the conscious 'remember' tool: gravitational search
        across the full long-term archive for concept-relevant memories.
        """
        return self.memory.search_semantic(query, limit=limit)

    def get_status(self):
        """Get current pulse loop status."""
        return self.pulse_loop.get_status()
