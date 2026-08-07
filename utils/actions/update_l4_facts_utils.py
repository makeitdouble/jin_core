from __future__ import annotations

import json


MAX_UPDATE_L4_FACTS_MESSAGE_CHARS = 1200


def parse_update_l4_facts_payload(payload: str) -> dict:
    text = str(payload or "").strip()

    if not text:
        return {}

    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}

    if not isinstance(value, dict):
        return {}

    raw_fact_ids = value.get("fact_ids")
    if not isinstance(raw_fact_ids, list):
        return {}

    fact_ids = []
    seen = set()

    for raw_fact_id in raw_fact_ids:
        fact_id = str(raw_fact_id or "").strip()

        if not fact_id.startswith("l4_"):
            return {}
        if fact_id in seen:
            continue

        seen.add(fact_id)
        fact_ids.append(fact_id)

    message = " ".join(
        str(value.get("message") or "").split()
    ).strip()

    if not fact_ids or not message:
        return {}

    if len(message) > MAX_UPDATE_L4_FACTS_MESSAGE_CHARS:
        return {}

    return {
        "fact_ids": fact_ids,
        "message": message,
    }


def build_update_l4_facts_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:
    del placeholder_payloads

    parsed = parse_update_l4_facts_payload(query)

    if not parsed:
        return None

    return json.dumps(
        parsed,
        ensure_ascii=False,
        separators=(",", ":"),
    )
