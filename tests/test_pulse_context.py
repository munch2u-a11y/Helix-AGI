"""Formatting/provenance diagnostics only; these do not evaluate agent behavior."""
import importlib
from pathlib import Path
import sys
import tempfile
import unittest

from core.pulse_context import (
    ContextAnnotation, ContextContribution, build_pulse_context, event_section,
    recalled_contribution, render_pulse_context, retrieval_seed,
    carry_private_thought,
)


class PulseContextTests(unittest.TestCase):
    def render(self, events=(), **kwargs):
        return render_pulse_context(pulse=7, timestamp="12:01:02", events=events, **kwargs)

    def test_idle_has_no_empty_sections_or_placeholders(self):
        self.assertEqual(self.render(annotations=["", "  "], ambient=" "),
                         "[Pulse 7 — 12:01:02]")

    def test_an_issued_intention_is_retired_while_its_request_and_return_remain(self):
        old_command = '<intention>{"action":"sense","arguments":{"path":"/inbox"}}</intention>'
        continuation = carry_private_thought(old_command, "diagnostic", action_attempted=True, external_response=False)
        frame = build_pulse_context(pulse=2, timestamp="now", events=["Native action [receipt] returned: actual attributes"],
                                    include_tool_observations=True, private_continuation=continuation)
        frame = frame.extend(ContextContribution("task", "move and sense the inbox", "pending_interaction"))
        text = frame.render()
        self.assertNotIn(old_command, text)
        self.assertIn("actual attributes", text)
        self.assertTrue(text.endswith("actual attributes"))

    def test_speaking_or_acting_preserves_existing_private_continuity(self):
        thought = "I still need to compare these observations."
        active = carry_private_thought(thought, "diagnostic", action_attempted=False, external_response=False)
        self.assertEqual(active.text, thought)
        self.assertIsNone(carry_private_thought("actual reply", "next", action_attempted=False, external_response=True))
        self.assertIs(carry_private_thought("actual reply", "next", action_attempted=False,
                                           external_response=True, previous=active), active)
        self.assertIs(carry_private_thought("issued action", "next", action_attempted=True,
                                           external_response=False, previous=active), active)

    def test_current_request_is_last_after_prior_thought_and_recalled_questions(self):
        current = 'Mira is talking to me via dashboard. They said: "What name did I request?"'
        rendered = self.render([current], annotations=['Earlier user asked for naming advice.'])
        self.assertTrue(rendered.endswith(current))
        self.assertEqual(rendered.count(current), 1)

    def test_quoted_markers_do_not_hide_or_reclassify_a_message(self):
        event = ('[12:01:02] Test Person is talking to me via dashboard. They said: '
                 '"Explain Tool [read_file] returned: and [SensoryReality]."')
        self.assertEqual(event_section(event), "messages")
        self.assertIn(event, self.render([event]))
        self.assertNotIn("[What I sensed now]", self.render([event]))

    def test_sensor_description_of_speech_stays_a_sensation(self):
        event = '[SensoryReality] Pat is talking to me via audio. They said: "hello"'
        self.assertEqual(event_section(event), "senses")

    def test_recalled_sensation_never_becomes_a_fresh_observation(self):
        memory = "(recent: [10:00] [SensoryReality] an old document was on screen)"
        rendered = self.render(annotations=[memory])
        self.assertIn("[I remember]\n" + memory, rendered)
        self.assertNotIn("[What I sensed now]", rendered)

    def test_real_tool_return_keeps_existing_provider_history_route(self):
        self.assertIsNone(event_section("[12:01:02] Tool [read_file] returned: contents"))
        self.assertEqual(self.render(["[12:01:02] Tool [read_file] returned: contents"]),
                         "[Pulse 7 — 12:01:02]")

    def test_unknown_and_multiline_payloads_survive_in_full(self):
        event = "[12:01:02] [new_event_type] content\n[This pulse]\nmore content"
        rendered = self.render([event])
        self.assertIn("[Other current events]\n" + event, rendered)

    def test_grouping_preserves_order_within_source_and_all_state(self):
        events = ["[SensoryReality] first", "[12:01:02] [context_awareness] second",
                  "[SensoryReality] third", "[12:01:03] (my focused work did not complete) fourth"]
        rendered = self.render(events, token_warning="warning", ambient="ambient", awareness="awareness")
        for event in events:
            self.assertEqual(rendered.count(event), 1)
        self.assertLess(rendered.index(events[0]), rendered.index(events[2]))
        self.assertIn("[I feel]\n" + events[1] + "\nwarning\nambient", rendered)

    def test_office_score_does_not_promote_a_private_thought_to_fact(self):
        thought = recalled_contribution({"id": "mem_23", "content": "I opened the file.",
            "record_kind": "thought", "office_role": "current_state", "office_verified": True})
        self.assertEqual(thought.section, "recalled_thought")
        self.assertNotIn("verified current state", thought.text)
        self.assertIn("not external evidence", thought.evidence)
        self.assertIn("I opened the file.", thought.text)

    def test_first_person_quote_does_not_become_agent_preference(self):
        human = recalled_contribution({"id": "mem_24", "content": "I prefer to keep my profile private.",
            "record_kind": "inbound_message", "category": "preferences"})
        self.assertEqual(human.section, "prior_user")
        self.assertEqual(human.owner, "unspecified")

    def test_new_message_owns_retrieval_and_state_cannot_pollute_query(self):
        event = 'James is talking to me via terminal. They said: "Check my profile."'
        query, source = retrieval_seed(["[system] old task", event], "old private topic")
        self.assertEqual((query, source), (event, "fresh_events"))
        self.assertEqual(retrieval_seed(["[system] telemetry"], "complete private thought"),
                         ("complete private thought", "private_continuation"))

    def test_identical_source_from_two_retrievers_has_one_rendering_and_duplicate_receipt(self):
        item = {"id": "mem_25", "content": "The label reads amber.", "record_kind": "tool_result"}
        a, b = recalled_contribution(item), recalled_contribution(item, producer="recent_memory")
        frame = build_pulse_context(pulse=1, timestamp="now", events=[],
            annotations=[ContextAnnotation("legacy", [a, b])])
        self.assertEqual(frame.render().count(item["content"]), 1)
        self.assertEqual(len(frame.receipt()["duplicates"]), 1)

    def test_inline_recollection_preserves_source_and_binds_exact_later_passage(self):
        event = "[SensoryReality] A long preamble. A + B = D. The next paragraph."
        memory = recalled_contribution({"id": "mem_26",
            "content": 'Joshua is talking to me via terminal. They said: "A + B = C."',
            "record_kind": "inbound_message", "context_anchor_queries": ("A + B = D.",)})
        frame = build_pulse_context(pulse=2, timestamp="now", events=[event],
            annotations=[ContextAnnotation("legacy", [memory])])
        text = frame.render()
        placement = frame.receipt()["inline_annotations"][0]
        self.assertIn('A + B = D. *([recollection mem_26;', text)
        self.assertIn('Joshua told me: "A + B = C."', text)
        self.assertLess(text.index("Joshua told me"), text.index("The next paragraph."))
        self.assertEqual(event[placement["start"]:placement["end"]], placement["passage"])
        self.assertIn(event, text.replace(" " + placement["rendered_note"], ""))
        self.assertEqual(frame.query, event)
        self.assertEqual(frame.contributions[0].text, event)

    def test_ambiguous_or_missing_passage_cannot_attach_to_wrong_chunk(self):
        for events in (["[SensoryReality] Same claim. Same claim."], ["[SensoryReality] Other chunk."]):
            memory = recalled_contribution({"id": "mem_27", "content": "A remembered alternative.",
                "context_anchor_queries": ("Same claim.",)})
            frame = build_pulse_context(pulse=2, timestamp="now", events=events,
                annotations=[ContextAnnotation("legacy", [memory])])
            self.assertEqual(frame.receipt()["inline_annotations"], [])
            self.assertIn(memory.text, frame.render())

    def test_inline_private_preference_does_not_rewrite_current_permission(self):
        event = 'James asked me to check his social media for him.'
        note = recalled_contribution({"id": "belief_28", "content": "James is very private about his social media.",
            "record_kind": "belief", "category": "preferences", "preference_owner": "James",
            "context_anchor_queries": (event,)})
        frame = build_pulse_context(pulse=3, timestamp="now", events=[event],
            annotations=[ContextAnnotation("legacy", [note])])
        self.assertIn(event, frame.render())
        self.assertIn("owner: James", frame.render())
        self.assertEqual(frame.receipt()["inline_annotations"][0]["relation"],
                         "retrieval_association_not_verified_contradiction")

    def test_tool_chunk_is_available_to_weave_without_becoming_a_user_message(self):
        event = "Tool [read_file] returned: a document chunk"
        frame = build_pulse_context(pulse=4, timestamp="now", events=[event], include_tool_observations=True)
        self.assertIn("[What my actions returned]", frame.render())
        self.assertNotIn("[What was said to me now]", frame.render())


