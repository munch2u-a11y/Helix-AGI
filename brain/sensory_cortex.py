"""
Helix — Vision Cortex

Subconscious visual perception system. All camera input passes through
this module before reaching consciousness. Uses Gemma3 4B vision model
running locally via Ollama.

Architecture:
    - Gemma3:4b runs via Ollama's HTTP API (localhost:11434)
    - Maintains a visual memory buffer (last N scene descriptions)
    - Each look() call captures 2 frames, feeds previous scene context
      to detect changes vs stable elements
    - PTZ motor control (EMEET PIXY) for camera positioning
    - Sensory journal for persistent environmental model

Conscious-facing tools:
    look(focus?)        — Capture + analyze what's visible
    ptz_look(direction) — Move camera head to look somewhere
    camera_auto_track(enabled) — Toggle face auto-tracking
"""

import os
import cv2
import json
import time
import fcntl
import struct
import logging
import threading
import sounddevice as sd
from faster_whisper import WhisperModel
import requests
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional

try:
    from llm.providers.gemini_provider import GeminiProvider
except ImportError:
    GeminiProvider = None

logger = logging.getLogger("helix.brain.sensory_cortex")

# Ollama vision model
_OLLAMA_MODEL = "gemma3:4b"
_OLLAMA_URL = "http://localhost:11434"

# How many scene descriptions to keep in the rolling buffer
_VISUAL_MEMORY_SIZE = 10


