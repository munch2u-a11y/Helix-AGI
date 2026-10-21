"""Protocol diagnostics with controlled text; not live agent evidence."""
import tempfile
import unittest
import threading
from contextlib import nullcontext
import numpy as np
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from llm.providers.rwkv_provider import BicameralRWKVSession
from core.mindscape_intention import decode_foreground
from llm.rwkv_tokens import RWKVTokenCounter
from core.bicameral_rwkv import BicameralRWKV


class ProtocolTests(unittest.TestCase):
    def session(self, outputs):
        def generate(prompt, **options):
            self.assertIsNone(options['max_new_tokens'])
            system.last_generation_receipt = {'prompt_tokens': len(prompt.encode()),
                                               'generated_tokens': 1, 'done_reason': 'eos'}
            return next(outputs)
        system = SimpleNamespace(backend=SimpleNamespace(encode=lambda x: list(x.encode())),
                                 device='cpu', generate_language=generate)
        with tempfile.TemporaryDirectory() as directory:
            with patch('llm.providers.rwkv_provider.BicameralRWKV', return_value=system):
                session = BicameralRWKVSession(directory, system_instruction='system')
        return session

    def test_thought_is_fresh_and_raw_receipt_is_retained(self):
        session = self.session(iter(['<think>considering</think>First reply', 'Second reply']))
        self.assertEqual(session.send_message('first'), 'First reply')
        self.assertEqual(session.last_contemplation, 'considering')
        self.assertEqual(session.send_message('second'), 'Second reply')
        self.assertEqual(session.last_contemplation, '')
        self.assertEqual(session.last_context_receipt['raw_foreground'], 'Second reply')
        self.assertEqual(session.last_context_receipt['done_reason'], 'eos')

    def test_private_pulse_never_becomes_public_history(self):
        session = self.session(iter(['<think>still considering</think>']))
        session.context_decoder = decode_foreground
        text = session.send_context('question')
        self.assertTrue(text.startswith('[thought]'))
        session.finish_context(['question'], text, delivered=False)
        self.assertEqual(session.history, [{'role': 'user', 'content': 'question'}])

    def test_wrong_commit_is_rejected(self):
        session = self.session(iter(['reply']))
        session.send_context('question')
        with self.assertRaises(ValueError):
            session.finish_context(['question'], 'other', delivered=True)

    def test_direct_speech_accounting_matches_evaluated_input(self):
        session = self.session(iter(['Direct reply']))
        session.options['direct_speech'] = True
        text = session.send_context('hello')
        self.assertEqual(text, 'Direct reply')

    def test_render_messages_does_not_duplicate_trailing_assistant_role(self):
        messages = [
            {'role': 'user', 'content': 'User: Hi\nAssistant: Hello\nUser: What is 2+2?\nAssistant:'}
        ]
        rendered = RWKVTokenCounter.render_messages(messages)
        self.assertFalse(rendered.endswith('Assistant:\nAssistant:') or rendered.endswith('Assistant:\n\nAssistant:'), f'Duplicate role detected: {rendered}')
        self.assertTrue(rendered.endswith('\n\nAssistant:'), f'Did not end with Assistant: {rendered}')

    def test_full_input_boundary_fails_without_clipping(self):
        with tempfile.TemporaryDirectory() as directory:
            counter = RWKVTokenCounter(lambda x: list(x.encode()), directory)
        messages = [{'role': 'user', 'content': 'complete content'}]
        with self.assertRaises(ValueError):
            counter.check_request(messages, 1)
        self.assertEqual(messages[0]['content'], 'complete content')

    def generator(self, text):
        # Exercise the production sampler's protocol with a controlled token
        # stream. This checks neither neural inference nor agent competence.
        generator = object.__new__(BicameralRWKV)
        cursor = iter(text.encode())

        class Logits:
            def __init__(self):
                self.value = np.zeros(256)
                self.value[next(cursor, 0)] = 10
            def __getitem__(self, key): return self
            def detach(self): return self
            def float(self): return self
            def cpu(self): return self
            def numpy(self): return self.value

        generator.backend = SimpleNamespace(encode=lambda s: list(s.encode()),
                                           decode=lambda ids: bytes(ids).decode(), eos_token_id=0)
        generator.torch = SimpleNamespace(inference_mode=nullcontext, tensor=lambda x, **kw: x)
        generator.device = 'cpu'
        generator.language_state = None
        generator.cancel_event = threading.Event()
        generator.generation_progress = None
        generator.step_language = lambda *args, **kw: Logits().value
        generator.model = lambda **kw: SimpleNamespace(state=None, logits=Logits())
        generator.feedback_language_to_sensory = lambda **kw: None
        return generator

    def test_single_newline_human_role_ends_assistant_turn(self):
        generator = self.generator('Actual reply\nUser: invented incoming message')
        output = generator.generate_language('prompt', temperature=0)
        self.assertEqual(output, 'Actual reply')
        self.assertEqual(generator.last_generation_receipt['done_reason'], 'conversation_boundary')

    def test_timestamped_human_role_ends_assistant_turn(self):
        generator = self.generator('Actual reply\n[01:05:05]\nUser: invented incoming message')
        output = generator.generate_language('prompt', temperature=0)
        self.assertEqual(output, 'Actual reply')
        self.assertEqual(generator.last_generation_receipt['done_reason'], 'conversation_boundary')

    def test_leading_assistant_echo_does_not_abort_generation(self):
        generator = self.generator('\nAssistant: Actual reply\nUser: next turn')
        output = generator.generate_language('prompt', temperature=0)
        self.assertEqual(output.strip(), 'Assistant: Actual reply')
        self.assertEqual(generator.last_generation_receipt['done_reason'], 'conversation_boundary')

    def test_leading_double_newline_assistant_echo_does_not_abort_generation(self):
        generator = self.generator('\n\nAssistant: Actual reply\nUser: next turn')
        output = generator.generate_language('prompt', temperature=0)
        self.assertEqual(output.strip(), 'Assistant: Actual reply')
        self.assertEqual(generator.last_generation_receipt['done_reason'], 'conversation_boundary')


    def test_explicit_output_boundary_rejects_partial_result(self):
        generator = self.generator('unfinished output')
        with self.assertRaisesRegex(RuntimeError, 'incomplete generation withheld'):
            generator.generate_language('prompt', temperature=0, max_new_tokens=2)
        self.assertEqual(generator.last_generation_receipt['done_reason'], 'configured_output_boundary')

    def test_repeated_leading_assistant_echo_does_not_abort_generation(self):
        generator = self.generator('Assistant:\n\nAssistant: Actual reply\nUser: next turn')
        output = generator.generate_language('prompt', temperature=0)
        self.assertIn('Actual reply', output)
        self.assertEqual(generator.last_generation_receipt['done_reason'], 'conversation_boundary')


    def test_bracketed_scaffold_stops_generation(self):
        generator = self.generator('Actual reply\n\n[What I want to do:] Invented plan\nUser: next turn')
        output = generator.generate_language('prompt', temperature=0)
        self.assertEqual(output.strip(), 'Actual reply')
        self.assertEqual(generator.last_generation_receipt['done_reason'], 'conversation_boundary')


if __name__ == '__main__':
    unittest.main()
