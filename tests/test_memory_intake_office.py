#!/usr/bin/env python3
"""Tests for the memory-goal intake work order."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from core.memory_intake_office import MemoryIntakeOffice, clean_memory_query


class MemoryIntakeOfficeTests(unittest.TestCase):
    def setUp(self):
        self.intake = MemoryIntakeOffice()

    def test_strips_transport_wrapper_and_binds_possessive_subject(self):
        order = self.intake.review(
            "Operator question: What tattoo did Jon's friend mention?",
            known_entities=["Gina", "Jon"],
        )
        self.assertEqual(order.search_query, "What tattoo did Jon's friend mention?")
        self.assertEqual(order.subjects, ("Jon",))
        self.assertEqual(order.possessive_subjects, ("Jon",))
        self.assertTrue(order.requires_exact)
        self.assertEqual(order.role_constraint, "relational")

    def test_factual_person_question_does_not_request_profile(self):
        order = self.intake.review(
            "What flooring did Gina choose for the studio?",
            known_entities=["Gina", "Jon"],
        )
        self.assertEqual(order.subjects, ("Gina",))
        self.assertTrue(order.requires_exact)
        self.assertFalse(order.profile_allowed)
        self.assertEqual(order.role_constraint, "subject_facts")

    def test_preference_and_style_queries_allow_learned_profile(self):
        preference = self.intake.review(
            "What is Bob's favorite ice cream?", known_entities=["Bob"],
        )
        style = self.intake.review(
            "What phrase does Bob usually use?", known_entities=["Bob"],
        )
        self.assertTrue(preference.profile_allowed)
        self.assertTrue(preference.requires_exact)
        self.assertTrue(style.profile_allowed)
        self.assertIn("communication_style", style.requested_facets)

    def test_statement_remains_available_for_ordinary_recognition(self):
        order = self.intake.review(
            "Bob told me about the garden today.", known_entities=["Bob"],
        )
        self.assertFalse(order.is_question)
        self.assertFalse(order.requires_exact)
        self.assertEqual(clean_memory_query(order.raw_message), order.search_query)


if __name__ == "__main__":
    unittest.main(verbosity=2)
