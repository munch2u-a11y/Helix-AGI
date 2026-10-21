#!/usr/bin/env python3
"""Tests for LoCoMo deep memory benchmark with sleep consolidation cycles."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.locomo_deep_memory_sandbox import (
    main,
    run_progressive_evaluation,
)


class TestLoCoMoDeepMemorySandbox(unittest.TestCase):
    def setUp(self):
        self.sample_dataset = [
            {
                "sample_id": "test-sample-001",
                "conversation": {
                    "session_1_date_time": "2026-03-02 09:00",
                    "session_1": [
                        {"dia_id": "D1:1", "speaker": "Mara", "text": "I brought mint tea."},
                        {"dia_id": "D1:2", "speaker": "Eli", "text": "Thanks, I am checking the flyer."},
                    ],
                    "session_2_date_time": "2026-03-09 14:30",
                    "session_2": [
                        {"dia_id": "D2:1", "speaker": "Mara", "text": "The list is in the yellow folder."},
                        {"dia_id": "D2:2", "speaker": "Eli", "text": "Got it."},
                    ],
                },
                "qa": [
                    {
                        "probe_id": "fact-c1",
                        "checkpoint": 1,
                        "probe_type": "fact",
                        "question": "What kind of tea did Mara bring?",
                        "answer": "mint tea",
                        "scoring": {"method": "token_f1"},
                    },
                    {
                        "probe_id": "fact-c2",
                        "checkpoint": 2,
                        "probe_type": "fact",
                        "question": "What color folder held the list?",
                        "answer": "yellow",
                        "scoring": {"method": "token_f1"},
                    },
                ],
            }
        ]

    def test_cli_parser_supports_sleep_consolidation_flags(self):
        """CLI parser must accept --sleep-consolidation and --sleep-model."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self.sample_dataset, f)
            dataset_path = f.name

        try:
            with patch("sys.argv", [
                "locomo_deep_memory_sandbox.py",
                "--dataset", dataset_path,
                "--dry-run",
                "--sleep-consolidation", "cases",
                "--sleep-model", "test-model",
            ]):
                with self.assertRaises(SystemExit) as cm:
                    main()
                self.assertEqual(cm.exception.code, 0)
        finally:
            Path(dataset_path).unlink(missing_ok=True)

    def test_run_progressive_evaluation_with_sleep_consolidation_cases(self):
        """run_progressive_evaluation should accept sleep_consolidation='cases' and record audits."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self.sample_dataset, f)
            dataset_path = f.name

        details_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        details_path = details_file.name
        details_file.close()

        try:
            # We test with dry_run=False but mock the LLM session
            with patch("tests.locomo_deep_memory_sandbox.load_provider_config") as mock_prov:
                cfg = MagicMock()
                cfg.provider_type = "test_provider"
                cfg.model = "test_model"
                mock_prov.return_value = cfg

                with patch("llm.providers.base.create_session") as mock_session_factory:
                    mock_session = MagicMock()
                    mock_session.send_message.return_value = '{"answer": "mint tea"}'
                    mock_session_factory.return_value = mock_session

                    success = run_progressive_evaluation(
                        dataset_path=dataset_path,
                        backend="auto",
                        sleep_consolidation="cases",
                        details_path=details_path,
                    )
                    self.assertTrue(success)

            saved_details = json.loads(Path(details_path).read_text(encoding="utf-8"))
            self.assertGreater(len(saved_details), 0)
            # Verify sleep consolidation audit is recorded in details
            first_row = saved_details[0]
            self.assertIn("sleep_consolidation", first_row)
            self.assertEqual(first_row["sleep_consolidation"]["mode"], "cases")
            self.assertGreaterEqual(first_row["sleep_consolidation"]["cases_touched"], 1)
        finally:
            Path(dataset_path).unlink(missing_ok=True)
            Path(details_path).unlink(missing_ok=True)


    def test_run_progressive_evaluation_with_sleep_consolidation_full(self):
        """run_progressive_evaluation with sleep_consolidation='full' should form person facets."""
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(self.sample_dataset, f)
            dataset_path = f.name

        details_file = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False)
        details_path = details_file.name
        details_file.close()

        try:
            with patch("tests.locomo_deep_memory_sandbox.load_provider_config") as mock_prov:
                cfg = MagicMock()
                cfg.provider_type = "test_provider"
                cfg.model = "test_model"
                cfg.max_output_tokens = 2048
                cfg.context_window = 64000
                cfg.options = {}
                mock_prov.return_value = cfg

                with patch("llm.providers.base.create_session") as mock_session_factory:
                    def side_effect_session(config, instruction, **kwargs):
                        sess = MagicMock()
                        if "Extract durable person-specific" in instruction:
                            # Maintenance worker response
                            sess.send_message.return_value = json.dumps({
                                "people": [
                                    {
                                        "name": "Mara",
                                        "source_ids": [],
                                        "facts": ["brought mint tea"],
                                        "communication_style": ["might we give it a blue minute"],
                                    }
                                ]
                            })
                        else:
                            # QA probe response
                            sess.send_message.return_value = '{"answer": "mint tea"}'
                        return sess

                    mock_session_factory.side_effect = side_effect_session

                    success = run_progressive_evaluation(
                        dataset_path=dataset_path,
                        backend="auto",
                        sleep_consolidation="full",
                        details_path=details_path,
                    )
                    self.assertTrue(success)

            saved_details = json.loads(Path(details_path).read_text(encoding="utf-8"))
            self.assertGreater(len(saved_details), 0)
            first_row = saved_details[0]
            self.assertEqual(first_row["sleep_consolidation"]["mode"], "full")
            self.assertGreaterEqual(first_row["sleep_consolidation"]["profiles_written"], 1)
        finally:
            Path(dataset_path).unlink(missing_ok=True)
            Path(details_path).unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
