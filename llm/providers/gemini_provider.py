"""
Helix — Gemini Chat Session Provider (Native Function Calling)

Uses the google.genai SDK to create persistent multi-turn chat sessions
with Gemini models, including native function calling for all tools.

The chat session handles the full function call cycle internally:
  1. Send message to model
  2. If model returns function_call parts → execute via ToolExecutor
  3. Send function results back (with matching id) to model
  4. Repeat until model returns pure text (the internal monologue)
  5. Return the final text to the pulse loop

The SDK manages conversation history and context window automatically.
No manual truncation, rollover, or char counting needed.

Subconscious agents (dream engine, etc.) continue to use local Ollama.
"""

import os
import logging
from typing import Optional, List, Dict, Any

from llm.providers.base import ChatSession

logger = logging.getLogger("helix.llm.providers.gemini")


class GeminiSession(ChatSession):
    """Chat session backed by Gemini API with native function calling.

    Uses client.chats.create() for persistent multi-turn conversation.
    The SDK manages history, context, and thought signatures internally.
    """

    def __init__(
        self,
        model: str = None,
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

        from llm.providers.base import PRIMARY_MODEL
        self._model = model or PRIMARY_MODEL
        self._tool_executor = tool_executor
        self._preconscious = preconscious
        self._genai = genai
        self._types = types
        self._tools_used = []
        self._last_token_count = 0

        # Store config for session recreation (compression / toolset changes)
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

        # Build config
        config_kwargs = {
            "system_instruction": system_instruction,
            "temperature": temperature,
            "max_output_tokens": max_output_tokens,
        }

        # Add tool declarations if provided
        if tool_declarations:
            config_kwargs["tools"] = [
                types.Tool(function_declarations=tool_declarations)
            ]
            logger.info(f"Registered {len(tool_declarations)} native function declarations")

        # Create persistent chat session — the SDK manages everything
        self._chat = self._client.chats.create(
            model=model,
            config=types.GenerateContentConfig(**config_kwargs),
        )

        logger.info(
            f"Gemini session created: model={model}, "
            f"system_instruction={len(system_instruction)} chars, "
            f"tools={len(tool_declarations) if tool_declarations else 0}, "
            f"preconscious={'yes' if preconscious else 'no'}"
        )

    def switch_model(self, new_model: str):
        """Recreate the session on a different model, preserving history.

        Used for 429 fallback — e.g. gemini-3-flash-preview → gemini-3.1-flash-lite-preview.
        """
        old_model = self._model
        self._model = new_model

        # Get current history before destroying session
        current_history = self.get_history()
        self.replace_history(current_history)

        logger.info(
            f"Model switched: {old_model} → {new_model} "
            f"(history preserved: {len(current_history)} messages)"
        )

    def send_message(self, message: str) -> str:
        """Send a message, handle function calls, return final thought text.

        If the model requests function calls, this method:
          1. Executes each via tool_executor.execute_function_call()
          2. Sends results back to the model (with matching id per Gemini 3 spec)
          3. Repeats until the model produces text

        Returns:
            The model's final text response (internal monologue).
        """
        self._tools_used = []

        try:
            response = self._chat.send_message(message)
        except Exception as e:
            logger.error(f"Gemini API call failed: {e}")
            return f"[internal error: Gemini API call failed — {str(e)[:200]}]"

        # Loop until model returns text (no function calls)
        round_num = 0
        MAX_FC_ROUNDS = 20  # Circuit breaker: prevent infinite FC loops
        while True:
            function_calls = self._extract_function_calls(response)

            if not function_calls:
                # No function calls — return the text response
                self._update_token_count(response)
                return self._extract_text(response)

            # Circuit breaker: if we've exceeded max rounds, force return
            if round_num >= MAX_FC_ROUNDS:
                logger.warning(
                    f"FC circuit breaker triggered at round {round_num} — "
                    f"forcing text extraction"
                )
                text = self._extract_text(response)
                return text or "[FC loop exceeded maximum rounds — thought aborted]"

            # Execute function calls and collect results
            function_responses = []
            for fc in function_calls:
                name = fc.name
                args = dict(fc.args) if fc.args else {}
                fc_id = getattr(fc, 'id', None)

                logger.info(f"FC[{round_num}]: {name}({args}) id={fc_id}")
                self._tools_used.append({"name": name, "args": args})

                # Execute via tool executor
                if self._tool_executor:
                    result_str = self._tool_executor.execute_function_call(name, args)
                else:
                    result_str = f"Tool executor not available for: {name}"

                # Log the actual result for forensic verification
                logger.info(
                    f"FC[{round_num}] result ({name}): "
                    f"{result_str[:500] if result_str else '(empty)'}"
                )

                # Preconscious enrichment — inject beliefs relevant to tool result.
                # Skip for output-only tools (reply, send_message, verbalize).
                _OUTPUT_TOOLS = {"reply", "send_message", "verbalize"}
                if (self._preconscious and result_str
                        and name not in _OUTPUT_TOOLS):
                    try:
                        beliefs = self._preconscious.inject(
                            previous_thought=result_str[:300],
                            trigger_type="tool_result",
                        )
                        if beliefs:
                            result_str += f"\n\n<spatial-awareness>\n{beliefs}\n</spatial-awareness>"
                    except Exception as e:
                        logger.debug(f"Preconscious enrichment failed: {e}")

                # Build function response — include id per Gemini 3 spec
                fr_kwargs = {
                    "name": name,
                    "response": {"result": result_str},
                }
                if fc_id:
                    fr_kwargs["id"] = fc_id

                function_responses.append(
                    self._types.Part(
                        function_response=self._types.FunctionResponse(**fr_kwargs)
                    )
                )

            # Send function results back to the model
            try:
                response = self._chat.send_message(function_responses)
            except Exception as e:
                logger.error(f"Gemini FC response failed: {e}")
                return f"[internal error: function response failed — {str(e)[:200]}]"

            round_num += 1

    def _update_token_count(self, response) -> None:
        """Extract prompt token count from usage metadata."""
        try:
            meta = getattr(response, "usage_metadata", None)
            if meta:
                self._last_token_count = getattr(meta, "prompt_token_count", 0)
        except Exception:
            pass

    def get_last_token_count(self) -> int:
        """Get the prompt token count from the last interaction."""
        return self._last_token_count

    def get_history_size(self) -> int:
        """Return approximate character count of history."""
        try:
            history = self._chat.get_history(curated=True)
            total = 0
            for msg in history:
                for part in getattr(msg, 'parts', []):
                    if hasattr(part, 'text') and part.text:
                        total += len(part.text)
            return total
        except Exception:
            return 0

    def get_history(self) -> List[Dict[str, Any]]:
        """Return the curated chat history as serializable dicts.

        Converts the SDK's internal Content objects into plain dicts
        with the structure: {"role": str, "parts": [...]}
        This is what the ContextCompressor operates on.
        """
        try:
            history = self._chat.get_history(curated=True)
        except Exception:
            return []

        result = []
        for msg in history:
            role = getattr(msg, 'role', 'user')
            parts = []
            for part in getattr(msg, 'parts', []):
                if hasattr(part, 'text') and part.text:
                    parts.append({"text": part.text})
                elif hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    fc_dict = {
                        "function_call": {
                            "name": getattr(fc, 'name', ''),
                            "args": dict(fc.args) if fc.args else {},
                        }
                    }
                    if hasattr(fc, 'id') and fc.id:
                        fc_dict["function_call"]["id"] = fc.id
                    parts.append(fc_dict)
                elif hasattr(part, 'function_response') and part.function_response:
                    fr = part.function_response
                    fr_dict = {
                        "function_response": {
                            "name": getattr(fr, 'name', ''),
                            "response": dict(fr.response) if fr.response else {},
                        }
                    }
                    if hasattr(fr, 'id') and fr.id:
                        fr_dict["function_response"]["id"] = fr.id
                    parts.append(fr_dict)
            if parts:
                result.append({"role": role, "parts": parts})
        return result

    def replace_history(self, compressed_history: List[Dict[str, Any]]):
        """Replace the current session with a new one containing compressed history.

        Creates a fresh chat session with the same config but uses the
        compressed message list as the seed history. This is the cleanest
        approach — avoids mutating SDK internals.

        Args:
            compressed_history: List of Gemini-format message dicts from
                                the ContextCompressor.
        """
        # Convert plain dicts back to SDK Content objects
        sdk_history = []
        for msg in compressed_history:
            role = msg.get("role", "user")
            parts = []
            for part_dict in msg.get("parts", []):
                if isinstance(part_dict, dict):
                    if "text" in part_dict:
                        parts.append(self._types.Part(text=part_dict["text"]))
                    elif "function_call" in part_dict:
                        fc = part_dict["function_call"]
                        fc_kwargs = {
                            "name": fc.get("name", ""),
                            "args": fc.get("args", {}),
                        }
                        if "id" in fc:
                            fc_kwargs["id"] = fc["id"]
                        parts.append(
                            self._types.Part(
                                function_call=self._types.FunctionCall(**fc_kwargs)
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
                                function_response=self._types.FunctionResponse(**fr_kwargs)
                            )
                        )
                elif isinstance(part_dict, str):
                    parts.append(self._types.Part(text=part_dict))

            if parts:
                sdk_history.append(
                    self._types.Content(role=role, parts=parts)
                )

        # Rebuild config
        config_kwargs = {
            "system_instruction": self._system_instruction,
            "temperature": self._temperature,
            "max_output_tokens": self._max_output_tokens,
        }
        if self._tool_declarations:
            config_kwargs["tools"] = [
                self._types.Tool(function_declarations=self._tool_declarations)
            ]

        # Create new session with compressed history using existing client
        self._chat = self._client.chats.create(
            model=self._model,
            config=self._types.GenerateContentConfig(**config_kwargs),
            history=sdk_history,
        )

        logger.info(
            "Session recreated with compressed history: %d messages",
            len(sdk_history),
        )

    def update_tool_declarations(
        self, new_declarations: List[Dict[str, Any]]
    ):
        """Rebuild the session with a different set of tool declarations.

        Preserves the existing conversation history but changes which
        tools are available. Used by the dynamic toolset system.

        Args:
            new_declarations: New list of FunctionDeclaration dicts.
        """
        self._tool_declarations = new_declarations

        # Get current history before destroying session
        current_history = self.get_history()

        # Recreate with new tools + existing history
        self.replace_history(current_history)

        logger.info(
            "Tool declarations updated: %d tools, history preserved (%d messages)",
            len(new_declarations), len(current_history),
        )

    def get_last_tool_calls(self) -> List[Dict[str, Any]]:
        """Return the list of tools called during the last send_message()."""
        return self._tools_used

    def _extract_function_calls(self, response) -> list:
        """Extract function_call parts from a response."""
        calls = []
        try:
            for candidate in response.candidates:
                for part in candidate.content.parts:
                    if hasattr(part, 'function_call') and part.function_call:
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
                    if hasattr(part, 'text') and part.text:
                        parts.append(part.text)
            return "\n".join(parts) if parts else ""
        except (AttributeError, IndexError, TypeError):
            return ""
