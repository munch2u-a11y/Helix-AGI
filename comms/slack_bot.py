"""
Helix — Slack Bot

Two-way communication via Slack (Socket Mode).
Inbound messages are emitted to the pulse loop's event queue.
Outbound messages are sent via the channel router.

Message flow:
    Incoming: Slack → pulse_loop.emit() → consciousness stream
    Outgoing: [REPLY:name] → channel_router → send_message()
"""

import os
import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger("helix.comms.slack")


class HelixSlackBot:
    """Slack bot — runs in a background thread via Socket Mode.

    Anyone can message the agent. No user restrictions.
    """

    def __init__(self, bot_token: str = None, app_token: str = None):
        disable_flag = os.environ.get("HELIX_DISABLE_SLACK", "").strip().lower()
        if disable_flag in {"1", "true", "yes", "on"}:
            self.bot_token = ""
            self.app_token = ""
            self.enabled = False
            logger.info("Slack bot disabled by HELIX_DISABLE_SLACK")
        else:
            self.bot_token = bot_token or os.environ.get("HELIX_SLACK_BOT_TOKEN", "")
            self.app_token = app_token or os.environ.get("HELIX_SLACK_APP_TOKEN", "")
            self.enabled = bool(self.bot_token and self.app_token)

        self._thread: Optional[threading.Thread] = None
        self._app = None
        self._socket_mode_handler = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

        # Pulse loop reference — set after init
        self._pulse_loop = None

        # Track known channel IDs for proactive messaging
        self._known_channels: dict[str, str] = {}  # channel_id → display_name

        if not self.enabled and disable_flag not in {"1", "true", "yes", "on"}:
            if not self.bot_token:
                logger.warning("Slack bot token not set. Bot disabled.")
            if not self.app_token:
                logger.warning("Slack app token not set. Bot disabled.")
            self.enabled = False

    def set_pulse_loop(self, pulse_loop):
        """Wire the pulse loop — messages emit into the event queue."""
        self._pulse_loop = pulse_loop

    def start(self):
        """Start the bot in a background thread."""
        if not self.enabled:
            logger.info("Slack bot is disabled (missing tokens)")
            return

        # Guard imports — graceful degradation if slack_bolt isn't installed
        try:
            import slack_bolt  # noqa: F401
            import slack_sdk   # noqa: F401
        except ImportError:
            logger.warning(
                "slack_bolt / slack_sdk not installed. "
                "Install with: pip install slack-bolt slack-sdk"
            )
            self.enabled = False
            return

        self._thread = threading.Thread(
            target=self._run_bot, daemon=True, name="helix-slack",
        )
        self._thread.start()

        if self._ready.wait(timeout=15):
            logger.info("Slack bot connected and ready")
        else:
            logger.warning("Slack bot did not become ready within 15s")

    def stop(self):
        """Stop the bot gracefully."""
        if self._socket_mode_handler:
            try:
                self._socket_mode_handler.close()
            except Exception as e:
                logger.debug(f"Slack shutdown: {e}")

        if self._loop:
            try:
                if not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Slack bot stopped")

    def _run_bot(self):
        """Run the bot event loop in its own thread."""
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._app = App(token=self.bot_token)

            @self._app.event("message")
            def _handle_message(event, say):
                # Ignore bot messages and message_changed subtypes
                if event.get("bot_id") or event.get("subtype"):
                    return

                user_id = event.get("user", "unknown")
                channel_id = event.get("channel", "")
                content = event.get("text", "")

                # Resolve display name via Web API
                display_name = self._resolve_user_name(user_id)
                self._known_channels[channel_id] = display_name

                if not content:
                    return

                logger.info(f"Slack from {display_name}: {content[:100]}")

                if self._pulse_loop:
                    self._pulse_loop.emit(
                        "user_message",
                        {
                            "sender": display_name,
                            "content": content,
                            "channel": "slack",
                            "channel_id": channel_id,
                        },
                    )
                else:
                    say(
                        "I'm still starting up — try again in a moment."
                    )

            self._socket_mode_handler = SocketModeHandler(
                self._app, self.app_token,
            )

            self._ready.set()
            logger.info("Slack bot socket mode started")

            # Blocking — runs until close() is called
            self._socket_mode_handler.start()

        except Exception as e:
            logger.error(f"Slack bot error: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    # ── Helpers ───────────────────────────────────────────────────────

    def _resolve_user_name(self, user_id: str) -> str:
        """Look up a Slack user's display name via the Web API."""
        try:
            result = self._app.client.users_info(user=user_id)
            user = result.get("user", {})
            profile = user.get("profile", {})
            return (
                profile.get("display_name")
                or profile.get("real_name")
                or user.get("name")
                or user_id
            )
        except Exception:
            return user_id

    # ── Outbound ──────────────────────────────────────────────────────

    def send_message(self, text: str, channel_id: Optional[str] = None) -> bool:
        """Send a message to a Slack channel."""
        if not self.enabled or not self._app or not self._ready.is_set():
            logger.warning("Slack bot not ready")
            return False

        if channel_id is None:
            if self._known_channels:
                channel_id = list(self._known_channels.keys())[-1]
            else:
                logger.warning("No known Slack channels")
                return False

        chunks = self._chunk_message(text, limit=3000)
        try:
            for chunk in chunks:
                self._app.client.chat_postMessage(
                    channel=channel_id, text=chunk,
                )
            logger.info(f"Slack sent to {channel_id}: {text[:80]}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Slack: {e}")
            return False

    @staticmethod
    def _chunk_message(text: str, limit: int = 3000) -> list[str]:
        """Split a message into Slack-safe chunks."""
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
            "known_channels": len(self._known_channels),
        }
