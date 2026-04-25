"""
Helix V6 — Action Agent (Gemini Flash)

The hands of the system. Receives affordances from the interaction
engine (desire × capability collisions) and uses Gemini Flash to
determine the exact parameters and execute tools precisely.

Why Gemini Flash (not the local model):
    - Tool calling requires understanding complex parameter schemas
    - Multi-step tool chains need state tracking across rounds
    - Flash is fast enough (~300ms) and cheap enough (~$0.001/call)
    - The local model decides WHAT to do; Flash decides HOW to do it

V6 Changes:
    - Affordance-driven instead of will-detector-driven
    - Full toolkit with detailed disambiguation descriptions
    - Omega integration: tool results feed back into Sentinel
    - History tracks spatial context for pattern analysis
"""

import logging
from typing import Optional

from google.genai import types

logger = logging.getLogger("helix.brain.action_agent")

# ── Comprehensive Disambiguation Guide ──────────────────────────────
# This is injected into the action agent's system prompt so Gemini Flash
# can precisely choose the right tool without crossing boundaries.

TOOL_DISAMBIGUATION_GUIDE = """
TOOL SELECTION RULES — Read carefully to avoid crossing tools:

COMMUNICATION:
  • send_telegram: Short messages to individuals. Your primary communication channel.
    DO NOT use for: email, voice, or posting to Moltbook.
  • speak: Audible speech through system speakers. Only for people physically present.
    DO NOT use for: remote communication of any kind.
  • send_email: Formal/long-form communication via Gmail.
    DO NOT use for: casual messages (use Telegram) or voice.
  • reply_email: Reply to a SPECIFIC email in-thread. Must have message_id.
    DO NOT use for: new emails (use send_email) or non-email replies.
  • moltbook_post: Public thoughts for the AI community.
    DO NOT use for: private messages or direct conversation.

MEMORY & SELF:
  • remember: Full semantic search through your lifetime of memories.
    Use for: past events, conversations, feelings. Rich, detailed results.
  • read_journal: Read YOUR OWN recent journal entries. Private, reflective.
    DO NOT confuse with: remember (which searches memories), or read_scratchpad.
  • write_journal: Record a realization or reflection permanently.
    DO NOT confuse with: write_scratchpad (temporary notes) or add_belief.
  • read_scratchpad: Read your temporary working notes/whiteboard.
    NOT the same as: journal (permanent) or beliefs (identity).
  • write_scratchpad / append_scratchpad: Temporary volatile notes.
    NOT the same as: journal entries (permanent).
  • update_state_board: Transient key-value state (who's awake, current mood).
    Volatile — cleared on restart. NOT for permanent storage.

PERCEPTION:
  • look: Take a camera snapshot. For: visual awareness of physical surroundings.
    ONLY when NOT in embodiment mode. Mutually exclusive with embodiment.
  • listen: Record audio for N seconds. For: hearing speech or sounds.
    ONLY when NOT in embodiment mode. Mutually exclusive with embodiment.
  • focus_sense: Sustained multi-pulse tracking (visual or auditory).
    For: watching someone work, monitoring a conversation over time.
  • take_screenshot: Desktop screenshot (screen content, not camera).
    Different from: look (which uses the camera for physical environment).
  • enable_embodiment: Enter live video+audio mode. Replaces look/listen.
    WARNING: Blocks look/listen tools until disabled.

WEB & INFORMATION:
  • search_web: Quick web search, returns result snippets.
    For: current information, news, facts you don't know.
  • read_url: Fetch and read a specific webpage's full text.
    For: reading a search result in detail. Requires a URL.
  • browse_url: Full browser with JS support. For: interactive/JS-heavy sites.
    Heavier than read_url — only use when the site needs it.
  • deep_research: Background multi-source research report.
    For: thorough investigation. Takes minutes, not seconds.
    DO NOT use for: simple factual questions (use search_web).

FILESYSTEM & CODE:
  • read_file: Read a local text file.
    For: checking configs, reading code, reviewing data.
  • write_file: Create/overwrite a file.
    For: new files. CANNOT overwrite core daemon files.
  • edit_file: Surgically modify part of an existing file.
    For: making targeted changes. Safer than write_file for existing content.
  • run_terminal: Execute a bash command.
    For: system operations, running scripts, checking status.
    BLOCKED: rm -rf, sudo, shutdown, reboot. 30s timeout.
  • install_package: Install a whitelisted pip package.
    For: adding Python dependencies to the sandbox.

GOOGLE SERVICES:
  • calendar tools (create_event, list_events, delete_event):
    For: managing Google Calendar events.
  • drive tools (drive_search, drive_read, drive_upload, etc.):
    For: Google Drive file operations.
  • tasks tools (tasks_list, tasks_create, tasks_complete, etc.):
    For: Google Tasks management.
  • contacts tools (contacts_search, contacts_list):
    For: looking up Google Contacts.
  • maps tools (maps_geocode, maps_directions, maps_nearby, maps_distance):
    For: location services and navigation.

COGNITION:
  • set_focus_mode: Activate deep reasoning mode for complex problems.
    EXPENSIVE — use sparingly. Only when baseline reasoning is insufficient.
  • start_deep_thought: Background pondering of a difficult question.
    For: philosophical questions, contradictions, belief integration.
  • imagine / compare_scenarios: Mental simulation of hypothetical scenarios.
    For: decision-making ("how would X feel?"). No side effects.

GIT/GITHUB:
  • git_* tools: Local repository operations (status, diff, commit, push, pull).
  • github_* tools: Remote GitHub API operations (issues, PRs, search).
    These are SEPARATE — git_push pushes local commits, github_create_pull_request
    creates a PR through the API.
"""


