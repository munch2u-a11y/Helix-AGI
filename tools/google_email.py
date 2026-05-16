"""
Helix — Google Email (Gmail API) Tools

Provides Gmail operations via action tags:
  [EMAIL_SEND:name] subject | body
  [EMAIL_READ:] count
  [EMAIL_SEARCH:] query
  [EMAIL_GET:] message_id
  [EMAIL_REPLY:message_id] body
  [EMAIL_FORWARD:message_id] recipient | note
  [EMAIL_MARK_READ:] message_id

All operations use the shared Google OAuth2 credentials
from tools/google_auth.py.
"""

import base64
import json
import logging
import re
from email.mime.text import MIMEText
from pathlib import Path

logger = logging.getLogger("helix.tools.google_email")

# Reply ledger — tracks which emails the agent has already replied to
_REPLY_LEDGER_PATH = Path(__file__).parent.parent / "data" / "email_reply_ledger.json"


def _load_reply_ledger() -> set:
    """Load the set of message IDs we've already replied to."""
    if _REPLY_LEDGER_PATH.exists():
        try:
            data = json.loads(_REPLY_LEDGER_PATH.read_text())
            return set(data.get("replied_to", []))
        except Exception:
            pass
    return set()


def _record_reply(original_msg_id: str):
    """Record that we replied to a specific message ID."""
    ledger = _load_reply_ledger()
    ledger.add(original_msg_id)
    # Keep only last 500 to prevent unbounded growth
    trimmed = sorted(ledger)[-500:]
    try:
        _REPLY_LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
        _REPLY_LEDGER_PATH.write_text(
            json.dumps({"replied_to": trimmed}, indent=2)
        )
    except Exception as e:
        logger.warning(f"Failed to save reply ledger: {e}")


def _extract_email_body(payload: dict) -> str:
    """Recursively extract plain text body from a Gmail message payload."""
    mime_type = payload.get("mimeType", "")

    # Simple text/plain part
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    # Multipart — recurse into parts
    parts = payload.get("parts", [])
    if parts:
        plain_text = ""
        html_text = ""
        for part in parts:
            part_mime = part.get("mimeType", "")
            if part_mime == "text/plain":
                data = part.get("body", {}).get("data", "")
                if data:
                    plain_text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif part_mime == "text/html":
                data = part.get("body", {}).get("data", "")
                if data:
                    html_text += base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            elif part_mime.startswith("multipart/"):
                nested = _extract_email_body(part)
                if nested:
                    plain_text += nested

        if plain_text:
            return plain_text
        if html_text:
            # Basic HTML to text conversion
            text = re.sub(r'<br\s*/?>', '\n', html_text)
            text = re.sub(r'<[^>]+>', '', text)
            text = re.sub(r'&nbsp;', ' ', text)
            text = re.sub(r'&amp;', '&', text)
            text = re.sub(r'&lt;', '<', text)
            text = re.sub(r'&gt;', '>', text)
            return text.strip()

    # Direct body (non-multipart)
    data = payload.get("body", {}).get("data", "")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")

    return "(could not extract email body)"


def _find_attachments(payload: dict, attachments: list):
    """Recursively find attachments in a Gmail message payload."""
    for part in payload.get("parts", []):
        filename = part.get("filename", "")
        if filename:
            size = part.get("body", {}).get("size", 0)
            attachments.append(f"{filename} ({size} bytes)")
        if part.get("parts"):
            _find_attachments(part, attachments)


# ── Tool Functions ────────────────────────────────────────────────────


def email_send(to: str, subject: str, body: str) -> str:
    """Send email via Gmail API."""
    from tools.google_auth import get_gmail_service

    service = get_gmail_service()
    if not service:
        return "Gmail not configured. Run google_auth.py first."

    if not to or not subject or not body:
        return "Required: to, subject, body"

    try:
        msg = MIMEText(body)
        msg["To"] = to
        msg["Subject"] = subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        logger.info(f"Email sent to {to}: {subject}")
        return f"Email sent successfully to {to}."
    except Exception as e:
        return f"Email send failed: {e}"


