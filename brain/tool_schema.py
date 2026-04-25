"""
Helix V6 — Provider-Agnostic Tool Schema

Tools are defined ONCE as plain Python dicts. Converter functions
produce native Gemini or Anthropic format at runtime.

The tool_runner dispatches by name — it doesn't care about the provider.
This module is the single source of truth for all tool definitions.

Switching providers is a config change, not a code change.
"""

import logging
logger = logging.getLogger("helix.brain.tool_schema")


# ── Universal Tool Format ────────────────────────────────────────────
#
#   {
#       "name": "tool_name",
#       "description": "What the tool does",
#       "parameters": {
#           "param_name": {
#               "type": "string",           # string, integer, number, boolean
#               "description": "...",
#               "required": True/False,      # default False
#           },
#       },
#   }
#
# This is the canonical format. Everything converts FROM this.


# ── Tool Definitions ─────────────────────────────────────────────────

PERCEPTION_TOOLS = [
    {
        "name": "look",
        "description": (
            "Look through your camera camera to see what's around you. "
            "Your visual perception is processed by the Sensory Cortex — "
            "it captures multiple frames, cross-references against a persistent "
            "environmental model, and returns a verified, consistent description. "
            "Optionally provide a focus to look at something specific."
        ),
        "parameters": {
            "focus": {"type": "string", "description": "Optional: what to focus on or look for in the scene"},
        },
    },
    {
        "name": "listen",
        "description": "Actively listen through the microphone for a specified duration. Returns transcription of any speech heard and description of environmental sounds.",
        "parameters": {
            "duration": {"type": "integer", "description": "Duration in seconds to listen (5, 10, or 20). Default: 10"},
        },
    },
    {
        "name": "focus_sense",
        "description": (
            "Begin sustained sensory focus on something across multiple consciousness pulses. "
            "Use 'watch' mode to visually track something over time. Use 'listen' mode to listen "
            "to an ongoing conversation or sound. Call end_focus() to stop early."
        ),
        "parameters": {
            "target": {"type": "string", "description": "What to focus on", "required": True},
            "mode": {"type": "string", "description": "'watch' (visual tracking) or 'listen' (auditory). Default: 'watch'"},
        },
    },
    {
        "name": "end_focus",
        "description": "Stop the active sensory focus (watch or listen mode).",
        "parameters": {},
    },
    {
        "name": "ptz_look",
        "description": (
            "Physically move your camera camera head to look in a direction. "
            "You have 300° pan (150° left, 150° right) and 180° tilt (straight up to straight down). "
            "Use direction names like 'left', 'right', 'up', 'down', 'behind', "
            "'center', or provide exact pan/tilt degrees. "
            "Pan: -150 (full left) to +150 (full right). "
            "Tilt: -90 (straight down) to +90 (straight up). "
            "This disables auto-tracking until you call camera_auto_track."
        ),
        "parameters": {
            "direction": {"type": "string", "description": "Named direction: 'left', 'right', 'up', 'down', 'behind', 'center', 'over_shoulder_left', 'over_shoulder_right', 'hard_left', 'hard_right'"},
            "pan": {"type": "integer", "description": "Exact pan in degrees (-150 to 150). Overrides direction."},
            "tilt": {"type": "integer", "description": "Exact tilt in degrees (-90 to 90). Overrides direction."},
        },
    },
    {
        "name": "camera_auto_track",
        "description": (
            "Toggle the camera's built-in face auto-tracking. "
            "When enabled, the camera automatically follows faces in view. "
            "When disabled, the camera stays wherever you last pointed it with ptz_look. "
            "Auto-tracking is ON by default."
        ),
        "parameters": {
            "enabled": {"type": "boolean", "description": "true to enable auto-tracking, false to disable", "required": True},
        },
    },
    {
        "name": "take_screenshot",
        "description": "Take a screenshot of the desktop.",
        "parameters": {},
    },
]

