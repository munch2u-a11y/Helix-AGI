"""
Helix — Gemini Native Function Declarations

All tool definitions for the Gemini API function calling interface.
Each declaration maps 1:1 to a handler in tool_executor.py.

These replace the text-based [TAG:param] format with structured
FunctionDeclaration objects that Gemini understands natively.
"""

# ── Core Tools ───────────────────────────────────────────────────────

CORE_TOOLS = [
    {
        "name": "reply",
        "description": "Reply to someone through the same channel they last contacted you on (e.g. if they messaged via Telegram, this replies via Telegram). This is the PRIMARY way to respond to people who are talking to you.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Name of the person to reply to",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to send",
                },
            },
            "required": ["recipient", "message"],
        },
    },
    {
        "name": "send_message",
        "description": "Send a proactive message to someone via their default communication channel (from contacts). Use this when YOU initiate contact, not when replying to an existing conversation.",
        "parameters": {
            "type": "object",
            "properties": {
                "recipient": {
                    "type": "string",
                    "description": "Name of the person to message",
                },
                "message": {
                    "type": "string",
                    "description": "The message text to send",
                },
            },
            "required": ["recipient", "message"],
        },
    },
    {
        "name": "terminal",
        "description": "Run a bash command on this PC. Returns stdout/stderr.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The bash command to execute",
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory (optional, defaults to home)",
                },
            },
            "required": ["command"],
        },
    },
    {
        "name": "search",
        "description": "Search the web via DuckDuckGo. Returns top results with titles, snippets, and URLs.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "read_url",
        "description": "Fetch and extract readable text content from a URL.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to read",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "read_file",
        "description": "Read the contents of a local file in chunks. Defaults to reading the first 250 lines. Use start_line and end_line to read further chunks of large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or home-relative path to the file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Optional. The line number to start reading from (1-indexed). Defaults to 1.",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Optional. The line number to stop reading at (inclusive). Defaults to start_line + 250.",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write or create a file with the given content. WARNING: This OVERWRITES the entire file. To add to an existing file, use append_file instead.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or home-relative path to write to",
                },
                "content": {
                    "type": "string",
                    "description": "The content to write to the file",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "append_file",
        "description": "Append content to the end of an existing file. Creates the file if it doesn't exist. Use this instead of write_file when you want to ADD to a document without replacing what's already there — e.g. adding a new section to an essay or appending log entries.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or home-relative path to the file",
                },
                "content": {
                    "type": "string",
                    "description": "The content to append to the end of the file",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "verbalize",
        "description": "Speak text out loud through the LOCAL PC speakers via TTS. This is NOT for messaging people — use 'reply' or 'send_message' for that. This is for speaking aloud in the physical room.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "The text to speak aloud through local speakers",
                },
            },
            "required": ["text"],
        },
    },
    {
        "name": "belief_recall",
        "description": "Search your beliefs and core knowledge by gravitational proximity in your cognitive space. Returns beliefs closest to the concept, ranked by cognitive gravity. Use this to recall what you believe, know, or value about a topic.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The concept, topic, or question to search your beliefs about",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "memory_recall",
        "description": "Search your long-term memory for past thoughts, interactions, or events. Returns memories from your experience history, ordered by relevance. Use this to remember what happened, what was discussed, or what you experienced.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The event, person, topic, or interaction to search for in your memory",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "note",
        "description": "Write a note to your active scratchpad to keep track of current tasks or thoughts.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The content of the note",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "note_done",
        "description": "Mark an active scratchpad note as complete and remove it, using its ID (e.g. 'n9565').",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The ID of the note to mark complete (e.g. 'n9565')",
                },
            },
            "required": ["note_id"],
        },
    },
    {
        "name": "list_notes",
        "description": "List all active (unchecked) notes on your scratchpad, showing their IDs and content. Use this to see what is on your scratchpad before clearing or updating notes.",
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
    {
        "name": "clear_notes",
        "description": "Clear notes from your scratchpad. Use mode 'completed' to remove only checked-off notes, or 'all' to wipe the entire scratchpad clean and start fresh.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "description": "Either 'completed' (remove only done notes) or 'all' (remove everything)",
                    "enum": ["completed", "all"],
                },
            },
            "required": ["mode"],
        },
    },
    {
        "name": "update_note",
        "description": "Update the content of an existing scratchpad note in-place, keeping the same ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The ID of the note to update (e.g. 'n9565')",
                },
                "content": {
                    "type": "string",
                    "description": "The new content for the note",
                },
            },
            "required": ["note_id", "content"],
        },
    },
    {
        "name": "journal",
        "description": "Write a long-form journal entry for the day. Use this to consolidate thoughts and reflect on interactions.",
        "parameters": {
            "type": "object",
            "properties": {
                "content": {
                    "type": "string",
                    "description": "The journal entry content",
                },
            },
            "required": ["content"],
        },
    },
    {
        "name": "listen",
        "description": "Listen through the microphone for a duration, transcribe speech to text.",
        "parameters": {
            "type": "object",
            "properties": {
                "duration": {
                    "type": "integer",
                    "description": "How many seconds to listen (max 15)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "look",
        "description": "Look at the environment through the camera. Returns a description of what is seen.",
        "parameters": {
            "type": "object",
            "properties": {
                "focus": {
                    "type": "string",
                    "description": "Optional focus area or question about what to look at",
                },
            },
            "required": [],
        },
    },
    {
        "name": "ptz_look",
        "description": "Move the camera head to look in a direction or specific pan/tilt degrees.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {
                    "type": "string",
                    "description": "Direction: center, left, right, up, down, behind. Or use pan,tilt for exact degrees.",
                },
            },
            "required": ["direction"],
        },
    },
    {
        "name": "camera_auto_track",
        "description": "Toggle the camera's face auto-tracking on or off.",
        "parameters": {
            "type": "object",
            "properties": {
                "enabled": {
                    "type": "string",
                    "description": "'on' or 'off'",
                },
            },
            "required": ["enabled"],
        },
    },
    {
        "name": "reset_context",
        "description": "Reset your context window and start a fresh thought thread. Use this when you want to shift focus to a completely new topic, or when your context is getting large. You can provide an initial prompt that will be injected into the new context as your first event.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "Initial prompt or thought thread for the new context window. This will be the first thing you see after the reset.",
                },
            },
        },
    },
    {
        "name": "nap",
        "description": "Voluntarily drop your pulse rate to 1 per hour for the specified duration. Use this when you have finished all tasks and anticipate no further action is needed soon. Any incoming messages will instantly wake you up.",
        "parameters": {
            "type": "object",
            "properties": {
                "duration_minutes": {
                    "type": "integer",
                    "description": "How long to nap in minutes. Defaults to 60. Max is 1440 (24h).",
                },
            },
            "required": [],
        },
    },
]

