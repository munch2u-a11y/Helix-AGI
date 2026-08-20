"""
Interactive CLI Chat Interface for Subconscious Over-Agent System.
Features background thread idle pulses so Helix actively reflects in real-time
even while waiting for user input.
"""

import sys
import argparse
import threading
import time
from subconscious_conductor import SubconsciousConductor
from llm_backend import LLMBackend
from voice_subagents import TTSPlayer, STTListener

def start_background_pulse_thread(conductor: SubconsciousConductor, debug: bool):
    """Background thread that runs idle pulses every 10s while waiting for user input."""
    def _loop():
        while True:
            try:
                conductor.pulse_idle_check(debug=debug)
            except Exception as e:
                if debug:
                    print(f"\n[Background Pulse Note]: {e}")
                time.sleep(10)
    t = threading.Thread(target=_loop, daemon=True)
    t.start()

def main():
    parser = argparse.ArgumentParser(description="Subconscious Over-Agent Chat Interface")
    parser.add_argument("--debug", action="store_true", help="Enable live subconscious stream and subagent debug logs")
    parser.add_argument("--voice", action="store_true", help="Enable TTS spoken audio output and STT microphone listener")
    parser.add_argument("--model", type=str, default="granite4.1:8b", help="Local model to use (default: granite4.1:8b)")
    args = parser.parse_args()

    print("===============================================================")
    print("      Subconscious Over-Agent System — Interactive Chat         ")
    print("===============================================================")
    print(f"Model: {args.model}")
    print(f"Debug Mode: {'ENABLED' if args.debug else 'DISABLED'}")
    print(f"Voice Mode: {'ENABLED 🎙️' if args.voice else 'DISABLED (Pure Text Mode)'}")
    print("Type your message below. Type 'exit' or 'quit' to end.\n")

    backend = LLMBackend(default_model=args.model)
    if not backend.check_health():
        print("[Warning] Could not connect to local Ollama server at http://localhost:11434.")
        print("Please ensure Ollama is running (`ollama serve`).")
        sys.exit(1)

    conductor = SubconsciousConductor(backend=backend)
    tts = TTSPlayer() if args.voice else None
    stt = STTListener() if args.voice else None

    # Start active real-time background pulse thread
    start_background_pulse_thread(conductor, debug=args.debug)

    while True:
        try:
            user_input = None
            if stt and stt.whisper_available:
                user_input = stt.listen()
                
            if not user_input:
                user_input = input("\nHelix > ").strip()
                
            if not user_input:
                continue
            if user_input.lower() in ["exit", "quit"]:
                print("\nEnding chat session. Goodbye!")
                break

            response = conductor.process_user_event(user_input, debug=args.debug)
            print(f"\nHelix Spoken > {response}")

            if tts:
                tts.speak(response)

        except KeyboardInterrupt:
            print("\nSession interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\n[Error]: {e}")

if __name__ == "__main__":
    main()
