#!/usr/bin/env python3
"""
Helix — Google OAuth Setup Script

This script handles the OAuth2 consent flow for Google APIs
(Gmail, Calendar, Drive, Tasks).

Prerequisites:
    1. Go to https://console.cloud.google.com/
    2. Create a project (or select existing)
    3. Enable these APIs:
       - Gmail API
       - Google Calendar API
       - Google Drive API
       - Google Tasks API
    4. Create OAuth 2.0 credentials:
       - Go to APIs & Services → Credentials
       - Click "Create Credentials" → "OAuth client ID"
       - Application type: "Desktop app"
       - Download the JSON file
       - Save it as ~/.config/helix/google_credentials.json

Usage:
    python scripts/setup_google_oauth.py
"""

import os
import sys
import json
from pathlib import Path

CONFIG_DIR = Path(os.path.expanduser("~/.config/helix"))
CRED_PATH = CONFIG_DIR / "google_credentials.json"
TOKEN_PATH = CONFIG_DIR / "google_token.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/tasks",
]


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if TOKEN_PATH.exists():
        print(f"✓ Token already exists at {TOKEN_PATH}")
        print("  Delete it and re-run this script to re-authenticate.")

        # Verify it's still valid
        try:
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(str(TOKEN_PATH))
            if creds.expired and creds.refresh_token:
                creds.refresh(Request())
                TOKEN_PATH.write_text(creds.to_json())
                print("  ✓ Token refreshed successfully")
            elif creds.valid:
                print("  ✓ Token is valid")
            else:
                print("  ✗ Token is invalid — delete and re-run")
        except Exception as e:
            print(f"  ✗ Token validation failed: {e}")
        return

    if not CRED_PATH.exists():
        print("=" * 60)
        print("  Google OAuth Setup — Step 1: Create Credentials")
        print("=" * 60)
        print()
        print("  1. Open: https://console.cloud.google.com/")
        print("  2. Create or select a project")
        print("  3. Go to 'APIs & Services' → 'Library'")
        print("     Enable: Gmail, Calendar, Drive, Tasks APIs")
        print("  4. Go to 'APIs & Services' → 'Credentials'")
        print("  5. Click 'Create Credentials' → 'OAuth client ID'")
        print("     - Type: 'Desktop app'")
        print("     - Name: 'Helix'")
        print("  6. Download the JSON file")
        print(f"  7. Save it as: {CRED_PATH}")
        print()
        print("  If you've already done this but saved the file elsewhere,")
        print("  paste the full path to it now:")
        print()

        user_path = input("  Path to credentials JSON (or Enter to exit): ").strip()
        if not user_path:
            print("\n  Exiting. Re-run after placing credentials file.")
            sys.exit(0)

        user_path = Path(user_path).expanduser()
        if not user_path.exists():
            print(f"\n  ✗ File not found: {user_path}")
            sys.exit(1)

        # Validate it's a proper OAuth credentials file
        try:
            data = json.loads(user_path.read_text())
            if "installed" not in data and "web" not in data:
                print("  ✗ This doesn't look like an OAuth client credentials file.")
                print("    Expected 'installed' or 'web' key in JSON.")
                sys.exit(1)
        except json.JSONDecodeError:
            print("  ✗ Invalid JSON file.")
            sys.exit(1)

        # Copy to config dir
        import shutil
        shutil.copy2(str(user_path), str(CRED_PATH))
        print(f"\n  ✓ Credentials saved to {CRED_PATH}")

    # Now run the OAuth flow
    print()
    print("=" * 60)
    print("  Google OAuth Setup — Step 2: Authorize")
    print("=" * 60)
    print()
    print("  A browser window will open for you to authorize Helix.")
    print("  Log in with: Helix.AGI.email@gmail.com")
    print("  Grant access to Gmail, Calendar, Drive, and Tasks.")
    print()

    try:
        from google_auth_oauthlib.flow import InstalledAppFlow

        flow = InstalledAppFlow.from_client_secrets_file(
            str(CRED_PATH), SCOPES
        )
        creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())
        print(f"\n  ✓ Token saved to {TOKEN_PATH}")

        # Quick verification
        from googleapiclient.discovery import build
        service = build("gmail", "v1", credentials=creds)
        profile = service.users().getProfile(userId="me").execute()
        print(f"  ✓ Authenticated as: {profile.get('emailAddress')}")
        print(f"  ✓ Total messages: {profile.get('messagesTotal')}")

        print()
        print("  Google APIs are ready! Helix can now use:")
        print("    - Gmail (send, read, search, reply, forward)")
        print("    - Google Calendar (view, create events)")
        print("    - Google Drive (list, read, search files)")
        print("    - Google Tasks (list, create, complete)")

    except Exception as e:
        print(f"\n  ✗ OAuth flow failed: {e}")
        print("    Make sure you have a display available for the browser.")
        print("    If running headless, you may need to use a different flow.")
        sys.exit(1)


if __name__ == "__main__":
    main()
