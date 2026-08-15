#!/usr/bin/env python3
"""Bounded branch-oriented action planner tests."""

import unittest

from core.action_planner import ActionPlanner


TOOLS = {
    "web": "Search and read public information",
    "email": "Read, search, and send email",
    "files": "Read and update local files",
}


class ActionPlannerTests(unittest.TestCase):
    def test_material_ambiguity_becomes_one_question(self):
        planner = ActionPlanner(
            lambda _prompt: "ASK | Which Alex should receive the report?"
        )
        plan = planner.plan("Email Alex the report", TOOLS)
        self.assertTrue(plan.waiting_for_input)
        self.assertFalse(plan.ready)
        self.assertEqual(plan.legs, [])

    def test_gather_then_act_uses_separate_scoped_legs(self):
        planner = ActionPlanner(lambda _prompt: "\n".join([
            "LEG | web | Find the confirmed event date | Result includes date and source URL",
            "LEG | email | Send the date and source to Mara | Delivery receipt identifies Mara",
        ]))
        plan = planner.plan("Find the event date and email it to Mara", TOOLS)
        self.assertTrue(plan.ready)
        self.assertEqual([leg.toolset for leg in plan.legs], ["web", "email"])
        self.assertIn("source URL", plan.legs[0].success_check)

    def test_unknown_toolset_and_freeform_claim_are_rejected(self):
        planner = ActionPlanner(lambda _prompt: "I handled it with magic.")
        plan = planner.plan("Do the work", TOOLS)
        self.assertFalse(plan.ready)
        self.assertIn("no usable", plan.error.lower())

        parsed = planner.parse(
            "Do the work",
            "LEG | magic | Do it | It is done",
            TOOLS,
        )
        self.assertFalse(parsed.ready)

    def test_plan_is_hard_capped(self):
        output = "\n".join(
            f"LEG | web | Outcome {index} | Evidence {index}"
            for index in range(8)
        )
        plan = ActionPlanner(lambda _prompt: output, max_legs=4).plan("Research", TOOLS)
        self.assertEqual(len(plan.legs), 4)

    def test_context_and_lessons_are_bounded(self):
        planner = ActionPlanner(
            lambda _prompt: "LEG | web | Find the fact | Source URL and exact fact",
            context_tokens=40,
            lesson_tokens=20,
        )
        plan = planner.plan(
            "Find the fact",
            TOOLS,
            context="context " * 500,
            lessons="lesson " * 500,
        )
        self.assertTrue(plan.ready)
        self.assertIn("[...truncated...]", planner.last_prompt)
        self.assertLess(plan.prompt_tokens, 500)

    def test_prompt_contains_no_full_schema_contract(self):
        planner = ActionPlanner(
            lambda _prompt: "LEG | files | Update the file | Read-back contains the new value"
        )
        planner.plan("Update it", TOOLS)
        self.assertNotIn('"parameters"', planner.last_prompt)
        self.assertNotIn('"properties"', planner.last_prompt)
        self.assertIn("AVAILABLE TOOLSETS", planner.last_prompt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
