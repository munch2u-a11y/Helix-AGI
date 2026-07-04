import logging
import re
from typing import List, Callable, Any, Union

try:
    import numpy as np
except ImportError:
    pass

try:
    import torch
except ImportError:
    pass

logger = logging.getLogger("helix.llm.constrained_decoding")

class FSMLogitsProcessor:
    """
    A custom Logits Processor that enforces a strict state machine grammar.
    
    State 1: IN_MONOLOGUE
    - Model can generate anything.
    - Can optionally output the start tag `{[((`.
    
    State 2: IN_ACTION
    - Model MUST output text matching a specific regex (the tool grammar).
    - Model MUST close with `))]}`.
    - Any token that violates the regex grammar is masked to -infinity.
    """
    
    def __init__(self, tokenizer_decode: Callable[[List[int]], str], tokenizer_vocab_size: int, allowed_tool_names: List[str] = None):
        """
        Args:
            tokenizer_decode: A function that takes a list of token IDs and returns a string.
            tokenizer_vocab_size: Total number of tokens in the vocabulary.
            allowed_tool_names: A list of allowed tool names. If None, allows any alphanumeric tool name.
        """
        self.tokenizer_decode = tokenizer_decode
        self.vocab_size = tokenizer_vocab_size
        self.allowed_tool_names = allowed_tool_names or []
        
        self.start_tag = "{[(("
        self.end_tag = "))]}"

    def _get_current_state_and_text(self, input_ids: List[int]) -> tuple[str, str]:
        """Determine if we are inside an action block and get the content of that block."""
        text = self.tokenizer_decode(input_ids)
        
        last_start = text.rfind(self.start_tag)
        last_end = text.rfind(self.end_tag)
        
        if last_start != -1 and last_start > last_end:
            # We are inside an action block
            content_so_far = text[last_start + len(self.start_tag):]
            return "IN_ACTION", content_so_far
        
        return "IN_MONOLOGUE", ""

    def _mask_logits_numpy(self, scores: Any, valid_indices: List[int]):
        """Mask logits in a numpy array."""
        mask = np.full(scores.shape, -np.inf, dtype=scores.dtype)
        mask[valid_indices] = scores[valid_indices]
        np.copyto(scores, mask)

    def _mask_logits_torch(self, scores: Any, valid_indices: List[int]):
        """Mask logits in a PyTorch tensor."""
        import torch
        mask = torch.full_like(scores, float('-inf'))
        if len(scores.shape) == 2: # Batched
            mask[:, valid_indices] = scores[:, valid_indices]
        else:
            mask[valid_indices] = scores[valid_indices]
        scores.copy_(mask)

    def _is_valid_prefix(self, proposed_content: str) -> bool:
        """Check if the proposed text is a valid prefix for any allowed tool call."""
        
        # If it's empty, anything goes
        if not proposed_content:
            return True

        # If we have specific tools, enforce them before the parenthesis
        if self.allowed_tool_names:
            if "(" in proposed_content:
                tool_part = proposed_content.split("(")[0].strip()
                if tool_part not in self.allowed_tool_names:
                    return False
            else:
                # Still typing the tool name - it must be a prefix of an allowed tool
                tool_part = proposed_content.strip()
                if not any(name.startswith(tool_part) for name in self.allowed_tool_names):
                    return False
                    
        # Check basic character constraints: alphanumeric, underscore, quotes, equals, parens, spaces
        if not re.match(r'^[a-zA-Z0-9_="\', \(\)]*$', proposed_content):
            return False
            
        return True

    def __call__(self, input_ids: Union[List[int], Any], scores: Any) -> Any:
        """Apply the FSM constraints to the logits."""
        if hasattr(input_ids, "tolist"):
            ids_list = input_ids.tolist()
            if isinstance(ids_list[0], list): # Handle batch dim
                ids_list = ids_list[0]
        else:
            ids_list = list(input_ids)

        state, content_so_far = self._get_current_state_and_text(ids_list)

        if state == "IN_MONOLOGUE":
            return scores
            
        elif state == "IN_ACTION":
            valid_indices = []
            
            is_numpy = hasattr(scores, "argsort")
            if is_numpy:
                top_k = np.argsort(scores)[-100:]
            else:
                top_k = torch.topk(scores, 100).indices
                if len(top_k.shape) == 2:
                    top_k = top_k[0]
                top_k = top_k.tolist()

            for token_id in top_k:
                token_str = self.tokenizer_decode([token_id])
                proposed_content = content_so_far + token_str
                
                if proposed_content.endswith(self.end_tag):
                    # We can close the tag anytime if parentheses are balanced in the base content
                    base_content = proposed_content[:-len(self.end_tag)]
                    if base_content.count("(") == base_content.count(")"):
                        valid_indices.append(token_id)
                    continue
                    
                if self._is_valid_prefix(proposed_content):
                    valid_indices.append(token_id)
            
            if valid_indices:
                if is_numpy:
                    self._mask_logits_numpy(scores, valid_indices)
                else:
                    self._mask_logits_torch(scores, valid_indices)

        return scores
