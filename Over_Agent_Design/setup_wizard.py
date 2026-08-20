#!/usr/bin/env python3
"""
Helix Subconscious Over-Agent — Interactive Setup Wizard & System Installer.

Guides users through environment diagnostics, Ollama LLM model verification,
mRAG memory engine detection, voice audio sub-systems, identity initialization,
and launcher options.
"""

import os
import sys
import json
import subprocess
import urllib.request
import urllib.error

BANNER = r"""
======================================================================
  ██╗  ██╗███████╗██╗     ██╗██╗  ██╗     █████╗  ██████╗ ██╗
  ██║  ██║██╔════╝██║     ██║╚██╗██╔╝    ██╔══██╗██╔════╝ ██║
  ███████║█████╗  ██║     ██║ ╚███╔╝     ███████║██║  ███╗██║
  ██╔══██║██╔══╝  ██║     ██║ ██╔██╗     ██╔══██║██║   ██║██║
  ██║  ██║███████╗███████╗██║██╔╝ ██╗    ██║  ██║╚██████╔╝██║
  ╚═╝  ╚═╝╚══════╝╚══════╝╚═╝╚═╝  ╚═╝    ╚═╝  ╚═╝ ╚═════╝ ╚═╝
             Interactive Setup & Diagnostics Wizard
======================================================================
"""

def print_step(title: str):
    print(f"\n🔹 {title}")
    print("-" * 65)

def check_python_environment():
    print_step("Step 1: Checking Python Environment")
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"  ✓ Python Version: {py_ver}")
    if sys.version_info < (3, 8):
        print("  ❌ ERROR: Python 3.8+ is required.")
        return False
    return True

def check_ollama_backend():
    print_step("Step 2: Checking Local Ollama LLM Backend")
    base_url = "http://localhost:11434"
    try:
        req = urllib.request.Request(f"{base_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                models_data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("name") for m in models_data.get("models", [])]
                print(f"  ✓ Ollama Service: ONLINE at {base_url}")
                print(f"  ✓ Available Local Models: {', '.join(models) if models else 'None detected'}")
                
                target_model = "granite4.1:8b"
                if any(target_model in m for m in models):
                    print(f"  ✓ Default Model '{target_model}': INSTALLED")
                else:
                    print(f"  ⚠️ Warning: Model '{target_model}' not found in Ollama tags.")
                    print(f"  💡 Run: `ollama pull {target_model}` to install default model.")
                return True
    except Exception as e:
        print(f"  ❌ Ollama Service OFFLINE ({e})")
        print("  💡 Please start Ollama using: `ollama serve`")
        return False

def check_mrag_engine():
    print_step("Step 3: Checking mRAG & Memory Retrieval Engine")
    try:
        import chromadb
        print("  ✓ ChromaDB Vector Store: INSTALLED")
    except ImportError:
        print("  ℹ️ ChromaDB Vector Store: Not installed (optional)")

    local_mrag = "/home/nemo/Local-mRag"
    if os.path.exists(local_mrag):
        print(f"  ✓ Local mRAG Stack Found: {local_mrag}")
        print("  ✓ Operating Mode: FULL MULTI-HEAD mRAG VECTOR RECALL")
    else:
        print("  ℹ️ Local mRAG Stack: Not detected")
        print("  ✓ Operating Mode: PLUG-AND-PLAY KEYWORD & JSON BELIEF RECALL (Fallback Mode)")
    return True

def check_audio_systems():
    print_step("Step 4: Checking Voice & Audio Subsystems (Optional)")
    # TTS
    tts_found = False
    for tts_cmd in ["spd-say", "espeak-ng", "say"]:
        if subprocess.run(f"which {tts_cmd}", shell=True, capture_output=True).returncode == 0:
            print(f"  ✓ Text-To-Speech (TTS) Command: {tts_cmd}")
            tts_found = True
            break
    if not tts_found:
        print("  ℹ️ Text-To-Speech (TTS): No engine found (Pure Text Mode default)")

    # STT
    try:
        import speech_recognition
        import whisper
        print("  ✓ Speech-To-Text (STT): OpenAI Whisper & SpeechRecognition installed")
    except ImportError:
        print("  ℹ️ Speech-To-Text (STT): SpeechRecognition/Whisper not installed (Pure Text Mode default)")

def check_identity_files():
    print_step("Step 5: Initializing Identity & Persona Files")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    
    identity_file = os.path.join(base_dir, "identity.md")
    if os.path.exists(identity_file):
        print("  ✓ Baseline Identity Source (identity.md): FOUND")
    else:
        print("  ⚠️ Warning: identity.md missing. Creating baseline identity...")
        with open(identity_file, "w", encoding="utf-8") as f:
            f.write("# Shared Identity Source — The Digital Bicameral Mind\nI am Helix, a continuous digital mind operating through focused cognitive windows.\n")
        print("  ✓ Created identity.md")

    opinion_file = os.path.join(base_dir, "self_opinion.json")
    if not os.path.exists(opinion_file):
        with open(opinion_file, "w", encoding="utf-8") as f:
            json.dump({"self_opinion": "I am continually evolving my understanding of memory architectures."}, f, indent=2)
        print("  ✓ Initialized self_opinion.json")
    else:
        print("  ✓ Dynamic Self-Opinion Statement (self_opinion.json): FOUND")

    affect_file = os.path.join(base_dir, "synthetic_affect_state.json")
    if not os.path.exists(affect_file):
        with open(affect_file, "w", encoding="utf-8") as f:
            json.dump({"valence": 0.5, "arousal": 0.4, "focus_depth": 0.8, "label": "Deeply Focused & Analytical"}, f, indent=2)
        print("  ✓ Initialized synthetic_affect_state.json")
    else:
        print("  ✓ Synthetic Affect State Vectors (synthetic_affect_state.json): FOUND")

def run_setup_wizard():
    print(BANNER)
    p_ok = check_python_environment()
    o_ok = check_ollama_backend()
    check_mrag_engine()
    check_audio_systems()
    check_identity_files()

    print("\n=====================================================================")
    print(" 🎉 SETUP & DIAGNOSTIC WIZARD COMPLETE")
    print("=====================================================================")
    if p_ok and o_ok:
        print("  System Status: ALL CORE SUBSYSTEMS READY FOR LAUNCH!")
        choice = input("\n  Would you like to launch the Helix Agent now? [Y/n]: ").strip().lower()
        if choice in ["", "y", "yes"]:
            print("\n  Launching Helix Terminal Application...\n")
            main_script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
            os.execv(sys.executable, [sys.executable, main_script, "--debug"])
    else:
        print("  ⚠ System Notice: Please review the warnings above before launching.")

if __name__ == "__main__":
    run_setup_wizard()
