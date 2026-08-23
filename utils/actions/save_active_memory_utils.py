import json
import re

from contracts.rules_assembler import (
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    get_runtime_action_private_marker,
)

from .action_payload_utils import (
    _build_internal_action_payload,
    _clean_internal_action_query,
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


def _get_save_active_memory_placeholder_source(
    marker: str | None = None,
) -> str:

    if marker is None:
        marker = get_runtime_action_private_marker(
            RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
        )

    _, marker_fields = extract_private_marker_parts(
        marker
    )

    return marker_fields or "CONDITIONS"


def get_save_active_memory_marker_fields(
    marker: str | None = None,
) -> tuple[str, ...]:

    marker_fields = _get_save_active_memory_placeholder_source(
        marker
    )

    if not marker_fields:
        return ()

    if marker_fields.lstrip().startswith("{"):
        try:
            placeholder = json.loads(marker_fields)
        except (TypeError, ValueError, json.JSONDecodeError):
            return ()

        if isinstance(placeholder, dict) and "conditions" in placeholder:
            return ("conditions",)

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


def get_save_active_memory_placeholder_payload(
    marker: str | None = None,
) -> str:

    marker_fields = _get_save_active_memory_placeholder_source(
        marker
    )

    if not marker_fields:
        return ""

    return " | ".join(
        field.strip()
        for field in marker_fields.split("|")
        if field.strip()
    )


def build_save_active_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    canonical_placeholder = (
        get_save_active_memory_placeholder_payload()
    )
    placeholders = tuple(placeholder_payloads)

    if (
        canonical_placeholder
        and canonical_placeholder not in placeholders
    ):
        placeholders = (
            *placeholders,
            canonical_placeholder,
        )

    return _build_internal_action_payload(
        query,
        placeholders,
    )
