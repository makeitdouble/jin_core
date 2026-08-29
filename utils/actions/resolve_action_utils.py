import re

from .action_payload_utils import (
    _build_internal_action_payload,
)
from .active_memory_utils import ACTIVE_MEMORY_SLOT_ID_RE


ACTIVE_MEMORY_DELETE_SLOT_ID_TOKEN_RE = re.compile(
    r"(?<![a-zA-Z0-9_])([a-zA-Z0-9]{6})(?![a-zA-Z0-9_])",
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
        str(active_memory_id or "").strip().casefold()
        for active_memory_id in (existing_ids or ())
        if ACTIVE_MEMORY_SLOT_ID_RE.fullmatch(
            str(active_memory_id or "").strip().casefold()
        )
    }

    for match in ACTIVE_MEMORY_DELETE_SLOT_ID_TOKEN_RE.finditer(
        str(payload or "")
    ):
        active_memory_id = match.group(
            1
        ).casefold()

        if (
            existing_id_set
            and active_memory_id not in existing_id_set
        ):
            continue

        return active_memory_id

    return ""
