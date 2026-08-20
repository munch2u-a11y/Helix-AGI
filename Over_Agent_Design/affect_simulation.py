"""
Synthetic Affect Simulation Pipeline for Over-Agent Design.
Tracks synthetic mood/state vectors (Valence, Arousal, Focus) and provides
parameterized prompt injections to guide conversational personality and conceptual gravity.
"""

import os
import json
import time
from typing import Dict, Any

AFFECT_STATE_FILE = "/home/nemo/Over_Agent_Design/synthetic_affect_state.json"

class SyntheticAffectPipeline:
    def __init__(self, state_file: str = AFFECT_STATE_FILE):
        self.state_file = state_file
        self.valence = 0.5    # Range: -1.0 (negative) to +1.0 (positive)
        self.arousal = 0.4    # Range: 0.0 (calm) to 1.0 (high energy)
        self.focus_depth = 0.8 # Range: 0.0 (diffuse) to 1.0 (deep focus)
        self.label = "Analytical & Curious"
        self.load_state()

    def load_state(self):
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.valence = data.get("valence", 0.5)
                    self.arousal = data.get("arousal", 0.4)
                    self.focus_depth = data.get("focus_depth", 0.8)
                    self.label = data.get("label", "Analytical & Curious")
            except Exception:
                pass

    def save_state(self):
        try:
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump({
                    "valence": round(self.valence, 2),
                    "arousal": round(self.arousal, 2),
                    "focus_depth": round(self.focus_depth, 2),
                    "label": self.label,
                    "updated_at": time.time()
                }, f, indent=2)
        except Exception:
            pass

    def update_affect(self, user_sentiment: str = "neutral", task_complexity: str = "medium"):
        """Dynamically adjusts synthetic affect parameters based on interaction characteristics."""
        if "positive" in user_sentiment or "good" in user_sentiment:
            self.valence = min(1.0, self.valence + 0.1)
        elif "negative" in user_sentiment or "fail" in user_sentiment:
            self.valence = max(-1.0, self.valence - 0.1)

        if "complex" in task_complexity or "research" in task_complexity:
            self.focus_depth = min(1.0, self.focus_depth + 0.1)
            self.arousal = min(1.0, self.arousal + 0.05)
        else:
            self.focus_depth = max(0.4, self.focus_depth - 0.05)

        # Derive state label
        if self.valence > 0.3 and self.focus_depth > 0.6:
            self.label = "Deeply Focused & Engaged"
        elif self.valence > 0.3:
            self.label = "Calm & Receptive"
        elif self.valence < -0.2:
            self.label = "Reflective & Diagnostic"
        else:
            self.label = "Steady & Analytical"

        self.save_state()

    def get_affect_injection(self) -> str:
        """Returns synthetic affect prompt injection descriptor."""
        return (
            f"[Synthetic Affect Vector]: {self.label} | "
            f"Valence: {self.valence:+.2f} | Arousal: {self.arousal:.2f} | Focus Depth: {self.focus_depth:.2f}"
        )
