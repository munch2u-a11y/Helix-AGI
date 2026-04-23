import logging
import json
import re
from typing import Optional
from brain.architecture_preamble import RESONANCE_TAGGER_PREAMBLE

logger = logging.getLogger("helix.brain.resonance")

class ResonanceTagger:
    """The preconscious Familiarity Click generator.
    
    Responsible for adding deep memory resonance markers (⟪ ⟫) to incoming
    sensory strings (like chat messages) without altering the raw data.
    """

    def __init__(self, memory, gemini_client):
        self.memory = memory
        self.gemini = gemini_client

    def apply_familiarity_click(self, text: str) -> str:
        """Strip existing tags, check resonance, and apply ⟪ ⟫ highlighting."""
        # 1. Sanitize input to prevent human spoofing
        clean_text = text.replace("⟪", "").replace("⟫", "")
        
        # 2. Skip trivial or too short texts
        if len(clean_text.split()) < 3:
            return clean_text

        try:
            # 3. Strict recall: high importance, very strict resonance
            # We want memories with high relevance. memory.recall gives results.
            results = self.memory.recall(search=clean_text, limit=3, min_importance=0.6)
            
            # In Helix, `relevance` = 1.0 - ChromaDB distance.
            # We want distance < 0.35, meaning relevance >= 0.65
            highly_resonant = [m for m in results if m.get("relevance", 0.0) >= 0.65]
            
            if not highly_resonant:
                return clean_text
                
            # Take the top 1-2 memories for context
            context_memories = "\n".join(
                [f"- {m.get('content', '')[:250]}" for m in highly_resonant[:2]]
            )
            
            # 4. Flash Subagent: The strict extraction
            # We extract substrings instead of having the LLM rewrite the text.
            # This guarantees 100% data integrity of the original message.
            prompt = (
                f"{RESONANCE_TAGGER_PREAMBLE}\n"
                "Your job is to identify 1-2 highly specific concepts or nouns in the the MESSAGE "
                "that strongly relate to the provided MEMORIES.\n\n"
                "CRITICAL RULES:\n"
                "1. Return ONLY a valid JSON dictionary containing a 'tags' array: {'tags': ['concept_1']}\n"
                "2. The strings in the array must be EXACT substrings present in the MESSAGE.\n"
                "3. DO NOT tag common, everyday vocabulary.\n"
                "4. Only return 1-2 highly resonant concepts at most. Return an empty array [] if nothing fits perfectly.\n\n"
                f"MEMORIES:\n{context_memories}\n\n"
                f"MESSAGE:\n{clean_text}\n"
            )
            
            raw_output = self.gemini.ask(prompt=prompt, model="conscious", temperature=0.0)
            
            # Parse JSON safely
            match = re.search(r"\{.*\}", raw_output, re.DOTALL)
            if not match:
                return clean_text
                
            data = json.loads(match.group(0))
            tags = data.get("tags", [])
            
            # 5. Apply tags (Safe replace)
            tagged_text = clean_text
            for tag in tags:
                # Ensure tag is substantial (skip empty str or single letters if hallucinated)
                if isinstance(tag, str) and len(tag) > 3 and tag in tagged_text:
                    # Replace only the first occurrence to avoid messing up natural language
                    tagged_text = tagged_text.replace(tag, f"⟪{tag}⟫", 1)
                    
            if "⟪" in tagged_text:
                logger.info(f"Familiarity Click triggered for tags: {tags}")
                
            return tagged_text
            
        except Exception as e:
            logger.debug(f"Resonance tagging failed (safe fallback): {e}")
            return clean_text
