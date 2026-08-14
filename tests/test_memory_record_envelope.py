#!/usr/bin/env python3
"""Evidence-envelope persistence and legacy-classification tests."""

import tempfile
import unittest

from memory.memory_manager import MemoryManager
from memory.record_envelope import (
    build_record_envelope,
    envelope_from_metadata,
    record_kind_from_index_metadata,
)


class MemoryRecordEnvelopeTests(unittest.TestCase):
    def test_private_thought_is_not_external_action_evidence(self):
        envelope = build_record_envelope(
            content="[thought] I should message Mara about the invoice.",
            memory_type="thought",
            source="pulse_output",
            tags=["pulse_thought", "turn:4"],
        )

        self.assertEqual(envelope["record_kind"], "thought")
        self.assertEqual(envelope["direction"], "internal")
        self.assertEqual(envelope["evidence_scopes"], ["agent_cognition"])
        self.assertEqual(envelope["action_status"], "unverified")
        self.assertIn("not proof that an external action occurred", envelope["retrieval_text"])

    def test_inbound_and_outbound_communications_keep_distinct_roles(self):
        inbound = build_record_envelope(
            content=(
                '[10:02:03] Mara is talking to me via telegram. '
                'They said: "The invoice total is $420."'
            ),
            memory_type="event",
            source="pulse_input",
            tags=["conversation"],
        )
        outbound = build_record_envelope(
            content="I replied to Mara: I received the $420 invoice.",
            memory_type="conversation",
            source="helix_outbound",
            tags=["outbound", "recipient:Mara"],
        )

        self.assertEqual(inbound["record_kind"], "inbound_message")
        self.assertEqual(inbound["actor"], "Mara")
        self.assertEqual(inbound["action_status"], "received")
        self.assertEqual(outbound["record_kind"], "outbound_message")
        self.assertEqual(outbound["recipients"], ["Mara"])
        self.assertEqual(outbound["action_status"], "delivered")

    def test_new_store_persists_envelope_but_keeps_exact_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            memory = MemoryManager(tmp)
            exact = "[thought] Maybe the deployment should wait."
            memory_id = memory.store(
                content=exact,
                memory_type="thought",
                source="pulse_output",
                tags=["session:s1", "turn:9"],
            )
            entry = memory.journal.latest_by_id()[str(memory_id)]
            metadata = entry["metadata"]

        self.assertEqual(entry["content"], exact)
        self.assertEqual(metadata["record_kind"], "thought")
        self.assertEqual(metadata["record_envelope"]["visibility"], "private")
        self.assertIn(exact, metadata["retrieval_text"])

    def test_legacy_metadata_is_classified_without_journal_rewrite(self):
        legacy = {
            "memory_type": "conversation",
            "source": "helix_outbound",
            "tags": ["reply", "outbound", "recipient:Jon"],
        }
        envelope = envelope_from_metadata("I replied to Jon: Done.", legacy)

        self.assertEqual(envelope["record_kind"], "outbound_message")
        self.assertEqual(envelope["recipients"], ["Jon"])
        self.assertNotIn("record_envelope", legacy)

    def test_semantic_index_filter_can_type_legacy_rows(self):
        kind = record_kind_from_index_metadata({
            "type": "memory",
            "content": "[thought] I might send a reply.",
            "memory_type": "thought",
            "source": "pulse_output",
            "tags": ["pulse_thought"],
        })
        self.assertEqual(kind, "thought")

    def test_failed_tool_report_cannot_masquerade_as_completed_action(self):
        envelope = build_record_envelope(
            content="[10:04] Tool [email_send] returned: Tool error: delivery failed",
            memory_type="event",
            source="pulse_input",
            tags=["tool_result"],
        )

        self.assertEqual(envelope["record_kind"], "tool_result")
        self.assertEqual(envelope["tool_name"], "email_send")
        self.assertEqual(envelope["action_status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
