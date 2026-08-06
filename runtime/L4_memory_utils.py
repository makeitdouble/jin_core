from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import re
from xml.sax.saxutils import escape

from runtime.L4_memory_rules import (
    L4_EXTRACTION_SYSTEM_PROMPT,
    L4_MERGE_SYSTEM_PROMPT,
    L4_JIN_NOTE_SYSTEM_PROMPT,
)


L4_STORE_VERSION = 1
L4_FACT_ID_PREFIX = "l4_"
L4_PENDING_FACT_ID_PREFIX = "l4p_"
L4_FIELD_STATUS_PENDING = "pending"
L4_FIELD_STATUS_ANALYZED = "analyzed"
L4_ALLOWED_CATEGORIES = {
    "user_fact",
    "user_preference",
    "project_fact",
    "project_decision",
    "persistent_constraint",
    "environment",
    "other",
}
L4_ALLOWED_MERGE_ACTIONS = {
    "create",
    "update",
    "reinforce",
    "ignore",
}


def build_l4_extraction_system_prompt() -> str:
    return L4_EXTRACTION_SYSTEM_PROMPT


def build_l4_extraction_user_prompt(*, pending_fields: list[dict]) -> str:
    return (
        "Extract permanent-memory candidates from all pending Facts Memory "
        "fields below.\n\n"
        + json.dumps(
            {"facts_memory_fields": pending_fields},
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def build_l4_merge_system_prompt() -> str:
    return L4_MERGE_SYSTEM_PROMPT


def build_l4_jin_note_system_prompt() -> str:
    return L4_JIN_NOTE_SYSTEM_PROMPT


def build_l4_jin_note_user_prompt(
    *,
    existing_facts: list[dict],
    selected_fact_ids: list[str],
    message: str,
) -> str:
    return (
        "Resolve this focused conversational clarification against the current "
        "L4 memory.\n\n"
        + json.dumps(
            {
                "existing_facts": [
                    {
                        "id": normalize_l4_text(fact.get("id")),
                        "key": normalize_l4_text(fact.get("key")),
                        "value": normalize_l4_text(fact.get("value")),
                        "category": normalize_l4_text(fact.get("category")),
                    }
                    for fact in existing_facts
                    if isinstance(fact, dict)
                ],
                "selected_fact_ids": selected_fact_ids,
                "message": normalize_l4_text(message),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def build_l4_merge_user_prompt(
    *,
    existing_facts: list[dict],
    pending_facts: list[dict],
) -> str:
    return (
        "Consolidate the entire pending batch into the current long-term "
        "memory. Return exactly one operation for every pending_id.\n\n"
        + json.dumps(
            {
                "existing_facts": existing_facts,
                "pending_facts": pending_facts,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def normalize_l4_text(value) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def normalize_l4_key(value) -> str:
    key = normalize_l4_text(value).casefold()
    key = re.sub(r"\s+", "_", key)
    key = re.sub(r"[^a-z0-9а-яё._-]+", "_", key)
    key = re.sub(r"_+", "_", key)
    return key.strip("._-")


def normalize_l4_category(value) -> str:
    category = normalize_l4_key(value)
    return category if category in L4_ALLOWED_CATEGORIES else "other"


def normalize_l4_string_list(value) -> list[str]:
    candidates = value if isinstance(value, list) else [value]
    result = []
    seen = set()

    for candidate in candidates:
        text = normalize_l4_text(candidate)
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)

    return result


def merge_l4_string_lists(*values) -> list[str]:
    result = []
    seen = set()

    for value in values:
        for item in normalize_l4_string_list(value):
            if item in seen:
                continue
            seen.add(item)
            result.append(item)

    return result


def normalize_l4_deleted_fact_ids(value) -> list[str]:
    return [
        fact_id
        for fact_id in normalize_l4_string_list(value)
        if fact_id.startswith(L4_FACT_ID_PREFIX)
    ]


def build_l4_content_hash(content: str) -> str:
    return hashlib.sha256(
        normalize_l4_text(content).encode("utf-8")
    ).hexdigest()[:16]


def build_l4_fact_id(*, key: str, value: str, pending: bool = False) -> str:
    prefix = L4_PENDING_FACT_ID_PREFIX if pending else L4_FACT_ID_PREFIX
    digest = hashlib.sha256(f"{key}\0{value}".encode("utf-8")).hexdigest()[:12]
    return f"{prefix}{digest}"


def normalize_l4_fact(
    value,
    *,
    pending: bool = False,
    now: str | None = None,
) -> dict | None:
    if not isinstance(value, dict):
        return None

    key = normalize_l4_key(value.get("key"))
    fact_value = normalize_l4_text(value.get("value") or value.get("content"))
    if not key or not fact_value:
        return None

    current_time = now or utc_now_iso()
    expected_prefix = L4_PENDING_FACT_ID_PREFIX if pending else L4_FACT_ID_PREFIX
    fact_id = normalize_l4_text(value.get("id"))
    if not fact_id.startswith(expected_prefix):
        fact_id = build_l4_fact_id(key=key, value=fact_value, pending=pending)

    try:
        mention_count = max(1, int(value.get("mention_count") or 1))
    except (TypeError, ValueError):
        mention_count = 1

    return {
        "id": fact_id,
        "key": key,
        "value": fact_value,
        "category": normalize_l4_category(value.get("category")),
        "mention_count": mention_count,
        "created_at": normalize_l4_text(value.get("created_at")) or current_time,
        "updated_at": normalize_l4_text(value.get("updated_at")) or current_time,
        "source_session_ids": normalize_l4_string_list(
            value.get("source_session_ids")
            or value.get("source_session_id")
            or value.get("session_id")
        ),
        "source_runtime_snapshot_ids": normalize_l4_string_list(
            value.get("source_runtime_snapshot_ids")
            or value.get("source_runtime_snapshot_id")
            or value.get("runtime_snapshot_id")
        ),
        "source_keys": normalize_l4_string_list(
            value.get("source_keys") or value.get("source_key")
        ),
        "source_fact_ids": normalize_l4_string_list(
            value.get("source_fact_ids") or value.get("source_fact_id")
        ),
    }


def merge_same_l4_fact(existing: dict, incoming: dict, *, now: str) -> dict:
    result = dict(existing)
    result["mention_count"] = max(1, int(existing.get("mention_count") or 1)) + max(
        1,
        int(incoming.get("mention_count") or 1),
    )
    result["source_session_ids"] = merge_l4_string_lists(
        existing.get("source_session_ids"),
        incoming.get("source_session_ids"),
    )
    result["source_runtime_snapshot_ids"] = merge_l4_string_lists(
        existing.get("source_runtime_snapshot_ids"),
        incoming.get("source_runtime_snapshot_ids"),
    )
    result["source_keys"] = merge_l4_string_lists(
        existing.get("source_keys"),
        incoming.get("source_keys"),
    )
    result["source_fact_ids"] = merge_l4_string_lists(
        existing.get("source_fact_ids"),
        incoming.get("source_fact_ids"),
    )
    result["updated_at"] = now
    return result


def deduplicate_l4_facts(facts: list[dict], *, pending: bool, now: str) -> list[dict]:
    result = []
    by_id = {}

    for raw_fact in facts:
        fact = normalize_l4_fact(raw_fact, pending=pending, now=now)
        if fact is None:
            continue

        existing_index = by_id.get(fact["id"])
        if existing_index is None:
            by_id[fact["id"]] = len(result)
            result.append(fact)
            continue

        result[existing_index] = merge_same_l4_fact(
            result[existing_index],
            fact,
            now=now,
        )

    return result


def merge_l4_snapshot_fact(
    existing: dict,
    incoming: dict,
    *,
    pending: bool,
    now: str,
) -> dict:

    existing_fact = normalize_l4_fact(
        existing,
        pending=pending,
        now=now,
    )
    incoming_fact = normalize_l4_fact(
        incoming,
        pending=pending,
        now=now,
    )

    if existing_fact is None:
        return incoming_fact or {}
    if incoming_fact is None:
        return existing_fact

    existing_updated_at = normalize_l4_text(
        existing_fact.get("updated_at")
    )
    incoming_updated_at = normalize_l4_text(
        incoming_fact.get("updated_at")
    )
    prefer_incoming = incoming_updated_at > existing_updated_at
    base = incoming_fact if prefer_incoming else existing_fact
    existing_id = normalize_l4_text(
        existing_fact.get("id")
    )
    incoming_id = normalize_l4_text(
        incoming_fact.get("id")
    )

    merged = {
        **base,
        "id": existing_id or incoming_id,
        "mention_count": max(
            max(1, int(existing_fact.get("mention_count") or 1)),
            max(1, int(incoming_fact.get("mention_count") or 1)),
        ),
        "created_at": (
            existing_fact.get("created_at")
            or incoming_fact.get("created_at")
            or now
        ),
        "updated_at": (
            max(
                existing_updated_at,
                incoming_updated_at,
            )
            or now
        ),
        "source_session_ids": merge_l4_string_lists(
            existing_fact.get("source_session_ids"),
            incoming_fact.get("source_session_ids"),
        ),
        "source_runtime_snapshot_ids": merge_l4_string_lists(
            existing_fact.get("source_runtime_snapshot_ids"),
            incoming_fact.get("source_runtime_snapshot_ids"),
        ),
        "source_keys": merge_l4_string_lists(
            existing_fact.get("source_keys"),
            incoming_fact.get("source_keys"),
        ),
        "source_fact_ids": merge_l4_string_lists(
            existing_fact.get("source_fact_ids"),
            incoming_fact.get("source_fact_ids"),
            [incoming_id] if incoming_id and incoming_id != existing_id else [],
        ),
    }

    normalized = normalize_l4_fact(
        merged,
        pending=pending,
        now=now,
    )
    return normalized or existing_fact


def merge_l4_snapshot_fact_lists(
    existing_facts,
    incoming_facts,
    *,
    pending: bool,
    now: str,
) -> tuple[list[dict], bool]:

    normalized_existing = deduplicate_l4_facts(
        existing_facts if isinstance(existing_facts, list) else [],
        pending=pending,
        now=now,
    )
    original = deepcopy(
        normalized_existing
    )

    facts = []
    for fact in normalized_existing:
        existing_index = next(
            (
                index
                for index, existing_fact in enumerate(facts)
                if existing_fact.get("key") == fact.get("key")
            ),
            None,
        )
        if existing_index is None:
            facts.append(
                dict(fact)
            )
            continue

        facts[existing_index] = merge_l4_snapshot_fact(
            facts[existing_index],
            fact,
            pending=pending,
            now=now,
        )

    by_id = {
        fact["id"]: index
        for index, fact in enumerate(facts)
    }
    by_key = {
        fact["key"]: index
        for index, fact in enumerate(facts)
    }

    incoming = deduplicate_l4_facts(
        incoming_facts if isinstance(incoming_facts, list) else [],
        pending=pending,
        now=now,
    )

    for fact in incoming:
        existing_index = by_id.get(
            fact["id"]
        )
        if existing_index is None:
            existing_index = by_key.get(
                fact["key"]
            )

        if existing_index is None:
            by_id[fact["id"]] = len(facts)
            by_key[fact["key"]] = len(facts)
            facts.append(
                fact
            )
            continue

        merged = merge_l4_snapshot_fact(
            facts[existing_index],
            fact,
            pending=pending,
            now=now,
        )
        previous_id = facts[existing_index]["id"]
        previous_key = facts[existing_index]["key"]
        facts[existing_index] = merged
        by_id.pop(
            previous_id,
            None,
        )
        by_key.pop(
            previous_key,
            None,
        )
        by_id[merged["id"]] = existing_index
        by_key[merged["key"]] = existing_index

    return facts, facts != original


def collect_l4_processed_pending_fact_ids(facts) -> set[str]:
    processed_ids = set()

    for fact in facts if isinstance(facts, list) else []:
        if not isinstance(fact, dict):
            continue

        for source_fact_id in normalize_l4_string_list(
            fact.get("source_fact_ids")
        ):
            if source_fact_id.startswith(L4_PENDING_FACT_ID_PREFIX):
                processed_ids.add(source_fact_id)

    return processed_ids


def prune_l4_processed_pending_facts(
    *,
    facts,
    pending_facts,
) -> list[dict]:
    processed_ids = collect_l4_processed_pending_fact_ids(facts)
    if not processed_ids:
        return pending_facts

    return [
        fact
        for fact in pending_facts
        if normalize_l4_text(fact.get("id")) not in processed_ids
    ]


def merge_l4_store_snapshots(
    primary_store,
    incoming_store,
    *,
    now: str | None = None,
) -> tuple[dict, dict]:

    current_time = now or utc_now_iso()
    primary = normalize_l4_store(
        primary_store,
        now=current_time,
    )
    incoming = normalize_l4_store(
        incoming_store,
        now=current_time,
    )

    deleted_fact_ids = merge_l4_string_lists(
        primary.get("deleted_fact_ids"),
        incoming.get("deleted_fact_ids"),
    )
    deleted_fact_id_set = set(deleted_fact_ids)

    facts, _facts_changed = merge_l4_snapshot_fact_lists(
        [
            fact
            for fact in primary.get("facts") or []
            if fact.get("id") not in deleted_fact_id_set
        ],
        [
            fact
            for fact in incoming.get("facts") or []
            if fact.get("id") not in deleted_fact_id_set
        ],
        pending=False,
        now=current_time,
    )
    pending_facts, _pending_changed = merge_l4_snapshot_fact_lists(
        primary.get("pending_facts"),
        incoming.get("pending_facts"),
        pending=True,
        now=current_time,
    )
    pending_facts = prune_l4_processed_pending_facts(
        facts=facts,
        pending_facts=pending_facts,
    )
    changed = bool(
        facts != primary.get("facts")
        or pending_facts != primary.get("pending_facts")
        or deleted_fact_ids != primary.get("deleted_fact_ids")
    )

    merged = {
        **primary,
        "facts": facts,
        "pending_facts": pending_facts,
        "deleted_fact_ids": deleted_fact_ids,
    }

    if changed:
        merged["revision"] = max(
            int(primary.get("revision") or 0),
            int(incoming.get("revision") or 0),
        ) + 1
        merged["updated_at"] = current_time

    return merged, {
        "changed": changed,
        "facts_count": len(facts),
        "pending_count": len(pending_facts),
        "deleted_count": len(deleted_fact_ids),
    }


def empty_l4_store(*, now: str | None = None) -> dict:
    return {
        "version": L4_STORE_VERSION,
        "revision": 0,
        "updated_at": now or "",
        "facts": [],
        "pending_facts": [],
        "deleted_fact_ids": [],
    }


def normalize_l4_store(value, *, now: str | None = None) -> dict:
    current_time = now or utc_now_iso()
    if not isinstance(value, dict):
        return empty_l4_store()

    try:
        revision = max(0, int(value.get("revision") or 0))
    except (TypeError, ValueError):
        revision = 0

    facts = value.get("facts") if isinstance(value.get("facts"), list) else []
    pending = (
        value.get("pending_facts")
        if isinstance(value.get("pending_facts"), list)
        else []
    )
    deleted_fact_ids = normalize_l4_deleted_fact_ids(
        value.get("deleted_fact_ids")
    )
    deleted_fact_id_set = set(deleted_fact_ids)

    facts = [
        fact
        for fact in deduplicate_l4_facts(
            facts,
            pending=False,
            now=current_time,
        )
        if fact.get("id") not in deleted_fact_id_set
    ]
    pending_facts = prune_l4_processed_pending_facts(
        facts=facts,
        pending_facts=deduplicate_l4_facts(
            pending,
            pending=True,
            now=current_time,
        ),
    )

    return {
        "version": L4_STORE_VERSION,
        "revision": revision,
        "updated_at": normalize_l4_text(value.get("updated_at")) or current_time,
        "facts": facts,
        "pending_facts": pending_facts,
        "deleted_fact_ids": deleted_fact_ids,
    }


def normalize_facts_memory_field(
    *,
    key,
    field,
    session_id: str = "",
) -> dict | None:
    if not isinstance(field, dict):
        return None

    normalized_key = normalize_l4_key(key)
    content = normalize_l4_text(field.get("content") or field.get("value"))
    if not normalized_key or not content:
        return None

    status = normalize_l4_key(field.get("l4_status"))
    if status == "analized":
        status = L4_FIELD_STATUS_ANALYZED
    if status not in {L4_FIELD_STATUS_PENDING, L4_FIELD_STATUS_ANALYZED}:
        status = L4_FIELD_STATUS_PENDING

    return {
        **field,
        "content": content,
        "runtime_snapshot_id": normalize_l4_text(field.get("runtime_snapshot_id")),
        "session_id": normalize_l4_text(field.get("session_id") or session_id),
        "l4_status": status,
        "l4_content_hash": normalize_l4_text(field.get("l4_content_hash"))
        or build_l4_content_hash(content),
        "l4_analyzed_at": (
            normalize_l4_text(field.get("l4_analyzed_at"))
            if status == L4_FIELD_STATUS_ANALYZED
            else ""
        ),
    }


def normalize_facts_memory_records(value) -> list[dict]:
    if not isinstance(value, list):
        return []

    records = []
    for raw_record in value:
        if not isinstance(raw_record, dict):
            continue

        session_id = normalize_l4_text(raw_record.get("session_id"))
        storage_key = normalize_l4_text(
            raw_record.get("storage_key") or raw_record.get("key")
        )
        raw_signals = raw_record.get("signals")
        if not isinstance(raw_signals, dict):
            continue

        signals = {}
        for key, field in raw_signals.items():
            normalized_key = normalize_l4_key(key)
            normalized_field = normalize_facts_memory_field(
                key=normalized_key,
                field=field,
                session_id=session_id,
            )
            if normalized_field is not None:
                signals[normalized_key] = normalized_field

        if signals:
            records.append({
                "storage_key": storage_key,
                "session_id": session_id,
                "signal_count": len(signals),
                "signals": signals,
            })

    return records


def collect_pending_facts_memory_fields(records: list[dict]) -> list[dict]:
    pending = []
    seen = set()

    for record in normalize_facts_memory_records(records):
        session_id = record.get("session_id", "")
        for key, field in record.get("signals", {}).items():
            if field.get("l4_status") != L4_FIELD_STATUS_PENDING:
                continue

            identity = (session_id, key, field.get("l4_content_hash", ""))
            if identity in seen:
                continue
            seen.add(identity)
            pending.append({
                "key": key,
                "content": field.get("content", ""),
                "runtime_snapshot_id": field.get("runtime_snapshot_id", ""),
                "session_id": field.get("session_id") or session_id,
                "l4_content_hash": field.get("l4_content_hash", ""),
            })

    return pending


def mark_facts_memory_fields_analyzed(
    records: list[dict],
    fields: list[dict],
    *,
    now: str | None = None,
) -> tuple[list[dict], bool]:
    analyzed_at = now or utc_now_iso()
    identities = {
        (
            normalize_l4_text(field.get("session_id")),
            normalize_l4_key(field.get("key")),
            normalize_l4_text(field.get("l4_content_hash")),
        )
        for field in fields
        if isinstance(field, dict)
    }
    updated_records = normalize_facts_memory_records(records)
    changed = False

    for record in updated_records:
        session_id = record.get("session_id", "")
        for key, field in record.get("signals", {}).items():
            identity = (
                field.get("session_id") or session_id,
                key,
                field.get("l4_content_hash", ""),
            )
            if identity not in identities:
                continue
            if field.get("l4_status") != L4_FIELD_STATUS_ANALYZED:
                field["l4_status"] = L4_FIELD_STATUS_ANALYZED
                field["l4_analyzed_at"] = analyzed_at
                changed = True

    return updated_records, changed


def extract_l4_json_payload(text: str) -> dict | None:
    source = str(text or "").strip()
    if not source:
        return None

    candidates = [source]
    candidates.extend(
        re.findall(
            r"```(?:json)?\s*(\{.*?\})\s*```",
            source,
            flags=re.IGNORECASE | re.DOTALL,
        )
    )

    first_brace = source.find("{")
    last_brace = source.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        candidates.append(source[first_brace:last_brace + 1])

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if isinstance(payload, dict):
            return payload

    return None


def normalize_l4_candidates(
    payload,
    *,
    source_fields: list[dict],
    now: str | None = None,
) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("facts"), list):
        return []

    current_time = now or utc_now_iso()
    fields_by_key: dict[str, list[dict]] = {}
    for field in source_fields:
        if not isinstance(field, dict):
            continue
        key = normalize_l4_key(field.get("key"))
        if key:
            fields_by_key.setdefault(key, []).append(field)

    candidates = []
    for raw_candidate in payload["facts"]:
        if not isinstance(raw_candidate, dict):
            continue

        source_keys = normalize_l4_string_list(raw_candidate.get("source_keys"))
        source_keys = [key for key in map(normalize_l4_key, source_keys) if key in fields_by_key]
        if not source_keys and len(fields_by_key) == 1:
            source_keys = list(fields_by_key)
        if not source_keys:
            continue

        matched_fields = [
            field
            for source_key in source_keys
            for field in fields_by_key[source_key]
        ]
        candidate = normalize_l4_fact(
            {
                **raw_candidate,
                "source_keys": source_keys,
                "source_session_ids": [
                    field.get("session_id", "") for field in matched_fields
                ],
                "source_runtime_snapshot_ids": [
                    field.get("runtime_snapshot_id", "") for field in matched_fields
                ],
                "created_at": current_time,
                "updated_at": current_time,
            },
            pending=True,
            now=current_time,
        )
        if candidate is not None:
            candidates.append(candidate)

    return deduplicate_l4_facts(candidates, pending=True, now=current_time)


def add_l4_pending_candidates(
    store,
    candidates: list[dict],
    *,
    now: str | None = None,
) -> tuple[dict, dict]:
    current_time = now or utc_now_iso()
    next_store = normalize_l4_store(store, now=current_time)
    pending = list(next_store["pending_facts"])
    by_id = {fact["id"]: index for index, fact in enumerate(pending)}
    added_ids = []
    reinforced_ids = []

    for raw_candidate in candidates:
        candidate = normalize_l4_fact(raw_candidate, pending=True, now=current_time)
        if candidate is None:
            continue

        index = by_id.get(candidate["id"])
        if index is None:
            by_id[candidate["id"]] = len(pending)
            pending.append(candidate)
            added_ids.append(candidate["id"])
        else:
            pending[index] = merge_same_l4_fact(
                pending[index],
                candidate,
                now=current_time,
            )
            reinforced_ids.append(candidate["id"])

    changed = bool(added_ids or reinforced_ids)
    if changed:
        next_store["pending_facts"] = pending
        next_store["revision"] += 1
        next_store["updated_at"] = current_time

    return next_store, {
        "added_pending_ids": added_ids,
        "reinforced_pending_ids": reinforced_ids,
        "pending_count": len(next_store["pending_facts"]),
        "changed": changed,
    }


def normalize_l4_merge_operations(payload) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("operations"), list):
        return []

    operations = []
    for raw_operation in payload["operations"]:
        if not isinstance(raw_operation, dict):
            continue

        action = normalize_l4_key(raw_operation.get("action"))
        pending_id = normalize_l4_text(raw_operation.get("pending_id"))
        if action not in L4_ALLOWED_MERGE_ACTIONS or not pending_id:
            continue

        operation = {
            "action": action,
            "pending_id": pending_id,
        }
        target_id = normalize_l4_text(raw_operation.get("target_id"))
        if target_id:
            operation["target_id"] = target_id

        for key in ("key", "value", "category"):
            if key in raw_operation:
                operation[key] = raw_operation[key]

        operations.append(operation)

    return operations


def validate_l4_merge_operations(store, operations: list[dict]) -> tuple[bool, str]:
    normalized_store = normalize_l4_store(store)
    pending = normalized_store["pending_facts"]
    pending_ids = {fact["id"] for fact in pending}
    fact_ids = {fact["id"] for fact in normalized_store["facts"]}

    if len(operations) != len(pending):
        return False, "operation_count_mismatch"

    seen = set()
    for operation in operations:
        pending_id = operation.get("pending_id")
        if pending_id not in pending_ids:
            return False, "unknown_pending_id"
        if pending_id in seen:
            return False, "duplicate_pending_operation"
        seen.add(pending_id)

        action = operation.get("action")
        if action in {"update", "reinforce"}:
            if operation.get("target_id") not in fact_ids:
                return False, "unknown_target_id"

    if seen != pending_ids:
        return False, "missing_pending_operation"

    return True, ""


def merge_fact_sources(existing: dict, incoming: dict) -> dict:
    existing_id = normalize_l4_text(existing.get("id"))
    incoming_id = normalize_l4_text(incoming.get("id"))

    return {
        "source_session_ids": merge_l4_string_lists(
            existing.get("source_session_ids"),
            incoming.get("source_session_ids"),
        ),
        "source_runtime_snapshot_ids": merge_l4_string_lists(
            existing.get("source_runtime_snapshot_ids"),
            incoming.get("source_runtime_snapshot_ids"),
        ),
        "source_keys": merge_l4_string_lists(
            existing.get("source_keys"),
            incoming.get("source_keys"),
        ),
        "source_fact_ids": merge_l4_string_lists(
            existing.get("source_fact_ids"),
            incoming.get("source_fact_ids"),
            [incoming_id] if incoming_id and incoming_id != existing_id else [],
        ),
    }


def build_l4_merge_detail_fact(fact: dict) -> dict:
    return {
        "id": normalize_l4_text(fact.get("id")),
        "key": normalize_l4_text(fact.get("key")),
        "value": normalize_l4_text(fact.get("value")),
        "category": normalize_l4_text(fact.get("category")),
        "mention_count": max(1, int(fact.get("mention_count") or 1)),
    }


def build_l4_merge_operation_detail(
    *,
    action: str,
    pending: dict,
    target_before: dict | None = None,
    target_after: dict | None = None,
    created_fact: dict | None = None,
) -> dict:
    detail = {
        "action": action,
        "pending_id": pending["id"],
        "pending_fact": build_l4_merge_detail_fact(pending),
    }

    if target_before is not None:
        detail["target_id"] = target_before["id"]
        detail["target_before"] = build_l4_merge_detail_fact(target_before)

    if target_after is not None:
        detail["target_id"] = target_after["id"]
        detail["target_after"] = build_l4_merge_detail_fact(target_after)

    if created_fact is not None:
        detail["created_id"] = created_fact["id"]
        detail["created_fact"] = build_l4_merge_detail_fact(created_fact)

    return detail


def apply_l4_merge_operations(
    store,
    operations: list[dict],
    *,
    now: str | None = None,
) -> tuple[dict, dict]:
    current_time = now or utc_now_iso()
    base_store = normalize_l4_store(store, now=current_time)
    valid, reason = validate_l4_merge_operations(base_store, operations)
    if not valid:
        return base_store, {
            "valid": False,
            "reason": reason,
            "changed": False,
        }

    facts = [dict(fact) for fact in base_store["facts"]]
    facts_by_id = {fact["id"]: index for index, fact in enumerate(facts)}
    pending_by_id = {fact["id"]: fact for fact in base_store["pending_facts"]}
    added_ids = []
    updated_ids = []
    reinforced_ids = []
    ignored_ids = []
    operation_details = []

    for operation in operations:
        action = operation["action"]
        pending = pending_by_id[operation["pending_id"]]

        if action == "ignore":
            ignored_ids.append(pending["id"])
            operation_details.append(
                build_l4_merge_operation_detail(
                    action=action,
                    pending=pending,
                )
            )
            continue

        if action == "reinforce":
            index = facts_by_id[operation["target_id"]]
            target = facts[index]
            target_before = dict(target)
            target.update(merge_fact_sources(target, pending))
            target["mention_count"] = max(1, int(target.get("mention_count") or 1)) + max(
                1,
                int(pending.get("mention_count") or 1),
            )
            target["updated_at"] = current_time
            reinforced_ids.append(target["id"])
            operation_details.append(
                build_l4_merge_operation_detail(
                    action=action,
                    pending=pending,
                    target_before=target_before,
                    target_after=target,
                )
            )
            continue

        if action == "update":
            index = facts_by_id[operation["target_id"]]
            target = facts[index]
            target_before = dict(target)
            candidate = normalize_l4_fact(
                {
                    **pending,
                    **{
                        key: operation[key]
                        for key in ("key", "value", "category")
                        if key in operation
                    },
                    "id": target["id"],
                    "created_at": target.get("created_at"),
                    "updated_at": current_time,
                    **merge_fact_sources(target, pending),
                    "mention_count": max(1, int(target.get("mention_count") or 1))
                    + max(1, int(pending.get("mention_count") or 1)),
                },
                now=current_time,
            )
            if candidate is None:
                return base_store, {
                    "valid": False,
                    "reason": "invalid_update_payload",
                    "changed": False,
                }
            facts[index] = candidate
            updated_ids.append(candidate["id"])
            operation_details.append(
                build_l4_merge_operation_detail(
                    action=action,
                    pending=pending,
                    target_before=target_before,
                    target_after=candidate,
                )
            )
            continue

        candidate = normalize_l4_fact(
            {
                **pending,
                **{
                    key: operation[key]
                    for key in ("key", "value", "category")
                    if key in operation
                },
                "id": "",
                "created_at": current_time,
                "updated_at": current_time,
            },
            now=current_time,
        )
        if candidate is None:
            return base_store, {
                "valid": False,
                "reason": "invalid_create_payload",
                "changed": False,
            }

        if any(fact["key"] == candidate["key"] for fact in facts):
            return base_store, {
                "valid": False,
                "reason": "create_key_already_exists",
                "changed": False,
            }

        facts_by_id[candidate["id"]] = len(facts)
        facts.append(candidate)
        added_ids.append(candidate["id"])
        operation_details.append(
            build_l4_merge_operation_detail(
                action=action,
                pending=pending,
                created_fact=candidate,
            )
        )

    next_store = {
        **base_store,
        "facts": facts,
        "pending_facts": [],
        "revision": base_store["revision"] + 1,
        "updated_at": current_time,
    }

    return next_store, {
        "valid": True,
        "added_ids": added_ids,
        "updated_ids": updated_ids,
        "reinforced_ids": reinforced_ids,
        "ignored_pending_ids": ignored_ids,
        "processed_pending_ids": sorted(pending_by_id),
        "operation_details": operation_details,
        "total_facts": len(facts),
        "pending_count": 0,
        "changed": True,
    }


def normalize_l4_jin_note_result(payload) -> dict:
    if not isinstance(payload, dict):
        return {}

    action = normalize_l4_key(payload.get("action"))
    if action == "keep":
        return {
            "action": "keep",
            "replacement_facts": [],
        }

    if action != "replace":
        return {}

    raw_replacements = payload.get("replacement_facts")
    if not isinstance(raw_replacements, list):
        return {}

    replacements = []
    for raw_fact in raw_replacements:
        if not isinstance(raw_fact, dict):
            return {}

        key = normalize_l4_key(raw_fact.get("key"))
        value = normalize_l4_text(raw_fact.get("value"))
        if not key or not value:
            return {}

        replacements.append({
            "key": key,
            "value": value,
            "category": normalize_l4_category(raw_fact.get("category")),
        })

    return {
        "action": "replace",
        "replacement_facts": replacements,
    }


def _l4_fact_semantic_signature(fact: dict) -> tuple[str, str, str]:
    return (
        normalize_l4_key(fact.get("key")),
        normalize_l4_text(fact.get("value")),
        normalize_l4_category(fact.get("category")),
    )


def apply_l4_jin_note_result(
    store,
    *,
    selected_fact_ids: list[str],
    result: dict,
    now: str | None = None,
) -> tuple[dict, dict]:
    current_time = now or utc_now_iso()
    base_store = normalize_l4_store(store, now=current_time)
    selected_ids = normalize_l4_string_list(selected_fact_ids)
    facts_by_id = {fact["id"]: fact for fact in base_store["facts"]}

    if not selected_ids or any(fact_id not in facts_by_id for fact_id in selected_ids):
        return base_store, {
            "valid": False,
            "reason": "unknown_selected_fact_id",
            "changed": False,
        }

    normalized_result = normalize_l4_jin_note_result(result)
    if not normalized_result:
        return base_store, {
            "valid": False,
            "reason": "invalid_jin_note_result",
            "changed": False,
        }

    selected_facts = [facts_by_id[fact_id] for fact_id in selected_ids]

    if normalized_result["action"] == "keep":
        return base_store, {
            "valid": True,
            "changed": False,
            "action": "keep",
            "selected_fact_ids": selected_ids,
            "replacement_fact_ids": [],
        }

    unselected_facts = [
        dict(fact)
        for fact in base_store["facts"]
        if fact["id"] not in set(selected_ids)
    ]
    unselected_keys = {fact["key"] for fact in unselected_facts}
    unselected_ids = {fact["id"] for fact in unselected_facts}
    replacement_facts = []
    replacement_keys = set()

    for raw_fact in normalized_result["replacement_facts"]:
        replacement = normalize_l4_fact(
            {
                **raw_fact,
                "id": "",
                "created_at": current_time,
                "updated_at": current_time,
            },
            pending=False,
            now=current_time,
        )
        if replacement is None:
            return base_store, {
                "valid": False,
                "reason": "invalid_replacement_fact",
                "changed": False,
            }
        if replacement["key"] in unselected_keys:
            return base_store, {
                "valid": False,
                "reason": "replacement_key_matches_unselected_fact",
                "changed": False,
            }
        if replacement["id"] in unselected_ids:
            return base_store, {
                "valid": False,
                "reason": "replacement_matches_unselected_fact",
                "changed": False,
            }
        if replacement["key"] in replacement_keys:
            return base_store, {
                "valid": False,
                "reason": "duplicate_replacement_key",
                "changed": False,
            }
        replacement_keys.add(replacement["key"])
        replacement_facts.append(replacement)

    before_signatures = sorted(
        _l4_fact_semantic_signature(fact)
        for fact in selected_facts
    )
    after_signatures = sorted(
        _l4_fact_semantic_signature(fact)
        for fact in replacement_facts
    )

    if before_signatures == after_signatures:
        return base_store, {
            "valid": True,
            "changed": False,
            "action": "keep",
            "selected_fact_ids": selected_ids,
            "replacement_fact_ids": [],
        }

    replacement_ids = [fact["id"] for fact in replacement_facts]
    next_store = {
        **base_store,
        "facts": [*unselected_facts, *replacement_facts],
        "deleted_fact_ids": merge_l4_string_lists(
            base_store.get("deleted_fact_ids"),
            selected_ids,
        ),
        "revision": base_store["revision"] + 1,
        "updated_at": current_time,
    }

    return next_store, {
        "valid": True,
        "changed": True,
        "action": "replace",
        "selected_fact_ids": selected_ids,
        "removed_fact_ids": selected_ids,
        "replacement_fact_ids": replacement_ids,
        "selected_facts": [build_l4_merge_detail_fact(fact) for fact in selected_facts],
        "replacement_facts": [
            build_l4_merge_detail_fact(fact)
            for fact in replacement_facts
        ],
        "total_facts": len(next_store["facts"]),
    }


def restore_l4_fact_to_store(
    store,
    fact,
    *,
    now: str | None = None,
) -> tuple[dict, bool]:
    current_time = now or utc_now_iso()
    next_store = normalize_l4_store(store, now=current_time)
    restored = normalize_l4_fact(
        fact,
        pending=False,
        now=current_time,
    )
    if restored is None:
        return next_store, False

    if any(
        existing.get("id") == restored["id"]
        or existing.get("key") == restored["key"]
        for existing in next_store["facts"]
    ):
        return next_store, False

    next_store["deleted_fact_ids"] = [
        deleted_id
        for deleted_id in next_store.get("deleted_fact_ids") or []
        if deleted_id != restored["id"]
    ]
    next_store["facts"].append(restored)
    next_store["revision"] += 1
    next_store["updated_at"] = current_time
    return next_store, True


def delete_l4_fact_from_store(
    store,
    fact_id: str,
    *,
    now: str | None = None,
) -> tuple[dict, bool]:
    current_time = now or utc_now_iso()
    next_store = normalize_l4_store(store, now=current_time)
    target_id = normalize_l4_text(fact_id)
    remaining = [fact for fact in next_store["facts"] if fact.get("id") != target_id]
    if len(remaining) == len(next_store["facts"]):
        return next_store, False

    next_store["facts"] = remaining
    next_store["deleted_fact_ids"] = merge_l4_string_lists(
        next_store.get("deleted_fact_ids"),
        [target_id],
    )
    next_store["revision"] += 1
    next_store["updated_at"] = current_time
    return next_store, True


def format_l4_fact_metadata_suffixes(fact: dict) -> list[str]:
    metadata = []
    for key in (
        "id",
        "category",
        "mention_count",
        "source_session_ids",
        "source_runtime_snapshot_ids",
        "source_keys",
        "source_fact_ids",
        "created_at",
        "updated_at",
    ):
        value = fact.get(key)
        if isinstance(value, list):
            value = ", ".join(str(item) for item in value if str(item).strip())
        if value in (None, "", []):
            continue
        if isinstance(value, float):
            value = f"{value:.2f}"
        metadata.append(f"[{key}: {value}]")
    return metadata


def format_l4_fact_line(fact: dict, *, include_metadata: bool = True) -> str:
    key = normalize_l4_text(fact.get("key"))
    value = normalize_l4_text(fact.get("value"))
    if not key or not value:
        return ""

    line = f"{key}: {value}"
    if include_metadata:
        suffixes = format_l4_fact_metadata_suffixes(fact)
        if suffixes:
            line = f"{line} {' '.join(suffixes)}"
    return line


def format_l4_merge_detail_fact(fact: dict) -> str:
    if not isinstance(fact, dict):
        return ""

    line = format_l4_fact_line(
        fact,
        include_metadata=False,
    )
    fact_id = normalize_l4_text(fact.get("id"))
    if line and fact_id:
        return f"{line} [ id: {fact_id} ]"
    return line or fact_id


def format_l4_merge_operation_details(change: dict) -> str:
    operation_details = (
        change.get("operation_details")
        if isinstance(change, dict)
        else None
    )
    if not isinstance(operation_details, list) or not operation_details:
        return ""

    lines = []
    for index, detail in enumerate(operation_details, start=1):
        if not isinstance(detail, dict):
            continue

        action = normalize_l4_key(detail.get("action"))
        pending_id = normalize_l4_text(detail.get("pending_id"))
        target_id = normalize_l4_text(detail.get("target_id"))
        created_id = normalize_l4_text(detail.get("created_id"))
        arrow_target = target_id or created_id
        header = f"{index}. {action.upper()}"
        if pending_id and arrow_target:
            header = f"{header} {pending_id} -> {arrow_target}"
        elif pending_id:
            header = f"{header} {pending_id}"
        lines.append(header)

        pending = detail.get("pending_fact")
        target_before = detail.get("target_before")
        target_after = detail.get("target_after")
        created_fact = detail.get("created_fact")

        if action == "update":
            lines.extend([
                f"   incoming: {format_l4_merge_detail_fact(pending)}",
                f"   before:   {format_l4_merge_detail_fact(target_before)}",
                f"   after:    {format_l4_merge_detail_fact(target_after)}",
            ])
            continue

        if action == "reinforce":
            lines.extend([
                f"   confirmation: {format_l4_merge_detail_fact(pending)}",
                f"   existing:     {format_l4_merge_detail_fact(target_before)}",
            ])
            continue

        if action == "create":
            lines.extend([
                f"   incoming: {format_l4_merge_detail_fact(pending)}",
                f"   created:  {format_l4_merge_detail_fact(created_fact)}",
            ])
            continue

        if action == "ignore":
            lines.append(
                f"   ignored: {format_l4_merge_detail_fact(pending)}"
            )

    return "\n".join(
        line
        for line in lines
        if line.strip()
    )


def format_long_term_memory_context(facts: list[dict]) -> str:
    lines = []

    for fact in facts:
        line = format_l4_fact_line(
            fact,
            include_metadata=False,
        )
        fact_id = normalize_l4_text(
            fact.get(
                "id",
                "",
            )
        )

        if not line or not fact_id:
            continue

        lines.append(
            f"{line} [ id: {fact_id} ]"
        )

    if not lines:
        return ""

    body = "\n".join(
        escape(line)
        for line in lines
    )
    return f"<LONG_TERM_MEMORY>\n{body}\n</LONG_TERM_MEMORY>"


def clone_l4_store(store) -> dict:
    return deepcopy(normalize_l4_store(store))
