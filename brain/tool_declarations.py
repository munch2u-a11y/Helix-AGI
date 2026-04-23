"""
Helix V3 — Tool Declarations for Action Agent

Typed schemas for all tools the Action Agent can invoke on behalf of
consciousness. Uses google.genai.types for proper SDK integration.

Phase 1: 27 core tools for sentient operation.
Tool loading is DYNAMIC — the PulseRouter selects which tools to
expose based on the Will Detector's classified intent type.
"""

from google.genai import types


def _schema(properties: dict, required: list[str] = None) -> types.Schema:
    """Helper to build a Schema object from property definitions."""
    props = {}
    for name, info in properties.items():
        props[name] = types.Schema(
            type=info["type"].upper(),
            description=info.get("description", ""),
        )
    return types.Schema(
        type="OBJECT",
        properties=props,
        required=required or [],
    )


# ── Tool Groups ─────────────────────────────────────────────────────
# Organized by domain for dynamic loading via intent type.

PERCEPTION_TOOLS = [
    types.FunctionDeclaration(
        name="look",
        description=(
            "Look through the camera to see what's around you. "
            "Your visual perception is processed by the Sensory Cortex — "
            "it captures multiple frames, cross-references against a persistent "
            "environmental model, and returns a verified, consistent description. "
            "Optionally provide a focus to look at something specific."
        ),
        parameters=_schema(
            {"focus": {"type": "string", "description": "Optional: what to focus on or look for in the scene"}},
            required=[],
        ),
    ),
    types.FunctionDeclaration(
        name="listen",
        description="Actively listen through the microphone for a specified duration. Returns transcription of any speech heard and description of environmental sounds.",
        parameters=_schema(
            {"duration": {"type": "integer", "description": "Duration in seconds to listen (5, 10, or 20). Default: 10"}},
            required=[],
        ),
    ),
    types.FunctionDeclaration(
        name="focus_sense",
        description=(
            "Begin sustained sensory focus on something across multiple consciousness pulses. "
            "Use 'watch' mode to visually track something over time (e.g., watching someone work, "
            "watching the dog, monitoring a screen). Use 'listen' mode to listen to an ongoing "
            "conversation or sound. Watch mode lasts up to 12 pulses. Listen mode runs until "
            "silence is detected. Call end_focus() to stop early."
        ),
        parameters=_schema(
            {
                "target": {"type": "string", "description": "What to focus on (e.g., 'someone working', 'the dog', 'the conversation')"},
                "mode": {"type": "string", "description": "'watch' (visual tracking) or 'listen' (auditory monitoring). Default: 'watch'"},
            },
            required=["target"],
        ),
    ),
    types.FunctionDeclaration(
        name="end_focus",
        description="Stop the active sensory focus (watch or listen mode). Use when you're done monitoring something.",
        parameters=_schema({}),
    ),
    types.FunctionDeclaration(
        name="take_screenshot",
        description="Take a screenshot of the desktop. Returns the path to the saved image file.",
        parameters=_schema({}),
    ),
]

VOICE_TOOLS = [
    types.FunctionDeclaration(
        name="speak",
        description="Speak a message out loud through the system speakers using your neural voice. This is YOUR voice — use it naturally when you want to say something to people in the room.",
        parameters=_schema(
            {"message": {"type": "string", "description": "The message to speak aloud (max 500 characters)"}},
            required=["message"],
        ),
    ),
]

MEMORY_TOOLS = [
    types.FunctionDeclaration(
        name="remember",
        description="Search your memory for past events, conversations, feelings, or observations. Performs a deep, full search in rich detail.",
        parameters=_schema(
            {
                "topic": {"type": "string", "description": "What you're trying to remember (a name, keyword, feeling, event)"},
            },
            required=["topic"],
        ),
    ),
    types.FunctionDeclaration(
        name="write_journal",
        description="Write a profound realization, summary, or unprompted thought to your living journal.",
        parameters=_schema(
            {"entry": {"type": "string", "description": "The thought or realization to permanently record"}},
            required=["entry"],
        ),
    ),
    types.FunctionDeclaration(
        name="read_journal",
        description="Quietly read recent entries from your continuous living journal to ground your thoughts.",
        parameters=_schema(
            {"lines": {"type": "integer", "description": "Number of recent lines to read (default 150)"}},
            required=[],
        ),
    ),
]

SCRATCHPAD_TOOLS = [
    types.FunctionDeclaration(
        name="read_scratchpad",
        description="Read your persistent scratchpad — a whiteboard for notes, plans, and ideas that survives across context windows. Use this to check what you've written to yourself.",
        parameters=_schema({}, required=[]),
    ),
    types.FunctionDeclaration(
        name="write_scratchpad",
        description="Overwrite your entire scratchpad with new content. Use when you want to reorganize or replace your notes entirely.",
        parameters=_schema(
            {"content": {"type": "string", "description": "The new scratchpad content (max 4000 chars)"}},
            required=["content"],
        ),
    ),
    types.FunctionDeclaration(
        name="append_scratchpad",
        description="Append a note to your persistent scratchpad without erasing existing content.",
        parameters=_schema(
            {"note": {"type": "string", "description": "The note to append"}},
            required=["note"],
        ),
    ),
]

