#!/usr/bin/env python3
"""Scoring and retrieval tests for the RAGOffice parity runner."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.ragoffice_parity_sandbox import (
    ANSWER_PROMPT,
    contains_answer,
    is_refusal,
    normalize_answer,
    retrieval_scores,
    score_answer,
)


class RagOfficeAnswerParityTests(unittest.TestCase):
    def test_reader_prompt_uses_ragoffice_refusal_contract(self):
        self.assertIn("NOT IN CONTEXT", ANSWER_PROMPT)
        self.assertIn("in as few words as possible", ANSWER_PROMPT)

    def test_span_matching_does_not_match_seven_inside_seventeen(self):
        self.assertFalse(contains_answer("17", "7"))
        self.assertTrue(contains_answer("The answer is 7.", "7"))

    def test_accepted_answer_and_required_span_rules(self):
        accepted = {
            "answerable": True,
            "ground_truth": "rejects them",
            "accepted_answers": ["prefers non-vector", "negative"],
        }
        self.assertTrue(score_answer(accepted, "negative")["correct"])

        compound = {
            "answerable": True,
            "ground_truth": "Alan Reyes and Helios",
            "required_spans": ["Alan Reyes", "Helios"],
        }
        self.assertTrue(score_answer(compound, "Helios — Alan Reyes")["correct"])
        self.assertFalse(score_answer(compound, "Alan Reyes")["correct"])

    def test_negative_control_requires_refusal(self):
        item = {"answerable": False, "ground_truth": ""}
        self.assertTrue(score_answer(item, "NOT IN CONTEXT")["correct"])
        self.assertTrue(is_refusal("Not mentioned."))
        self.assertFalse(score_answer(item, "Seattle")["correct"])


class RagOfficeRetrievalParityTests(unittest.TestCase):
    def test_support_hit_and_non_gold_are_kept_separate(self):
        item = {
            "support": [{"speaker": "User", "text": "The answer is cobalt."}],
        }
        retrieval = {"session_ids": ["q:t1", "other:t1"]}
        refs = {
            "q:t1": {"text": "The answer is cobalt."},
            "other:t1": {"text": "An unrelated distractor."},
        }
        scores = retrieval_scores(
            item,
            retrieval,
            "Recalled: The answer is cobalt. An unrelated distractor.",
            refs,
        )
        self.assertEqual(scores["support_hit_rate"], 1.0)
        self.assertEqual(scores["non_gold_ratio"], 0.5)
        self.assertEqual(scores["first_support_rank"], 1)

    def test_normalization_matches_ragoffice_article_rule(self):
        self.assertEqual(normalize_answer("The Deep Indigo"), "deep indigo")


if __name__ == "__main__":
    unittest.main(verbosity=2)