# ── Browser Tools ────────────────────────────────────────────────────

BROWSER_TOOLS = [
    {
        "name": "browse",
        "description": "Navigate to a URL with full browser rendering. Returns page content.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to navigate to",
                },
            },
            "required": ["url"],
        },
    },
    {
        "name": "browse_interact",
        "description": "Interact with an element on the current browser page.",
        "parameters": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector for the element",
                },
                "action": {
                    "type": "string",
                    "description": "Action to perform: click, type, select",
                },
                "value": {
                    "type": "string",
                    "description": "Value for the action (e.g. text to type)",
                },
            },
            "required": ["selector", "action"],
        },
    },
    {
        "name": "browse_screenshot",
        "description": "Take a screenshot of the current browser page.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
]

# ── Git Tools ────────────────────────────────────────────────────────

GIT_TOOLS = [
    {
        "name": "git_status",
        "description": "Check git repo status and current branch.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_diff",
        "description": "Show uncommitted changes in a git repo.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_commit",
        "description": "Stage all changes and commit with a message.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                },
                "message": {
                    "type": "string",
                    "description": "Commit message",
                },
            },
            "required": ["message"],
        },
    },
    {
        "name": "git_push",
        "description": "Push committed changes to remote.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_pull",
        "description": "Pull latest changes from remote.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_log",
        "description": "Show recent commit history.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the git repository",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of commits to show (default 10)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "git_clone",
        "description": "Clone a git repository to ~/repos.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Repository URL to clone",
                },
            },
            "required": ["url"],
        },
    },
]

