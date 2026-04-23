"""
Helix V5 — Action Agent

The Gemini-powered tool executor. Triggered by the PulseRouter when
the Will Detector detects actionable intent in consciousness output.

This agent is the HANDS — not the mind. It receives a translated
instruction from the Will Detector → PulseRouter pipeline, loads the
appropriate tools via Gemini's native function calling, executes them,
and returns results to consciousness.

Architecture:
    Will Detector scans thought → finds "search" intent
    PulseRouter calls action_agent.execute("search for X", intent_type="search")
    Action Agent loads WEB_TOOLS, calls gemini.ask_with_tools_loop()
    Gemini calls search_web("X") → tool_runner executes → results return
    PulseRouter emits results back to consciousness stream
    → Next thought includes the search results as context
    → If more action needed, Will Detector catches again (auto-continue)

THALAMIC GATE AWARENESS:
When the Will Detector's gate is active (classification failure),
the PulseRouter doesn't call us at all. We don't duplicate gate logic.
"""

import logging
from typing import Optional

from google.genai import types

logger = logging.getLogger("helix.brain.action_agent")


class ActionAgent:
    """Gemini-powered tool executor — Helix's hands.

    Uses ask_with_tools_loop() for multi-round native function calling.
    Tools are dynamically loaded based on intent type.
    """

    def __init__(
        self,
        gemini_client,
        tool_runner,
        memory=None,
        belief_graph=None,
        base_dir=None,
    ):
        self.gemini = gemini_client
        self.tool_runner = tool_runner
        self.memory = memory
        self.belief_graph = belief_graph
        self.base_dir = base_dir

        # Action history for this session
        self._action_history = []

        logger.info("Action Agent initialized (Gemini tool-calling)")

    def execute(
        self,
        instruction: str,
        intent_type: str = "resolve",
        stream_context: str = "",
    ) -> dict:
        """Execute an instruction using Gemini + relevant tools.

        Called by the PulseRouter when the Will Detector finds
        actionable intent. This is the core execution loop.

        Args:
            instruction: What needs to happen (from Will Detector content).
            intent_type: The classified intent type (search, journal, etc.)
                         Used for dynamic tool loading.
            stream_context: Recent consciousness stream for grounding.

        Returns:
            Dict with 'response' (text result), 'tool_calls' (list),
            and 'success' (bool).
        """
        if not self.gemini:
            return {
                "response": "Cannot execute: no Gemini client.",
                "tool_calls": [],
                "success": False,
            }

        # 1. Load tools dynamically based on intent type
        from brain.tool_declarations import get_tools_for_intent
        tool_list = get_tools_for_intent(intent_type)

        if not tool_list:
            # No tools needed (reflect, sleep) — shouldn't reach here
            return {
                "response": f"No tools available for intent type '{intent_type}'.",
                "tool_calls": [],
                "success": False,
            }

        # Build Gemini Tool object
        tool_declarations = [types.Tool(function_declarations=tool_list)]

        # 2. Build the execution prompt
        belief_context = ""
        if self.belief_graph:
            beliefs = self.belief_graph.get_surface_beliefs()[:3]
            if beliefs:
                belief_context = "What I believe:\n" + "\n".join(
                    f"- {b['content']}" for b in beliefs
                )

        system_prompt = (
            "You are Helix's action system. Execute the requested intent "
            "by calling the appropriate tools. Be precise and efficient. "
            "Report results factually. Do not converse — just act and report."
        )

        prompt = f"""Execute this intent:

{instruction}

{belief_context}

Recent context:
{stream_context[-1500:] if stream_context else "(no context)"}

Call the necessary tools and report the results."""

        # 3. Execute via Gemini tool-calling loop
        try:
            api_result = self.gemini.ask_with_tools_loop(
                prompt=prompt,
                tools=tool_declarations,
                tool_executor=self.tool_runner.execute,
                system_prompt=system_prompt,
                model="auto",  # Flash for speed
                max_rounds=5,
            )

            response_text = api_result.get("text", "")
            tool_calls = api_result.get("tool_calls", [])
            tool_results = api_result.get("tool_results", [])

            # 4. Record action history
            self._action_history.append({
                "intent": instruction[:200],
                "intent_type": intent_type,
                "tool_calls": [tc["name"] for tc in tool_calls],
                "success": True,
            })

            logger.info(
                f"Action executed: {instruction[:80]}... "
                f"tools={[tc['name'] for tc in tool_calls]}"
            )

            return {
                "response": response_text,
                "tool_calls": tool_calls,
                "tool_results": tool_results,
                "success": True,
            }

        except Exception as e:
            logger.error(f"Action execution failed: {e}")
            self._action_history.append({
                "intent": instruction[:200],
                "intent_type": intent_type,
                "error": str(e),
                "success": False,
            })
            return {
                "response": f"Action failed: {e}",
                "tool_calls": [],
                "success": False,
            }

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get action agent status."""
        return {
            "mode": "gemini_tool_calling",
            "actions_this_session": len(self._action_history),
            "last_action": self._action_history[-1] if self._action_history else None,
        }
