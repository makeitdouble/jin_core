import re

from .action_payload_utils import (
    _build_internal_action_payload,
)
from .active_memory_utils import normalize_active_memory_slot_id


ACTIVE_MEMORY_DELETE_SLOT_ID_TOKEN_RE = re.compile(
    r"(?<![a-zA-Z0-9_-])(AM-[a-z0-9]{6})(?![a-zA-Z0-9_-])",
)


def build_resolve_action_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    return _build_internal_action_payload(
        query,
        placeholder_payloads,
    )


def extract_active_memory_delete_slot_id(
    payload: str,
    *,
    existing_ids=None,
) -> str:

    existing_id_set = {
        normalized_id
        for active_memory_id in (existing_ids or ())
        if (
            normalized_id := normalize_active_memory_slot_id(
                active_memory_id
            )
        )
    }

    for match in ACTIVE_MEMORY_DELETE_SLOT_ID_TOKEN_RE.finditer(
        str(payload or "")
    ):
        active_memory_id = normalize_active_memory_slot_id(
            match.group(1)
        )

        if (
            existing_id_set
            and active_memory_id not in existing_id_set
        ):
            continue

        return active_memory_id

    return ""