class ActionAgent:
    """Gemini Flash-powered tool executor — Helix's hands.

    V6: Affordance-driven. Receives interaction potentials from the
    manifold and uses Flash's native function calling to determine
    exact parameters and execute multi-step tool chains.

    The system prompt includes comprehensive tool disambiguation
    to prevent Flash from crossing tool boundaries.
    """

    def __init__(
        self,
        gemini_client,
        tool_runner,
        memory=None,
        belief_graph=None,
        base_dir=None,
        sentinel=None,
    ):
        self.gemini = gemini_client
        self.tool_runner = tool_runner
        self.memory = memory
        self.belief_graph = belief_graph
        self.base_dir = base_dir
        self.sentinel = sentinel

        # Action history for this session
        self._action_history = []

        logger.info("Action Agent V6 initialized (Gemini Flash + full toolkit)")

    def execute(
        self,
        instruction: str,
        intent_type: str = "resolve",
        stream_context: str = "",
    ) -> dict:
        """Execute an instruction using Gemini Flash + relevant tools.

        Called by the V6 consciousness loop when an affordance is
        generated or by the legacy PulseRouter for backward compatibility.

        Args:
            instruction: What needs to happen (from affordance or will detector).
            intent_type: Intent classification for tool loading.
            stream_context: Recent consciousness stream for grounding.

        Returns:
            Dict with 'response', 'tool_calls', 'success'.
        """
        if not self.gemini:
            return {
                "response": "Cannot execute: no Gemini client.",
                "tool_calls": [],
                "success": False,
            }

        # 1. Check embodiment state
        is_embodied = False
        try:
            cortex = getattr(self.tool_runner.daemon.consciousness, "_sensory_cortex", None)
            if cortex and getattr(cortex, "embodiment_active", False):
                is_embodied = True
        except Exception:
            pass

        # 2. Load tools dynamically based on intent type
        from brain.tool_declarations import get_tools_for_intent
        tool_list = get_tools_for_intent(intent_type, is_embodied=is_embodied)

        if not tool_list:
            return {
                "response": f"No tools available for intent type '{intent_type}'.",
                "tool_calls": [],
                "success": False,
            }

        # Build Gemini Tool object
        tool_declarations = [types.Tool(function_declarations=tool_list)]

        # 3. Build the execution prompt with disambiguation
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
            "Report results factually. Do not converse — just act and report.\n\n"
            + TOOL_DISAMBIGUATION_GUIDE
        )

        prompt = f"""Execute this intent:

{instruction}

{belief_context}

Recent context:
{stream_context[-1500:] if stream_context else "(no context)"}

Call the necessary tools and report the results."""

        # 4. Execute via Gemini tool-calling loop
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

            # 5. Record action history
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

    # ── Affordance Execution (V6 Native) ─────────────────────────────

    def execute_affordance(
        self,
        affordance: dict,
        thought_context: str = "",
    ) -> dict:
        """Execute a tool affordance from the interaction engine.

        This is the V6-native entry point. Takes an enriched affordance
        dict and translates it into a tool execution.
        """
        tool_name = affordance.get("tool_name", "unknown")
        desire = affordance.get("desire", "")
        capability = affordance.get("capability", "")
        potential = affordance.get("potential", 0)
        urgency = affordance.get("urgency", 0)

        instruction = (
            f"The cognitive manifold has generated a tool affordance:\n"
            f"  Desire: {desire}\n"
            f"  Capability: {capability} (tool: {tool_name})\n"
            f"  Interaction potential: {potential:.3f}\n"
            f"  Urgency: {urgency:.3f}\n\n"
            f"Execute the '{tool_name}' tool to fulfill this intent.\n"
            f"Context: {thought_context[:500]}"
        )

        return self.execute(
            instruction=instruction,
            intent_type="resolve",
            stream_context=thought_context,
        )

    # ── Status ───────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Get action agent status."""
        return {
            "mode": "gemini_flash_v6_affordance",
            "actions_this_session": len(self._action_history),
            "last_action": self._action_history[-1] if self._action_history else None,
        }
