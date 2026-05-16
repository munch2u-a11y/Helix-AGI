"""
Helix — Google Drive API Tools

Provides Google Drive operations via action tags:
  [DRIVE_SEARCH:] query
  [DRIVE_READ:] file_id
  [DRIVE_LIST:] folder_id
  [DRIVE_UPLOAD:path] name | content
  [DRIVE_SHARE:file_id] email | role

All operations use the shared Google OAuth2 credentials
from tools/google_auth.py.
"""

import logging

logger = logging.getLogger("helix.tools.google_drive")


def drive_search(query: str, file_type: str = "", limit: int = 10) -> str:
    """Search Google Drive for files."""
    from tools.google_auth import get_drive_service

    service = get_drive_service()
    if not service:
        return "Google Drive not configured. Run google_auth.py first."

    if not query:
        return "No search query provided."

    try:
        q_parts = [f"name contains '{query}' or fullText contains '{query}'"]
        mime_map = {
            "document": "application/vnd.google-apps.document",
            "spreadsheet": "application/vnd.google-apps.spreadsheet",
            "presentation": "application/vnd.google-apps.presentation",
            "pdf": "application/pdf",
            "image": "image/",
            "folder": "application/vnd.google-apps.folder",
        }
        if file_type and file_type in mime_map:
            if file_type == "image":
                q_parts.append("mimeType contains 'image/'")
            else:
                q_parts.append(f"mimeType = '{mime_map[file_type]}'")

        q_parts.append("trashed = false")
        q_str = " and ".join(q_parts)

        results = service.files().list(
            q=q_str,
            pageSize=limit,
            fields="files(id, name, mimeType, modifiedTime, size, owners)",
        ).execute()
        files = results.get("files", [])
        if not files:
            return f"No files found for '{query}'."

        lines = []
        for f in files:
            owner = f.get("owners", [{}])[0].get("displayName", "?") if f.get("owners") else "?"
            lines.append(
                f"• {f['name']} ({f['mimeType'][:30]})\n"
                f"  ID: {f['id']} | Modified: {f.get('modifiedTime', '?')[:16]} | Owner: {owner}"
            )
        return "\n".join(lines)
    except Exception as e:
        return f"Drive search failed: {e}"


def drive_read(file_id: str, read_content: bool = True) -> str:
    """Read a Google Drive file."""
    from tools.google_auth import get_drive_service

    service = get_drive_service()
    if not service:
        return "Google Drive not configured."

    if not file_id:
        return "No file_id provided."

    try:
        meta = service.files().get(
            fileId=file_id, fields="id, name, mimeType, modifiedTime, size, description"
        ).execute()

        info = (
            f"File: {meta['name']}\n"
            f"Type: {meta['mimeType']}\n"
            f"Modified: {meta.get('modifiedTime', '?')}\n"
            f"Size: {meta.get('size', '?')} bytes"
        )

        if read_content and meta["mimeType"].startswith("application/vnd.google-apps"):
            export_mime = "text/plain"
            if "spreadsheet" in meta["mimeType"]:
                export_mime = "text/csv"
            content = service.files().export(
                fileId=file_id, mimeType=export_mime
            ).execute()
            text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
            return f"{info}\n\n--- CONTENT ---\n{text[:5000]}"
        elif read_content:
            content = service.files().get_media(fileId=file_id).execute()
            text = content.decode("utf-8", errors="replace") if isinstance(content, bytes) else str(content)
            return f"{info}\n\n--- CONTENT ---\n{text[:5000]}"

        return info
    except Exception as e:
        return f"Drive read failed: {e}"


def drive_list(folder_id: str = "", limit: int = 20) -> str:
    """List files in a Drive folder."""
    from tools.google_auth import get_drive_service

    service = get_drive_service()
    if not service:
        return "Google Drive not configured."

    try:
        q = "trashed = false"
        if folder_id:
            q += f" and '{folder_id}' in parents"

        results = service.files().list(
            q=q, pageSize=limit, orderBy="modifiedTime desc",
            fields="files(id, name, mimeType, modifiedTime, size)",
        ).execute()
        files = results.get("files", [])
        if not files:
            return "No files found."

        lines = [f"Files ({len(files)}):"]
        for f in files:
            icon = "📁" if "folder" in f.get("mimeType", "") else "📄"
            lines.append(f"  {icon} {f['name']} (id: {f['id'][:12]}..., modified: {f.get('modifiedTime', '?')[:10]})")
        return "\n".join(lines)
    except Exception as e:
        return f"Drive list failed: {e}"


def drive_upload(name: str, content: str, mime_type: str = "text/plain",
                 folder_id: str = "") -> str:
    """Upload/create a file on Google Drive."""
    from tools.google_auth import get_drive_service

    service = get_drive_service()
    if not service:
        return "Google Drive not configured."

    from googleapiclient.http import MediaInMemoryUpload

    if not name or not content:
        return "name and content required."

    try:
        file_meta = {"name": name}
        if folder_id:
            file_meta["parents"] = [folder_id]

        media = MediaInMemoryUpload(content.encode("utf-8"), mimetype="text/plain")
        f = service.files().create(
            body=file_meta, media_body=media, fields="id, name, webViewLink"
        ).execute()
        return f"Created file '{f['name']}' (id: {f['id']})\nLink: {f.get('webViewLink', 'N/A')}"
    except Exception as e:
        return f"Drive upload failed: {e}"


def drive_share(file_id: str, email: str, role: str = "reader") -> str:
    """Share a Drive file."""
    from tools.google_auth import get_drive_service

    service = get_drive_service()
    if not service:
        return "Google Drive not configured."

    if not file_id or not email:
        return "file_id and email required."
    if role not in ("reader", "writer", "commenter"):
        return "role must be 'reader', 'writer', or 'commenter'."

    try:
        service.permissions().create(
            fileId=file_id,
            body={"type": "user", "role": role, "emailAddress": email},
            sendNotificationEmail=True,
        ).execute()
        return f"Shared file {file_id} with {email} as {role}."
    except Exception as e:
        return f"Drive share failed: {e}"