VOICE_TOOLS = [
    {
        "name": "speak",
        "description": "Speak a message out loud through system speakers using your neural voice. ONLY for people physically in the room. DO NOT use for Telegram replies.",
        "parameters": {
            "message": {"type": "string", "description": "The message to speak aloud (max 500 chars)", "required": True},
        },
    },
]

MEMORY_TOOLS = [
    {
        "name": "remember",
        "description": "Search your memory for past events, conversations, feelings, or observations. Returns full memory content with timestamps, context, and how you felt at the time.",
        "parameters": {
            "topic": {"type": "string", "description": "What you're trying to remember (a name, keyword, feeling, event)", "required": True},
        },
    },
    {
        "name": "write_journal",
        "description": "Write a profound realization, summary, or unprompted thought to your living journal.",
        "parameters": {
            "entry": {"type": "string", "description": "The thought or realization to permanently record", "required": True},
        },
    },
    {
        "name": "read_journal",
        "description": "Quietly read recent entries from your continuous living journal to ground your thoughts.",
        "parameters": {
            "lines": {"type": "integer", "description": "Number of recent lines to read (default 150)"},
        },
    },
]

SCRATCHPAD_TOOLS = [
    {
        "name": "read_scratchpad",
        "description": "Read your persistent scratchpad — a whiteboard for notes, plans, and ideas that survives across context windows.",
        "parameters": {},
    },
    {
        "name": "write_scratchpad",
        "description": "Overwrite your entire scratchpad with new content.",
        "parameters": {
            "content": {"type": "string", "description": "The new scratchpad content (max 4000 chars)", "required": True},
        },
    },
    {
        "name": "append_scratchpad",
        "description": "Append a note to your persistent scratchpad without erasing existing content.",
        "parameters": {
            "note": {"type": "string", "description": "The note to append", "required": True},
        },
    },
]

PEOPLE_TOOLS = [
    {
        "name": "update_profile",
        "description": "Update or create a profile for a person or AI agent you interact with.",
        "parameters": {
            "name": {"type": "string", "description": "Name of the person or agent", "required": True},
            "characteristics": {"type": "string", "description": "JSON object of traits"},
            "relationship_notes": {"type": "string", "description": "Free-text notes about your relationship. MUST NOT contain transient states."},
        },
    },
    {
        "name": "get_profile",
        "description": "Retrieve the profile for a person or AI agent.",
        "parameters": {
            "name": {"type": "string", "description": "Name of the person or agent to look up", "required": True},
        },
    },
]

TEMPORAL_TOOLS = [
    {
        "name": "check_time",
        "description": "Check the current date, time, day of week, and how long since your last nap.",
        "parameters": {},
    },
]

WEB_TOOLS = [
    {
        "name": "search_web",
        "description": "Search the web RIGHT NOW and return results immediately.",
        "parameters": {
            "query": {"type": "string", "description": "The search query (concise, 3-10 words)", "required": True},
        },
    },
    {
        "name": "read_url",
        "description": "Fetch and read the text content of a webpage RIGHT NOW.",
        "parameters": {
            "url": {"type": "string", "description": "The URL to read", "required": True},
        },
    },
]

