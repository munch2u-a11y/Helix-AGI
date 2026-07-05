"""
Helix — WhatsApp Bot

Two-way communication via WhatsApp Business Cloud API.
Mirrors the Telegram bot architecture exactly.

Inbound messages are emitted to the pulse loop's event queue.
Outbound messages are sent via the channel router.

Message flow:
    Incoming: WhatsApp webhook → pulse_loop.emit() → consciousness stream
    Outgoing: [REPLY:name] → channel_router → send_message()

Requires: WhatsApp Business Cloud API credentials
Env vars:
    HELIX_WHATSAPP_TOKEN       — permanent access token
    HELIX_WHATSAPP_PHONE_ID    — phone number ID
    HELIX_WHATSAPP_VERIFY_TOKEN — webhook verification token
    HELIX_WHATSAPP_PORT        — webhook port (default 5100)
"""

import os
import logging
import threading
from typing import Optional

logger = logging.getLogger("helix.comms.whatsapp")


class HelixWhatsAppBot:
    """WhatsApp bot — runs in a background thread.

    Architecture mirrors HelixTelegramBot:
    - Background daemon thread with its own Flask webhook server
    - Inbound messages → pulse_loop.emit("user_message", ...)
    - Outbound messages → send_message(text, chat_id)
    """

    def __init__(self, token: str = None, phone_id: str = None,
                 verify_token: str = None):
        disable_flag = os.environ.get("HELIX_DISABLE_WHATSAPP", "").strip().lower()
        if disable_flag in {"1", "true", "yes", "on"}:
            self.token = ""
            self.phone_id = ""
            self.verify_token = ""
            self.enabled = False
            logger.info("WhatsApp bot disabled by HELIX_DISABLE_WHATSAPP")
        else:
            self.token = token or os.environ.get("HELIX_WHATSAPP_TOKEN", "")
            self.phone_id = phone_id or os.environ.get(
                "HELIX_WHATSAPP_PHONE_ID", ""
            )
            self.verify_token = verify_token or os.environ.get(
                "HELIX_WHATSAPP_VERIFY_TOKEN", ""
            )
            self.enabled = bool(self.token and self.phone_id)

        self._thread: Optional[threading.Thread] = None
        self._app = None  # Flask app
        self._server = None  # Werkzeug server
        self._ready = threading.Event()

        # Pulse loop reference — set after init
        self._pulse_loop = None

        # Track known chats for proactive messaging
        self._known_chats: dict[str, str] = {}  # phone_number → display_name

        # Webhook port
        self._port = int(os.environ.get("HELIX_WHATSAPP_PORT", "5100"))

        if not self.enabled and disable_flag not in {"1", "true", "yes", "on"}:
            logger.warning(
                "WhatsApp token/phone_id not set. Bot disabled."
            )

    def set_pulse_loop(self, pulse_loop):
        """Wire the pulse loop — messages emit into the event queue."""
        self._pulse_loop = pulse_loop

    def start(self):
        """Start the bot in a background thread."""
        if not self.enabled:
            logger.info("WhatsApp bot is disabled (no credentials)")
            return

        try:
            import flask  # noqa: F401
        except ImportError:
            logger.warning(
                "Flask not installed. Run: pip install flask"
            )
            self.enabled = False
            return

        try:
            import requests  # noqa: F401
        except ImportError:
            logger.warning(
                "requests not installed. Run: pip install requests"
            )
            self.enabled = False
            return

        self._thread = threading.Thread(
            target=self._run_bot, daemon=True, name="helix-whatsapp",
        )
        self._thread.start()

        if self._ready.wait(timeout=15):
            logger.info("WhatsApp bot connected and ready")
        else:
            logger.warning("WhatsApp bot did not become ready within 15s")

    def stop(self):
        """Stop the bot gracefully."""
        if self._server:
            try:
                self._server.shutdown()
            except Exception as e:
                logger.debug(f"WhatsApp shutdown: {e}")

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("WhatsApp bot stopped")

    def _run_bot(self):
        """Run the Flask webhook server in its own thread."""
        from flask import Flask, request, jsonify
        import requests as req_lib

        self._app = Flask("helix-whatsapp")
        self._app.logger.setLevel(logging.WARNING)  # Suppress Flask noise
        self._server = None

        bot = self  # Closure reference

        @self._app.route("/webhook", methods=["GET"])
        def verify_webhook():
            """Handle Meta webhook verification challenge."""
            mode = request.args.get("hub.mode", "")
            token = request.args.get("hub.verify_token", "")
            challenge = request.args.get("hub.challenge", "")

            if mode == "subscribe" and token == bot.verify_token:
                logger.info("WhatsApp webhook verified")
                return challenge, 200
            else:
                logger.warning("WhatsApp webhook verification failed")
                return "Forbidden", 403

        @self._app.route("/webhook", methods=["POST"])
        def receive_message():
            """Handle incoming WhatsApp messages."""
            data = request.get_json(silent=True) or {}

            try:
                for entry in data.get("entry", []):
                    for change in entry.get("changes", []):
                        value = change.get("value", {})
                        messages = value.get("messages", [])
                        contacts = value.get("contacts", [])

                        # Build contact lookup
                        contact_map = {}
                        for contact in contacts:
                            wa_id = contact.get("wa_id", "")
                            profile = contact.get("profile", {})
                            name = profile.get("name", wa_id)
                            contact_map[wa_id] = name

                        for msg in messages:
                            if msg.get("type") != "text":
                                continue

                            phone = msg.get("from", "")
                            content = msg.get("text", {}).get("body", "")

                            if not phone or not content:
                                continue

                            display_name = contact_map.get(phone, phone)
                            bot._known_chats[phone] = display_name

                            logger.info(
                                f"WhatsApp from {display_name}: "
                                f"{content[:100]}"
                            )

                            if bot._pulse_loop:
                                bot._pulse_loop.emit(
                                    "user_message",
                                    {
                                        "sender": display_name,
                                        "content": content,
                                        "channel": "whatsapp",
                                        "chat_id": phone,
                                    },
                                )
            except Exception as e:
                logger.error(f"WhatsApp webhook processing error: {e}")

            return jsonify({"status": "ok"}), 200

        port = self._port

        logger.info(f"WhatsApp webhook starting on port {port}")
        self._ready.set()

        try:
            from werkzeug.serving import make_server
            self._server = make_server("0.0.0.0", port, self._app)
            self._server.serve_forever()
        except Exception as e:
            logger.error(f"WhatsApp bot error: {e}")

    # ── Outbound ──────────────────────────────────────────────────────

    def send_message(self, text: str, chat_id: Optional[str] = None) -> bool:
        """Send a message to a WhatsApp chat."""
        if not self.enabled or not self._ready.is_set():
            logger.warning("WhatsApp bot not ready")
            return False

        if chat_id is None:
            if self._known_chats:
                chat_id = list(self._known_chats.keys())[-1]
            else:
                logger.warning("No known WhatsApp chats")
                return False

        import requests as req_lib

        url = (
            f"https://graph.facebook.com/v21.0/"
            f"{self.phone_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

        chunks = self._chunk_message(text, limit=4096)
        try:
            for chunk in chunks:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": chat_id,
                    "type": "text",
                    "text": {"body": chunk},
                }
                resp = req_lib.post(
                    url, json=payload, headers=headers, timeout=15
                )
                if resp.status_code not in (200, 201):
                    logger.error(
                        f"WhatsApp API error {resp.status_code}: "
                        f"{resp.text[:200]}"
                    )
                    return False

            logger.info(f"WhatsApp sent to {chat_id}: {text[:80]}")
            return True
        except Exception as e:
            logger.error(f"Failed to send WhatsApp: {e}")
            return False

    @staticmethod
    def _chunk_message(text: str, limit: int = 4096) -> list[str]:
        """Split a message into WhatsApp-safe chunks (4096 char limit)."""
        if len(text) <= limit:
            return [text]
        chunks = []
        remaining = text
        while remaining and len(chunks) < 5:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n\n", 0, limit)
            if split_at < limit // 2:
                split_at = remaining.rfind("\n", 0, limit)
            if split_at < limit // 2:
                split_at = limit
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")
        return chunks

    @property
    def is_ready(self) -> bool:
        return self.enabled and self._ready.is_set()

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "ready": self.is_ready,
            "known_chats": len(self._known_chats),
        }
