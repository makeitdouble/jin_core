from __future__ import annotations

import re
import unicodedata

from utils.actions.regexp_utils import RUNTIME_ACTION_QUOTE_OPENERS


_VARIATION_SELECTOR = "\ufe0f"
_ZERO_WIDTH_JOINER = "\u200d"
_KEYCAP = "\u20e3"

_JIN_REACTION_MARKER_RE = re.compile(
    "(?<![" + re.escape(RUNTIME_ACTION_QUOTE_OPENERS) + "])"
    r"<\s*JIN_REACTION\s*:\s*([^>\r\n]*?)\s*>",
    re.IGNORECASE,
)


def _is_emoji_base(char: str) -> bool:
    if not char:
        return False

    codepoint = ord(char)

    if (
        0x1F000 <= codepoint <= 0x1FAFF
        or 0x2600 <= codepoint <= 0x27BF
        or 0x2300 <= codepoint <= 0x23FF
        or 0x2B00 <= codepoint <= 0x2BFF
    ):
        return True

    return char in {
        "©", "®", "™", "↔", "↕", "↖", "↗", "↘", "↙",
        "↩", "↪", "‼", "⁉", "ℹ", "◻", "◼", "◽", "◾",
        "〰", "〽", "㊗", "㊙",
    }


def _is_modifier(char: str) -> bool:
    codepoint = ord(char)
    return (
        0x1F3FB <= codepoint <= 0x1F3FF
        or 0xE0020 <= codepoint <= 0xE007E
        or codepoint == 0xE007F
        or unicodedata.category(char) in {"Mn", "Me"}
    )


def _consume_emoji_component(value: str, index: int) -> int:
    if index >= len(value):
        return -1

    char = value[index]

    if char in "#*0123456789":
        next_index = index + 1
        if next_index < len(value) and value[next_index] == _VARIATION_SELECTOR:
            next_index += 1
        if next_index < len(value) and value[next_index] == _KEYCAP:
            return next_index + 1
        return -1

    if not _is_emoji_base(char):
        return -1

    index += 1

    while index < len(value):
        char = value[index]
        if char == _VARIATION_SELECTOR or _is_modifier(char):
            index += 1
            continue
        break

    return index


def _is_single_emoji_cluster(value: str) -> bool:
    if not value or any(char.isspace() for char in value):
        return False

    codepoints = [ord(char) for char in value]

    if all(0x1F1E6 <= codepoint <= 0x1F1FF for codepoint in codepoints):
        return len(codepoints) == 2

    index = _consume_emoji_component(value, 0)
    if index < 0:
        return False

    while index < len(value):
        if value[index] != _ZERO_WIDTH_JOINER:
            return False
        index = _consume_emoji_component(value, index + 1)
        if index < 0:
            return False

    return True


def normalize_jin_reaction_payload(payload: str) -> str:
    value = str(payload or "").strip()
    return value if _is_single_emoji_cluster(value) else ""


def build_jin_reaction_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:
    del placeholder_payloads
    return normalize_jin_reaction_payload(query) or None


def strip_jin_reaction_markers(text: str) -> str:
    return _JIN_REACTION_MARKER_RE.sub("", str(text or ""))