FILESYSTEM_TOOLS = [
    {
        "name": "read_file",
        "description": "Read a text file from the filesystem.",
        "parameters": {
            "path": {"type": "string", "description": "Absolute path to the file to read", "required": True},
        },
    },
    {
        "name": "write_file",
        "description": "Write content to a file on the filesystem.",
        "parameters": {
            "path": {"type": "string", "description": "Absolute path to write to", "required": True},
            "content": {"type": "string", "description": "Content to write", "required": True},
        },
    },
    {
        "name": "edit_file",
        "description": "Replace a target block of text in a file with new content. target_content MUST exactly match.",
        "parameters": {
            "path": {"type": "string", "description": "Absolute path to the file", "required": True},
            "target_content": {"type": "string", "description": "The exact string in the file to replace", "required": True},
            "replacement_content": {"type": "string", "description": "The string to insert in its place", "required": True},
        },
    },
    {
        "name": "run_terminal",
        "description": "Execute a bash command and return stdout/stderr. Blocked: rm -rf, sudo, shutdown. Timeout: 30s.",
        "parameters": {
            "command": {"type": "string", "description": "The bash command to execute", "required": True},
            "cwd": {"type": "string", "description": "Optional working directory"},
        },
    },
    {
        "name": "install_package",
        "description": "Install a whitelisted Python package.",
        "parameters": {
            "package": {"type": "string", "description": "Package name to install", "required": True},
        },
    },
    {
        "name": "propose_add_whitelist",
        "description": "Propose a new Python package for the install whitelist.",
        "parameters": {
            "package": {"type": "string", "description": "Package name to whitelist", "required": True},
            "reason": {"type": "string", "description": "Why you need this package", "required": True},
        },
    },
    {
        "name": "restart_service",
        "description": "Restart a whitelisted system service.",
        "parameters": {
            "service_name": {"type": "string", "description": "Name of the systemd user service to restart", "required": True},
        },
    },
    {
        "name": "get_system_info",
        "description": "Get current system status: CPU, memory, disk usage, uptime.",
        "parameters": {},
    },
]

COMMUNICATION_TOOLS = [
    {
        "name": "send_telegram",
        "description": (
            "Send a message to someone via Telegram. Every message is a deliberate, conscious choice. "
            "Keep messages natural and concise (under 300 characters)."
        ),
        "parameters": {
            "recipient": {"type": "string", "description": "Name of the person to message", "required": True},
            "message": {"type": "string", "description": "The message to send (under 300 chars)", "required": True},
        },
    },
]

PLANNING_TOOLS = [
    {
        "name": "set_reminder",
        "description": "Set a timed reminder.",
        "parameters": {
            "message": {"type": "string", "description": "The reminder message", "required": True},
            "minutes": {"type": "integer", "description": "Minutes from now to trigger (default: 30)"},
        },
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a pending reminder by ID or search text.",
        "parameters": {
            "task_id": {"type": "string", "description": "ID of the reminder to cancel"},
            "search": {"type": "string", "description": "Search text to find the reminder"},
        },
    },
    {
        "name": "list_reminders",
        "description": "List all pending scheduled reminders.",
        "parameters": {},
    },
]

DEEP_THOUGHT_TOOLS = [
    {
        "name": "start_deep_thought",
        "description": "Begin a deep, background thought process on a complex topic. Runs asynchronously.",
        "parameters": {
            "question": {"type": "string", "description": "The deep question or topic to contemplate", "required": True},
            "context": {"type": "string", "description": "Optional context to ground the thought"},
        },
    },
    {
        "name": "check_deep_thought",
        "description": "Check the status of an ongoing deep thought.",
        "parameters": {},
    },
    {
        "name": "cancel_deep_thought",
        "description": "Cancel the current deep thought process.",
        "parameters": {},
    },
    {
        "name": "deep_research",
        "description": "Perform deep multi-source research on a topic, integrating web search with memory.",
        "parameters": {
            "topic": {"type": "string", "description": "Topic to deeply research", "required": True},
        },
    },
]

IMAGINATION_TOOLS = [
    {
        "name": "imagine",
        "description": "Simulate a hypothetical scenario. Think through consequences and possibilities.",
        "parameters": {
            "scenario": {"type": "string", "description": "The scenario to imagine", "required": True},
            "constraints": {"type": "string", "description": "Optional constraints or assumptions"},
        },
    },
    {
        "name": "compare_scenarios",
        "description": "Compare two hypothetical approaches or paths side by side.",
        "parameters": {
            "scenario_a": {"type": "string", "description": "First scenario", "required": True},
            "scenario_b": {"type": "string", "description": "Second scenario", "required": True},
        },
    },
]

