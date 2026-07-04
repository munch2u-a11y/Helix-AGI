import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bootstrap.seed_builder import (
    BootstrapContext,
    build_seed_bundle,
    canonicalize_bootstrap_profile,
)


class BootstrapSeedBuilderTests(unittest.TestCase):
    def _context(self, profile: str) -> BootstrapContext:
        return BootstrapContext(
            agent_name="Nova",
            creator_name="Morgan",
            profile=profile,
            personality="professional",
            wake_time="07:30",
            sleep_time="22:15",
            channels=["Dashboard", "Telegram"],
        )

    def test_profile_aliases_canonicalize(self):
        self.assertEqual(canonicalize_bootstrap_profile("birth"), "basic")
        self.assertEqual(canonicalize_bootstrap_profile("prepared"), "standard")
        self.assertEqual(canonicalize_bootstrap_profile("developed"), "predeveloped")
        self.assertEqual(canonicalize_bootstrap_profile("pre-developed"), "predeveloped")

    def test_dynamic_names_appear_in_seed_beliefs_and_memories(self):
        bundle = build_seed_bundle(self._context("standard"))
        all_beliefs = [
            belief
            for beliefs in bundle["beliefs"].values()
            for belief in beliefs
        ]
        belief_text = "\n".join(belief["content"] for belief in all_beliefs)
        terms = [belief.get("term", "") for belief in all_beliefs]
        memory_text = "\n".join(memory["content"] for memory in bundle["memories"])

        self.assertIn("Nova", belief_text)
        self.assertIn("Morgan", belief_text)
        self.assertIn("Nova", terms)
        self.assertIn("Morgan", terms)
        self.assertIn("07:30", belief_text)
        self.assertIn("22:15", belief_text)
        self.assertIn("Dashboard and Telegram", belief_text)
        self.assertIn("Morgan", memory_text)

    def test_profile_depth_increases_seed_counts(self):
        basic = build_seed_bundle(self._context("basic"))
        standard = build_seed_bundle(self._context("standard"))
        predeveloped = build_seed_bundle(self._context("predeveloped"))

        def total_beliefs(bundle):
            return sum(len(items) for items in bundle["beliefs"].values())

        self.assertLess(total_beliefs(basic), total_beliefs(standard))
        self.assertLess(total_beliefs(standard), total_beliefs(predeveloped))
        self.assertLess(len(basic["memories"]), len(standard["memories"]))
        self.assertLess(len(standard["memories"]), len(predeveloped["memories"]))

    def test_bootstrap_seed_omits_tool_call_lore(self):
        bundle = build_seed_bundle(self._context("predeveloped"))
        text = "\n".join(
            belief["content"]
            for beliefs in bundle["beliefs"].values()
            for belief in beliefs
        )

        disallowed = [
            "reply",
            "send_message",
            "memory_recall",
            "read_file",
            "terminal",
            "browse",
            "git_status",
            "journal tool",
            "scratchpad tool",
        ]
        lowered = text.lower()
        for token in disallowed:
            self.assertNotIn(token, lowered)


if __name__ == "__main__":
    unittest.main()
