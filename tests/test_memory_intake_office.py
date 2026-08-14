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

    def test_comparative_like_and_hyphenated_first_do_not_change_question_type(self):
        order = self.intake.review(
            "I think the Office-first design may sound less like himself. What do you think?"
        )
        self.assertIn("opinion", order.requested_facets)
        self.assertNotIn("preference", order.requested_facets)
        self.assertFalse(order.requires_exact)
        self.assertFalse(order.requires_chronology)

    def test_routes_sent_received_cognition_and_tool_evidence(self):
        sent = self.intake.review(
            "What did you tell Mara about the invoice?", known_entities=["Mara"],
        )
        sent_noun_first = self.intake.review(
            "What message did you send Mara?", known_entities=["Mara"],
        )
        received = self.intake.review(
            "What did Mara tell me about the invoice?", known_entities=["Mara"],
        )
        cognition = self.intake.review(
            "Why did you decide to message Mara?", known_entities=["Mara"],
        )
        tool = self.intake.review("What result did the temperature sensor report?")

        self.assertEqual(sent.target_record_kinds, ("outbound_message",))
        self.assertEqual(sent_noun_first.target_record_kinds, ("outbound_message",))
        self.assertEqual(sent.evidence_scope, "delivered_communication")
        self.assertEqual(sent.thought_policy, "exclude")
        self.assertEqual(received.target_record_kinds, ("inbound_message",))
        self.assertEqual(cognition.target_record_kinds, ("thought",))
        self.assertEqual(cognition.thought_policy, "primary")
        self.assertIn("outbound_message", cognition.related_record_kinds)
        self.assertEqual(tool.target_record_kinds, ("tool_result", "tool_observation"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
