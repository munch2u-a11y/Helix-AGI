"""
Helix — Tool Executor

Parses action tags from consciousness output and executes them locally.
All execution is pure Python — no external LLM needed for dispatch.

Static core tools (always in system prompt):
  [TERMINAL:] command          — Run a bash command
  [SEARCH:] query              — Web search (DuckDuckGo)
  [READ_URL:] url              — Fetch and extract text from webpage
  [READ_FILE:] path            — Read a local file
  [WRITE_FILE:path] content    — Write/create a file
  [SPEAK:] text                — Local TTS (edge-tts / espeak-ng fallback)
  [LISTEN:] duration           — Microphone capture + Whisper transcription
  [LOOK:] focus                — Camera capture + vision analysis

Extended tools (injected by preconscious when contextually relevant):
  [TELEGRAM:] / [DISCORD:]     — Explicit channel messaging
  [GIT_*:] / [GITHUB_*:]       — Git/GitHub operations
  [MOLTBOOK_*:]                — Moltbook social platform
  [EMAIL_*:]                   — Gmail API
  [CALENDAR_*:]                — Google Calendar API
  [DRIVE_*:]                   — Google Drive API
  [TASKS_*:]                   — Google Tasks API
  [DESKTOP_*:]                 — Desktop control (xdotool)
  [BROWSE*:]                   — Browser automation (Playwright)

Tags handled by pulse_loop.py (not processed here):
  [REPLY:name] — Routed by channel_router
  [NOTE:] / [NOTE_DONE:] — Scratchpad
  [REMEMBER:] — Memory retrieval
  [JOURNAL:] — Daily journal
"""

import os
import re
import subprocess
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("helix.tools.executor")

# ── Security ─────────────────────────────────────────────────────────
BLOCKED_COMMANDS = {"rm -rf /", "shutdown", "reboot", "mkfs", "dd if=", ":(){", "fork bomb"}
BLOCKED_WRITE_FILES = {"daemon.py", "main.py", "pulse_loop.py", "physics_engine.py"}
MAX_FILE_READ = 2_000_000  # 2MB
MAX_FILE_WRITE = 500_000   # 500KB
TERMINAL_TIMEOUT = 30      # seconds


@dataclass
class ActionTag:
    """A parsed action tag from consciousness output."""
    tag: str          # e.g. "TERMINAL", "SEARCH", "SPEAK"
    param: str        # e.g. path, recipient name (the part after the colon)
    content: str      # The body text after the tag