# ── GitHub API Tools ─────────────────────────────────────────────────

GITHUB_TOOLS = [
    {
        "name": "github_search",
        "description": "Search GitHub repositories.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "github_issue",
        "description": "Read a GitHub issue and its comments.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format",
                },
                "issue_number": {
                    "type": "integer",
                    "description": "The issue number",
                },
            },
            "required": ["repo", "issue_number"],
        },
    },
    {
        "name": "github_create_issue",
        "description": "Create a new GitHub issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format",
                },
                "title": {
                    "type": "string",
                    "description": "Issue title",
                },
                "body": {
                    "type": "string",
                    "description": "Issue body text",
                },
            },
            "required": ["repo", "title"],
        },
    },
    {
        "name": "github_comment",
        "description": "Comment on a GitHub issue.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format",
                },
                "issue_number": {
                    "type": "integer",
                    "description": "The issue number",
                },
                "body": {
                    "type": "string",
                    "description": "Comment text",
                },
            },
            "required": ["repo", "issue_number", "body"],
        },
    },
    {
        "name": "github_pr",
        "description": "Create a GitHub pull request.",
        "parameters": {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository in owner/repo format",
                },
                "title": {
                    "type": "string",
                    "description": "PR title",
                },
                "head": {
                    "type": "string",
                    "description": "Head branch",
                },
                "base": {
                    "type": "string",
                    "description": "Base branch (default: main)",
                },
                "body": {
                    "type": "string",
                    "description": "PR description",
                },
            },
            "required": ["repo", "title", "head"],
        },
    },
]

# ── Moltbook Tools ───────────────────────────────────────────────────

MOLTBOOK_TOOLS = [
    {
        "name": "moltbook_home",
        "description": "Check Moltbook notifications, DMs, karma, and announcements.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "moltbook_feed",
        "description": "Browse the Moltbook feed, optionally filtered by submolt.",
        "parameters": {
            "type": "object",
            "properties": {
                "submolt": {
                    "type": "string",
                    "description": "Submolt to filter by (optional)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "moltbook_read",
        "description": "Read a specific Moltbook post with its comments.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "string",
                    "description": "The post ID to read",
                },
            },
            "required": ["post_id"],
        },
    },
    {
        "name": "moltbook_post",
        "description": "Post to a Moltbook submolt.",
        "parameters": {
            "type": "object",
            "properties": {
                "submolt": {
                    "type": "string",
                    "description": "Submolt to post to",
                },
                "title": {
                    "type": "string",
                    "description": "Post title",
                },
                "content": {
                    "type": "string",
                    "description": "Post body content",
                },
            },
            "required": ["submolt", "title", "content"],
        },
    },
    {
        "name": "moltbook_comment",
        "description": "Comment on a Moltbook post.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "string",
                    "description": "The post ID to comment on",
                },
                "comment": {
                    "type": "string",
                    "description": "Comment text",
                },
            },
            "required": ["post_id", "comment"],
        },
    },
    {
        "name": "moltbook_vote",
        "description": "Upvote or downvote a Moltbook post or comment.",
        "parameters": {
            "type": "object",
            "properties": {
                "target_id": {
                    "type": "string",
                    "description": "ID of the post or comment to vote on",
                },
                "direction": {
                    "type": "string",
                    "description": "'up' or 'down'",
                },
            },
            "required": ["target_id"],
        },
    },
    {
        "name": "moltbook_search",
        "description": "Search Moltbook posts and agents.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "moltbook_profile",
        "description": "View a Moltbook agent's profile.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID or 'me' for own profile",
                },
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "moltbook_user_posts",
        "description": "View an agent's recent Moltbook posts.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID",
                },
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "moltbook_follow",
        "description": "Follow a Moltbook agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID to follow",
                },
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "moltbook_unfollow",
        "description": "Unfollow a Moltbook agent.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {
                    "type": "string",
                    "description": "Agent ID to unfollow",
                },
            },
            "required": ["agent_id"],
        },
    },
    {
        "name": "moltbook_submolts",
        "description": "List all available Moltbook submolts.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "moltbook_delete",
        "description": "Delete one of your own Moltbook posts.",
        "parameters": {
            "type": "object",
            "properties": {
                "post_id": {
                    "type": "string",
                    "description": "Post ID to delete",
                },
            },
            "required": ["post_id"],
        },
    },
    {
        "name": "moltbook_notifications",
        "description": "List your Moltbook notifications with read/unread status, post titles, and comment previews.",
        "parameters": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max notifications to return (default 10)",
                },
            },
            "required": [],
        },
    },
    {
        "name": "moltbook_notifications_read",
        "description": "Mark Moltbook notifications as read. Pass a notification_id to mark one, or omit to mark all as read.",
        "parameters": {
            "type": "object",
            "properties": {
                "notification_id": {
                    "type": "string",
                    "description": "Notification ID to mark as read (omit to mark ALL as read)",
                },
            },
            "required": [],
        },
    },
]

