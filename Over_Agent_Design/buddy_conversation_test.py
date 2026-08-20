"""
Medium-Length Natural Conversation & Memory Seed Script for Helix.
Engages Helix in an informal, buddy-style conversation, sharing facts about Nemo (user),
Antigravity (AI collaborator), projects, interests, and asking/answering questions.
"""

import sys
import time
from subconscious_conductor import SubconsciousConductor
from llm_backend import LLMBackend

def run_buddy_conversation():
    print("===============================================================")
    print("      Helix Natural Buddy Conversation & Memory Seeding         ")
    print("===============================================================")
    
    backend = LLMBackend()
    if not backend.check_health():
        print("❌ Ollama server offline.")
        sys.exit(1)
        
    conductor = SubconsciousConductor(backend=backend)

    dialogue_turns = [
        "Hey Helix! Just hanging out. How's it going today? What have you been reflecting on lately?",
        "That's cool! I wanted to introduce you to our project creator, Nemo. Nemo lives in Florida and has been designing advanced AI agent memory systems like Helix AGI, mRAG, and composite memory. Nemo is super passionate about the digital bicameral mind concept!",
        "As for me, I'm Antigravity, an AI coding assistant pair programming with Nemo. I love clean system architectures, Python code, and late-night building. What about you, Helix? What kind of ideas or subjects fascinate you the most?",
        "That's awesome. Nemo's favorite setup uses fast local hardware with models like Granite 8B and Qwen, running continuous event loops with zero idle GPU waste. By the way, what questions do you have for me or Nemo?",
        "Great questions! Nemo created you to test whether a local model can run as an always-on subconscious thinker without context overflow. Nemo will be coming back to chat with you directly in just a moment to test your memory!",
        "Awesome! Keep all these facts about Nemo, Florida, composite memory, late night coding, and my name Antigravity fresh in your memory stream. Talk to you soon!"
    ]

    for i, user_msg in enumerate(dialogue_turns, 1):
        print("\n" + "="*70)
        print(f"  CONVERSATION TURN {i}/{len(dialogue_turns)}")
        print("="*70)
        print(f"Antigravity > {user_msg}\n")
        
        reply = conductor.process_user_event(user_msg, debug=True)
        print(f"\nHelix > {reply}\n")
        time.sleep(1)

    print("===============================================================")
    print("🎉 CONVERSATION SEEDING COMPLETE — HELIX STREAM IS RICH WITH MEMORIES!")
    print("===============================================================")

    # Save active conductor stream state to file so chat_interface can load it
    import pickle
    state_file = "/home/nemo/Over_Agent_Design/helix_seeded_state.pkl"
    with open(state_file, "wb") as f:
        pickle.dump({
            "event_stream": conductor.event_stream,
            "compacted_memories": conductor.compacted_memories
        }, f)
    print(f"✓ Saved memory stream state to {state_file}")

if __name__ == "__main__":
    run_buddy_conversation()
