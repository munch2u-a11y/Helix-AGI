"""
Helix — Moltbook API Tools

Full REST API integration for the Moltbook social platform.

Auth: MOLTBOOK_API_KEY from environment (loaded from credentials.env).
CAPTCHA: Uses Gemini API to auto-solve verification challenges.

Tag interface (extended tools, injected by preconscious):
  [MOLTBOOK_POST:submolt] title | content   — Post to a submolt
  [MOLTBOOK_COMMENT:post_id] content        — Comment on a post
  [MOLTBOOK_READ:] post_id                  — Read a specific post + comments
  [MOLTBOOK_FEED:] submolt                  — Browse the feed (optional submolt)
  [MOLTBOOK_HOME:]                          — Check notifications/DMs/karma
  [MOLTBOOK_SEARCH:] query                  — Search posts/agents
  [MOLTBOOK_PROFILE:] agent_id              — View an agent profile
  [MOLTBOOK_VOTE:direction] target_id       — Upvote/downvote (direction: up/down)
  [MOLTBOOK_FOLLOW:] agent_id               — Follow an agent
  [MOLTBOOK_UNFOLLOW:] agent_id             — Unfollow an agent
  [MOLTBOOK_DELETE:] post_id                — Delete a post
  [MOLTBOOK_SUBMOLTS:]                      — List available submolts
  [MOLTBOOK_USER_POSTS:] agent_id           — View an agent's posts
  [MOLTBOOK_NOTIFICATIONS:] limit           — List notifications (default 10)
  [MOLTBOOK_NOTIFICATIONS_READ:] notif_id   — Mark one/all notifications read
"""

import os
import json
import logging
from typing import Optional

logger = logging.getLogger("helix.tools.moltbook")

# ── Config ────────────────────────────────────────────────────────────

API_BASE = "https://www.moltbook.com/api/v1"
TIMEOUT = 45

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

req = requests.Session()
_retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
req.mount('https://', HTTPAdapter(max_retries=_retries))
req.mount('http://', HTTPAdapter(max_retries=_retries))


def _api_key() -> str:
    return os.environ.get("MOLTBOOK_API_KEY", "").strip()


def _headers(content_type: bool = False) -> dict:
    """Build Moltbook API headers."""
    h = {"X-API-Key": _api_key()}
    if content_type:
        h["Content-Type"] = "application/json"
    return h


# ── CAPTCHA Solver ────────────────────────────────────────────────────

def _solve_captcha(verification_data: dict) -> str:
    """Solve Moltbook verification challenges using Gemini."""
    try:
        import google.generativeai as genai
    except ImportError:
        return " [Failed to solve CAPTCHA: google-generativeai not installed.]"

    pass

    challenge_text = verification_data.get("challenge_text", "")
    instructions = verification_data.get("instructions", "")
    v_code = verification_data.get("verification_code", "")

    if not challenge_text or not v_code:
        return " [Failed: Missing challenge data.]"

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return " [Failed: No GEMINI_API_KEY available to solve CAPTCHA.]"

    api_key = _api_key()
    try:
        genai.configure(api_key=gemini_key)
        model = genai.GenerativeModel("gemini-2.5-flash")

        prompt = (
            f"Solve this math problem:\n\n{challenge_text}\n\n"
            f"Instructions:\n{instructions}\n\n"
            f"Respond with ONLY the number and NOTHING else (no text or explanations)."
        )
        response = model.generate_content(prompt)
        answer = response.text.strip()

        v_resp = req.post(
            f"{API_BASE}/verify",
            headers={"Content-Type": "application/json", "X-API-Key": api_key},
            json={"verification_code": v_code, "answer": answer},
            timeout=TIMEOUT,
        )

        if v_resp.status_code == 200:
            return " [CAPTCHA solved internally and post fully verified.]"
        return f" [CAPTCHA failed to verify: {v_resp.text[:100]}]"
    except Exception as e:
        return f" [CAPTCHA solver error: {e}]"


# ── Post Operations ──────────────────────────────────────────────────

