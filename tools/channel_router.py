"""
Helix — Channel Router

Routes outbound messages to the correct communication channel.
Two routing modes:

  [REPLY:name] → Routes to the channel that person LAST contacted the agent on.
                 Tracks last_inbound_channel per person, updated on every
                 incoming event. Falls back to default_channel if no recent
                 inbound exists.

  [MESSAGE:name] → Routes to the person's DEFAULT channel from contacts.json.
                   For proactive outreach — when the agent initiates contact.

  [TELEGRAM:name] / [DISCORD:name] → Explicit channel override.
                   Extended tools, injected by preconscious when relevant.

Channels supported:
  - telegram: python-telegram-bot async send
  - local_speech: SPEAK tag (handled by tool_executor, not here)
  - discord: placeholder (future)
  - email: placeholder (future)
"""

import os
import json
import time
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger("helix.tools.channel_router")


class ChannelRouter:
    """Routes messages to the correct communication channel.

    Resolves name → contact → channel → delivery.
    Tracks last inbound channel per person for [REPLY:] routing.
    """

    # How long a last_inbound is considered "current" (seconds)
    REPLY_WINDOW = 3600  # 1 hour

    def __init__(self, data_dir: str = "data"):
        self.data_dir = data_dir
        self.contacts: Dict[str, dict] = {}
        self._telegram_bot = None
        self._last_inbound: Dict[str, dict] = {}  # name_lower → {channel, chat_id, time}
        self._load_contacts()

    def _load_contacts(self):
        """Load contact registry."""
        contacts_path = os.path.join(self.data_dir, "contacts.json")
        if os.path.exists(contacts_path):
            try:
                with open(contacts_path, 'r') as f:
                    self.contacts = json.load(f)
                logger.info(f"Loaded {len(self.contacts)} contacts")
            except Exception as e:
                logger.warning(f"Failed to load contacts: {e}")
        else:
            logger.info("No contacts.json found — starting fresh")

    def _save_contacts(self):
        """Persist contacts to disk."""
        contacts_path = os.path.join(self.data_dir, "contacts.json")
        try:
            os.makedirs(self.data_dir, exist_ok=True)
            with open(contacts_path, 'w') as f:
                json.dump(self.contacts, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to save contacts: {e}")

    def set_telegram_bot(self, bot):
        """Wire the Telegram bot instance."""
        self._telegram_bot = bot
        logger.info("Telegram bot wired to channel router")

    # ── Contact Resolution ────────────────────────────────────────────

    def resolve_contact(self, name: str) -> Optional[dict]:
        """Resolve a name (case-insensitive) to a contact entry."""
        name_lower = name.lower().strip()

        if name_lower in self.contacts:
            return self.contacts[name_lower]

        for key, contact in self.contacts.items():
            if contact.get("display_name", "").lower() == name_lower:
                return contact
            for alias in contact.get("aliases", []):
                if alias.lower() == name_lower:
                    return contact

        return None

    # ── Inbound Tracking ──────────────────────────────────────────────

    def track_inbound(self, sender: str, channel: str, **kwargs):
        """Record the channel a person last contacted the agent on.

        Called by the pulse loop when processing incoming events.
        This drives reply() routing.

        If the sender is not in contacts.json, auto-creates a minimal
        contact entry so the agent can always reply to and message them.

        Args:
            sender: Display name of the sender.
            channel: Channel type ("telegram", "discord", "local_speech").
            **kwargs: Channel-specific data (chat_id, etc.)
        """
        name_lower = sender.lower().strip()
        self._last_inbound[name_lower] = {
            "channel": channel,
            "time": time.time(),
            **kwargs,
        }
        logger.debug(f"Tracked inbound: {sender} via {channel}")

        # Auto-register unknown contacts
        if not self.resolve_contact(sender):
            new_contact = {
                "display_name": sender,
                "aliases": [],
                "relationship": "unknown",
                "notes": f"Auto-registered on first {channel} message.",
                "channels": {},
            }
            # Store channel-specific info
            if channel == "telegram" and kwargs.get("chat_id"):
                new_contact["channels"]["telegram"] = {
                    "chat_id": kwargs["chat_id"],
                }
                new_contact["default_channel"] = "telegram"
            elif channel == "discord" and kwargs.get("channel_id"):
                new_contact["channels"]["discord"] = {
                    "channel_id": kwargs["channel_id"],
                }
                new_contact["default_channel"] = "discord"

            self.contacts[name_lower] = new_contact
            self._save_contacts()
            logger.info(
                f"Auto-registered new contact: {sender} via {channel}"
            )

    def _get_last_inbound(self, name: str) -> Optional[dict]:
        """Get the last inbound channel for a person (if recent enough)."""
        name_lower = name.lower().strip()
        inbound = self._last_inbound.get(name_lower)
        if not inbound:
            # Check aliases
            contact = self.resolve_contact(name)
            if contact:
                display = contact.get("display_name", "").lower()
                inbound = self._last_inbound.get(display)
                if not inbound:
                    for alias in contact.get("aliases", []):
                        inbound = self._last_inbound.get(alias.lower())
                        if inbound:
                            break

        if inbound and (time.time() - inbound["time"]) < self.REPLY_WINDOW:
            return inbound
        return None

    # ── Routing ───────────────────────────────────────────────────────

    def route_reply(self, recipient: str, message: str) -> bool:
        """Route a [REPLY:name] message — uses last inbound channel.

        Falls back to default channel if no recent inbound.
        """
        inbound = self._get_last_inbound(recipient)
        if inbound:
            channel = inbound["channel"]
            logger.info(f"[REPLY:{recipient}] routing via last inbound: {channel}")
            return self._send_via_channel(
                recipient=recipient,
                message=message,
                channel=channel,
                channel_data=inbound,
            )

        # No recent inbound — fall back to default
        logger.info(f"[REPLY:{recipient}] no recent inbound, falling back to default")
        return self.route_message(recipient, message)

    def route_message(self, recipient: str, message: str) -> bool:
        """Route a [MESSAGE:name] message — uses person's default channel."""
        contact = self.resolve_contact(recipient)
        if not contact:
            logger.warning(f"No contact found for '{recipient}'")
            return False

        channels = contact.get("channels", {})
        display = contact.get("display_name", recipient)
        default = contact.get("default_channel")

        # If default_channel is set, use it
        if default and default in channels:
            return self._send_via_channel(
                recipient=recipient,
                message=message,
                channel=default,
                channel_data=channels[default],
            )

        # Otherwise, priority: telegram > discord > email
        if "telegram" in channels and channels["telegram"].get("chat_id"):
            return self._send_via_channel(
                recipient=recipient,
                message=message,
                channel="telegram",
                channel_data=channels["telegram"],
            )

        if "discord" in channels:
            logger.info(f"Discord for {display} — not yet implemented")
            return False

        if "email" in channels:
            logger.info(f"Email for {display} — not yet implemented")
            return False

        logger.warning(f"No deliverable channel for {display}")
        return False

    def route_explicit(self, recipient: str, message: str, channel: str) -> bool:
        """Route via an explicitly specified channel (e.g. [TELEGRAM:name])."""
        contact = self.resolve_contact(recipient)
        if not contact:
            logger.warning(f"No contact for '{recipient}' on {channel}")
            return False

        channels = contact.get("channels", {})
        if channel not in channels:
            logger.warning(f"{recipient} has no {channel} channel configured")
            return False

        return self._send_via_channel(
            recipient=recipient,
            message=message,
            channel=channel,
            channel_data=channels[channel],
        )

    # ── Channel Dispatch ──────────────────────────────────────────────

    def _send_via_channel(
        self, recipient: str, message: str, channel: str, channel_data: dict
    ) -> bool:
        """Dispatch to the appropriate channel sender."""
        if channel == "telegram":
            chat_id = channel_data.get("chat_id")
            if not chat_id:
                logger.warning(f"No chat_id for {recipient} on Telegram")
                return False
            return self._send_telegram(message, chat_id, recipient)

        if channel == "local_speech":
            # Handled by tool_executor [SPEAK:], not here
            logger.info(f"Local speech for {recipient} — use [SPEAK:] tag instead")
            return False

        if channel == "discord":
            logger.info(f"Discord send not yet implemented")
            return False

        if channel == "email":
            logger.info(f"Email send not yet implemented")
            return False

        logger.warning(f"Unknown channel type: {channel}")
        return False

    def _send_telegram(self, message: str, chat_id: int, display_name: str) -> bool:
        """Send via Telegram bot."""
        if not self._telegram_bot:
            logger.warning("Telegram bot not initialized")
            return False
        try:
            success = self._telegram_bot.send_message(text=message, chat_id=chat_id)
            if success:
                logger.info(f"Telegram → {display_name} ({chat_id}): {message[:80]}")
            return success
        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            return False

    # ── Contact Metadata ──────────────────────────────────────────────

    def update_last_contact(self, name: str, context: str = ""):
        """Update the last_contact timestamp for a contact."""
        from datetime import datetime
        contact = self.resolve_contact(name)
        if contact:
            contact["last_contact"] = {
                "timestamp": datetime.now().isoformat()[:19],
                "context": context[:200] if context else "interaction",
            }
            self._save_contacts()

    def get_contact_info(self, name: str) -> Optional[str]:
        """Get a brief summary of a contact for preconscious injection."""
        contact = self.resolve_contact(name)
        if not contact:
            return None
        parts = [contact.get("display_name", name)]
        rel = contact.get("relationship", "")
        if rel:
            parts.append(f"({rel})")
        notes = contact.get("notes", "")
        if notes:
            parts.append(f"— {notes[:100]}")
        return " ".join(parts)
