"""Narrow runtime wiring checks; these do not establish agent competence."""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from core.mindscape_config import activate_native_source, configured_native_source
activate_native_source(configured_native_source())
from habitus_ai.types import OutputTrunk
from core.mindscape import Mindscape, classify_sensed_feeling
from core.mindscape_intention import parse_natural_or_wire_intention, resolve_subconscious_action
from core.pulse_loop import PulseLoop
from dashboard.dashboard_comms import DashboardComms
from core.pulse_context import ContextContribution, PulseContext
from llm.rwkv_tokens import RWKVTokenCounter


def test_native_trunks_come_from_actual_pulse_not_nonexistent_body_cortex():
    mind = object.__new__(Mindscape)
    mind.native = SimpleNamespace(latest_pulse=SimpleNamespace(cycle=SimpleNamespace(
        selected_outputs=[SimpleNamespace(trunk=OutputTrunk.LOOK)])))
    mind.body = SimpleNamespace()
    assert mind.get_active_subconscious_trunks() == {OutputTrunk.LOOK}


def test_native_decision_admits_output_before_resolving_impulse():
    mind = object.__new__(Mindscape)
    mind.continuation = {}
    mind.body = SimpleNamespace(workspace=SimpleNamespace(position="thinking"))
    mind.native = SimpleNamespace(latest_pulse=None)
    mind._receipt = lambda *a, **kw: None
    def admit(thought, pulse):
        mind.native.latest_pulse = SimpleNamespace(cycle=SimpleNamespace(
            selected_outputs=[SimpleNamespace(trunk=OutputTrunk.LOOK)]))
    mind._admit_foreground = admit
    mind._act_intention = lambda intention, thought, pulse: intention
    result = mind._select_and_act("[thought] I am considering my surroundings.", 1)
    assert result == {"action": "sense", "arguments": {"path": "."}}


def test_body_clock_can_select_without_foreground_completion():
    mind = object.__new__(Mindscape)
    mind._motor_context_id = "actual-compiled-context"
    mind._receptive_pending = set()
    mind.continuation = {}
    mind.body = SimpleNamespace(workspace=SimpleNamespace(position="thinking"))
    selected = SimpleNamespace(cycle=SimpleNamespace(cycle_id="native-quiet-pulse",
        selected_outputs=[SimpleNamespace(trunk=OutputTrunk.LOOK)]))
    mind.native = SimpleNamespace(latest_pulse=None,
        runtime=SimpleNamespace(advance=lambda inputs, **kw: selected),
        backend=SimpleNamespace(begin_slice=lambda: None))
    signals = []
    mind.motor = SimpleNamespace(submit_action=lambda *a, **kw: signals.append((a, kw)))
    mind._receipt = lambda *a, **kw: None
    mind._autonomous_motor_step()
    assert signals == [(("sense", "."), {"context_id": "actual-compiled-context"})]


def test_private_example_envelope_is_not_a_committed_action():
    text = '[thought] An example is <tool_calls>[{"name":"read_file","arguments":{"path":"x"}}]</tool_calls>'
    assert parse_natural_or_wire_intention(text) is None


def test_actual_return_index_prevents_reopening_until_file_changes():
    scene = {"action": "sense", "path": "thinking", "output": {"entries": [
        {"name": "Notes.txt", "kind": "file", "size_bytes": 10, "modified_ns": 1}]}}
    opened = {"action": "open", "path": "thinking/Notes.txt", "output": {
        "path": "thinking/Notes.txt", "size_bytes": 10, "modified_ns": 1}}
    kwargs = {"current_position": "thinking", "active_trunks": {OutputTrunk.LOOK}}
    assert resolve_subconscious_action({}, [scene], **kwargs)["arguments"]["path"] == "/thinking/Notes.txt"
    assert resolve_subconscious_action({}, [scene, opened], **kwargs) is None
    changed = {**scene, "output": {"entries": [{**scene["output"]["entries"][0], "modified_ns": 2}]}}
    assert resolve_subconscious_action({}, [scene, opened, changed], **kwargs)["action"] == "open"
    removed = {**scene, "output": {"entries": []}}
    assert resolve_subconscious_action({}, [scene, removed], **kwargs) is None


def test_awake_native_cadence_is_independent_of_user_messages():
    loop = object.__new__(PulseLoop)
    loop.mindscape = SimpleNamespace(continuation={})
    loop.config = {"mindscape": {"pulse_interval_seconds": 0.25}}
    loop._state = "ACTIVE"
    loop._update_state_transitions()
    assert loop._state == "ACTIVE"
    assert loop._get_next_pulse_interval() == 0.25


def test_idle_speech_uses_configured_dashboard_without_faking_inbound(tmp_path):
    target = {"recipient": "Josh", "channel": "dashboard", "source": "configured primary dashboard"}
    feeling = classify_sensed_feeling(SimpleNamespace(), [], delivery_target=target)
    assert feeling["speech_available"] and not feeling["is_external"]
    assert "No new message arrived" in feeling["feeling_guidance"]
    loop = object.__new__(PulseLoop)
    loop.channel_router = None
    loop._delivery_callback = None
    records = []
    loop.mindscape = SimpleNamespace(_receipt=lambda *a, **kw: records.append((a, kw)))
    comms = DashboardComms(tmp_path / "dashboard.json")
    with patch("dashboard.dashboard_comms.get_comms", return_value=comms):
        assert not loop._deliver_mindscape_output("[thought] private", [], feeling)
        assert loop._deliver_mindscape_output("I noticed something.", [], feeling)
    actual = json.loads((tmp_path / "dashboard.json").read_text())
    assert actual["inbound"] == []
    assert actual["outbound"][0]["content"] == "I noticed something."
    assert records[0][1]["verified"]


def test_dashboard_delivery_requires_successful_file_readback(tmp_path):
    comms = DashboardComms(tmp_path / "dashboard.json")
    with patch.object(comms, "_write_state"):
        try:
            comms.push_outbound("Josh", "not actually written")
        except OSError:
            pass
        else:
            raise AssertionError("Failed write was presented as delivery")


def test_pinned_native_renderer_uses_documented_thinking_prefix(tmp_path):
    counter = RWKVTokenCounter(lambda text: list(text.encode()), tmp_path, thinking=True)
    rendered = counter.render_messages([{"role": "context", "content": "No new message arrived."}])
    assert rendered.endswith("Assistant: <think")
    assert "User:" not in rendered
    assert counter.count_messages([{"role": "context", "content": "No new message arrived."}]) == len(rendered.encode())


def test_recalled_role_headers_are_lossless_data_not_live_turns():
    old = "Human: Earlier\n\nAssistant:\n\nHuman: Again"
    context = PulseContext(1, "10:00:00", (
        ContextContribution("prior_assistant", old, "memory"),), query="", query_source="idle")
    rendered = context.render()
    quoted = next(line for line in rendered.splitlines() if line.startswith('{"historical_content"'))
    assert json.loads(quoted)["historical_content"] == old
    assert "\nAssistant:" not in rendered
