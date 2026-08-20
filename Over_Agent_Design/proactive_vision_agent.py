"""
Proactive Desktop Vision & mRAG Resonance Agent — Subconscious Over-Agent System.

Monitors user desktop activity, generates quick screen summaries, queries mRAG preconscious memory,
and triggers unprompted proactive vocalization whenever screen actions resonate with past memory beliefs.
"""

import os
import sys
import time
import json
import subprocess
from typing import Dict, Any, Optional

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from llm_backend import LLMBackend
from mrag_adapter import HelixMRAGAdapter

class ProactiveVisionAgent:
    def __init__(self, backend: Optional[LLMBackend] = None):
        self.backend = backend or LLMBackend()
        self.mrag_adapter = HelixMRAGAdapter()
        self.last_proactive_time = 0.0

    def capture_screen_summary(self) -> str:
        """Captures a quick screen snapshot and extracts active workspace text/window context."""
        try:
            # Check active window title via xdotool if available
            cmd = "xdotool getactivewindow getwindowname"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=2)
            window_title = res.stdout.strip()
            if window_title:
                return f"User Active Window: '{window_title}'"
        except Exception:
            pass

        # Fallback file workspace snapshot
        recent_files = self._get_recently_modified_files()
        if recent_files:
            return f"User Working on Local Files: {', '.join(recent_files[:3])}"

        return "User Active Desktop Workspace"

    def evaluate_proactive_resonance(self, min_interval_s: float = 45.0) -> Optional[Dict[str, Any]]:
        """
        Evaluates desktop activity against mRAG memory stores.
        If a screen action triggers memory resonance, returns a proactive speech event.
        """
        now = time.time()
        if (now - self.last_proactive_time) < min_interval_s:
            return None

        screen_summary = self.capture_screen_summary()
        mrag_context = self.mrag_adapter.retrieve_mrag_context(screen_summary, top_k=3)

        if "No matching memory beliefs found" in mrag_context or not mrag_context.strip():
            return None

        # Generate charming, unprompted proactive speech comment
        system_prompt = (
            "I am Helix, an active floating mascot companion.\n"
            "I am watching what the user is working on on their screen.\n"
            "Generate ONE short, charming, single-sentence unprompted observation (under 15 words) "
            "connecting what the user is doing to the recalled memory belief."
        )
        prompt = (
            f"SCREEN CONTEXT: {screen_summary}\n\n"
            f"RECALLED MEMORY BELIEF:\n{mrag_context}\n\n"
            "My proactive, charming observation to the user:"
        )

        proactive_thought = self.backend.generate(prompt=prompt, system_prompt=system_prompt, temperature=0.7)
        if proactive_thought and len(proactive_thought.strip()) > 5:
            self.last_proactive_time = now
            return {
                "screen_summary": screen_summary,
                "recalled_memory": mrag_context[:150],
                "proactive_speech": proactive_thought.strip(),
                "expression": "surprised",
                "mood_label": "Memory Resonance Triggered!"
            }

        return None

    def _get_recently_modified_files(self) -> list:
        try:
            cmd = f"find {BASE_DIR} -maxdepth 2 -mmin -10 -type f"
            res = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=3)
            files = [os.path.basename(f) for f in res.stdout.splitlines() if f.strip() and not f.endswith(".pkl")]
            return files
        except Exception:
            return []
