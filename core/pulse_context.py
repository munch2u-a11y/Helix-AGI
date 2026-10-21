"""Conditional pulse headings; source content is never summarized or clipped here.

The established event queue holds translated strings, not typed envelopes.
Classify only their outer form: markers quoted inside a message are its content.
Unknown forms remain visible instead of guessing their provenance.
"""
from __future__ import annotations

import re
import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass
from typing import Mapping, Sequence
from core.context_focus import ContextFocus, infer_focus


_TIMESTAMP = re.compile(r"^\[\d{2}:\d{2}:\d{2}\]\s*")
_MESSAGE = re.compile(r"^[^\n]+? is talking to me via [^\n]+?\. They said:")
_TOOL_RESULT = re.compile(r"^(?:Tool|Native action) \[[^\]\n]+\] returned:")
_INTERNAL = re.compile(r"^\[(?:system|context_awareness|stability_(?:drift|warning|critical|recovered)|context reset)\]")

SECTION_TITLES = {
    "messages": "What was said to me now",
    "senses": "I sense now (live hardware):",
    "environment": "In my digital workspace (filesystem):",
    "module": "The operational module in my focus:",
    "tool_observations": "What my actions returned",
    "work": "What I am working on:",
    "task": "I want to:",
    "thinking": "My most recent private thought",
    "recalled_thought": "I was thinking:",
    "personal": "I prefer / value:",
    "associations": "Associations coming to mind:",
    "recalled": "I remember:",
    "prior_user": "What was said to me before:",
    "prior_assistant": "I previously said:",
    "observations": "I observed / read:",
    "procedures": "Procedures I recall:",
    "summary": "A summary I recall:",
    "topical": "My topic orientation:",
    "reminders": "Reminders surfacing now:",
    "other": "Other current events:",
    "state": "I feel:",
    "abilities": "My ability awareness:",
    "direction": "My current output direction:",
    "routing": "Who I am interacting with:",
}

COGNITIVE_SECTIONS = {"thinking", "recalled_thought", "personal", "associations"}

CONTEXT_GUIDANCE = (
    "Continue my private stream from my most recent thought, taking account of current messages, "
    "surroundings and actual action returns. Earlier recollections retain their sources; "
    "my private thought expresses my perspective and intentions. Action returns tell me what happened. "
    "An unfinished line of thought can continue over later pulses. When information is missing, "
    "use an available information source."
)

# Background recollections precede the current situation. The causal tail is
# always the latest private thought followed by real returns, next to inference.
PULSE_SECTION_ORDER = (
    "summary", "personal", "recalled", "prior_user", "prior_assistant",
    "observations", "recalled_thought", "associations", "procedures", "topical",
    "reminders", "state", "abilities", "direction", "routing", "environment",
    "module", "senses", "other", "task", "messages", "work",
    "thinking", "tool_observations",
)


@dataclass(frozen=True)
class ContextContribution:
    section: str
    text: str
    producer: str
    source_ids: tuple[str, ...] = ()
    kind: str = "context"
    evidence: str = "unverified"
    owner: str = "unspecified"
    source_content_sha256: str = ""
    anchor_queries: tuple[str, ...] = ()
    inline_note: str = ""

    def receipt(self):
        return {**asdict(self), "sha256": hashlib.sha256(self.text.encode()).hexdigest()}


class ContextAnnotation(str):
    """Legacy string API with typed contributions for the modular renderer."""

    def __new__(cls, text, contributions):
        value = super().__new__(cls, text)
        value.contributions = tuple(contributions)
        return value


