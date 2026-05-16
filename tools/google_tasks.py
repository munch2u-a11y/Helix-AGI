"""
Helix — Google Tasks API Tools

Provides Google Tasks operations via action tags:
  [TASKS_LISTS:]               — list all task lists
  [TASKS_LIST:list_id]         — list tasks in a list
  [TASKS_CREATE:list_id] title | notes | due
  [TASKS_COMPLETE:list_id] task_id
  [TASKS_DELETE:list_id] task_id

All operations use the shared Google OAuth2 credentials
from tools/google_auth.py.
"""

import logging

logger = logging.getLogger("helix.tools.google_tasks")


def tasks_list_lists() -> str:
    """List all task lists."""
    from tools.google_auth import get_tasks_service

    service = get_tasks_service()
    if not service:
        return "Google Tasks not configured. Run google_auth.py first."

    try:
        results = service.tasklists().list(maxResults=20).execute()
        lists = results.get("items", [])
        if not lists:
            return "No task lists found."

        lines = ["Task Lists:"]
        for tl in lists:
            lines.append(f"  • {tl['title']} (id: {tl['id']})")
        return "\n".join(lines)
    except Exception as e:
        return f"Tasks list failed: {e}"


def tasks_list(list_id: str = "@default", show_completed: bool = False) -> str:
    """List tasks from a task list."""
    from tools.google_auth import get_tasks_service

    service = get_tasks_service()
    if not service:
        return "Google Tasks not configured."

    try:
        results = service.tasks().list(
            tasklist=list_id, showCompleted=show_completed, maxResults=50
        ).execute()
        tasks = results.get("items", [])
        if not tasks:
            return "No tasks found."

        lines = [f"Tasks ({len(tasks)}):"]
        for t in tasks:
            status = "✅" if t.get("status") == "completed" else "☐"
            due = f" (due: {t['due'][:10]})" if t.get("due") else ""
            notes = f"\n    Notes: {t['notes'][:80]}" if t.get("notes") else ""
            lines.append(f"  {status} {t['title']}{due} [id: {t['id']}]{notes}")
        return "\n".join(lines)
    except Exception as e:
        return f"Tasks list failed: {e}"


def tasks_create(title: str, notes: str = "", due: str = "",
                 list_id: str = "@default") -> str:
    """Create a new task."""
    from tools.google_auth import get_tasks_service

    service = get_tasks_service()
    if not service:
        return "Google Tasks not configured."

    if not title:
        return "Task title required."

    try:
        task_body = {"title": title}
        if notes:
            task_body["notes"] = notes
        if due:
            task_body["due"] = due

        result = service.tasks().insert(tasklist=list_id, body=task_body).execute()
        return f"Task created: '{result['title']}' (id: {result['id']})"
    except Exception as e:
        return f"Task creation failed: {e}"


def tasks_complete(task_id: str, list_id: str = "@default") -> str:
    """Mark a task as completed."""
    from tools.google_auth import get_tasks_service

    service = get_tasks_service()
    if not service:
        return "Google Tasks not configured."

    if not task_id:
        return "task_id required."

    try:
        task = service.tasks().get(tasklist=list_id, task=task_id).execute()
        task["status"] = "completed"
        result = service.tasks().update(
            tasklist=list_id, task=task_id, body=task
        ).execute()
        return f"Task '{result['title']}' marked complete."
    except Exception as e:
        return f"Task complete failed: {e}"


def tasks_delete(task_id: str, list_id: str = "@default") -> str:
    """Delete a task."""
    from tools.google_auth import get_tasks_service

    service = get_tasks_service()
    if not service:
        return "Google Tasks not configured."

    if not task_id:
        return "task_id required."

    try:
        service.tasks().delete(tasklist=list_id, task=task_id).execute()
        return f"Task {task_id} deleted."
    except Exception as e:
        return f"Task delete failed: {e}"
