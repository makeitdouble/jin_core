from __future__ import annotations

import re

from .delayed_memory_utils import is_delayed_memory_report_id
from .save_delayed_memory_utils import normalize_long_term_fact_ids


UPDATE_DELAYED_MEMORY_FIELD_RE = re.compile(
    r"(?im)^[^\S\r\n]*(tags|body|long_term_facts_ids)"
    r"[^\S\r\n]*:[^\S\r\n]*(.*)$",
)


def _normalize_tags(value) -> list[str]:
    source = value if isinstance(value, list) else str(value or "").split(",")
    tags = []
    seen = set()

    for item in source:
        tag = str(item or "").strip()
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

    if not is_delayed_memory_report_id(report_id):
        return {}

    body_text = remainder if separator else ""
    field_matches = list(UPDATE_DELAYED_MEMORY_FIELD_RE.finditer(body_text))

    if not field_matches:
        return {}

    fields = {}

    for index, match in enumerate(field_matches):
        field_name = str(match.group(1) or "").casefold()
        inline_value = str(match.group(2) or "").strip()
        next_start = (
            field_matches[index + 1].start()
            if index + 1 < len(field_matches)
            else len(body_text)
        )
        block_value = body_text[match.end():next_start].strip("\n")
        combined = "\n".join(
            part
            for part in (inline_value, block_value)
            if part
        ).strip()

        if field_name == "tags":
            fields[field_name] = _normalize_tags(combined)
        elif field_name == "long_term_facts_ids":
            fields[field_name] = normalize_long_term_fact_ids(combined)
        else:
            fields[field_name] = combined

    tags = fields.get("tags", [])
    fact_ids = fields.get("long_term_facts_ids", [])
    body = str(fields.get("body", "") or "").strip()

    if not tags and not fact_ids and not body:
        return {}

    return {
        "id": report_id,
        "tags": tags,
        "long_term_facts_ids": fact_ids,
        "body": body,
    }


def build_update_delayed_memory_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:
    del placeholder_payloads

    text = str(query or "").strip()

    if not parse_update_delayed_memory_payload(text):
        return None

    return text
