import re

from contracts.rules_assembler import (
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    get_runtime_action_private_marker,
)

from .action_payload_utils import (
    _clean_internal_action_query,
    _is_placeholder_internal_query,
)
from .active_memory_utils import generate_short_runtime_id
from .regexp_utils import extract_private_marker_parts


def generate_active_memory_slot_id(
    existing_ids=None,
) -> str:

    return generate_short_runtime_id(
        existing_ids
    )

def normalize_active_memory_marker_field(
    field: str,
) -> str:

    normalized_field = re.sub(
        r"[^0-9a-zA-Z_]+",
        "_",
        str(field or "").strip().casefold(),
    ).strip("_")

    return normalized_field


def get_create_active_memory_marker_fields(
    marker: str | None = None,
) -> tuple[str, ...]:

    marker = (
        marker
        if marker is not None
        else get_runtime_action_private_marker(
            RUNTIME_ACTION_CREATE_ACTIVE_MEMORY
        )
    )

    _, marker_fields = extract_private_marker_parts(
        marker
    )

    if not marker_fields:
        return ()

    fields = []

    for field in marker_fields.split("|"):
        normalized_field = normalize_active_memory_marker_field(
            field
        )

        if (
            normalized_field
            and normalized_field not in fields
        ):
            fields.append(
                normalized_field
            )

    return tuple(
        fields
    )


def get_create_active_memory_placeholder_payload(
    marker: str | None = None,
) -> str:

    marker = (
        marker
        if marker is not None
        else get_runtime_action_private_marker(
            RUNTIME_ACTION_CREATE_ACTIVE_MEMORY
        )
    )

    _, marker_fields = extract_private_marker_parts(
        marker
    )

    if not marker_fields:
        return ""

    return " | ".join(
        field.strip()
        for field in marker_fields.split("|")
        if field.strip()
    )


def build_create_active_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    payload = _clean_internal_action_query(
        query
    )

    if _is_placeholder_internal_query(
        payload,
        placeholder_payloads,
    ):
        return None

    return payload
