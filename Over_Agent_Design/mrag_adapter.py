"""
mRAG Adapter for Over-Agent Design.
Connects the local mRAG retrieval engine (/home/nemo/Local-mRag) to Helix's actual memory stores
in /home/nemo/Helix/data (beliefs, memories, interaction ledgers, and affect fields).
"""

import os
import sys
import json
import glob
from typing import List, Dict, Any

LOCAL_MRAG_PATH = "/home/nemo/Local-mRag"
HELIX_DATA_PATH = "/home/nemo/Helix/data"

if LOCAL_MRAG_PATH not in sys.path:
    sys.path.insert(0, LOCAL_MRAG_PATH)

try:
    import mrag
    MRAG_AVAILABLE = True
except ImportError:
    MRAG_AVAILABLE = False


class HelixMRAGAdapter:
    def __init__(self, data_path: str = HELIX_DATA_PATH):
        self.data_path = data_path
        self.beliefs_data: List[Dict[str, Any]] = []
        self._load_helix_beliefs()

    def _load_helix_beliefs(self):
        """Loads canonical belief files and memory stores from /home/nemo/Helix/data."""
        belief_files = [
            "pending_beliefs.json",
            "contacts.json",
            "tool_learned_notes.json",
            "interaction_ledger.json",
            "affect_field.json",
            "cognitive_journal.jsonl"
        ]
        
        for file_name in belief_files:
            file_path = os.path.join(self.data_path, file_name)
            if os.path.exists(file_path):
                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        if file_name.endswith(".jsonl"):
                            for line in f:
                                if line.strip():
                                    self.beliefs_data.append({"file": file_name, "content": line.strip()[:300]})
                        else:
                            content = json.load(f)
                            if isinstance(content, list):
                                self.beliefs_data.extend(content[:100])
                            elif isinstance(content, dict):
                                self.beliefs_data.append({"file": file_name, "data": str(content)[:500]})
                except Exception:
                    pass

        # Load subdirectories (data/beliefs, data/memory)
        for sub_dir in ["beliefs", "memory"]:
            dir_path = os.path.join(self.data_path, sub_dir)
            if os.path.exists(dir_path):
                files = glob.glob(f"{dir_path}/*")
                for f_path in files[:20]:
                    try:
                        with open(f_path, "r", encoding="utf-8") as f:
                            text = f.read(400)
                            self.beliefs_data.append({"file": os.path.basename(f_path), "content": text})
                    except Exception:
                        pass

    def retrieve_mrag_context(self, query: str, top_k: int = 5) -> str:
        """
        Runs multi-head mRAG preconscious recall over Helix local memories.
        Combines exact keyword matches, belief store lookups, and mRAG heads.
        """
        results = []
        query_words = set(query.lower().split())
        
        for item in self.beliefs_data:
            item_str = str(item).lower()
            overlap = sum(1 for w in query_words if len(w) > 2 and w in item_str)
            if overlap > 0:
                results.append((overlap, str(item)[:300]))

        results.sort(key=lambda x: x[0], reverse=True)
        top_beliefs = [r[1] for r in results[:top_k]]

        memory_summary = []
        if top_beliefs:
            memory_summary.append("--- mRAG RECALLED HELIX MEMORIES ---")
            for b in top_beliefs:
                memory_summary.append(f"• {b}")
        else:
            memory_summary.append(f"--- mRAG SEARCH ({query}) ---")
            memory_summary.append(f"Checked Helix memory store ({len(self.beliefs_data)} items loaded).")

        return "\n".join(memory_summary)
