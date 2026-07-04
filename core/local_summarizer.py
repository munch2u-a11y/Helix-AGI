import torch
from transformers import AutoModelForCausalLM, AutoTokenizer
import logging

logger = logging.getLogger("helix.preconscious.summarizer")

class LocalSummarizer:
    def __init__(self, model_id="Qwen/Qwen2.5-0.5B-Instruct"):
        self.model_id = model_id
        self.model = None
        self.tokenizer = None

    def _load(self):
        if not self.model:
            logger.info(f"Loading native summarizer model: {self.model_id} on CPU...")
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_id)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_id
            )
            logger.info("Native summarizer model loaded.")

    def summarize(self, items: list[str], context_type: str = "beliefs") -> str:
        """Summarize retrieved items into a 1st-person statement using local HF model.
        
        Args:
            items: list of raw content strings to summarize.
            context_type: "beliefs" or "memories".
            
        Returns:
            The raw text statement (outer parentheses stripped if generated).
        """
        if not items:
            return ""
            
        try:
            self._load()
            
            prompt = (
                "<|im_start|>system\n"
                "Summarize the following beliefs and experiences into a single brief, 1st person statement or expression.<|im_end|>\n"
                "<|im_start|>user\n"
                f"{context_type.capitalize()}:\n"
            )
            for item in items:
                prompt += f"- {item}\n"
            prompt += "<|im_end|>\n<|im_start|>assistant\n*("
            
            inputs = self.tokenizer(prompt, return_tensors="pt")
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=60,
                temperature=0.3,
                do_sample=True,
                pad_token_id=self.tokenizer.eos_token_id
            )
            
            result = self.tokenizer.decode(outputs[0][inputs.input_ids.shape[1]:], skip_special_tokens=True)
            
            # Clean up potential artifacts and make it fit nicely in parenthetical wrapping
            cleaned = result.strip()
            
            # Strip outer parenthetical wraps if the model completed the *( with a closing ) or )*
            if cleaned.endswith(")*"):
                cleaned = cleaned[:-2]
            elif cleaned.endswith(")"):
                cleaned = cleaned[:-1]
                
            if cleaned.startswith("*("):
                cleaned = cleaned[2:]
            elif cleaned.startswith("("):
                cleaned = cleaned[1:]
                
            return cleaned.strip()
            
        except Exception as e:
            logger.error(f"Native summarizer failed: {e}")
            raise e