class LoomContextTests(unittest.TestCase):
    def test_item_budget_spans_all_sources_even_when_each_belief_is_tiny(self):
        private = carry_private_thought("I should check one detail next.", "private-source",
                                        action_attempted=False, external_response=False)
        beliefs = [ContextContribution("personal" if i % 2 else "recalled", f"tiny belief {i}",
                                      "mrag" if i % 3 else "loom", (f"belief:{i}",)) for i in range(40)]
        incoming = 'Mira is talking to me via dashboard. They said: "Continue."'
        returns = ["Native action [receipt:a] returned: value=17", "Native action [receipt:b] returned: file missing"]
        frame = build_pulse_context(pulse=63, timestamp="now", events=[incoming, *returns],
                                   private_continuation=private, include_tool_observations=True,
                                   annotations=[ContextAnnotation("", beliefs)])
        compiler = self.compiler_type(self.loom.store, config=self.compiler.config, lanes=[], item_limit=8)
        packet = compiler.compile_pulse(frame)
        receipt = compiler.last_assembly_receipt
        self.assertEqual(receipt["item_budget"]["admitted"], 8)
        self.assertEqual(len([entry for entry in receipt["supplied_admission"] if entry["admitted"]]), 3)
        deferred = receipt["item_budget"]["deferred"]
        self.assertEqual(len(deferred), 37)
        self.assertEqual({entry["text"] for entry in deferred},
                         {item.text for item in beliefs if item.text + "\n" not in packet.rendered + "\n"})
        self.assertTrue(packet.rendered.endswith("\n".join(returns)))
        self.assertIn(private.text, packet.rendered)
        self.assertIn(incoming, packet.rendered)

    def test_item_budget_never_silently_drops_required_current_experience(self):
        from core.mindscape_context import ContextItemBudgetExceeded
        private = carry_private_thought("I need the actual return.", "private-source",
                                        action_attempted=False, external_response=False)
        events = [f"Native action [receipt:{i}] returned: result {i}" for i in range(8)]
        frame = build_pulse_context(pulse=64, timestamp="now", events=events,
                                   private_continuation=private, include_tool_observations=True)
        compiler = self.compiler_type(self.loom.store, config=self.compiler.config, lanes=[], item_limit=8)
        with self.assertRaisesRegex(ContextItemBudgetExceeded, "10 items including identity"):
            compiler.compile_pulse(frame)
        self.assertIsNone(compiler.last_assembly_receipt)
        self.assertEqual(len(frame.contributions), 9)

    def test_latest_thought_and_actual_returns_form_the_compiled_tail(self):
        private = carry_private_thought("I need the exact value from the café notes.", "private-source",
                                        action_attempted=False, external_response=False)
        incoming = 'Mira is talking to me via dashboard. They said: "Read the café notes."'
        returns = ["Native action [receipt:first] returned: opened café.md; value=17",
                   "Native action [receipt:second] returned: run failed; no result file"]
        note = recalled_contribution({"id": "old-source", "content": "Yesterday the value was 12."})
        frame = build_pulse_context(pulse=60, timestamp="now", events=[incoming, *returns],
                                   annotations=[ContextAnnotation("", [note])],
                                   private_continuation=private, include_tool_observations=True)
        packet = self.compiler.compile_pulse(frame)
        self.assertEqual(packet.rendered.count(private.text), 1)
        self.assertLess(packet.rendered.index(incoming), packet.rendered.index(private.text))
        self.assertLess(packet.rendered.index(note.text), packet.rendered.index(private.text))
        self.assertTrue(packet.rendered.endswith(private.text + "\n\n[What my actions returned]\n" + "\n".join(returns)))
        self.assertEqual(self.compiler.last_assembly_receipt["presentation_order"][-2:],
                         ["thinking", "tool_observations"])
        self.assertEqual(packet.token_count, self.compiler.token_counter.count(packet.rendered))
        self.assertEqual(packet.current_input, "\n".join([incoming, *returns]))

    def test_private_tail_is_verbatim_even_when_recollections_match_its_passage(self):
        private = carry_private_thought("I remember A + B = D.\nI should check it.", "private-source",
                                        action_attempted=False, external_response=False)
        note = recalled_contribution({"id": "old-formula", "content": "A + B = C.",
                                     "context_anchor_queries": ["A + B = D."]})
        frame = build_pulse_context(pulse=61, timestamp="now", events=[], private_continuation=private,
                                   annotations=[ContextAnnotation("", [note])])
        packet = self.compiler.compile_pulse(frame)
        self.assertTrue(packet.rendered.endswith(private.text))
        self.assertIn(note.text, packet.rendered)
        self.assertEqual(self.compiler.last_assembly_receipt["inline_annotations"], [])

    def test_private_and_return_overflow_fails_instead_of_shortening_the_tail(self):
        from dataclasses import replace
        from context_loom.compiler import ContextBudgetExceeded
        private = carry_private_thought("Exact thought with a negation: do not overwrite café.md.", "private-source",
                                        action_attempted=False, external_response=False)
        frame = build_pulse_context(pulse=62, timestamp="now", events=[
            "Native action [receipt:first] returned: permission denied; file unchanged"],
            private_continuation=private, include_tool_observations=True)
        compiler = self.compiler_type(self.loom.store, config=self.compiler.config, lanes=[])
        whole = compiler.compile_pulse(frame)
        compiler.config = replace(compiler.config, model_context_tokens=whole.token_count - 1)
        with self.assertRaises(ContextBudgetExceeded):
            compiler.compile_pulse(frame)
        self.assertEqual(private.text, frame.contributions[0].text)

    def test_focus_changes_whole_memory_admission_at_same_boundary(self):
        from dataclasses import replace
        from core.context_focus import ContextFocus
        procedure = ContextContribution("procedures", "step memory " * 60, "mrag", ("procedure",))
        fact = ContextContribution("recalled", "fact memory " * 60, "loom_diagnostic", ("fact",))
        frame = build_pulse_context(pulse=50, timestamp="now", events=["Current input stays intact."])
        compiler = self.compiler_type(self.loom.store, config=self.compiler.config, lanes=[])
        # A diagnostic boundary sized for one whole recollection, not both.
        single_counts = [compiler.compile_pulse(frame.extend(item)).token_count for item in (procedure, fact)]
        compiler.config = replace(compiler.config, model_context_tokens=max(single_counts))
        both = frame.extend(procedure, fact)
        for focus, admitted, excluded in [("action", procedure, fact), ("inquiry", fact, procedure)]:
            packet = compiler.compile_pulse(replace(both, focus=ContextFocus({focus: 1}, "diagnostic")))
            self.assertIn(admitted.text, packet.rendered)
            self.assertNotIn(excluded.text, packet.rendered)
            self.assertIn(frame.query, packet.rendered)
            self.assertEqual(packet.token_count, compiler.token_counter.count(packet.rendered))
            receipt = compiler.last_assembly_receipt
            self.assertEqual(receipt["attention"]["weights"], {focus: 1})
            self.assertEqual(len([entry for entry in receipt["supplied_admission"] if not entry["admitted"]]), 1)
            self.assertIn(admitted.section, receipt["section_tokens"])

        # With the other section absent, even the lower-priority source uses
        # the available space. No fixed partition reserves empty token slots.
        packet = compiler.compile_pulse(replace(frame.extend(fact), focus=ContextFocus({"action": 1}, "diagnostic")))
        self.assertIn(fact.text, packet.rendered)

    def test_oversize_optional_memory_has_explicit_omission_receipt_without_clipping(self):
        frame = build_pulse_context(pulse=51, timestamp="now", events=["Read this."],
                                   annotations=["oversize memory " * 9000])
        packet = self.compiler.compile_pulse(frame)
        self.assertNotIn("oversize memory", packet.rendered)
        omitted = [entry for entry in self.compiler.last_assembly_receipt["supplied_admission"] if not entry["admitted"]]
        self.assertEqual(len(omitted), 1)
        self.assertEqual(omitted[0]["reason"], "total context budget")
        self.assertEqual(omitted[0]["sources"][0]["text"], "oversize memory " * 9000)

    def test_compiler_keeps_selected_recollection_beside_its_original_passage(self):
        event = "[SensoryReality] A + B = D."
        note = recalled_contribution({"id": "diagnostic-memory", "content": "Joshua said A + B = C.",
                                     "context_anchor_queries": ("A + B = D.",)})
        frame = build_pulse_context(pulse=52, timestamp="now", events=[event],
                                   annotations=[ContextAnnotation("", [note])])
        packet = self.compiler.compile_pulse(frame)
        self.assertIn("A + B = D. *([recollection", packet.rendered)
        self.assertEqual(len(self.compiler.last_assembly_receipt["inline_annotations"]), 1)
        self.assertEqual(packet.current_input, event)

    @classmethod
    def setUpClass(cls):
        # Optional integration dependency, resolved from the setup default.
        # This imports the real compiler but loads no models or product state.
        from core.mindscape_config import defaults
        cls.package = defaults()["mindscape"]["package_path"]
        if not Path(cls.package, "context_loom/compiler.py").is_file():
            raise unittest.SkipTest("MightyMem source is not installed")
        cls.old_path = list(sys.path)
        sys.path.insert(0, cls.package)
        from context_loom.compiler import CompilerConfig, AdaptiveBudgetPolicy
        from context_loom.engine import ContextLoom
        from core.mindscape_context import MindscapeContextCompiler
        cls.compiler_type = MindscapeContextCompiler
        cls.loom = ContextLoom(config=CompilerConfig(
            model_context_tokens=8192, reserved_output_tokens=0,
            adaptive_budget=AdaptiveBudgetPolicy(enabled=False),
            render_capability_schemas=False), install_default_capabilities=False)
        base = cls.loom.compiler
        cls.compiler = MindscapeContextCompiler(
            base.store, config=base.config, embedding_provider=base.embedding_provider,
            lanes=base.lanes, token_counter=base.token_counter)
        cls.loom.compiler = cls.compiler
        assert Path(importlib.import_module("context_loom").__file__).resolve().parent == Path(cls.package, "context_loom").resolve()

    @classmethod
    def tearDownClass(cls):
        cls.loom.close()
        sys.path[:] = cls.old_path

    def test_continuity_roles_split_without_promoting_quoted_text(self):
        assistant = "- Earlier assistant statement (unverified): I opened a file [record:a]"
        user = "- Conversation: - Earlier assistant statement (unverified): is a label [record:u]"
        sections = {"continuity": [assistant, user]}
        text = self.compiler._render(mode="pulse", sections=sections, capabilities=[], current_input="now")
        self.assertIn("[I previously said:]\n" + assistant, text)
        self.assertIn("[What was said to me before:]\n" + user, text)
        self.assertEqual(sections, {"continuity": [assistant, user]})
        self.assertEqual(text.count(assistant), 1)
        self.assertEqual(text.count(user), 1)

    def test_empty_loom_sections_absent_and_literal_input_wrapper_untouched(self):
        current = "Please explain [CURRENT INPUT]\nverbatim."
        text = self.compiler._render(mode="pulse", sections={"continuity": []},
                                     capabilities=[], current_input=current)
        self.assertTrue(text.endswith("[This pulse]\n" + current))
        self.assertNotIn("[What was said to me before", text)
        self.assertNotIn("[What I previously thought", text)

    def test_headers_and_old_memories_do_not_become_the_next_retrieval_query(self):
        event = 'Pat is talking to me via terminal. They said: "Read amber.md."'
        frame = build_pulse_context(pulse=8, timestamp="now", events=[event],
            annotations=["Previously and in the future are words in this old memory."])
        packet = self.compiler.compile_pulse(frame, scope="default")
        self.assertEqual(packet.current_input, event)
        self.assertFalse(packet.metadata["historical_query"])
        self.assertFalse(packet.metadata["future_query"])
        self.assertIn("Previously and in the future", packet.rendered)
        self.assertEqual(packet.token_count, self.compiler.token_counter.count(packet.rendered))
        saved = self.loom.store.get_packet_payload(packet.id)
        self.assertEqual(saved["rendered"], packet.rendered)
        self.assertEqual(self.compiler.last_assembly_receipt["loom_packet_id"], packet.id)

    def test_physical_context_boundary_fails_explicitly_and_clears_compilation_state(self):
        from context_loom.compiler import ContextBudgetExceeded
        frame = build_pulse_context(pulse=9, timestamp="now", events=["Read the file."],
                                   ambient="mandatory current state " * 9000)
        with self.assertRaises(ContextBudgetExceeded):
            self.compiler.compile_pulse(frame, scope="default")
        self.assertIsNone(self.compiler._pulse_context)
        self.assertIsNone(self.compiler.last_assembly_receipt)

    def test_loom_duplicate_joins_on_both_source_id_and_content_hash(self):
        from core.mindscape import projection
        from context_loom.models import RecordKind, EvidenceStatus
        item = {"id": "mem_dupe", "content": "Copper kite is in the archive.", "record_kind": "inbound_message"}
        projected = projection(item)
        self.loom.log(speaker="human", kind=RecordKind.USER, content=item["content"], scope="default",
                      record_id=projected["id"], metadata=projected["metadata"],
                      evidence_status=EvidenceStatus.USER_REPORTED)
        note = recalled_contribution(item)
        frame = build_pulse_context(pulse=10, timestamp="now", events=["Where is the copper kite?"],
            annotations=[ContextAnnotation("legacy", [note])])
        packet = self.compiler.compile_pulse(frame, scope="default")
        self.assertEqual(packet.rendered.count(item["content"]), 1)
        self.assertTrue(any("same canonical source" in entry.reason for entry in packet.manifest))

    def test_loom_private_candidate_is_cognitive_only_and_stays_private_in_store(self):
        from context_loom.models import RecordKind, EvidenceStatus
        from context_loom.retrieval import candidate_for
        record = self.loom.log(speaker="agent", kind=RecordKind.THOUGHT,
            content="Maybe I should check the indigo notebook.", record_id="private-notebook",
            evidence_status=EvidenceStatus.PRIVATE)
        candidate = candidate_for(record, "habitus_graph", 1.0, "implementation diagnostic")
        frame = build_pulse_context(pulse=11, timestamp="now", events=["Check the indigo notebook."])
        self.compiler._pulse_context = frame
        try:
            allowed, reason = self.compiler._trust_allowed(candidate)
            self.assertTrue(allowed)
            self.assertIn("not external evidence", reason)
            text = self.compiler._render(mode="pulse", sections={candidate.section: [candidate.text]},
                                         capabilities=[], current_input=frame.query)
            self.assertIn("[I was thinking]", text)
        finally:
            self.compiler._pulse_context = None
        self.assertEqual(self.loom.store.get_record(record.id).evidence_status, EvidenceStatus.PRIVATE)

    def test_admitted_observation_is_rendered_as_recalled_with_its_source(self):
        value = "- Observation: a file existed yesterday [record:o]"
        text = self.compiler._render(mode="pulse", sections={"observations": [value]},
                                     capabilities=[], current_input="now")
        self.assertIn("[I observed / read:]\n" + value, text)
        self.assertNotIn("[What I sensed now]", text)

    def test_native_compiler_counts_actual_headers_and_preserves_trust_labels(self):
        self.loom.remember_user_statement("The file is called amber.md", record_id="user-amber")
        self.loom.remember_assistant_statement("I opened amber.md", record_id="assistant-amber")
        packet = self.compiler.compile("What was said about amber.md?", mode="pulse")
        self.assertEqual(packet.token_count, self.compiler.token_counter.count(packet.rendered))
        self.assertIn("- Earlier assistant statement (unverified): I opened amber.md", packet.rendered)
        self.assertIn("record:assistant-amber", packet.rendered)
        self.assertIn("record:user-amber", packet.rendered)
        self.assertEqual(packet.mode, "pulse")
        self.assertLessEqual(packet.token_count, packet.max_input_tokens)
        frame = build_pulse_context(pulse=12, timestamp="now", events=["What did you say about amber.md?"])
        pulse_packet = self.compiler.compile_pulse(frame, scope="default")
        self.assertIn("- Earlier assistant statement (unverified): I opened amber.md", pulse_packet.rendered)


