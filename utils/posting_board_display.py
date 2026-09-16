from __future__ import annotations

import json
import re


# One compact, deterministic presentation for POSTING_BOARD actions.
# Free-form write title/body fields intentionally stay out of the action label:
# they can be large/untrusted board content and remain available in payload/result traces.
_DISPLAY_FIELDS = {
    "feed": ("cursor", "limit"),
    "inbox": ("limit", "after", "before"),
    "read": ("source", "root_id", "article_revision_id"),
    "search": ("query", "topic", "limit"),
    "post": ("topic",),
    "reply": ("thread_id",),
    "delete": ("post_id",),
    "ack": ("through",),
}

_MAX_DISPLAY_VALUE = 160


def parse_posting_board_payload(payload) -> dict:
    if isinstance(payload, dict):
        value = dict(payload)
    else:
        try:
            value = json.loads(str(payload or "").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return value if isinstance(value, dict) else {}


def posting_board_action_name(payload) -> str:
    parsed = parse_posting_board_payload(payload)
    return str(parsed.get("action") or "").strip().casefold()


def _display_scalar(value) -> str:
    if value is True:
        text = "true"
    elif value is False:
        text = "false"
    elif value is None:
        return ""
    elif isinstance(value, (dict, list, tuple)):
        text = json.dumps(
            value,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    else:
        text = str(value)

    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > _MAX_DISPLAY_VALUE:
        text = text[: _MAX_DISPLAY_VALUE - 3].rstrip() + "..."
    return text


def build_posting_board_display_text(
    payload,
    *,
    failed: bool = False,
) -> str:
    parsed = parse_posting_board_payload(payload)
    action = str(parsed.get("action") or "unknown").strip().casefold() or "unknown"

    parts = [f"POSTING_BOARD: action:{action}"]
    for key in _DISPLAY_FIELDS.get(action, ()):
        if key == "topic" and action == "post":
            raw_value = parsed.get(key) or "general"
        elif key in parsed:
            raw_value = parsed.get(key)
        else:
            continue
        value = _display_scalar(raw_value)
        if value:
            parts.append(f"{key}: {value}")

    text = " | ".join(parts)
    if failed:
        text += " - failed"
    return text


def build_posting_board_display_detail(payload) -> str:
    text = build_posting_board_display_text(payload)
    prefix = "POSTING_BOARD: "
    return text[len(prefix):] if text.startswith(prefix) else text


def compact_posting_board_model_output(value: str) -> str:
    """Compact protocol markers for logger presentation only."""

    text = str(value or "")
    if "POSTING_BOARD" not in text.upper():
        return text

    def replace_closed(match: re.Match) -> str:
        payload = str(match.group("payload") or "").strip()
        if not parse_posting_board_payload(payload):
            return match.group(0)
        return build_posting_board_display_text(payload)

    text = re.sub(
        r"<POSTING_BOARD\s*>\s*(?P<payload>.*?)\s*</POSTING_BOARD\s*>",
        replace_closed,
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def replace_legacy(match: re.Match) -> str:
        payload = str(match.group("payload") or "").strip()
        if not parse_posting_board_payload(payload):
            return match.group(0)
        return build_posting_board_display_text(payload)

    return re.sub(
        r"<POSTING_BOARD\s*:\s*(?P<payload>\{[^\n>]*\})\s*>",
        replace_legacy,
        text,
        flags=re.IGNORECASE,
    )
