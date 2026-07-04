import unittest
import numpy as np

# We provide a mock tokenizer decode function
def mock_decode(token_ids):
    # For testing, we map some token IDs to characters/strings
    # 0: '{[((', 1: '))]}', 2: 'query_memory(', 3: 'foo="bar")', 4: 'search_db(', 5: ' '
    vocab = {
        0: '{[((',
        1: '))]}',
        2: 'query_memory(',
        3: 'foo="bar")',
        4: 'search_db(',
        5: ' '
    }
    return "".join([vocab.get(tid, "") for tid in token_ids])

from llm.constrained_decoding import FSMLogitsProcessor

class TestConstrainedDecoding(unittest.TestCase):
    def setUp(self):
        # We only allow the tool "query_memory" for this test grammar
        self.processor = FSMLogitsProcessor(
            tokenizer_decode=mock_decode,
            tokenizer_vocab_size=6,
            allowed_tool_names=['query_memory']
        )

    def test_in_monologue_state(self):
        # input_ids simulating regular text
        input_ids = [5, 5, 5]
        scores = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6], dtype=np.float32)
        original_scores = scores.copy()
        
        # Processor should do nothing
        new_scores = self.processor(input_ids, scores)
        np.testing.assert_array_equal(new_scores, original_scores)

    def test_in_action_state_masks_illegal_tokens(self):
        # input_ids simulating we just output the start tag '{[(('
        input_ids = [0]
        
        # Suppose the model hallucinated and wants to output 'search_db(' (id 4) as the most likely token
        scores = np.array([-10.0, -10.0, 5.0, -10.0, 10.0, 2.0], dtype=np.float32)
        
        new_scores = self.processor(input_ids, scores)
        
        # 'search_db(' (id 4) breaks the regex ^query_memory\(.*?\)
        # So it should be masked to -inf
        self.assertEqual(new_scores[4], -np.inf)
        
        # 'query_memory(' (id 2) is a valid prefix, so it should keep its score
        self.assertEqual(new_scores[2], 5.0)

    def test_closes_action_tag(self):
        # input_ids simulating '{[((', 'query_memory(', 'foo="bar")'
        input_ids = [0, 2, 3]
        
        scores = np.array([1.0, 2.0, 3.0, 4.0, 5.0, 6.0], dtype=np.float32)
        new_scores = self.processor(input_ids, scores)
        
        # Since 'query_memory(foo="bar")' is complete, closing tag '))]}' (id 1) is valid
        self.assertEqual(new_scores[1], 2.0)

if __name__ == "__main__":
    unittest.main()
