"""
Helix — Anthropic Provider (Claude Fable 5 — Unified Pulse Architecture)

Uses the anthropic Python SDK with manual history management via
client.messages.create(). Each send_message() call is exactly
ONE API request — no inner function-calling loop.

When the model returns tool_use blocks:
  1. Tools are executed synchronously
  2. Results are queued as pending events for the next pulse
  3. Tool calls are preserved natively in the history
  4. The pulse loop processes results with full preconscious injection

This mirrors the GeminiSession architecture exactly, swapping only
the SDK-specific serialization:
  - Gemini FunctionCall/FunctionResponse → Anthropic tool_use/tool_result
  - Gemini system_instruction config → Anthropic system= parameter
  - Gemini parts[] → Anthropic content[] blocks

Prompt caching (cache_control: ephemeral) is applied to the system
instruction and tool definitions to minimize cost across pulses.

Rate limit fallback: claude-fable-5 → claude-opus-4-8
"""

import json
import os
import logging
from typing import Optional, List, Dict, Any

from llm.providers.base import ChatSession

logger = logging.getLogger("helix.llm.providers.anthropic")


def _convert_tool_declarations(gemini_declarations: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert Gemini FunctionDeclaration dicts to Anthropic tool format.

    Gemini format:
        {"name": "...", "description": "...", "parameters": {JSON Schema}}

    Anthropic format:
        {"name": "...", "description": "...", "input_schema": {JSON Schema}}

    Both use standard JSON Schema for the parameter object, so the
    conversion is just a key rename.
    """
    anthropic_tools = []
    for decl in gemini_declarations:
        tool = {
            "name": decl["name"],
            "description": decl.get("description", ""),
            "input_schema": decl.get("parameters", {"type": "object", "properties": {}}),
        }
        anthropic_tools.append(tool)
    return anthropic_tools


class AnthropicSession(ChatSession):
    """Anthropic Claude session with manual history — one API call per pulse.

    Uses client.messages.create() with explicit history management.
    We manage the conversation history as plain dicts, giving full control
    over what the model sees between pulses.

    Prompt caching is applied via cache_control on the system instruction
    and tool definitions to exploit Anthropic's prefix caching (90% cheaper
    on cache hits, 5-minute TTL — well within pulse intervals).
    """

    def __init__(
        self,
        model: str = "claude-fable-5",
        system_instruction: str = "",
        temperature: float = 0.8,
        max_output_tokens: int = 16384,
        api_key: Optional[str] = None,
        tool_declarations: Optional[List[Dict[str, Any]]] = None,
        tool_executor=None,
        preconscious=None,
    ):
        import anthropic

        self._model = model
        self._tool_executor = tool_executor
        self._preconscious = preconscious
        self._tools_used = []
        self._last_token_count = 0
        self._pending_tool_results = []

        # Store config components for rebuild on toolset changes
        self._system_instruction = system_instruction
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens

        # Convert Gemini-format tool declarations to Anthropic format
        self._tool_declarations_gemini = tool_declarations or []
        self._tool_declarations = _convert_tool_declarations(
            self._tool_declarations_gemini
        )

        # Pending tool_result blocks to prepend to next user message
        self._pending_tool_result_blocks = []

        # Resolve API key
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError(
                "No Anthropic API key found. Set ANTHROPIC_API_KEY environment "
                "variable or pass api_key parameter."
            )

        # Create client
        self._client = anthropic.Anthropic(api_key=key)

        # Manual history — list of plain dicts with role + content blocks
        self._history = []

        logger.info(
            f"Anthropic session created: model={model}, "
            f"system_instruction={len(system_instruction)} chars, "
            f"tools={len(self._tool_declarations)}, "
            f"preconscious={'yes' if preconscious else 'no'}"
        )

    # ── System Instruction with Prompt Caching ────────────────────────

    def _build_system_blocks(self) -> list:
        """Build the system parameter with cache_control for prompt caching.

        Anthropic's cache hierarchy: tools → system → messages.
        Applying cache_control to the system instruction caches
        everything above it (tools + system) as a stable prefix.
        """
        if not self._system_instruction:
            return []

        return [
            {
                "type": "text",
                "text": self._system_instruction,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    # ── Core: One API Call Per Pulse ──────────────────────────────────

    def send_message(self, message: str) -> str:
        """Send one message to Claude. Exactly ONE API call.

        If the model returns tool_use blocks, tools are executed synchronously.
        The tool results are queued as tool_result content blocks and injected
        into the next pulse's user message.

        Returns:
            The model's text output (thought / internal monologue).
        """
        self._tools_used = []

        # Build the content blocks for the new user message
        user_content = []

        # Prepend any pending tool_result blocks from the previous pulse
        if self._pending_tool_result_blocks:
            user_content.extend(self._pending_tool_result_blocks)
            self._pending_tool_result_blocks = []

        # Add the actual user text
        user_content.append({"type": "text", "text": message})

        # Build the full messages array (history + new message)
        messages = list(self._history) + [
            {"role": "user", "content": user_content}
        ]

        # Build API call kwargs
        api_kwargs = {
            "model": self._model,
            "max_tokens": self._max_output_tokens,
            "messages": messages,
        }

        # Temperature is deprecated for extended-thinking models (Fable 5, Mythos 5).
        # Only include it for older models like Opus that still support it.
        _thinking_models = ("fable", "mythos")
        if not any(t in self._model.lower() for t in _thinking_models):
            api_kwargs["temperature"] = self._temperature

        # System instruction with caching
        system_blocks = self._build_system_blocks()
        if system_blocks:
            api_kwargs["system"] = system_blocks

        # Tool definitions
        if self._tool_declarations:
            api_kwargs["tools"] = self._tool_declarations

        try:
            response = self._client.messages.create(**api_kwargs)
        except Exception as e:
            logger.error(f"Anthropic API call failed: {e}")
            return f"[internal error: Anthropic API call failed — {str(e)[:200]}]"

        # Success — update token count and append user message to history
        self._update_token_count(response)
        self._history.append({"role": "user", "content": user_content})

        # Parse response content blocks
        thought_text = self._extract_text(response)
        thinking_text = self._extract_thinking(response)
        tool_use_blocks = self._extract_tool_use(response)

        # Combine thinking + text for the pulse loop (both are internal monologue)
        combined_thought = ""
        if thinking_text:
            combined_thought = thinking_text
        if thought_text:
            if combined_thought:
                combined_thought += "\n" + thought_text
            else:
                combined_thought = thought_text

        if tool_use_blocks:
            # Build model response content for history
            # IMPORTANT: thinking blocks MUST be preserved in history for
            # Anthropic's API (they validate thinking block continuity)
            model_content = []

            # Preserve raw thinking blocks from the response
            for block in response.content:
                if block.type == "thinking":
                    thinking_dict = {
                        "type": "thinking",
                        "thinking": block.thinking,
                    }
                    # Signature is REQUIRED by Anthropic for history continuity
                    if hasattr(block, "signature") and block.signature:
                        thinking_dict["signature"] = block.signature
                    model_content.append(thinking_dict)

            if thought_text:
                model_content.append({"type": "text", "text": thought_text})

            for tool_block in tool_use_blocks:
                tool_id = tool_block.id
                name = tool_block.name
                args = dict(tool_block.input) if tool_block.input else {}

                logger.info(f"FC: {name}({args}) id={tool_id}")
                self._tools_used.append({"name": name, "args": args})

                # Execute the tool synchronously
                if self._tool_executor:
                    result_str = self._tool_executor.execute_function_call(name, args)
                else:
                    result_str = f"Tool executor not available for: {name}"

                logger.info(
                    f"FC result ({name}): "
                    f"{result_str[:500] if result_str else '(empty)'}"
                )

                # Queue tool_result for the next user message
                self._pending_tool_result_blocks.append({
                    "type": "tool_result",
                    "tool_use_id": tool_id,
                    "content": result_str or "",
                })

                # Also queue for the pulse loop events (preconscious grounding)
                self._pending_tool_results.append({
                    "name": name,
                    "args": args,
                    "result": result_str or "",
                })

                # Store the tool_use block in the model content for history
                model_content.append({
                    "type": "tool_use",
                    "id": tool_id,
                    "name": name,
                    "input": args,
                })

            self._history.append({"role": "assistant", "content": model_content})
            return combined_thought or "[tools called, results pending]"

        else:
            # Pure text response (may include thinking blocks)
            if combined_thought:
                model_content = []
                # Preserve thinking blocks
                for block in response.content:
                    if block.type == "thinking":
                        thinking_dict = {
                            "type": "thinking",
                            "thinking": block.thinking,
                        }
                        if hasattr(block, "signature") and block.signature:
                            thinking_dict["signature"] = block.signature
                        model_content.append(thinking_dict)
                if thought_text:
                    model_content.append({"type": "text", "text": thought_text})
                self._history.append({
                    "role": "assistant",
                    "content": model_content,
                })
            return combined_thought

    # ── Tool Result Queue ────────────────────────────────────────────

    def get_pending_tool_results(self) -> List[Dict[str, Any]]:
        """Pop pending tool results for the pulse loop to emit as events.

        Called by pulse_loop after each pulse. Results are formatted as
        events and processed on the next pulse with full preconscious
        injection.
        """
        results = self._pending_tool_results
        self._pending_tool_results = []
        return results

    def clear_pending_tool_results(self) -> None:
        """Clear any pending/queued tool responses/results in the session."""
        self._pending_tool_result_blocks = []
        self._pending_tool_results = []
        logger.info("Cleared pending Anthropic tool responses and results.")


    # ── Model Switching ──────────────────────────────────────────────

    def switch_model(self, new_model: str):
        """Switch to a different model. History is preserved as-is.

        No session recreation needed — we manage history ourselves.
        Just update the model name for the next messages.create() call.
        """
        old_model = self._model
        self._model = new_model
        logger.info(
            f"Model switched: {old_model} → {new_model} "
            f"(history preserved: {len(self._history)} messages)"
        )

    # ── History Management ───────────────────────────────────────────

    def get_history(self) -> List[Dict[str, Any]]:
        """Return the conversation history as plain dicts.

        History is already stored as plain dicts — no conversion needed.
        This is what the ContextCompressor operates on.
        """
        return list(self._history)

    def get_history_size(self) -> int:
        """Return approximate character count of history."""
        total = 0
        for msg in self._history:
            for block in msg.get("content", []):
                if isinstance(block, dict):
                    if block.get("type") == "text":
                        total += len(block.get("text", ""))
                    elif block.get("type") == "thinking":
                        total += len(block.get("thinking", ""))
                    elif block.get("type") == "tool_use":
                        total += len(json.dumps(block.get("input", {})))
                    elif block.get("type") == "tool_result":
                        content = block.get("content", "")
                        total += len(content) if isinstance(content, str) else len(json.dumps(content))
                elif isinstance(block, str):
                    total += len(block)
        return total

    def replace_history(self, compressed_history: List[Dict[str, Any]]):
        """Replace the conversation history with compressed version.

        No session recreation needed — just swap the list. The next
        messages.create() call will use the new history.

        Args:
            compressed_history: List of plain dict messages from
                                the ContextCompressor.
        """
        self._history = list(compressed_history)
        logger.info(
            "History replaced: %d messages", len(self._history)
        )

    def update_tool_declarations(
        self, new_declarations: List[Dict[str, Any]]
    ):
        """Update tool declarations without affecting history.

        Accepts Gemini-format declarations (with 'parameters' key) and
        converts to Anthropic format (with 'input_schema' key) internally.
        """
        self._tool_declarations_gemini = new_declarations
        self._tool_declarations = _convert_tool_declarations(new_declarations)
        logger.info(
            "Tool declarations updated: %d tools, "
            "history preserved (%d messages)",
            len(new_declarations), len(self._history),
        )

    def update_generation_params(
        self, temperature: float = None, max_output_tokens: int = None
    ):
        """Update generation parameters mid-session.

        Called by the pulse loop before each send_message() to apply
        the Sentinel's spatially-modulated temperature and token budget.
        """
        if temperature is not None and abs(temperature - self._temperature) > 0.005:
            self._temperature = temperature
        if max_output_tokens is not None and max_output_tokens != self._max_output_tokens:
            self._max_output_tokens = max_output_tokens

    # ── Token Counting ───────────────────────────────────────────────

    def _update_token_count(self, response) -> None:
        """Extract prompt token count from Anthropic usage metadata."""
        try:
            usage = getattr(response, "usage", None)
            if usage:
                self._last_token_count = getattr(
                    usage, "input_tokens", 0
                )
        except Exception:
            pass

    def get_last_token_count(self) -> int:
        """Get the prompt token count from the last interaction."""
        return self._last_token_count

    def get_last_tool_calls(self) -> List[Dict[str, Any]]:
        """Return the list of tools called during the last send_message()."""
        return self._tools_used

    # ── Response Parsing ─────────────────────────────────────────────

    def _extract_tool_use(self, response) -> list:
        """Extract tool_use content blocks from an Anthropic response."""
        tool_blocks = []
        try:
            for block in response.content:
                if block.type == "tool_use":
                    tool_blocks.append(block)
        except (AttributeError, TypeError):
            pass
        return tool_blocks

    def _extract_thinking(self, response) -> str:
        """Extract thinking content from an Anthropic response.

        Fable 5 uses extended thinking by default. The thinking block
        IS Helix's internal monologue — the raw cognitive process before
        the model formulates its external output.
        """
        try:
            parts = []
            for block in response.content:
                if block.type == "thinking" and block.thinking:
                    parts.append(block.thinking)
            return "\n".join(parts) if parts else ""
        except (AttributeError, TypeError):
            return ""

    def _extract_text(self, response) -> str:
        """Extract text content from an Anthropic response."""
        try:
            parts = []
            for block in response.content:
                if block.type == "text" and block.text:
                    parts.append(block.text)
            return "\n".join(parts) if parts else ""
        except (AttributeError, TypeError):
            return ""

