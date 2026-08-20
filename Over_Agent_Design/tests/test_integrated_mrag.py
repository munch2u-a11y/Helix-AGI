"""Deterministic coverage for the embedded Helix mRAG boundary."""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

APP_DIR = Path(__file__).resolve().parents[1]
HELIX_ROOT = APP_DIR.parent
for path in (APP_DIR, HELIX_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from document_ingester import DocumentIngester
from mrag_adapter import HelixMRAGAdapter
from subconscious_conductor import SubconsciousConductor


class TestEmbeddedMRAG(unittest.TestCase):
    def test_mrag_adapter_retrieves_beliefs(self):
        with tempfile.TemporaryDirectory(prefix="helix_mrag_") as tmp:
            data_dir = Path(tmp)
            with open(data_dir / "contacts.json", "w", encoding="utf-8") as f:
                f.write('[{"name": "Nemo", "note": "Builds inspectable memory systems"}]')

            adapter = HelixMRAGAdapter(data_path=str(data_dir))
            context = adapter.retrieve_mrag_context("Nemo", top_k=3)

            self.assertIn("mRAG RECALLED HELIX MEMORIES", context)
            self.assertIn("Nemo", context)

    def test_document_ingester_uses_mrag_write_boundary(self):
        class RecordingAdapter:
            def __init__(self):
                self.calls = []

            def ingest_document_chunks(self, filename, chunks):
                self.calls.append((filename, list(chunks)))
                return ["mem_41", "mem_42"]

        recorder = RecordingAdapter()
        ingester = DocumentIngester(
            chunk_size_words=50,
            overlap_words=10,
            mrag_adapter=recorder,
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("evidence " * 80)
            path = handle.name
        try:
            result = ingester.process_file_upload(path, "../unsafe/source.txt")
        finally:
            os.unlink(path)

        self.assertTrue(result["success"])
        self.assertEqual(result["filename"], "source.txt")
        self.assertEqual(result["saved_nodes"], ["mem_41", "mem_42"])
        self.assertEqual(recorder.calls[0][0], "source.txt")
        self.assertGreater(len(recorder.calls[0][1]), 1)


class _RecordingMRAG:
    def __init__(self):
        self.queries = []
        self.memories = []

    def retrieve_mrag_context(self, query, top_k=5):
        self.queries.append((query, top_k))
        return "--- HELIX mRAG RECALLED CONTEXT ---\n- [id=people_nemo tier=2 category=people] Nemo prefers local systems."

    def remember(self, content, **kwargs):
        self.memories.append((content, kwargs))
        return f"mem_{len(self.memories)}"


class _ScriptedBackend:
    def __init__(self):
        self.responses = iter([
            'open_focus_window(type="speaker", prompt="Answer with grounded context")',
            "Hello from the grounded speaker.",
        ])

    def generate(self, **_kwargs):
        return next(self.responses)


class TestConductorMRAGFlow(unittest.TestCase):
    def test_turn_recalls_then_records_inbound_and_outbound(self):
        mrag = _RecordingMRAG()
        with tempfile.TemporaryDirectory(prefix="helix_overagent_state_") as tmp:
            seeded_path = os.path.join(tmp, "seed.pkl")
            with patch("subconscious_conductor.SEEDED_STATE_PATH", seeded_path):
                conductor = SubconsciousConductor(
                    backend=_ScriptedBackend(),
                    enable_autonomous_background=False,
                    mrag_adapter=mrag,
                )
                conductor.identity_compiler.affect_pipeline.state_file = os.path.join(
                    tmp, "affect.json"
                )
                response = conductor.process_user_event("Do you remember Nemo?")

        self.assertEqual(response, "Hello from the grounded speaker.")
        self.assertEqual(mrag.queries, [("Do you remember Nemo?", 5)])


if __name__ == "__main__":
    unittest.main()
