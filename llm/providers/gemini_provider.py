"""
Helix — Gemini Provider (Unified Pulse Architecture)

Uses the google.genai SDK with manual history management via
client.models.generate_content(). Each send_message() call is exactly
ONE API request — no inner function-calling loop.

When the model returns function calls:
  1. Tools are executed synchronously
  2. Results are queued as pending events for the next pulse
  3. Function calls are converted to text in the history
  4. The pulse loop processes results with full preconscious injection

This ensures every tool interaction gets cognitive grounding through
the preconscious system (beliefs, memories, spatial context).

Subconscious agents (dream engine, etc.) continue to use local Ollama.
"""

import json
import os
import logging
from typing import Optional, List, Dict, Any

from llm.providers.base import ChatSession

logger = logging.getLogger("helix.llm.providers.gemini")


class GeminiSession(ChatSession):
    """Gemini session with manual history — one API call per pulse.

    Uses client.models.generate_content() instead of SDK chat sessions.
    We manage the conversation history as plain dicts, giving full control
    over what the model sees between pulses.
    """

    def __init__(
        self,
        model: str = "gemini-3-flash-preview",
        system_instruction: str = "",
        temperature: float = 0.8,
        max_output_tokens: int = 8192,
        api_key: Optional[str] = None,
        tool_declarations: Optional[List[Dict[str, Any]]] = None,
        tool_executor=None,
        preconscious=None,
    ):
        from google import genai
        from google.genai import types

        self._model = model
        self._tool_executor = tool_executor
        self._preconscious = preconscious
        self._genai = genai
        self._types = types
        self._tools_used = []
        self._last_token_count = 0
        self._pending_tool_results = []
        self._native_tool_responses = []

        # Store config components for rebuild on toolset changes
        self._system_instruction = system_instruction
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._tool_declarations = tool_declarations

        # Resolve API key
        key = api_key or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ValueError(
                "No Gemini API key found. Set GEMINI_API_KEY environment "
                "variable or pass api_key parameter."
            )

        # Create client
        self._client = genai.Client(api_key=key)

        # Build reusable config
        self._config = self._build_config()

        # Manual history — list of plain dicts, no SDK objects
        self._history = []

        logger.info(
            f"Gemini session created: model={model}, "
            f"system_instruction={len(system_instruction)} chars, "
            f"tools={len(tool_declarations) if tool_declarations else 0}, "
            f"preconscious={'yes' if preconscious else 'no'}"
        )

    def _build_config(self):
        """Build a GenerateContentConfig from stored parameters."""
        config_kwargs = {
            "system_instruction": self._system_instruction,
            "temperature": self._temperature,
            "max_output_tokens": self._max_output_tokens,
        }

        if self._tool_declarations:
            config_kwargs["tools"] = [
                self._types.Tool(function_declarations=self._tool_declarations)
            ]
            logger.info(
                f"Registered {len(self._tool_declarations)} native "
                f"function declarations"
            )

        return self._types.GenerateContentConfig(**config_kwargs)

    # ── Core: One API Call Per Pulse ──────────────────────────────────

    def send_message(self, message: str) -> str:
        """Send one message to Gemini. Exactly ONE API call.

        If the model returns function calls, tools are executed synchronously.
        The tool results are natively queued as FunctionResponse objects 
        and injected into the next pulse's user message.
        Function calls and responses are preserved natively in history,
        completely preventing text syntax hallucination.

        Returns:
            The model's text output (thought / internal monologue).
        """
        self._tools_used = []

        # Build the parts for the new user message
        user_parts = []
        user_parts_dict = []

        if self._native_tool_responses:
            for res in self._native_tool_responses:
                fr_kwargs = {
                    "name": res["name"],
                    "response": res["response"]
                }
                if "id" in res:
                    fr_kwargs["id"] = res["id"]
                user_parts.append(
                    self._types.Part(
                        function_response=self._types.FunctionResponse(**fr_kwargs)
                    )
                )
                
                fr_dict = {
                    "name": res["name"],
                    "response": res["response"]
                }
                if "id" in res:
                    fr_dict["id"] = res["id"]
                user_parts_dict.append({"function_response": fr_dict})

        user_parts.append(self._types.Part(text=message))
        user_parts_dict.append({"text": message})

        contents = self._history_to_sdk() + [
            self._types.Content(role="user", parts=user_parts)
        ]

        try:
            response = self._client.models.generate_content(
                model=self._model,
                contents=contents,
                config=self._config,
            )
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            return f"[internal error: Gemini API call failed — {str(e)[:200]}]"

        # Success! Now we can safely clear pending native results and append user message
        self._native_tool_responses = []
        self._update_token_count(response)
        self._history.append({"role": "user", "parts": user_parts_dict})
        
        function_calls = self._extract_function_calls(response)
        thought_text = self._extract_text(response)

        if function_calls:
            model_parts_dict = []
            if thought_text:
                model_parts_dict.append({"text": thought_text})
                
            for fc in function_calls:
                name = fc.name
                args = dict(fc.args) if fc.args else {}
                fc_id = getattr(fc, "id", None)
                thought_sig = getattr(fc, "thought_signature", None)
                
                logger.info(f"FC: {name}({args}) id={fc_id}")
                self._tools_used.append({"name": name, "args": args})
                
                if self._tool_executor:
                    result_str = self._tool_executor.execute_function_call(name, args)
                else:
                    result_str = f"Tool executor not available for: {name}"
                    
                logger.info(f"FC result ({name}): {result_str[:500] if result_str else '(empty)'}")
                
                res_dict = {
                    "name": name,
                    "response": {"result": result_str or ""}
                }
                if fc_id:
                    res_dict["id"] = fc_id
                self._native_tool_responses.append(res_dict)
                
                # Also queue for the pulse loop events (preconscious grounding)
                self._pending_tool_results.append({
                    "name": name,
                    "args": args,
                    "result": result_str or "",
                })
                
                fc_dict = {
                    "name": name,
                    "args": args
                }
                if fc_id:
                    fc_dict["id"] = fc_id
                if thought_sig:
                    fc_dict["thought_signature"] = thought_sig
                model_parts_dict.append({"function_call": fc_dict})
                
            self._history.append({"role": "model", "parts": model_parts_dict})
            return thought_text or "[tools called, results pending]"
            
        else:
            if thought_text:
                self._history.append({"role": "model", "parts": [{"text": thought_text}]})
            return thought_text

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

    # ── Model Switching ──────────────────────────────────────────────

    def switch_model(self, new_model: str):
        """Switch to a different model. History is preserved as-is.

        No session recreation needed — we manage history ourselves.
        Just update the model name for the next generate_content() call.
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
            for part in msg.get("parts", []):
                if isinstance(part, dict) and "text" in part:
                    total += len(part["text"])
                elif isinstance(part, str):
                    total += len(part)
        return total

    def replace_history(self, compressed_history: List[Dict[str, Any]]):
        """Replace the conversation history with compressed version.

        No session recreation needed — just swap the list. The next
        generate_content() call will use the new history.

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

        Rebuilds the config with new tools. History is unchanged.
        """
        self._tool_declarations = new_declarations
        self._config = self._build_config()
        logger.info(
            "Tool declarations updated: %d tools, "
            "history preserved (%d messages)",
            len(new_declarations), len(self._history),
        )

    # ── Token Counting ───────────────────────────────────────────────

    def _update_token_count(self, response) -> None:
        """Extract prompt token count from usage metadata."""
        try:
            meta = getattr(response, "usage_metadata", None)
            if meta:
                self._last_token_count = getattr(
                    meta, "prompt_token_count", 0
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

    def _extract_function_calls(self, response) -> list:
        """Extract function_call parts from a response."""
        calls = []
        try:
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "function_call") and part.function_call:
                        calls.append(part.function_call)
        except (AttributeError, IndexError, TypeError):
            pass
        return calls

    def _extract_text(self, response) -> str:
        """Extract text content from a response."""
        try:
            parts = []
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, "text") and part.text:
                        parts.append(part.text)
            return "\n".join(parts) if parts else ""
        except (AttributeError, IndexError, TypeError):
            return ""

    # ── History Serialization ────────────────────────────────────────

    def _history_to_sdk(self) -> List:
        """Convert plain dict history to SDK Content objects for API call.

        The history is stored as plain dicts for easy manipulation.
        This converts them to SDK types for the generate_content() call.
        """
        sdk_contents = []
        for msg in self._history:
            role = msg.get("role", "user")
            parts = []
            for part_dict in msg.get("parts", []):
                if isinstance(part_dict, dict):
                    if "text" in part_dict:
                        parts.append(
                            self._types.Part(text=part_dict["text"])
                        )
                    # Note: function_call and function_response parts
                    # should not appear in history — they're converted
                    # to text by _format_tool_actions(). But handle
                    # gracefully if they exist from pre-compression history.
                    elif "function_call" in part_dict:
                        fc = part_dict["function_call"]
                        fc_kwargs = {
                            "name": fc.get("name", ""),
                            "args": fc.get("args", {}),
                        }
                        if "id" in fc:
                            fc_kwargs["id"] = fc["id"]
                        if "thought_signature" in fc:
                            fc_kwargs["thought_signature"] = fc["thought_signature"]
                        parts.append(
                            self._types.Part(
                                function_call=self._types.FunctionCall(
                                    **fc_kwargs
                                )
                            )
                        )
                    elif "function_response" in part_dict:
                        fr = part_dict["function_response"]
                        fr_kwargs = {
                            "name": fr.get("name", ""),
                            "response": fr.get("response", {}),
                        }
                        if "id" in fr:
                            fr_kwargs["id"] = fr["id"]
                        parts.append(
                            self._types.Part(
                                function_response=self._types.FunctionResponse(
                                    **fr_kwargs
                                )
                            )
                        )
                elif isinstance(part_dict, str):
                    parts.append(self._types.Part(text=part_dict))

            if parts:
                sdk_contents.append(
                    self._types.Content(role=role, parts=parts)
                )
        return sdk_contents