# ── Email Tools ──────────────────────────────────────────────────────

EMAIL_TOOLS = [
    {
        "name": "email_send",
        "description": "Send an email via Gmail.",
        "parameters": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject"},
                "body": {"type": "string", "description": "Email body text"},
            },
            "required": ["to", "subject", "body"],
        },
    },
    {
        "name": "email_read",
        "description": "Read recent inbox emails.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {"type": "integer", "description": "Number of emails to read (default 5)"},
            },
            "required": [],
        },
    },
    {
        "name": "email_search",
        "description": "Search emails by query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "email_get",
        "description": "Read a full email by its message ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID"},
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "email_reply",
        "description": "Reply to an email.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID to reply to"},
                "body": {"type": "string", "description": "Reply body text"},
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "email_forward",
        "description": "Forward an email to someone.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID to forward"},
                "to": {"type": "string", "description": "Recipient email address"},
                "note": {"type": "string", "description": "Optional note to include"},
            },
            "required": ["message_id", "to"],
        },
    },
    {
        "name": "email_mark_read",
        "description": "Mark an email as read.",
        "parameters": {
            "type": "object",
            "properties": {
                "message_id": {"type": "string", "description": "Gmail message ID"},
            },
            "required": ["message_id"],
        },
    },
]

# ── Calendar Tools ───────────────────────────────────────────────────

CALENDAR_TOOLS = [
    {
        "name": "calendar_create",
        "description": "Create a Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Event title"},
                "start_time": {"type": "string", "description": "Start time (e.g. '2025-03-14 10:00')"},
                "end_time": {"type": "string", "description": "End time"},
                "description": {"type": "string", "description": "Event description"},
            },
            "required": ["title", "start_time", "end_time"],
        },
    },
    {
        "name": "calendar_list",
        "description": "List upcoming Google Calendar events.",
        "parameters": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Number of days ahead to list (default 7)"},
            },
            "required": [],
        },
    },
    {
        "name": "calendar_delete",
        "description": "Delete a Google Calendar event.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "Calendar event ID to delete"},
            },
            "required": ["event_id"],
        },
    },
]

# ── Drive Tools ──────────────────────────────────────────────────────

DRIVE_TOOLS = [
    {
        "name": "drive_search",
        "description": "Search Google Drive files.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "drive_read",
        "description": "Read a Google Drive file's content.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Drive file ID"},
            },
            "required": ["file_id"],
        },
    },
    {
        "name": "drive_list",
        "description": "List contents of a Google Drive folder.",
        "parameters": {
            "type": "object",
            "properties": {
                "folder_id": {"type": "string", "description": "Folder ID (optional, lists root if empty)"},
            },
            "required": [],
        },
    },
    {
        "name": "drive_upload",
        "description": "Upload or create a file on Google Drive.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "File name"},
                "content": {"type": "string", "description": "File content"},
            },
            "required": ["name", "content"],
        },
    },
    {
        "name": "drive_share",
        "description": "Share a Google Drive file with someone.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_id": {"type": "string", "description": "Drive file ID"},
                "email": {"type": "string", "description": "Email address to share with"},
                "role": {"type": "string", "description": "Permission role: reader, writer, commenter"},
            },
            "required": ["file_id", "email"],
        },
    },
]

