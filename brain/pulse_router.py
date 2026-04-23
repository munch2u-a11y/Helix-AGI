"""
Helix V5 — Pulse Router

Simplified nervous system for Gemini consciousness. No Will Detector,
no speech center — the conscious model (Gemini 3.0 Pro) handles
everything directly.

Two paths:
  External message → queue event → wake consciousness → model responds
  Model response → parse [REPLY:] → deliver via Telegram
"""

import time
import json
import logging
import threading
from typing import Optional, Callable

logger = logging.getLogger("helix.brain.pulse_router")


class PulseRouter:
    """Routes messages and delivers replies.

    Simplified from V3 — no Will Detector scan. The conscious
    model outputs structured responses that we parse directly.
    """

    def __init__(
        self,
        consciousness,
        memory,
        sentinel,
        scheduler=None,
        librarian=None,
    ):
        self.consciousness = consciousness
        self.memory = memory
        self.sentinel = sentinel
        self.scheduler = scheduler
        self.librarian = librarian
        self.action_agent = None  # Set by daemon after init

        # Delivery callbacks — registered by comms bots
        self._delivery_channels: dict[str, Callable] = {}

        # Contact registry — maps lowercase name → {chat_id, channel, display_name}
        # This is how Helix knows how to reach people
        self.contacts_file = self.memory.base_dir / "brain" / "contacts.json"
        self._contacts: dict[str, dict] = {}
        if self.contacts_file.exists():
            try:
                self._contacts = json.loads(self.contacts_file.read_text())
                logger.info(f"Loaded {len(self._contacts)} known contacts from disk")
            except Exception as e:
                logger.warning(f"Failed to load contacts: {e}")

        # Stats
        self._messages_received = 0
        self._deliveries_made = 0

        self._lock = threading.Lock()

        logger.info("PulseRouter initialized — simplified nervous system")

    # ── Delivery channel registration ────────────────────────────────

    def register_delivery_channel(self, channel_name: str, callback: Callable):
        """Register a delivery callback for a channel.

        Callback signature: (text: str, chat_id: int) -> bool
        """
        self._delivery_channels[channel_name] = callback
        logger.info(f"Delivery channel registered: {channel_name}")

    # ── Contact tracking ─────────────────────────────────────────────

    def _register_contact(self, name: str, chat_id: int, channel: str):
        """Track a contact's chat_id so Helix can message them by name."""
        key = name.lower().strip()
        new_data = {
            "chat_id": chat_id,
            "channel": channel,
            "display_name": name,
        }
        
        # Only rewrite if something changed
        if self._contacts.get(key) != new_data:
            self._contacts[key] = new_data
            try:
                self.contacts_file.write_text(json.dumps(self._contacts, indent=2))
            except Exception as e:
                logger.warning(f"Failed to save contacts: {e}")

    def _resolve_contact(self, name: str):
        """Resolve a name to (channel_name, callback, chat_id) or None."""
        key = name.lower().strip()
        contact = self._contacts.get(key)
        if contact:
            channel = contact["channel"]
            callback = self._delivery_channels.get(channel)
            if callback:
                return channel, callback, contact["chat_id"]
        return None

    def get_known_contacts(self) -> list[str]:
        """Return list of people Helix can currently reach."""
        return [c["display_name"] for c in self._contacts.values()]

    # ── Incoming messages ────────────────────────────────────────────

    def on_message(
        self,
        message: str,
        sender: str,
        channel: str,
        chat_id: int = None,
        reply_callback: Callable = None,
    ):
        """Handle an incoming message.

        1. Register the sender as a reachable contact
        2. Inject event into consciousness
        3. Wake Helix if dormant
        4. Record to memory
        """
        self._messages_received += 1

        logger.info(f"Message received [{channel}] {sender}: {message[:80]}")

        # Register this person so Helix can message them by name
        if chat_id is not None:
            self._register_contact(sender, chat_id, channel)

        # Apply Familiarity Click (preconscious resonance)
        emitted_message = message
        if self.librarian and hasattr(self.librarian, "resonance_tagger"):
            emitted_message = self.librarian.resonance_tagger.apply_familiarity_click(message)

        # Inject event into consciousness
        if self.consciousness:
            self.consciousness.emit("user_message", {
                "user": sender,
                "content": emitted_message,
            })

            # Wake if dormant, or reset timers if already awake
            # wake() handles both: full wake-up or timer/ramp reset
            self.consciousness.wake(
                trigger=f"message from {sender} on {channel}"
            )

        # Record to memory (original text)
        self._record_inbound(message, sender, channel)

    # ── Reply delivery ───────────────────────────────────────────────

    def deliver_reply(self, recipient: str, text: str):
        """Deliver a reply to a specific person by name.

        Called by consciousness when it parses a [REPLY:name] block.
        Looks up the recipient's chat_id from the contact registry.
        """
        if not text or not text.strip():
            return

        logger.info(f"Delivering reply to {recipient}: {text[:80]}...")

        resolved = self._resolve_contact(recipient)
        if resolved:
            channel_name, callback, chat_id = resolved
            try:
                callback(text, chat_id)
                self._deliveries_made += 1
                logger.info(
                    f"Reply delivered to {recipient} via {channel_name}"
                )

                # Record to memory
                self._record_outbound(text, recipient, channel_name)

                # Emit back to consciousness
                if self.consciousness:
                    self.consciousness.emit("own_response", {
                        "content": text,
                    })
                return
            except Exception as e:
                logger.warning(f"Delivery to {recipient} via {channel_name} failed: {e}")

        logger.warning(
            f"Could not deliver reply to {recipient} — "
            f"no known contact. Known contacts: {self.get_known_contacts()}"
        )

    # ── Scheduler integration ────────────────────────────────────────

    def schedule_task(self, minutes: int, description: str):
        """Schedule a future task (from consciousness [SCHEDULE:] output)."""
        if self.scheduler:
            self.scheduler.schedule(minutes, description)
            logger.info(f"Scheduled: '{description}' in {minutes} minutes")
        else:
            logger.warning("Schedule requested but no scheduler available")

    # ── Memory recording ─────────────────────────────────────────────

    def _record_inbound(self, message: str, sender: str, channel: str):
        if not self.memory:
            return
        try:
            snapshot = {}
            if self.sentinel:
                snapshot = self.sentinel.get_lagrangian_snapshot()
            importance = self._score_importance(message, snapshot, is_inbound=True)
            self.memory.store(
                content=f"[{channel}] {sender} said: {message}",
                memory_type="conversation",
                source="pulse_router",
                importance=importance,
                tags=[channel, sender.lower()],
                lagrangian_snapshot=snapshot,
            )
        except Exception as e:
            logger.debug(f"Inbound recording failed: {e}")

    def _record_outbound(self, response: str, recipient: str, channel: str):
        if not self.memory:
            return
        try:
            snapshot = {}
            if self.sentinel:
                snapshot = self.sentinel.get_lagrangian_snapshot()
            importance = self._score_importance(response, snapshot, is_inbound=False)
            self.memory.store(
                content=f"[{channel}] I told {recipient}: {response}",
                memory_type="conversation",
                source="pulse_router",
                importance=importance,
                tags=[channel, recipient.lower()],
                lagrangian_snapshot=snapshot,
            )
        except Exception as e:
            logger.debug(f"Outbound recording failed: {e}")

    def _score_importance(self, text: str, snapshot: dict, is_inbound: bool) -> float:
        """Score memory importance dynamically based on relative systemic change and resonance.
        
        Importance is no longer driven by string length or hardcoded emojis. 
        It is driven by the structural impact on the organism (the shift in stability/omega)
        and the preconscious semantic resonance (Familiarity Clicks).
        """
        # Default baseline if no telemetry is available
        base_importance = 0.35 

        if snapshot:
            # Omega represents the magnitude of shift/deviation in the system.
            # Large shifts in either direction (positive or negative) generate higher importance.
            omega = snapshot.get('omega', 0.5)
            # Normalize omega shift. Omega is centered at 0.5. A shift to 0.1 or 0.9 is a 0.4 deviation.
            omega_shift = abs(omega - 0.5) * 2.0  # Range 0.0 to 1.0
            
            # The severity of the instability state also guarantees deep memory encoding (trauma/growth).
            severity = snapshot.get('severity', 'all_clear')
            severity_bonus = 0.0
            if severity == 'warning':
                severity_bonus = 0.15
            elif severity == 'critical':
                severity_bonus = 0.25

            # The new telemetry-driven baseline. A stable, non-shifting system stores memories at ~0.35.
            # A highly volatile or shifting system stores them much higher.
            base_importance = 0.35 + (omega_shift * 0.30) + severity_bonus

        # Semantic Resonance (Familiarity Click) multiplier
        # ⟪ ⟫ tags indicate the Librarian found a deep semantic link to past experiences.
        resonance_count = text.count("⟪")
        if resonance_count > 0:
             # Add weight for each profound resonant concept touched in this pulse
             base_importance += (resonance_count * 0.10)
             
        # Clamp to valid range so Librarian recall thresholds work cleanly
        return round(max(0.30, min(0.95, base_importance)), 4)

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "messages_received": self._messages_received,
            "deliveries_made": self._deliveries_made,
            "known_contacts": self.get_known_contacts(),
            "delivery_channels": list(self._delivery_channels.keys()),
        }
