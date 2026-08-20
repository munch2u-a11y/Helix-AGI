"""
Modular Voice Subagents (TTS / STT) for Over-Agent System.
Provides optional Speech-to-Text (STT) audio intake and Text-to-Speech (TTS) audio output.
Designed to be toggleable so it can be enabled or disabled cleanly without impacting core functionality.
"""

import os
import subprocess
import shutil
from typing import Optional

class TTSPlayer:
    """
    Text-to-Speech Subagent.
    Converts Speaker Subagent text output into spoken audio using fast local speech synthesizers
    (e.g., piper, spd-say, espeak-ng) with graceful fallbacks.
    """
    def __init__(self, voice_engine: str = "auto"):
        self.engine = self._detect_engine(voice_engine)

    def _detect_engine(self, requested: str) -> str:
        if requested != "auto":
            return requested
        if shutil.which("spd-say"):
            return "spd-say"
        elif shutil.which("espeak-ng"):
            return "espeak-ng"
        elif shutil.which("espeak"):
            return "espeak"
        elif shutil.which("say"):  # macOS fallback
            return "say"
        return "none"

    def speak(self, text: str):
        """Synthesizes and plays spoken audio for the given text."""
        if not text or self.engine == "none":
            return

        # Clean text for speech synthesis command
        clean_text = text.replace('"', '\\"').replace("'", "\\'")
        
        try:
            if self.engine == "spd-say":
                subprocess.run(["spd-say", "-r", "10", clean_text], check=False)
            elif self.engine in ["espeak-ng", "espeak"]:
                subprocess.run([self.engine, "-s", "160", clean_text], check=False)
            elif self.engine == "say":
                subprocess.run(["say", clean_text], check=False)
        except Exception as e:
            print(f"[TTS Warning] Speech output failed: {e}")


class STTListener:
    """
    Speech-to-Text Subagent.
    Listens for user speech via microphone and transcribes to text.
    Provides graceful fallback to text input if audio input hardware/libraries are absent.
    """
    def __init__(self):
        self.whisper_available = self._check_whisper()

    def _check_whisper(self) -> bool:
        try:
            import speech_recognition as sr
            return True
        except ImportError:
            return False

    def listen(self, prompt_text: str = "Listening (speak into microphone)... ") -> Optional[str]:
        """
        Listens for audio input and returns transcribed text.
        Falls back to standard keyboard input if speech recognition library is not installed.
        """
        if not self.whisper_available:
            return None

        try:
            import speech_recognition as sr
            r = sr.Recognizer()
            with sr.Microphone() as source:
                print(f"\n🎙️ {prompt_text}")
                r.adjust_for_ambient_noise(source, duration=0.5)
                audio = r.listen(source, timeout=5, phrase_time_limit=15)
                print("⏳ Transcribing audio...")
                transcription = r.recognize_google(audio)
                print(f"[STT Transcribed]: {transcription}")
                return transcription
        except Exception as e:
            print(f"[STT Info] Speech transcription skipped ({e}). Falling back to text.")
            return None
