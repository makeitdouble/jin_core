import re

from .action_payload_utils import _build_internal_action_payload
from .active_memory_utils import (
    normalize_active_memory_custom_field_name,
    normalize_active_memory_custom_field_value,
)


ACTIVE_MEMORY_UPDATE_ID_RE = re.compile(
    r"(?<![a-z0-9])([a-z0-9]{6})(?![a-z0-9])",
    re.IGNORECASE,
)


def build_update_active_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    return _build_internal_action_payload(
        query,
        placeholder_payloads,
        reject_placeholders=False,
    )


def parse_update_active_memory_payload(
    payload: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:

    lines = [
        str(line or "").strip()
        for line in str(payload or "").splitlines()
        if str(line or "").strip()
    ]

    if len(lines) < 2:
        return "", ()

    id_match = ACTIVE_MEMORY_UPDATE_ID_RE.search(
        lines[0]
    )
    if id_match is None:
        return "", ()

    active_memory_id = id_match.group(1).casefold()
    changes = []
    seen = set()

    for line in lines[1:]:
        if ":" not in line:
            return "", ()

        raw_name, raw_value = line.split(":", 1)
        field_name = normalize_active_memory_custom_field_name(
            raw_name
        )
        field_value = normalize_active_memory_custom_field_value(
            raw_value
        )

        if (
            not field_name
            or not field_value
            or field_name in seen
        ):
            return "", ()

        changes.append((field_name, field_value))
        seen.add(field_name)

    return active_memory_id, tuple(changes)
