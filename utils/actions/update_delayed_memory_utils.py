from __future__ import annotations

import json

from .delayed_memory_utils import is_delayed_memory_report_id
from .save_delayed_memory_utils import (
    normalize_delayed_memory_fact_roles,
    normalize_long_term_fact_ids,
)


UPDATE_DELAYED_MEMORY_FIELDS = frozenset({
    "tags",
    "body",
    "anchor_fact_ids",
    "absorbed_fact_ids",
})


def _normalize_tags(value) -> list[str]:
    if isinstance(value, list):
        source = value
    else:
        source = str(value or "").split(",")

    tags = []
    seen = set()

    for item in source:
        tag = str(item or "").strip().strip("\"'")
        normalized = tag.casefold()

        if not tag or normalized in seen:
            continue

        seen.add(normalized)
        tags.append(tag)

    return tags


def parse_update_delayed_memory_payload(payload: str) -> dict:
    text = str(payload or "").replace("\r\n", "\n").strip()

    if not text:
        return {}

    first_line, separator, remainder = text.partition("\n")
    report_id = first_line.strip().casefold()

    if not is_delayed_memory_report_id(report_id) or not separator:
        return {}

    try:
        raw_update = json.loads(remainder.strip())
    except (json.JSONDecodeError, TypeError, ValueError):
        return {}

    if not isinstance(raw_update, dict) or not raw_update:
        return {}

    unknown_fields = set(raw_update) - UPDATE_DELAYED_MEMORY_FIELDS
    if unknown_fields:
        return {}

    update = {"id": report_id}

    if "tags" in raw_update:
        tags = _normalize_tags(raw_update.get("tags"))
        if tags:
            update["tags"] = tags

    if "body" in raw_update:
        body = str(raw_update.get("body", "") or "").strip()
        if body:
            update["body"] = body

    requested_anchor_ids = (
        normalize_long_term_fact_ids(raw_update.get("anchor_fact_ids", []))
        if "anchor_fact_ids" in raw_update
        else []
    )
    requested_absorbed_ids = (
        normalize_long_term_fact_ids(raw_update.get("absorbed_fact_ids", []))
        if "absorbed_fact_ids" in raw_update
        else []
    )
    anchor_ids, absorbed_ids = normalize_delayed_memory_fact_roles(
        requested_anchor_ids,
        requested_absorbed_ids,
    )

    if "anchor_fact_ids" in raw_update and anchor_ids:
        update["anchor_fact_ids"] = anchor_ids

    if "absorbed_fact_ids" in raw_update and absorbed_ids:
        update["absorbed_fact_ids"] = absorbed_ids

    if len(update) == 1:
        return {}

    return update


def build_update_delayed_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:
    del placeholder_payloads

    text = str(query or "").strip()

    if not parse_update_delayed_memory_payload(text):
        return None

    return text
