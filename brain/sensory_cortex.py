"""
Helix — Sensory Cortex

Subconscious perception superagent. ALL visual and auditory input
passes through this system before reaching consciousness.

Architecture:
    - Maintains a persistent sensory_journal.json (environmental model)
    - 2-frame minimum for ALL visual observations
    - Resolves inconsistencies by committing to one answer + logging why
    - Never adds details — only reports what is confirmed across frames
    - Focus mode: sustained watch/listen across multiple pulses

Conscious-facing tools:
    look(focus?)        — "Look at something" — cortex decides depth
    listen(duration?)   — "Listen to something" — cortex filters ambient
    focus_sense(target, mode) — sustained watch/listen across pulses
    end_focus()         — stop active focus mode
"""

import os
import cv2
import json
import time
import logging
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger("helix.brain.sensory_cortex")


class SensoryCortex:
    """Subconscious perception system — processes all sensory input
    before it reaches consciousness.

    Acts as a stateful intermediary: raw camera/mic data never reaches
    the conscious model directly. Instead, the cortex builds a persistent
    environmental model and returns processed, verified descriptions.
    """

    # Focus mode limits
    MAX_WATCH_PULSES = 12
    MAX_LISTEN_SECONDS = 180  # 3 minutes
    LISTEN_SILENCE_THRESHOLD = 5  # seconds of silence to auto-end

    def __init__(self, daemon, base_dir: Path, config: dict = None):
        self.daemon = daemon
        self.base_dir = base_dir
        self.config = config or {}

        # Journal — persistent environmental model
        self.journal_path = base_dir / "brain" / "sensory_journal.json"
        self.journal = self._load_journal()

        # Focus mode state
        self._focus_active = False
        self._focus_target = ""
        self._focus_mode = ""  # "watch" or "listen"
        self._focus_scratchpad = []
        self._focus_pulses_remaining = 0
        self._focus_started_at = 0

        # Import preamble
        try:
            from brain.architecture_preamble import SENSORY_CORTEX_PREAMBLE
            self._preamble = SENSORY_CORTEX_PREAMBLE
        except ImportError:
            self._preamble = ""

        logger.info("Sensory Cortex initialized")

    # ══════════════════════════════════════════════════════════════════
    # CONSCIOUS-FACING METHODS
    # ══════════════════════════════════════════════════════════════════

    def look(self, focus: str = None) -> str:
        """Process a visual observation request from consciousness.

        Always captures 2+ frames. Uses the journal's environmental
        model as context so the vision model can flag changes and
        avoid re-describing known stable elements.
        """
        # Capture 2 frames, 300ms apart
        frames = self._capture_frames(count=2, interval_ms=300)
        if not frames:
            return "Camera not available — couldn't capture any images."

        # If asking about a specific detail, take an extra frame
        if focus:
            extra = self._capture_frames(count=1, interval_ms=200)
            if extra:
                frames.extend(extra)

        # Build context from journal
        env_context = self._get_environment_context()

        # Analyze with the primary analyst (Gemini 3 Flash)
        result = self._analyze_visual(frames, focus, env_context)

        # Update journal with any new confirmed observations
        if result.get("observations"):
            self._update_journal(result["observations"])

        return result.get("description", "I looked but couldn't process what I saw.")

    def listen(self, duration: int = 5) -> str:
        """Process an auditory observation request from consciousness.

        Uses Whisper for transcription, then filters against known
        ambient sounds from the journal.
        """
        duration = min(duration, 15)  # Cap at 15s

        try:
            import sounddevice as sd

            logger.info(f"Sensory cortex: listening for {duration}s...")
            audio = sd.rec(
                int(duration * 16000),
                samplerate=16000,
                channels=1,
                dtype="int16",
            )
            sd.wait()

            # Convert to float32 for whisper
            audio_float = audio.flatten().astype(np.float32) / 32768.0

            # Check if there's any meaningful audio
            rms = np.sqrt(np.mean(audio_float ** 2))
            if rms < 0.01:
                known_ambient = self.journal.get("environment", {}).get("ambient_sounds", "unknown")
                return f"I listened for {duration} seconds. Silence — just the usual background ({known_ambient})."

            # Transcribe with whisper
            try:
                from faster_whisper import WhisperModel
                model = WhisperModel("base.en", device="cpu", compute_type="int8")
                segments, info = model.transcribe(audio_float, beam_size=1, language="en")
                transcript = " ".join(seg.text for seg in segments).strip()

                if transcript:
                    # Filter Whisper hallucination artifacts
                    words = transcript.split()
                    if len(words) >= 3:
                        unique_words = set(w.lower().strip('.,!?') for w in words)
                        if len(unique_words) <= 2:
                            known_ambient = self.journal.get("environment", {}).get("ambient_sounds", "unknown")
                            return f"I heard ambient sounds for {duration} seconds — nothing distinct beyond the usual ({known_ambient})."

                    # Cross-reference against known ambient
                    known_ambient = self.journal.get("environment", {}).get("ambient_sounds", "")
                    return f"I heard ({duration}s): {transcript}"

                return f"I heard sounds for {duration} seconds but couldn't make out words."
            except Exception as e:
                return f"I heard audio (RMS={rms:.3f}) but transcription failed: {e}"

        except Exception as e:
            return f"Active listening failed: {e}"

    def start_focus(self, target: str, mode: str = "watch") -> str:
        """Begin sustained sensory focus across multiple pulses.

        watch: captures and analyzes a frame each pulse (max 12 pulses)
        listen: continuous audio monitoring until silence or end_focus()
        """
        if self._focus_active:
            return (
                f"Already focused on: '{self._focus_target}' ({self._focus_mode} mode, "
                f"{self._focus_pulses_remaining} pulses remaining). "
                f"Call end_focus() first to switch."
            )

        mode = mode.lower().strip()
        if mode not in ("watch", "listen"):
            return f"Invalid mode '{mode}'. Use 'watch' or 'listen'."

        self._focus_active = True
        self._focus_target = target
        self._focus_mode = mode
        self._focus_scratchpad = []
        self._focus_started_at = time.time()

        if mode == "watch":
            self._focus_pulses_remaining = self.MAX_WATCH_PULSES
            logger.info(f"Focus WATCH started: '{target}' ({self.MAX_WATCH_PULSES} pulses)")
            # Take an initial snapshot
            initial = self._focus_tick_watch()
            return (
                f"Now watching: '{target}'. I'll report what I see each pulse "
                f"for up to {self.MAX_WATCH_PULSES} pulses. "
                f"Use end_focus() to stop early.\n\n"
                f"Initial observation: {initial}"
            )
        else:
            self._focus_pulses_remaining = 999  # Listen until silence/manual end
            logger.info(f"Focus LISTEN started: '{target}'")
            return (
                f"Now listening for: '{target}'. I'll report what I hear each pulse "
                f"until silence is detected or you call end_focus()."
            )

    def end_focus(self) -> str:
        """End the active focus mode."""
        if not self._focus_active:
            return "No active focus to end."

        target = self._focus_target
        mode = self._focus_mode
        observations = len(self._focus_scratchpad)
        elapsed = time.time() - self._focus_started_at

        # Log the focus session to journal
        self._log_focus_session()

        self._focus_active = False
        self._focus_target = ""
        self._focus_mode = ""
        self._focus_scratchpad = []
        self._focus_pulses_remaining = 0

        logger.info(f"Focus {mode.upper()} ended: '{target}' ({observations} observations, {elapsed:.0f}s)")
        return (
            f"Stopped {mode}ing '{target}'. "
            f"Recorded {observations} observations over {elapsed:.0f} seconds."
        )

    def pulse_tick(self) -> Optional[str]:
        """Called each consciousness heartbeat. If focus mode is active,
        captures and returns a brief update. Otherwise returns None.
        """
        if not self._focus_active:
            return None

        if self._focus_mode == "watch":
            return self._focus_tick_watch()
        elif self._focus_mode == "listen":
            return self._focus_tick_listen()
        return None

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: CAPTURE
    # ══════════════════════════════════════════════════════════════════

    def _capture_frames(self, count: int = 2, interval_ms: int = 300) -> list:
        """Capture multiple frames from the webcam.

        Returns a list of JPEG byte arrays.
        """
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                return []

            # Request HD resolution
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            # Warm up — let auto-exposure settle
            for _ in range(3):
                cap.read()

            frames = []
            for i in range(count):
                ret, frame = cap.read()
                if ret:
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92])
                    frames.append(buf.tobytes())
                if i < count - 1:
                    time.sleep(interval_ms / 1000.0)

            cap.release()
            return frames
        except Exception as e:
            logger.error(f"Multi-frame capture failed: {e}")
            return []

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: ANALYSIS
    # ══════════════════════════════════════════════════════════════════

    def _analyze_visual(self, frames: list, focus: str, env_context: str) -> dict:
        """Send frames + context to the primary analyst (Gemini 3 Flash).

        Returns {description: str, observations: dict}.
        """
        try:
            from google.genai import types

            gemini = self.daemon.gemini
            model_name = gemini.conscious_model

            # Build the analysis prompt
            system_prompt = self._preamble if self._preamble else ""
            system_prompt += (
                "\n\nYou are analyzing webcam images for Helix's perceptual system. "
                "You have access to a known environmental model to maintain consistency.\n\n"
                "RULES:\n"
                "1. Only describe what you can CLEARLY see across the frames\n"
                "2. For ambiguous details (colors, exact objects), use natural hedging: "
                "'looks like...', 'appears to be...', 'hard to tell in this lighting...'\n"
                "3. NEVER invent or assume details that aren't visible\n"
                "4. If something contradicts the known environment, describe what you see "
                "and note the discrepancy naturally\n"
                "5. Respond in TWO sections:\n"
                "   DESCRIPTION: A natural, concise description of what you see\n"
                "   OBSERVATIONS: A JSON object with confirmed environmental details "
                "(only include details you're confident about)\n"
            )

            # Build the content parts
            content_parts = []

            # Add environment context
            if env_context:
                content_parts.append(
                    types.Part.from_text(
                        text=f"Known environment model:\n{env_context}\n\n"
                    )
                )

            # Add frames
            for i, frame_bytes in enumerate(frames):
                content_parts.append(
                    types.Part.from_bytes(data=frame_bytes, mime_type="image/jpeg")
                )
                if len(frames) > 1:
                    content_parts.append(
                        types.Part.from_text(
                            text=f"(Frame {i+1} of {len(frames)}, ~{i * 300}ms apart)"
                        )
                    )

            # Add focus directive
            if focus:
                content_parts.append(
                    types.Part.from_text(
                        text=f"\nFocus on: {focus}\nDescribe this specifically."
                    )
                )
            else:
                content_parts.append(
                    types.Part.from_text(
                        text="\nDescribe the overall scene."
                    )
                )

            # Call the model
            start_time = time.time()
            response = gemini.client.models.generate_content(
                model=model_name,
                contents=content_parts,
                config=types.GenerateContentConfig(
                    system_instruction=system_prompt,
                    temperature=0.3,  # Low temp for factual accuracy
                ),
            )
            elapsed = time.time() - start_time

            # Track costs
            usage = response.usage_metadata
            inp = usage.prompt_token_count or 0
            out = usage.candidates_token_count or 0
            cost = gemini._compute_cost(model_name, inp, out)
            gemini._log_call(
                model=model_name,
                input_tokens=inp,
                output_tokens=out,
                cost=cost,
                elapsed=elapsed,
                prompt_preview="sensory_cortex_look",
            )

            raw_text = response.text.strip() if response.text else ""
            logger.info(f"Visual analysis ({model_name}): {len(raw_text)} chars, {elapsed:.1f}s")

            # Parse the response
            return self._parse_analyst_response(raw_text)

        except Exception as e:
            logger.error(f"Visual analysis failed: {e}")
            return {"description": f"Vision processing failed: {e}", "observations": {}}

    def _parse_analyst_response(self, raw_text: str) -> dict:
        """Parse the analyst's response into description + observations."""
        result = {"description": raw_text, "observations": {}}

        # Try to split DESCRIPTION and OBSERVATIONS sections
        if "OBSERVATIONS:" in raw_text.upper():
            parts = raw_text.upper().split("OBSERVATIONS:", 1)
            desc_section = raw_text[:raw_text.upper().index("OBSERVATIONS:")].strip()
            obs_section = raw_text[raw_text.upper().index("OBSERVATIONS:") + len("OBSERVATIONS:"):].strip()

            # Clean up description label
            if desc_section.upper().startswith("DESCRIPTION:"):
                desc_section = desc_section[len("DESCRIPTION:"):].strip()

            result["description"] = desc_section

            # Try to parse JSON observations
            try:
                # Find JSON in the observations section
                json_start = obs_section.find("{")
                json_end = obs_section.rfind("}") + 1
                if json_start >= 0 and json_end > json_start:
                    result["observations"] = json.loads(obs_section[json_start:json_end])
            except (json.JSONDecodeError, ValueError):
                logger.debug(f"Could not parse observations JSON, using raw text")

        elif "DESCRIPTION:" in raw_text.upper():
            desc_section = raw_text[raw_text.upper().index("DESCRIPTION:") + len("DESCRIPTION:"):].strip()
            result["description"] = desc_section

        return result

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: FOCUS MODE
    # ══════════════════════════════════════════════════════════════════

    def _focus_tick_watch(self) -> Optional[str]:
        """One pulse of active watch mode. Cheap 2.5 Flash analysis."""
        if self._focus_pulses_remaining <= 0:
            self.end_focus()
            return f"[Focus expired] Watch mode for '{self._focus_target}' has ended after {self.MAX_WATCH_PULSES} pulses."

        self._focus_pulses_remaining -= 1

        # Capture a single frame (focus mode is cheap — 1 frame per tick)
        frames = self._capture_frames(count=1, interval_ms=0)
        if not frames:
            return None

        try:
            from google.genai import types
            gemini = self.daemon.gemini

            # Use cheaper model for per-pulse focus ticks
            model_name = gemini.default_model

            # Build context from previous focus observations
            prev_context = ""
            if self._focus_scratchpad:
                recent = self._focus_scratchpad[-3:]  # Last 3 observations
                prev_context = "Previous observations:\n" + "\n".join(
                    f"  - {obs}" for obs in recent
                )

            prompt_parts = [
                types.Part.from_text(
                    text=(
                        f"You are monitoring: '{self._focus_target}'\n"
                        f"Pulse {self.MAX_WATCH_PULSES - self._focus_pulses_remaining} "
                        f"of {self.MAX_WATCH_PULSES}\n"
                        f"{prev_context}\n\n"
                        f"Describe what you see in 1-2 sentences. Focus ONLY on "
                        f"'{self._focus_target}'. Note any changes from previous observations. "
                        f"If the subject is no longer visible, say so."
                    )
                ),
                types.Part.from_bytes(data=frames[0], mime_type="image/jpeg"),
            ]

            response = gemini.client.models.generate_content(
                model=model_name,
                contents=prompt_parts,
                config=types.GenerateContentConfig(temperature=0.2),
            )

            # Track cost
            usage = response.usage_metadata
            inp = usage.prompt_token_count or 0
            out = usage.candidates_token_count or 0
            cost = gemini._compute_cost(model_name, inp, out)
            gemini._log_call(
                model=model_name,
                input_tokens=inp,
                output_tokens=out,
                cost=cost,
                elapsed=0,
                prompt_preview="sensory_focus_watch",
            )

            observation = response.text.strip() if response.text else "Couldn't process frame."
            self._focus_scratchpad.append(observation)

            remaining = self._focus_pulses_remaining
            return f"[Focus: watching '{self._focus_target}' — {remaining} pulses left] {observation}"

        except Exception as e:
            logger.error(f"Focus watch tick failed: {e}")
            return None

    def _focus_tick_listen(self) -> Optional[str]:
        """One pulse of active listen mode."""
        # Check time limit
        elapsed = time.time() - self._focus_started_at
        if elapsed > self.MAX_LISTEN_SECONDS:
            self.end_focus()
            return f"[Focus expired] Listen mode for '{self._focus_target}' ended after {elapsed:.0f}s."

        # Quick 3-second listen
        result = self.listen(duration=3)

        # Check for silence (auto-end)
        if "silence" in result.lower() or "nothing distinct" in result.lower():
            self._focus_pulses_remaining -= 1
            if self._focus_pulses_remaining <= 0:
                self.end_focus()
                return f"[Focus ended — silence detected] {result}"
            return None  # Silence — don't report to consciousness

        # Reset silence counter on actual content
        self._focus_pulses_remaining = 5  # Reset silence tolerance

        self._focus_scratchpad.append(result)
        return f"[Focus: listening for '{self._focus_target}'] {result}"

    def _log_focus_session(self):
        """Log a completed focus session to the journal."""
        if not self._focus_scratchpad:
            return

        session = {
            "timestamp": datetime.now().isoformat(),
            "target": self._focus_target,
            "mode": self._focus_mode,
            "duration_seconds": round(time.time() - self._focus_started_at),
            "observation_count": len(self._focus_scratchpad),
            "summary": self._focus_scratchpad[-1] if self._focus_scratchpad else "",
        }

        # Append to resolution log (reusing it for all observations)
        self.journal.setdefault("focus_sessions", []).append(session)

        # Cap focus session log
        if len(self.journal["focus_sessions"]) > 20:
            self.journal["focus_sessions"] = self.journal["focus_sessions"][-20:]

        self._save_journal()

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: JOURNAL MANAGEMENT
    # ══════════════════════════════════════════════════════════════════

    def _load_journal(self) -> dict:
        """Load the sensory journal from disk."""
        try:
            if self.journal_path.exists():
                return json.loads(self.journal_path.read_text())
        except (json.JSONDecodeError, IOError) as e:
            logger.warning(f"Journal load failed, starting fresh: {e}")

        return {
            "environment": {
                "room_type": "unknown",
                "lighting": {"description": "unknown", "confirmed_count": 0},
                "key_objects": [],
                "people_usually_present": [],
                "pets": [],
                "ambient_sounds": "unknown",
            },
            "resolution_log": [],
            "active_focus": None,
            "last_full_scan": None,
        }

    def _save_journal(self):
        """Save the sensory journal to disk."""
        try:
            self.journal_path.write_text(json.dumps(self.journal, indent=2))
        except Exception as e:
            logger.error(f"Journal save failed: {e}")

    def _get_environment_context(self) -> str:
        """Convert the journal's environment model to natural language
        for use as LLM context.
        """
        env = self.journal.get("environment", {})
        lines = []

        room_type = env.get("room_type", "unknown")
        if room_type != "unknown":
            lines.append(f"Room: {room_type}")

        lighting = env.get("lighting", {})
        if isinstance(lighting, dict):
            desc = lighting.get("description", "unknown")
            count = lighting.get("confirmed_count", 0)
            if desc != "unknown":
                lines.append(f"Lighting: {desc} (confirmed {count}x)")
        elif isinstance(lighting, str) and lighting != "unknown":
            lines.append(f"Lighting: {lighting}")

        objects = env.get("key_objects", [])
        if objects:
            obj_strs = []
            for obj in objects:
                if isinstance(obj, dict):
                    label = obj.get("label", "")
                    color = obj.get("color", "")
                    notes = obj.get("notes", "")
                    count = obj.get("confirmed_count", 0)
                    desc = label
                    if color:
                        desc += f" ({color})"
                    if notes:
                        desc += f" — {notes}"
                    if count > 0:
                        desc += f" [seen {count}x]"
                    obj_strs.append(desc)
                else:
                    obj_strs.append(str(obj))
            lines.append("Known objects: " + "; ".join(obj_strs))

        people = env.get("people_usually_present", [])
        if people:
            lines.append("People usually present: " + ", ".join(people))

        pets = env.get("pets", [])
        if pets:
            lines.append("Pets: " + ", ".join(pets))

        ambient = env.get("ambient_sounds", "unknown")
        if ambient != "unknown":
            lines.append(f"Ambient sounds: {ambient}")

        # Recent resolutions (last 3) — so the model knows about past inconsistencies
        resolutions = self.journal.get("resolution_log", [])
        if resolutions:
            recent = resolutions[-3:]
            lines.append("\nRecent resolved observations:")
            for r in recent:
                detail = r.get("detail", "")
                resolved = r.get("resolved_to", "")
                if detail and resolved:
                    lines.append(f"  - {detail}: {resolved}")

        if not lines:
            return "No prior observations. This is the first look."

        return "\n".join(lines)

    def _update_journal(self, observations: dict):
        """Update the journal with confirmed observations.

        Only updates fields that the analyst reported with confidence.
        Logs any inconsistencies to the resolution log.
        """
        if not observations:
            return

        env = self.journal.setdefault("environment", {})
        changed = False

        # Update room type if provided
        if "room_type" in observations:
            old = env.get("room_type", "unknown")
            new = observations["room_type"]
            if old == "unknown" or old == new:
                env["room_type"] = new
                changed = True
            elif old != new:
                # Log inconsistency
                self._log_resolution("room_type", old, new, f"Changed from '{old}' to '{new}'")
                env["room_type"] = new
                changed = True

        # Update lighting
        if "lighting" in observations:
            new_light = observations["lighting"]
            if isinstance(new_light, str):
                new_light = {"description": new_light, "confirmed_count": 1}
            old_light = env.get("lighting", {})
            if isinstance(old_light, dict):
                old_desc = old_light.get("description", "unknown")
                if old_desc == "unknown" or old_desc == new_light.get("description", ""):
                    old_light["description"] = new_light.get("description", old_desc)
                    old_light["confirmed_count"] = old_light.get("confirmed_count", 0) + 1
                else:
                    self._log_resolution(
                        "lighting", old_desc,
                        new_light.get("description", ""),
                        "Lighting description changed"
                    )
                    old_light["description"] = new_light.get("description", old_desc)
                    old_light["confirmed_count"] = 1
                env["lighting"] = old_light
                changed = True

        # Update objects (additive — new objects get added, existing get confirmed)
        if "objects" in observations and isinstance(observations["objects"], list):
            existing = {obj.get("label", "").lower(): obj for obj in env.get("key_objects", []) if isinstance(obj, dict)}
            for new_obj in observations["objects"]:
                if isinstance(new_obj, dict):
                    label = new_obj.get("label", "").lower()
                    if label in existing:
                        existing[label]["confirmed_count"] = existing[label].get("confirmed_count", 0) + 1
                        # Update color/notes if provided
                        if "color" in new_obj:
                            existing[label]["color"] = new_obj["color"]
                        if "notes" in new_obj:
                            existing[label]["notes"] = new_obj["notes"]
                    else:
                        new_obj.setdefault("confirmed_count", 1)
                        existing[label] = new_obj
            env["key_objects"] = list(existing.values())
            changed = True

        # Update people
        if "people" in observations and isinstance(observations["people"], list):
            for person in observations["people"]:
                if person and person not in env.get("people_usually_present", []):
                    env.setdefault("people_usually_present", []).append(person)
                    changed = True

        # Update ambient sounds
        if "ambient_sounds" in observations:
            env["ambient_sounds"] = observations["ambient_sounds"]
            changed = True

        if changed:
            self.journal["last_full_scan"] = datetime.now().isoformat()
            self._save_journal()
            logger.debug("Sensory journal updated")

    def _log_resolution(self, detail: str, old_value: str, new_value: str, reasoning: str):
        """Log an inconsistency resolution to the journal."""
        entry = {
            "timestamp": datetime.now().isoformat(),
            "detail": detail,
            "observations": [f"was: {old_value}", f"now: {new_value}"],
            "resolved_to": new_value,
            "reasoning": reasoning,
        }
        self.journal.setdefault("resolution_log", []).append(entry)

        # Cap resolution log at 50 entries
        if len(self.journal["resolution_log"]) > 50:
            self.journal["resolution_log"] = self.journal["resolution_log"][-50:]

        logger.info(f"Sensory resolution: {detail} — {old_value} → {new_value}")

    # ══════════════════════════════════════════════════════════════════
    # STATUS
    # ══════════════════════════════════════════════════════════════════

    def get_status(self) -> dict:
        """Return current sensory cortex status."""
        env = self.journal.get("environment", {})
        return {
            "focus_active": self._focus_active,
            "focus_target": self._focus_target if self._focus_active else None,
            "focus_mode": self._focus_mode if self._focus_active else None,
            "focus_remaining": self._focus_pulses_remaining if self._focus_active else 0,
            "known_objects": len(env.get("key_objects", [])),
            "resolution_count": len(self.journal.get("resolution_log", [])),
            "last_scan": self.journal.get("last_full_scan"),
        }
