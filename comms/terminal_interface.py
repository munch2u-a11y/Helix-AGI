import threading
import logging
from typing import Optional

logger = logging.getLogger("helix.comms.terminal")

class HelixTerminalBot:
    """Local terminal interface for Helix AGI.
    Acts as a fallback communication channel if Telegram is not configured,
    or as a direct CLI chat.
    """

    def __init__(self, config: dict):
        self.config = config
        self.enabled = True
        self._pulse_router = None
        self._consciousness = None
        self._gemini = None
        self._thread = None
        self._running = False

    def set_pulse_router(self, pulse_router):
        """Wire the PulseRouter — all messages flow through it."""
        self._pulse_router = pulse_router

    def set_gemini(self, gemini_client):
        """Set Gemini client for media analysis (unused in terminal but needed for interface)."""
        self._gemini = gemini_client

    def set_consciousness(self, consciousness):
        """Set consciousness reference for direct event emission."""
        self._consciousness = consciousness

    def start(self):
        """Start the Terminal interface in a background thread."""
        if not self.enabled:
            return

        self._running = True
        self._thread = threading.Thread(
            target=self._run_terminal,
            daemon=True,
            name="helix-terminal",
        )
        self._thread.start()
        logger.info("Terminal interface started")

    def stop(self):
        """Stop the interface gracefully."""
        self._running = False
        logger.info("Terminal interface stopped")

    def _run_terminal(self):
        """Loop for standard input."""
        print("\n" + "=" * 60)
        print("  HELIX AGI — TERMINAL INTERFACE  ")
        print("  Type your messages below. Press Ctrl+C to exit.")
        print("=" * 60 + "\n")

        print("> ", end="", flush=True)
        while self._running:
            try:
                # Blocks waiting for user input
                text = input()
                if not text.strip():
                    print("> ", end="", flush=True)
                    continue
                    
                if text.strip().lower() in ["exit", "quit"]:
                    print("Exiting terminal interface...")
                    break
                    
                if self._pulse_router:
                    self._pulse_router.route_incoming_message(
                        source="terminal",
                        content=text.strip(),
                        metadata={"user": "cli_user"}
                    )
                else:
                    logger.warning("PulseRouter not connected; message dropped.")
                
                # Ready for next input visually (output will overwrite but that's okay for CLI)
                print("> ", end="", flush=True)

            except EOFError:
                break
            except KeyboardInterrupt:
                break
            except Exception as e:
                logger.error(f"Terminal read error: {e}")

    def send_message(self, text: str, chat_id: Optional[int] = None) -> bool:
        """Called by PulseRouter/Consciousness when outputting."""
        print(f"\n[Helix]: {text}\n> ", end="", flush=True)
        return True