class SensoryCortex:
    """Subconscious visual perception — processes camera input through
    a local VL model (Gemma3 4B via Ollama) before it reaches consciousness.

    The conscious model never sees raw pixels. It receives processed,
    contextually grounded scene descriptions.
    """

    def __init__(self, camera_device: int = 0, n_gpu_layers: int = -1):
        """Initialize the vision cortex.

        Args:
            camera_device: V4L2 device index (default 0)
            n_gpu_layers: Unused (kept for API compat). Ollama manages GPU.
        """
        self.camera_device = self._auto_detect_camera(camera_device)
        self._n_gpu_layers = n_gpu_layers

        # Ollama readiness flag (checked on first use)
        self._ollama_verified = False
        self._model_lock = threading.Lock()

        # Visual memory buffer — rolling window of recent observations
        self._visual_memory: list[dict] = []

        # Sensory journal — persistent environmental model
        self._journal_path = Path(__file__).parent.parent / "data" / "sensory_journal.json"
        self._journal = self._load_journal()

        # PTZ state

        self._auto_tracking = True
        self._camera_v4l2_path = f"/dev/video{self.camera_device}"

        # --- Passive Background State ---
        self._passive_active = False
        self._video_thread = None
        self._audio_stream = None
        self._latest_frame = None
        self._audio_buffer = []
        self._audio_lock = threading.Lock()
        # Ensure model for background audio
        self._whisper_model = None

        # Provider settings: default to 'local' for cost efficiency
        self._provider = os.environ.get("HELIX_VISION_PROVIDER", "local").lower()
        self._model = os.environ.get("HELIX_VISION_MODEL", "gemini-2.5-flash")

        logger.info(
            f"Vision Cortex initialized (camera={self.camera_device}, "
            f"provider={self._provider}, model={self._model})"
        )

    def _auto_detect_camera(self, default_index: int = 0) -> int:
        """Find the first available camera device that can read a frame."""
        # Try default first
        cap = cv2.VideoCapture(default_index)
        if cap.isOpened():
            ret, _ = cap.read()
            cap.release()
            if ret:
                return default_index
                
        # Search others
        for i in range(10):
            if i == default_index:
                continue
            cap = cv2.VideoCapture(i)
            if cap.isOpened():
                ret, _ = cap.read()
                cap.release()
                if ret:
                    logger.info(f"Auto-detected working camera at index {i}")
                    return i
                    
        logger.warning(f"No working camera found! Falling back to index {default_index}")
        return default_index

    # ══════════════════════════════════════════════════════════════════
    # MODEL MANAGEMENT (Ollama)
    # ══════════════════════════════════════════════════════════════════

    def _ensure_model(self):
        """Verify Ollama is running and the vision model is available.

        Thread-safe. Only checks once per session — Ollama manages
        model lifecycle independently.
        """
        if self._ollama_verified:
            return

        with self._model_lock:
            if self._ollama_verified:
                return

            logger.info(f"Verifying Ollama vision model ({_OLLAMA_MODEL})...")

            try:
                resp = requests.get(f"{_OLLAMA_URL}/api/tags", timeout=5)
                if resp.status_code != 200:
                    raise RuntimeError(f"Ollama not responding (HTTP {resp.status_code})")

                models = [m["name"] for m in resp.json().get("models", [])]
                # Check for exact match or base name match
                if _OLLAMA_MODEL not in models:
                    raise RuntimeError(
                        f"Model {_OLLAMA_MODEL} not found in Ollama. "
                        f"Available: {models}. Run: ollama pull {_OLLAMA_MODEL}"
                    )

                self._ollama_verified = True
                logger.info(f"Ollama vision model verified: {_OLLAMA_MODEL}")
            except requests.ConnectionError:
                raise RuntimeError(
                    "Ollama not running. Start it with: ollama serve"
                )

    def unload(self):
        """Reset verification flag. Ollama manages model memory."""
        self._ollama_verified = False
        logger.info("Vision cortex Ollama verification reset")

    # ══════════════════════════════════════════════════════════════════
    # CONSCIOUS-FACING: LOOK
    # ══════════════════════════════════════════════════════════════════

    def look(self, focus: str = "") -> str:
        """Process a visual observation request from consciousness.

        Captures 2 frames (300ms apart) for consistency verification.
        Feeds previous scene context so the model can flag changes.

        Args:
            focus: Optional focus description ("the desk", "the monitor", etc.)

        Returns:
            Natural language scene description.
        """
        # Capture 2 frames
        frames = self._capture_frames(count=2, interval_ms=300)
        if not frames:
            return "Camera not available — couldn't capture any images."

        # Build context from visual memory
        context = self._build_visual_context()

        # Analyze with Moondream
        try:
            self._ensure_model()
        except Exception as e:
            return f"Vision system unavailable: {e}"

        # Use the most recent frame for analysis (second frame, after auto-exposure)
        image_bytes = frames[-1]

        # Build the prompt
        prompt = "Describe what you see in this image. Be factual and precise."
        if focus:
            prompt += f" Focus on: {focus}"
        if context:
            prompt += f"\n\nPrevious scene context: {context}"
            prompt += "\nNote any changes from the previous observation."

        try:
            description = self._analyze_image(image_bytes, prompt)
        except Exception as e:
            return f"Vision analysis failed: {e}"

        # Store to visual memory
        self._store_observation(description, focus)

        # Update journal with environmental info
        self._update_journal_from_observation(description)

        return description

    # ══════════════════════════════════════════════════════════════════
    # CONSCIOUS-FACING: RECORD VIDEO
    # ══════════════════════════════════════════════════════════════════

    _VALID_DURATIONS = {5, 10, 15}

    def record_video(self, duration: int = 5, focus: str = "") -> str:
        """Record a short video clip and analyze key frames.

        Pipeline:
          1. Record video from camera → save .mp4 to disk
          2. Sample ~4 key frames at regular intervals during recording
          3. Analyze each key frame through Moondream with temporal context
          4. Build a timestamped narrative of what was observed
          5. Store the narrative in visual memory
          6. Return the narrative + file path

        Args:
            duration: Recording length — must be 5, 10, or 15 seconds.
            focus: Optional focus description for Moondream analysis.

        Returns:
            Temporal narrative of what was observed + file path.
        """
        # Validate duration
        if duration not in self._VALID_DURATIONS:
            duration = min(self._VALID_DURATIONS, key=lambda d: abs(d - duration))
            logger.info(f"Video duration snapped to {duration}s")

        output_dir = Path(__file__).parent.parent / "data" / "screenshots"
        output_dir.mkdir(parents=True, exist_ok=True)

        recording_time = datetime.now()
        timestamp_str = recording_time.strftime("%Y%m%d_%H%M%S")
        output_path = output_dir / f"video_{timestamp_str}.mp4"

        # ── Phase 1: Record video + capture key frames ────────────
        #    We record at 15fps and sample ~4 key frames at even
        #    intervals for subsequent Moondream analysis.
        fps = 15
        num_key_frames = 4
        frame_interval = max(1, (duration * fps) // num_key_frames)
        key_frame_indices = set(
            i * frame_interval for i in range(num_key_frames)
        )

        try:
            total_frames = duration * fps
            interval = 1.0 / fps
            key_frames = []  # (timestamp_seconds, jpeg_bytes)
            
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(str(output_path), fourcc, fps, (1280, 720))

            if self._passive_active:
                for i in range(total_frames):
                    if self._latest_frame:
                        frame_array = np.frombuffer(self._latest_frame, np.uint8)
                        frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                        if frame is not None:
                            writer.write(frame)
                            if i in key_frame_indices:
                                key_frames.append((i / fps, self._latest_frame))
                    time.sleep(interval)
                writer.release()
            else:
                cap = cv2.VideoCapture(self.camera_device)
                if not cap.isOpened():
                    return "Camera not available — couldn't start recording."

                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

                # Warm up auto-exposure
                for _ in range(5):
                    cap.read()

                for i in range(total_frames):
                    ret, frame = cap.read()
                    if not ret:
                        continue
                    writer.write(frame)

                    # Sample key frame
                    if i in key_frame_indices:
                        _, buf = cv2.imencode(
                            ".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 92]
                        )
                        seconds = i / fps
                        key_frames.append((seconds, buf.tobytes()))

                    time.sleep(interval)

                writer.release()
                cap.release()

        except Exception as e:
            logger.error(f"Video recording failed: {e}")
            return f"Recording failed: {e}"

        if not key_frames:
            return "Recording completed but no frames were captured."

        size_kb = output_path.stat().st_size // 1024
        logger.info(
            f"Video recorded: {duration}s @ {fps}fps, "
            f"{len(key_frames)} key frames, {size_kb}KB → {output_path}"
        )

        # ── Phase 2: Analyze key frames through Moondream ─────────
        #    Each frame gets temporal context from the previous
        #    frame's description so Moondream reports changes.
        try:
            self._ensure_model()
        except Exception as e:
            # Recording succeeded but analysis failed — return path
            return (
                f"Video saved to {output_path} ({duration}s, {size_kb}KB) "
                f"but visual analysis unavailable: {e}"
            )

        observations = []
        previous_desc = ""

        for seconds, image_bytes in key_frames:
            # Build temporal prompt
            ts_label = f"{int(seconds // 60)}:{int(seconds % 60):02d}"

            prompt = (
                f"This is a frame from a {duration}-second video recording "
                f"at timestamp {ts_label}. "
                f"Describe what you see. Be factual and concise."
            )
            if focus:
                prompt += f" Focus on: {focus}"
            if previous_desc:
                prompt += (
                    f"\n\nThe previous frame showed: {previous_desc}\n"
                    f"Note any changes or movement since then."
                )

            try:
                desc = self._analyze_image(image_bytes, prompt)
                observations.append((ts_label, desc))
                previous_desc = desc
            except Exception as e:
                observations.append((ts_label, f"(analysis failed: {e})"))
                logger.warning(f"Frame analysis failed at {ts_label}: {e}")

        # ── Phase 3: Build temporal narrative ─────────────────────
        time_label = recording_time.strftime("%H:%M:%S")
        narrative_lines = [
            f"Video recorded ({duration}s) at {time_label} "
            f"— saved to {output_path.name}",
            "",
            "Observations:",
        ]
        for ts_label, desc in observations:
            narrative_lines.append(f"  {ts_label} — {desc}")

        narrative = "\n".join(narrative_lines)

        # ── Phase 4: Store to visual memory ───────────────────────
        self._store_observation(
            description=f"[VIDEO {duration}s] {'; '.join(d for _, d in observations)}",
            focus=focus or "video recording",
        )

        logger.info(
            f"Video analysis complete: {len(observations)} frames analyzed"
        )

        return narrative

    # ══════════════════════════════════════════════════════════════════
    # CONSCIOUS-FACING: PTZ
    # ══════════════════════════════════════════════════════════════════

    # Named direction presets (degrees)
    # Pan:  -150 (full left) to +150 (full right)
    # Tilt: -90 (straight down) to +90 (straight up)
    DIRECTION_MAP = {
        "center":               (0,     0),
        "left":                 (-90,   0),
        "right":                (90,    0),
        "hard_left":            (-150,  0),
        "hard_right":           (150,   0),
        "up":                   (0,     45),
        "down":                 (0,    -45),
        "behind":               (-150,  0),
        "behind_left":          (-150,  0),
        "behind_right":         (150,   0),
        "over_shoulder_left":   (-120,  15),
        "over_shoulder_right":  (120,   15),
        "slight_left":          (-45,   0),
        "slight_right":         (45,    0),
        "up_left":              (-45,   30),
        "up_right":             (45,    30),
        "down_left":            (-45,  -30),
        "down_right":           (45,   -30),
    }

    def ptz_look(self, direction: str = "", pan: int = None, tilt: int = None) -> str:
        """Move the EMEET PIXY camera head to look in a direction.

        Accepts named directions or exact pan/tilt degrees.
        Disables auto-tracking when a manual direction is set.

        Hardware: EMEET PIXY via V4L2 UVC
          Pan:  ±540000 arc-sec (±150°), step 3600 (1°)
          Tilt: ±324000 arc-sec (±90°),  step 3600 (1°)
        """
        direction = direction.strip().lower().replace(" ", "_")

        if pan is not None or tilt is not None:
            pan_deg = max(-150, min(150, int(pan or 0)))
            tilt_deg = max(-90, min(90, int(tilt or 0)))
        elif direction in self.DIRECTION_MAP:
            pan_deg, tilt_deg = self.DIRECTION_MAP[direction]
        elif direction:
            return (
                f"Unknown direction '{direction}'. "
                f"Use: {', '.join(sorted(self.DIRECTION_MAP.keys()))} "
                f"or provide exact pan/tilt degrees."
            )
        else:
            return "Provide a direction name or pan/tilt degrees."

        # Convert degrees to EMEET arc-seconds (3600 arc-seconds per degree)
        pan_arcsec = int(pan_deg * 3600)
        tilt_arcsec = int(tilt_deg * 3600)

        # Disable auto-tracking when manually pointing
        self._auto_tracking = False

        result = self._send_ptz_command(pan_val=pan_arcsec, tilt_val=tilt_arcsec)

        direction_label = direction if direction else f"pan={pan_deg}°, tilt={tilt_deg}°"
        logger.info(f"PTZ: {direction_label} → pan={pan_arcsec}, tilt={tilt_arcsec}")
        return f"Camera moved: looking {direction_label}. Auto-tracking disabled."

    def camera_auto_track(self, enabled: bool = True) -> str:
        """Toggle the EMEET PIXY's built-in face auto-tracking."""
        if enabled:
            self._send_ptz_command(pan_val=0, tilt_val=0)
            self._auto_tracking = True
            return "Auto-tracking enabled. Camera will follow faces automatically."
        else:
            self._auto_tracking = False
            return "Auto-tracking disabled. Camera will stay where you point it."

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: CAPTURE
    # ══════════════════════════════════════════════════════════════════

    def _capture_frames(self, count: int = 2, interval_ms: int = 300) -> list:
        """Capture multiple frames from the webcam as JPEG bytes.

        Returns a list of JPEG byte arrays.
        """
        if self._passive_active and self._latest_frame:
            # Camera is locked by the passive background thread, use the buffer
            frames = []
            for i in range(count):
                frames.append(self._latest_frame)
                if i < count - 1:
                    time.sleep(interval_ms / 1000.0)
            return frames

        try:
            cap = cv2.VideoCapture(self.camera_device)
            if not cap.isOpened():
                return []

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
            logger.error(f"Frame capture failed: {e}")
            return []

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: ANALYSIS (Gemma3 via Ollama)
    # ══════════════════════════════════════════════════════════════════

    def _analyze_local(self, image_bytes: bytes, prompt: str) -> str:
        """Analyze an image using the Ollama vision model.

        Sends the image as base64 to Ollama's chat API with the
        configured vision model (gemma3:4b).
        """
        import base64

        if not self._ollama_verified:
            raise RuntimeError("Ollama vision model not verified")

        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        t0 = time.time()
        try:
            resp = requests.post(
                f"{_OLLAMA_URL}/api/chat",
                json={
                    "model": _OLLAMA_MODEL,
                    "messages": [
                        {
                            "role": "user",
                            "content": prompt,
                            "images": [b64_image],
                        }
                    ],
                    "stream": False,
                    "options": {
                        "temperature": 0.2,
                        "num_predict": 512,
                    },
                },
                timeout=120,
            )
            resp.raise_for_status()
        except requests.ConnectionError:
            raise RuntimeError("Ollama not running")
        except requests.Timeout:
            raise RuntimeError("Ollama vision analysis timed out (120s)")

        elapsed = time.time() - t0
        data = resp.json()
        result = data.get("message", {}).get("content", "").strip()
        tokens = data.get("eval_count", "?")

        logger.info(
            f"Ollama vision analysis: {len(result)} chars, "
            f"{tokens} tokens, {elapsed:.1f}s"
        )

        return result if result else "(no description generated)"

    def _analyze_image(self, image_bytes: bytes, prompt: str) -> str:
        """Analyze an image using either the Gemini API or the local Ollama model
        based on the configured provider.
        """
        if self._provider == "gemini":
            if GeminiProvider and os.environ.get("GEMINI_API_KEY"):
                from google.genai import types
                provider = GeminiProvider(model=self._model)
                
                prompt_parts = [
                    types.Part.from_text(text=prompt),
                    types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"),
                ]
                response = provider.client.models.generate_content(
                    model=self._model,
                    contents=prompt_parts,
                    config=types.GenerateContentConfig(temperature=0.2),
                )
                description = response.text.strip() if response.text else "(no description generated)"
                logger.info(
                    f"Gemini vision analysis ({self._model}): {len(description)} chars"
                )
                return description
            else:
                logger.warning(
                    "Gemini requested for vision, but GeminiProvider or GEMINI_API_KEY is missing. "
                    "Falling back to local."
                )
                return self._analyze_local(image_bytes, prompt)
        else:
            return self._analyze_local(image_bytes, prompt)

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: VISUAL MEMORY
    # ══════════════════════════════════════════════════════════════════

    def _build_visual_context(self) -> str:
        """Build context from the most recent visual observation."""
        if not self._visual_memory:
            return ""

        last = self._visual_memory[-1]
        ts = last["timestamp"]
        desc = last["description"]
        age = time.time() - last["time"]

        if age < 60:
            freshness = "just now"
        elif age < 300:
            freshness = f"{int(age/60)} minutes ago"
        else:
            freshness = f"{int(age/60)} minutes ago (may be outdated)"

        return f"[{freshness}] {desc[:300]}"

    def _store_observation(self, description: str, focus: str = ""):
        """Store a scene description in the visual memory buffer."""
        entry = {
            "timestamp": datetime.now().strftime("%H:%M:%S"),
            "time": time.time(),
            "description": description,
            "focus": focus,
        }

        self._visual_memory.append(entry)

        # Trim to buffer size
        if len(self._visual_memory) > _VISUAL_MEMORY_SIZE:
            self._visual_memory = self._visual_memory[-_VISUAL_MEMORY_SIZE:]

    def get_recent_observations(self, count: int = 3) -> list:
        """Return the N most recent visual observations (for preconscious use)."""
        return self._visual_memory[-count:]

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: SENSORY JOURNAL
    # ══════════════════════════════════════════════════════════════════

    def _load_journal(self) -> dict:
        """Load the persistent environmental model."""
        if self._journal_path.exists():
            try:
                return json.loads(self._journal_path.read_text())
            except Exception:
                pass
        return {
            "environment": {
                "last_updated": None,
                "lighting": "unknown",
                "location": "unknown",
                "ambient_sounds": "unknown",
                "notable_objects": [],
            },
            "observation_count": 0,
        }

    def _save_journal(self):
        """Persist the environmental model."""
        try:
            self._journal_path.parent.mkdir(parents=True, exist_ok=True)
            self._journal_path.write_text(json.dumps(self._journal, indent=2))
        except Exception as e:
            logger.warning(f"Failed to save sensory journal: {e}")

    def _update_journal_from_observation(self, description: str):
        """Update the journal with new environmental data from an observation."""
        self._journal["observation_count"] = self._journal.get("observation_count", 0) + 1
        self._journal["environment"]["last_updated"] = datetime.now().isoformat()

        # Simple keyword-based environmental updates
        desc_lower = description.lower()

        if any(w in desc_lower for w in ["dark", "dim", "low light"]):
            self._journal["environment"]["lighting"] = "dark/dim"
        elif any(w in desc_lower for w in ["bright", "sunlight", "well-lit"]):
            self._journal["environment"]["lighting"] = "bright"

        self._save_journal()

    # ══════════════════════════════════════════════════════════════════
    # INTERNAL: PTZ MOTOR CONTROL (EMEET PIXY)
    # ══════════════════════════════════════════════════════════════════

    def _send_ptz_command(self, pan_val: int = None, tilt_val: int = None) -> str:
        """Send UVC hardware commands to manually tilt/pan the EMEET PIXY.

        V4L2_CID_PAN_ABSOLUTE  = 0x009a0908
        V4L2_CID_TILT_ABSOLUTE = 0x009a0909
        VIDIOC_S_CTRL          = 0xc008561c
        struct v4l2_control: { __u32 id; __s32 value; } (8 bytes)
        """
        if not os.path.exists(self._camera_v4l2_path):
            return "Camera device not found."

        try:
            fd = os.open(self._camera_v4l2_path, os.O_RDWR)
            try:
                if pan_val is not None:
                    data = struct.pack('ii', 0x009a0908, int(pan_val))
                    fcntl.ioctl(fd, 0xc008561c, data)
                if tilt_val is not None:
                    data = struct.pack('ii', 0x009a0909, int(tilt_val))
                    fcntl.ioctl(fd, 0xc008561c, data)
            finally:
                os.close(fd)
        except Exception as e:
            logger.warning(f"Failed to send PTZ command: {e}")
            return f"Hardware error: {e}"

        return f"Shifted gaze to pan={pan_val}, tilt={tilt_val}."

    def reset_posture(self):
        """Reset the EMEET PIXY to center, yielding control back to hardware tracker."""
        return self._send_ptz_command(pan_val=0, tilt_val=0)


    # ══════════════════════════════════════════════════════════════════
    # PASSIVE BACKGROUND SENSING (PULSE TICK)
    # ══════════════════════════════════════════════════════════════════

    def start_passive_sensing(self):
        """Start continuous background capture of camera and audio."""
        if self._passive_active:
            return
        
        self._passive_active = True
        logger.info("Starting passive sensory capture threads...")
        
        # Start video worker
        self._video_thread = threading.Thread(target=self._video_worker, daemon=True)
        self._video_thread.start()
        
        # Start audio worker
        try:
            def audio_cb(indata, frames, time_info, status):
                if self._passive_active:
                    with self._audio_lock:
                        self._audio_buffer.append(indata.copy())
            self._audio_stream = sd.InputStream(samplerate=16000, channels=1, dtype='int16', callback=audio_cb)
            self._audio_stream.start()
        except Exception as e:
            logger.error(f"Failed to start passive audio stream: {e}")
            
    def stop_passive_sensing(self):
        self._passive_active = False
        if self._audio_stream:
            self._audio_stream.stop()
            self._audio_stream.close()
            self._audio_stream = None
            
    def _video_worker(self):
        """Maintains the latest video frame without blocking."""
        cap = cv2.VideoCapture(self.camera_device)
        if not cap.isOpened():
            logger.error(f"Failed to open /dev/video{self.camera_device} for passive vision")
            return
            
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        
        while self._passive_active:
            ret, frame = cap.read()
            if ret:
                # Keep it lightweight
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                self._latest_frame = buf.tobytes()
            time.sleep(0.1) # Throttle to ~10 FPS
            
        cap.release()

    def pulse_tick(self) -> Optional[dict]:
        """Called each consciousness heartbeat to fetch sensory reality.
        Runs fully locally to avoid API costs and latency.
        """
        if not self._passive_active:
            return None
            
        # 1. Pop audio
        audio_text = "Silence."
        with self._audio_lock:
            if self._audio_buffer:
                audio_data = np.concatenate(self._audio_buffer, axis=0)
                self._audio_buffer.clear()
            else:
                audio_data = None
                
        if audio_data is not None:
            audio_float = audio_data.flatten().astype(np.float32) / 32768.0
            rms = np.sqrt(np.mean(audio_float ** 2))
            if rms >= 0.01:
                try:
                    if not self._whisper_model:
                        self._whisper_model = WhisperModel("base.en", device="cpu", compute_type="int8")
                    segments, _ = self._whisper_model.transcribe(
                        audio_float, 
                        beam_size=1, 
                        language="en",
                        vad_filter=True,
                        condition_on_previous_text=False
                    )
                    transcribed = " ".join(seg.text for seg in segments).strip()
                    if transcribed:
                        audio_text = transcribed
                except Exception as e:
                    logger.error(f"Background audio parsing failed: {e}")

        # 2. Pop video
        frame = self._latest_frame
        visual_desc = "Nothing discernible."
        if frame:
            try:
                # Use the local Ollama vision model
                self._ensure_model()
                prompt = "Describe exactly what you see right now in 1 sentence. Be factual and direct. Ignore the timestamp."
                visual_desc = self._analyze(frame, prompt)
            except Exception as e:
                logger.error(f"Background vision parsing failed: {e}")
                
        # 3. Combine into factual SensoryReality block
        sensory_text = (
            f"Visual: {visual_desc} | "
            f"Auditory: {audio_text}"
        )
        
        logger.debug(f"Pulse Tick: {sensory_text}")
        
        return {
            "type": "sensory_reality",
            "content": f"[SensoryReality] {sensory_text}"
        }
