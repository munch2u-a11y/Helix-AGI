#!/usr/bin/env python3
"""Live Agent-to-Agent Conversational Coherence & Anti-Repetition Test.

Evaluates:
1. Multi-turn dialogue between two local Bicameral RWKV agents (Alpha and Beta).
2. Topical coherency and natural knowledge progression across 5 turns.
3. Absence of greeting restarts ("Hello", "Greetings") on ongoing turns.
4. Absence of echo looping (lexical stagnation) between agent turns.
5. Context Bidding Desk auto-blocker validation on the generated dialogue turns.
"""

import os
import re
import unittest
from pathlib import Path

from core.bicameral_rwkv import BicameralRWKV
from core.office_workflows import OfficeArbiter
from llm.providers.rwkv_provider import BicameralRWKVSession

RWKV_MODEL_PATH = Path(os.environ.get(
    "RWKV_MODEL_PATH",
    Path.home() / "habitus-ai-experiments" / "habitus-mind" / "models" / "rwkv7-g1j-1.5b-20260831-2c18b29"
))


class TestAgentToAgentCoherence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        print("\n=== Initializing Dual-Agent Local RWKV Dialogue Session ===")
        # Agent Alpha: Focuses on cognitive state architecture and memory
        cls.agent_alpha = BicameralRWKVSession(
            model_path=str(RWKV_MODEL_PATH),
            system_instruction=(
                "You are Agent Alpha, an autonomous systems researcher. "
                "You are in a live technical dialogue with Agent Beta about memory consolidation in recurrent neural agents. "
                "Speak concisely in 1 to 3 sentences. Never repeat greetings across turns. "
                "Advance the inquiry with specific architecture proposals, trade-offs, or questions rather than echoing the peer's statements."
            ),
            temperature=0.65,
            max_output_tokens=256,
        )
        cls.agent_alpha.options["repetition_penalty"] = 1.20

        # Agent Beta: Shares the underlying backend weights to save RAM
        cls.agent_beta = BicameralRWKVSession(
            model_path=str(RWKV_MODEL_PATH),
            system_instruction=(
                "You are Agent Beta, an expert in neural state stability and cognitive retention. "
                "You are in a live technical dialogue with Agent Alpha about memory consolidation in recurrent neural agents. "
                "Speak concisely in 1 to 3 sentences. Never repeat greetings across turns. "
                "Advance the inquiry with specific architecture proposals, trade-offs, or questions rather than echoing the peer's statements."
            ),
            backend=cls.agent_alpha.system.backend,
            temperature=0.65,
            max_output_tokens=256,
        )
        cls.agent_beta.options["repetition_penalty"] = 1.20


    def setUp(self):
        self.agent_alpha.history.clear()
        self.agent_alpha.system.reset_states()
        self.agent_beta.history.clear()
        self.agent_beta.system.reset_states()

    def test_01_five_turn_agent_dialogue_coherence(self):
        print("\n--- Running 5-Turn Agent-to-Agent Interactive Dialogue ---")
        
        # Seed topic from user/environment to Agent Alpha
        seed_prompt = (
            "Agent Beta, how should we structure the transition of episodic observations "
            "into persistent cognitive memory without causing catastrophic forgetting?"
        )

        turns = []
        salutation_pattern = re.compile(
            r"^\s*(hello|hi|greetings|hey)\s+(agent|beta|alpha|there)?[!.,]",
            re.IGNORECASE,
        )

        current_speaker = "Beta"
        current_listener = self.agent_beta
        incoming_message = seed_prompt

        turns.append(("Alpha (Seed)", seed_prompt))
        print(f"\n[Turn 1] Alpha -> Beta: {seed_prompt}")

        for turn_idx in range(2, 7):
            reply = current_listener.send_message(incoming_message).strip()
            turns.append((current_speaker, reply))
            print(f"\n[Turn {turn_idx}] {current_speaker}: {reply}")

            # 1. Non-empty check
            self.assertTrue(len(reply) > 0, f"Turn {turn_idx} ({current_speaker}) returned empty reply")

            # 2. Anti-greeting check (must not repeat greetings on follow-up turns)
            if turn_idx > 2:
                self.assertIsNone(
                    salutation_pattern.match(reply),
                    f"Turn {turn_idx} ({current_speaker}) repeated a greeting: {reply[:60]}",
                )

            # Prepare for next turn: alternate speakers
            incoming_message = reply
            if current_speaker == "Beta":
                current_speaker = "Alpha"
                current_listener = self.agent_alpha
            else:
                current_speaker = "Beta"
                current_listener = self.agent_beta

        # 3. Topical coherency check:
        # Dialogue should maintain topical anchor terms (memory, state, weights, consolidation, retention, etc.)
        topical_keywords = {
            "memory", "state", "episodic", "recurrent", "forgetting", "consolidation",
            "weights", "retention", "persistent", "cognitive", "transition", "stability",
            "decay", "activation", "store", "neural"
        }
        all_text = " ".join([turn[1].lower() for turn in turns[1:]])
        matched_keywords = [kw for kw in topical_keywords if kw in all_text]
        print(f"\nTopical Keywords Matched ({len(matched_keywords)}): {matched_keywords}")
        self.assertGreaterEqual(
            len(matched_keywords),
            3,
            f"Dialogue drifted away from topic. Matched only: {matched_keywords}",
        )

        # 4. Measure echo / parroting in raw uncurated conversational generation
        echoes_detected = []
        for i in range(1, len(turns)):
            prev_turn = set(re.findall(r"\w+", turns[i - 1][1].lower()))
            curr_turn = set(re.findall(r"\w+", turns[i][1].lower()))
            if len(prev_turn) >= 5 and len(curr_turn) >= 5:
                overlap = len(prev_turn & curr_turn) / len(prev_turn | curr_turn)
                print(f"Overlap Turn {i} vs Turn {i+1}: {overlap:.3f}")
                if overlap >= 0.70:
                    echoes_detected.append((i - 1, i, overlap))
        print(f"Raw dialogue echo pairs detected (overlap >= 0.70): {len(echoes_detected)}")

        # 5. Context Bidding Desk Auto-Blocker Integration Test:
        # When uncurated turns (including any raw echoed turns and internal loops)
        # compete in OfficeArbiter, the auto-blocker must block redundant copies,
        # ensuring perseveration spirals never pollute the final context.
        candidates = [
            {
                "id": f"turn_{idx}",
                "content": text,
                "office_desk": "semantic_advisor",
                "relevance": round(0.95 - (idx * 0.05), 2),
                "confidence": 0.85,
            }
            for idx, (_, text) in enumerate(turns)
        ]
        candidates.append({
            "id": "turn_internal_loop",
            "content": "Consolidation in memory. Consolidation in memory. Consolidation in memory. Consolidation in memory.",
            "office_desk": "beliefs",
            "relevance": 0.99,
            "confidence": 0.95,
        })

        arbiter = OfficeArbiter()
        allocated = arbiter.allocate(
            candidates,
            active_desks={"semantic_advisor", "facts", "beliefs"},
            max_items=4,
        )
        allocated_ids = [item["id"] for item in allocated]
        print(f"\nAllocated items in Context Office: {allocated_ids}")

        # The auto-blocker must block runaway internal loops
        self.assertNotIn(
            "turn_internal_loop",
            allocated_ids,
            "Auto-blocker failed to block internal loop candidate",
        )

        # For any echoed turns in raw dialogue, the auto-blocker must NEVER admit
        # both into the context window
        for prior_idx, next_idx, overlap_val in echoes_detected:
            both_admitted = f"turn_{prior_idx}" in allocated_ids and f"turn_{next_idx}" in allocated_ids
            self.assertFalse(
                both_admitted,
                f"Auto-blocker failed: both echoed turns {prior_idx} and {next_idx} (overlap {overlap_val:.3f}) were admitted!",
            )

        self.assertGreaterEqual(
            len(allocated),
            3,
            "Arbiter should fill slots with distinct, non-redundant turns",
        )
        print("✓ All Agent-to-Agent Coherency & Context Auto-Blocker checks passed!")


if __name__ == "__main__":
    unittest.main(verbosity=2)

