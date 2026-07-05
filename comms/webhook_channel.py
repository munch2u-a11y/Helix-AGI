"""
Helix — Generic Webhook Channel

Universal bidirectional webhook adapter for connecting Helix to any
external service — Zapier, n8n, Matrix bridges, custom apps, Home
Assistant, IFTTT, or bespoke internal tools.

Inbound:  Flask server receives POSTs → pulse_loop.emit() → consciousness
Outbound: requests.post() sends JSON to a configured endpoint

The channel is deliberately protocol-agnostic: any system that can
send/receive JSON over HTTP can integrate with Helix through this
adapter without writing a platform-specific bot.

Message flow:
    Incoming: External POST → /webhook → pulse_loop.emit() → consciousness stream
    Outgoing: [REPLY:name] → channel_router → send_message()

Requires: pip install flask requests
Config:
    HELIX_WEBHOOK_OUTBOUND_URL   — URL to POST outbound messages to
    HELIX_WEBHOOK_INBOUND_SECRET — shared secret for verifying inbound POSTs
    HELIX_WEBHOOK_PORT           — port for the inbound Flask server (default 5101)
"""

import os
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("helix.comms.webhook")


class HelixWebhookChannel:
    """Generic webhook channel — runs in a background thread.

    Architecture mirrors HelixTelegramBot / HelixDiscordBot:
    - Background daemon thread with its own Flask server
    - Inbound messages → pulse_loop.emit("user_message", ...)
    - Outbound messages → send_message(text, channel_id)
    """

    def __init__(
        self,
        outbound_url: str = None,
        inbound_secret: str = None,
        port: int = None,
    ):
        disable_flag = os.environ.get("HELIX_DISABLE_WEBHOOK", "").strip().lower()
        if disable_flag in {"1", "true", "yes", "on"}:
            self.outbound_url = ""
            self.inbound_secret = ""
            self.port = 5101
            self.enabled = False
            logger.info("Webhook channel disabled by HELIX_DISABLE_WEBHOOK")
        else:
            self.outbound_url = (
                outbound_url
                or os.environ.get("HELIX_WEBHOOK_OUTBOUND_URL", "")
            )
            self.inbound_secret = (
                inbound_secret
                or os.environ.get("HELIX_WEBHOOK_INBOUND_SECRET", "")
            )
            self.port = (
                port
                or int(os.environ.get("HELIX_WEBHOOK_PORT", "5101"))
            )
            # Enabled if EITHER direction is configured
            self.enabled = bool(self.outbound_url or self.inbound_secret)

        self._thread: Optional[threading.Thread] = None
        self._flask_app = None
        self._server = None
        self._ready = threading.Event()

        # Pulse loop reference — set after init
        self._pulse_loop = None

        # Track known senders for proactive messaging
        self._known_senders: dict[str, str] = {}  # sender_id → display_name

        if (
            not self.outbound_url
            and not self.inbound_secret
            and disable_flag not in {"1", "true", "yes", "on"}
        ):
            logger.warning(
                "No webhook URL or inbound secret set. Channel disabled."
            )
            self.enabled = False

    def set_pulse_loop(self, pulse_loop):
        """Wire the pulse loop — messages emit into the event queue."""
        self._pulse_loop = pulse_loop

    def start(self):
        """Start the webhook channel in a background thread."""
        if not self.enabled:
            logger.info("Webhook channel is disabled (not configured)")
            return

        try:
            import flask       # noqa: F401
            import requests    # noqa: F401
        except ImportError:
            logger.warning(
                "flask/requests not installed. Run: pip install flask requests"
            )
            self.enabled = False
            return

        self._thread = threading.Thread(
            target=self._run_bot, daemon=True, name="helix-webhook",
        )
        self._thread.start()

        if self._ready.wait(timeout=10):
            logger.info("Webhook channel ready")
        else:
            logger.warning("Webhook channel did not become ready within 10s")

    def stop(self):
        """Stop the webhook channel gracefully."""
        if self._server:
            try:
                self._server.shutdown()
            except Exception as e:
                logger.debug(f"Webhook shutdown: {e}")

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Webhook channel stopped")

    def _run_bot(self):
        """Run the Flask inbound server in its own thread."""
        from flask import Flask, request, jsonify
        from werkzeug.serving import make_server

        self._flask_app = Flask("helix-webhook")

        # Suppress default Flask/Werkzeug request logging
        werkzeug_log = logging.getLogger("werkzeug")
        werkzeug_log.setLevel(logging.WARNING)

        @self._flask_app.route("/webhook", methods=["POST"])
        def inbound_webhook():
            # ── Auth check ────────────────────────────────────────────
            if self.inbound_secret:
                auth_header = request.headers.get("Authorization", "")
                if auth_header != f"Bearer {self.inbound_secret}":
                    logger.warning("Webhook inbound auth failed")
                    return jsonify({"error": "unauthorized"}), 401

            # ── Parse body ────────────────────────────────────────────
            data = request.get_json(silent=True)
            if not data:
                return jsonify({"error": "invalid JSON body"}), 400

            sender = data.get("sender", "")
            content = data.get("content", "")
            sender_id = data.get("sender_id", "")
            metadata = data.get("metadata", {})

            if not content:
                return jsonify({"error": "missing content"}), 400

            if not sender:
                sender = sender_id or "webhook-user"
            if not sender_id:
                sender_id = sender

            self._known_senders[sender_id] = sender

            logger.info(f"Webhook from {sender}: {content[:100]}")

            # ── Emit to pulse loop ────────────────────────────────────
            if self._pulse_loop:
                self._pulse_loop.emit(
                    "user_message",
                    {
                        "sender": sender,
                        "content": content,
                        "channel": "webhook",
                        "channel_id": sender_id,
                        "metadata": metadata,
                    },
                )
            else:
                logger.warning("Webhook received message but pulse loop not set")

            return jsonify({"status": "received"}), 200

        # ── Start serving ─────────────────────────────────────────────
        try:
            self._server = make_server("0.0.0.0", self.port, self._flask_app)
            self._ready.set()
            logger.info(f"Webhook inbound server listening on :{self.port}")
            self._server.serve_forever()
        except Exception as e:
            logger.error(f"Webhook server error: {e}")

    # ── Outbound ──────────────────────────────────────────────────────

    def send_message(self, text: str, channel_id: Optional[str] = None) -> bool:
        """Send a message via outbound webhook POST."""
        if not self.enabled or not self._ready.is_set():
            logger.warning("Webhook channel not ready")
            return False

        if not self.outbound_url:
            logger.warning("No outbound webhook URL configured")
            return False

        import requests

        payload = {
            "recipient": channel_id,
            "message": text,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "helix",
        }

        chunks = self._chunk_message(text, limit=4000)
        try:
            for chunk in chunks:
                payload_chunk = {**payload, "message": chunk}
                resp = requests.post(
                    self.outbound_url,
                    json=payload_chunk,
                    timeout=15,
                )
                resp.raise_for_status()

            logger.info(f"Webhook sent to {channel_id}: {text[:80]}")
            return True
        except Exception as e:
            logger.error(f"Failed to send webhook: {e}")
            return False

    @staticmethod
    def _chunk_message(text: str, limit: int = 4000) -> list[str]:
        """Split a message into webhook-safe chunks."""
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
            "known_senders": len(self._known_senders),
        }
