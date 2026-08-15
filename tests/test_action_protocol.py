#!/usr/bin/env python3
"""Deterministic action receipt and verification tests."""

import unittest

from core.action_protocol import (
    EvidenceLevel,
    ReceiptStatus,
    ToolReceipt,
    VerificationStatus,
    clarification_question,
    classify_tool_result,
    verify_receipts,
)


class ToolReceiptTests(unittest.TestCase):
    def test_failure_language_is_not_success(self):
        for result in (
            "Search failed: offline",
            "Could not deliver reply to Mara — no contact record found.",
            "Browser navigation failed: timeout",
            "Application not found: vlc",
            "No page loaded; call browse first.",
            "Google Calendar not configured.",
            "Title and start_time required.",
            '{"error": "permission denied"}',
        ):
            with self.subTest(result=result):
                receipt = classify_tool_result("search", {"query": "x"}, result)
                self.assertNotEqual(receipt.status, ReceiptStatus.SUCCESS)
                self.assertEqual(receipt.evidence, EvidenceLevel.NONE)

    def test_no_results_is_a_valid_observation(self):
        receipt = classify_tool_result("search", {"query": "missing"}, "No results for: missing")
        self.assertEqual(receipt.status, ReceiptStatus.SUCCESS)
        self.assertEqual(receipt.evidence, EvidenceLevel.OBSERVED)

    def test_structured_metadata_overrides_legacy_wording(self):
        receipt = classify_tool_result(
            "custom_action",
            {},
            {"ok": True, "verified": True, "status": "complete", "artifact_refs": ["a-1"]},
        )
        self.assertTrue(receipt.confirmed)
        self.assertEqual(receipt.artifact_refs, ["a-1"])

    def test_receipt_round_trip(self):
        original = classify_tool_result(
            "email_send",
            {"to": "mara@example.com"},
            "Email sent successfully. Message ID: abc123",
        )
        restored = ToolReceipt.from_dict(original.to_dict())
        self.assertEqual(restored, original)


class ActionVerificationTests(unittest.TestCase):
    def test_model_report_without_receipt_cannot_prove_action(self):
        result = verify_receipts([])
        self.assertEqual(result.status, VerificationStatus.NO_ACTION)
        self.assertFalse(result.verified)

    def test_confirmed_delivery_verifies_communication(self):
        receipt = classify_tool_result(
            "reply", {"recipient": "Mara"}, "Sent to Mara."
        )
        result = verify_receipts([receipt])
        self.assertEqual(result.status, VerificationStatus.VERIFIED)

    def test_file_write_requires_matching_readback(self):
        write = classify_tool_result(
            "write_file",
            {"path": "/tmp/a.txt", "content": "final total: 42"},
            "File written successfully",
        )
        partial = verify_receipts([write])
        self.assertEqual(partial.status, VerificationStatus.PARTIAL)

        read = classify_tool_result(
            "read_file", {"path": "/tmp/a.txt"}, "final total: 42"
        )
        verified = verify_receipts([write, read])
        self.assertEqual(verified.status, VerificationStatus.VERIFIED)

    def test_file_readback_must_match_path_and_content(self):
        write = classify_tool_result(
            "write_file", {"path": "/tmp/a.txt", "content": "wanted"}, "ok"
        )
        wrong_path = classify_tool_result(
            "read_file", {"path": "/tmp/b.txt"}, "wanted"
        )
        wrong_content = classify_tool_result(
            "read_file", {"path": "/tmp/a.txt"}, "old"
        )
        self.assertEqual(
            verify_receipts([write, wrong_path]).status,
            VerificationStatus.PARTIAL,
        )
        self.assertEqual(
            verify_receipts([write, wrong_content]).status,
            VerificationStatus.PARTIAL,
        )

    def test_browser_and_desktop_mutations_need_observation(self):
        click = classify_tool_result(
            "browse_interact", {"selector": "#play", "action": "click"}, "Clicked: #play"
        )
        self.assertEqual(verify_receipts([click]).status, VerificationStatus.PARTIAL)
        page = classify_tool_result("browse", {"url": "https://youtube.com/watch?v=x"}, "Page loaded: Video")
        self.assertEqual(verify_receipts([click, page]).status, VerificationStatus.VERIFIED)

        key = classify_tool_result("desktop_key", {"key": "space"}, "Pressed: space")
        window = classify_tool_result("desktop_window", {}, "Active window: YouTube")
        self.assertEqual(verify_receipts([key, window]).status, VerificationStatus.VERIFIED)

    def test_failed_attempt_can_be_recovered_by_confirmed_success(self):
        failed = classify_tool_result(
            "email_send", {"to": "bad"}, "Error: invalid recipient"
        )
        recovered = classify_tool_result(
            "email_send", {"to": "mara@example.com"}, "Email sent. Message ID: 7"
        )
        result = verify_receipts([failed, recovered])
        self.assertEqual(result.status, VerificationStatus.VERIFIED)

    def test_unrelated_read_does_not_mask_failed_mutation(self):
        gathered = classify_tool_result("search", {"query": "date"}, "Date: Friday")
        failed = classify_tool_result(
            "email_send", {"to": "bad"}, "Failed to send email: invalid recipient"
        )
        result = verify_receipts([gathered, failed])
        self.assertEqual(result.status, VerificationStatus.FAILED)

    def test_terminal_mutation_needs_a_later_observer_command(self):
        edit = classify_tool_result(
            "terminal", {"command": "perl -pi -e 's/old/new/' app.py"}, "Exit code: 0"
        )
        self.assertEqual(verify_receipts([edit]).status, VerificationStatus.PARTIAL)
        test = classify_tool_result(
            "terminal", {"command": "pytest -q"}, "2 passed in 0.2s"
        )
        self.assertEqual(
            verify_receipts([edit, test]).status,
            VerificationStatus.VERIFIED,
        )

    def test_authoritative_api_success_can_confirm_mutation(self):
        task = classify_tool_result(
            "tasks_create", {"title": "Call Mara"}, "Task created: 'Call Mara' (id: 7)"
        )
        self.assertTrue(task.confirmed)
        self.assertEqual(verify_receipts([task]).status, VerificationStatus.VERIFIED)


class ClarificationProtocolTests(unittest.TestCase):
    def test_extracts_one_compact_question(self):
        self.assertEqual(
            clarification_question("NEED_INPUT: Which Alex should receive the report?"),
            "Which Alex should receive the report?",
        )
        self.assertEqual(clarification_question("I need more information."), "")


if __name__ == "__main__":
    unittest.main(verbosity=2)