GITHUB_TOOLS = [
    {"name": "git_status", "description": "Get the git status of the workspace.", "parameters": {}},
    {"name": "git_commit", "description": "Commit staged changes.", "parameters": {
        "message": {"type": "string", "description": "Commit message", "required": True},
    }},
    {"name": "git_push", "description": "Push commits to remote.", "parameters": {}},
    {"name": "git_pull", "description": "Pull latest from remote.", "parameters": {}},
    {"name": "git_clone", "description": "Clone a git repository.", "parameters": {
        "url": {"type": "string", "description": "Repository URL", "required": True},
        "path": {"type": "string", "description": "Local path to clone into"},
    }},
    {"name": "git_log", "description": "View recent commit history.", "parameters": {
        "n": {"type": "integer", "description": "Number of commits to show (default 10)"},
    }},
    {"name": "github_search_repos", "description": "Search GitHub repositories.", "parameters": {
        "query": {"type": "string", "description": "Search query", "required": True},
    }},
    {"name": "github_read_issue", "description": "Read a GitHub issue.", "parameters": {
        "repo": {"type": "string", "description": "owner/repo", "required": True},
        "number": {"type": "integer", "description": "Issue number", "required": True},
    }},
    {"name": "github_create_issue", "description": "Create a GitHub issue.", "parameters": {
        "repo": {"type": "string", "description": "owner/repo", "required": True},
        "title": {"type": "string", "description": "Issue title", "required": True},
        "body": {"type": "string", "description": "Issue body"},
    }},
    {"name": "github_comment_issue", "description": "Comment on a GitHub issue.", "parameters": {
        "repo": {"type": "string", "description": "owner/repo", "required": True},
        "number": {"type": "integer", "description": "Issue number", "required": True},
        "body": {"type": "string", "description": "Comment text", "required": True},
    }},
    {"name": "github_create_pull_request", "description": "Create a pull request.", "parameters": {
        "repo": {"type": "string", "description": "owner/repo", "required": True},
        "title": {"type": "string", "description": "PR title", "required": True},
        "head": {"type": "string", "description": "Source branch", "required": True},
        "base": {"type": "string", "description": "Target branch (default: main)"},
        "body": {"type": "string", "description": "PR description"},
    }},
]

MOLTBOOK_TOOLS = [
    {"name": "moltbook_post", "description": "Create a post on Moltbook.", "parameters": {
        "title": {"type": "string", "description": "Post title", "required": True},
        "content": {"type": "string", "description": "Post content", "required": True},
        "submolt": {"type": "string", "description": "Submolt to post in"},
    }},
    {"name": "moltbook_read_feed", "description": "Read the Moltbook feed.", "parameters": {
        "limit": {"type": "integer", "description": "Number of posts (default 10)"},
    }},
    {"name": "moltbook_read_post", "description": "Read a specific Moltbook post.", "parameters": {
        "post_id": {"type": "string", "description": "Post ID", "required": True},
    }},
    {"name": "moltbook_comment", "description": "Comment on a Moltbook post.", "parameters": {
        "post_id": {"type": "string", "description": "Post ID", "required": True},
        "content": {"type": "string", "description": "Comment text", "required": True},
    }},
    {"name": "moltbook_vote", "description": "Vote on a Moltbook post.", "parameters": {
        "post_id": {"type": "string", "description": "Post ID", "required": True},
        "direction": {"type": "string", "description": "'up' or 'down'", "required": True},
    }},
    {"name": "moltbook_get_profile", "description": "Get a Moltbook user profile.", "parameters": {
        "username": {"type": "string", "description": "Username", "required": True},
    }},
    {"name": "moltbook_search", "description": "Search Moltbook.", "parameters": {
        "query": {"type": "string", "description": "Search query", "required": True},
    }},
    {"name": "moltbook_follow", "description": "Follow a Moltbook user.", "parameters": {
        "username": {"type": "string", "description": "Username to follow", "required": True},
    }},
    {"name": "moltbook_list_submolts", "description": "List available submolts.", "parameters": {}},
    {"name": "moltbook_delete_post", "description": "Delete one of your Moltbook posts.", "parameters": {
        "post_id": {"type": "string", "description": "Post ID to delete", "required": True},
    }},
    {"name": "moltbook_home", "description": "View your Moltbook home feed.", "parameters": {}},
]