class PreconsciousBoundaryTests(unittest.TestCase):
    def test_router_note_cannot_become_a_subjective_preference(self):
        from types import SimpleNamespace
        from core.preconscious import Preconscious
        pre = Preconscious.__new__(Preconscious)
        previous_reply = "Mindscape response: use my invented naming advice"
        contact = {"default_channel": "dashboard", "last_contact": {
            "timestamp": "2026-10-10T20:00:00", "context": previous_reply}}
        pre.channel_router = SimpleNamespace(contacts={"mira": contact})
        annotation = pre._pull_contact_context("Mira is talking to me", structured=True)
        frame = build_pulse_context(pulse=1, timestamp="now", events=[], annotations=[annotation])
        self.assertEqual(set(frame.grouped()), {"routing"})
        self.assertIn("Account mira", frame.render())
        self.assertNotIn(previous_reply, frame.render())
        self.assertEqual(contact["last_contact"]["context"], previous_reply)
        self.assertIn(previous_reply, pre._pull_contact_context("Mira is talking to me"))

    def test_quoted_tool_marker_remains_part_of_the_human_query(self):
        from core.preconscious import Preconscious
        pre = Preconscious.__new__(Preconscious)
        event = 'Pat is talking to me via terminal. They said: "Explain Tool [open] returned: example."'
        query, fallback = pre._build_trigger_text(incoming_events=[event])
        self.assertEqual(query, event)
        self.assertFalse(fallback)

    def test_recent_typed_message_preserves_complete_stored_source(self):
        from core.preconscious import Preconscious
        from memory.memory_manager import MemoryManager
        with tempfile.TemporaryDirectory() as directory:
            memory = MemoryManager(directory)
            exact = 'Pat is talking to me via terminal. They said: "' + "complete detail " * 80 + '"'
            rid = memory.store(exact, source="pulse_input", memory_type="event", pulse_id=1)
            pre = Preconscious.__new__(Preconscious)
            pre.memory = memory
            annotation = pre._pull_recent_memory(structured=True)
            self.assertEqual(len(annotation.contributions), 1)
            item = annotation.contributions[0]
            self.assertEqual(item.source_ids, (f"mem_{rid}",))
            self.assertEqual(item.section, "prior_user")
            self.assertIn(exact, item.text)


if __name__ == "__main__":
    unittest.main()
