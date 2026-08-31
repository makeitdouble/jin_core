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

UPDATE_ACTIVE_MEMORY_SELF_CLOSING_MARKER_RE = re.compile(
    (
        r"^\s*<\s*UPDATE_ACTIVE_MEMORY"
        r"(?P<attributes>\s+(?:[^<>\"']+|\"[^\"]*\"|'[^']*')*?)"
        r"\s*/\s*>\s*$"
    ),
    re.IGNORECASE | re.DOTALL,
)

UPDATE_ACTIVE_MEMORY_ATTRIBUTE_RE = re.compile(
    (
        r"(?P<name>[a-z][a-z0-9_]*)"
        r"\s*=\s*"
        r"(?:"
        r"\"(?P<double>[^\"]*)\""
        r"|'(?P<single>[^']*)'"
        r"|(?P<bare>[^\s\"'<>]+)"
        r")"
    ),
    re.IGNORECASE | re.DOTALL,
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


def _unwrap_update_active_memory_attribute_payload(
    payload: str,
) -> str:

    text = str(
        payload or ""
    ).strip()

    match = UPDATE_ACTIVE_MEMORY_SELF_CLOSING_MARKER_RE.fullmatch(
        text
    )

    if match is None:
        return text

    return str(
        match.group("attributes")
        or ""
    ).strip()


def _read_update_active_memory_attribute_pairs(
    payload: str,
) -> tuple[tuple[str, str], ...] | None:

    text = _unwrap_update_active_memory_attribute_payload(
        payload
    )

    if (
        not text
        or text.startswith("{")
        or not re.match(
            r"^\s*[a-z][a-z0-9_]*\s*=",
            text,
            re.IGNORECASE,
        )
    ):
        return None

    pairs = []
    position = 0

    while position < len(text):
        spacing_match = re.match(
            r"\s*",
            text[position:],
        )
        if spacing_match is not None:
            position += spacing_match.end()

        if position >= len(text):
            break

        match = UPDATE_ACTIVE_MEMORY_ATTRIBUTE_RE.match(
            text,
            position,
        )
        if match is None:
            return ()

        value = (
            match.group("double")
            if match.group("double") is not None
            else (
                match.group("single")
                if match.group("single") is not None
                else match.group("bare")
            )
        )
        pairs.append(
            (
                str(
                    match.group("name")
                    or ""
                ),
                str(
                    value
                    or ""
                ),
            )
        )
        position = match.end()

    return tuple(
        pairs
    )


def _parse_update_active_memory_attribute_payload(
    payload: str,
    *,
    include_reserved_fields: bool = False,
) -> tuple[str, tuple[tuple[str, str], ...]] | None:

    pairs = _read_update_active_memory_attribute_pairs(
        payload
    )

    if pairs is None:
        return None

    if not pairs:
        return "", ()

    active_memory_id = ""
    changes = []
    seen = set()

    for raw_name, raw_value in pairs:
        raw_field_name = str(
            raw_name or ""
        ).strip().casefold()

        if raw_field_name in {
            "active_memory_id",
            "id",
        }:
            if active_memory_id:
                return "", ()

            active_memory_id = str(
                raw_value or ""
            ).strip().casefold()
            continue

        if include_reserved_fields:
            field_name = raw_field_name
            if not re.fullmatch(
                r"[a-z][a-z0-9_]{0,31}",
                field_name,
            ):
                return "", ()
        else:
            if raw_field_name in ACTIVE_MEMORY_RESERVED_CUSTOM_FIELD_NAMES:
                continue

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
        seen.add(
            field_name
        )

    if not ACTIVE_MEMORY_UPDATE_ID_RE.fullmatch(
        active_memory_id
    ):
        return "", ()

    if not changes:
        return "", ()

    return active_memory_id, tuple(
        changes
    )


def _collect_update_active_memory_json_fields(
    data: dict,
) -> dict | None:

    for wrapper_key in (
        "fields_to_update",
        "field_to_update",
        "fields",
        "updates",
    ):
        if wrapper_key not in data:
            continue

        candidate = data.get(wrapper_key)
        if isinstance(candidate, dict):
            if (
                wrapper_key == "field_to_update"
                and len(candidate) != 1
            ):
                return None

            return candidate

        if wrapper_key in {
            "fields",
            "updates",
        }:
            return None

    return {
        key: value
        for key, value in data.items()
        if str(key or "").strip().casefold()
        not in {
            "active_memory_id",
            "id",
        }
    }


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

    raw_fields = _collect_update_active_memory_json_fields(
        data
    )

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

    attribute_result = _parse_update_active_memory_attribute_payload(
        text,
        include_reserved_fields=True,
    )

    if attribute_result is not None:
        return attribute_result

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

    raw_fields = _collect_update_active_memory_json_fields(
        data
    )
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

    attribute_result = _parse_update_active_memory_attribute_payload(
        text
    )

    if attribute_result is not None:
        return attribute_result

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