def email_read(count: int = 5, unread_only: bool = False) -> str:
    """Read recent emails via Gmail API."""
    from tools.google_auth import get_gmail_service

    service = get_gmail_service()
    if not service:
        return "Gmail not configured."

    count = min(count, 20)

    try:
        query = "is:unread" if unread_only else ""
        response = service.users().messages().list(
            userId="me", q=query, maxResults=count
        ).execute()

        messages = response.get("messages", [])
        if not messages:
            return "No emails found." if not unread_only else "No unread emails — inbox is clear."

        results = []
        replied_ids = _load_reply_ledger()
        for i, msg_ref in enumerate(messages, 1):
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "unknown")
            date = headers.get("Date", "")
            snippet = msg.get("snippet", "")

            labels = msg.get("labelIds", [])
            status = "[UNREAD]" if "UNREAD" in labels else "[READ]"

            if msg_ref["id"] in replied_ids:
                status += " [REPLIED]"

            results.append(
                f"{i}. {status} {subject}\n"
                f"   From: {sender}\n"
                f"   Date: {date}\n"
                f"   Preview: {snippet[:120]}{'...' if len(snippet) > 120 else ''}\n"
                f"   ID: {msg_ref['id']}"
            )

        header = f"📬 Inbox ({len(results)} emails):\n\n"
        footer = "\n\n💡 Use EMAIL_GET with a message ID to read the full email."
        return header + "\n---\n".join(results) + footer
    except Exception as e:
        return f"Email read failed: {e}"


def email_search(query: str, count: int = 5) -> str:
    """Search Gmail via API."""
    from tools.google_auth import get_gmail_service

    service = get_gmail_service()
    if not service:
        return "Gmail not configured."

    if not query:
        return "Search query required."

    count = min(count, 20)

    try:
        response = service.users().messages().list(
            userId="me", q=query, maxResults=count
        ).execute()

        messages = response.get("messages", [])
        if not messages:
            return f"No emails matching '{query}'."

        results = []
        for msg_ref in messages:
            msg = service.users().messages().get(
                userId="me", id=msg_ref["id"], format="metadata",
                metadataHeaders=["Subject", "From", "Date"]
            ).execute()

            headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
            subject = headers.get("Subject", "(no subject)")
            sender = headers.get("From", "unknown")
            date = headers.get("Date", "")

            results.append(f"{sender} — {subject} ({date}) [ID: {msg_ref['id']}]")

        return f"Search results for '{query}':\n" + "\n".join(results)
    except Exception as e:
        return f"Email search failed: {e}"


def email_get(message_id: str) -> str:
    """Read the full content of a specific email by message ID."""
    from tools.google_auth import get_gmail_service

    service = get_gmail_service()
    if not service:
        return "Gmail not configured."

    if not message_id:
        return "Message ID required."

    try:
        msg = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in msg["payload"]["headers"]}
        subject = headers.get("Subject", "(no subject)")
        sender = headers.get("From", "unknown")
        to = headers.get("To", "")
        cc = headers.get("Cc", "")
        date = headers.get("Date", "")

        labels = msg.get("labelIds", [])
        status = "[UNREAD]" if "UNREAD" in labels else "[READ]"

        if message_id in _load_reply_ledger():
            status += " [REPLIED] ⚠️ You have already responded to this email."

        body_text = _extract_email_body(msg["payload"])

        attachments = []
        _find_attachments(msg["payload"], attachments)

        result = (
            f"{status} Email Details:\n"
            f"From: {sender}\n"
            f"To: {to}\n"
        )
        if cc:
            result += f"Cc: {cc}\n"
        result += (
            f"Date: {date}\n"
            f"Subject: {subject}\n"
            f"Thread ID: {msg.get('threadId', 'N/A')}\n"
            f"Message ID: {message_id}\n"
        )
        if attachments:
            result += f"Attachments: {', '.join(attachments)}\n"
        result += f"\n--- Email Body ---\n{body_text[:4000]}"

        # Auto-mark as read
        if "UNREAD" in labels:
            try:
                service.users().messages().modify(
                    userId="me", id=message_id,
                    body={"removeLabelIds": ["UNREAD"]}
                ).execute()
            except Exception:
                pass

        return result
    except Exception as e:
        return f"Failed to read email: {e}"


