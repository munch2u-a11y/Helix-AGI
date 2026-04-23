"""
Helix_main — Passive Audio Monitor

Always-on, lightweight audio listener that detects:
1. Wake word ("Helix") via Whisper transcription
2. Loud events (amplitude spike) like door bangs, claps

When triggered, wakes consciousness and injects an event.

Architecture:
    PyAudio → 16kHz mono → webrtcvad (VAD) → buffer → faster-whisper base.en
    
Resource profile:
    - Idle: ~0 CPU (VAD is C-native, blocks on silence)
    - Active transcription: ~1-2s CPU burst per speech segment
    - Model RAM: ~140 MB (base.en, loaded once)
"""

import os
import time
import struct
import logging
import threading
import numpy as np
from pathlib import Path
from collections import deque

logger = logging.getLogger("helix.brain.audio_monitor")


class AudioMonitor:
    """Passive audio monitor that runs in a background thread."""

    def __init__(self, consciousness, config: dict = None):
        self.consciousness = consciousness
        self.config = config or {}

        # Audio settings
        self.sample_rate = self.config.get("sample_rate", 16000)
        self.device_name = self.config.get("device", "Brio 101")
        self.vad_aggressiveness = self.config.get("vad_aggressiveness", 2)
        self.wake_words = self.config.get("wake_words", ["helix", "hey helix"])
        self.amplitude_threshold = self.config.get("amplitude_threshold", 8000)
        self.min_speech_duration = self.config.get("min_speech_duration", 1.5)

        # State
        self._running = False
        self._thread = None
        self._model = None  # Lazy-loaded whisper model
        self._vad = None
        self._device_index = None

        # Cooldown to prevent spam
        self._last_wake_time = 0
        self._wake_cooldown = 10  # seconds between wake events

    def start(self):
        """Start the monitor in a background thread."""
        if self._running:
            logger.warning("Audio monitor already running")
            return

        # Find audio device
        self._device_index = self._find_device()
        if self._device_index is None:
            logger.error(f"Audio device '{self.device_name}' not found — monitor disabled")
            return

        self._running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True, name="audio-monitor")
        self._thread.start()
        logger.info(f"Passive audio monitor started (device={self.device_name}, VAD={self.vad_aggressiveness})")

    def stop(self):
        """Stop the monitor."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        logger.info("Audio monitor stopped")

    def _find_device(self) -> int | None:
        """Find the audio input device by name substring."""
        try:
            import pyaudio
            pa = pyaudio.PyAudio()
            for i in range(pa.get_device_count()):
                info = pa.get_device_info_by_index(i)
                if (self.device_name.lower() in info["name"].lower()
                        and info["maxInputChannels"] > 0):
                    logger.info(f"Found audio device: [{i}] {info['name']}")
                    pa.terminate()
                    return i
            pa.terminate()
            # Try default device as fallback
            logger.warning(f"Device '{self.device_name}' not found, trying default input")
            return None
        except Exception as e:
            logger.error(f"Failed to enumerate audio devices: {e}")
            return None

    def _load_whisper(self):
        """Lazy-load the Whisper model (only when speech is first detected)."""
        if self._model is not None:
            return
        try:
            from faster_whisper import WhisperModel
            logger.info("Loading Whisper base.en model (first speech detection)...")
            self._model = WhisperModel(
                "base.en",
                device="cpu",
                compute_type="int8",
            )
            logger.info("Whisper model loaded successfully")
        except Exception as e:
            logger.error(f"Failed to load Whisper model: {e}")
            self._model = None

    def _init_vad(self):
        """Initialize Voice Activity Detection."""
        import webrtcvad
        self._vad = webrtcvad.Vad(self.vad_aggressiveness)

    def _monitor_loop(self):
        """Main monitoring loop — runs in background thread."""
        import pyaudio

        self._init_vad()

        pa = pyaudio.PyAudio()
        frame_duration_ms = 30  # 30ms frames for VAD
        frame_size = int(self.sample_rate * frame_duration_ms / 1000)  # 480 samples
        chunk_bytes = frame_size * 2  # 16-bit = 2 bytes per sample

        try:
            stream_kwargs = {
                "format": pyaudio.paInt16,
                "channels": 1,
                "rate": self.sample_rate,
                "input": True,
                "frames_per_buffer": frame_size,
            }
            if self._device_index is not None:
                stream_kwargs["input_device_index"] = self._device_index

            stream = pa.open(**stream_kwargs)
            logger.info("Audio stream opened — listening passively")
        except Exception as e:
            logger.error(f"Failed to open audio stream: {e}")
            pa.terminate()
            return

        # Speech buffering state
        speech_frames = deque()
        speech_start = None
        silence_frames = 0
        max_silence_frames = int(0.8 / (frame_duration_ms / 1000))  # 0.8s of silence ends speech

        try:
            while self._running:
                try:
                    data = stream.read(frame_size, exception_on_overflow=False)
                except Exception:
                    time.sleep(0.1)
                    continue

                # RMS computed for monitoring only (no wake trigger)
                rms = self._compute_rms(data)

                # Voice Activity Detection
                try:
                    is_speech = self._vad.is_speech(data, self.sample_rate)
                except Exception:
                    continue

                if is_speech:
                    # Skip speech processing if consciousness is already awake
                    # (the listen tool handles active audio when awake)
                    if (self.consciousness and 
                            getattr(self.consciousness, '_state', 'DORMANT') == 'AWAKE'):
                        speech_frames.clear()
                        speech_start = None
                        silence_frames = 0
                        continue

                    if speech_start is None:
                        speech_start = time.time()
                    speech_frames.append(data)
                    silence_frames = 0
                else:
                    if speech_start is not None:
                        silence_frames += 1
                        speech_frames.append(data)  # Keep trailing silence

                        # End of speech segment
                        if silence_frames >= max_silence_frames:
                            duration = time.time() - speech_start
                            if duration >= self.min_speech_duration:
                                self._process_speech(speech_frames, duration)
                            # Reset
                            speech_frames.clear()
                            speech_start = None
                            silence_frames = 0

                        # Safety cap: don't buffer more than 10s
                        elif len(speech_frames) > int(10 / (frame_duration_ms / 1000)):
                            self._process_speech(speech_frames, time.time() - speech_start)
                            speech_frames.clear()
                            speech_start = None
                            silence_frames = 0

        except Exception as e:
            logger.error(f"Audio monitor error: {e}")
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()
            logger.info("Audio stream closed")

    def _compute_rms(self, data: bytes) -> float:
        """Compute RMS amplitude of an audio frame."""
        try:
            count = len(data) // 2
            shorts = struct.unpack(f"<{count}h", data)
            sum_squares = sum(s * s for s in shorts)
            return (sum_squares / count) ** 0.5
        except Exception:
            return 0.0


    def _process_speech(self, frames: deque, duration: float):
        """Transcribe speech and check for wake word."""
        now = time.time()
        if now - self._last_wake_time < self._wake_cooldown:
            return  # Cooldown

        # Lazy-load whisper on first speech
        self._load_whisper()
        if self._model is None:
            return

        # Convert frames to numpy array
        try:
            audio_data = b"".join(frames)
            audio_np = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0

            # Transcribe
            segments, info = self._model.transcribe(
                audio_np,
                beam_size=1,
                language="en",
                vad_filter=False,  # We already did VAD
            )

            transcript = " ".join(seg.text for seg in segments).strip().lower()

            if not transcript or len(transcript) < 3:
                return

            logger.debug(f"Heard ({duration:.1f}s): {transcript}")

            # Check for wake word
            for wake_word in self.wake_words:
                if wake_word.lower() in transcript:
                    self._last_wake_time = now
                    logger.info(f"Wake word detected: '{wake_word}' in '{transcript}'")

                    if self.consciousness:
                        self.consciousness.wake(f"audio: heard '{wake_word}'")
                        self.consciousness.emit_raw(
                            f"[AUDIO] Someone said your name! Heard: \"{transcript}\" "
                            f"(duration: {duration:.1f}s)"
                        )
                    return

        except Exception as e:
            logger.error(f"Speech processing failed: {e}")