def carry_private_thought(thought, memory_id, *, action_attempted, external_response,
                          contemplation=None, previous=None):
    """Keep private cognition independent of speaking or acting.

    An explicit private channel wins over the public output of the same pulse.
    Speech, issued commands and errors cannot replace the latest private
    thought. Without new private content the prior contribution remains intact.
    """
    if contemplation and contemplation.strip():
        private = contemplation
    elif thought and thought.startswith("[thought]"):
        private = thought[len("[thought]"):].lstrip()
    elif (not thought or action_attempted or external_response
          or thought.startswith(("[internal error:", "[no LLM session", "<intention>"))):
        return previous
    else:
        private = thought
    if not private.strip():
        return previous
    return ContextContribution(
        "thinking", private, "foreground_private", (f"mem_{memory_id}",),
        "thought", "private thought, not external evidence", "agent",
        hashlib.sha256(("[thought] " + private).encode()).hexdigest())


def recalled_contribution(item: Mapping, *, producer="mrag") -> ContextContribution:
    """Route by persisted type, never by words such as 'I' inside a quote.

    A retrieval desk's coverage/score cannot verify a source's claims. In
    particular, an old state report remains a recollection and a human's
    preference never becomes the agent's own preference by rephrasing it.
    """
    envelope = item.get("record_envelope") or {}
    kind = envelope.get("kind") or envelope.get("record_kind") or item.get("record_kind") or item.get("memory_type") or "memory"
    category = item.get("category") or item.get("_category")
    lane = item.get("lane", "recall")
    section = {
        "thought": "recalled_thought", "inbound_message": "prior_user",
        "outbound_message": "prior_assistant", "tool_result": "observations",
        "tool_observation": "observations", "task_outcome": "observations",
        "task_result": "observations", "tool_call": "observations",
    }.get(kind, "recalled")
    evidence = {
        "thought": "private thought, not external evidence",
        "inbound_message": "reported by speaker",
        "outbound_message": "earlier assistant claim, not external verification",
        "tool_call": "attempt only, no completion established",
        "belief": "derived belief, consult its sources",
    }.get(kind, "stored report, verification not established by retrieval")
    if section == "recalled":
        if category in {"preferences", "premises", "values", "identity", "feelings"} or kind == "preference":
            section = "personal"
        elif lane in {"spatial", "associative"} or item.get("association_linked"):
            section = "associations"
        elif category == "skills":
            section = "procedures"
    owner = str(envelope.get("preference_owner") or item.get("preference_owner") or "unspecified")
    source_ids = (str(item["id"]),) if item.get("id") is not None else ()
    labels = [f"source:{','.join(source_ids) or 'unidentified'}", f"via:{producer}/{lane}",
              f"kind:{kind}", evidence]
    if item.get("created_at"):
        labels.append(f"recorded:{item['created_at']}")
    if section == "personal":
        labels.append(f"preference owner:{owner}")
    if envelope.get("action_status") or item.get("action_status"):
        labels.append(f"action status:{envelope.get('action_status') or item['action_status']}")
    raw = str(item["content"])
    sanitized = raw
    if "[SensoryReality]" in sanitized:
        sanitized = sanitized.replace("[SensoryReality]", "I remember sensing:")
    if sanitized.startswith("[thought]"):
        sanitized = sanitized[len("[thought]"):].strip()

    if kind == "inbound_message":
        message = _TIMESTAMP.sub("", sanitized, count=1)
        wrapper = _MESSAGE.match(message)
        actor = envelope.get("actor")
        if wrapper:
            actor = actor or message.split(" is talking to me via ", 1)[0]
        note = f"{actor} told me: {message[wrapper.end():].strip()}" if wrapper and actor else f"I recall a received message: {sanitized}"
    elif kind == "thought":
        note = f"An earlier private thought comes to mind: {sanitized}"
    elif kind == "outbound_message":
        note = f"I previously said this: {sanitized}"
    elif section == "personal":
        note = f"I recall this preference or value (owner: {owner}): {sanitized}"
    elif section == "associations":
        note = f"This brings an association to mind: {sanitized}"
    else:
        note = f"I recall a stored {kind.replace('_', ' ')}: {sanitized}"
    header_label = f"(Recorded: {item['created_at']})" if item.get("created_at") else f"(Memory {','.join(source_ids) or 'unidentified'})"
    return ContextContribution(section, f"{header_label}\n{sanitized}",
                               producer, source_ids, kind, evidence, owner,
                               hashlib.sha256(raw.encode()).hexdigest(),
                               tuple(item.get("context_anchor_queries") or ()), note)


