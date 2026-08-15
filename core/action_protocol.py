"""Provider-neutral contracts for trustworthy Helix actions.

The language model may propose work and describe what it observed, but it
does not get to declare an external action successful.  This module converts
tool returns into typed receipts and evaluates those receipts against small,
deterministic verification rules.

The contracts deliberately contain no model prompts and no tool schemas.
They can therefore be shared by hosted focus sessions, local directed tool
passes, and future computer-use branches without expanding the main context.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence
from uuid import uuid4


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


class ReceiptStatus(str, Enum):
    SUCCESS = "success"
    FAILED = "failed"
    BLOCKED = "blocked"
    UNKNOWN = "unknown"


class EvidenceLevel(str, Enum):
    NONE = "none"
    OBSERVED = "observed"
    CONFIRMED = "confirmed"


class VerificationStatus(str, Enum):
    VERIFIED = "verified"
    PARTIAL = "partial"
    FAILED = "failed"
    NO_ACTION = "no_action"


_FAILURE_RE = re.compile(
    r"(?:^|\n)\s*(?:tool\s+error|error\b|unknown\s+tool|failed\b|failure\b|"
    r"could\s+not\b|couldn't\b|unable\s+to\b|timed?\s*out\b|command\s+failed\b|"
    r"search\s+failed\b|browser\s+(?:navigation|interaction)\s+failed\b|"
    r"screenshot\s+failed\b|no\s+contact\s+record\b|invalid\b|"
    r"(?:[a-z0-9_' -]+\s+)?required\.?$|"
    r"no\s+(?:url|file_id|task_id|event_id|query|search\s+query)\s+provided\b)",
    re.IGNORECASE,
)
_OPERATIONAL_FAILURE_RE = re.compile(
    r"(?:\b(?:xdotool|subprocess|playwright|browser|desktop|application|window|"
    r"command)\s+(?:error|failed|not\s+found|not\s+installed)\b|"
    r"\bno\s+page\s+loaded\b|"
    r"\bfailed\s+to\s+(?:open|load|send|write|read|click|type|focus|execute)\b|"
    r"\b(?:not\s+configured|tool\s+executor\s+unavailable)\b)",
    re.IGNORECASE,
)
_BLOCKED_RE = re.compile(
    r"(?:blocked|not\s+allowed|not\s+on\s+(?:the\s+)?whitelist|access\s+denied|"
    r"permission\s+denied|authorization\s+required|requires?\s+authorization)",
    re.IGNORECASE,
)
_STRONG_SUCCESS_RE = re.compile(
    r"(?:\bsent\s+to\b|\bmessage\s+id\b|\bemail\s+sent\b|\breplied\s+to\b|"
    r"\bcreated\b|\bsaved\b|\bwritten\b|\bupdated\b|\bdeleted\b|\buploaded\b|"
    r"\bshared\b|\bcommitted\b|\bpushed\b|\bcompleted(?:,|\s+with)?\b|"
    r"\bmarked\s+(?:as\s+)?(?:read|complete)\b|\bcomment\s+added\b|"
    r"\b(?:up|down)voted\b|\bfollowed\b|\bunfollowed\b|"
    r"\bpage\s+loaded\b|\bactive\s+window\b|\bexit\s+code\s*[:=]?\s*0\b)",
    re.IGNORECASE,
)

_COMMUNICATION_TOOLS = {
    "reply", "send_message", "email_send", "email_reply", "email_forward",
    "moltbook_comment", "moltbook_post", "moltbook_dm",
}
_AUTHORITATIVE_API_MUTATIONS = {
    "calendar_create", "calendar_delete",
    "drive_upload", "drive_share",
    "tasks_create", "tasks_complete", "tasks_delete",
    "github_create_issue", "github_comment", "github_create_pr",
    "moltbook_vote", "moltbook_follow", "moltbook_unfollow",
    "moltbook_delete", "moltbook_notifications_read", "email_mark_read",
}
_FILE_MUTATIONS = {"write_file", "append_file"}
_FILE_READS = {"read_file"}
_BROWSER_MUTATIONS = {"browse_interact"}
_BROWSER_OBSERVERS = {"browse", "browse_observe", "browse_screenshot"}
_DESKTOP_MUTATIONS = {
    "desktop_type", "desktop_key", "desktop_click", "desktop_mouse",
    "desktop_scroll", "desktop_focus", "desktop_open", "desktop_open_url",
}
_DESKTOP_OBSERVERS = {"desktop_window", "desktop_screenshot"}
_GIT_MUTATIONS = {
    "git_commit", "git_push", "git_pull", "git_clone", "git_checkout", "git_merge",
}
_GIT_OBSERVERS = {"git_status", "git_diff", "git_log"}
_SHELL_TOOLS = {"terminal"}
_GENERIC_MUTATION_WORDS = {
    "write", "append", "send", "reply", "forward", "create", "delete",
    "remove", "update", "upload", "share", "commit", "push", "complete",
    "click", "type", "open", "focus", "interact",
}


def tool_is_mutating(tool_name: str) -> bool:
    """Conservative mutation classification used by the verifier."""
    name = str(tool_name or "").strip().lower()
    if name in (
        _COMMUNICATION_TOOLS | _FILE_MUTATIONS | _BROWSER_MUTATIONS |
        _DESKTOP_MUTATIONS | _GIT_MUTATIONS | _AUTHORITATIVE_API_MUTATIONS |
        _SHELL_TOOLS
    ):
        return True
    return bool(set(name.split("_")) & _GENERIC_MUTATION_WORDS)


_SHELL_OBSERVER_RE = re.compile(
    r"^\s*(?:pwd\b|ls\b|find\b|rg\b|grep\b|cat\b|head\b|tail\b|stat\b|"
    r"wc\b|sed\s+-n\b|git\s+(?:status|diff|log|show)\b|"
    r"(?:python\S*\s+-m\s+)?pytest\b)",
    re.IGNORECASE,
)


def _receipt_is_mutating(receipt: ToolReceipt) -> bool:
    if receipt.tool in _SHELL_TOOLS:
        command = str(
            receipt.args.get("command") or receipt.args.get("cmd") or ""
        )
        return not bool(_SHELL_OBSERVER_RE.match(command))
    return tool_is_mutating(receipt.tool)


def _structured_result(result: Any) -> tuple[str, Dict[str, Any]]:
    if isinstance(result, Mapping):
        payload = dict(result)
        return json.dumps(payload, ensure_ascii=False, default=str), payload
    text = str(result or "").strip()
    if text.startswith("{") and text.endswith("}"):
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return text, value
        except (TypeError, ValueError, json.JSONDecodeError):
            pass
    return text, {}


def _metadata_status(payload: Mapping[str, Any]) -> Optional[ReceiptStatus]:
    if not payload:
        return None
    if payload.get("ok") is True or payload.get("success") is True:
        return ReceiptStatus.SUCCESS
    if payload.get("ok") is False or payload.get("success") is False:
        return ReceiptStatus.FAILED
    status = str(payload.get("status") or "").strip().lower()
    if status in {"success", "succeeded", "complete", "completed", "delivered"}:
        return ReceiptStatus.SUCCESS
    if status in {"blocked", "denied", "unauthorized"}:
        return ReceiptStatus.BLOCKED
    if status in {"failed", "failure", "error", "timeout", "timed_out"}:
        return ReceiptStatus.FAILED
    if payload.get("error"):
        return ReceiptStatus.FAILED
    return None


@dataclass
class ToolReceipt:
    """One tool call and its system-classified evidentiary meaning."""

    tool: str
    args: Dict[str, Any]
    result: str
    status: ReceiptStatus
    evidence: EvidenceLevel
    error_code: str = ""
    artifact_refs: List[str] = field(default_factory=list)
    call_id: str = field(default_factory=lambda: f"call_{uuid4().hex[:12]}")
    observed_at: str = field(default_factory=_now_iso)

    @property
    def ok(self) -> bool:
        return self.status == ReceiptStatus.SUCCESS

    @property
    def confirmed(self) -> bool:
        return self.ok and self.evidence == EvidenceLevel.CONFIRMED

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        value["evidence"] = self.evidence.value
        return value

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ToolReceipt":
        data = dict(value)
        data["status"] = ReceiptStatus(data.get("status", ReceiptStatus.UNKNOWN))
        data["evidence"] = EvidenceLevel(data.get("evidence", EvidenceLevel.NONE))
        return cls(**{
            key: item for key, item in data.items()
            if key in cls.__dataclass_fields__
        })


def classify_tool_result(
    tool_name: str,
    args: Optional[Mapping[str, Any]],
    result: Any,
) -> ToolReceipt:
    """Build a conservative receipt from a legacy or structured tool return.

    Structured ``ok/status/error`` fields win.  Legacy strings are accepted
    for compatibility, but negative language is recognized across Helix's
    existing handlers instead of checking only a few prefixes.
    """
    text, payload = _structured_result(result)
    status = _metadata_status(payload)
    error_code = str(payload.get("error_code") or "") if payload else ""
    refs = []
    if payload:
        raw_refs = payload.get("artifact_refs") or payload.get("artifacts") or []
        if isinstance(raw_refs, str):
            refs = [raw_refs]
        elif isinstance(raw_refs, Sequence):
            refs = [str(item) for item in raw_refs if str(item).strip()]

    if status is None:
        if not text:
            status = ReceiptStatus.UNKNOWN
        elif _BLOCKED_RE.search(text):
            status = ReceiptStatus.BLOCKED
            error_code = error_code or "blocked"
        elif _FAILURE_RE.search(text) or _OPERATIONAL_FAILURE_RE.search(text):
            status = ReceiptStatus.FAILED
            error_code = error_code or "tool_failure"
        else:
            status = ReceiptStatus.SUCCESS

    name = str(tool_name or "").strip()
    if status != ReceiptStatus.SUCCESS:
        evidence = EvidenceLevel.NONE
    elif payload.get("verified") is True or payload.get("confirmed") is True:
        evidence = EvidenceLevel.CONFIRMED
    elif name in _COMMUNICATION_TOOLS and _STRONG_SUCCESS_RE.search(text):
        evidence = EvidenceLevel.CONFIRMED
    elif name in _AUTHORITATIVE_API_MUTATIONS and _STRONG_SUCCESS_RE.search(text):
        evidence = EvidenceLevel.CONFIRMED
    elif name in _GIT_MUTATIONS and _STRONG_SUCCESS_RE.search(text):
        evidence = EvidenceLevel.CONFIRMED
    else:
        evidence = EvidenceLevel.OBSERVED

    return ToolReceipt(
        tool=name,
        args=dict(args or {}),
        result=text,
        status=status,
        evidence=evidence,
        error_code=error_code,
        artifact_refs=refs,
    )


@dataclass
class VerificationResult:
    status: VerificationStatus
    reasons: List[str] = field(default_factory=list)
    evidence_call_ids: List[str] = field(default_factory=list)
    unresolved_call_ids: List[str] = field(default_factory=list)

    @property
    def verified(self) -> bool:
        return self.status == VerificationStatus.VERIFIED

    def to_dict(self) -> Dict[str, Any]:
        value = asdict(self)
        value["status"] = self.status.value
        return value


def _same_arg(left: ToolReceipt, right: ToolReceipt, key: str) -> bool:
    a = str(left.args.get(key) or "").strip()
    b = str(right.args.get(key) or "").strip()
    return bool(a and b and a == b)


def _later_success(
    receipts: Sequence[ToolReceipt],
    start: int,
    names: Iterable[str],
) -> List[ToolReceipt]:
    allowed = set(names)
    return [
        receipt for receipt in receipts[start + 1:]
        if receipt.tool in allowed and receipt.ok
    ]


def verify_receipts(receipts: Iterable[ToolReceipt]) -> VerificationResult:
    """Decide whether receipts prove the requested work actually occurred.

    Read-only observations can prove an information-gathering leg directly.
    Communication tools need a delivery confirmation.  File, browser,
    desktop, and generic mutations require either a strong receipt or a
    later read-back/observation.  Failed attempts may be recovered by later
    confirmed work and remain useful experience rather than poisoning the
    final result.
    """
    items = list(receipts)
    if not items:
        return VerificationResult(
            VerificationStatus.NO_ACTION,
            ["No tool receipt exists; model text alone cannot prove completion."],
        )

    successful = [item for item in items if item.ok]
    if not successful:
        reasons = [item.result[:240] for item in items if item.result]
        return VerificationResult(
            VerificationStatus.FAILED,
            reasons or ["Every tool attempt failed or was blocked."],
            unresolved_call_ids=[item.call_id for item in items],
        )

    mutation_attempts = [item for item in items if _receipt_is_mutating(item)]
    successful_mutations = [item for item in mutation_attempts if item.ok]
    if mutation_attempts and not successful_mutations:
        return VerificationResult(
            VerificationStatus.FAILED,
            ["A state-changing action was attempted, but no mutation succeeded."],
            evidence_call_ids=[item.call_id for item in successful if not _receipt_is_mutating(item)],
            unresolved_call_ids=[item.call_id for item in mutation_attempts],
        )

    evidence_ids: List[str] = []
    unresolved: List[str] = []
    reasons: List[str] = []

    for index, receipt in enumerate(items):
        if not receipt.ok:
            continue
        if not _receipt_is_mutating(receipt):
            evidence_ids.append(receipt.call_id)
            continue
        if receipt.confirmed:
            evidence_ids.append(receipt.call_id)
            continue

        confirmations: List[ToolReceipt] = []
        if receipt.tool in _FILE_MUTATIONS:
            confirmations = [
                later for later in _later_success(items, index, _FILE_READS)
                if _same_arg(receipt, later, "path")
            ]
            if confirmations and receipt.args.get("content"):
                expected = str(receipt.args["content"])
                confirmations = [
                    later for later in confirmations
                    if expected[: min(160, len(expected))] in later.result
                ]
        elif receipt.tool in _BROWSER_MUTATIONS:
            confirmations = _later_success(items, index, _BROWSER_OBSERVERS)
        elif receipt.tool in _DESKTOP_MUTATIONS:
            confirmations = _later_success(items, index, _DESKTOP_OBSERVERS)
        elif receipt.tool in _GIT_MUTATIONS:
            confirmations = _later_success(items, index, _GIT_OBSERVERS)
        elif receipt.tool in _SHELL_TOOLS:
            confirmations = [
                later for later in items[index + 1:]
                if later.tool in _SHELL_TOOLS
                and later.ok
                and not _receipt_is_mutating(later)
            ]

        if confirmations:
            evidence_ids.extend([receipt.call_id, confirmations[0].call_id])
        else:
            unresolved.append(receipt.call_id)
            reasons.append(
                f"{receipt.tool} reported an action but no independent confirmation followed."
            )

    if unresolved:
        return VerificationResult(
            VerificationStatus.PARTIAL,
            reasons,
            list(dict.fromkeys(evidence_ids)),
            unresolved,
        )

    return VerificationResult(
        VerificationStatus.VERIFIED,
        ["The tool receipts satisfy the action verification policy."],
        list(dict.fromkeys(evidence_ids)),
    )


_NEED_INPUT_RE = re.compile(r"^\s*NEED_INPUT\s*:\s*(.+)$", re.IGNORECASE | re.DOTALL)


def clarification_question(text: Any) -> str:
    """Extract the compact clarification protocol used by focus branches."""
    match = _NEED_INPUT_RE.match(str(text or "").strip())
    return " ".join(match.group(1).split()) if match else ""
