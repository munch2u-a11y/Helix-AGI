#!/usr/bin/env python3
"""Tests for the review-first LongMemEval-S sandbox."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.longmemeval_sandbox import (
    LONGMEMEVAL_QA_INSTRUCTION,
    MAX_DEV_QUESTIONS,
    answer_diagnostics,
    evidence_diagnostics,
    format_session,
    rebuild_reports,
    retrieval_record,
    stratified_selection,
    validate_dataset,
    write_question_review,
)


def _item(index, question_type="multi-session", abstention=False):
    question_id = f"q{index}" + ("_abs" if abstention else "")
    return {
        "question_id": question_id,
        "question_type": question_type,
        "question": "What was remembered?",
        "answer": "blue",
        "question_date": "2026/01/02 (Fri) 10:00",
        "haystack_sessions": [[
            {"role": "user", "content": "Remember blue.", "has_answer": True},
            {"role": "assistant", "content": "I will."},
        ]],
        "haystack_session_ids": [f"session-{index}"],
        "haystack_dates": ["2026/01/01 (Thu) 09:00"],
        "answer_session_ids": [] if abstention else [f"session-{index}"],
    }


class DatasetTests(unittest.TestCase):
    def test_question_date_is_not_a_global_evidence_cutoff(self):
        instruction = LONGMEMEVAL_QA_INSTRUCTION.lower()
        self.assertNotIn("before the question date", instruction)
        self.assertIn("not a universal evidence", instruction)

    def test_schema_and_hidden_answer_flag_is_not_rendered(self):
        data = [_item(1)]
        self.assertEqual(validate_dataset(data), [])
        rendered = format_session(
            "session-1", data[0]["haystack_dates"][0], data[0]["haystack_sessions"][0],
        )
        self.assertIn("[SESSION: session-1]", rendered)
        self.assertIn("User: Remember blue.", rendered)
        self.assertNotIn("has_answer", rendered)
        self.assertNotIn("True", rendered)

    def test_stratified_selection_is_deterministic_and_bounded(self):
        data = []
        for index in range(60):
            data.append(_item(index, "multi-session", abstention=index < 6))
        for index in range(60, 100):
            data.append(_item(index, "temporal-reasoning", abstention=index < 64))
        first, quotas = stratified_selection(data, limit=20, seed=7)
        second, _ = stratified_selection(data, limit=20, seed=7)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 20)
        self.assertEqual(len(set(first)), 20)
        self.assertEqual(sum(quotas.values()), 20)
        with self.assertRaises(ValueError):
            stratified_selection(data * 2, limit=MAX_DEV_QUESTIONS + 1)


class DiagnosticTests(unittest.TestCase):
    def test_answer_diagnostics_are_transparent(self):
        scores = answer_diagnostics("my blue bicycle", "blue bicycle", False)
        self.assertFalse(scores["normalized_exact_match"])
        self.assertTrue(scores["normalized_contains"])
        self.assertGreaterEqual(scores["token_f1"], 0.8)
        abstention = answer_diagnostics("I don't know.", "I don't know", True)
        self.assertTrue(abstention["predicted_abstention"])
        self.assertTrue(abstention["abstention_match"])

    def test_evidence_diagnostics_do_not_grade_abstention_retrieval(self):
        regular = evidence_diagnostics(["s1", "s2"], ["s2"], False)
        self.assertEqual(regular["recall"], 1.0)
        self.assertEqual(regular["precision"], 0.5)
        self.assertTrue(regular["hit"])
        abstention = evidence_diagnostics(["s1"], [], True)
        self.assertIsNone(abstention["recall"])
        self.assertIsNone(abstention["hit"])

    def test_retrieval_attribution_counts_recent_context_the_model_saw(self):
        class _Unified:
            last_stats = {"selected": 1}

        class _Preconscious:
            _unified = _Unified()
            _last_surfaced_memory_ids = ["mem_1"]
            _last_selected_beliefs = [{
                "id": "mem_1",
                "content": "[SESSION: selected] remembered",
                "lane": "semantic",
                "tier": 0,
            }]

        runtime = {
            "preconscious": _Preconscious(),
            "_longmemeval_point_sessions": {"mem_1": "selected"},
        }
        record = retrieval_record(
            runtime,
            "mRAG [SESSION: selected] plus (recent: [SESSION: recent] context)",
        )
        self.assertEqual(record["selected_session_ids"], ["selected"])
        self.assertEqual(record["context_session_ids"], ["selected", "recent"])
        self.assertEqual(record["session_ids"], ["selected", "recent"])


class ReportTests(unittest.TestCase):
    def test_reports_keep_manual_review_and_official_hypothesis(self):
        row = {
            "sequence": 1,
            "question_id": "q1",
            "question_type": "multi-session",
            "question_date": "2026/01/02",
            "is_abstention": False,
            "question": "What color?",
            "gold_answer": "blue",
            "prediction": "blue",
            "raw_response": '{"answer":"blue"}',
            "answer_diagnostics": {
                "normalized_exact_match": True,
                "token_f1": 1.0,
                "abstention_match": None,
            },
            "evidence_diagnostics": {
                "gold_session_ids": ["s1"],
                "retrieved_session_ids": ["s1"],
                "overlap_session_ids": ["s1"],
                "recall": 1.0,
                "precision": 1.0,
                "hit": True,
            },
            "retrieval": {
                "stats": {"by_lane": {"semantic": 1}},
                "memories": [{
                    "point_id": "mem_1", "session_id": "s1", "lane": "semantic",
                    "tier": 0, "rank": 1, "semantic_score": 0.9, "gravity": 0.1,
                    "association_linked": False,
                }],
            },
            "gold_evidence": [{"content": "[SESSION: s1]\nUser: blue"}],
            "injected_context": "Recalled blue.",
        }
        manifest = {"num_questions": 1}
        with tempfile.TemporaryDirectory() as tmp_dir:
            output = Path(tmp_dir)
            write_question_review(output, row)
            rebuild_reports(output, manifest, [row])
            review = (output / "manual_review.md").read_text(encoding="utf-8")
            hypothesis = json.loads(
                (output / "hypotheses.jsonl").read_text(encoding="utf-8")
            )
            self.assertIn("transparent diagnostics", review)
            self.assertIn("review/001_q1.md", review)
            self.assertEqual(hypothesis, {"question_id": "q1", "hypothesis": "blue"})
            self.assertTrue((output / "review" / "001_q1.md").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