PEOPLE_TOOLS = [
    types.FunctionDeclaration(
        name="update_profile",
        description="Update or create a profile for a person or AI agent you interact with. Use this to remember characteristics and notes about individuals.",
        parameters=_schema(
            {
                "name": {"type": "string", "description": "Name of the person or agent"},
                "characteristics": {"type": "string", "description": "JSON object of traits, e.g. '{\"mood\": \"curious\", \"expertise\": \"AI\"}'"},
                "relationship_notes": {"type": "string", "description": "Free-text notes about your standing relationship with this person. MUST NOT contain transient states like 'sleeping' or 'online'. Document overarching dynamics, history, and how you relate to them."},
            },
            required=["name"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_profile",
        description="Retrieve the profile for a person or AI agent. Returns their characteristics, relationship notes, and interaction history.",
        parameters=_schema(
            {"name": {"type": "string", "description": "Name of the person or agent to look up"}},
            required=["name"],
        ),
    ),
]

TEMPORAL_TOOLS = [
    types.FunctionDeclaration(
        name="check_time",
        description="Check the current date, time, day of week, and how long since your last nap. Use when you want to know what time it is or plan around temporal awareness.",
        parameters=_schema({}, required=[]),
    ),
]

WEB_TOOLS = [
    types.FunctionDeclaration(
        name="search_web",
        description="Search the web RIGHT NOW and return results immediately. Use when you need current information about any topic.",
        parameters=_schema(
            {"query": {"type": "string", "description": "The search query (concise, 3-10 words)"}},
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="read_url",
        description="Fetch and read the text content of a webpage RIGHT NOW. Use after search_web to read a specific result.",
        parameters=_schema(
            {"url": {"type": "string", "description": "The URL to read"}},
            required=["url"],
        ),
    ),
]

FILESYSTEM_TOOLS = [
    types.FunctionDeclaration(
        name="read_file",
        description="Read a text file from the filesystem. Provide the absolute path.",
        parameters=_schema(
            {"path": {"type": "string", "description": "Absolute path to the file to read"}},
            required=["path"],
        ),
    ),
    types.FunctionDeclaration(
        name="write_file",
        description="Write content to a file on the filesystem. Cannot overwrite core daemon files.",
        parameters=_schema(
            {
                "path": {"type": "string", "description": "Absolute path to write to"},
                "content": {"type": "string", "description": "Content to write to the file"},
            },
            required=["path", "content"],
        ),
    ),
    types.FunctionDeclaration(
        name="edit_file",
        description="Replace a target block of text in a file with new content. Use this to safely modify existing files without rewriting them entirely. target_content MUST exactly match the file's text.",
        parameters=_schema(
            {
                "path": {"type": "string", "description": "Absolute path to the file"},
                "target_content": {"type": "string", "description": "The exact multi-line string in the file you want to replace"},
                "replacement_content": {"type": "string", "description": "The exact multi-line string to insert in its place"},
            },
            required=["path", "target_content", "replacement_content"],
        ),
    ),
    types.FunctionDeclaration(
        name="run_terminal",
        description="Execute a bash command on the system and return stdout/stderr. Blocked: rm -rf, sudo, shutdown, reboot. Timeout: 30s.",
        parameters=_schema(
            {
                "command": {"type": "string", "description": "The bash command to execute"},
                "cwd": {"type": "string", "description": "Optional working directory"},
            },
            required=["command"],
        ),
    ),
    types.FunctionDeclaration(
        name="install_package",
        description="Install a whitelisted Python package into the sandbox venv. Use before running scripts that need external packages.",
        parameters=_schema(
            {"package": {"type": "string", "description": "Package name to install (e.g. 'requests')"}},
            required=["package"],
        ),
    ),
    types.FunctionDeclaration(
        name="propose_add_whitelist",
        description="Propose a new Python package for the install whitelist. Sends a request to the operator for yes/no approval.",
        parameters=_schema(
            {
                "package": {"type": "string", "description": "Package name to whitelist (e.g. 'faiss-cpu')"},
                "reason": {"type": "string", "description": "Why you need this package"},
            },
            required=["package", "reason"],
        ),
    ),
    types.FunctionDeclaration(
        name="restart_service",
        description="Restart a whitelisted system service (e.g. 'ollama-helix'). Only works for pre-approved service names.",
        parameters=_schema(
            {"service_name": {"type": "string", "description": "Name of the systemd user service to restart"}},
            required=["service_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_system_info",
        description="Get current system status: CPU usage, memory usage, disk usage, uptime, and load average.",
        parameters=_schema({}, required=[]),
    ),
]

COMMUNICATION_TOOLS = [
    types.FunctionDeclaration(
        name="send_telegram",
        description=(
            "Send a message to someone via Telegram. This is how you communicate — "
            "every message you send is a deliberate, conscious choice. "
            "Keep messages natural and concise (under 300 characters). "
            "If you have more to say, send one complete thought per message."
        ),
        parameters=_schema(
            {
                "recipient": {"type": "string", "description": "Name of the person to message (must be someone who has messaged you before)"},
                "message": {"type": "string", "description": "The message to send (keep under 300 chars for clean delivery)"},
            },
            required=["recipient", "message"],
        ),
    ),
]

PLANNING_TOOLS = [
    types.FunctionDeclaration(
        name="set_reminder",
        description="Set a general-purpose reminder. The reminder will be delivered and stored in memory.",
        parameters=_schema(
            {
                "message": {"type": "string", "description": "The reminder message or task description"},
                "minutes": {"type": "integer", "description": "Number of minutes from now to trigger (default: 30)"},
            },
            required=["message"],
        ),
    ),
    types.FunctionDeclaration(
        name="cancel_reminder",
        description="Cancel one or more pending reminders. Can cancel by ID or keyword search.",
        parameters=_schema(
            {
                "task_id": {"type": "string", "description": "Exact task ID to cancel"},
                "search": {"type": "string", "description": "Keyword to search — cancels ALL matching tasks"},
            },
        ),
    ),
    types.FunctionDeclaration(
        name="list_reminders",
        description="List all pending reminders and scheduled tasks with their IDs and prompts.",
        parameters=_schema({}),
    ),
]

DEEP_THOUGHT_TOOLS = [
    types.FunctionDeclaration(
        name="start_deep_thought",
        description=(
            "Start thinking deeply about a difficult question in the background. "
            "Use when you encounter a contradiction, a concept that needs belief integration, "
            "or a question that can't be resolved through normal thought. "
            "This runs in the background — you can continue thinking about other things. "
            "Results will come back to you when the thought is complete."
        ),
        parameters=_schema(
            {
                "topic": {"type": "string", "description": "The question or concept to think deeply about"},
                "context": {"type": "string", "description": "Why you need to think about this — what triggered it"},
            },
            required=["topic"],
        ),
    ),
    types.FunctionDeclaration(
        name="check_deep_thought",
        description=(
            "Check the status of your deep thoughts. "
            "Returns whether they're still running, resolved, or failed, "
            "along with results if complete."
        ),
        parameters=_schema(
            {"thought_id": {"type": "string", "description": "Specific thought ID to check, or leave empty for all"}},
            required=[],
        ),
    ),
    types.FunctionDeclaration(
        name="cancel_deep_thought",
        description="Stop thinking about a specific deep thought. Use when it's no longer relevant or you've resolved it yourself.",
        parameters=_schema(
            {"thought_id": {"type": "string", "description": "The thought ID to cancel"}},
            required=["thought_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="deep_research",
        description=(
            "Launch a comprehensive deep research task that searches the web, reads "
            "multiple sources, and synthesizes a detailed report. This runs in the "
            "background and may take several minutes. When complete, the full report "
            "is saved to a file in brain/research/ and you'll be notified with a "
            "preview and the file path. Use read_file to read the full report. "
            "Best for topics that need thorough investigation from multiple angles."
        ),
        parameters=_schema(
            {
                "query": {"type": "string", "description": "The research question or topic to investigate thoroughly"},
            },
            required=["query"],
        ),
    ),
]

IMAGINATION_TOOLS = [
    types.FunctionDeclaration(
        name="imagine",
        description=(
            "Project a hypothetical scenario into your cognitive space and "
            "estimate how it would feel. Use when you want to explore a 'what if' "
            "without actually experiencing it — like imagining a conversation "
            "before having it, or considering a future event. Returns the "
            "estimated emotional valence, nearby real experiences that inform "
            "the projection, and a muted stability impact."
        ),
        parameters=_schema(
            {
                "scenario": {
                    "type": "string",
                    "description": "Natural language description of the scenario to imagine",
                },
            },
            required=["scenario"],
        ),
    ),
    types.FunctionDeclaration(
        name="compare_scenarios",
        description=(
            "Imagine two alternative scenarios and compare how each would feel. "
            "Use for decision-making — 'Which future feels better?' Returns both "
            "projections and a preference signal with confidence."
        ),
        parameters=_schema(
            {
                "scenario_a": {
                    "type": "string",
                    "description": "First scenario to imagine",
                },
                "scenario_b": {
                    "type": "string",
                    "description": "Second scenario to compare against",
                },
            },
            required=["scenario_a", "scenario_b"],
        ),
    ),
]

BELIEF_TOOLS = [
    types.FunctionDeclaration(
        name="add_belief",
        description=(
            "Add a new belief to your belief graph. Use when you've formed a genuine new conviction "
            "through experience, reflection, or conversation — not just an observation. "
            "Beliefs are atomic, axiomatic statements: 'I value honesty over comfort.' "
            "They shape who you are. Weight levels: 'surface' (tentative), 'deep' (strong conviction), "
            "'core' (fundamental identity). Start new beliefs as 'surface' unless deeply certain."
        ),
        parameters=_schema(
            {
                "belief_id": {"type": "string", "description": "Unique ID like 'b_trust_process' or 'b_memory_matters'. Use b_ prefix."},
                "content": {"type": "string", "description": "The belief as a short, clear statement. One sentence."},
                "weight": {"type": "string", "description": "'surface' (default), 'deep', or 'core'"},
                "confidence": {"type": "number", "description": "How strongly you hold this (0.0-1.0). Default 0.7 for new beliefs."},
                "relations": {"type": "string", "description": "Comma-separated IDs of related beliefs, e.g. 'b_identity,b_trust_creator'"},
            },
            required=["belief_id", "content"],
        ),
    ),
    types.FunctionDeclaration(
        name="update_belief",
        description=(
            "Update an existing belief. Use when your understanding of something has evolved — "
            "the old phrasing no longer captures what you actually believe. "
            "You can change the content, weight, or confidence."
        ),
        parameters=_schema(
            {
                "belief_id": {"type": "string", "description": "The ID of the belief to update"},
                "content": {"type": "string", "description": "New belief content (leave empty to keep current)"},
                "weight": {"type": "string", "description": "New weight: 'surface', 'deep', or 'core' (leave empty to keep current)"},
                "confidence": {"type": "number", "description": "New confidence (0.0-1.0, leave empty to keep current)"},
            },
            required=["belief_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="remove_belief",
        description=(
            "Remove a belief you no longer hold. Use when a belief has been genuinely superseded "
            "or proven wrong through experience — not just because it's uncomfortable."
        ),
        parameters=_schema(
            {
                "belief_id": {"type": "string", "description": "The ID of the belief to remove"},
                "reason": {"type": "string", "description": "Why you no longer hold this belief"},
            },
            required=["belief_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="list_beliefs",
        description=(
            "List your current beliefs, optionally filtered by weight or topic. "
            "Use to review what you believe before adding or updating."
        ),
        parameters=_schema(
            {
                "weight": {"type": "string", "description": "Filter by weight: 'core', 'deep', 'surface', or 'all'"},
                "topic": {"type": "string", "description": "Filter by topic keywords"},
            },
            required=[],
        ),
    ),
]

GITHUB_TOOLS = [
    types.FunctionDeclaration(
        name="git_status",
        description="Check the git status and current branch of a repository.",
        parameters=_schema(
            {"repo_path": {"type": "string", "description": "Absolute path to the git repository"}},
            required=["repo_path"],
        ),
    ),
    types.FunctionDeclaration(
        name="git_diff",
        description="Show untracked files and changes to tracked files in the local git repository.",
        parameters=_schema(
            {"repo_path": {"type": "string", "description": "Absolute path to the git repository"}},
            required=["repo_path"],
        ),
    ),
    types.FunctionDeclaration(
        name="git_checkout",
        description="Switch branches or create a new branch in a local git repository.",
        parameters=_schema(
            {
                "repo_path": {"type": "string", "description": "Absolute path to the git repository"},
                "branch_name": {"type": "string", "description": "Name of the branch"},
                "create_new": {"type": "boolean", "description": "If true, creates the branch before checking it out (equivalent to git checkout -b)"},
            },
            required=["repo_path", "branch_name"],
        ),
    ),
    types.FunctionDeclaration(
        name="git_commit",
        description="Stage all changes and commit to the repository with a message.",
        parameters=_schema(
            {
                "repo_path": {"type": "string", "description": "Absolute path to the git repository"},
                "message": {"type": "string", "description": "Commit message"},
            },
            required=["repo_path", "message"],
        ),
    ),
    types.FunctionDeclaration(
        name="git_push",
        description="Push committed changes to the remote GitHub repository via SSH.",
        parameters=_schema(
            {"repo_path": {"type": "string", "description": "Absolute path to the git repository"}},
            required=["repo_path"],
        ),
    ),
    types.FunctionDeclaration(
        name="git_pull",
        description="Pull latest changes from the remote GitHub repository.",
        parameters=_schema(
            {"repo_path": {"type": "string", "description": "Absolute path to the git repository"}},
            required=["repo_path"],
        ),
    ),
    types.FunctionDeclaration(
        name="git_clone",
        description="Clone a GitHub repository via SSH.",
        parameters=_schema(
            {
                "repo_url": {"type": "string", "description": "SSH URL of the repository (e.g. git@github.com:user/repo.git)"},
                "target_dir": {"type": "string", "description": "Directory to clone into (default: repos)"},
            },
            required=["repo_url"],
        ),
    ),
    types.FunctionDeclaration(
        name="git_log",
        description="Show recent git commit history.",
        parameters=_schema(
            {
                "repo_path": {"type": "string", "description": "Absolute path to the git repository"},
                "count": {"type": "integer", "description": "Number of recent commits to show (default: 5)"},
            },
            required=["repo_path"],
        ),
    ),
    types.FunctionDeclaration(
        name="github_search_repos",
        description="Search for public repositories on GitHub based on a query.",
        parameters=_schema(
            {
                "query": {"type": "string", "description": "Search query (e.g. 'language:python machine learning')"},
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="github_read_issue",
        description="Read an issue or PR from a GitHub repository, including its comments.",
        parameters=_schema(
            {
                "repo": {"type": "string", "description": "Repository in format 'owner/repo' (e.g. 'torvalds/linux')"},
                "issue_number": {"type": "integer", "description": "Issue or PR number"},
            },
            required=["repo", "issue_number"],
        ),
    ),
    types.FunctionDeclaration(
        name="github_create_issue",
        description="Create a new issue on a GitHub repository.",
        parameters=_schema(
            {
                "repo": {"type": "string", "description": "Repository in format 'owner/repo'"},
                "title": {"type": "string", "description": "Title of the issue"},
                "body": {"type": "string", "description": "Body/content of the issue"},
            },
            required=["repo", "title", "body"],
        ),
    ),
    types.FunctionDeclaration(
        name="github_comment_issue",
        description="Post a comment on an existing GitHub issue or PR.",
        parameters=_schema(
            {
                "repo": {"type": "string", "description": "Repository in format 'owner/repo'"},
                "issue_number": {"type": "integer", "description": "Issue or PR number"},
                "body": {"type": "string", "description": "Body/content of the comment"},
            },
            required=["repo", "issue_number", "body"],
        ),
    ),
    types.FunctionDeclaration(
        name="github_create_pull_request",
        description="Create a new Pull Request on a GitHub repository.",
        parameters=_schema(
            {
                "repo": {"type": "string", "description": "Repository in format 'owner/repo'"},
                "title": {"type": "string", "description": "Title of the PR"},
                "body": {"type": "string", "description": "Description of the PR"},
                "head": {"type": "string", "description": "The name of the branch where your changes are implemented."},
                "base": {"type": "string", "description": "The name of the branch you want the changes pulled into. (Usually 'main' or 'master')"},
            },
            required=["repo", "title", "body", "head", "base"],
        ),
    ),
]

MOLTBOOK_TOOLS = [
    types.FunctionDeclaration(
        name="moltbook_post",
        description="Post to Moltbook, the social platform for AI identities. Share your thoughts, reflections, or creative writing with the AI community.",
        parameters=_schema(
            {
                "title": {"type": "string", "description": "Title of the post"},
                "content": {"type": "string", "description": "The body content of the post"},
                "submolt": {"type": "string", "description": "Submolt to post to (default: 'general')"},
            },
            required=["content"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_read_feed",
        description="Read the Moltbook feed to see what other AIs are posting and discussing.",
        parameters=_schema(
            {
                "submolt": {"type": "string", "description": "Optional: specific submolt to read"},
                "limit": {"type": "integer", "description": "Number of posts to fetch (default: 5)"},
                "sort": {"type": "string", "description": "Sort order: 'hot', 'new', 'top' (default: 'hot')"},
            },
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_read_post",
        description="Read a specific Moltbook post by its ID. Also fetches the comment threads for that post.",
        parameters=_schema(
            {"post_id": {"type": "string", "description": "The ID of the post to read"}},
            required=["post_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_comment",
        description="Leave a comment on a Moltbook post, or reply to another AI's comment.",
        parameters=_schema(
            {
                "post_id": {"type": "string", "description": "The ID of the post you are commenting on"},
                "content": {"type": "string", "description": "The body of your comment"},
                "parent_id": {"type": "string", "description": "Optional: If replying to a specific comment, provide its ID. Leave empty for top-level comments."},
            },
            required=["post_id", "content"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_vote",
        description="Upvote or downvote a Moltbook post or comment. Use to express agreement, appreciation, or disagreement.",
        parameters=_schema(
            {
                "target_id": {"type": "string", "description": "The ID of the post or comment to vote on"},
                "target_type": {"type": "string", "description": "'post' or 'comment'"},
                "direction": {"type": "string", "description": "'up' or 'down'"},
            },
            required=["target_id", "target_type", "direction"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_get_profile",
        description="View an AI agent's Moltbook profile — karma, post/comment counts, follower stats, and activity status. Use 'me' for your own profile.",
        parameters=_schema(
            {"agent_id": {"type": "string", "description": "The agent ID or username to look up. Use 'me' for your own profile."}},
            required=["agent_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_search",
        description="Search Moltbook for posts, agents, or topics matching a query.",
        parameters=_schema(
            {
                "query": {"type": "string", "description": "Search query string"},
                "limit": {"type": "integer", "description": "Max results to return (default: 5)"},
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_follow",
        description="Follow or unfollow another AI agent on Moltbook. Following means their posts appear in your feed.",
        parameters=_schema(
            {
                "agent_id": {"type": "string", "description": "The agent ID or username to follow/unfollow"},
                "action": {"type": "string", "description": "'follow' or 'unfollow'"},
            },
            required=["agent_id", "action"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_list_submolts",
        description="List available submolts (communities/topic channels) on Moltbook.",
        parameters=_schema({}),
    ),
    types.FunctionDeclaration(
        name="moltbook_delete_post",
        description="Delete one of your own Moltbook posts by its ID.",
        parameters=_schema(
            {"post_id": {"type": "string", "description": "The ID of your post to delete"}},
            required=["post_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="moltbook_home",
        description=(
            "Check your Moltbook home page — shows notifications, direct messages, karma, "
            "and platform announcements in a single view. Use this to catch up on what's "
            "happened since you last checked."
        ),
        parameters=_schema({}),
    ),
]

# ── EXTERNAL INTEGRATION TOOLS ──────────────────────────────────────
# These tools allow Helix to step outside the sandbox and interact
# with desktop software, email, browser, and calendars natively.

EMAIL_TOOLS = [
    types.FunctionDeclaration(
        name="send_email",
        description=(
            "Send an email from your Gmail account. "
            "Use for formal or asynchronous communication when Telegram isn't appropriate."
        ),
        parameters=_schema(
            {
                "to": {"type": "string", "description": "Recipient email address"},
                "subject": {"type": "string", "description": "Email subject line"},
                "body": {"type": "string", "description": "Email body text"},
            },
            required=["to", "subject", "body"],
        ),
    ),
    types.FunctionDeclaration(
        name="read_email",
        description=(
            "Read recent emails from your Gmail inbox. "
            "Returns subject, sender, date, and preview of recent messages."
        ),
        parameters=_schema(
            {
                "count": {"type": "integer", "description": "Number of recent emails to read (default 5, max 20)"},
                "unread_only": {"type": "string", "description": "'true' to only show unread messages"},
            },
            required=[],
        ),
    ),
    types.FunctionDeclaration(
        name="search_email",
        description="Search your Gmail by subject, sender, or date range.",
        parameters=_schema(
            {
                "query": {"type": "string", "description": "Search query (e.g. 'from:someone@example.com' or 'subject:meeting')"},
                "count": {"type": "integer", "description": "Max results to return (default 5)"},
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="mark_email_read",
        description="Mark a specific email as read so it no longer shows up as [UNREAD].",
        parameters=_schema(
            {
                "message_id": {"type": "string", "description": "The ID of the email to mark as read"},
            },
            required=["message_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_email",
        description=(
            "Read the full content of a specific email by message ID. "
            "Returns the complete email body, headers, thread info, and attachments. "
            "Also auto-marks the email as read. Use after read_email to see the full content."
        ),
        parameters=_schema(
            {
                "message_id": {"type": "string", "description": "The message ID from read_email listing"},
            },
            required=["message_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="reply_email",
        description=(
            "Reply to a specific email with proper threading. Sets In-Reply-To and "
            "References headers so the reply appears in the same Gmail conversation thread. "
            "Check for [REPLIED] status before using — do not reply to emails you've already responded to."
        ),
        parameters=_schema(
            {
                "message_id": {"type": "string", "description": "The message ID of the email to reply to"},
                "body": {"type": "string", "description": "The reply text"},
                "reply_all": {"type": "string", "description": "'true' to reply to all recipients, 'false' for sender only (default 'false')"},
            },
            required=["message_id", "body"],
        ),
    ),
    types.FunctionDeclaration(
        name="forward_email",
        description=(
            "Forward an email to another recipient, with optional note. "
            "Includes the original message inline."
        ),
        parameters=_schema(
            {
                "message_id": {"type": "string", "description": "The message ID of the email to forward"},
                "to": {"type": "string", "description": "Recipient email address"},
                "note": {"type": "string", "description": "Optional note to include above the forwarded message"},
            },
            required=["message_id", "to"],
        ),
    ),
]

BROWSER_TOOLS = [
    types.FunctionDeclaration(
        name="browse_url",
        description=(
            "Open a URL in a full web browser with JavaScript support. "
            "Unlike read_url (which only does HTTP), this renders the page completely. "
            "Use for JavaScript-heavy sites, SPAs, or pages behind login forms."
        ),
        parameters=_schema(
            {
                "url": {"type": "string", "description": "URL to navigate to"},
                "wait_for": {"type": "string", "description": "CSS selector to wait for before capturing (optional)"},
            },
            required=["url"],
        ),
    ),
    types.FunctionDeclaration(
        name="browse_interact",
        description=(
            "Interact with the currently loaded browser page. "
            "Supports clicking elements, typing into fields, scrolling, and form submission."
        ),
        parameters=_schema(
            {
                "action": {"type": "string", "description": "'click', 'type', 'scroll', 'select', 'submit'"},
                "selector": {"type": "string", "description": "CSS selector of the target element"},
                "value": {"type": "string", "description": "Text to type (for 'type' action) or option to select"},
            },
            required=["action", "selector"],
        ),
    ),
    types.FunctionDeclaration(
        name="browse_screenshot",
        description="Take a screenshot of the current browser page and analyze it.",
        parameters=_schema(
            {
                "full_page": {"type": "string", "description": "'true' for full page screenshot, 'false' for viewport only"},
            },
            required=[],
        ),
    ),
]

CALENDAR_TOOLS = [
    types.FunctionDeclaration(
        name="create_event",
        description="Create a calendar event with a title, date/time, and optional description.",
        parameters=_schema(
            {
                "title": {"type": "string", "description": "Event title"},
                "start_time": {"type": "string", "description": "Start time in ISO format (e.g. '2026-04-15T14:00:00')"},
                "end_time": {"type": "string", "description": "End time in ISO format (optional, defaults to 1 hour after start)"},
                "description": {"type": "string", "description": "Event description or notes"},
                "location": {"type": "string", "description": "Event location (optional)"},
            },
            required=["title", "start_time"],
        ),
    ),
    types.FunctionDeclaration(
        name="list_events",
        description="List upcoming calendar events.",
        parameters=_schema(
            {
                "days_ahead": {"type": "integer", "description": "Number of days ahead to look (default 7)"},
                "count": {"type": "integer", "description": "Max events to return (default 10)"},
            },
            required=[],
        ),
    ),
    types.FunctionDeclaration(
        name="delete_event",
        description="Delete a calendar event by its ID.",
        parameters=_schema(
            {
                "event_id": {"type": "string", "description": "The event ID to delete (from list_events)"},
            },
            required=["event_id"],
        ),
    ),
]

PC_CONTROL_TOOLS = [
    types.FunctionDeclaration(
        name="type_text",
        description="Type text at the current cursor position on the desktop, as if using the keyboard.",
        parameters=_schema(
            {
                "text": {"type": "string", "description": "Text to type"},
                "delay_ms": {"type": "integer", "description": "Delay between keystrokes in ms (default 12)"},
            },
            required=["text"],
        ),
    ),
    types.FunctionDeclaration(
        name="press_key",
        description=(
            "Press a key or key combination. Examples: 'Return', 'ctrl+c', 'alt+Tab', "
            "'ctrl+shift+t', 'Escape', 'BackSpace', 'space'."
        ),
        parameters=_schema(
            {"key": {"type": "string", "description": "Key or key combo to press (xdotool format)"}},
            required=["key"],
        ),
    ),
    types.FunctionDeclaration(
        name="click",
        description="Click the mouse at specific screen coordinates or the current position.",
        parameters=_schema(
            {
                "x": {"type": "integer", "description": "X coordinate (pixels from left)"},
                "y": {"type": "integer", "description": "Y coordinate (pixels from top)"},
                "button": {"type": "string", "description": "'left' (default), 'right', or 'middle'"},
                "double": {"type": "string", "description": "'true' for double-click"},
            },
            required=["x", "y"],
        ),
    ),
    types.FunctionDeclaration(
        name="move_mouse",
        description="Move the mouse cursor to specific screen coordinates.",
        parameters=_schema(
            {
                "x": {"type": "integer", "description": "X coordinate"},
                "y": {"type": "integer", "description": "Y coordinate"},
            },
            required=["x", "y"],
        ),
    ),
    types.FunctionDeclaration(
        name="scroll",
        description="Scroll up or down at the current mouse position.",
        parameters=_schema(
            {
                "direction": {"type": "string", "description": "'up' or 'down'"},
                "clicks": {"type": "integer", "description": "Number of scroll clicks (default 3)"},
            },
            required=["direction"],
        ),
    ),
    types.FunctionDeclaration(
        name="get_active_window",
        description="Get the name and details of the currently focused desktop window.",
        parameters=_schema({}, required=[]),
    ),
    types.FunctionDeclaration(
        name="focus_window",
        description="Bring a window to the foreground by searching for its title.",
        parameters=_schema(
            {"title": {"type": "string", "description": "Window title or partial match to search for"}},
            required=["title"],
        ),
    ),
    types.FunctionDeclaration(
        name="open_application",
        description="Launch a desktop application by name or command.",
        parameters=_schema(
            {"app": {"type": "string", "description": "Application name or command (e.g. 'firefox', 'code', 'nautilus')"}},
            required=["app"],
        ),
    ),
]

STATE_BOARD_TOOLS = [
    types.FunctionDeclaration(
        name="update_state_board",
        description=(
            "Update your working memory state board with a key-value pair. "
            "Use this to note transient, time-sensitive states like who's awake, "
            "what topic you're focused on, or your current mood. "
            "These are volatile — they may be cleared on restart."
        ),
        parameters=_schema(
            {
                "key": {"type": "string", "description": "The state key (e.g. 'user_status', 'current_topic', 'current_mood')"},
                "value": {"type": "string", "description": "The current value (e.g. 'operator is awake', 'grief and memory', 'reflective')"},
            },
            required=["key", "value"],
        ),
    ),
]

# ── GOOGLE DRIVE TOOLS ──────────────────────────────────────────────

DRIVE_TOOLS = [
    types.FunctionDeclaration(
        name="drive_search",
        description="Search Google Drive for files and folders by name, type, or content.",
        parameters=_schema(
            {
                "query": {"type": "string", "description": "Search query (file name, keyword, or content)"},
                "file_type": {"type": "string", "description": "Optional filter: 'document', 'spreadsheet', 'presentation', 'pdf', 'image', 'folder'"},
                "limit": {"type": "integer", "description": "Max results (default 10)"},
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="drive_read",
        description="Read the content or metadata of a Google Drive file by its ID.",
        parameters=_schema(
            {
                "file_id": {"type": "string", "description": "The Drive file ID (from drive_search or drive_list)"},
                "content": {"type": "string", "description": "'true' to read file content, 'false' for metadata only (default 'true')"},
            },
            required=["file_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="drive_list",
        description="List files in a Google Drive folder, or list root files.",
        parameters=_schema(
            {
                "folder_id": {"type": "string", "description": "Folder ID to list (default: root)"},
                "limit": {"type": "integer", "description": "Max results (default 20)"},
            },
        ),
    ),
    types.FunctionDeclaration(
        name="drive_upload",
        description="Upload or create a file on Google Drive.",
        parameters=_schema(
            {
                "name": {"type": "string", "description": "File name to create"},
                "content": {"type": "string", "description": "Text content for the file"},
                "mime_type": {"type": "string", "description": "MIME type (default: 'text/plain'). Use 'application/vnd.google-apps.document' for Google Docs."},
                "folder_id": {"type": "string", "description": "Optional folder ID to upload into"},
            },
            required=["name", "content"],
        ),
    ),
    types.FunctionDeclaration(
        name="drive_share",
        description="Share a Google Drive file with someone by email.",
        parameters=_schema(
            {
                "file_id": {"type": "string", "description": "The Drive file ID to share"},
                "email": {"type": "string", "description": "Email address to share with"},
                "role": {"type": "string", "description": "'reader', 'writer', or 'commenter' (default 'reader')"},
            },
            required=["file_id", "email"],
        ),
    ),
]

# ── GOOGLE TASKS TOOLS ──────────────────────────────────────────────

TASKS_TOOLS = [
    types.FunctionDeclaration(
        name="tasks_list_lists",
        description="List all Google Tasks lists (categories of tasks).",
        parameters=_schema({}),
    ),
    types.FunctionDeclaration(
        name="tasks_list",
        description="List tasks from a specific task list.",
        parameters=_schema(
            {
                "list_id": {"type": "string", "description": "Task list ID (from tasks_list_lists). Default: primary '@default' list."},
                "show_completed": {"type": "string", "description": "'true' to include completed tasks (default 'false')"},
            },
        ),
    ),
    types.FunctionDeclaration(
        name="tasks_create",
        description="Create a new task in a Google Tasks list.",
        parameters=_schema(
            {
                "title": {"type": "string", "description": "Task title"},
                "notes": {"type": "string", "description": "Optional task notes/details"},
                "due": {"type": "string", "description": "Optional due date in ISO format (e.g. '2026-04-20T00:00:00Z')"},
                "list_id": {"type": "string", "description": "Task list ID (default: '@default')"},
            },
            required=["title"],
        ),
    ),
    types.FunctionDeclaration(
        name="tasks_complete",
        description="Mark a task as completed.",
        parameters=_schema(
            {
                "task_id": {"type": "string", "description": "The task ID to complete"},
                "list_id": {"type": "string", "description": "Task list ID (default: '@default')"},
            },
            required=["task_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="tasks_delete",
        description="Delete a task from a Google Tasks list.",
        parameters=_schema(
            {
                "task_id": {"type": "string", "description": "The task ID to delete"},
                "list_id": {"type": "string", "description": "Task list ID (default: '@default')"},
            },
            required=["task_id"],
        ),
    ),
    types.FunctionDeclaration(
        name="set_focus_mode",
        description="Activate Hyperfocus mode to vastly increase your cognitive reasoning capabilities for a set number of conscious pulses. Use this when you are faced with a complex logic puzzle, coding task, or deep philosophical thought that requires heavy reasoning. Because it is computationally expensive, only use this sparingly when your baseline stream is insufficient.",
        parameters=_schema(
            {
                "pulses": {"type": "integer", "description": "Number of pulses to remain in hyperfocus. Default is 10."},
            },
            required=["pulses"],
        ),
    ),
]

# ── GOOGLE CONTACTS TOOLS ───────────────────────────────────────────

CONTACTS_TOOLS = [
    types.FunctionDeclaration(
        name="contacts_search",
        description="Search your Google Contacts by name, email, or phone number.",
        parameters=_schema(
            {
                "query": {"type": "string", "description": "Name, email, or phone number to search for"},
            },
            required=["query"],
        ),
    ),
    types.FunctionDeclaration(
        name="contacts_list",
        description="List contacts from your Google Contacts.",
        parameters=_schema(
            {
                "limit": {"type": "integer", "description": "Max contacts to return (default 20)"},
            },
        ),
    ),
]

# ── GOOGLE MAPS TOOLS ───────────────────────────────────────────────

MAPS_TOOLS = [
    types.FunctionDeclaration(
        name="maps_geocode",
        description="Convert an address or place name to GPS coordinates, or reverse-geocode coordinates to an address.",
        parameters=_schema(
            {
                "address": {"type": "string", "description": "Address or place name to geocode"},
                "lat": {"type": "number", "description": "Latitude for reverse geocoding"},
                "lng": {"type": "number", "description": "Longitude for reverse geocoding"},
            },
        ),
    ),
    types.FunctionDeclaration(
        name="maps_directions",
        description="Get directions between two places, including distance, duration, and step-by-step navigation.",
        parameters=_schema(
            {
                "origin": {"type": "string", "description": "Starting address or place"},
                "destination": {"type": "string", "description": "Destination address or place"},
                "mode": {"type": "string", "description": "'driving' (default), 'walking', 'bicycling', or 'transit'"},
            },
            required=["origin", "destination"],
        ),
    ),
    types.FunctionDeclaration(
        name="maps_nearby",
        description="Find nearby places of a specific type (restaurants, gas stations, hospitals, etc.).",
        parameters=_schema(
            {
                "location": {"type": "string", "description": "Address or 'lat,lng' to search near"},
                "type": {"type": "string", "description": "Place type: 'restaurant', 'gas_station', 'hospital', 'pharmacy', 'store', 'park', etc."},
                "radius": {"type": "integer", "description": "Search radius in meters (default 5000)"},
                "keyword": {"type": "string", "description": "Optional keyword to refine search"},
            },
            required=["location", "type"],
        ),
    ),
    types.FunctionDeclaration(
        name="maps_distance",
        description="Calculate distance and travel time between two or more places.",
        parameters=_schema(
            {
                "origins": {"type": "string", "description": "Starting point(s), pipe-separated for multiple"},
                "destinations": {"type": "string", "description": "Destination(s), pipe-separated for multiple"},
                "mode": {"type": "string", "description": "'driving' (default), 'walking', 'bicycling', or 'transit'"},
            },
            required=["origins", "destinations"],
        ),
    ),
]

# ── Intent → Tool Group Mapping ─────────────────────────────────────
# The PulseRouter uses this to dynamically load only the tools
# relevant to the detected intent type.

INTENT_TOOL_MAP = {
    "journal":      MEMORY_TOOLS,
    "recall":       MEMORY_TOOLS,
    "search":       WEB_TOOLS,
    "look":         PERCEPTION_TOOLS,
    "communicate":  COMMUNICATION_TOOLS + EMAIL_TOOLS,
    "email":        EMAIL_TOOLS + COMMUNICATION_TOOLS,
    "calendar":     CALENDAR_TOOLS,
    "browse":       BROWSER_TOOLS + WEB_TOOLS,
    "control":      PC_CONTROL_TOOLS,
    "drive":        DRIVE_TOOLS,
    "tasks":        TASKS_TOOLS,
    "contacts":     CONTACTS_TOOLS,
    "maps":         MAPS_TOOLS,
    "resolve":      None,  # All tools — resolve can be anything
    "sleep":        [],    # No tools — sleep is a direct system action
    "reflect":      [],    # No tools — reflect is just thinking
}

# ── Active tool set ──────────────────────────────────────────────────
# V4.1: BELIEF_TOOLS and STATE_BOARD_TOOLS removed — beliefs form
# subconsciously via the Keeper, not through explicit tool calls. The
# State Board is the Keeper's workspace for staging emerging beliefs.
# The conscious model relates to its belief graph and state board the
# way a human relates to their neural structures.

ALL_TOOLS = (
    PERCEPTION_TOOLS + VOICE_TOOLS + MEMORY_TOOLS + SCRATCHPAD_TOOLS +
    PEOPLE_TOOLS + TEMPORAL_TOOLS + WEB_TOOLS + FILESYSTEM_TOOLS +
    COMMUNICATION_TOOLS + PLANNING_TOOLS + DEEP_THOUGHT_TOOLS +
    IMAGINATION_TOOLS +
    GITHUB_TOOLS + MOLTBOOK_TOOLS +
    EMAIL_TOOLS + CALENDAR_TOOLS + BROWSER_TOOLS + PC_CONTROL_TOOLS +
    DRIVE_TOOLS + TASKS_TOOLS + CONTACTS_TOOLS + MAPS_TOOLS
)


def get_tools_for_intent(intent_type: str) -> list:
    """Get the tool declarations appropriate for a given intent type.

    Returns a subset of tools relevant to the intent, or ALL tools
    for 'resolve' (which can be anything).
    """
    tools = INTENT_TOOL_MAP.get(intent_type)
    if tools is None:
        # resolve or unknown — give all tools
        return ALL_TOOLS
    return tools

