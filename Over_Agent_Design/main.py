"""
Helix Subconscious Over-Agent — Main Terminal Application.

Provides a rich terminal UI, interactive bicameral mind chat session,
health diagnostics, logging, model selection, debug options,
and real-time background pulse threading while waiting for user input.
"""

import os
import sys
import argparse
import time
import threading
from llm_backend import LLMBackend
from subconscious_conductor import SubconsciousConductor
from voice_subagents import TTSPlayer, STTListener

BANNER = r"""
  ██╗  ██╗███████╗██╗     ██╗██╗  ██╗     █████╗  ██████╗ ██╗
  ██║  ██║██╔════╝██║     ██║╚██╗██╔╝    ██╔══██╗██╔════╝ ██║
  ███████║█████╗  ██║     ██║ ╚███╔╝     ███████║██║  ███╗██║
  ██╔══██║██╔══╝  ██║     ██║ ██╔██╗     ██╔══██║██║   ██║██║
  ██║  ██║███████╗███████╗██║██╔╝ ██╗    ██║  ██║╚██████╔╝██║
  ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝ ╚═════╝ ╚═╝
           Subconscious Bicameral Over-Agent Terminal
"""

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

def print_status_dashboard(model: str, debug: bool, voice: bool, backend_ok: bool):
    print("=" * 70)
    print(BANNER)
    print("=" * 70)
    print(f"  🤖 Model Backend : {model} ({'ONLINE ✓' if backend_ok else 'OFFLINE ❌'})")
    print(f"  🧠 Architecture  : Digital Bicameral Mind (Slim Main Orchestrator)")
    print(f"  ⚡ Mode          : Real-Time Background Pulses (Reflecting While Waiting)")
    print(f"  🔍 Sub-Passes    : Speaker / Research / Execution Sub-Orchestrators")
    print(f"  🎙️ Voice Mode    : {'ENABLED 🎙️' if voice else 'DISABLED (Pure Text)'}")
    print(f"  🛠️ Debug Output  : {'ENABLED' if debug else 'DISABLED'}")
    print("=" * 70)
    print("  Type your prompt to converse. Options: 'exit', 'quit', '--help'")
    print("=" * 70 + "\n")


def run_terminal_app():
    parser = argparse.ArgumentParser(description="Helix Subconscious Over-Agent Terminal Application")
    parser.add_argument("--model", type=str, default="granite4.1:8b", help="Local LLM model to use (default: granite4.1:8b)")
    parser.add_argument("--debug", action="store_true", help="Enable live subconscious monologue and sub-orchestrator logs")
    parser.add_argument("--voice", action="store_true", help="Enable TTS audio playback and STT microphone input")
    args = parser.parse_args()

    backend = LLMBackend(default_model=args.model)
    backend_ok = backend.check_health()

    print_status_dashboard(
        model=args.model,
        debug=args.debug,
        voice=args.voice,
        backend_ok=backend_ok
    )

    if not backend_ok:
        print("  ⚠ ERROR: Local Ollama backend is not accessible on http://localhost:11434.")
        print("  Please start Ollama service using: `ollama serve`\n")
        sys.exit(1)

    conductor = SubconsciousConductor(backend=backend)
    tts = TTSPlayer() if args.voice else None
    stt = STTListener() if args.voice else None

    # Start active real-time background pulse thread while user is typing/idle
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
                print("\n  Closing Helix Terminal Session. Goodbye!")
                break

            response = conductor.process_user_event(user_input, debug=args.debug)
            print(f"\nHelix Spoken > {response}")

            if tts:
                tts.speak(response)

        except KeyboardInterrupt:
            print("\n\n  Session interrupted by user. Closing Helix Terminal Application.")
            break
        except Exception as e:
            print(f"\n  ❌ Exception occurred: {e}")

if __name__ == "__main__":
    run_terminal_app()
