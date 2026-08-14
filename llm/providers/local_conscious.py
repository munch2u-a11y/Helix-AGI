import logging
from typing import Optional, List, Dict, Any

try:
    from llama_cpp import Llama, LogitsProcessorList
except ImportError:
    pass

from llm.providers.llama_cpp_provider import LlamaCppSession
from llm.constrained_decoding import FSMLogitsProcessor, parse_action_tags

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
        # A directed tool pass borrows this session and drives the tool loop
        # itself, one call at a time. Auto-execution here would run every
        # call twice and leak the pass's results into the main window.
        self.auto_execute_tools = True

        def decode_wrapper(token_ids: List[int]) -> str:
            try:
                valid_ids = [t for t in token_ids if t >= 0]
                return self._llm.detokenize(valid_ids).decode("utf-8", errors="ignore")
            except Exception as e:
                return ""

        vocab_size = self._llm.n_vocab()

        self.fsm_processor = FSMLogitsProcessor(
            tokenizer_decode=decode_wrapper,
            tokenizer_vocab_size=vocab_size,
            allowed_tool_names=self._registry_tool_names(),
        )
        self.logits_processor_list = LogitsProcessorList([self.fsm_processor])
        logger.info(
            "ConsciousSpeakerSession initialized with FSMLogitsProcessor "
            "(%d tools in grammar)",
            len(self.fsm_processor.allowed_tool_names),
        )

    # ── Grammar scope ────────────────────────────────────────────────

    def _registry_tool_names(self, toolset: Optional[str] = None) -> List[str]:
        """Tool names the grammar should accept, from the live registry.

        Without this the FSM falls back to "any syntactically valid name" and
        the model can emit a perfectly well-formed call to a tool that does
        not exist — which parses cleanly and dispatches to nothing.
        """
        registry = getattr(self._tool_executor, "_registry", None)
        if registry is None:
            return []
        try:
            return registry.get_tool_names(toolset)
        except Exception as e:
            logger.warning("Could not read tool names from registry: %s", e)
            return []

    def set_allowed_tools(self, names: Optional[List[str]]) -> None:
        """Narrow the grammar to an explicit tool set for a directed pass."""
        self.fsm_processor.set_allowed_tools(names)

    def scope_to_toolset(self, toolset: Optional[str]) -> None:
        """Narrow the grammar to one toolset (None restores the full set)."""
        self.fsm_processor.set_allowed_tools(self._registry_tool_names(toolset))

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

        # --- Parse grammar-guaranteed {[(( ToolName(kwargs) ))]} ---
        if not self.auto_execute_tools:
            return thought

        for tool_name, args in parse_action_tags(thought):
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
