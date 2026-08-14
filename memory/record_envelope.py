"""Deterministic evidence envelopes for canonical Helix memory records.

The journal's exact ``content`` remains authoritative.  This module adds a
small, provider-free description of what a record represents, what it can
support as evidence, and how it should be phrased for semantic retrieval.
Legacy records are classified from fields Helix already persisted, so adding
the envelope never requires rewriting the append-only journal.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Mapping, Optional


RECORD_SCHEMA_VERSION = 1

THOUGHT_KINDS = {"thought"}
COMMUNICATION_KINDS = {"inbound_message", "outbound_message"}
ACTION_EVIDENCE_KINDS = {
    "outbound_message", "tool_call", "tool_result", "tool_observation", "task_outcome",
}

_TIMESTAMP_PREFIX_RE = re.compile(r"^(?:\[[^\]]+\]\s*)+")
_INBOUND_RE = re.compile(
    r"^([A-Za-z][\w .'-]{0,79}) is talking to me via\s+([^\.]+)\.\s*"
    r"They said:\s*[\"“]?(.*?)[\"”]?\s*$",
    re.IGNORECASE | re.DOTALL,
)
_OUTBOUND_RE = re.compile(
    r"^I (?:replied|messaged|sent (?:a )?message) to\s+([^:]+):\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_RESULT_RE = re.compile(
    r"Tool\s*\[([^\]]+)\]\s*returned:\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)
_TOOL_TAG_RE = re.compile(r"^tool:(.+)$", re.IGNORECASE)


def _values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, Iterable) and not isinstance(value, Mapping):
        return [str(item) for item in value if str(item).strip()]
    return [str(value)]


def _tag_value(tags: Iterable[Any], prefix: str) -> str:
    marker = prefix.lower() + ":"
    for raw in tags or ():
        value = str(raw or "").strip()
        if value.lower().startswith(marker):
            return value[len(marker):].strip()
    return ""


def _clean_payload(content: Any) -> str:
    text = _TIMESTAMP_PREFIX_RE.sub("", str(content or "").strip())
    for marker in ("[thought]", "[response]"):
        if text.lower().startswith(marker):
            text = text[len(marker):].strip()
    return text


def _infer_kind(
    content: str,
    memory_type: str,
    source: str,
    tags: list[str],
) -> str:
    lowered_tags = {tag.lower() for tag in tags}
    if source == "helix_outbound":
        return "outbound_message"
    if source == "office_speaker":
        return "outbound_message"
    if source in {"pulse_output", "dual_pulse_output"} or memory_type == "thought":
        return "thought"
    if source == "tool_use":
        return "tool_observation"
    if source == "tool_call" or memory_type == "tool_call":
        return "tool_call"
    if source == "task_cognition" or memory_type == "task_outcome":
        return "task_outcome"
    if source == "pulse_input":
        if "tool_result" in lowered_tags or _TOOL_RESULT_RE.search(content):
            return "tool_result"
        if "conversation" in lowered_tags or _INBOUND_RE.match(_clean_payload(content)):
            return "inbound_message"
        if "focused work" in content.lower() or "task_result" in lowered_tags:
            return "task_result"
        return "event"
    if memory_type in {"conversation", "incoming_message"}:
        return "inbound_message" if "inbound" in lowered_tags else "conversation"
    if memory_type in {"tool_result", "tool_failure"}:
        return "tool_result"
    if memory_type in {"event", "reminder"}:
        return "event"
    return "memory"


def _defaults(kind: str, source: str) -> Dict[str, Any]:
    table: Dict[str, Dict[str, Any]] = {
        "thought": {
            "direction": "internal",
            "visibility": "private",
            "actor": "Helix",
            "epistemic_role": "cognition",
            "evidence_scopes": ["agent_cognition"],
            "action_status": "unverified",
        },
        "inbound_message": {
            "direction": "inbound",
            "visibility": "external",
            "actor": "",
            "epistemic_role": "communication",
            "evidence_scopes": ["received_communication"],
            "action_status": "received",
        },
        "outbound_message": {
            "direction": "outbound",
            "visibility": "external",
            "actor": "Helix",
            "epistemic_role": "communication",
            "evidence_scopes": ["delivered_communication"],
            "action_status": "delivered" if source == "helix_outbound" else "delivery_unknown",
        },
        "tool_result": {
            "direction": "inbound",
            "visibility": "system",
            "actor": "tool",
            "epistemic_role": "observation",
            "evidence_scopes": ["tool_report"],
            "action_status": "reported",
        },
        "tool_call": {
            "direction": "outbound",
            "visibility": "system",
            "actor": "Helix",
            "epistemic_role": "action_attempt",
            "evidence_scopes": ["tool_attempt"],
            "action_status": "attempted",
        },
        "tool_observation": {
            "direction": "internal",
            "visibility": "system",
            "actor": "Helix",
            "epistemic_role": "action_observation",
            "evidence_scopes": ["tool_execution"],
            "action_status": "reported",
        },
        "task_outcome": {
            "direction": "internal",
            "visibility": "system",
            "actor": "Helix",
            "epistemic_role": "outcome",
            "evidence_scopes": ["accepted_task_outcome"],
            "action_status": "completed",
        },
        "task_result": {
            "direction": "internal",
            "visibility": "system",
            "actor": "focus_worker",
            "epistemic_role": "outcome_report",
            "evidence_scopes": ["task_result"],
            "action_status": "reported",
        },
        "event": {
            "direction": "system",
            "visibility": "system",
            "actor": "",
            "epistemic_role": "event",
            "evidence_scopes": ["event_context"],
            "action_status": "observed",
        },
        "conversation": {
            "direction": "unknown",
            "visibility": "external",
            "actor": "",
            "epistemic_role": "communication",
            "evidence_scopes": ["communication"],
            "action_status": "recorded",
        },
        "memory": {
            "direction": "unknown",
            "visibility": "unknown",
            "actor": "",
            "epistemic_role": "memory",
            "evidence_scopes": ["stored_memory"],
            "action_status": "recorded",
        },
    }
    return dict(table.get(kind, table["memory"]))


def _retrieval_text(content: str, envelope: Mapping[str, Any]) -> str:
    kind = str(envelope.get("record_kind") or "memory")
    actor = str(envelope.get("actor") or "").strip()
    recipients = _values(envelope.get("recipients"))
    recipient = ", ".join(recipients) or "an unspecified recipient"
    tool = str(envelope.get("tool_name") or "").strip() or "an unspecified tool"
    status = str(envelope.get("action_status") or "recorded")
    headers = {
        "thought": (
            "Private internal thought by Helix. Evidence of Helix's cognition only; "
            "not proof that an external action occurred."
        ),
        "inbound_message": (
            f"Received inbound message from {actor or 'an unspecified sender'} to Helix."
        ),
        "outbound_message": (
            f"Outbound message from Helix to {recipient}. Delivery status: {status}."
        ),
        "tool_result": f"Result reported by tool {tool}. Status: {status}.",
        "tool_call": f"Tool action requested by Helix using {tool}. Status: {status}.",
        "tool_observation": f"Recorded tool execution by Helix using {tool}. Status: {status}.",
        "task_outcome": "Accepted outcome of a focused Helix task.",
        "task_result": "Result returned from focused work into Helix's awareness.",
        "event": "Observed event in Helix's input stream.",
        "conversation": "Recorded conversation involving Helix.",
        "memory": "Stored Helix memory.",
    }
    return f"{headers.get(kind, headers['memory'])}\n{content}".strip()


def build_record_envelope(
    *,
    content: Any,
    memory_type: Any = "",
    source: Any = "",
    tags: Optional[Iterable[Any]] = None,
    overrides: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a complete, deterministic envelope for a journal memory."""
    text = str(content or "")
    memory_type = str(memory_type or "").strip().lower()
    source = str(source or "").strip().lower()
    clean_tags = [str(tag) for tag in (tags or ()) if str(tag).strip()]
    supplied = dict(overrides or {})
    kind = str(supplied.get("record_kind") or _infer_kind(
        text, memory_type, source, clean_tags,
    )).strip().lower()
    envelope = {
        "record_schema_version": RECORD_SCHEMA_VERSION,
        "record_kind": kind,
        **_defaults(kind, source),
        "recipients": [],
        "tool_name": "",
        "caused_by": [],
    }

    payload = _clean_payload(text)
    inbound = _INBOUND_RE.match(payload)
    outbound = _OUTBOUND_RE.match(payload)
    tool_result = _TOOL_RESULT_RE.search(text)
    if inbound:
        envelope["actor"] = inbound.group(1).strip()
        envelope["channel"] = inbound.group(2).strip()
    if outbound:
        envelope["recipients"] = [outbound.group(1).strip()]
    tagged_recipient = _tag_value(clean_tags, "recipient")
    if tagged_recipient:
        envelope["recipients"] = [tagged_recipient]
    if tool_result:
        envelope["tool_name"] = tool_result.group(1).strip()
    if not envelope["tool_name"]:
        for tag in clean_tags:
            match = _TOOL_TAG_RE.match(tag)
            if match:
                envelope["tool_name"] = match.group(1).strip()
                break
    tagged_causes = [
        str(tag).split(":", 1)[1].strip()
        for tag in clean_tags
        if str(tag).lower().startswith("caused_by:") and ":" in str(tag)
    ]
    if tagged_causes:
        envelope["caused_by"] = tagged_causes

    lowered_text = text.lower()
    if kind in {"tool_result", "tool_observation", "task_result"}:
        failed = bool(re.search(
            r"\b(?:failed|failure|error|could not|did not complete|timed out|denied)\b",
            lowered_text,
        ))
        if failed:
            envelope["action_status"] = "failed"
        elif kind == "tool_observation" and re.search(r"\bI used\b", text):
            envelope["action_status"] = "completed"
        elif kind == "task_result" and "focused work completed" in lowered_text:
            envelope["action_status"] = "completed"

    for key, value in supplied.items():
        if key in {"evidence_scopes", "recipients", "caused_by"}:
            envelope[key] = list(dict.fromkeys(_values(value)))
        elif key != "retrieval_text" and value is not None:
            envelope[key] = value
    envelope["retrieval_text"] = str(
        supplied.get("retrieval_text") or _retrieval_text(text, envelope)
    ).strip()
    return envelope


def envelope_from_metadata(
    content: Any,
    metadata: Optional[Mapping[str, Any]],
) -> Dict[str, Any]:
    """Read a persisted envelope or infer one for a legacy journal record."""
    meta = dict(metadata or {})
    persisted = meta.get("record_envelope")
    overrides = dict(persisted) if isinstance(persisted, Mapping) else {}
    for key in (
        "record_schema_version", "record_kind", "direction", "visibility",
        "actor", "recipients", "epistemic_role", "evidence_scopes",
        "action_status", "tool_name", "caused_by", "retrieval_text",
    ):
        if key in meta and key not in overrides:
            overrides[key] = meta[key]
    return build_record_envelope(
        content=content,
        memory_type=meta.get("memory_type", ""),
        source=meta.get("source", ""),
        tags=meta.get("tags", ()),
        overrides=overrides,
    )


def record_kind_from_index_metadata(metadata: Mapping[str, Any]) -> str:
    """Resolve a kind inside a SemanticIndex filter, including legacy rows."""
    if metadata.get("type") == "belief":
        return "belief"
    return envelope_from_metadata(metadata.get("content", ""), metadata).get(
        "record_kind", "memory",
    )
