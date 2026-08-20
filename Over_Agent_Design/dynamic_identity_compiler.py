"""
Dynamic Identity Compiler for Over-Agent Design.
Combines:
1. Baseline identity (identity.md)
2. Running Self-Opinion Statement (self_opinion.json, updated during DORMANT passes)
3. Synthetic Affect Simulation state (affect_simulation.py)
"""

import os
import json
from typing import Dict, Any
from affect_simulation import SyntheticAffectPipeline

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
IDENTITY_FILE_PATH = os.path.join(BASE_DIR, "identity.md")
SELF_OPINION_FILE_PATH = os.path.join(BASE_DIR, "self_opinion.json")

class DynamicIdentityCompiler:
    def __init__(self):
        self.affect_pipeline = SyntheticAffectPipeline()

    def get_self_opinion_statement(self) -> str:
        if os.path.exists(SELF_OPINION_FILE_PATH):
            try:
                with open(SELF_OPINION_FILE_PATH, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("self_opinion", "I am continually evolving my understanding of long-term memory architectures and effective AI pair programming.")
            except Exception:
                pass
        return "I am continually evolving my understanding of long-term memory architectures and effective AI pair programming."

    def update_self_opinion_statement(self, new_opinion: str):
        try:
            with open(SELF_OPINION_FILE_PATH, "w", encoding="utf-8") as f:
                json.dump({"self_opinion": new_opinion.strip()}, f, indent=2)
        except Exception as e:
            print(f"[Warning] Could not update self-opinion statement: {e}")

    def compile_dynamic_identity(self) -> str:
        """Compiles the dynamic identity system anchor."""
        base_identity = ""
        if os.path.exists(IDENTITY_FILE_PATH):
            with open(IDENTITY_FILE_PATH, "r", encoding="utf-8") as f:
                base_identity = f.read().strip()

        self_opinion = self.get_self_opinion_statement()
        affect_injection = self.affect_pipeline.get_affect_injection()

        return f"""{base_identity}

--- DYNAMIC SELF-OPINION STATEMENT (Consolidated Memory Anchor) ---
{self_opinion}

--- CURRENT AFFECT SIMULATION STATE ---
{affect_injection}
--------------------------------------------------------------------
"""
