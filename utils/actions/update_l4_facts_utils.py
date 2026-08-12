from __future__ import annotations

import json
import re


MAX_UPDATE_L4_FACTS_MESSAGE_CHARS = 1200
L4_FACT_ID_RE = re.compile(r"^F[1-9]\d*$", re.IGNORECASE)
L4_FACT_ID_SCAN_RE = re.compile(r"\bF[1-9]\d*\b", re.IGNORECASE)
FORBIDDEN_UPDATE_L4_FACTS_NOTE_RE = re.compile(
    r"\b(delete|deleted|deleting|remove|removed|removing|erase|erased|"
    r"erasing|drop|dropped|dropping|purge|purged|purging)\b",
    re.IGNORECASE,
)


def normalize_update_l4_fact_ids(raw_fact_ids) -> list[str] | None:
    if raw_fact_ids is None:
        return []

    if not isinstance(raw_fact_ids, list):
        return None

    fact_ids = []
    seen = set()

    for raw_fact_id in raw_fact_ids:
        fact_id = str(raw_fact_id or "").strip().upper()

        if not L4_FACT_ID_RE.fullmatch(fact_id):
            return None
        if fact_id in seen:
            continue

        seen.add(fact_id)
        fact_ids.append(fact_id)

    return fact_ids


def normalize_update_l4_message(value) -> str:
    message = " ".join(str(value or "").split()).strip()

    if not message:
        return ""

    if len(message) > MAX_UPDATE_L4_FACTS_MESSAGE_CHARS:
        return ""

    if FORBIDDEN_UPDATE_L4_FACTS_NOTE_RE.search(message):
        return ""

    return message


def scan_update_l4_fact_ids(message: str) -> list[str]:
    fact_ids = []
    seen = set()

    for match in L4_FACT_ID_SCAN_RE.finditer(message):
        fact_id = match.group(0).upper()
        if fact_id in seen:
            continue
        seen.add(fact_id)
        fact_ids.append(fact_id)

    return fact_ids


def parse_update_l4_facts_payload(payload: str) -> dict:
    text = str(payload or "").strip()

    if not text:
        return {}

    try:
        value = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        message = normalize_update_l4_message(text)
        if not message:
            return {}

        return {
            "fact_ids": scan_update_l4_fact_ids(message),
            "message": message,
        }

    if not isinstance(value, dict):
        return {}

    fact_ids = normalize_update_l4_fact_ids(value.get("fact_ids"))
    if fact_ids is None:
        return {}

    message = normalize_update_l4_message(value.get("message"))
    if not message:
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