def retrieval_events(events: Sequence[str]) -> list[str]:
    """Fresh external content, including native tool returns, without telemetry."""
    return [event for event in events if event.strip() and event_section(event) != "state"]


def retrieval_seed(events: Sequence[str], private_thought: str = "") -> tuple[str, str]:
    fresh = retrieval_events(events)
    if fresh:
        return "\n".join(fresh), "fresh_events"
    if private_thought.strip():
        return private_thought, "private_continuation"
    return "Continue this pulse.", "idle"


@dataclass(frozen=True)
class PulseContext:
    pulse: int
    timestamp: str
    contributions: tuple[ContextContribution, ...]
    query: str
    query_source: str
    focus: ContextFocus | None = None

    def extend(self, *contributions):
        return PulseContext(self.pulse, self.timestamp, self.contributions + tuple(contributions),
                            self.query, self.query_source, self.focus)

    def selected(self):
        seen = set()
        selected, excluded = [], []
        for item in self.contributions:
            # A summary citing the same IDs is not an identical source body.
            identity = (item.source_ids, item.source_content_sha256)
            if item.source_ids and item.source_content_sha256 and identity in seen:
                excluded.append({**item.receipt(), "reason": "same source and content already present"})
            else:
                selected.append(item)
                seen.add(identity)
        return selected, excluded

    def grouped(self, additional: Mapping[str, Sequence[str]] | None = None):
        sections = defaultdict(list)
        selected = self.selected()[0]
        placements, anchored = self.inline_placements()
        for index, contribution in enumerate(selected):
            if index in anchored:
                continue
            if contribution.section not in SECTION_TITLES:
                raise ValueError(f"Unknown context section: {contribution.section}")
            if contribution.text.strip():
                text = contribution.text
                if index in placements:
                    pieces, cursor = [], 0
                    for placement in sorted(placements[index], key=lambda item: item["end"]):
                        pieces.append(text[cursor:placement["end"]])
                        pieces.append(" " + placement["rendered_note"])
                        cursor = placement["end"]
                    pieces.append(text[cursor:])
                    text = "".join(pieces)
                sections[contribution.section].append(text)
        for key, values in (additional or {}).items():
            if key not in SECTION_TITLES:
                raise ValueError(f"Unknown context section: {key}")
            sections[key].extend(value for value in values if value.strip())
        return dict(sections)

    def inline_placements(self):
        """Attach only to a unique exact passage returned by a search head.

        Offsets refer to the original untouched event/thought. Failed or
        ambiguous anchors remain in their ordinary source section. Nothing
        here decides truth, contradicts a claim, or grants/revokes authority.
        """
        selected = self.selected()[0]
        # The latest private thought is verbatim continuity. Recollections may
        # annotate fresh passages, but must not rewrite that private output.
        targets = [(index, item) for index, item in enumerate(selected)
                   if item.producer == "pulse_event"]
        placements, anchored = defaultdict(list), set()
        for index, item in enumerate(selected):
            if not item.inline_note:
                continue
            for query in item.anchor_queries:
                words = query.split()
                if not words:
                    continue
                pattern = re.compile(r"\s+".join(re.escape(word) for word in words))
                matches = [(target_index, target, match) for target_index, target in targets
                           for match in pattern.finditer(target.text)]
                if len(matches) != 1:
                    continue
                target_index, target, match = matches[0]
                # Escape recalled source Markdown so it cannot close the
                # presentation tag. Canonical source text remains untouched.
                note = re.sub(r"([\\*_\[\]])", r"\\\1", item.inline_note)
                label = ",".join(item.source_ids) or item.producer
                rendered_note = f"*([recollection {label}; {item.evidence}] {note})*"
                placements[target_index].append({
                    "source_ids": list(item.source_ids), "target_ids": list(target.source_ids),
                    "start": match.start(), "end": match.end(),
                    "target_sha256": hashlib.sha256(target.text.encode()).hexdigest(),
                    "passage": match.group(), "retrieval_query": query,
                    "rendered_note": rendered_note, "relation": "retrieval_association_not_verified_contradiction",
                })
                anchored.add(index)
                break
        return dict(placements), anchored

    def render(self, additional=None):
        sections = self.grouped(additional)
        blocks = [f"[Pulse {self.pulse} — {self.timestamp}]"]
        for section in PULSE_SECTION_ORDER:
            title = SECTION_TITLES[section].rstrip(":")
            if sections.get(section):
                values = sections[section]
                if section in {"prior_user", "prior_assistant", "recalled_thought"}:
                    # Recalled role delimiters are data, not live conversation
                    # turns. Preserve every byte through a lossless JSON view.
                    values = [json.dumps({"historical_content": value}, ensure_ascii=False) for value in values]
                blocks.append(f"[{title}]\n" + "\n".join(values))
        return "\n\n".join(blocks)

    def receipt(self):
        selected, excluded = self.selected()
        return {"pulse": self.pulse, "query": self.query, "query_source": self.query_source,
                "presentation_order": [key for key in PULSE_SECTION_ORDER if any(
                    item.section == key for item in selected)],
                "contributions": [item.receipt() for item in selected], "duplicates": excluded,
                "inline_annotations": [item for values in self.inline_placements()[0].values() for item in values]}