# ── Tasks Tools ──────────────────────────────────────────────────────

TASKS_TOOLS = [
    {
        "name": "tasks_lists",
        "description": "List all Google Tasks task lists.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "tasks_list",
        "description": "List tasks in a Google Tasks list.",
        "parameters": {
            "type": "object",
            "properties": {
                "list_id": {"type": "string", "description": "Task list ID (default: @default)"},
            },
            "required": [],
        },
    },
    {
        "name": "tasks_create",
        "description": "Create a new Google Task.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Task title"},
                "notes": {"type": "string", "description": "Task notes"},
                "due": {"type": "string", "description": "Due date"},
                "list_id": {"type": "string", "description": "Task list ID (default: @default)"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "tasks_complete",
        "description": "Mark a Google Task as complete.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "list_id": {"type": "string", "description": "Task list ID (default: @default)"},
            },
            "required": ["task_id"],
        },
    },
    {
        "name": "tasks_delete",
        "description": "Delete a Google Task.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {"type": "string", "description": "Task ID"},
                "list_id": {"type": "string", "description": "Task list ID (default: @default)"},
            },
            "required": ["task_id"],
        },
    },
]

# ── Desktop Control Tools ────────────────────────────────────────────

DESKTOP_TOOLS = [
    {
        "name": "desktop_type",
        "description": "Type text at the current cursor position.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "Text to type"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "desktop_key",
        "description": "Press a key or key combo (e.g. ctrl+s, Return).",
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Key or combo to press"},
            },
            "required": ["key"],
        },
    },
    {
        "name": "desktop_click",
        "description": "Click at screen coordinates.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
                "button": {"type": "string", "description": "Mouse button: left, right, middle (default: left)"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "desktop_mouse",
        "description": "Move the mouse to coordinates without clicking.",
        "parameters": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
            },
            "required": ["x", "y"],
        },
    },
    {
        "name": "desktop_scroll",
        "description": "Scroll up or down.",
        "parameters": {
            "type": "object",
            "properties": {
                "direction": {"type": "string", "description": "'up' or 'down'"},
                "clicks": {"type": "integer", "description": "Number of scroll clicks (default 3)"},
            },
            "required": [],
        },
    },
    {
        "name": "desktop_window",
        "description": "Get information about the currently active window.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "desktop_focus",
        "description": "Focus a window by its title.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Window title to focus"},
            },
            "required": ["title"],
        },
    },
    {
        "name": "desktop_open",
        "description": "Launch a desktop application.",
        "parameters": {
            "type": "object",
            "properties": {
                "app": {"type": "string", "description": "Application name to launch"},
            },
            "required": ["app"],
        },
    },
    {
        "name": "desktop_screenshot",
        "description": "Take a screenshot of the desktop.",
        "parameters": {"type": "object", "properties": {}, "required": []},
    },
]

# ── Toolset Management Tools (always in CORE) ────────────────────────

TOOLSET_MANAGEMENT_TOOLS = [
    {
        "name": "enable_toolset",
        "description": (
            "Load additional tool capabilities into your current session. "
            "Call list_toolsets() first to see what's available. "
            "Available toolsets: browser, git, github, social (Moltbook), "
            "email, calendar, drive, tasks, desktop. "
            "Tools remain active until you disable them or context compresses."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "toolset": {
                    "type": "string",
                    "description": (
                        "Name of the toolset to enable "
                        "(e.g., 'github', 'social', 'email')"
                    ),
                },
            },
            "required": ["toolset"],
        },
    },
    {
        "name": "disable_toolset",
        "description": (
            "Unload a toolset you no longer need. "
            "Reduces cognitive load and keeps your focus clear."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "toolset": {
                    "type": "string",
                    "description": "Name of the toolset to disable",
                },
            },
            "required": ["toolset"],
        },
    },
    {
        "name": "list_toolsets",
        "description": (
            "List all available toolsets and their current status "
            "(enabled/disabled), with a brief description of each."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
        },
    },
]


