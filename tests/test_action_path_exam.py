#!/usr/bin/env python3
"""Regression gate for the runnable modular action-path exam."""

import unittest

from tests.run_action_path_exam import run_exam


class ActionPathExamTests(unittest.TestCase):
    def test_exam_passes_with_bounded_branch_context(self):
        report = run_exam()
        failed = [case["name"] for case in report["cases"] if not case["passed"]]
        self.assertEqual(failed, [])
        self.assertEqual(report["passed"], 7)
        self.assertLess(report["max_planner_tokens"], 500)
        self.assertLess(report["max_branch_frame_tokens"], 900)


if __name__ == "__main__":
    unittest.main(verbosity=2)
