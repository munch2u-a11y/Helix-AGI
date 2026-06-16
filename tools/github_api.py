"""
Helix — GitHub API Tools

Provides structured API access to GitHub repos, issues, and PRs.

Also includes local git operations (status, diff, commit, push, pull, clone, log)
which use subprocess directly rather than the GitHub REST API.

Auth: GITHUB_TOKEN from environment (loaded from credentials.env).

Tag interface (extended tools, injected by preconscious):
  [GIT_STATUS:path]              — Repo status + current branch
  [GIT_DIFF:path]                — Show uncommitted changes
  [GIT_COMMIT:path] message      — Stage all + commit
  [GIT_PUSH:path]                — Push to remote
  [GIT_PULL:path]                — Pull from remote
  [GIT_LOG:path]                 — Recent commit history
  [GIT_CLONE:] url               — Clone a repo
  [GITHUB_SEARCH:] query         — Search repos on GitHub
  [GITHUB_ISSUE:repo] number     — Read an issue + comments
  [GITHUB_CREATE_ISSUE:repo] title | body — Create an issue
  [GITHUB_COMMENT:repo] issue_number | body — Comment on issue
  [GITHUB_PR:repo] title | head | base | body — Create a PR
"""

import os
import subprocess
import logging
from typing import Optional
from pathlib import Path

logger = logging.getLogger("helix.tools.github")

# ── Config ────────────────────────────────────────────────────────────

API_BASE = "https://api.github.com"
TIMEOUT = 15


