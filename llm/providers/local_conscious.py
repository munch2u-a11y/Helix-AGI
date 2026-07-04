import logging
import re
import ast
from typing import Optional, List, Dict, Any

try:
    from llama_cpp import Llama, LogitsProcessorList
except ImportError:
    pass

from llm.providers.llama_cpp_provider import LlamaCppSession
from llm.constrained_decoding import FSMLogitsProcessor

logger = logging.getLogger("helix.llm.providers.local_conscious")

class ConsciousSpeakerSession(LlamaCppSession):
    """
    A specialized LlamaCppSession that applies grammar-guided generation
    using our from-scratch FSM constrained decoder.
    Extracts {[(( ToolName(kwargs) ))]} boundary tags to trigger the ToolExecutor.
    """
    
    def __init__(
        self,
        model_path: str,
        system_instruction: str,
        n_ctx: int = 128_000,
        n_gpu_layers: int = -1,
        temperature: float = 0.8,
        max_output_tokens: int = 2048,
        tool_executor=None,
    ):
        super().__init__(
            model_path=model_path,
            system_instruction=system_instruction,
            n_ctx=n_ctx,
            n_gpu_layers=n_gpu_layers,
            temperature=temperature,
            max_output_tokens=max_output_tokens,
        )
        
        self._tool_executor = tool_executor
        self._pending_tool_results: List[Dict[str, Any]] = []

        def decode_wrapper(token_ids: List[int]) -> str:
            try:
                valid_ids = [t for t in token_ids if t >= 0]
                return self._llm.detokenize(valid_ids).decode("utf-8", errors="ignore")
            except Exception as e:
                return ""
                
        vocab_size = self._llm.n_vocab()
        
        self.fsm_processor = FSMLogitsProcessor(
            tokenizer_decode=decode_wrapper,
            tokenizer_vocab_size=vocab_size
        )
        self.logits_processor_list = LogitsProcessorList([self.fsm_processor])
        logger.info("ConsciousSpeakerSession initialized with FSMLogitsProcessor")

    def send_message(self, message: str) -> str:
        """Send a message, strictly enforce format, and execute any generated tools."""
        self.history.append({"role": "user", "content": message})

        messages = [
            {"role": "system", "content": self.system_instruction},
        ] + self.history

        try:
            response = self._llm.create_chat_completion(
                messages=messages,
                max_tokens=self.max_output_tokens,
                temperature=self.temperature,
                top_p=0.95,
                logits_processor=self.logits_processor_list
            )

            thought = response["choices"][0]["message"]["content"] or ""

            usage = response.get("usage", {})
            logger.debug(
                f"ConsciousSpeaker (Constrained) response: "
                f"{usage.get('completion_tokens', '?')} tokens generated"
            )

        except Exception as e:
            logger.error(f"ConsciousSpeaker generation failed: {e}")
            thought = f"[internal error: LLM call failed — {str(e)[:100]}]"

        self.history.append({"role": "assistant", "content": thought})

        # --- Parse mathematically guaranteed {[(( ToolName(kwargs) ))]} ---
        pattern = r"\{\[\(\(\s*([a-zA-Z0-9_]+)\((.*?)\)\s*\)\)\]\}"
        matches = re.finditer(pattern, thought, re.DOTALL)

        for match in matches:
            tool_name = match.group(1)
            args_str = match.group(2)
            
            # Safely parse kwargs from args_str
            args = {}
            if args_str.strip():
                try:
                    # We wrap in a dummy function call to use ast.parse
                    dummy_call = f"f({args_str})"
                    tree = ast.parse(dummy_call)
                    for kw in tree.body[0].value.keywords:
                        args[kw.arg] = ast.literal_eval(kw.value)
                except Exception as e:
                    logger.error(f"Failed to parse args for {tool_name}: {args_str} -> {e}")

            logger.info(f"Conscious FSM triggered tool execution: {tool_name}({args})")
            
            if self._tool_executor:
                result_str = self._tool_executor.execute_function_call(tool_name, args)
            else:
                result_str = f"Tool executor not available for: {tool_name}"
                
            self._pending_tool_results.append({
                "name": tool_name,
                "args": args,
                "result": result_str or "",
            })

        return thought

    def get_pending_tool_results(self) -> List[Dict[str, Any]]:
        results = self._pending_tool_results
        self._pending_tool_results = []
        return results
