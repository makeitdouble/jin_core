import json
import re

from .action_payload_utils import _build_internal_action_payload
from .active_memory_utils import (
    ACTIVE_MEMORY_RESERVED_CUSTOM_FIELD_NAMES,
    normalize_active_memory_custom_field_name,
    normalize_active_memory_custom_field_value,
    normalize_active_memory_slot_id,
)


UPDATE_ACTIVE_MEMORY_FAILURE_REASONS = {
    "invalid_update_active_memory_payload": "invalid payload",
    "active_memory_not_found": "incorrect id",
    "active_memory_update_no_changes": "no changes",
    "active_memory_update_failed": "update failed",
}

UPDATE_ACTIVE_MEMORY_CONDITIONS_FIELD = "conditions"


def _normalize_update_active_memory_field_value(
    field_name: str,
    value,
) -> str:
    """Normalize UPDATE_ACTIVE_MEMORY values without treating conditions
    like a bounded custom metadata field.

    `conditions` is the active-memory record's primary text field. It may be
    substantially longer than the 256-character limit used for custom suffix
    fields, so applying the custom-field normalizer here incorrectly rejects a
    valid conditions update.
    """

    if str(field_name or "").strip().casefold() == (
        UPDATE_ACTIVE_MEMORY_CONDITIONS_FIELD
    ):
        return re.sub(
            r"\s+",
            " ",
            str(value or "").strip(),
        )

    return normalize_active_memory_custom_field_value(
        value
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


def _read_update_active_memory_json_payload(
    payload: str,
) -> tuple[str, dict | None]:

    text = str(payload or "").strip()

    if not text.startswith("{"):
        return "", None

    try:
        data = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "", None

    if not isinstance(data, dict):
        return "", None

    active_memory_id = normalize_active_memory_slot_id(
        data.get("id")
    )
    if not active_memory_id:
        return "", None

    raw_fields = {
        key: value
        for key, value in data.items()
        if str(key or "").strip().casefold() != "id"
    }
    if not raw_fields:
        return "", None

    return active_memory_id, raw_fields


def _parse_update_active_memory_json_payload(
    payload: str,
    *,
    include_reserved_fields: bool = False,
) -> tuple[str, tuple[tuple[str, str], ...]]:

    active_memory_id, raw_fields = _read_update_active_memory_json_payload(
        payload
    )
    if not active_memory_id or not raw_fields:
        return "", ()

    changes = []
    seen = set()

    for raw_name, raw_value in raw_fields.items():
        if isinstance(raw_value, (dict, list)):
            return "", ()

        raw_field_name = str(raw_name or "").strip().casefold()

        if include_reserved_fields:
            if not re.fullmatch(
                r"[a-z][a-z0-9_]{0,31}",
                raw_field_name,
            ):
                return "", ()
            field_name = raw_field_name
        else:
            if (
                raw_field_name in ACTIVE_MEMORY_RESERVED_CUSTOM_FIELD_NAMES
                and raw_field_name != UPDATE_ACTIVE_MEMORY_CONDITIONS_FIELD
            ):
                return "", ()

            field_name = (
                UPDATE_ACTIVE_MEMORY_CONDITIONS_FIELD
                if raw_field_name == UPDATE_ACTIVE_MEMORY_CONDITIONS_FIELD
                else normalize_active_memory_custom_field_name(raw_name)
            )

        field_value = _normalize_update_active_memory_field_value(
            field_name,
            raw_value,
        )

        if not field_name or not field_value or field_name in seen:
            return "", ()

        changes.append((field_name, field_value))
        seen.add(field_name)

    return active_memory_id, tuple(changes)


def parse_update_active_memory_payload_fields(
    payload: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Read the exact new-format id and submitted flat JSON fields."""

    return _parse_update_active_memory_json_payload(
        payload,
        include_reserved_fields=True,
    )


def parse_update_active_memory_payload(
    payload: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Parse only the flat SAVE_ACTIVE_MEMORY update JSON shape."""

    return _parse_update_active_memory_json_payload(payload)


def format_update_active_memory_failure_reason(
    result: dict,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return "update failed"

    error = str(
        result.get(
            "error",
            "",
        )
        or ""
    ).strip().casefold()

    if error == "active_memory_field_not_declared":
        unknown_fields = [
            str(field or "").strip()
            for field in result.get(
                "unknown_fields",
                [],
            )
            or []
            if str(field or "").strip()
        ]

        if unknown_fields:
            label = (
                "unknown field"
                if len(unknown_fields) == 1
                else "unknown fields"
            )
            return (
                f"{label}: "
                + ", ".join(
                    unknown_fields
                )
            )

        return "unknown field"

    reason = UPDATE_ACTIVE_MEMORY_FAILURE_REASONS.get(
        error,
        "",
    )

    if reason:
        return reason

    if error:
        return error.replace(
            "_",
            " ",
        )

    return "update failed"
