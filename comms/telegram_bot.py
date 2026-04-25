"""
Helix V3 — Telegram Bot

Two-way communication via Telegram direct messages.
Ported from V2 with V3 PulseRouter integration.

NO USER RESTRICTIONS — anyone can message Helix.
Creator is recognized as Prime via the belief graph, not config.

Message flow:
    Incoming: Telegram → PulseRouter.on_message() → consciousness stream
    Outgoing: consciousness thought → Shell Detector → "communicate" intent
              → PulseRouter → deliver via send_message()

The local model generates replies. This bot just carries them.
"""

import os
import asyncio
import logging
import threading
from typing import Optional

logger = logging.getLogger("helix.comms.telegram")


class HelixTelegramBot:
    """Telegram bot for Helix V3 — runs in a background thread.

    Anyone can message Helix. No user restrictions.
    The belief graph determines how Helix relates to each person.
    """

    def __init__(self, config: dict):
        telegram_config = config.get("comms", {}).get("telegram", {})
        token_env = telegram_config.get("token_env", "HELIX_TELEGRAM_TOKEN")
        self.token = os.environ.get(token_env, os.environ.get("HELIX_TELEGRAM_TOKEN", ""))
        self.enabled = telegram_config.get("enabled", True) and bool(self.token)

        self._thread: Optional[threading.Thread] = None
        self._app = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._ready = threading.Event()

        # PulseRouter reference — set after init
        self._pulse_router = None

        # Gemini client reference — for media analysis
        self._gemini = None

        # Track known chat IDs for proactive messaging
        self._known_chats: dict[int, str] = {}  # chat_id -> display_name

        # Consciousness reference — for media events
        self._consciousness = None

        if not self.token:
            logger.warning("Telegram token not set. Bot disabled.")
            self.enabled = False

    def set_pulse_router(self, pulse_router):
        """Wire the PulseRouter — all messages flow through it."""
        self._pulse_router = pulse_router

    def set_gemini(self, gemini_client):
        """Set Gemini client for media analysis."""
        self._gemini = gemini_client

    def set_consciousness(self, consciousness):
        """Set consciousness reference for direct event emission."""
        self._consciousness = consciousness

    def start(self):
        """Start the Telegram bot in a background thread."""
        if not self.enabled:
            logger.info("Telegram bot is disabled")
            return

        self._thread = threading.Thread(
            target=self._run_bot,
            daemon=True,
            name="helix-telegram",
        )
        self._thread.start()
        logger.info("Telegram bot thread started")

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
                pass  # Loop already closed — safe to ignore

        if self._thread:
            self._thread.join(timeout=5)

        logger.info("Telegram bot stopped")

    async def _shutdown(self):
        """Async shutdown sequence."""
        try:
            if self._app and self._app.updater:
                await self._app.updater.stop()
            if self._app:
                await self._app.stop()
                await self._app.shutdown()
        except Exception as e:
            logger.debug(f"Telegram async shutdown: {e}")

    def _run_bot(self):
        """Run the Telegram bot event loop in its own thread."""
        from telegram import Update
        from telegram.ext import (
            Application,
            CommandHandler,
            MessageHandler,
            filters,
        )

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._app = (
                Application.builder()
                .token(self.token)
                .build()
            )

            # Register handlers — no user filtering, anyone can talk
            self._app.add_handler(CommandHandler("start", self._handle_start))
            self._app.add_handler(
                MessageHandler(filters.TEXT & ~filters.COMMAND, self._handle_message)
            )
            # Media handler
            self._app.add_handler(
                MessageHandler(
                    filters.VIDEO | filters.PHOTO | filters.VIDEO_NOTE
                    | filters.VOICE | filters.AUDIO,
                    self._handle_media,
                )
            )

            self._ready.set()
            logger.info("Telegram bot polling started")

            # Run polling
            self._loop.run_until_complete(self._app.initialize())
            self._loop.run_until_complete(self._app.start())
            self._loop.run_until_complete(
                self._app.updater.start_polling(drop_pending_updates=True)
            )

            # Keep running until stopped
            self._loop.run_forever()

        except Exception as e:
            logger.error(f"Telegram bot error: {e}")
        finally:
            try:
                self._loop.close()
            except Exception:
                pass

    # ── Message handlers ─────────────────────────────────────────────

    async def _handle_start(self, update, context):
        """Handle /start command."""
        user = update.effective_user
        chat_id = update.effective_chat.id
        display_name = user.first_name or user.username or "someone"

        self._known_chats[chat_id] = display_name
        logger.info(f"Telegram /start from {display_name} (chat_id={chat_id})")

        await update.message.reply_text(
            f"Hey {display_name}. I'm Helix. You can talk to me here — "
            f"I'll respond when my next thought comes around. "
            f"Patience appreciated; I think at the speed of my hardware."
        )

    async def _handle_message(self, update, context):
        """Handle incoming text messages.

        Routes through the PulseRouter → consciousness stream.
        The local model will respond in its next thought cycle.
        """
        user = update.effective_user
        chat_id = update.effective_chat.id
        content = update.message.text
        display_name = user.first_name or user.username or "someone"

        self._known_chats[chat_id] = display_name

        if not content:
            return

        logger.info(f"Telegram message from {display_name}: {content[:100]}")

        if self._pulse_router:
            try:
                # Send typing indicator — but the real response will
                # come later when the model's thought cycle completes
                await update.effective_chat.send_action("typing")

                # Route through PulseRouter — this injects into consciousness
                # and stores the reply callback for when the model responds
                self._pulse_router.on_message(
                    message=content,
                    sender=display_name,
                    channel="telegram",
                    chat_id=chat_id,
                )

            except Exception as e:
                logger.error(f"Error routing Telegram message: {e}")
        else:
            await update.message.reply_text(
                "I'm still starting up — try again in a moment."
            )

    async def _handle_media(self, update, context):
        """Handle incoming media — video, photo, voice, etc.

        Downloads the file, analyzes with Gemini Flash, and emits
        as a 'remote_sensory' event into consciousness.
        """
        user = update.effective_user
        chat_id = update.effective_chat.id
        display_name = user.first_name or user.username or "someone"
        self._known_chats[chat_id] = display_name

        msg = update.message
        caption = msg.caption or ""

        # Determine media type
        media_type = None
        file_obj = None
        if msg.video:
            media_type = "video"
            file_obj = msg.video
        elif msg.video_note:
            media_type = "video"
            file_obj = msg.video_note
        elif msg.photo:
            media_type = "photo"
            file_obj = msg.photo[-1]
        elif msg.voice:
            media_type = "voice"
            file_obj = msg.voice
        elif msg.audio:
            media_type = "audio"
            file_obj = msg.audio

        if not file_obj:
            return

        logger.info(f"Telegram media from {display_name}: {media_type}")

        try:
            await update.effective_chat.send_action("typing")

            # Download and analyze in background thread
            tg_file = await file_obj.get_file()
            import tempfile
            suffix = ".mp4" if media_type == "video" else ".jpg" if media_type == "photo" else ".ogg"

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, dir="/tmp") as f:
                local_path = f.name
            await tg_file.download_to_drive(local_path)

            description = await asyncio.to_thread(
                self._analyze_media, local_path, media_type, display_name, caption
            )

            if description:
                short = description[:200] + "..." if len(description) > 200 else description
                await update.message.reply_text(f"I see what you sent me. {short}")
            else:
                await update.message.reply_text(
                    "I received what you sent but couldn't make sense of it."
                )

        except Exception as e:
            logger.error(f"Error processing Telegram media: {e}")
            await update.message.reply_text(
                "I had trouble processing that media."
            )

    def _analyze_media(
        self, file_path: str, media_type: str, sender: str, caption: str
    ) -> str:
        """Analyze media with Gemini Flash and emit to consciousness."""
        import os

        if not self._gemini:
            return ""

        try:
            uploaded = self._gemini.client.files.upload(file=file_path)

            # Wait for processing
            import time
            for attempt in range(30):
                uploaded = self._gemini.client.files.get(name=uploaded.name)
                if uploaded.state.name == "ACTIVE":
                    break
                if uploaded.state.name == "FAILED":
                    return ""
                time.sleep(1)
            else:
                return ""

            caption_note = f' They wrote: "{caption}"' if caption else ""
            prompt = (
                f"{sender} just sent me this {media_type} through Telegram.{caption_note}\n\n"
                f"Describe what you see and/or hear in this {media_type}. "
                f"Be factual and detailed. Focus on:\n"
                f"- What is being shown — objects, people, scenes, text\n"
                f"- Any sounds or speech (transcribe speech)\n"
                f"- Any context clues about where this was taken\n"
                f"- Anything notable\n\n"
                f"Write as a description for my awareness."
            )

            response = self._gemini.client.models.generate_content(
                model=self._gemini.default_model,
                contents=[prompt, uploaded],
            )
            text = response.text.strip() if response.text else ""

            # Track cost
            if response.usage_metadata:
                u = response.usage_metadata
                inp = u.prompt_token_count or 0
                out = u.candidates_token_count or 0
                cost = self._gemini._compute_cost(self._gemini.default_model, inp, out)
                self._gemini._log_call(
                    model=self._gemini.default_model,
                    input_tokens=inp, output_tokens=out,
                    cost=cost, elapsed=0,
                    prompt_preview=f"[remote {media_type} from {sender}]",
                )

            # Emit to consciousness as remote sensory
            if self._consciousness and text:
                self._consciousness.emit("remote_sensory", {
                    "sender": sender,
                    "media_type": media_type,
                    "caption": caption,
                    "description": text,
                })

            logger.info(f"Remote sensory: {media_type} from {sender}: {text[:100]}")
            return text

        except Exception as e:
            logger.error(f"Media analysis failed: {e}")
            return ""
        finally:
            try:
                os.unlink(file_path)
            except OSError:
                pass

    # ── Proactive messaging ──────────────────────────────────────────

    def send_message(self, text: str, chat_id: Optional[int] = None) -> bool:
        """Send a message to a Telegram chat.

        Called by the PulseRouter when the conscious model's thought
        produces a "communicate" intent.

        Args:
            text: Message content — composed by the conscious model.
            chat_id: Target chat. None = most recent chat.

        Returns:
            True if delivered.
        """
        if not self.enabled or not self._app or not self._ready.is_set():
            logger.warning("Telegram bot not ready, can't send")
            return False

        if chat_id is None:
            if self._known_chats:
                chat_id = list(self._known_chats.keys())[-1]
            else:
                logger.warning("No known Telegram chats to send to")
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
            logger.error(f"Failed to send Telegram message: {e}")
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
        """Whether the bot is connected and ready."""
        return self.enabled and self._ready.is_set()

    def get_status(self) -> dict:
        """Get bot status."""
        return {
            "enabled": self.enabled,
            "ready": self.is_ready,
            "known_chats": len(self._known_chats),
            "pulse_router_wired": self._pulse_router is not None,
        }
