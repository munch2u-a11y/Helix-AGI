"""Outcome credit and lesson attribution without live tools or model calls."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from core.action_protocol import classify_tool_result
from core.progress_feedback import ProgressFeedback
import core.engagement_hook as engagement
import core.tool_lesson_tracker as lessons


class ProgressFeedbackTests(unittest.TestCase):
    def setUp(self):
        self.feedback = ProgressFeedback()

    def test_duplicate_and_repeated_observations_do_not_earn_new_progress(self):
        first = classify_tool_result("read_file", {"path": "a.txt"}, "actual content")
        self.feedback.observe_tool(first)
        self.feedback.observe_tool(first)
        self.feedback.observe_tool(classify_tool_result("read_file", {"path": "a.txt"}, "actual content"))
        counts = self.feedback.snapshot()
        self.assertEqual(counts["attempts"], 2)
        self.assertEqual(counts["advanced"], 1)
        self.assertEqual(self.feedback.snapshot()["advanced"], 0)

    def test_failed_or_unconfirmed_mutations_do_not_count_as_progress(self):
        for result in ("Error: denied", "attempted to type the message"):
            self.feedback.observe_tool(classify_tool_result("desktop_type", {}, result))
        counts = self.feedback.snapshot()
        self.assertEqual(counts["advanced"], 0)
        self.assertGreater(counts["failures"], 0)

    def test_failed_retry_does_not_make_old_content_new_again(self):
        for result in ("actual content", "Error: not available", "actual content"):
            self.feedback.observe_tool(classify_tool_result("read_file", {"path": "a.txt"}, result))
        self.assertEqual(self.feedback.snapshot()["advanced"], 1)

    def test_tool_attempts_cannot_clear_stagnation_but_verified_progress_can(self):
        sentinel = Mock()
        with patch.multiple(engagement, _sentinel=sentinel, _physics_engine=None,
                            _recent_thoughts=[], _recent_embeddings=[], _stagnation_counter=0):
            ctx = SimpleNamespace(thought="", tool_calls=[{"name": "browse"}],
                                  progress={"attempts": 1, "failures": 1})
            for _ in range(3):
                engagement.engagement_hook(ctx)
            self.assertEqual(engagement._stagnation_counter, 3)
            self.assertFalse(any(call.args == ("verified_progress",) for call in sentinel.nudge_omega_from_event.call_args_list))
            sentinel.reset_mock()
            ctx.progress = {"advanced": 1, "failures": 1}
            engagement.engagement_hook(ctx)
            sentinel.nudge_omega_from_event.assert_any_call("tool_failure")
            self.assertEqual(engagement._stagnation_counter, 0)
            sentinel.nudge_omega_from_event.assert_called_with("verified_progress")

    def test_unknown_calls_are_not_assumed_to_be_successful(self):
        ctx = SimpleNamespace(thought="A new thought that is long enough to compare.",
                              tool_calls=[{"name": "unverified_call"}], progress={})
        sentinel = Mock()
        with patch.multiple(engagement, _sentinel=sentinel, _physics_engine=None,
                            _recent_thoughts=[], _recent_embeddings=[], _stagnation_counter=2):
            engagement.engagement_hook(ctx)
            self.assertEqual(engagement._stagnation_counter, 3)
            sentinel.nudge_omega_from_event.assert_called_with("cognitive_stagnation")

    def test_lesson_credit_needs_matching_exposure_and_never_verifies_its_claim(self):
        belief = {"verifications": 2, "stability_index": 0.5}
        store = Mock()
        store.get_belief.return_value = belief
        store.update_belief.side_effect = lambda bid, **values: belief.update(values)
        with patch.multiple(lessons, _belief_store=store, _recent_injections=[]):
            lessons.note_lessons_injected([{"belief_id": "lesson:1", "tools": ["read_file"]}])
            receipt = classify_tool_result("read_file", {"path": "a.txt"}, "actual content")
            lessons.observe_tool_result("read_file", receipt.args, receipt.result, receipt=receipt)
            store.update_belief.assert_not_called()
            lessons.observe_tool_result("read_file", receipt.args, receipt.result, receipt=receipt,
                                        context_id="turn:1", lesson_ids={"different:lesson"})
            store.update_belief.assert_not_called()
            lessons.observe_tool_result("read_file", receipt.args, receipt.result, receipt=receipt,
                                        context_id="turn:1", lesson_ids={"lesson:1"})
            self.assertEqual(belief["successful_uses"], 1)
            self.assertEqual(belief["verifications"], 2)
            self.assertEqual(belief["stability_index"], 0.5)
            self.assertEqual(belief["last_successful_use"]["call_id"], receipt.call_id)
            store.update_stability_index.assert_not_called()

    def test_executor_reports_its_real_receipt_to_progress_feedback(self):
        from tools.tool_executor import ToolExecutor
        executor = ToolExecutor.__new__(ToolExecutor)
        executor._registry = SimpleNamespace(get_entry=lambda name: SimpleNamespace(handler=lambda args: "actual content"))
        executor._update_tools_status = Mock()
        executor._pulse_loop = SimpleNamespace(progress_feedback=self.feedback)
        with patch("core.tool_lesson_tracker.observe_tool_result") as observer, \
             patch("core.interaction_ledger.annotate_result", side_effect=lambda name, result: result):
            self.assertEqual(executor.execute_function_call("read_file", {"path": "a.txt"}), "actual content")
        self.assertEqual(self.feedback.snapshot()["advanced"], 1)
        self.assertEqual(observer.call_args.kwargs["receipt"].call_id, executor._last_action_receipt["call_id"])

    def test_successful_exposure_survives_real_belief_store_round_trip(self):
        import tempfile
        from memory.belief_store import BeliefStore
        with tempfile.TemporaryDirectory() as directory:
            store = BeliefStore(directory)
            bid = store.generate_id("skills")
            store.add_belief(category="skills", belief_id=bid, content="A scoped lesson",
                             confidence=0.5, tool_bindings=["read_file"])
            before = store.get_belief(bid)
            with patch.multiple(lessons, _belief_store=store, _recent_injections=[]):
                lessons.note_lessons_injected([{"belief_id": bid, "tools": ["read_file"]}])
                lessons.observe_tool_result("read_file", {"path": "a.txt"}, "actual content",
                                            context_id="turn:1", lesson_ids={bid})
            after = BeliefStore(directory).get_belief(bid)
            self.assertEqual(after["successful_uses"], 1)
            self.assertEqual(after["verifications"], before["verifications"])
            self.assertEqual(after["stability_index"], before["stability_index"])

    def test_lesson_attribution_does_not_leak_across_threads_or_failed_generations(self):
        from concurrent.futures import ThreadPoolExecutor
        from core.progress_feedback import current_lesson_context, lesson_context
        with self.assertRaises(RuntimeError):
            with lesson_context("foreground:1", {"lesson:1"}):
                self.assertEqual(current_lesson_context(), ("foreground:1", frozenset({"lesson:1"})))
                with ThreadPoolExecutor(max_workers=1) as pool:
                    self.assertEqual(pool.submit(current_lesson_context).result(), ("", frozenset()))
                raise RuntimeError("generation failed")
        self.assertEqual(current_lesson_context(), ("", frozenset()))