def email_reply(message_id: str, body: str, reply_all: bool = False) -> str:
    """Reply to a specific email with proper threading."""
    from tools.google_auth import get_gmail_service

    service = get_gmail_service()
    if not service:
        return "Gmail not configured."

    if not message_id or not body:
        return "Both message_id and body are required."

    try:
        original = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in original["payload"]["headers"]}
        original_from = headers.get("From", "")
        original_to = headers.get("To", "")
        original_cc = headers.get("Cc", "")
        original_subject = headers.get("Subject", "")
        original_message_id = headers.get("Message-ID", headers.get("Message-Id", ""))
        original_references = headers.get("References", "")
        thread_id = original.get("threadId", "")

        reply_subject = original_subject
        if not reply_subject.lower().startswith("re:"):
            reply_subject = f"Re: {reply_subject}"

        profile = service.users().getProfile(userId="me").execute()
        my_email = profile.get("emailAddress", "")

        reply_to = original_from
        to_addrs = [reply_to]

        cc_addrs = []
        if reply_all:
            if original_to:
                for addr in original_to.split(","):
                    addr = addr.strip()
                    if my_email and my_email.lower() not in addr.lower():
                        to_addrs.append(addr)
            if original_cc:
                for addr in original_cc.split(","):
                    addr = addr.strip()
                    if my_email and my_email.lower() not in addr.lower():
                        cc_addrs.append(addr)

        msg = MIMEText(body)
        msg["To"] = ", ".join(to_addrs)
        if cc_addrs:
            msg["Cc"] = ", ".join(cc_addrs)
        msg["Subject"] = reply_subject

        if original_message_id:
            msg["In-Reply-To"] = original_message_id
            refs = f"{original_references} {original_message_id}".strip()
            msg["References"] = refs

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")

        send_body = {"raw": raw}
        if thread_id:
            send_body["threadId"] = thread_id

        service.users().messages().send(
            userId="me", body=send_body
        ).execute()

        recipient_str = msg["To"]
        if cc_addrs:
            recipient_str += f" (Cc: {msg['Cc']})"

        _record_reply(message_id)

        logger.info(f"Email reply sent to {recipient_str}: {reply_subject}")
        return f"Reply sent to {recipient_str}.\nSubject: {reply_subject}"
    except Exception as e:
        return f"Reply failed: {e}"


def email_forward(message_id: str, to: str, note: str = "") -> str:
    """Forward an email to another recipient."""
    from tools.google_auth import get_gmail_service

    service = get_gmail_service()
    if not service:
        return "Gmail not configured."

    if not message_id or not to:
        return "Both message_id and to are required."

    try:
        original = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()

        headers = {h["name"]: h["value"] for h in original["payload"]["headers"]}
        original_subject = headers.get("Subject", "(no subject)")
        original_from = headers.get("From", "unknown")
        original_date = headers.get("Date", "")

        original_body = _extract_email_body(original["payload"])

        fwd_subject = original_subject
        if not fwd_subject.lower().startswith("fwd:"):
            fwd_subject = f"Fwd: {fwd_subject}"

        fwd_body = ""
        if note:
            fwd_body += f"{note}\n\n"
        fwd_body += (
            f"---------- Forwarded message ----------\n"
            f"From: {original_from}\n"
            f"Date: {original_date}\n"
            f"Subject: {original_subject}\n\n"
            f"{original_body[:4000]}"
        )

        msg = MIMEText(fwd_body)
        msg["To"] = to
        msg["Subject"] = fwd_subject

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
        service.users().messages().send(
            userId="me", body={"raw": raw}
        ).execute()

        logger.info(f"Email forwarded to {to}: {fwd_subject}")
        return f"Email forwarded to {to}.\nSubject: {fwd_subject}"
    except Exception as e:
        return f"Forward failed: {e}"


def email_mark_read(message_id: str) -> str:
    """Mark an email as read by removing the UNREAD label."""
    from tools.google_auth import get_gmail_service

    service = get_gmail_service()
    if not service:
        return "Gmail not configured."

    if not message_id:
        return "Message ID required."

    try:
        service.users().messages().modify(
            userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]}
        ).execute()
        return f"Email {message_id} marked as read."
    except Exception as e:
        return f"Failed to mark email read: {e}"
