import json
import re

from .action_payload_utils import _build_internal_action_payload
from .active_memory_utils import (
    ACTIVE_MEMORY_RESERVED_CUSTOM_FIELD_NAMES,
    normalize_active_memory_custom_field_name,
    normalize_active_memory_custom_field_value,
)


ACTIVE_MEMORY_UPDATE_ID_RE = re.compile(
    r"(?<![a-z0-9])([a-z0-9]{6})(?![a-z0-9])",
    re.IGNORECASE,
)

UPDATE_ACTIVE_MEMORY_FAILURE_REASONS = {
    "invalid_update_active_memory_payload": "invalid payload",
    "active_memory_not_found": "incorrect id",
    "active_memory_update_no_changes": "no changes",
    "active_memory_update_failed": "update failed",
}


def build_update_active_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    return _build_internal_action_payload(
        query,
        placeholder_payloads,
        reject_placeholders=False,
    )


def _parse_update_active_memory_json_payload(
    payload: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:

    text = str(
        payload or ""
    ).strip()

    if not text.startswith("{"):
        return "", ()

    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return "", ()

    if not isinstance(
        data,
        dict,
    ):
        return "", ()

    active_memory_id = str(
        data.get("active_memory_id")
        or data.get("id")
        or ""
    ).strip().casefold()

    if not ACTIVE_MEMORY_UPDATE_ID_RE.fullmatch(
        active_memory_id
    ):
        return "", ()

    raw_fields = (
        data.get("fields")
        if "fields" in data
        else data.get("updates")
    )

    if raw_fields is None:
        raw_fields = {
            key: value
            for key, value in data.items()
            if str(key or "").strip().casefold()
            not in {
                "active_memory_id",
                "id",
            }
        }

    if not isinstance(
        raw_fields,
        dict,
    ) or not raw_fields:
        return "", ()

    changes = []
    seen = set()

    for raw_name, raw_value in raw_fields.items():
        raw_field_name = str(
            raw_name or ""
        ).strip().casefold()

        if raw_field_name in ACTIVE_MEMORY_RESERVED_CUSTOM_FIELD_NAMES:
            continue

        if isinstance(
            raw_value,
            (dict, list),
        ):
            return "", ()

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

        changes.append(
            (
                field_name,
                field_value,
            )
        )
        seen.add(field_name)

    return active_memory_id, tuple(changes)


def parse_update_active_memory_payload_fields(
    payload: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:
    """Read the id and submitted values from flat or legacy nested JSON."""

    text = str(payload or "").strip()
    if not text.startswith("{"):
        return parse_update_active_memory_payload(text)

    try:
        data = json.loads(text)
    except (TypeError, ValueError):
        return "", ()

    if not isinstance(data, dict):
        return "", ()

    active_memory_id = str(
        data.get("active_memory_id")
        or data.get("id")
        or ""
    ).strip().casefold()
    if not ACTIVE_MEMORY_UPDATE_ID_RE.fullmatch(active_memory_id):
        return "", ()

    raw_fields = (
        data.get("fields")
        if "fields" in data
        else data.get("updates")
    )
    if raw_fields is None:
        raw_fields = {
            key: value
            for key, value in data.items()
            if str(key or "").strip().casefold()
            not in {"active_memory_id", "id"}
        }
    if not isinstance(raw_fields, dict) or not raw_fields:
        return "", ()

    fields = []
    seen = set()
    for raw_name, raw_value in raw_fields.items():
        if isinstance(raw_value, (dict, list)):
            return "", ()

        field_name = str(raw_name or "").strip().casefold()
        field_value = normalize_active_memory_custom_field_value(
            raw_value
        )
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", field_name)
            or not field_value
            or field_name in seen
        ):
            return "", ()

        fields.append((field_name, field_value))
        seen.add(field_name)

    return active_memory_id, tuple(fields)


def parse_update_active_memory_payload(
    payload: str,
) -> tuple[str, tuple[tuple[str, str], ...]]:

    text = str(
        payload or ""
    ).strip()

    if text.startswith("{"):
        return _parse_update_active_memory_json_payload(
            text
        )

    lines = [
        str(line or "").strip()
        for line in text.splitlines()
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