def event_section(event: str) -> str | None:
    text = _TIMESTAMP.sub("", event, count=1)
    if text.startswith("[SensoryReality]"):
        return "senses"
    if _TOOL_RESULT.match(text):
        # Preserve the existing route: native tool returns live in provider
        # history and preconscious observations, not a duplicate full payload.
        return None
    if text.startswith("(my focused work "):
        return "work"
    if text.startswith("(a reminder surfaces)"):
        return "reminders"
    if _INTERNAL.match(text):
        return "state"
    # Event markers inside the speaker's payload do not change its source.
    if _MESSAGE.match(text):
        return "messages"
    return "other"


def build_pulse_context(
    *,
    pulse: int,
    timestamp: str,
    events: Sequence[str],
    annotations: Sequence[str] | None = None,
    ambient: str | None = None,
    token_warning: str | None = None,
    awareness: str | None = None,
    private_continuation: ContextContribution | None = None,
    include_tool_observations: bool = False,
) -> PulseContext:
    contributions = []
    if private_continuation is not None:
        contributions.append(private_continuation)
    for index, event in enumerate(events):
        if event.strip():
            section = event_section(event)
            if section is None and include_tool_observations:
                section = "tool_observations"
            if section is not None:
                contributions.append(ContextContribution(
                    section, event, "pulse_event", (getattr(event, "event_id", f"pulse:{pulse}:event:{index}"),),
                    "fresh_event", "event report"))
    # An annotation containing a sensory/message marker is still recalled
    # material. It must never be promoted to a fresh event by its wording.
    for value in annotations or ():
        if isinstance(value, ContextAnnotation):
            contributions.extend(value.contributions)
        elif value.strip():
            contributions.append(ContextContribution("recalled", value, "legacy_annotation"))
    for value in (token_warning, ambient):
        if value and value.strip():
            contributions.append(ContextContribution("state", value, "pulse_state"))
    if awareness and awareness.strip():
        contributions.append(ContextContribution("abilities", awareness, "task_cognition"))

    query, source = retrieval_seed(events, private_continuation.text if private_continuation else "")
    return PulseContext(pulse, timestamp, tuple(contributions), query, source,
                        infer_focus(query, source))


def render_pulse_context(**kwargs) -> str:
    return build_pulse_context(**kwargs).render()
