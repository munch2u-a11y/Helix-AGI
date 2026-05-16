"""
Helix — Telegram Bot

Two-way communication via Telegram.
Inbound messages are emitted to the pulse loop's event queue.
Outbound messages are sent via the channel router.

Message flow:
    Incoming: Telegram → pulse_loop.emit() → consciousness stream
    Outgoing: [REPLY:name] → channel_router → send_message()
"""

import os
import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger("helix.comms.telegram")


class HelixTelegramBot:
    """Telegram bot — runs in a background thread.

    Anyone can message the agent. No user restrictions.
    """

    def __init__(self, token: str = None):
        self.token = token or os.environ.get("HELIX_TELEGRAM_TOKEN", "")
        self.enabled = bool(self.token)

        self._thread: Optional[threading.Thread] = None
        self._app = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

        # Pulse loop reference — set after init
        self._pulse_loop = None

        # Track known chat IDs for proactive messaging
        self._known_chats: dict[int, str] = {}  # chat_id → display_name

        if not self.token:
            logger.warning("Telegram token not set. Bot disabled.")
            self.enabled = False

    def set_pulse_loop(self, pulse_loop):
        """Wire the pulse loop — messages emit into the event queue."""
        self._pulse_loop = pulse_loop

    def start(self):
        """Start the bot in a background thread."""
        if not self.enabled:
            logger.info("Telegram bot is disabled (no token)")
            return

        self._thread = threading.Thread(
            target=self._run_bot, daemon=True, name="helix-telegram",
        )
        self._thread.start()

        if self._ready.wait(timeout=15):
            logger.info("Telegram bot connected and ready")
        else:
            logger.warning("Telegram bot did not become ready within 15s")

    def stop(self):
        """Stop the bot gracefully."""
        if self._loop and self._app:
            try:
                if not self._loop.is_closed():
                    future = asyncio.run_coroutine_threadsafe(
                        self._shutdown(), self._loop
                    )
                    future.result(timeout=10)
            except Exception as e:
                logger.debug(f"Telegram shutdown: {e}")

        if self._loop:
            try:
                if not self._loop.is_closed():
                    self._loop.call_soon_threadsafe(self._loop.stop)
            except RuntimeError:
                pass

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Telegram bot stopped")

    async def _shutdown(self):
        """Async shutdown."""
        try:
            if self._app and self._app.updater:
                await self._app.updater.stop()
            if self._app:
                await self._app.stop()
                await self._app.shutdown()
        except Exception as e:
            logger.debug(f"Telegram async shutdown: {e}")

    def _run_bot(self):
        """Run the bot event loop in its own thread."""
        from telegram import Update
        from telegram.ext import (
            Application, CommandHandler, MessageHandler, filters,
        )

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._app = Application.builder().token(self.token).build()

            self._app.add_handler(CommandHandler("start", self._handle_start))
            self._app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
            )

            self._ready.set()
            logger.info("Telegram bot polling started")

            self._loop.run_until_complete(self._app.initialize())
            self._loop.run_until_complete(self._app.start())
            self._loop.run_until_complete(
                self._app.updater.start_polling(drop_pending_updates=True)
            )
            self._loop.run_forever()

        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    # ── Handlers ──────────────────────────────────────────────────────

    async def _handle_start(self, update, context):
        """Handle /start command."""
        user = update.effective_user
        chat_id = update.effective_chat.id
        display_name = user.first_name or user.username or "someone"
        self._known_chats[chat_id] = display_name
        logger.info(f"Telegram /start from {display_name} (chat_id={chat_id})")
        await update.message.reply_text(
            f"Hey {display_name}. I'm awake. Talk to me — "
            f"I'll respond when my next thought comes around."
        )

    async def _handle_message(self, update, context):
        """Handle incoming text — emit into pulse loop."""
        user = update.effective_user
        chat_id = update.effective_chat.id
        content = update.message.text
        display_name = user.first_name or user.username or "someone"
        self._known_chats[chat_id] = display_name

        if not content:
            return

        logger.info(f"Telegram from {display_name}: {content[:100]}")

        if self._pulse_loop:
            await update.effective_chat.send_action("typing")
            self._pulse_loop.emit(
                "user_message",
                {
                    "sender": display_name,
                    "content": content,
                    "channel": "telegram",
                    "chat_id": chat_id,
                },
            )
        else:
            await update.message.reply_text(
                "I'm still starting up — try again in a moment."
            )

    # ── Outbound ──────────────────────────────────────────────────────

    def send_message(self, text: str, chat_id: Optional[int] = None) -> bool:
        """Send a message to a Telegram chat."""
        if not self.enabled or not self._app or not self._ready.is_set():
            logger.warning("Telegram bot not ready")
            return False

        if chat_id is None:
            if self._known_chats:
                chat_id = list(self._known_chats.keys())[-1]
            else:
                logger.warning("No known Telegram chats")
                return False

        chunks = self._chunk_message(text, limit=4000)
        try:
            for chunk in chunks:
                future = asyncio.run_coroutine_threadsafe(
                    self._app.bot.send_message(chat_id=chat_id, text=chunk),
                    self._loop,
                )
                future.result(timeout=15)
            logger.info(f"Telegram sent to {chat_id}: {text[:80]}")
            return True
        except Exception as e:
            logger.error(f"Failed to send Telegram: {e}")
            return False

    @staticmethod
    def _chunk_message(text: str, limit: int = 4000) -> list[str]:
        """Split a message into Telegram-safe chunks."""
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
