"""
Helix — Discord Bot

Two-way communication via Discord.
Mirrors the Telegram bot architecture exactly.

Inbound messages are emitted to the pulse loop's event queue.
Outbound messages are sent via the channel router.

Message flow:
    Incoming: Discord → pulse_loop.emit() → consciousness stream
    Outgoing: [REPLY:name] → channel_router → send_message()

Requires: pip install discord.py>=2.0
Token: HELIX_DISCORD_TOKEN in credentials.env
"""

import os
import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger("helix.comms.discord")


class HelixDiscordBot:
    """Discord bot — runs in a background thread.

    Architecture mirrors HelixTelegramBot:
    - Background daemon thread with its own asyncio event loop
    - Inbound messages → pulse_loop.emit("user_message", ...)
    - Outbound messages → send_message(text, channel_id)
    """

    def __init__(self, token: str = None):
        self.token = token or os.environ.get("HELIX_DISCORD_TOKEN", "")
        self.enabled = bool(self.token)

        self._thread: Optional[threading.Thread] = None
        self._client = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

        # Pulse loop reference — set after init
        self._pulse_loop = None

        # Track known channels for proactive messaging
        self._known_channels: dict[int, str] = {}  # channel_id → display_name

        if not self.token:
            logger.warning("Discord token not set. Bot disabled.")
            self.enabled = False

    def set_pulse_loop(self, pulse_loop):
        """Wire the pulse loop — messages emit into the event queue."""
        self._pulse_loop = pulse_loop

    def start(self):
        """Start the bot in a background thread."""
        if not self.enabled:
            logger.info("Discord bot is disabled (no token)")
            return

        try:
            import discord
        except ImportError:
            logger.warning(
                "discord.py not installed. Run: pip install discord.py"
            )
            self.enabled = False
            return

        self._thread = threading.Thread(
            target=self._run_bot, daemon=True, name="helix-discord",
        )
        self._thread.start()

        if self._ready.wait(timeout=20):
            logger.info("Discord bot connected and ready")
        else:
            logger.warning("Discord bot did not become ready within 20s")

    def stop(self):
        """Stop the bot gracefully."""
        if self._loop and self._client:
            try:
                if not self._loop.is_closed():
                    future = asyncio.run_coroutine_threadsafe(
                        self._client.close(), self._loop
                    )
                    future.result(timeout=10)
            except Exception as e:
                logger.debug(f"Discord shutdown: {e}")

        if self._loop:
            try:
                if not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Discord bot stopped")

    def _run_bot(self):
        """Run the bot event loop in its own thread."""
        import discord

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        # Create client with message content intent
        intents = discord.Intents.default()
        intents.message_content = True
        self._client = discord.Client(intents=intents)

        @self._client.event
        async def on_ready():
            logger.info(f"Discord bot logged in as {self._client.user}")
            self._ready.set()

        @self._client.event
        async def on_message(message):
            # Ignore own messages
            if message.author == self._client.user:
                return

            # Ignore bot messages
            if message.author.bot:
                return

            content = message.content
            if not content:
                return

            display_name = message.author.display_name or message.author.name
            channel_id = message.channel.id
            self._known_channels[channel_id] = display_name

            logger.info(f"Discord from {display_name}: {content[:100]}")

            if self._pulse_loop:
                self._pulse_loop.emit(
                    "user_message",
                    {
                        "sender": display_name,
                        "content": content,
                        "channel": "discord",
                        "channel_id": channel_id,
                    },
                )
            else:
                try:
                    await message.channel.send(
                        "I'm still starting up — try again in a moment."
                    )
                except Exception:
                    pass

        try:
            self._loop.run_until_complete(self._client.start(self.token))
        except Exception as e:
            logger.error(f"Discord bot error: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    # ── Outbound ──────────────────────────────────────────────────────

    def send_message(self, text: str, channel_id: Optional[int] = None) -> bool:
        """Send a message to a Discord channel."""
        if not self.enabled or not self._client or not self._ready.is_set():
            logger.warning("Discord bot not ready")
            return False

        if channel_id is None:
            if self._known_channels:
                channel_id = list(self._known_channels.keys())[-1]
            else:
                logger.warning("No known Discord channels")
                return False

        try:
            channel = self._client.get_channel(channel_id)
            if not channel:
                logger.warning(f"Discord channel {channel_id} not found")
                return False

            chunks = self._chunk_message(text, limit=1900)
            for chunk in chunks:
                future = asyncio.run_coroutine_threadsafe(
                    channel.send(chunk), self._loop
                )
                future.result(timeout=15)

            logger.info(f"Discord sent to {channel_id}: {text[:80]}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Discord: {e}")
            return False

    @staticmethod
    def _chunk_message(text: str, limit: int = 1900) -> list[str]:
        """Split a message into Discord-safe chunks (2000 char limit)."""
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
