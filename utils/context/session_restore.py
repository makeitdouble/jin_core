"""Helpers for the one-shot hidden session-restore prompt."""

from __future__ import annotations

from datetime import datetime
from xml.sax.saxutils import escape


def build_session_restore_message(
    message: str,
    *,
    session_id: str = "",
    now: datetime | None = None,
) -> str:
    """Wrap the restore instruction with live bootstrap identity/time metadata."""

    current_time = now or datetime.now().astimezone()
    if current_time.tzinfo is None:
        current_time = current_time.astimezone()

    normalized_session_id = str(session_id or "").strip() or "unknown"
    body = str(message or "").strip()

    lines = [
        "<MANDATORY_SYSTEM_NOTIFICATION>",
        f"Current session id: {escape(normalized_session_id)}",
        f"Current time: {escape(current_time.isoformat(timespec='seconds'))}",
    ]
    if body:
        lines.append(body)
    lines.append("</MANDATORY_SYSTEM_NOTIFICATION>")
    return "\n".join(lines)