def _github_headers() -> dict:
    """Build GitHub API headers with optional auth."""
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    headers = {
        "Accept": "application/vnd.github.v3+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


# ── Local Git Operations ─────────────────────────────────────────────

def git_status(repo_path: str) -> str:
    """Check git status of a repository."""
    if not repo_path or not os.path.isdir(repo_path):
        return f"Invalid repo path: {repo_path}"
    try:
        result = subprocess.run(
            ["git", "status", "--short"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        status = result.stdout.strip() or "Clean — nothing to commit."
        branch = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=repo_path, capture_output=True, text=True, timeout=5,
        )
        return f"Branch: {branch.stdout.strip()}\n{status}"
    except Exception as e:
        return f"Git status failed: {e}"


def git_diff(repo_path: str) -> str:
    """Show untracked and tracked file changes."""
    if not repo_path or not os.path.isdir(repo_path):
        return f"Invalid repo path: {repo_path}"
    try:
        untracked = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        diff = subprocess.run(
            ["git", "diff"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        out = ""
        if untracked.stdout.strip():
            out += f"Untracked files:\n{untracked.stdout.strip()}\n\n"
        if diff.stdout.strip():
            out += f"Modifications:\n{diff.stdout.strip()[:3000]}"
            if len(diff.stdout) > 3000:
                out += "\n...[diff truncated]"
        return out if out else "No changes."
    except Exception as e:
        return f"Git diff failed: {e}"


def git_commit(repo_path: str, message: str) -> str:
    """Stage all changes and commit with a message."""
    if not repo_path or not message:
        return "Need both repo_path and message."
    try:
        subprocess.run(
            ["git", "add", "-A"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=repo_path, capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            return f"Committed: {message}\n{result.stdout.strip()}"
        return f"Commit failed: {result.stderr.strip() or result.stdout.strip()}"
    except Exception as e:
        return f"Git commit failed: {e}"


def git_push(repo_path: str) -> str:
    """Push commits to remote."""
    if not repo_path:
        return "No repo_path provided."
    try:
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no"
        result = subprocess.run(
            ["git", "push"],
            cwd=repo_path, capture_output=True, text=True, timeout=30, env=env,
        )
        if result.returncode == 0:
            return f"Pushed successfully.\n{result.stderr.strip()}"
        return f"Push failed: {result.stderr.strip()}"
    except Exception as e:
        return f"Git push failed: {e}"


def git_pull(repo_path: str) -> str:
    """Pull latest from remote."""
    if not repo_path:
        return "No repo_path provided."
    try:
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no"
        result = subprocess.run(
            ["git", "pull"],
            cwd=repo_path, capture_output=True, text=True, timeout=30, env=env,
        )
        return result.stdout.strip() or result.stderr.strip()
    except Exception as e:
        return f"Git pull failed: {e}"


def git_log(repo_path: str, count: int = 10) -> str:
    """Show recent git log."""
    if not repo_path:
        return "No repo_path provided."
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{count}"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "No commits found."
    except Exception as e:
        return f"Git log failed: {e}"


def git_clone(repo_url: str, target_dir: str = "") -> str:
    """Clone a repository."""
    if not repo_url:
        return "No repo_url provided."
    target = target_dir or os.path.expanduser("~/repos")
    try:
        Path(target).mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        env["GIT_SSH_COMMAND"] = "ssh -o StrictHostKeyChecking=no"
        result = subprocess.run(
            ["git", "clone", repo_url],
            cwd=target, capture_output=True, text=True, timeout=60, env=env,
        )
        if result.returncode == 0:
            return f"Cloned {repo_url} into {target}"
        return f"Clone failed: {result.stderr.strip()}"
    except Exception as e:
        return f"Git clone failed: {e}"


# ── GitHub REST API ───────────────────────────────────────────────────

def github_search_repos(query: str) -> str:
    """Search GitHub repositories."""
    import requests as req
    if not query:
        return "Missing query."
    try:
        res = req.get(
            f"{API_BASE}/search/repositories",
            params={"q": query, "per_page": 5},
            headers=_github_headers(),
            timeout=TIMEOUT,
        )
        if res.status_code == 200:
            items = res.json().get("items", [])
            if not items:
                return "No repositories found."
            out = "Found Repositories:\n"
            for i in items:
                out += f"- {i['full_name']} (Stars: {i['stargazers_count']}): {i['description']}\n"
            return out
        return f"GitHub search failed ({res.status_code}): {res.text[:500]}"
    except Exception as e:
        return f"GitHub API error: {e}"


def github_read_issue(repo: str, issue_number: int) -> str:
    """Read an issue and its comments."""
    import requests as req
    if not repo or not issue_number:
        return "Missing repo or issue_number."
    try:
        res = req.get(
            f"{API_BASE}/repos/{repo}/issues/{issue_number}",
            headers=_github_headers(),
            timeout=TIMEOUT,
        )
        if res.status_code != 200:
            return f"Failed to fetch issue: {res.text[:500]}"
        issue = res.json()
        out = (
            f"Issue #{issue['number']}: {issue['title']} (State: {issue['state']})\n"
            f"Author: {issue['user']['login']}\n\n{issue['body']}\n\n--- COMMENTS ---\n"
        )

        c_res = req.get(
            f"{API_BASE}/repos/{repo}/issues/{issue_number}/comments",
            headers=_github_headers(),
            timeout=TIMEOUT,
        )
        if c_res.status_code == 200:
            for c in c_res.json():
                out += f"\n[{c['user']['login']}] at {c['created_at']}:\n{c['body']}\n"
        return out
    except Exception as e:
        return f"GitHub API error: {e}"


def github_create_issue(repo: str, title: str, body: str = "") -> str:
    """Create a new issue."""
    import requests as req
    if not repo or not title:
        return "Missing repo or title."
    try:
        res = req.post(
            f"{API_BASE}/repos/{repo}/issues",
            json={"title": title, "body": body},
            headers=_github_headers(),
            timeout=TIMEOUT,
        )
        if res.status_code == 201:
            return f"Issue created successfully: {res.json()['html_url']}"
        return f"Failed to create issue ({res.status_code}): {res.text[:500]}"
    except Exception as e:
        return f"GitHub API error: {e}"


def github_comment_issue(repo: str, issue_number: int, body: str) -> str:
    """Comment on an issue."""
    import requests as req
    if not repo or not issue_number or not body:
        return "Missing required arguments."
    try:
        res = req.post(
            f"{API_BASE}/repos/{repo}/issues/{issue_number}/comments",
            json={"body": body},
            headers=_github_headers(),
            timeout=TIMEOUT,
        )
        if res.status_code == 201:
            return f"Comment added successfully to #{issue_number}."
        return f"Failed to add comment ({res.status_code}): {res.text[:500]}"
    except Exception as e:
        return f"GitHub API error: {e}"


def github_create_pr(repo: str, title: str, head: str, base: str = "main", body: str = "") -> str:
    """Create a pull request."""
    import requests as req
    if not repo or not title or not head or not base:
        return "Missing required arguments."
    try:
        res = req.post(
            f"{API_BASE}/repos/{repo}/pulls",
            json={"title": title, "body": body, "head": head, "base": base},
            headers=_github_headers(),
            timeout=TIMEOUT,
        )
        if res.status_code == 201:
            return f"Pull Request created successfully: {res.json()['html_url']}"
        return f"Failed to create PR ({res.status_code}): {res.text[:500]}"
    except Exception as e:
        return f"GitHub API error: {e}"
