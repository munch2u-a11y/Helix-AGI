"""
Helix — Google API Authentication Helper

Shared OAuth2 credential management for all Google API tools
(Gmail, Calendar, Drive, Tasks).

Token and credentials are stored in ~/.config/helix/.
Credentials auto-refresh when expired.
"""

import json
import logging
from pathlib import Path

logger = logging.getLogger("helix.tools.google_auth")

_GOOGLE_TOKEN_PATH = "/home/nemo/.config/helix/google_token.json"
_GOOGLE_CRED_PATH = "/home/nemo/.config/helix/google_credentials.json"

# Cached credentials (module-level singleton)
_cached_creds = None


def get_google_creds():
    """Get or refresh Google OAuth2 credentials.

    Returns valid credentials or None if not configured.
    """
    global _cached_creds

    if _cached_creds and _cached_creds.valid:
        return _cached_creds

    token_path = Path(_GOOGLE_TOKEN_PATH)
    if not token_path.exists():
        logger.warning(f"Google token not found at {_GOOGLE_TOKEN_PATH}")
        return None

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request

        creds = Credentials.from_authorized_user_file(str(token_path))

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                token_path.write_text(creds.to_json())
                logger.info("Google token refreshed successfully")
            except Exception as e:
                logger.error(f"Google token refresh failed: {e}")
                return None

        _cached_creds = creds
        return creds
    except Exception as e:
        logger.error(f"Failed to load Google credentials: {e}")
        return None


def get_gmail_service():
    """Get authenticated Gmail API service."""
    from googleapiclient.discovery import build
    creds = get_google_creds()
    if not creds:
        return None
    return build("gmail", "v1", credentials=creds)


def get_calendar_service():
    """Get authenticated Google Calendar API service."""
    from googleapiclient.discovery import build
    creds = get_google_creds()
    if not creds:
        return None
    return build("calendar", "v3", credentials=creds)


def get_drive_service():
    """Get authenticated Google Drive API service."""
    from googleapiclient.discovery import build
    creds = get_google_creds()
    if not creds:
        return None
    return build("drive", "v3", credentials=creds)


def get_tasks_service():
    """Get authenticated Google Tasks API service."""
    from googleapiclient.discovery import build
    creds = get_google_creds()
    if not creds:
        return None
    return build("tasks", "v1", credentials=creds)
