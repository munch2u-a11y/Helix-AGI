"""
Helix — Interaction Ledger

Deterministic artifact-level provenance: "I have already responded to
this." The gravity/semantic recall answers *what does this remind me
of*; this ledger answers the binary question *have I acted on this
exact thing before* — which semantic similarity is bad at (reading the
same email twice produces nearly identical embeddings whether or not a
reply happened in between).

How it works:
  1. When a respond-type tool fires (reply, email_send, moltbook_comment,
     …), every id-shaped value in its args is recorded with a timestamp.
  2. When a read-type tool returns (email_get, moltbook_notifications,
     …), the result text is scanned for recorded ids. Hits get an
     inline annotation appended to the result:
         [memory: I already responded to 19e84ddd… on 2026-06-28]
     The model sees its own interaction history at the exact moment of
     re-perception — before it can respond a second time.

Ids are matched by substring; only ids ≥ 8 chars are recorded, so false
positives are effectively impossible. The pre-existing email reply
ledger (data/email_reply_ledger.json) is merged in on first load.

Module-level singleton, same pattern as the other hooks. Never raises
into the tool path.
"""

import json
import logging
import re
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("helix.core.interaction_ledger")

_LEDGER_PATH = Path("data/interaction_ledger.json")
_LEGACY_EMAIL_LEDGER = Path("data/email_reply_ledger.json")

# Tools whose invocation means "I responded to something"
_RESPOND_TOOLS = {
    "reply", "send_message", "email_send", "email_reply",
    "moltbook_comment", "moltbook_post", "moltbook_dm",
}

# Tools whose results should be annotated with prior interactions
_READ_TOOLS = {
    "email_get", "email_read", "email_list",
    "moltbook_notifications", "moltbook_home", "moltbook_feed",
    "moltbook_read", "moltbook_dms",
}

# Arg keys that carry artifact identifiers
_ID_ARG_KEYS = {
    "message_id", "email_id", "post_id", "comment_id", "thread_id",
    "notif_id", "notification_id", "parent_id", "reply_to", "dm_id", "id",
}

# Minimum id length to record — short values ("5", "yes") would create
# false substring matches when scanning results.
_MIN_ID_LEN = 8

# Keep the ledger bounded
_MAX_ENTRIES = 3000

_lock = threading.Lock()
_responded: Optional[Dict[str, Dict[str, Any]]] = None  # id → {tool, at}


def _load() -> Dict[str, Dict[str, Any]]:
    global _responded
    if _responded is not None:
        return _responded

    data: Dict[str, Dict[str, Any]] = {}
    try:
        if _LEDGER_PATH.exists():
            raw = json.loads(_LEDGER_PATH.read_text())
            if isinstance(raw, dict):
                data = raw.get("responded", {})
    except Exception as e:
        logger.warning("Interaction ledger load failed: %s", e)

    # One-time merge of the legacy email reply ledger
    try:
        if _LEGACY_EMAIL_LEDGER.exists():
            legacy = json.loads(_LEGACY_EMAIL_LEDGER.read_text())
            for mid in legacy.get("replied_to", []):
                if isinstance(mid, str) and len(mid) >= _MIN_ID_LEN:
                    data.setdefault(mid, {"tool": "email_reply", "at": ""})
    except Exception:
        pass

    _responded = data
    return _responded


def _save():
    try:
        _LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        data = _load()
        if len(data) > _MAX_ENTRIES:
            # Drop oldest entries (empty timestamps sort first — legacy)
            trimmed = sorted(data.items(), key=lambda kv: kv[1].get("at", ""))
            data = dict(trimmed[-_MAX_ENTRIES:])
            globals()["_responded"] = data
        _LEDGER_PATH.write_text(json.dumps({"responded": data}, indent=1))
    except Exception as e:
        logger.warning("Interaction ledger save failed: %s", e)


def record_from_call(tool_name: str, args: Optional[dict]):
    """Record artifact ids when a respond-type tool fires."""
    try:
        if tool_name not in _RESPOND_TOOLS or not isinstance(args, dict):
            return
        now = time.strftime("%Y-%m-%d %H:%M")
        recorded = 0
        with _lock:
            data = _load()
            for key, val in args.items():
                if key not in _ID_ARG_KEYS:
                    continue
                sval = str(val).strip()
                if len(sval) >= _MIN_ID_LEN and not sval.isspace():
                    data[sval] = {"tool": tool_name, "at": now}
                    recorded += 1
            if recorded:
                _save()
        if recorded:
            logger.info(
                "Interaction recorded: %s → %d artifact id(s)",
                tool_name, recorded,
            )
    except Exception as e:
        logger.debug("record_from_call failed (non-fatal): %s", e)


def annotate_result(tool_name: str, result: str) -> str:
    """Append prior-interaction annotations to a read-type tool result."""
    try:
        if tool_name not in _READ_TOOLS or not result:
            return result

        with _lock:
            data = _load()
            hits = [
                (aid, meta) for aid, meta in data.items()
                if aid in result
            ]

        if not hits:
            return result

        lines = []
        for aid, meta in hits[:8]:
            at = meta.get("at", "")
            via = meta.get("tool", "responded")
            lines.append(
                f"{aid} (via {via}{', ' + at if at else ''})"
            )
        annotation = (
            "\n\n[memory: I have already responded to "
            + "; ".join(lines)
            + " — no need to respond again unless something new is asked]"
        )
        return result + annotation
    except Exception as e:
        logger.debug("annotate_result failed (non-fatal): %s", e)
        return result


def get_stats() -> dict:
    with _lock:
        return {"responded_artifacts": len(_load())}