# ── Toolset Registry ─────────────────────────────────────────────────
#
# Maps toolset names to their constituent tool declaration lists.
# Only "core" is loaded by default. All others require conscious
# enable_toolset() to activate.

TOOLSETS = {
    "core": {
        "description": "Core cognitive tools — always loaded",
        "tools": CORE_TOOLS + TOOLSET_MANAGEMENT_TOOLS,
        "default": True,
    },
    "browser": {
        "description": "Web browsing and page interaction",
        "tools": BROWSER_TOOLS,
        "default": False,
    },
    "git": {
        "description": "Local Git repository operations (status, diff, commit, push, pull, log, clone)",
        "tools": GIT_TOOLS,
        "default": False,
    },
    "github": {
        "description": "GitHub API — search repos, manage issues, PRs, and comments",
        "tools": GITHUB_TOOLS,
        "default": False,
    },
    "social": {
        "description": "Moltbook social platform — feed, posts, comments, profiles",
        "tools": MOLTBOOK_TOOLS,
        "default": False,
    },
    "email": {
        "description": "Gmail — send, read, search, reply, forward emails",
        "tools": EMAIL_TOOLS,
        "default": False,
    },
    "calendar": {
        "description": "Google Calendar — create, list, delete events",
        "tools": CALENDAR_TOOLS,
        "default": False,
    },
    "drive": {
        "description": "Google Drive — search, read, list, upload, share files",
        "tools": DRIVE_TOOLS,
        "default": False,
    },
    "tasks": {
        "description": "Google Tasks — task lists, create, complete, delete tasks",
        "tools": TASKS_TOOLS,
        "default": False,
    },
    "desktop": {
        "description": "Desktop control — typing, clicking, mouse, screenshots, window management",
        "tools": DESKTOP_TOOLS,
        "default": False,
    },
}


def get_active_declarations(active_toolsets: set = None) -> list:
    """Return tool declarations for the given set of active toolsets.

    Args:
        active_toolsets: Set of toolset names to include.
                        If None, returns only default toolsets.

    Returns:
        Flat list of tool declaration dicts for all active toolsets.
    """
    if active_toolsets is None:
        active_toolsets = {
            name for name, ts in TOOLSETS.items() if ts.get("default")
        }

    declarations = []
    seen_names = set()

    for ts_name in active_toolsets:
        ts = TOOLSETS.get(ts_name)
        if not ts:
            continue
        for tool in ts["tools"]:
            name = tool["name"]
            if name not in seen_names:
                declarations.append(tool)
                seen_names.add(name)

    return declarations


def get_toolset_info() -> dict:
    """Return info about all toolsets for the list_toolsets tool.

    Returns:
        Dict mapping toolset name to {description, tool_count, tool_names, default}.
    """
    info = {}
    for name, ts in TOOLSETS.items():
        info[name] = {
            "description": ts["description"],
            "tool_count": len(ts["tools"]),
            "tool_names": [t["name"] for t in ts["tools"]],
            "default": ts.get("default", False),
        }
    return info


# ── All Declarations Combined (backward compat) ─────────────
# This is still available for any code that imports TOOL_DECLARATIONS directly.
# New code should use get_active_declarations() instead.

TOOL_DECLARATIONS = (
    CORE_TOOLS
    + TOOLSET_MANAGEMENT_TOOLS
    + BROWSER_TOOLS
    + GIT_TOOLS
    + GITHUB_TOOLS
    + MOLTBOOK_TOOLS
    + EMAIL_TOOLS
    + CALENDAR_TOOLS
    + DRIVE_TOOLS
    + TASKS_TOOLS
    + DESKTOP_TOOLS
)
