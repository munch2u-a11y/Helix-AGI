"""
Helix — Vision Cortex

Subconscious visual perception system. All camera input passes through
this module before reaching consciousness. Uses Moondream (1B VL model)
running locally on llama.cpp with Vulkan GPU acceleration.

Architecture:
    - Moondream runs as a persistent model via llama_cpp_python + Vulkan
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
import numpy as np
from pathlib import Path
from datetime import datetime
from typing import Optional

logger = logging.getLogger("helix.brain.vision_cortex")

# Model paths (symlinks to Ollama blobs)
_MODEL_PATH = str(Path(__file__).parent.parent / "models" / "moondream-text.gguf")
_MMPROJ_PATH = str(Path(__file__).parent.parent / "models" / "moondream-mmproj.gguf")

# How many scene descriptions to keep in the rolling buffer
_VISUAL_MEMORY_SIZE = 10


class VisionCortex:
    """Subconscious visual perception — processes camera input through
    a local VL model (Moondream) before it reaches consciousness.

    The conscious model never sees raw pixels. It receives processed,
    contextually grounded scene descriptions.
    """

    def __init__(self, camera_device: int = 0, n_gpu_layers: int = -1):
        """Initialize the vision cortex.

        Args:
            camera_device: V4L2 device index (default 0)
            n_gpu_layers: GPU layers to offload (-1 = all, Vulkan)
        """
        self.camera_device = camera_device
        self._n_gpu_layers = n_gpu_layers

        # Moondream model (lazy-loaded on first use)
        self._model = None
        self._chat_handler = None
        self._model_lock = threading.Lock()

        # Visual memory buffer — rolling window of recent observations
        self._visual_memory: list[dict] = []

        # Sensory journal — persistent environmental model
        self._journal_path = Path(__file__).parent.parent / "data" / "sensory_journal.json"
        self._journal = self._load_journal()

        # PTZ state
        self._auto_tracking = True
        self._camera_v4l2_path = f"/dev/video{camera_device}"

        logger.info(
            f"Vision Cortex initialized (camera={camera_device}, "
            f"gpu_layers={n_gpu_layers}, model={Path(_MODEL_PATH).name})"
        )

    # ══════════════════════════════════════════════════════════════════
    # MODEL MANAGEMENT
    # ══════════════════════════════════════════════════════════════════

    def _ensure_model(self):
        """Lazy-load Moondream + CLIP projector on first use.

        Uses llama.cpp with Vulkan backend for GPU acceleration.
        Thread-safe — only one load at a time.
        """
        if self._model is not None:
            return

        with self._model_lock:
            if self._model is not None:
                return  # Double-check after acquiring lock

            logger.info("Loading Moondream VL model (Vulkan backend)...")
            t0 = time.time()

            try:
                from llama_cpp import Llama
                from llama_cpp.llama_chat_format import MoondreamChatHandler

                self._chat_handler = MoondreamChatHandler(
                    clip_model_path=_MMPROJ_PATH,
                    verbose=False,
                )

                self._model = Llama(
                    model_path=_MODEL_PATH,
                    chat_handler=self._chat_handler,
                    n_ctx=2048,
                    n_gpu_layers=self._n_gpu_layers,  # -1 = offload all to Vulkan
                    verbose=False,
                )

                elapsed = time.time() - t0
                logger.info(f"Moondream loaded in {elapsed:.1f}s (Vulkan GPU offload)")
            except Exception as e:
                logger.error(f"Failed to load Moondream: {e}")
                self._model = None
                raise

    def unload(self):
        """Explicitly free the model to reclaim memory."""
        with self._model_lock:
            if self._model is not None:
                del self._model
                self._model = None
                del self._chat_handler
                self._chat_handler = None
                logger.info("Moondream unloaded — VRAM freed")

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
            description = self._analyze(image_bytes, prompt)
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
            cap = cv2.VideoCapture(self.camera_device)
            if not cap.isOpened():
                return "Camera not available — couldn't start recording."

            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)

            # Warm up auto-exposure
            for _ in range(5):
                cap.read()

            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(
                str(output_path), fourcc, fps, (1280, 720)
            )

            total_frames = duration * fps
            interval = 1.0 / fps
            key_frames = []  # (timestamp_seconds, jpeg_bytes)

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
                desc = self._analyze(image_bytes, prompt)
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
    # INTERNAL: ANALYSIS (Moondream via llama.cpp)
    # ══════════════════════════════════════════════════════════════════

    def _analyze(self, image_bytes: bytes, prompt: str) -> str:
        """Analyze an image using Moondream via llama.cpp.

        Uses the MoondreamChatHandler which handles image encoding
        and multimodal prompt construction internally.
        """
        import base64

        if self._model is None:
            raise RuntimeError("Moondream model not loaded")

        # Encode image as data URI for the chat handler
        b64_image = base64.b64encode(image_bytes).decode("utf-8")
        image_url = f"data:image/jpeg;base64,{b64_image}"

        # Use the chat completion API with vision message format
        t0 = time.time()
        response = self._model.create_chat_completion(
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "image_url", "image_url": {"url": image_url}},
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
            max_tokens=512,
            temperature=0.1,
        )
        elapsed = time.time() - t0

        result = response["choices"][0]["message"]["content"].strip()
        tokens = response.get("usage", {})
        logger.info(
            f"Moondream analysis: {len(result)} chars, "
            f"{tokens.get('total_tokens', '?')} tokens, {elapsed:.1f}s"
        )

        return result

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