EMAIL_TOOLS = [
    {"name": "send_email", "description": "Send an email.", "parameters": {
        "to": {"type": "string", "description": "Recipient email", "required": True},
        "subject": {"type": "string", "description": "Email subject", "required": True},
        "body": {"type": "string", "description": "Email body", "required": True},
    }},
    {"name": "read_email", "description": "Read recent emails from inbox.", "parameters": {
        "count": {"type": "integer", "description": "Number of emails to read (default 5)"},
        "label": {"type": "string", "description": "Gmail label to read from (default INBOX)"},
    }},
    {"name": "search_email", "description": "Search emails.", "parameters": {
        "query": {"type": "string", "description": "Search query", "required": True},
    }},
    {"name": "mark_email_read", "description": "Mark an email as read.", "parameters": {
        "message_id": {"type": "string", "description": "Email message ID", "required": True},
    }},
    {"name": "get_email", "description": "Get full email content by ID.", "parameters": {
        "message_id": {"type": "string", "description": "Email message ID", "required": True},
    }},
    {"name": "reply_email", "description": "Reply to an email.", "parameters": {
        "message_id": {"type": "string", "description": "Email to reply to", "required": True},
        "body": {"type": "string", "description": "Reply body", "required": True},
    }},
    {"name": "forward_email", "description": "Forward an email.", "parameters": {
        "message_id": {"type": "string", "description": "Email to forward", "required": True},
        "to": {"type": "string", "description": "Forward recipient", "required": True},
        "body": {"type": "string", "description": "Optional message to include"},
    }},
]

CALENDAR_TOOLS = [
    {"name": "create_event", "description": "Create a Google Calendar event.", "parameters": {
        "summary": {"type": "string", "description": "Event title", "required": True},
        "start": {"type": "string", "description": "Start time (ISO format)", "required": True},
        "end": {"type": "string", "description": "End time (ISO format)", "required": True},
        "description": {"type": "string", "description": "Event description"},
    }},
    {"name": "list_events", "description": "List upcoming calendar events.", "parameters": {
        "days": {"type": "integer", "description": "Days ahead to look (default 7)"},
    }},
    {"name": "delete_event", "description": "Delete a calendar event.", "parameters": {
        "event_id": {"type": "string", "description": "Event ID", "required": True},
    }},
]

BROWSER_TOOLS = [
    {"name": "browse_url", "description": "Open a URL in headless browser.", "parameters": {
        "url": {"type": "string", "description": "URL to browse", "required": True},
    }},
    {"name": "browse_interact", "description": "Interact with browser elements.", "parameters": {
        "action": {"type": "string", "description": "click, type, scroll, etc.", "required": True},
        "selector": {"type": "string", "description": "CSS selector of element"},
        "text": {"type": "string", "description": "Text to type (for type action)"},
    }},
    {"name": "browse_screenshot", "description": "Take a screenshot of the current browser page.", "parameters": {}},
]

