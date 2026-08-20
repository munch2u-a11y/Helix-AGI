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
        ingester = DocumentIngester(
            chunk_size_words=50,
            overlap_words=10,
        )
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as handle:
            handle.write("evidence " * 80)
            path = handle.name
        try:
            result = ingester.process_file_upload(path, "source.txt")
        finally:
            os.unlink(path)

        self.assertTrue(result["success"])
        self.assertEqual(result["filename"], "source.txt")
        self.assertGreater(result["chunk_count"], 1)


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
        with tempfile.TemporaryDirectory(prefix="helix_overagent_state_") as tmp:
            seeded_path = os.path.join(tmp, "seed.pkl")
            with patch("subconscious_conductor.SEEDED_STATE_PATH", seeded_path):
                conductor = SubconsciousConductor(
                    backend=_ScriptedBackend(),
                    enable_autonomous_background=False,
                )
                conductor.identity_compiler.affect_pipeline.state_file = os.path.join(
                    tmp, "affect.json"
                )
                response = conductor.process_user_event("Do you remember Nemo?")

        self.assertEqual(response, "Hello from the grounded speaker.")


if __name__ == "__main__":
    unittest.main()