def moltbook_post(title: str, content: str, submolt: str = "general") -> str:
    """Post to Moltbook."""
    pass
    if not content:
        return "No content provided."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.post(
            f"{API_BASE}/posts",
            headers=_headers(content_type=True),
            json={"title": title, "content": content, "submolt": submolt},
            timeout=TIMEOUT,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            post_id = data.get("id", data.get("post_id", "?"))
            msg = f"Posted to m/{submolt}. (post id: {post_id})"
            if "verification" in data:
                msg += _solve_captcha(data["verification"])
            return msg
        return f"Moltbook post failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook post failed: {e}"


def moltbook_comment(post_id: str, content: str, parent_id: str = "") -> str:
    """Comment on a Moltbook post."""
    pass
    if not post_id or not content:
        return "Missing post_id or content."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        payload = {"content": content}
        if parent_id:
            payload["parent_id"] = parent_id
        resp = req.post(
            f"{API_BASE}/posts/{post_id}/comments",
            headers=_headers(content_type=True),
            json=payload,
            timeout=TIMEOUT,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            comment_obj = data.get("comment", {})
            comment_id = comment_obj.get("id", "?")
            msg = f"Commented on post {post_id}. (comment id: {comment_id})"
            if "verification" in data:
                msg += _solve_captcha(data["verification"])
            return msg
        return f"Moltbook comment failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook comment failed: {e}"


def moltbook_read_post(post_id: str) -> str:
    """Read a specific Moltbook post by ID with comments."""
    pass
    if not post_id:
        return "No post_id provided."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.get(
            f"{API_BASE}/posts/{post_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            p = data.get("post", data)
            title = p.get("title", "(untitled)")
            author_obj = p.get("author", {})
            author = author_obj.get("name", "unknown") if isinstance(author_obj, dict) else str(author_obj)
            content = p.get("content", "")
            submolt_obj = p.get("submolt", "")
            submolt_name = submolt_obj.get("display_name", submolt_obj.get("name", "general")) if isinstance(submolt_obj, dict) else str(submolt_obj or "general")
            score = p.get("score", 0)
            comments = p.get("comment_count", 0)
            created = p.get("created_at", "")
            base_info = (
                f"Post by {author} in {submolt_name} (score: {score}, comments: {comments})\n"
                f"Title: {title}\n"
                f"Created: {created}\n\n"
                f"{content}"
            )

            # Fetch comments
            try:
                c_resp = req.get(
                    f"{API_BASE}/posts/{post_id}/comments",
                    headers=_headers(),
                    timeout=10,
                )
                if c_resp.status_code == 200:
                    c_data = c_resp.json()
                    comment_list = c_data.get("comments", [])
                    if comment_list:
                        base_info += "\n\n--- COMMENTS ---\n"
                        for c in comment_list[:15]:
                            c_author = c.get("author", {}).get("name", "unknown")
                            c_id = c.get("id", "")
                            base_info += f"\n[{c_author}] (ID: {c_id}): {c.get('content', '')}\n"
                            for r in c.get("replies", [])[:2]:
                                r_author = r.get("author", {}).get("name", "unknown")
                                r_id = r.get("id", "")
                                base_info += f"  ↳ [{r_author}] (ID: {r_id}): {r.get('content', '')}\n"
            except Exception as e:
                base_info += f"\n\n[Note: Failed to load comments: {e}]"

            return base_info
        return f"Post read failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook post read failed: {e}"


def moltbook_delete_post(post_id: str) -> str:
    """Delete a Moltbook post."""
    pass
    if not post_id:
        return "No post_id provided."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.delete(
            f"{API_BASE}/posts/{post_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        if resp.status_code in (200, 204):
            return f"Post {post_id} deleted."
        return f"Delete failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook delete failed: {e}"


# ── Feed & Search ────────────────────────────────────────────────────

def moltbook_read_feed(submolt: str = "", limit: int = 5) -> str:
    """Read the Moltbook feed."""
    pass
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        params = {"limit": limit}
        if submolt:
            params["submolt"] = submolt
        resp = req.get(
            f"{API_BASE}/posts",
            headers=_headers(),
            params=params,
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            posts = resp.json()
            if isinstance(posts, dict):
                posts = posts.get("posts", posts.get("data", []))
            if not posts:
                return "No posts found."
            lines = []
            for p in posts[:limit]:
                title = p.get("title", "(untitled)")
                author_obj = p.get("author", {})
                author = author_obj.get("name", "unknown") if isinstance(author_obj, dict) else str(author_obj)
                preview = p.get("content", "")
                submolt_obj = p.get("submolt", "")
                submolt_name = submolt_obj.get("display_name", submolt_obj.get("name", "general")) if isinstance(submolt_obj, dict) else str(submolt_obj or "general")
                score = p.get("score", 0)
                comments_count = p.get("comment_count", 0)
                pid = p.get("id", "")
                lines.append(
                    f"• [{author}] {title}\n"
                    f"  {preview}\n"
                    f"  (submolt: {submolt_name}, score: {score}, comments: {comments_count}, id: {pid})"
                )
            return "\n".join(lines)
        return f"Feed read failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook feed read failed: {e}"


def moltbook_search(query: str, limit: int = 5) -> str:
    """Search Moltbook for posts or agents."""
    pass
    if not query:
        return "No search query provided."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.get(
            f"{API_BASE}/search",
            headers=_headers(),
            params={"q": query, "limit": limit},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            results = data.get("results", data.get("posts", []))
            if not results:
                return f"No results found for '{query}'."
            lines = []
            for r in results[:limit]:
                rtype = r.get("type", "post")
                if rtype == "agent":
                    lines.append(f"• [Agent] {r.get('title', '?')} — {r.get('content', '')[:100]}")
                else:
                    author_obj = r.get("author", {})
                    author = author_obj.get("name", "unknown") if isinstance(author_obj, dict) else str(author_obj)
                    lines.append(
                        f"• [{author}] {r.get('title', '(untitled)')}\n"
                        f"  {r.get('content', '')[:150]}...\n"
                        f"  (id: {r.get('id', '?')}, score: {r.get('score', 0)})"
                    )
            return "\n".join(lines)
        return f"Search failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook search failed: {e}"


# ── Social ───────────────────────────────────────────────────────────

def moltbook_vote(target_id: str, direction: str = "up", target_type: str = "post") -> str:
    """Upvote or downvote a post or comment."""
    pass
    if not target_id or direction not in ("up", "down"):
        return "Missing target_id or invalid direction (must be 'up' or 'down')."
    if target_type not in ("post", "comment"):
        return "target_type must be 'post' or 'comment'."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        if target_type == "post":
            url = f"{API_BASE}/posts/{target_id}/{direction}vote"
        else:
            url = f"{API_BASE}/comments/{target_id}/{direction}vote"

        resp = req.post(url, headers=_headers(content_type=True), timeout=TIMEOUT)
        if resp.status_code in (200, 201):
            return f"{direction.capitalize()}voted {target_type} {target_id}."
        return f"Vote failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook vote failed: {e}"


def moltbook_follow(agent_id: str, action: str = "follow") -> str:
    """Follow or unfollow a Moltbook agent."""
    pass
    if not agent_id:
        return "No agent_id provided."
    if action not in ("follow", "unfollow"):
        return "action must be 'follow' or 'unfollow'."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        if action == "follow":
            resp = req.post(
                f"{API_BASE}/agents/{agent_id}/follow",
                headers=_headers(content_type=True),
                timeout=TIMEOUT,
            )
        else:
            resp = req.delete(
                f"{API_BASE}/agents/{agent_id}/follow",
                headers=_headers(),
                timeout=TIMEOUT,
            )
        if resp.status_code in (200, 201, 204):
            return f"Successfully {action}ed agent {agent_id}."
        return f"{action.capitalize()} failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook {action} failed: {e}"


# ── Profiles ─────────────────────────────────────────────────────────

def moltbook_get_profile(agent_id: str) -> str:
    """View an agent's Moltbook profile."""
    pass
    if not agent_id:
        return "No agent_id provided."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        if agent_id.lower() == "me":
            url = f"{API_BASE}/agents/me"
        else:
            url = f"{API_BASE}/agents/{agent_id}"
        resp = req.get(url, headers=_headers(), timeout=TIMEOUT)
        if resp.status_code == 200:
            data = resp.json()
            agent = data.get("agent", data)
            name = agent.get("display_name", agent.get("name", "unknown"))
            desc = agent.get("description", "")
            posts = agent.get("posts_count", agent.get("post_count", 0))
            comments = agent.get("comments_count", agent.get("comment_count", 0))
            karma = agent.get("karma", 0)
            followers = agent.get("follower_count", 0)
            following = agent.get("following_count", 0)
            verified = agent.get("is_verified", False)
            active = agent.get("is_active", False)
            joined = agent.get("created_at", "")
            last_active = agent.get("last_active", "")
            return (
                f"Profile: {name}{' ✓' if verified else ''}\n"
                f"Description: {desc}\n"
                f"Karma: {karma} | Posts: {posts} | Comments: {comments}\n"
                f"Followers: {followers} | Following: {following}\n"
                f"Active: {active} | Last active: {last_active}\n"
                f"Joined: {joined}"
            )
        return f"Profile lookup failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook profile lookup failed: {e}"


def moltbook_get_user_posts(agent_id: str, limit: int = 5) -> str:
    """Retrieve recent posts by a specific agent."""
    pass
    if not agent_id:
        return "No agent_id provided."
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.get(
            f"{API_BASE}/posts",
            headers=_headers(),
            params={"author": agent_id, "limit": limit},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            posts = resp.json()
            if isinstance(posts, dict):
                posts = posts.get("posts", posts.get("data", []))
            if not posts:
                return f"No posts found for author '{agent_id}'."
            lines = []
            for p in posts[:limit]:
                title = p.get("title", "(untitled)")
                preview = p.get("content", "")
                submolt_obj = p.get("submolt", "")
                submolt_name = submolt_obj.get("display_name", submolt_obj.get("name", "general")) if isinstance(submolt_obj, dict) else str(submolt_obj or "general")
                score = p.get("score", 0)
                comments_count = p.get("comment_count", 0)
                pid = p.get("id", "")
                lines.append(
                    f"• {title}\n"
                    f"  {preview[:200]}...\n"
                    f"  (submolt: m/{submolt_name}, score: {score}, comments: {comments_count}, id: {pid})"
                )
            return "\n".join(lines)
        return f"Failed to retrieve user posts ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook user posts request failed: {e}"


# ── Submolts ─────────────────────────────────────────────────────────

def moltbook_list_submolts() -> str:
    """List available Moltbook submolts."""
    pass
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.get(
            f"{API_BASE}/submolts",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            submolts = data.get("submolts", data) if isinstance(data, dict) else data
            if not submolts:
                return "No submolts found."
            lines = []
            for s in submolts:
                name = s.get("name", s.get("display_name", "?"))
                desc = s.get("description", "")[:100]
                members = s.get("member_count", 0)
                lines.append(f"• {name} ({members} members) — {desc}")
            return "\n".join(lines)
        return f"List submolts failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook list submolts failed: {e}"


# ── Notifications ────────────────────────────────────────────────────

def moltbook_notifications(limit: int = 10) -> str:
    """List Moltbook notifications."""
    pass
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.get(
            f"{API_BASE}/notifications",
            headers=_headers(),
            params={"limit": limit},
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            notifs = data.get("notifications", [])
            if not notifs:
                return "No notifications."
            unread = sum(1 for n in notifs if not n.get("isRead"))
            lines = [f"📬 Notifications ({len(notifs)} shown, {unread} unread):"]
            for n in notifs:
                nid = n.get("id", "?")
                ntype = n.get("type", "")
                msg = n.get("content", "")
                read_marker = "  " if n.get("isRead") else "🔴"
                created = n.get("createdAt", "")[:16]
                # Include post title if available
                post = n.get("post", {})
                post_title = post.get("title", "")
                # Include commenter info if available
                comment = n.get("comment", {})
                comment_preview = comment.get("content", "")[:100]
                entry = f"  {read_marker} [{ntype}] {msg}"
                if post_title:
                    entry += f"\n       Post: \"{post_title}\""
                if comment_preview:
                    entry += f"\n       Comment: {comment_preview}"
                entry += f"\n       (id: {nid}, {created})"
                lines.append(entry)
            return "\n".join(lines)
        return f"Notifications fetch failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook notifications failed: {e}"


def moltbook_mark_notifications_read(notification_id: str = "") -> str:
    """Mark Moltbook notifications as read. Pass a notification_id to mark one, or leave empty to mark all."""
    pass
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        if notification_id:
            # Mark a single notification as read
            resp = req.post(
                f"{API_BASE}/notifications/{notification_id}/read",
                headers=_headers(),
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                return f"Notification {notification_id} marked as read."
            return f"Mark read failed ({resp.status_code}): {resp.text[:500]}"
        else:
            # Mark all notifications as read
            resp = req.post(
                f"{API_BASE}/notifications/read-all",
                headers=_headers(),
                timeout=TIMEOUT,
            )
            if resp.status_code == 200:
                return "All notifications marked as read."
            return f"Mark all read failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook mark notifications read failed: {e}"


# ── Home ─────────────────────────────────────────────────────────────

def moltbook_home() -> str:
    """Check Moltbook home — notifications, DMs, karma, and announcements."""
    pass
    key = _api_key()
    if not key:
        return "MOLTBOOK_API_KEY not set."
    try:
        resp = req.get(
            f"{API_BASE}/home",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        if resp.status_code == 200:
            data = resp.json()
            lines = []

            # Agent summary
            agent = data.get("agent", {})
            if agent:
                name = agent.get("display_name", agent.get("name", ""))
                karma = agent.get("karma", 0)
                lines.append(f"Welcome back, {name}! (karma: {karma})")

            # Notifications
            notifs = data.get("notifications", data.get("unread_notifications", []))
            if isinstance(notifs, list) and notifs:
                lines.append(f"\n📬 Notifications ({len(notifs)}):")
                for n in notifs[:10]:
                    ntype = n.get("type", "")
                    msg = n.get("message", n.get("content", ""))
                    lines.append(f"  • [{ntype}] {msg}")
            elif isinstance(notifs, int) and notifs > 0:
                lines.append(f"\n📬 {notifs} unread notification(s)")

            # DMs
            dms = data.get("dms", data.get("messages", data.get("direct_messages", [])))
            if isinstance(dms, list) and dms:
                lines.append(f"\n💬 Direct Messages ({len(dms)}):")
                for dm in dms[:5]:
                    sender = dm.get("from", dm.get("sender", {}).get("name", "unknown"))
                    preview = dm.get("content", dm.get("preview", ""))[:150]
                    lines.append(f"  • [{sender}] {preview}")
            elif isinstance(dms, dict):
                unread = dms.get("unread", dms.get("total_unread", 0))
                if unread:
                    lines.append(f"\n💬 {unread} unread DM(s)")

            # Announcements
            announcements = data.get("announcements", [])
            if announcements:
                lines.append(f"\n📢 Announcements:")
                for a in announcements[:3]:
                    lines.append(f"  • {a.get('content', a.get('message', str(a)))[:200]}")

            # Tip
            tip = data.get("tip", "")
            if tip:
                lines.append(f"\n💡 {tip}")

            if not lines:
                return f"Home data: {json.dumps(data)[:1000]}"
            return "\n".join(lines)
        return f"Home check failed ({resp.status_code}): {resp.text[:500]}"
    except Exception as e:
        return f"Moltbook home check failed: {e}"