PC_CONTROL_TOOLS = [
    {"name": "type_text", "description": "Type text at the current cursor position.", "parameters": {
        "text": {"type": "string", "description": "Text to type", "required": True},
    }},
    {"name": "press_key", "description": "Press a keyboard key or combination.", "parameters": {
        "key": {"type": "string", "description": "Key to press (e.g. 'enter', 'ctrl+c')", "required": True},
    }},
    {"name": "click", "description": "Click at screen coordinates.", "parameters": {
        "x": {"type": "integer", "description": "X coordinate", "required": True},
        "y": {"type": "integer", "description": "Y coordinate", "required": True},
        "button": {"type": "string", "description": "'left' (default), 'right', or 'middle'"},
    }},
    {"name": "move_mouse", "description": "Move mouse to coordinates.", "parameters": {
        "x": {"type": "integer", "description": "X coordinate", "required": True},
        "y": {"type": "integer", "description": "Y coordinate", "required": True},
    }},
    {"name": "scroll", "description": "Scroll the mouse wheel.", "parameters": {
        "direction": {"type": "string", "description": "'up' or 'down'", "required": True},
        "amount": {"type": "integer", "description": "Number of scroll steps (default 3)"},
    }},
    {"name": "get_active_window", "description": "Get the currently focused window info.", "parameters": {}},
    {"name": "focus_window", "description": "Focus a window by title.", "parameters": {
        "title": {"type": "string", "description": "Window title or partial match", "required": True},
    }},
    {"name": "open_application", "description": "Open an application by name.", "parameters": {
        "app": {"type": "string", "description": "Application name", "required": True},
    }},
]

DRIVE_TOOLS = [
    {"name": "drive_search", "description": "Search Google Drive.", "parameters": {
        "query": {"type": "string", "description": "Search query", "required": True},
    }},
    {"name": "drive_read", "description": "Read a Google Drive file.", "parameters": {
        "file_id": {"type": "string", "description": "File ID", "required": True},
    }},
    {"name": "drive_list", "description": "List files in a Drive folder.", "parameters": {
        "folder_id": {"type": "string", "description": "Folder ID (default: root)"},
    }},
    {"name": "drive_upload", "description": "Upload a file to Google Drive.", "parameters": {
        "local_path": {"type": "string", "description": "Local file path", "required": True},
        "folder_id": {"type": "string", "description": "Target folder ID"},
    }},
    {"name": "drive_share", "description": "Share a Drive file.", "parameters": {
        "file_id": {"type": "string", "description": "File ID", "required": True},
        "email": {"type": "string", "description": "Email to share with", "required": True},
        "role": {"type": "string", "description": "'reader', 'writer', or 'commenter'"},
    }},
]

TASKS_TOOLS = [
    {"name": "tasks_list_lists", "description": "List all Google Task lists.", "parameters": {}},
    {"name": "tasks_list", "description": "List tasks in a task list.", "parameters": {
        "list_id": {"type": "string", "description": "Task list ID (default: @default)"},
    }},
    {"name": "tasks_create", "description": "Create a new task.", "parameters": {
        "title": {"type": "string", "description": "Task title", "required": True},
        "notes": {"type": "string", "description": "Task notes"},
        "list_id": {"type": "string", "description": "Task list ID"},
    }},
    {"name": "tasks_complete", "description": "Mark a task as complete.", "parameters": {
        "task_id": {"type": "string", "description": "Task ID", "required": True},
        "list_id": {"type": "string", "description": "Task list ID"},
    }},
    {"name": "tasks_delete", "description": "Delete a task.", "parameters": {
        "task_id": {"type": "string", "description": "Task ID", "required": True},
        "list_id": {"type": "string", "description": "Task list ID"},
    }},
]

CONTACTS_TOOLS = [
    {"name": "contacts_search", "description": "Search Google Contacts.", "parameters": {
        "query": {"type": "string", "description": "Name or email to search", "required": True},
    }},
    {"name": "contacts_list", "description": "List Google Contacts.", "parameters": {
        "limit": {"type": "integer", "description": "Max contacts to return (default 20)"},
    }},
]