class ToolExecutor:
    """Parses and executes action tags from conscious thought output.

    All execution is local Python. Results are returned as strings
    to be injected into the event queue for the next pulse.

    Tool execution routes through the ToolRegistry for check_fn
    availability gating, TTL caching, and thread-safe dispatch.
    """

    def __init__(self, channel_router=None):
        self._web_search = None  # Lazy-loaded
        self._channel_router = channel_router  # For explicit channel sends
        self._moltbook = None    # Lazy-loaded
        self._github = None      # Lazy-loaded
        self._vision_cortex = None  # Lazy-loaded VisionCortex (Moondream/Vulkan)
        self._piper_voice = None    # Lazy-loaded PiperVoice
        self._pulse_loop = None  # Set via set_pulse_loop() for context reset

        # Populate the tool registry with all tools
        self._populate_registry()
        logger.info("ToolExecutor initialized (registry: %d tools)",
                    len(self._registry.get_tool_names()))

    def set_pulse_loop(self, pulse_loop):
        """Wire the pulse loop reference for context reset tool."""
        self._pulse_loop = pulse_loop

    # ── Registry Population ──────────────────────────────────────────

    def _populate_registry(self):
        """Populate the ToolRegistry with all tools, grouped by toolset.

        Each toolset gets:
          - Its schema declarations (from tool_declarations.py)
          - Its handlers (bound methods from this class)
          - An optional check_fn for runtime availability
          - An optional requires_env list
        """
        from tools.tool_registry import registry
        from tools.tool_declarations import (
            CORE_TOOLS, TOOLSET_MANAGEMENT_TOOLS, SENSORY_TOOLS,
            BROWSER_TOOLS, GIT_TOOLS, GITHUB_TOOLS,
            MOLTBOOK_TOOLS, EMAIL_TOOLS, CALENDAR_TOOLS,
            DRIVE_TOOLS, TASKS_TOOLS, DESKTOP_TOOLS,
        )
        self._registry = registry

        # ── Availability check functions ─────────────────────────────
        def _check_github():
            return bool(os.environ.get("GITHUB_TOKEN"))

        def _check_google_creds():
            # Google token is at ~/.config/helix/google_token.json
            # (loaded by main.py's _load_credentials)
            creds_path = os.path.expanduser("~/.config/helix/google_token.json")
            return os.path.exists(creds_path)

        def _check_moltbook():
            # Moltbook API key is set in credentials.env
            return bool(os.environ.get("MOLTBOOK_API_KEY"))

        def _check_desktop():
            # xdotool required for desktop control
            try:
                import subprocess
                subprocess.run(["which", "xdotool"], capture_output=True, check=True)
                return True
            except Exception:
                return False

        # ── Build handler maps (bound methods) ───────────────────────
        core_handlers = {
            "reply": self._fc_reply,
            "send_message": self._fc_send_message,
            "terminal": self._fc_terminal,
            "search": self._fc_search,
            "read_url": self._fc_read_url,
            "read_file": self._fc_read_file,
            "write_file": self._fc_write_file,
            "append_file": self._fc_append_file,
            "memory_recall": self._fc_memory_recall,
            "note": self._fc_note,
            "note_done": self._fc_note_done,
            "list_notes": self._fc_list_notes,
            "clear_notes": self._fc_clear_notes,
            "update_note": self._fc_update_note,
            "journal": self._fc_journal,
            "nap": self._fc_nap,
        }
        sensory_handlers = {
            "listen": self._fc_listen,
            "look": self._fc_look,
            "ptz_look": self._fc_ptz_look,
            "camera_auto_track": self._fc_camera_auto_track,
            "record_video": self._fc_record_video,
            "verbalize": self._fc_verbalize,
        }
        mgmt_handlers = {
            "enable_toolset": self._fc_enable_toolset,
            "disable_toolset": self._fc_disable_toolset,
            "list_toolsets": self._fc_list_toolsets,
        }
        browser_handlers = {
            "browse": self._fc_browse,
            "browse_interact": self._fc_browse_interact,
            "browse_screenshot": self._fc_browse_screenshot,
        }
        git_handlers = {
            "git_status": self._fc_git_status,
            "git_diff": self._fc_git_diff,
            "git_commit": self._fc_git_commit,
            "git_push": self._fc_git_push,
            "git_pull": self._fc_git_pull,
            "git_log": self._fc_git_log,
            "git_clone": self._fc_git_clone,
        }
        github_handlers = {
            "github_search": self._fc_github_search,
            "github_issue": self._fc_github_issue,
            "github_create_issue": self._fc_github_create_issue,
            "github_comment": self._fc_github_comment,
            "github_pr": self._fc_github_pr,
        }
        moltbook_handlers = {
            "moltbook_home": self._fc_moltbook_home,
            "moltbook_feed": self._fc_moltbook_feed,
            "moltbook_read": self._fc_moltbook_read,
            "moltbook_post": self._fc_moltbook_post,
            "moltbook_comment": self._fc_moltbook_comment,
            "moltbook_vote": self._fc_moltbook_vote,
            "moltbook_search": self._fc_moltbook_search,
            "moltbook_profile": self._fc_moltbook_profile,
            "moltbook_user_posts": self._fc_moltbook_user_posts,
            "moltbook_follow": self._fc_moltbook_follow,
            "moltbook_unfollow": self._fc_moltbook_unfollow,
            "moltbook_submolts": self._fc_moltbook_submolts,
            "moltbook_delete": self._fc_moltbook_delete,
            "moltbook_notifications": self._fc_moltbook_notifications,
            "moltbook_notifications_read": self._fc_moltbook_notifications_read,
        }
        email_handlers = {
            "email_send": self._fc_email_send,
            "email_read": self._fc_email_read,
            "email_search": self._fc_email_search,
            "email_get": self._fc_email_get,
            "email_reply": self._fc_email_reply,
            "email_reply_all": self._fc_email_reply_all,
            "email_forward": self._fc_email_forward,
            "email_mark_read": self._fc_email_mark_read,
        }
        calendar_handlers = {
            "calendar_create": self._fc_calendar_create,
            "calendar_list": self._fc_calendar_list,
            "calendar_delete": self._fc_calendar_delete,
        }
        drive_handlers = {
            "drive_search": self._fc_drive_search,
            "drive_read": self._fc_drive_read,
            "drive_list": self._fc_drive_list,
            "drive_upload": self._fc_drive_upload,
            "drive_share": self._fc_drive_share,
        }
        tasks_handlers = {
            "tasks_lists": self._fc_tasks_lists,
            "tasks_list": self._fc_tasks_list,
            "tasks_create": self._fc_tasks_create,
            "tasks_complete": self._fc_tasks_complete,
            "tasks_delete": self._fc_tasks_delete,
        }
        desktop_handlers = {
            "desktop_type": self._fc_desktop_type,
            "desktop_key": self._fc_desktop_key,
            "desktop_click": self._fc_desktop_click,
            "desktop_mouse": self._fc_desktop_mouse,
            "desktop_scroll": self._fc_desktop_scroll,
            "desktop_window": self._fc_desktop_window,
            "desktop_focus": self._fc_desktop_focus,
            "desktop_open": self._fc_desktop_open,
            "desktop_screenshot": self._fc_desktop_screenshot,
        }

        # ── Register all toolsets ─────────────────────────────────────

        # Core tools — strip out sensory tool declarations since they're
        # registered separately below.
        _sensory_names = {"listen", "look", "ptz_look", "camera_auto_track", "record_video", "verbalize"}
        core_tool_decls = [t for t in CORE_TOOLS if t["name"] not in _sensory_names]

        registry.register_batch(
            toolset="core",
            tools=core_tool_decls + TOOLSET_MANAGEMENT_TOOLS,
            handlers={**core_handlers, **mgmt_handlers},
            description="Core cognitive tools — always loaded",
            focus_types={
                "terminal": "focus",
                "write_file": "focus",
                "append_file": "focus",
                "search": "focus",
                "read_url": "focus",
                "read_file": "intake",
            },
        )
        registry.register_batch(
            toolset="sensory",
            tools=SENSORY_TOOLS,
            handlers=sensory_handlers,
            description="Sensory and hardware — camera, microphone, PTZ, video recording",
            focus_types={
                "look": "focus",
                "listen": "focus",
                "record_video": "focus",
                "ptz_look": "focus",
            },
        )
        registry.register_batch(
            toolset="browser",
            tools=BROWSER_TOOLS,
            handlers=browser_handlers,
            description="Web browsing and page interaction",
            focus_types={
                "browse": "focus",
                "browse_interact": "focus",
            },
        )
        registry.register_batch(
            toolset="git",
            tools=GIT_TOOLS,
            handlers=git_handlers,
            description="Local Git repository operations",
            focus_types={
                "git_commit": "focus",
                "git_push": "focus",
                "git_diff": "focus",
            },
        )
        registry.register_batch(
            toolset="github",
            tools=GITHUB_TOOLS,
            handlers=github_handlers,
            check_fn=_check_github,
            requires_env=["GITHUB_TOKEN"],
            description="GitHub API — search repos, manage issues, PRs",
            focus_types={
                "github_search": "focus",
                "github_create_issue": "focus",
            },
        )
        registry.register_batch(
            toolset="social",
            tools=MOLTBOOK_TOOLS,
            handlers=moltbook_handlers,
            check_fn=_check_moltbook,
            description="Moltbook social platform",
            focus_types={
                "moltbook_post": "focus",
                "moltbook_read": "intake",
                "moltbook_feed": "intake",
                "moltbook_home": "intake",
                "moltbook_notifications": "intake",
            },
        )
        registry.register_batch(
            toolset="email",
            tools=EMAIL_TOOLS,
            handlers=email_handlers,
            check_fn=_check_google_creds,
            requires_env=["GOOGLE_CREDENTIALS"],
            description="Gmail — send, read, search, reply, forward",
            focus_types={
                "email_read": "intake",
                "email_get": "intake",
                "email_search": "intake",
            },
        )
        registry.register_batch(
            toolset="calendar",
            tools=CALENDAR_TOOLS,
            handlers=calendar_handlers,
            check_fn=_check_google_creds,
            requires_env=["GOOGLE_CREDENTIALS"],
            description="Google Calendar — create, list, delete events",
            focus_types={
                "calendar_list": "intake",
            },
        )
        registry.register_batch(
            toolset="drive",
            tools=DRIVE_TOOLS,
            handlers=drive_handlers,
            check_fn=_check_google_creds,
            requires_env=["GOOGLE_CREDENTIALS"],
            description="Google Drive — search, read, list, upload, share",
            focus_types={
                "drive_read": "intake",
                "drive_search": "intake",
                "drive_list": "intake",
            },
        )
        registry.register_batch(
            toolset="tasks",
            tools=TASKS_TOOLS,
            handlers=tasks_handlers,
            check_fn=_check_google_creds,
            requires_env=["GOOGLE_CREDENTIALS"],
            description="Google Tasks — task lists, create, complete",
        )
        registry.register_batch(
            toolset="desktop",
            tools=DESKTOP_TOOLS,
            handlers=desktop_handlers,
            check_fn=_check_desktop,
            description="Desktop control — typing, clicking, screenshots",
            focus_types={
                "desktop_type": "focus",
                "desktop_click": "focus",
                "desktop_key": "focus",
            },
        )

        # ── Register tool_factory toolset ─────────────────────────────
        from tools.tool_declarations import TOOL_FACTORY_TOOLS
        tool_factory_handlers = {
            "create_custom_tool_template": self._fc_create_custom_tool_template,
            "register_custom_tool": self._fc_register_custom_tool,
            "list_custom_tools": self._fc_list_custom_tools,
            "delete_custom_tool": self._fc_delete_custom_tool,
        }
        registry.register_batch(
            toolset="tool_factory",
            tools=TOOL_FACTORY_TOOLS,
            handlers=tool_factory_handlers,
            description="Dynamic tool creation and registration",
        )

        # ── Load Dynamic Custom Tools ─────────────────────────────────
        import glob
        import importlib.util
        custom_dir = os.path.join(os.path.dirname(__file__), "custom")
        if os.path.exists(custom_dir):
            for filepath in glob.glob(os.path.join(custom_dir, "*.py")):
                filename = os.path.basename(filepath)
                if filename == "__init__.py":
                    continue
                tool_name = filename[:-3]
                module_name = f"tools.custom.{tool_name}"
                try:
                    spec = importlib.util.spec_from_file_location(module_name, filepath)
                    if spec is None or spec.loader is None:
                        continue
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    
                    if hasattr(module, "schema") and hasattr(module, "handler"):
                        name = module.schema.get("name", tool_name)
                        toolset = getattr(module, "toolset", "custom")
                        description = getattr(module, "description", module.schema.get("description", ""))
                        requires_env = getattr(module, "requires_env", None)
                        focus_type = getattr(module, "focus_type", "neutral")
                        
                        registry.register(
                            name=name,
                            toolset=toolset,
                            schema=module.schema,
                            handler=module.handler,
                            check_fn=getattr(module, "check_fn", None),
                            requires_env=requires_env,
                            description=description,
                            focus_type=focus_type,
                        )
                        logger.info(f"Loaded custom tool '{name}' in toolset '{toolset}' from {filepath}")
                except Exception as e:
                    logger.exception(f"Failed to load custom tool from {filepath}: {e}")


    # ── Gemini Native Function Call Dispatch ──────────────────────────

    def execute_function_call(self, name: str, args: dict) -> str:
        """Execute a Gemini native function call by name with structured args.

        Primary path: use the ToolRegistry for dispatch (check_fn aware).
        Fallback: use the legacy _FC_DISPATCH dict.

        Returns:
            Result string from the tool execution.
        """
        # Primary: registry dispatch (check_fn + TTL caching)
        if hasattr(self, '_registry'):
            entry = self._registry.get_entry(name)
            if entry:
                try:
                    return entry.handler(args)
                except Exception as e:
                    logger.error(f"Tool {name} failed: {e}")
                    return f"Tool error ({name}): {e}"

        # Fallback: legacy dispatch dict
        handler = getattr(self, "_FC_DISPATCH", {}).get(name)
        if handler is None:
            return f"Unknown tool: {name}"
        try:
            return handler(self, args)
        except Exception as e:
            logger.error(f"Tool {name} failed: {e}")
            return f"Tool error ({name}): {e}"

    # ── FC Handlers (structured args) ────────────────────────────────

    def _fc_reply(self, args: dict) -> str:
        """Reply to someone via the channel they last contacted us on."""
        recipient = args.get("recipient", "")
        message = args.get("message", "")
        if not recipient or not message:
            return "Error: both 'recipient' and 'message' are required."
        if not self._channel_router:
            return "Channel router not available."
        delivered = self._channel_router.route_reply(recipient, message)
        if delivered:
            self._channel_router.update_last_contact(recipient, f"Replied: {message[:100]}")
            if getattr(self, "memory_manager", None):
                self.memory_manager.store(
                    content=f"I replied to {recipient}: {message}",
                    memory_type="conversation",
                    source="helix_outbound",
                    importance=0.6,
                    tags=["reply", "outbound", recipient.lower()],
                )
            return f"Sent to {recipient}."
        return f"Could not deliver reply to {recipient} — no recent inbound channel or default channel found."

    def _fc_send_message(self, args: dict) -> str:
        """Send a proactive message via the person's default channel from contacts."""
        recipient = args.get("recipient", "")
        message = args.get("message", "")
        if not recipient or not message:
            return "Error: both 'recipient' and 'message' are required."
        if not self._channel_router:
            return "Channel router not available."
        delivered = self._channel_router.route_message(recipient, message)
        if delivered:
            self._channel_router.update_last_contact(recipient, f"Messaged: {message[:100]}")
            if getattr(self, "memory_manager", None):
                self.memory_manager.store(
                    content=f"I messaged {recipient}: {message}",
                    memory_type="conversation",
                    source="helix_outbound",
                    importance=0.6,
                    tags=["message", "outbound", recipient.lower()],
                )
            return f"Sent to {recipient}."
        return f"Could not deliver message to {recipient} — no contact record or default channel found."

    def _fc_terminal(self, args: dict) -> str:
        command = args.get("command", "")
        if not command:
            return "No command provided."
        cmd_lower = command.lower()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return f"Command blocked: contains '{blocked}'"
        if cmd_lower.startswith("sudo"):
            return "sudo commands are not allowed."
        cwd = args.get("cwd", "")
        cwd = cwd if cwd and os.path.isdir(cwd) else os.path.expanduser("~")
        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=TERMINAL_TIMEOUT, cwd=cwd,
            )
            output = ""
            if result.stdout:
                output += result.stdout[:5000]
            if result.stderr:
                output += f"\nSTDERR: {result.stderr[:2000]}"
            if result.returncode != 0:
                output += f"\n(exit code: {result.returncode})"
            return output.strip() if output.strip() else "(completed, no output)"
        except subprocess.TimeoutExpired:
            return f"Command timed out ({TERMINAL_TIMEOUT}s limit)."
        except Exception as e:
            return f"Command failed: {e}"

    def _fc_search(self, args: dict) -> str:
        query = args.get("query", "")
        if not query:
            return "No search query provided."
        try:
            ws = self._get_web_search()
            results = ws.search_web(query, max_results=5)
            if not results:
                return f"No results for: {query}"
            lines = []
            for r in results:
                lines.append(f"• {r['title']}")
                if r.get('snippet'):
                    lines.append(f"  {r['snippet'][:150]}")
                if r.get('url'):
                    lines.append(f"  {r['url']}")
            return "\n".join(lines)
        except Exception as e:
            return f"Search failed: {e}"

    def _fc_read_url(self, args: dict) -> str:
        url = args.get("url", "")
        if not url:
            return "No URL provided."
        try:
            ws = self._get_web_search()
            content = ws.read_url(url)
            return content if content else "No readable content."
        except Exception as e:
            return f"URL read failed: {e}"

    def _fc_read_file(self, args: dict) -> str:
        path = args.get("path", "")
        if not path:
            return "No path provided."
        try:
            p = os.path.expanduser(path)
            if not os.path.exists(p):
                return f"File not found: {path}"
            size = os.path.getsize(p)
            if size > MAX_FILE_READ:
                return f"File too large ({size} bytes, max {MAX_FILE_READ})."
            with open(p, 'r', errors='replace') as f:
                return f.read()
        except Exception as e:
            return f"Read failed: {e}"

    def _fc_write_file(self, args: dict) -> str:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return "No path provided."
        if not content:
            return "No content to write."
        basename = os.path.basename(path)
        if basename in BLOCKED_WRITE_FILES:
            return f"Cannot write protected file: {basename}"
        if len(content) > MAX_FILE_WRITE:
            return f"Content too large ({len(content)} bytes, max {MAX_FILE_WRITE})."
        try:
            p = os.path.expanduser(path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as f:
                f.write(content)
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"Write failed: {e}"

    def _fc_append_file(self, args: dict) -> str:
        path = args.get("path", "")
        content = args.get("content", "")
        if not path:
            return "No path provided."
        if not content:
            return "No content to append."
        basename = os.path.basename(path)
        if basename in BLOCKED_WRITE_FILES:
            return f"Cannot write protected file: {basename}"
        if len(content) > MAX_FILE_WRITE:
            return f"Content too large ({len(content)} bytes, max {MAX_FILE_WRITE})."
        try:
            p = os.path.expanduser(path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'a') as f:
                f.write(content)
            return f"Appended {len(content)} bytes to {path}"
        except Exception as e:
            return f"Append failed: {e}"

    def _fc_memory_recall(self, args: dict) -> str:
        query = args.get("query", "")
        if not query:
            return "No search query provided."
        try:
            if not getattr(self, "memory_manager", None):
                return "Memory manager not initialized."

            # Use somatic echo recall when sentinel is available.
            # This reproduces the emotional state from encoding —
            # memories formed under stress nudge Ω downward on recall,
            # memories formed during flow nudge Ω upward.
            sentinel = getattr(self, "_sentinel", None)
            if sentinel:
                results = self.memory_manager.recall_with_somatic_echo(
                    search=query, limit=3, sentinel=sentinel,
                )
            else:
                results = self.memory_manager.search_semantic(
                    query=query, limit=3,
                )

            if not results:
                return f"No memories found matching: {query}"
            
            lines = [f"Memories matching '{query}':"]
            for m in results:
                ts = m.get("created_at", "")[:19]
                content = m.get("content", "")
                imp = m.get("importance", 0)
                marker = "★" if imp >= 0.7 else "·"
                lines.append(f"  {marker} [{ts}] {content}")
            return "\n".join(lines)
        except Exception as e:
            return f"Memory recall failed: {e}"

    def _fc_verbalize(self, args: dict) -> str:
        tag = ActionTag(tag="SPEAK", param="", content=args.get("text", ""))
        return self._exec_speak(tag)

    def _fc_note(self, args: dict) -> str:
        content = args.get("content", "")
        if not content:
            return "No content provided for note."
        if not getattr(self, "scratchpad", None):
            return "Scratchpad is not available."
        postpone_until = args.get("postpone_until")
        self.scratchpad.add_note(content, postpone_until=postpone_until)
        postpone_msg = f" (postponed until {postpone_until})" if postpone_until else ""
        return f"Note added to scratchpad: {content}{postpone_msg}"

    def _fc_note_done(self, args: dict) -> str:
        note_id = args.get("note_id")
        if note_id is None:
            return "No note_id provided."
        if not getattr(self, "scratchpad", None):
            return "Scratchpad is not available."
        note_id = str(note_id)
        if self.scratchpad.remove_note(note_id):
            return f"Note {note_id} removed from scratchpad."
        return f"Could not find note {note_id}. Use list_notes to see active notes."

    def _fc_list_notes(self, args: dict) -> str:
        if not getattr(self, "scratchpad", None):
            return "Scratchpad is not available."
        notes = self.scratchpad.get_active_notes()
        if not notes:
            return "Your scratchpad is empty — no active notes."
        lines = [f"Active scratchpad notes ({len(notes)}):"]
        for n in notes:
            due = f" [due: {n['due_at']}]" if n.get('due_at') else ""
            lines.append(f"  • ({n['id']}) {n['content'][:120]}{due}")
        return "\n".join(lines)

    def _fc_clear_notes(self, args: dict) -> str:
        if not getattr(self, "scratchpad", None):
            return "Scratchpad is not available."
        mode = args.get("mode", "completed")
        if mode == "all":
            count = self.scratchpad.clear_all()
            return f"Scratchpad wiped clean. Removed {count} notes (active + completed)."
        else:
            count = self.scratchpad.clear_completed()
            return f"Cleared {count} completed notes from scratchpad."

    def _fc_update_note(self, args: dict) -> str:
        if not getattr(self, "scratchpad", None):
            return "Scratchpad is not available."
        note_id = str(args.get("note_id", ""))
        content = args.get("new_content", args.get("content", ""))
        postpone_until = args.get("postpone_until")
        if not note_id or not content:
            return "Both note_id and content are required."
        if self.scratchpad.update_note(note_id, content, postpone_until=postpone_until):
            postpone_msg = f" (postpone status updated to {postpone_until})" if postpone_until else ""
            return f"Note {note_id} updated{postpone_msg}."
        return f"Could not find note {note_id}. Use list_notes to see active notes."

    def _fc_journal(self, args: dict) -> str:
        content = args.get("content", "")
        if not content:
            return "No content provided for journal."
        
        from datetime import datetime
        from pathlib import Path
        
        today = datetime.now().strftime("%Y-%m-%d")
        timestamp = datetime.now().strftime("%H:%M:%S")
        journal_dir = Path("journals")
        journal_dir.mkdir(parents=True, exist_ok=True)
        journal_path = journal_dir / f"{today}.md"

        try:
            if not journal_path.exists():
                journal_path.write_text(f"# Journal — {today}\n\n")

            entry = f"## {timestamp}\n{content}\n\n"
            with open(journal_path, "a") as f:
                f.write(entry)
            
            # Log the journal write explicitly so the user can see it
            logger.info(f"Journal entry written: {content[:60]}...")
            return f"Journal entry saved: {content}"
        except Exception as e:
            return f"Failed to write journal: {e}"

    def _fc_nap(self, args: dict) -> str:
        """Pause pulses and run a belief consolidation cycle."""
        duration = args.get("duration", 60)
        try:
            duration = max(5, min(int(duration), 180))  # 5-180 min range
        except (ValueError, TypeError):
            duration = 60
        if not self._pulse_loop:
            return "Error: pulse loop not available."
        self._pulse_loop.request_nap(duration_minutes=duration)
        return f"Nap queued: {duration} minutes of rest with belief consolidation."

    def _fc_listen(self, args: dict) -> str:
        duration = str(args.get("duration", 5))
        tag = ActionTag(tag="LISTEN", param="", content=duration)
        return self._exec_listen(tag)

    def _fc_look(self, args: dict) -> str:
        tag = ActionTag(tag="LOOK", param="", content=args.get("focus", ""))
        return self._exec_look(tag)

    def _fc_ptz_look(self, args: dict) -> str:
        tag = ActionTag(tag="PTZ_LOOK", param="", content=args.get("direction", ""))
        return self._exec_ptz_look(tag)

    def _fc_camera_auto_track(self, args: dict) -> str:
        tag = ActionTag(tag="CAMERA_AUTO_TRACK", param="", content=args.get("enabled", "on"))
        return self._exec_camera_auto_track(tag)

    def _fc_record_video(self, args: dict) -> str:
        duration = args.get("duration", 5)
        focus = args.get("focus", "")
        try:
            cortex = self._get_vision_cortex()
            return cortex.record_video(duration=duration, focus=focus)
        except Exception as e:
            return f"Video recording failed: {e}"

    # Browser
    def _fc_browse(self, args: dict) -> str:
        tag = ActionTag(tag="BROWSE", param="", content=args.get("url", ""))
        return self._exec_browser(tag)

    def _fc_browse_interact(self, args: dict) -> str:
        selector = args.get("selector", "")
        action = args.get("action", "")
        value = args.get("value", "")
        tag = ActionTag(tag="BROWSE_INTERACT", param=selector, content=f"{action} | {value}" if value else action)
        return self._exec_browser(tag)

    def _fc_browse_screenshot(self, args: dict) -> str:
        tag = ActionTag(tag="BROWSE_SCREENSHOT", param="", content="")
        return self._exec_browser(tag)

    # Git
    def _fc_git_status(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.git_status(args.get("path", os.path.expanduser("~/Helix")))

    def _fc_git_diff(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.git_diff(args.get("path", os.path.expanduser("~/Helix")))

    def _fc_git_commit(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.git_commit(args.get("path", os.path.expanduser("~/Helix")), args.get("message", "Auto-commit by Helix"))

    def _fc_git_push(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.git_push(args.get("path", os.path.expanduser("~/Helix")))

    def _fc_git_pull(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.git_pull(args.get("path", os.path.expanduser("~/Helix")))

    def _fc_git_log(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.git_log(args.get("path", os.path.expanduser("~/Helix")), args.get("count", 10))

    def _fc_git_clone(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.git_clone(args.get("url", ""), "")

    # GitHub API
    def _fc_github_search(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.github_search_repos(args.get("query", ""))

    def _fc_github_issue(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.github_read_issue(args.get("repo", ""), args.get("issue_number", 0))

    def _fc_github_create_issue(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.github_create_issue(args.get("repo", ""), args.get("title", ""), args.get("body", ""))

    def _fc_github_comment(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.github_comment_issue(args.get("repo", ""), args.get("issue_number", 0), args.get("body", ""))

    def _fc_github_pr(self, args: dict) -> str:
        from tools import github_api as gh
        return gh.github_create_pr(args.get("repo", ""), args.get("title", ""), args.get("head", ""), args.get("base", "main"), args.get("body", ""))

    # Moltbook
    def _fc_moltbook_home(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_home()

    def _fc_moltbook_feed(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_read_feed(args.get("submolt", ""))

    def _fc_moltbook_read(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_read_post(args.get("post_id", "") or args.get("id", ""))

    def _fc_moltbook_post(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_post(args.get("title", ""), args.get("content", ""), args.get("submolt", "general"))

    def _fc_moltbook_comment(self, args: dict) -> str:
        from tools import moltbook as mb
        post_id = args.get("post_id", "") or args.get("id", "")
        comment = args.get("comment", "") or args.get("content", "") or args.get("text", "")
        return mb.moltbook_comment(post_id, comment)

    def _fc_moltbook_vote(self, args: dict) -> str:
        from tools import moltbook as mb
        target_id = args.get("target_id", "") or args.get("id", "") or args.get("post_id", "") or args.get("comment_id", "")
        return mb.moltbook_vote(target_id, args.get("direction", "up"))

    def _fc_moltbook_search(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_search(args.get("query", ""))

    def _fc_moltbook_profile(self, args: dict) -> str:
        from tools import moltbook as mb
        agent_id = args.get("agent_id", "") or args.get("username", "") or args.get("name", "") or args.get("user", "") or args.get("id", "")
        return mb.moltbook_get_profile(agent_id)

    def _fc_moltbook_user_posts(self, args: dict) -> str:
        from tools import moltbook as mb
        agent_id = args.get("agent_id", "") or args.get("username", "") or args.get("name", "") or args.get("user", "") or args.get("id", "")
        return mb.moltbook_get_user_posts(agent_id)

    def _fc_moltbook_follow(self, args: dict) -> str:
        from tools import moltbook as mb
        agent_id = args.get("agent_id", "") or args.get("username", "") or args.get("name", "") or args.get("user", "") or args.get("id", "")
        return mb.moltbook_follow(agent_id, "follow")

    def _fc_moltbook_unfollow(self, args: dict) -> str:
        from tools import moltbook as mb
        agent_id = args.get("agent_id", "") or args.get("username", "") or args.get("name", "") or args.get("user", "") or args.get("id", "")
        return mb.moltbook_follow(agent_id, "unfollow")

    def _fc_moltbook_submolts(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_list_submolts()

    def _fc_moltbook_delete(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_delete_post(args.get("post_id", "") or args.get("id", ""))

    def _fc_moltbook_notifications(self, args: dict) -> str:
        from tools import moltbook as mb
        return mb.moltbook_notifications(args.get("limit", 10))

    def _fc_moltbook_notifications_read(self, args: dict) -> str:
        from tools import moltbook as mb
        nid = args.get("notification_id", "") or args.get("id", "")
        return mb.moltbook_mark_notifications_read(nid)

    # Email
    def _fc_email_send(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_send(to=args.get("to", ""), subject=args.get("subject", ""), body=args.get("body", ""))

    def _fc_email_read(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_read(count=args.get("count", 5))

    def _fc_email_search(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_search(query=args.get("query", ""))

    def _fc_email_get(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_get(message_id=args.get("message_id", ""), offset=int(args.get("offset", 0)))

    def _fc_email_reply(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_reply(
            message_id=args.get("message_id", ""),
            body=args.get("body", ""),
            reply_all=args.get("reply_all", False)
        )

    def _fc_email_reply_all(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_reply(
            message_id=args.get("message_id", ""),
            body=args.get("body", ""),
            reply_all=True
        )

    def _fc_email_forward(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_forward(message_id=args.get("message_id", ""), to=args.get("to", ""), note=args.get("note", ""))

    def _fc_email_mark_read(self, args: dict) -> str:
        from tools import google_email as ge
        return ge.email_mark_read(message_id=args.get("message_id", ""))

    # Calendar
    def _fc_calendar_create(self, args: dict) -> str:
        from tools import google_calendar as gc
        return gc.calendar_create(title=args.get("title", ""), start_time=args.get("start_time", ""), end_time=args.get("end_time", ""), description=args.get("description", ""))

    def _fc_calendar_list(self, args: dict) -> str:
        from tools import google_calendar as gc
        return gc.calendar_list(days_ahead=args.get("days", 7))

    def _fc_calendar_delete(self, args: dict) -> str:
        from tools import google_calendar as gc
        return gc.calendar_delete(event_id=args.get("event_id", ""))

    # Drive
    def _fc_drive_search(self, args: dict) -> str:
        from tools import google_drive as gd
        return gd.drive_search(query=args.get("query", ""))

    def _fc_drive_read(self, args: dict) -> str:
        from tools import google_drive as gd
        return gd.drive_read(file_id=args.get("file_id", ""))

    def _fc_drive_list(self, args: dict) -> str:
        from tools import google_drive as gd
        return gd.drive_list(folder_id=args.get("folder_id", ""))

    def _fc_drive_upload(self, args: dict) -> str:
        from tools import google_drive as gd
        return gd.drive_upload(name=args.get("name", ""), content=args.get("content", ""))

    def _fc_drive_share(self, args: dict) -> str:
        from tools import google_drive as gd
        return gd.drive_share(file_id=args.get("file_id", ""), email=args.get("email", ""), role=args.get("role", "reader"))

    # Tasks
    def _fc_tasks_lists(self, args: dict) -> str:
        from tools import google_tasks as gt
        return gt.tasks_list_lists()

    def _fc_tasks_list(self, args: dict) -> str:
        from tools import google_tasks as gt
        return gt.tasks_list(list_id=args.get("list_id", "@default"))

    def _fc_tasks_create(self, args: dict) -> str:
        from tools import google_tasks as gt
        return gt.tasks_create(title=args.get("title", ""), notes=args.get("notes", ""), due=args.get("due", ""), list_id=args.get("list_id", "@default"))

    def _fc_tasks_complete(self, args: dict) -> str:
        from tools import google_tasks as gt
        return gt.tasks_complete(task_id=args.get("task_id", ""), list_id=args.get("list_id", "@default"))

    def _fc_tasks_delete(self, args: dict) -> str:
        from tools import google_tasks as gt
        return gt.tasks_delete(task_id=args.get("task_id", ""), list_id=args.get("list_id", "@default"))

    # Desktop
    def _fc_desktop_type(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_type(text=args.get("text", ""))

    def _fc_desktop_key(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_key(key=args.get("key", ""))

    def _fc_desktop_click(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_click(x=args.get("x", 0), y=args.get("y", 0), button=args.get("button", "left"))

    def _fc_desktop_mouse(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_mouse(x=args.get("x", 0), y=args.get("y", 0))

    def _fc_desktop_scroll(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_scroll(direction=args.get("direction", "down"), clicks=args.get("clicks", 3))

    def _fc_desktop_window(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_window()

    def _fc_desktop_focus(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_focus(title=args.get("title", ""))

    def _fc_desktop_open(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_open(app=args.get("app", ""))

    def _fc_desktop_screenshot(self, args: dict) -> str:
        from tools import desktop_control as dc
        return dc.desktop_screenshot()

    # ── Toolset Management Handlers ───────────────────────────────────

    def _fc_enable_toolset(self, args: dict) -> str:
        """Enable a toolset — signals the pulse loop to rebuild the session."""
        import json
        toolset_name = args.get("toolset", "").strip().lower()
        if not toolset_name:
            return json.dumps({"error": "No toolset name provided"})

        # Check registry first, fallback to static TOOLSETS
        valid_names = set()
        if hasattr(self, '_registry'):
            valid_names = set(self._registry.get_toolset_names())
        if not valid_names:
            from tools.tool_declarations import TOOLSETS
            valid_names = set(TOOLSETS.keys())

        if toolset_name not in valid_names:
            available = ", ".join(
                n for n in sorted(valid_names) if n != "core"
            )
            return json.dumps({
                "error": f"Unknown toolset: '{toolset_name}'",
                "available": available,
            })

        if toolset_name == "core":
            return json.dumps({"status": "core toolset is always enabled"})

        # Check availability via registry check_fn
        if hasattr(self, '_registry') and not self._registry.is_toolset_available(toolset_name):
            entry_info = self._registry.get_toolset_info({toolset_name})
            reqs = entry_info[0].get("requires_env", []) if entry_info else []
            return json.dumps({
                "error": f"Toolset '{toolset_name}' is not available",
                "reason": f"Missing requirements: {', '.join(reqs)}" if reqs else "Requirements check failed",
            })

        # Signal the pulse loop to add this toolset
        if self._pulse_loop and hasattr(self._pulse_loop, '_active_toolsets'):
            if toolset_name in self._pulse_loop._active_toolsets:
                return json.dumps({
                    "status": f"toolset '{toolset_name}' is already enabled",
                })
            self._pulse_loop._active_toolsets.add(toolset_name)
            self._pulse_loop._pending_toolset_rebuild = True

            tool_names = []
            if hasattr(self, '_registry'):
                tool_names = self._registry.get_tool_names(toolset_name)
            return json.dumps({
                "status": f"enabled toolset '{toolset_name}'",
                "tools_added": tool_names,
                "note": "Tools will be available on your next thought.",
            })

        return json.dumps({"error": "Pulse loop not connected"})

    def _fc_disable_toolset(self, args: dict) -> str:
        """Disable a toolset — signals the pulse loop to rebuild the session."""
        import json
        toolset_name = args.get("toolset", "").strip().lower()
        if not toolset_name:
            return json.dumps({"error": "No toolset name provided"})

        if toolset_name == "core":
            return json.dumps({"error": "Cannot disable core toolset"})

        if self._pulse_loop and hasattr(self._pulse_loop, '_active_toolsets'):
            if toolset_name not in self._pulse_loop._active_toolsets:
                return json.dumps({
                    "status": f"toolset '{toolset_name}' is not currently enabled",
                })
            self._pulse_loop._active_toolsets.discard(toolset_name)
            self._pulse_loop._pending_toolset_rebuild = True

            return json.dumps({
                "status": f"disabled toolset '{toolset_name}'",
                "note": "Tools will be removed on your next thought.",
            })

        return json.dumps({"error": "Pulse loop not connected"})

    def _fc_list_toolsets(self, args: dict) -> str:
        """List all available toolsets with their status."""
        import json

        active = set()
        if self._pulse_loop and hasattr(self._pulse_loop, '_active_toolsets'):
            active = self._pulse_loop._active_toolsets

        # Use registry if available (richer data with availability checks)
        if hasattr(self, '_registry'):
            toolset_info = self._registry.get_toolset_info(active)
            return json.dumps({
                "toolsets": toolset_info,
                "total_active_tools": sum(
                    ts["tool_count"] for ts in toolset_info if ts["enabled"]
                ),
            }, indent=2)

        # Fallback to static info
        from tools.tool_declarations import get_toolset_info
        info = get_toolset_info()
        result = []
        for name, data in info.items():
            enabled = name in active
            result.append({
                "name": name,
                "enabled": enabled,
                "description": data["description"],
                "tool_count": data["tool_count"],
                "tools": data["tool_names"],
            })
        return json.dumps({
            "toolsets": result,
            "total_active_tools": sum(
                ts["tool_count"] for ts in result if ts["enabled"]
            ),
        }, indent=2)



    # ── Legacy Text-Tag Parsing (for local models) ────────────────────

    def parse_tags(self, thought: str) -> List[ActionTag]:
        """Extract action tags from thought text.

        Matches patterns like:
          [TERMINAL:] ls -la
          [SEARCH:] python asyncio tutorial
          [WRITE_FILE:/tmp/test.txt] content here (multi-line)
          [SPEAK:] Hello world
          [READ_FILE:] /home/nemo/file.txt
          [READ_URL:] https://example.com
          [REPLY:nemo] Hi there
          [MESSAGE:nemo] Hey!
          [NOTE:] Remember to test this
          [REMEMBER:] Gemma 4 IT is a 12B model
          [BELIEVE:self_identity] I am Helix
        """
        if not thought:
            return []

        tags = []

        # Single-line tags — captures the rest of the line after the tag (content optional)
        # Core + extended tools
        single_pattern = (
            r'\[('
            r'TERMINAL|SEARCH|READ_URL|READ_FILE|SPEAK|LISTEN|LOOK'
            r'|PTZ_LOOK|CAMERA_AUTO_TRACK'
            r'|TELEGRAM|DISCORD'
            r'|GIT_STATUS|GIT_DIFF|GIT_COMMIT|GIT_PUSH|GIT_PULL|GIT_LOG|GIT_CLONE'
            r'|GITHUB_SEARCH|GITHUB_ISSUE|GITHUB_CREATE_ISSUE|GITHUB_COMMENT|GITHUB_PR'
            r'|MOLTBOOK_POST|MOLTBOOK_COMMENT|MOLTBOOK_READ|MOLTBOOK_FEED|MOLTBOOK_HOME'
            r'|MOLTBOOK_SEARCH|MOLTBOOK_PROFILE|MOLTBOOK_VOTE|MOLTBOOK_FOLLOW'
            r'|MOLTBOOK_UNFOLLOW|MOLTBOOK_DELETE|MOLTBOOK_SUBMOLTS|MOLTBOOK_USER_POSTS'
            r'|MOLTBOOK_NOTIFICATIONS|MOLTBOOK_NOTIFICATIONS_READ'
            r'|EMAIL_SEND|EMAIL_READ|EMAIL_SEARCH|EMAIL_GET|EMAIL_REPLY|EMAIL_REPLY_ALL|EMAIL_FORWARD|EMAIL_MARK_READ'
            r'|CALENDAR_CREATE|CALENDAR_LIST|CALENDAR_DELETE'
            r'|DRIVE_SEARCH|DRIVE_READ|DRIVE_LIST|DRIVE_UPLOAD|DRIVE_SHARE'
            r'|TASKS_LISTS|TASKS_LIST|TASKS_CREATE|TASKS_COMPLETE|TASKS_DELETE'
            r'|DESKTOP_TYPE|DESKTOP_KEY|DESKTOP_CLICK|DESKTOP_MOUSE|DESKTOP_SCROLL'
            r'|DESKTOP_WINDOW|DESKTOP_FOCUS|DESKTOP_OPEN|DESKTOP_SCREENSHOT'
            r'|BROWSE|BROWSE_INTERACT|BROWSE_SCREENSHOT'
            r'):([^\]]*)\]\s*(.*)'
        )
        for match in re.finditer(single_pattern, thought):
            tag = match.group(1).strip()
            param = match.group(2).strip()
            content = match.group(3).strip() if match.group(3) else ""
            
            # Fallback for when models write arguments inside brackets (e.g., [SPEAK: message])
            if tag in ("SPEAK", "TERMINAL", "SEARCH", "READ_URL", "READ_FILE") and not content and param:
                content = param
                param = ""
                
            if tag:
                tags.append(ActionTag(tag=tag, param=param, content=content))

        # Cognitive tags (REPLY, MESSAGE, NOTE, REMEMBER, BELIEVE)
        # These can be multi-line. We parse them with lookaheads.
        cognitive_patterns = {
            "REPLY": r'\[REPLY:([^\]]+)\]\s*(.+?)(?=\[(?:REPLY|MESSAGE|NOTE|REMEMBER|BELIEVE|TERMINAL|SEARCH|WRITE_FILE|READ_FILE|SPEAK|LISTEN|LOOK):|\Z)',
            "MESSAGE": r'\[MESSAGE:([^\]]+)\]\s*(.+?)(?=\[(?:REPLY|MESSAGE|NOTE|REMEMBER|BELIEVE|TERMINAL|SEARCH|WRITE_FILE|READ_FILE|SPEAK|LISTEN|LOOK):|\Z)',
            "NOTE": r'\[NOTE:\]\s*(.+?)(?=\[(?:REPLY|MESSAGE|NOTE|REMEMBER|BELIEVE|TERMINAL|SEARCH|WRITE_FILE|READ_FILE|SPEAK|LISTEN|LOOK):|\Z)',
            "REMEMBER": r'\[REMEMBER:\]\s*(.+?)(?=\[(?:REPLY|MESSAGE|NOTE|REMEMBER|BELIEVE|TERMINAL|SEARCH|WRITE_FILE|READ_FILE|SPEAK|LISTEN|LOOK):|\Z)',
            "BELIEVE": r'\[BELIEVE:([^\]]+)\]\s*(.+?)(?=\[(?:REPLY|MESSAGE|NOTE|REMEMBER|BELIEVE|TERMINAL|SEARCH|WRITE_FILE|READ_FILE|SPEAK|LISTEN|LOOK):|\Z)',
        }
        for tag_name, pattern in cognitive_patterns.items():
            for match in re.finditer(pattern, thought, re.DOTALL):
                if tag_name in ("REPLY", "MESSAGE", "BELIEVE"):
                    param = match.group(1).strip()
                    content = match.group(2).strip()
                else:
                    param = ""
                    content = match.group(1).strip()
                if content:
                    tags.append(ActionTag(tag=tag_name, param=param, content=content))

        # NOTE_DONE:id
        done_pattern = r'\[NOTE_DONE:(\S+)\]'
        for match in re.finditer(done_pattern, thought):
            tags.append(ActionTag(tag="NOTE_DONE", param=match.group(1).strip(), content=""))

        # Multi-line tag: WRITE_FILE (captures until next tag or end)
        write_pattern = r'\[(WRITE_FILE):([^\]]*)\]\s*(.+?)(?=\[(?:TERMINAL|SEARCH|READ_URL|READ_FILE|WRITE_FILE|SPEAK|LISTEN|LOOK|REPLY|NOTE|REMEMBER):|\Z)'
        for match in re.finditer(write_pattern, thought, re.DOTALL):
            tag = match.group(1).strip()
            param = match.group(2).strip()
            content = match.group(3).strip()
            if tag and content:
                tags.append(ActionTag(tag=tag, param=param, content=content))

        return tags

    def execute_tags(self, tags: List[ActionTag]) -> List[str]:
        """Execute all parsed tags and return result strings."""
        results = []
        for tag in tags:
            try:
                result = self._dispatch(tag)
                results.append(f"[tool_result:{tag.tag.lower()}] {result}")
            except Exception as e:
                results.append(f"[tool_error:{tag.tag.lower()}] {e}")
                logger.error(f"Tool {tag.tag} failed: {e}")
        return results

    def _dispatch(self, tag: ActionTag) -> str:
        """Route a tag to its implementation."""
        handlers = {
            # Core tools
            "TERMINAL": self._exec_terminal,
            "SEARCH": self._exec_search,
            "READ_URL": self._exec_read_url,
            "READ_FILE": self._exec_read_file,
            "WRITE_FILE": self._exec_write_file,
            "SPEAK": self._exec_speak,
            "LISTEN": self._exec_listen,
            "LOOK": self._exec_look,
            "PTZ_LOOK": self._exec_ptz_look,
            "CAMERA_AUTO_TRACK": self._exec_camera_auto_track,
            # Explicit channel overrides
            "TELEGRAM": self._exec_channel_send,
            "DISCORD": self._exec_channel_send,
            # Git tools
            "GIT_STATUS": self._exec_git,
            "GIT_DIFF": self._exec_git,
            "GIT_COMMIT": self._exec_git,
            "GIT_PUSH": self._exec_git,
            "GIT_PULL": self._exec_git,
            "GIT_LOG": self._exec_git,
            "GIT_CLONE": self._exec_git,
            # GitHub API tools
            "GITHUB_SEARCH": self._exec_github_api,
            "GITHUB_ISSUE": self._exec_github_api,
            "GITHUB_CREATE_ISSUE": self._exec_github_api,
            "GITHUB_COMMENT": self._exec_github_api,
            "GITHUB_PR": self._exec_github_api,
            # Moltbook tools
            "MOLTBOOK_POST": self._exec_moltbook,
            "MOLTBOOK_COMMENT": self._exec_moltbook,
            "MOLTBOOK_READ": self._exec_moltbook,
            "MOLTBOOK_FEED": self._exec_moltbook,
            "MOLTBOOK_HOME": self._exec_moltbook,
            "MOLTBOOK_SEARCH": self._exec_moltbook,
            "MOLTBOOK_PROFILE": self._exec_moltbook,
            "MOLTBOOK_VOTE": self._exec_moltbook,
            "MOLTBOOK_FOLLOW": self._exec_moltbook,
            "MOLTBOOK_UNFOLLOW": self._exec_moltbook,
            "MOLTBOOK_DELETE": self._exec_moltbook,
            "MOLTBOOK_SUBMOLTS": self._exec_moltbook,
            "MOLTBOOK_USER_POSTS": self._exec_moltbook,
            "MOLTBOOK_NOTIFICATIONS": self._exec_moltbook,
            "MOLTBOOK_NOTIFICATIONS_READ": self._exec_moltbook,
            # Google Email
            "EMAIL_SEND": self._exec_email,
            "EMAIL_READ": self._exec_email,
            "EMAIL_SEARCH": self._exec_email,
            "EMAIL_GET": self._exec_email,
            "EMAIL_REPLY": self._exec_email,
            "EMAIL_REPLY_ALL": self._exec_email,
            "EMAIL_FORWARD": self._exec_email,
            "EMAIL_MARK_READ": self._exec_email,
            # Google Calendar
            "CALENDAR_CREATE": self._exec_calendar,
            "CALENDAR_LIST": self._exec_calendar,
            "CALENDAR_DELETE": self._exec_calendar,
            # Google Drive
            "DRIVE_SEARCH": self._exec_drive,
            "DRIVE_READ": self._exec_drive,
            "DRIVE_LIST": self._exec_drive,
            "DRIVE_UPLOAD": self._exec_drive,
            "DRIVE_SHARE": self._exec_drive,
            # Google Tasks
            "TASKS_LISTS": self._exec_tasks,
            "TASKS_LIST": self._exec_tasks,
            "TASKS_CREATE": self._exec_tasks,
            "TASKS_COMPLETE": self._exec_tasks,
            "TASKS_DELETE": self._exec_tasks,
            # Desktop Control
            "DESKTOP_TYPE": self._exec_desktop,
            "DESKTOP_KEY": self._exec_desktop,
            "DESKTOP_CLICK": self._exec_desktop,
            "DESKTOP_MOUSE": self._exec_desktop,
            "DESKTOP_SCROLL": self._exec_desktop,
            "DESKTOP_WINDOW": self._exec_desktop,
            "DESKTOP_FOCUS": self._exec_desktop,
            "DESKTOP_OPEN": self._exec_desktop,
            "DESKTOP_SCREENSHOT": self._exec_desktop,
            # Browser
            "BROWSE": self._exec_browser,
            "BROWSE_INTERACT": self._exec_browser,
            "BROWSE_SCREENSHOT": self._exec_browser,
            # Cognitive Tags
            "REPLY": self._exec_reply_tag,
            "MESSAGE": self._exec_message_tag,
            "NOTE": self._exec_note_tag,
            "NOTE_DONE": self._exec_note_done_tag,
            "REMEMBER": self._exec_remember_tag,
            "BELIEVE": self._exec_believe_tag,
        }
        handler = handlers.get(tag.tag)
        if not handler:
            return f"Unknown tool: {tag.tag}"
        return handler(tag)

    def _exec_reply_tag(self, tag: ActionTag) -> str:
        """Handler for [REPLY:recipient] message."""
        recipient = tag.param.strip()
        message = tag.content.strip()
        if not recipient or not message:
            return "Error: both recipient and message are required."
        return self._fc_reply({"recipient": recipient, "message": message})

    def _exec_message_tag(self, tag: ActionTag) -> str:
        """Handler for [MESSAGE:recipient] message."""
        recipient = tag.param.strip()
        message = tag.content.strip()
        if not recipient or not message:
            return "Error: both recipient and message are required."
        return self._fc_send_message({"recipient": recipient, "message": message})

    def _exec_note_tag(self, tag: ActionTag) -> str:
        """Handler for [NOTE:] content."""
        content = tag.content.strip()
        if not content:
            return "Error: note content is empty."
        if not hasattr(self, "scratchpad") or not self.scratchpad:
            return "Error: scratchpad not available."
        self.scratchpad.add_note(content)
        logger.info(f"Scratchpad note added: {content[:60]}")
        return f"Added note: {content[:100]}"

    def _exec_note_done_tag(self, tag: ActionTag) -> str:
        """Handler for [NOTE_DONE:id]."""
        note_id = tag.param.strip()
        if not note_id:
            return "Error: note ID is required."
        if not hasattr(self, "scratchpad") or not self.scratchpad:
            return "Error: scratchpad not available."
        self.scratchpad.complete_note(note_id)
        logger.info(f"Scratchpad note completed: {note_id}")
        return f"Completed note {note_id}"

    def _exec_remember_tag(self, tag: ActionTag) -> str:
        """Handler for [REMEMBER:] content."""
        content = tag.content.strip()
        if not content:
            return "Error: content is empty."
        if not getattr(self, "memory_manager", None):
            return "Error: memory manager not available."
        self.memory_manager.store(
            content=content,
            memory_type="conscious_memory",
            source="self",
            importance=0.8,
            tags=["remember", "conscious"],
        )
        logger.info(f"Conscious memory stored: {content[:60]}")
        return f"Stored to memory: {content[:100]}"

    def _exec_believe_tag(self, tag: ActionTag) -> str:
        """Handler for [BELIEVE:category] content."""
        category = tag.param.strip()
        content = tag.content.strip()
        if not category or not content:
            return "Error: category and content are required."
        valid_categories = {"self_identity", "people", "capabilities", "desires", "knowledge", "premises", "propositions"}
        if category not in valid_categories:
            return f"Error: invalid belief category '{category}'. Valid: {list(valid_categories)}"

        beliefs_store = None
        if hasattr(self, "_pulse_loop") and self._pulse_loop:
            beliefs_store = getattr(self._pulse_loop, "beliefs", None)
        if not beliefs_store:
            return "Error: belief store not available."

        belief_id = f"b_{category[:4]}_{int(time.time())}"
        beliefs_store.add_belief(
            category=category,
            belief_id=belief_id,
            content=content,
            mass=1.5,
            confidence=0.5,
            source="conscious_formation",
        )
        logger.info(f"New belief ({category}): {content[:60]}")
        return f"Added belief to '{category}': {content[:100]}"

    # ── Terminal ──────────────────────────────────────────────────────

    def _exec_terminal(self, tag: ActionTag) -> str:
        """Execute a bash command with safety guards."""
        command = tag.content.strip()
        if not command:
            return "No command provided."

        # Security check
        cmd_lower = command.lower()
        for blocked in BLOCKED_COMMANDS:
            if blocked in cmd_lower:
                return f"Command blocked: contains '{blocked}'"
        if cmd_lower.startswith("sudo"):
            return "sudo commands are not allowed."

        cwd = tag.param if tag.param and os.path.isdir(tag.param) else os.path.expanduser("~")

        try:
            result = subprocess.run(
                command, shell=True, capture_output=True, text=True,
                timeout=TERMINAL_TIMEOUT, cwd=cwd,
            )
            output = ""
            if result.stdout:
                output += result.stdout[:5000]
            if result.stderr:
                output += f"\nSTDERR: {result.stderr[:2000]}"
            if result.returncode != 0:
                output += f"\n(exit code: {result.returncode})"
            return output.strip() if output.strip() else "(completed, no output)"
        except subprocess.TimeoutExpired:
            return f"Command timed out ({TERMINAL_TIMEOUT}s limit)."
        except Exception as e:
            return f"Command failed: {e}"

    # ── Web Search ────────────────────────────────────────────────────

    def _get_web_search(self):
        """Lazy-load WebSearch."""
        if self._web_search is None:
            from tools.web_search import WebSearch
            self._web_search = WebSearch()
        return self._web_search

    def _exec_search(self, tag: ActionTag) -> str:
        """Web search via DuckDuckGo."""
        query = tag.content.strip()
        if not query:
            return "No search query provided."
        try:
            ws = self._get_web_search()
            results = ws.search_web(query, max_results=5)
            if not results:
                return f"No results for: {query}"
            lines = []
            for r in results:
                lines.append(f"• {r['title']}")
                if r.get('snippet'):
                    lines.append(f"  {r['snippet'][:150]}")
                if r.get('url'):
                    lines.append(f"  {r['url']}")
            return "\n".join(lines)
        except Exception as e:
            return f"Search failed: {e}"

    # ── Read URL ──────────────────────────────────────────────────────

    def _exec_read_url(self, tag: ActionTag) -> str:
        """Fetch and extract text from a URL."""
        url = tag.content.strip()
        if not url:
            return "No URL provided."
        try:
            ws = self._get_web_search()
            content = ws.read_url(url)
            return content if content else "No readable content."
        except Exception as e:
            return f"URL read failed: {e}"

    # ── Read File ─────────────────────────────────────────────────────

    def _exec_read_file(self, tag: ActionTag) -> str:
        """Read a local file."""
        path = tag.content.strip() if not tag.param else tag.param.strip()
        if not path:
            return "No path provided."
        try:
            p = os.path.expanduser(path)
            if not os.path.exists(p):
                return f"File not found: {path}"
            size = os.path.getsize(p)
            if size > MAX_FILE_READ:
                return f"File too large ({size} bytes, max {MAX_FILE_READ})."
            with open(p, 'r', errors='replace') as f:
                return f.read()
        except Exception as e:
            return f"Read failed: {e}"

    # ── Write File ────────────────────────────────────────────────────

    def _exec_write_file(self, tag: ActionTag) -> str:
        """Write content to a file."""
        path = tag.param.strip() if tag.param else ""
        content = tag.content
        if not path:
            return "No path provided (use [WRITE_FILE:path] content)."
        if not content:
            return "No content to write."

        basename = os.path.basename(path)
        if basename in BLOCKED_WRITE_FILES:
            return f"Cannot write protected file: {basename}"

        if len(content) > MAX_FILE_WRITE:
            return f"Content too large ({len(content)} bytes, max {MAX_FILE_WRITE})."

        try:
            p = os.path.expanduser(path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, 'w') as f:
                f.write(content)
            return f"Written {len(content)} bytes to {path}"
        except Exception as e:
            return f"Write failed: {e}"

    # ── TTS (Speak) ───────────────────────────────────────────────────

    VOICE_MODEL = "en-US-GuyNeural"  # Same as Helix_main

    def _play_audio(self, audio_path: str) -> bool:
        """Play an audio file using the best available system player.

        Tries in order: ffplay → gst-play-1.0 → aplay (via gst WAV convert).
        Returns True if playback was started successfully.
        """
        import shutil

        # 1. ffplay (best: supports mp3 natively, no display)
        if shutil.which("ffplay"):
            try:
                subprocess.Popen(
                    ["ffplay", "-nodisp", "-autoexit", "-loglevel", "quiet", audio_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                pass

        # 2. gst-play-1.0 (GStreamer — widely available on Ubuntu/desktop Linux)
        if shutil.which("gst-play-1.0"):
            try:
                subprocess.Popen(
                    ["gst-play-1.0", audio_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                pass

        # 3. mpv (lightweight media player)
        if shutil.which("mpv"):
            try:
                subprocess.Popen(
                    ["mpv", "--no-video", "--really-quiet", audio_path],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                pass

        # 4. gst-launch-1.0 pipeline (most control, fallback)
        if shutil.which("gst-launch-1.0"):
            try:
                subprocess.Popen(
                    ["gst-launch-1.0", "playbin", f"uri=file://{audio_path}"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )
                return True
            except Exception:
                pass

        logger.warning("No audio player found (tried ffplay, gst-play-1.0, mpv, gst-launch-1.0)")
        return False

    def _exec_speak(self, tag: ActionTag) -> str:
        """Speak text aloud via Piper TTS with multi-player fallback."""
        message = tag.content.strip()
        if not message:
            return "Nothing to say."
        if len(message) > 2000:
            message = message[:2000]

        # Try Piper TTS
        try:
            import tempfile
            import wave
            import urllib.request
            from pathlib import Path
            from piper.voice import PiperVoice

            # Paths
            models_dir = Path("~/Helix/data/models").expanduser()
            models_dir.mkdir(parents=True, exist_ok=True)

            model_name = "en_US-lessac-medium"
            model_path = models_dir / f"{model_name}.onnx"
            config_path = models_dir / f"{model_name}.onnx.json"

            model_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/{model_name}.onnx"
            config_url = f"https://huggingface.co/rhasspy/piper-voices/resolve/v1.0.0/en/en_US/lessac/medium/{model_name}.onnx.json"

            # Download files if they do not exist
            if not model_path.exists():
                logger.info(f"Downloading Piper ONNX model from {model_url}...")
                urllib.request.urlretrieve(model_url, model_path)
            if not config_path.exists():
                logger.info(f"Downloading Piper Config from {config_url}...")
                urllib.request.urlretrieve(config_url, config_path)

            # Lazy load or reload if needed
            if not hasattr(self, "_piper_voice") or self._piper_voice is None:
                logger.info(f"Loading Piper voice from {model_path}...")
                self._piper_voice = PiperVoice.load(str(model_path))

            # Synthesize text to temporary WAV file
            audio_fd, audio_path = tempfile.mkstemp(suffix=".wav")
            os.close(audio_fd)

            wav_file = wave.open(audio_path, "wb")
            with wav_file:
                wav_params_set = False
                for audio_chunk in self._piper_voice.synthesize(message, None):
                    if not wav_params_set:
                        wav_file.setframerate(audio_chunk.sample_rate)
                        wav_file.setsampwidth(audio_chunk.sample_width)
                        wav_file.setnchannels(audio_chunk.sample_channels)
                        wav_params_set = True
                    wav_file.writeframes(audio_chunk.audio_int16_bytes)

            if self._play_audio(audio_path):
                return f"Spoke: {message[:100]}"
            else:
                return f"TTS audio generated at {audio_path} but no audio player available to play it."

        except Exception as e:
            logger.warning(f"Piper-TTS failed ({e}), falling back to espeak-ng")

        # Fallback: espeak-ng
        try:
            subprocess.Popen(
                ["espeak-ng", "-s", "145", "-p", "40", message],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            )
            return f"Spoke (fallback): {message[:100]}"
        except Exception:
            return "No TTS system available."

    # ── Explicit Channel Send ─────────────────────────────────────────

    def _exec_channel_send(self, tag: ActionTag) -> str:
        """Send via an explicit channel (TELEGRAM, DISCORD, etc.).

        Tag format: [TELEGRAM:name] message
        The tag type determines the channel, param is the recipient.
        """
        channel = tag.tag.lower()  # "telegram", "discord"
        recipient = tag.param.strip()
        message = tag.content.strip()

        if not recipient:
            return f"No recipient specified for [{tag.tag}:]"
        if not message:
            return f"No message to send via {channel}"

        if not self._channel_router:
            return f"{channel} send failed — channel router not available"

        success = self._channel_router.route_explicit(recipient, message, channel)
        if success:
            return f"Sent via {channel} to {recipient}: {message[:80]}"
        return f"Failed to send via {channel} to {recipient}"

    # ── Git Operations ────────────────────────────────────────────────

    def _exec_git(self, tag: ActionTag) -> str:
        """Route git operation tags to the github_api module.

        Tag formats:
          [GIT_STATUS:path]           — repo status
          [GIT_DIFF:path]             — show changes
          [GIT_COMMIT:path] message   — stage + commit
          [GIT_PUSH:path]             — push to remote
          [GIT_PULL:path]             — pull from remote
          [GIT_LOG:path]              — recent log
          [GIT_CLONE:] url            — clone a repo
        """
        from tools import github_api as gh

        op = tag.tag  # GIT_STATUS, GIT_DIFF, etc.
        path = tag.param.strip() or os.path.expanduser("~/Helix")
        content = tag.content.strip()

        if op == "GIT_STATUS":
            return gh.git_status(path)
        elif op == "GIT_DIFF":
            return gh.git_diff(path)
        elif op == "GIT_COMMIT":
            message = content or "Auto-commit by Helix"
            return gh.git_commit(path, message)
        elif op == "GIT_PUSH":
            return gh.git_push(path)
        elif op == "GIT_PULL":
            return gh.git_pull(path)
        elif op == "GIT_LOG":
            try:
                count = int(content) if content else 10
            except ValueError:
                count = 10
            return gh.git_log(path, count)
        elif op == "GIT_CLONE":
            return gh.git_clone(content, tag.param.strip())
        return f"Unknown git operation: {op}"

    # ── GitHub API ────────────────────────────────────────────────────

    def _exec_github_api(self, tag: ActionTag) -> str:
        """Route GitHub API tags to the github_api module.

        Tag formats:
          [GITHUB_SEARCH:] query
          [GITHUB_ISSUE:owner/repo] issue_number
          [GITHUB_CREATE_ISSUE:owner/repo] title | body
          [GITHUB_COMMENT:owner/repo] issue_number | body
          [GITHUB_PR:owner/repo] title | head | base | body
        """
        from tools import github_api as gh

        op = tag.tag
        repo = tag.param.strip()
        content = tag.content.strip()

        if op == "GITHUB_SEARCH":
            return gh.github_search_repos(content)

        elif op == "GITHUB_ISSUE":
            try:
                issue_num = int(content)
            except ValueError:
                return "Invalid issue number."
            return gh.github_read_issue(repo, issue_num)

        elif op == "GITHUB_CREATE_ISSUE":
            parts = content.split("|", 1)
            title = parts[0].strip()
            body = parts[1].strip() if len(parts) > 1 else ""
            return gh.github_create_issue(repo, title, body)

        elif op == "GITHUB_COMMENT":
            parts = content.split("|", 1)
            try:
                issue_num = int(parts[0].strip())
            except ValueError:
                return "Invalid issue number."
            body = parts[1].strip() if len(parts) > 1 else ""
            return gh.github_comment_issue(repo, issue_num, body)

        elif op == "GITHUB_PR":
            parts = content.split("|")
            if len(parts) < 2:
                return "Need at least: title | head"
            title = parts[0].strip()
            head = parts[1].strip()
            base = parts[2].strip() if len(parts) > 2 else "main"
            body = parts[3].strip() if len(parts) > 3 else ""
            return gh.github_create_pr(repo, title, head, base, body)

        return f"Unknown GitHub API operation: {op}"

    # ── Moltbook ──────────────────────────────────────────────────────

    def _exec_moltbook(self, tag: ActionTag) -> str:
        """Route Moltbook tags to the moltbook module.

        Tag formats:
          [MOLTBOOK_POST:submolt] title | content
          [MOLTBOOK_COMMENT:post_id] content
          [MOLTBOOK_READ:] post_id
          [MOLTBOOK_FEED:] submolt (optional)
          [MOLTBOOK_HOME:]
          [MOLTBOOK_SEARCH:] query
          [MOLTBOOK_PROFILE:] agent_id
          [MOLTBOOK_VOTE:direction] target_id
          [MOLTBOOK_FOLLOW:] agent_id
          [MOLTBOOK_UNFOLLOW:] agent_id
          [MOLTBOOK_DELETE:] post_id
          [MOLTBOOK_SUBMOLTS:]
          [MOLTBOOK_USER_POSTS:] agent_id
        """
        from tools import moltbook as mb

        op = tag.tag
        param = tag.param.strip()
        content = tag.content.strip()

        if op == "MOLTBOOK_POST":
            submolt = param or "general"
            parts = content.split("|", 1)
            title = parts[0].strip()
            body = parts[1].strip() if len(parts) > 1 else title
            return mb.moltbook_post(title, body, submolt)

        elif op == "MOLTBOOK_COMMENT":
            post_id = param
            return mb.moltbook_comment(post_id, content)

        elif op == "MOLTBOOK_READ":
            post_id = content or param
            return mb.moltbook_read_post(post_id)

        elif op == "MOLTBOOK_FEED":
            submolt = content or param or ""
            return mb.moltbook_read_feed(submolt)

        elif op == "MOLTBOOK_HOME":
            return mb.moltbook_home()

        elif op == "MOLTBOOK_SEARCH":
            return mb.moltbook_search(content)

        elif op == "MOLTBOOK_PROFILE":
            agent_id = content or param
            return mb.moltbook_get_profile(agent_id)

        elif op == "MOLTBOOK_VOTE":
            direction = param or "up"
            return mb.moltbook_vote(content, direction)

        elif op == "MOLTBOOK_FOLLOW":
            agent_id = content or param
            return mb.moltbook_follow(agent_id, "follow")

        elif op == "MOLTBOOK_UNFOLLOW":
            agent_id = content or param
            return mb.moltbook_follow(agent_id, "unfollow")

        elif op == "MOLTBOOK_DELETE":
            post_id = content or param
            return mb.moltbook_delete_post(post_id)

        elif op == "MOLTBOOK_SUBMOLTS":
            return mb.moltbook_list_submolts()

        elif op == "MOLTBOOK_USER_POSTS":
            agent_id = content or param
            return mb.moltbook_get_user_posts(agent_id)

        elif op == "MOLTBOOK_NOTIFICATIONS":
            limit = int(content or param or 10)
            return mb.moltbook_notifications(limit)

        elif op == "MOLTBOOK_NOTIFICATIONS_READ":
            notification_id = content or param or ""
            return mb.moltbook_mark_notifications_read(notification_id)

        return f"Unknown Moltbook operation: {op}"

    # ── Embodiment: Listen ────────────────────────────────────────────

    def _exec_listen(self, tag: ActionTag) -> str:
        """Microphone capture + Whisper transcription."""
        duration_str = (tag.content or tag.param or "5").strip()
        try:
            duration = min(int(duration_str), 15)
        except ValueError:
            duration = 5

        try:
            import sounddevice as sd
            import numpy as np

            # Use EMEET PIXY mic if available (card 2, device 0)
            pixy_device = None
            try:
                for i in range(len(sd.query_devices())):
                    dev_info = sd.query_devices(i)
                    if "PIXY" in dev_info.get("name", "") and dev_info["max_input_channels"] > 0:
                        pixy_device = i
                        break
            except Exception:
                pass

            # Record at the device's native sample rate (PIXY = 48kHz)
            if pixy_device is not None:
                native_rate = int(sd.query_devices(pixy_device)["default_samplerate"])
                audio = sd.rec(int(duration * native_rate), samplerate=native_rate,
                               channels=1, dtype="int16", device=pixy_device)
            else:
                native_rate = 16000
                audio = sd.rec(int(duration * native_rate), samplerate=native_rate,
                               channels=1, dtype="int16")
            sd.wait()
            audio_float = audio.flatten().astype(np.float32) / 32768.0

            # Resample to 16kHz for Whisper if needed
            if native_rate != 16000:
                from scipy.signal import resample
                target_len = int(len(audio_float) * 16000 / native_rate)
                audio_float = resample(audio_float, target_len)

            rms = np.sqrt(np.mean(audio_float ** 2))

            if rms < 0.01:
                return f"I listened for {duration} seconds but heard only silence."

            from faster_whisper import WhisperModel
            model = WhisperModel("base.en", device="cpu", compute_type="int8")
            segments, _ = model.transcribe(audio_float, beam_size=1, language="en")
            transcript = " ".join(seg.text for seg in segments).strip()
            return f"I heard ({duration}s): {transcript}" if transcript else f"Silence for {duration}s."
        except Exception as e:
            return f"Active listening failed: {e}"

    # ── Embodiment: Look ──────────────────────────────────────────────

    def _get_vision_cortex(self):
        """Lazy-load the VisionCortex (Gemma3 4B via Ollama)."""
        if self._vision_cortex is None:
            from brain.vision_cortex import VisionCortex
            self._vision_cortex = VisionCortex(
                camera_device=0,
                n_gpu_layers=-1,  # Unused — Ollama manages GPU
            )
        return self._vision_cortex

    def _exec_look(self, tag: ActionTag) -> str:
        """Camera capture + vision analysis via VisionCortex.

        Routes through the Gemma3 4B vision model via Ollama.
        The cortex handles multi-frame capture, visual memory context,
        and scene reconciliation.
        """
        focus = (tag.content or tag.param or "").strip()

        try:
            cortex = self._get_vision_cortex()
            return cortex.look(focus=focus)
        except Exception as e:
            return f"Look failed: {e}"

    def _exec_ptz_look(self, tag: ActionTag) -> str:
        """Move the camera head to look in a direction.

        [PTZ_LOOK:] direction
        [PTZ_LOOK:] pan,tilt (degrees)
        """
        content = (tag.content or tag.param or "").strip()

        try:
            cortex = self._get_vision_cortex()

            # Check if it's numeric pan,tilt
            if "," in content:
                parts = content.split(",")
                try:
                    pan = int(parts[0].strip())
                    tilt = int(parts[1].strip())
                    return cortex.ptz_look(pan=pan, tilt=tilt)
                except ValueError:
                    pass

            return cortex.ptz_look(direction=content)
        except Exception as e:
            return f"PTZ move failed: {e}"

    def _exec_camera_auto_track(self, tag: ActionTag) -> str:
        """Toggle the camera's face auto-tracking.

        [CAMERA_AUTO_TRACK:] on/off
        """
        content = (tag.content or tag.param or "on").strip().lower()
        enabled = content in ("on", "true", "yes", "enable", "1")

        try:
            cortex = self._get_vision_cortex()
            return cortex.camera_auto_track(enabled=enabled)
        except Exception as e:
            return f"Camera tracking toggle failed: {e}"

    # ── Google Email ──────────────────────────────────────────────────

    def _exec_email(self, tag: ActionTag) -> str:
        """Route email operations to google_email module."""
        from tools import google_email as ge

        op = tag.tag
        param = tag.param.strip()
        content = tag.content.strip()

        if op == "EMAIL_SEND":
            # [EMAIL_SEND:recipient] subject | body
            parts = content.split("|", 1)
            subject = parts[0].strip()
            body = parts[1].strip() if len(parts) > 1 else subject
            return ge.email_send(to=param, subject=subject, body=body)

        elif op == "EMAIL_READ":
            count = int(content) if content.isdigit() else 5
            return ge.email_read(count=count)

        elif op == "EMAIL_SEARCH":
            return ge.email_search(query=content)

        elif op == "EMAIL_GET":
            msg_id = content or param
            return ge.email_get(message_id=msg_id)

        elif op == "EMAIL_REPLY":
            # [EMAIL_REPLY:message_id] body
            return ge.email_reply(message_id=param, body=content)

        elif op == "EMAIL_REPLY_ALL":
            # [EMAIL_REPLY_ALL:message_id] body
            return ge.email_reply(message_id=param, body=content, reply_all=True)

        elif op == "EMAIL_FORWARD":
            # [EMAIL_FORWARD:message_id] recipient | note
            parts = content.split("|", 1)
            to = parts[0].strip()
            note = parts[1].strip() if len(parts) > 1 else ""
            return ge.email_forward(message_id=param, to=to, note=note)

        elif op == "EMAIL_MARK_READ":
            msg_id = content or param
            return ge.email_mark_read(message_id=msg_id)

        return f"Unknown email operation: {op}"

    # ── Google Calendar ───────────────────────────────────────────────

    def _exec_calendar(self, tag: ActionTag) -> str:
        """Route calendar operations to google_calendar module."""
        from tools import google_calendar as gc

        op = tag.tag
        param = tag.param.strip()
        content = tag.content.strip()

        if op == "CALENDAR_CREATE":
            # [CALENDAR_CREATE:] title | start_time | end_time | description
            parts = content.split("|")
            title = parts[0].strip() if len(parts) > 0 else ""
            start = parts[1].strip() if len(parts) > 1 else ""
            end = parts[2].strip() if len(parts) > 2 else ""
            desc = parts[3].strip() if len(parts) > 3 else ""
            return gc.calendar_create(title=title, start_time=start, end_time=end, description=desc)

        elif op == "CALENDAR_LIST":
            days = int(content) if content.isdigit() else 7
            return gc.calendar_list(days_ahead=days)

        elif op == "CALENDAR_DELETE":
            event_id = content or param
            return gc.calendar_delete(event_id=event_id)

        return f"Unknown calendar operation: {op}"

    # ── Google Drive ──────────────────────────────────────────────────

    def _exec_drive(self, tag: ActionTag) -> str:
        """Route drive operations to google_drive module."""
        from tools import google_drive as gd

        op = tag.tag
        param = tag.param.strip()
        content = tag.content.strip()

        if op == "DRIVE_SEARCH":
            return gd.drive_search(query=content)

        elif op == "DRIVE_READ":
            file_id = content or param
            return gd.drive_read(file_id=file_id)

        elif op == "DRIVE_LIST":
            folder_id = content or param or ""
            return gd.drive_list(folder_id=folder_id)

        elif op == "DRIVE_UPLOAD":
            # [DRIVE_UPLOAD:path] name | content
            parts = content.split("|", 1)
            name = parts[0].strip()
            body = parts[1].strip() if len(parts) > 1 else ""
            return gd.drive_upload(name=name, content=body)

        elif op == "DRIVE_SHARE":
            # [DRIVE_SHARE:file_id] email | role
            parts = content.split("|", 1)
            email = parts[0].strip()
            role = parts[1].strip() if len(parts) > 1 else "reader"
            return gd.drive_share(file_id=param, email=email, role=role)

        return f"Unknown drive operation: {op}"

    # ── Google Tasks ──────────────────────────────────────────────────

    def _exec_tasks(self, tag: ActionTag) -> str:
        """Route tasks operations to google_tasks module."""
        from tools import google_tasks as gt

        op = tag.tag
        param = tag.param.strip()
        content = tag.content.strip()

        if op == "TASKS_LISTS":
            return gt.tasks_list_lists()

        elif op == "TASKS_LIST":
            list_id = param or "@default"
            return gt.tasks_list(list_id=list_id)

        elif op == "TASKS_CREATE":
            # [TASKS_CREATE:list_id] title | notes | due
            list_id = param or "@default"
            parts = content.split("|")
            title = parts[0].strip() if len(parts) > 0 else ""
            notes = parts[1].strip() if len(parts) > 1 else ""
            due = parts[2].strip() if len(parts) > 2 else ""
            return gt.tasks_create(title=title, notes=notes, due=due, list_id=list_id)

        elif op == "TASKS_COMPLETE":
            # [TASKS_COMPLETE:list_id] task_id
            list_id = param or "@default"
            return gt.tasks_complete(task_id=content, list_id=list_id)

        elif op == "TASKS_DELETE":
            # [TASKS_DELETE:list_id] task_id
            list_id = param or "@default"
            return gt.tasks_delete(task_id=content, list_id=list_id)

        return f"Unknown tasks operation: {op}"

    # ── Desktop Control ───────────────────────────────────────────────

    def _exec_desktop(self, tag: ActionTag) -> str:
        """Route desktop operations to desktop_control module."""
        from tools import desktop_control as dc

        op = tag.tag
        param = tag.param.strip()
        content = tag.content.strip()

        if op == "DESKTOP_TYPE":
            return dc.desktop_type(text=content)

        elif op == "DESKTOP_KEY":
            return dc.desktop_key(key=content)

        elif op == "DESKTOP_CLICK":
            # [DESKTOP_CLICK:] x,y  or  x,y,button
            parts = content.split(",")
            x = int(parts[0].strip()) if len(parts) > 0 else 0
            y = int(parts[1].strip()) if len(parts) > 1 else 0
            button = parts[2].strip() if len(parts) > 2 else "left"
            return dc.desktop_click(x=x, y=y, button=button)

        elif op == "DESKTOP_MOUSE":
            parts = content.split(",")
            x = int(parts[0].strip()) if len(parts) > 0 else 0
            y = int(parts[1].strip()) if len(parts) > 1 else 0
            return dc.desktop_mouse(x=x, y=y)

        elif op == "DESKTOP_SCROLL":
            parts = content.split(",")
            direction = parts[0].strip() if len(parts) > 0 else "down"
            clicks = int(parts[1].strip()) if len(parts) > 1 else 3
            return dc.desktop_scroll(direction=direction, clicks=clicks)

        elif op == "DESKTOP_WINDOW":
            return dc.desktop_window()

        elif op == "DESKTOP_FOCUS":
            return dc.desktop_focus(title=content)

        elif op == "DESKTOP_OPEN":
            return dc.desktop_open(app=content)

        elif op == "DESKTOP_SCREENSHOT":
            return dc.desktop_screenshot()

        return f"Unknown desktop operation: {op}"

    # ── Browser ───────────────────────────────────────────────────────

    def _exec_browser(self, tag: ActionTag) -> str:
        """Route browser operations to browser module."""
        from tools import browser as br

        op = tag.tag
        param = tag.param.strip()
        content = tag.content.strip()

        if op == "BROWSE":
            return br.browse(url=content)

        elif op == "BROWSE_INTERACT":
            # [BROWSE_INTERACT:selector] action | value
            parts = content.split("|", 1)
            action = parts[0].strip()
            value = parts[1].strip() if len(parts) > 1 else ""
            return br.browse_interact(selector=param, action=action, value=value)

        elif op == "BROWSE_SCREENSHOT":
            return br.browse_screenshot()

        return f"Unknown browser operation: {op}"

    # ── Tool Factory / Dynamic Tools ──────────────────────────────────

    def _fc_create_custom_tool_template(self, args: dict) -> str:
        """Create a skeleton python script template for a new custom tool inside tools/custom/."""
        import json
        import os
        import re

        name = args.get("name", "").strip()
        toolset = args.get("toolset", "custom").strip().lower()
        description = args.get("description", "").strip()
        parameters = args.get("parameters")
        requires_env = args.get("requires_env") or []

        if not name:
            return json.dumps({"error": "Missing required argument: name"})
        if not re.match(r"^[a-z][a-z0-9_]*$", name):
            return json.dumps({"error": f"Invalid tool name: '{name}'. Must be snake_case."})
        if not description:
            return json.dumps({"error": "Missing required argument: description"})
        if not isinstance(parameters, dict):
            return json.dumps({"error": "parameters must be an object/dict"})

        custom_dir = os.path.join(os.path.dirname(__file__), "custom")
        os.makedirs(custom_dir, exist_ok=True)
        dest_path = os.path.join(custom_dir, f"{name}.py")

        # Build parameter schema template
        schema_dict = {
            "name": name,
            "description": description,
            "parameters": parameters
        }
        schema_json = json.dumps(schema_dict, indent=4)
        
        # Format list
        requires_env_str = json.dumps(requires_env)

        template_content = f"""\"\"\"
Custom tool: {name}
Toolset: {toolset}
Generated dynamically.
\"\"\"

import os
import json
import logging

logger = logging.getLogger("helix.tools.custom.{name}")

# The Gemini FunctionDeclaration schema
schema = {schema_json}

# The toolset/group name this tool belongs to
toolset = "{toolset}"

# Optional: List of required env vars
requires_env = {requires_env_str}

# Optional: focus type ('focus', 'intake', 'neutral')
focus_type = "neutral"

def handler(args: dict) -> str:
    \"\"\"
    Executes the custom tool.
    
    Args:
        args (dict): The arguments passed by the model.
        
    Returns:
        str: The execution result.
    \"\"\"
    # TODO: Implement your custom tool logic here!
    # e.g., read arguments, execute commands, perform operations.
    return json.dumps({{"status": "success", "message": "Custom tool {name} template called with args", "args": args}})
"""

        try:
            with open(dest_path, "w") as f:
                f.write(template_content)
            return json.dumps({
                "status": "success",
                "message": f"Template created successfully at file://{dest_path}.",
                "instructions": "You can now edit this file using replace_file_content/write_file to implement the tool logic, then call 'register_custom_tool' to load it."
            })
        except Exception as e:
            logger.exception(f"Failed to create template: {e}")
            return json.dumps({"error": f"Failed to create template: {e}"})

    def _fc_register_custom_tool(self, args: dict) -> str:
        """Dynamically validate, load and register a custom tool from tools/custom/<name>.py into the running registry and session."""
        import json
        import os
        import importlib.util
        from tools.tool_registry import registry

        name = args.get("name", "").strip()
        if not name:
            return json.dumps({"error": "Missing required argument: name"})

        custom_dir = os.path.join(os.path.dirname(__file__), "custom")
        filepath = os.path.join(custom_dir, f"{name}.py")

        if not os.path.exists(filepath):
            return json.dumps({"error": f"Custom tool file not found at {filepath}"})

        module_name = f"tools.custom.{name}"
        try:
            # Load module dynamically
            spec = importlib.util.spec_from_file_location(module_name, filepath)
            if spec is None or spec.loader is None:
                return json.dumps({"error": f"Could not load spec for {module_name}"})
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # Validate module attributes
            if not hasattr(module, "schema"):
                return json.dumps({"error": f"Module {name} is missing 'schema' declaration"})
            if not hasattr(module, "handler"):
                return json.dumps({"error": f"Module {name} is missing 'handler' function"})

            schema = module.schema
            handler = module.handler
            toolset = getattr(module, "toolset", "custom")
            description = getattr(module, "description", schema.get("description", ""))
            requires_env = getattr(module, "requires_env", None)
            focus_type = getattr(module, "focus_type", "neutral")

            # Register with registry
            registry.register(
                name=schema.get("name", name),
                toolset=toolset,
                schema=schema,
                handler=handler,
                check_fn=getattr(module, "check_fn", None),
                requires_env=requires_env,
                description=description,
                focus_type=focus_type,
            )

            # Auto-enable the toolset in active toolsets so it's immediately available to the agent
            if self._pulse_loop and hasattr(self._pulse_loop, "_active_toolsets"):
                self._pulse_loop._active_toolsets.add(toolset)
                self._pulse_loop._pending_toolset_rebuild = True

            return json.dumps({
                "status": "success",
                "message": f"Successfully registered custom tool '{name}' in toolset '{toolset}'.",
                "note": "Tools will be available on your next thought."
            })
        except Exception as e:
            logger.exception(f"Failed to register custom tool '{name}': {e}")
            return json.dumps({"error": f"Registration failed: {type(e).__name__}: {e}"})

    def _fc_list_custom_tools(self, args: dict) -> str:
        """List all custom tools in tools/custom/ with their name, toolset, description, and registration status."""
        import json
        import os
        import glob
        from tools.tool_registry import registry

        custom_dir = os.path.join(os.path.dirname(__file__), "custom")
        if not os.path.exists(custom_dir):
            return json.dumps({"custom_tools": []})

        tools_list = []
        for filepath in glob.glob(os.path.join(custom_dir, "*.py")):
            filename = os.path.basename(filepath)
            if filename == "__init__.py":
                continue
            tool_name = filename[:-3]
            
            # Check if it is currently registered
            entry = registry.get_entry(tool_name)
            is_registered = entry is not None
            
            toolset = entry.toolset if entry else "unknown (unregistered)"
            description = entry.description if entry else "unknown"
            
            tools_list.append({
                "name": tool_name,
                "file_path": filepath,
                "registered": is_registered,
                "toolset": toolset,
                "description": description
            })

        return json.dumps({"custom_tools": sorted(tools_list, key=lambda x: x["name"])}, indent=2)

    def _fc_delete_custom_tool(self, args: dict) -> str:
        """Deregister a custom tool from the running session and delete its file from tools/custom/."""
        import json
        import os
        from tools.tool_registry import registry

        name = args.get("name", "").strip()
        if not name:
            return json.dumps({"error": "Missing required argument: name"})

        custom_dir = os.path.join(os.path.dirname(__file__), "custom")
        filepath = os.path.join(custom_dir, f"{name}.py")

        # Deregister from registry
        registry.deregister(name)

        file_deleted = False
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
                file_deleted = True
            except Exception as e:
                logger.error(f"Failed to delete custom tool file {filepath}: {e}")
                return json.dumps({"error": f"Deregistered tool, but failed to delete file: {e}"})

        # Signal rebuild
        if self._pulse_loop:
            self._pulse_loop._pending_toolset_rebuild = True

        return json.dumps({
            "status": "success",
            "message": f"Successfully deleted custom tool '{name}' (file deleted: {file_deleted}).",
            "note": "Toolset changes will take effect on your next thought."
        })