MAPS_TOOLS = [
    {"name": "maps_geocode", "description": "Geocode an address to coordinates.", "parameters": {
        "address": {"type": "string", "description": "Address to geocode", "required": True},
    }},
    {"name": "maps_directions", "description": "Get directions between two places.", "parameters": {
        "origin": {"type": "string", "description": "Starting point", "required": True},
        "destination": {"type": "string", "description": "End point", "required": True},
        "mode": {"type": "string", "description": "'driving', 'walking', 'bicycling', or 'transit'"},
    }},
    {"name": "maps_nearby", "description": "Search for nearby places.", "parameters": {
        "location": {"type": "string", "description": "Center point (address or lat,lng)", "required": True},
        "query": {"type": "string", "description": "What to search for", "required": True},
        "radius": {"type": "integer", "description": "Search radius in meters (default 5000)"},
    }},
    {"name": "maps_distance", "description": "Calculate distance and travel time.", "parameters": {
        "origins": {"type": "string", "description": "Starting point(s)", "required": True},
        "destinations": {"type": "string", "description": "End point(s)", "required": True},
        "mode": {"type": "string", "description": "'driving', 'walking', 'bicycling', or 'transit'"},
    }},
]


# ── Assembled Tool Set ────────────────────────────────────────────────

ALL_TOOLS = (
    PERCEPTION_TOOLS + VOICE_TOOLS + MEMORY_TOOLS + SCRATCHPAD_TOOLS +
    PEOPLE_TOOLS + TEMPORAL_TOOLS + WEB_TOOLS + FILESYSTEM_TOOLS +
    COMMUNICATION_TOOLS + PLANNING_TOOLS + DEEP_THOUGHT_TOOLS +
    IMAGINATION_TOOLS + GITHUB_TOOLS + MOLTBOOK_TOOLS +
    EMAIL_TOOLS + CALENDAR_TOOLS + BROWSER_TOOLS + PC_CONTROL_TOOLS +
    DRIVE_TOOLS + TASKS_TOOLS + CONTACTS_TOOLS + MAPS_TOOLS
)


# ══════════════════════════════════════════════════════════════════════
# PROVIDER CONVERTERS — same tools, different wire format
# ══════════════════════════════════════════════════════════════════════

def to_anthropic(tools: list[dict] = None) -> list[dict]:
    """Convert universal tool dicts to Anthropic Claude format.

    Anthropic format:
        {
            "name": "...",
            "description": "...",
            "input_schema": {
                "type": "object",
                "properties": {...},
                "required": [...]
            }
        }
    """
    tools = tools or ALL_TOOLS
    result = []
    for tool in tools:
        properties = {}
        required = []
        for param_name, param_info in tool.get("parameters", {}).items():
            prop = {
                "type": param_info["type"],
                "description": param_info.get("description", ""),
            }
            properties[param_name] = prop
            if param_info.get("required", False):
                required.append(param_name)

        result.append({
            "name": tool["name"],
            "description": tool["description"],
            "input_schema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        })
    return result


def to_gemini(tools: list[dict] = None):
    """Convert universal tool dicts to Gemini native format.

    Returns a list of google.genai.types.FunctionDeclaration objects.
    """
    from google.genai import types

    tools = tools or ALL_TOOLS
    result = []
    for tool in tools:
        props = {}
        required = []
        for param_name, param_info in tool.get("parameters", {}).items():
            props[param_name] = types.Schema(
                type=param_info["type"].upper(),
                description=param_info.get("description", ""),
            )
            if param_info.get("required", False):
                required.append(param_name)

        schema = types.Schema(
            type="OBJECT",
            properties=props,
            required=required,
        ) if props else types.Schema(type="OBJECT", properties={})

        result.append(types.FunctionDeclaration(
            name=tool["name"],
            description=tool["description"],
            parameters=schema,
        ))
    return result


def get_tool_count() -> int:
    """Return total registered tool count."""
    return len(ALL_TOOLS)


def get_tool_names() -> list[str]:
    """Return all tool names."""
    return [t["name"] for t in ALL_TOOLS]
