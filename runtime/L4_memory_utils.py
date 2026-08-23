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
from utils.tokens import (
    estimate_runtime_tokens,
    estimate_tokens,
)
from utils.context.messages import (
    format_context_message_age_suffix,
)


L4_STORE_VERSION = 2
L4_FACT_ID_PREFIX = "F"
L4_PENDING_FACT_ID_PREFIX = "PF"
L4_FACT_ID_RE = re.compile(r"^F([1-9]\d*)$", re.IGNORECASE)
L4_PENDING_FACT_ID_RE = re.compile(r"^PF([1-9]\d*)$", re.IGNORECASE)
L4_LEGACY_FACT_ID_RE = re.compile(r"^l4_[a-z0-9_-]+$", re.IGNORECASE)
L4_LEGACY_PENDING_FACT_ID_RE = re.compile(r"^l4p_[a-z0-9_-]+$", re.IGNORECASE)
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
    "merge",
    "ignore",
}
L4_JIN_NOTE_ACTIONS = {
    "update",
    "merge",
    "create",
}


def infer_l4_jin_note_action(
    *,
    selected_fact_ids,
    message: str,
) -> str:
    selected_ids = [
        fact_id
        for fact_id in normalize_l4_string_list(selected_fact_ids)
        if normalize_l4_id(fact_id, pending=False)
    ]
    normalized_message = normalize_l4_text(message)
    explicit_match = re.match(
        r"^(update|merge|create)\b",
        normalized_message,
        flags=re.IGNORECASE,
    )

    if explicit_match:
        action = explicit_match.group(1).casefold()
    elif not selected_ids:
        action = "create"
    elif len(selected_ids) == 1:
        action = "update"
    else:
        action = "merge"

    if action == "create" and selected_ids:
        return ""
    if action == "update" and len(selected_ids) != 1:
        return ""
    if action == "merge" and len(selected_ids) < 2:
        return ""

    return action


def l4_jin_note_requests_new_fact(message: str) -> bool:
    normalized_message = normalize_l4_text(message)
    if not normalized_message:
        return False

    return bool(
        re.search(
            r"\bcreate\b[^.\n;:]{0,80}\bfact\b",
            normalized_message,
            flags=re.IGNORECASE,
        )
    )


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
    requested_action: str = "",
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
                "requested_action": normalize_l4_key(requested_action),
                "message": normalize_l4_text(message),
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )


def collect_l4_exact_key_conflicts(
    *,
    existing_facts: list[dict],
    pending_facts: list[dict],
) -> list[dict]:
    owners_by_key: dict[str, list[str]] = {}
    for fact in existing_facts:
        if not isinstance(fact, dict):
            continue
        key = normalize_l4_key(fact.get("key"))
        fact_id = normalize_l4_id(fact.get("id"), pending=False)
        if not key or not fact_id:
            continue
        owners_by_key.setdefault(key, []).append(fact_id)

    conflicts = []
    for pending in pending_facts:
        if not isinstance(pending, dict):
            continue
        pending_id = normalize_l4_id(pending.get("id"), pending=True)
        key = normalize_l4_key(pending.get("key"))
        owner_ids = owners_by_key.get(key, [])
        if pending_id and key and owner_ids:
            conflicts.append({
                "pending_id": pending_id,
                "key": key,
                "existing_fact_ids": owner_ids,
            })
    return conflicts


def build_l4_merge_user_prompt(
    *,
    existing_facts: list[dict],
    pending_facts: list[dict],
    protected_fact_ids=(),
    repair_context: dict | None = None,
) -> str:
    model_existing_facts = [
        build_l4_merge_model_fact(fact)
        for fact in existing_facts
        if isinstance(fact, dict)
    ]
    model_pending_facts = [
        build_l4_merge_model_fact(fact)
        for fact in pending_facts
        if isinstance(fact, dict)
    ]

    return (
        "Consolidate this pending batch into the current long-term memory. "
        "Return exactly one operation for every pending_id in this request.\n\n"
        + json.dumps(
            {
                "existing_facts": model_existing_facts,
                "pending_facts": model_pending_facts,
                "exact_key_conflicts": collect_l4_exact_key_conflicts(
                    existing_facts=existing_facts,
                    pending_facts=pending_facts,
                ),
                "protected_fact_ids": [
                    fact_id
                    for fact_id in normalize_l4_string_list(protected_fact_ids)
                    if normalize_l4_id(fact_id, pending=False)
                ],
                **(
                    {"repair": repair_context}
                    if isinstance(repair_context, dict) and repair_context
                    else {}
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def split_l4_existing_fact_batches(
    existing_facts: list[dict],
) -> list[list[dict]]:
    """Split committed L4 into at most two stable FIFO-preserving halves."""

    facts = [
        fact
        for fact in existing_facts
        if isinstance(fact, dict)
    ]
    if len(facts) <= 1:
        return [facts]

    midpoint = (len(facts) + 1) // 2
    return [
        facts[:midpoint],
        facts[midpoint:],
    ]


def build_l4_merge_shard_scan_system_prompt() -> str:
    return (
        "You scan one shard of JIN's committed L4 memory for semantic overlap "
        "with pending L4 candidates. This is only the first half of a two-pass "
        "comparison. Do not create or mutate memory. Return exactly one scan "
        "result for every pending_id.\n\n"
        "For each pending candidate choose one decision:\n"
        "- no_match: this shard contains no relevant overlap;\n"
        "- ignore: the candidate should be ignored, either because it is not "
        "durable/useful enough or because this shard already represents it;\n"
        "- update: exactly one committed fact in this shard should be updated;\n"
        "- merge: two or more committed facts in this shard overlap and should "
        "participate in a final merge.\n\n"
        "When ignore is caused by an existing fact, include that fact in "
        "fact_ids. For update include exactly one fact_id. For merge include at "
        "least two fact_ids. Use only F<number> IDs visible in this request. "
        "Protected fact IDs are read-only: if a pending candidate overlaps one, "
        "return ignore and include that protected ID in fact_ids.\n\n"
        "Return JSON only:\n"
        '{"scan":[{"pending_id":"PF1","decision":"no_match",'
        '"fact_ids":[],"comment":""}]}'
    )


def build_l4_merge_shard_scan_user_prompt(
    *,
    existing_facts: list[dict],
    pending_facts: list[dict],
    protected_fact_ids=(),
    repair_context: dict | None = None,
) -> str:
    return (
        "Scan this committed-memory shard against every pending candidate.\n\n"
        + json.dumps(
            {
                "existing_facts": [
                    build_l4_merge_model_fact(fact)
                    for fact in existing_facts
                    if isinstance(fact, dict)
                ],
                "pending_facts": [
                    build_l4_merge_model_fact(fact)
                    for fact in pending_facts
                    if isinstance(fact, dict)
                ],
                "protected_fact_ids": [
                    fact_id
                    for fact_id in normalize_l4_string_list(protected_fact_ids)
                    if normalize_l4_id(fact_id, pending=False)
                ],
                **(
                    {"repair": repair_context}
                    if isinstance(repair_context, dict) and repair_context
                    else {}
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def normalize_l4_merge_shard_scan(
    payload,
    *,
    pending_ids: list[str],
    visible_fact_ids: list[str],
) -> list[dict]:
    inspection = inspect_l4_merge_shard_scan(
        payload,
        pending_ids=pending_ids,
        visible_fact_ids=visible_fact_ids,
    )
    if inspection["invalid_pending_ids"] or inspection["global_errors"]:
        return []
    return inspection["results"]


def inspect_l4_merge_shard_scan(
    payload,
    *,
    pending_ids: list[str],
    visible_fact_ids: list[str],
) -> dict:
    """Validate shard-scan rows independently instead of poisoning the batch.

    The strict public normalizer above still preserves the old all-or-nothing
    contract for callers that need it. The merge runtime uses this inspection
    result so a malformed row can be repaired/retried without discarding valid
    rows for unrelated pending facts.
    """

    ordered_pending = []
    expected_pending = set()
    for raw_pending_id in pending_ids:
        pending_id = normalize_l4_id(raw_pending_id, pending=True)
        if not pending_id or pending_id in expected_pending:
            continue
        expected_pending.add(pending_id)
        ordered_pending.append(pending_id)

    visible_facts = {
        normalize_l4_id(fact_id, pending=False)
        for fact_id in visible_fact_ids
        if normalize_l4_id(fact_id, pending=False)
    }
    allowed_decisions = {
        "no_match",
        "ignore",
        "update",
        "merge",
    }
    results_by_pending = {}
    pending_errors: dict[str, list[str]] = {}
    global_errors = []
    seen_rows = set()

    def add_pending_error(pending_id: str, reason: str) -> None:
        errors = pending_errors.setdefault(pending_id, [])
        if reason not in errors:
            errors.append(reason)
        # Once a row is ambiguous/invalid, never keep an earlier result for
        # the same pending_id. A repair request will resolve that one item.
        results_by_pending.pop(pending_id, None)

    if not isinstance(payload, dict) or not isinstance(payload.get("scan"), list):
        return {
            "results": [],
            "valid_pending_ids": [],
            "invalid_pending_ids": ordered_pending,
            "pending_errors": {
                pending_id: ["invalid_scan_payload"]
                for pending_id in ordered_pending
            },
            "global_errors": ["invalid_scan_payload"],
        }

    for index, raw_item in enumerate(payload.get("scan") or []):
        if not isinstance(raw_item, dict):
            global_errors.append(f"item_{index}:invalid_item")
            continue

        pending_id = normalize_l4_id(raw_item.get("pending_id"), pending=True)
        if not pending_id:
            global_errors.append(f"item_{index}:invalid_pending_id")
            continue
        if pending_id not in expected_pending:
            global_errors.append(
                f"item_{index}:unexpected_pending_id:{pending_id}"
            )
            continue
        if pending_id in seen_rows:
            add_pending_error(pending_id, "duplicate_pending_id")
            continue
        seen_rows.add(pending_id)

        decision = normalize_l4_key(raw_item.get("decision"))
        if decision not in allowed_decisions:
            add_pending_error(pending_id, "invalid_decision")
            continue

        raw_fact_ids = raw_item.get("fact_ids")
        raw_fact_values = (
            raw_fact_ids
            if isinstance(raw_fact_ids, list)
            else [raw_fact_ids]
        )
        fact_ids = []
        invalid_fact_id = False
        for raw_fact_id in raw_fact_values:
            raw_text = normalize_l4_text(raw_fact_id)
            if not raw_text:
                continue
            fact_id = normalize_l4_id(raw_text, pending=False)
            if not fact_id:
                invalid_fact_id = True
                continue
            if fact_id not in fact_ids:
                fact_ids.append(fact_id)

        if invalid_fact_id:
            add_pending_error(pending_id, "invalid_fact_id")
            continue
        if any(fact_id not in visible_facts for fact_id in fact_ids):
            add_pending_error(pending_id, "fact_id_outside_shard")
            continue
        if decision == "no_match" and fact_ids:
            add_pending_error(pending_id, "no_match_with_fact_ids")
            continue
        if decision == "update" and len(fact_ids) != 1:
            add_pending_error(pending_id, "update_requires_one_fact_id")
            continue
        if decision == "merge" and len(fact_ids) < 2:
            add_pending_error(pending_id, "merge_requires_two_fact_ids")
            continue

        item = {
            "pending_id": pending_id,
            "decision": decision,
            "fact_ids": fact_ids,
        }
        comment = normalize_l4_text(raw_item.get("comment"))
        if comment:
            item["comment"] = comment
        results_by_pending[pending_id] = item

    for pending_id in ordered_pending:
        if pending_id not in seen_rows:
            add_pending_error(pending_id, "missing_scan_result")

    results = [
        results_by_pending[pending_id]
        for pending_id in ordered_pending
        if pending_id in results_by_pending
    ]
    invalid_pending_ids = [
        pending_id
        for pending_id in ordered_pending
        if pending_id in pending_errors
    ]
    return {
        "results": results,
        "valid_pending_ids": [item["pending_id"] for item in results],
        "invalid_pending_ids": invalid_pending_ids,
        "pending_errors": pending_errors,
        "global_errors": global_errors,
    }


def build_l4_merge_shard_finalize_user_prompt(
    *,
    existing_facts: list[dict],
    pending_facts: list[dict],
    previous_shard_scan: list[dict],
    previous_shard_facts: list[dict],
    all_existing_facts: list[dict],
    protected_fact_ids=(),
    repair_context: dict | None = None,
) -> str:
    return (
        "Finalize this pending batch after an earlier L4 shard scan. "
        "existing_facts is the remaining committed-memory shard. "
        "previous_shard_scan summarizes the first shard, and "
        "previous_shard_facts contains every committed fact explicitly "
        "referenced by that scan. Consider both shards together and return "
        "exactly one normal L4 merge operation for every pending_id.\n\n"
        + json.dumps(
            {
                "existing_facts": [
                    build_l4_merge_model_fact(fact)
                    for fact in existing_facts
                    if isinstance(fact, dict)
                ],
                "pending_facts": [
                    build_l4_merge_model_fact(fact)
                    for fact in pending_facts
                    if isinstance(fact, dict)
                ],
                "previous_shard_scan": previous_shard_scan,
                "previous_shard_facts": [
                    build_l4_merge_model_fact(fact)
                    for fact in previous_shard_facts
                    if isinstance(fact, dict)
                ],
                "exact_key_conflicts": collect_l4_exact_key_conflicts(
                    existing_facts=all_existing_facts,
                    pending_facts=pending_facts,
                ),
                "protected_fact_ids": [
                    fact_id
                    for fact_id in normalize_l4_string_list(protected_fact_ids)
                    if normalize_l4_id(fact_id, pending=False)
                ],
                **(
                    {"repair": repair_context}
                    if isinstance(repair_context, dict) and repair_context
                    else {}
                ),
            },
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def collect_l4_shard_scan_referenced_facts(
    existing_facts: list[dict],
    scan_results: list[dict],
) -> list[dict]:
    referenced_ids = {
        fact_id
        for item in scan_results
        if isinstance(item, dict)
        for fact_id in normalize_l4_string_list(item.get("fact_ids"))
        if normalize_l4_id(fact_id, pending=False)
    }
    return [
        fact
        for fact in existing_facts
        if isinstance(fact, dict)
        and normalize_l4_id(fact.get("id"), pending=False) in referenced_ids
    ]


def build_l4_merge_model_fact(fact: dict) -> dict:
    return {
        "id": normalize_l4_text(fact.get("id")),
        "key": normalize_l4_text(fact.get("key")),
        "value": normalize_l4_text(fact.get("value")),
        "category": normalize_l4_text(fact.get("category")),
    }


def estimate_l4_merge_response_tokens(
    pending_facts: list[dict],
) -> int:
    """Estimate a conservative full operation payload for a merge batch."""

    operations = []
    for fact in pending_facts:
        if not isinstance(fact, dict):
            continue

        model_fact = build_l4_merge_model_fact(fact)
        operations.append({
            "action": "update",
            "pending_id": model_fact["id"],
            "target_id": "F1",
            "key": model_fact["key"],
            "value": model_fact["value"],
            "category": model_fact["category"],
        })

    return estimate_tokens(
        json.dumps(
            {"operations": operations},
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )


def build_l4_merge_batch_plan(
    *,
    existing_facts: list[dict],
    pending_facts: list[dict],
    system_prompt: str,
    runtime_context_window: int,
    requested_max_tokens: int | None,
    runtime_output_reserve: int = 256,
    protected_fact_ids=(),
    max_batch_count: int | None = None,
) -> dict:
    """Select the largest FIFO pending slice that fits the live LM Studio budget.

    The configured SERVICE_CONTEXT_WINDOW is intentionally not a request limit;
    it remains a UI/reference denominator. L4 batching uses the context_length
    of the model instance actually loaded in LM Studio.
    """

    try:
        context_window = max(1, int(runtime_context_window))
    except (TypeError, ValueError):
        context_window = 1

    try:
        max_requested_output = max(1, int(requested_max_tokens))
    except (TypeError, ValueError):
        max_requested_output = context_window

    try:
        provider_reserve = max(0, int(runtime_output_reserve))
    except (TypeError, ValueError):
        provider_reserve = 0

    # L4 merge models may spend a meaningful part of the shared generation
    # budget on hidden reasoning before they emit the final JSON. Reserve a
    # proportional reasoning cushion instead of filling the context almost to
    # the edge with prompt + estimated JSON. The adaptive retry cap below can
    # still shrink the FIFO batch further if the live model needs more room.
    default_response_headroom = max(
        128,
        min(
            3072,
            context_window // 5,
        ),
    )
    response_headroom = default_response_headroom
    response_headroom_squeezed = False

    try:
        batch_limit = max(0, int(max_batch_count or 0))
    except (TypeError, ValueError):
        batch_limit = 0

    queue = [
        fact
        for fact in pending_facts
        if isinstance(fact, dict)
    ]
    minimum_required_tokens = 0
    if queue:
        minimum_prompt = build_l4_merge_user_prompt(
            existing_facts=existing_facts,
            pending_facts=[queue[0]],
            protected_fact_ids=protected_fact_ids,
        )
        minimum_prompt_tokens = estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=minimum_prompt,
        )
        minimum_response_tokens = estimate_l4_merge_response_tokens(
            [queue[0]]
        )
        minimum_required_tokens = (
            minimum_prompt_tokens
            + minimum_response_tokens
            + provider_reserve
            + 128
        )
    selected = []
    selected_prompt = ""
    selected_prompt_tokens = 0
    selected_response_tokens = 0
    estimated_total_tokens = 0

    for fact in queue:
        if batch_limit and len(selected) >= batch_limit:
            break

        candidate_batch = [*selected, fact]
        candidate_prompt = build_l4_merge_user_prompt(
            existing_facts=existing_facts,
            pending_facts=candidate_batch,
            protected_fact_ids=protected_fact_ids,
        )
        prompt_tokens = estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=candidate_prompt,
        )
        response_tokens = estimate_l4_merge_response_tokens(
            candidate_batch
        )
        total_tokens = (
            prompt_tokens
            + response_tokens
            + provider_reserve
            + response_headroom
        )

        if total_tokens > context_window:
            break

        selected = candidate_batch
        selected_prompt = candidate_prompt
        selected_prompt_tokens = prompt_tokens
        selected_response_tokens = response_tokens
        estimated_total_tokens = total_tokens

    if selected:
        configured_output_room = max(
            1,
            context_window
            - selected_prompt_tokens
            - provider_reserve,
        )
    else:
        # Calculate diagnostics for the first FIFO item so a failed budget is
        # explainable instead of silently retrying the same oversized payload.
        first_prompt = ""
        first_prompt_tokens = 0
        first_response_tokens = 0
        first_total_tokens = 0
        if queue:
            first_prompt = build_l4_merge_user_prompt(
                existing_facts=existing_facts,
                pending_facts=[queue[0]],
                protected_fact_ids=protected_fact_ids,
            )
            first_prompt_tokens = estimate_runtime_tokens(
                system_prompt=system_prompt,
                user_input=first_prompt,
            )
            first_response_tokens = estimate_l4_merge_response_tokens(
                [queue[0]]
            )
            first_total_tokens = (
                first_prompt_tokens
                + first_response_tokens
                + provider_reserve
                + response_headroom
            )

        # Do not let the conservative hidden-reasoning cushion deadlock the
        # FIFO forever. If the first pending fact itself fits, squeeze only the
        # *safety headroom* for this one-item fallback. The provider reserve and
        # estimated final JSON response remain fully protected.
        available_headroom = (
            context_window
            - first_prompt_tokens
            - first_response_tokens
            - provider_reserve
        )

        if queue and available_headroom >= 128:
            selected = [queue[0]]
            selected_prompt = first_prompt
            selected_prompt_tokens = first_prompt_tokens
            selected_response_tokens = first_response_tokens
            response_headroom = min(
                default_response_headroom,
                available_headroom,
            )
            response_headroom_squeezed = (
                response_headroom
                < default_response_headroom
            )
            estimated_total_tokens = (
                first_prompt_tokens
                + first_response_tokens
                + provider_reserve
                + response_headroom
            )
            configured_output_room = max(
                1,
                context_window
                - first_prompt_tokens
                - provider_reserve,
            )
        else:
            selected_prompt = first_prompt
            selected_prompt_tokens = first_prompt_tokens
            selected_response_tokens = first_response_tokens
            estimated_total_tokens = first_total_tokens
            configured_output_room = 0

    pending_ids = [
        normalize_l4_text(fact.get("id"))
        for fact in selected
        if normalize_l4_text(fact.get("id"))
    ]

    return {
        "pending_facts": selected,
        "pending_ids": pending_ids,
        "batch_count": len(selected),
        "total_pending_count": len(queue),
        "remaining_pending_count": max(0, len(queue) - len(selected)),
        "user_prompt": selected_prompt,
        "runtime_context_window_tokens": context_window,
        # Kept as a diagnostics compatibility alias for older log viewers.
        "configured_context_window_tokens": context_window,
        "estimated_prompt_tokens": selected_prompt_tokens,
        "estimated_response_tokens": selected_response_tokens,
        "runtime_output_reserve_tokens": provider_reserve,
        "response_headroom_tokens": response_headroom,
        "default_response_headroom_tokens": default_response_headroom,
        "response_headroom_squeezed": response_headroom_squeezed,
        "estimated_total_tokens": estimated_total_tokens,
        "configured_output_room_tokens": configured_output_room,
        "requested_max_output_tokens": max_requested_output,
        "adaptive_batch_limit": batch_limit,
        "minimum_required_tokens": minimum_required_tokens,
        "fits": bool(selected),
    }


def build_l4_double_batch_plan(
    *,
    existing_facts: list[dict],
    pending_facts: list[dict],
    system_prompt: str,
    runtime_context_window: int,
    requested_max_tokens: int | None,
    runtime_output_reserve: int = 256,
    protected_fact_ids=(),
    max_batch_count: int | None = None,
) -> dict:
    """Plan both pending batching and committed-L4 full/half batching.

    Full L4 is preferred. If even one pending fact cannot fit against the full
    committed list, the runtime falls back to exactly two committed-memory
    halves. Both halves must be able to compare at least one pending candidate
    before any model request is allowed.
    """

    facts = [
        fact
        for fact in existing_facts
        if isinstance(fact, dict)
    ]
    queue = [
        fact
        for fact in pending_facts
        if isinstance(fact, dict)
    ]
    full_plan = build_l4_merge_batch_plan(
        existing_facts=facts,
        pending_facts=queue,
        system_prompt=system_prompt,
        runtime_context_window=runtime_context_window,
        requested_max_tokens=requested_max_tokens,
        runtime_output_reserve=runtime_output_reserve,
        protected_fact_ids=protected_fact_ids,
        max_batch_count=max_batch_count,
    )
    if full_plan["fits"]:
        return {
            "fits": True,
            "mode": "full",
            "batch_count": full_plan["batch_count"],
            "pending_facts": full_plan["pending_facts"],
            "pending_ids": full_plan["pending_ids"],
            "total_pending_count": full_plan["total_pending_count"],
            "remaining_pending_count": full_plan["remaining_pending_count"],
            "plans": [full_plan],
            "existing_fact_batches": [facts],
            "minimum_required_tokens": full_plan["minimum_required_tokens"],
            "runtime_context_window_tokens": full_plan[
                "runtime_context_window_tokens"
            ],
        }

    halves = split_l4_existing_fact_batches(facts)
    if len(halves) < 2:
        return {
            "fits": False,
            "mode": "paused",
            "batch_count": 0,
            "pending_facts": [],
            "pending_ids": [],
            "total_pending_count": len(queue),
            "remaining_pending_count": len(queue),
            "plans": [full_plan],
            "existing_fact_batches": halves,
            "minimum_required_tokens": full_plan["minimum_required_tokens"],
            "runtime_context_window_tokens": full_plan[
                "runtime_context_window_tokens"
            ],
        }

    half_plans = [
        build_l4_merge_batch_plan(
            existing_facts=half,
            pending_facts=queue,
            system_prompt=system_prompt,
            runtime_context_window=runtime_context_window,
            requested_max_tokens=requested_max_tokens,
            runtime_output_reserve=runtime_output_reserve,
            protected_fact_ids=protected_fact_ids,
            max_batch_count=max_batch_count,
        )
        for half in halves
    ]
    minimum_required_tokens = max(
        [
            int(plan.get("minimum_required_tokens") or 0)
            for plan in half_plans
        ]
        or [0]
    )
    if any(not plan["fits"] for plan in half_plans):
        return {
            "fits": False,
            "mode": "paused",
            "batch_count": 0,
            "pending_facts": [],
            "pending_ids": [],
            "total_pending_count": len(queue),
            "remaining_pending_count": len(queue),
            "plans": half_plans,
            "existing_fact_batches": halves,
            "minimum_required_tokens": minimum_required_tokens,
            "runtime_context_window_tokens": max(
                int(plan.get("runtime_context_window_tokens") or 0)
                for plan in half_plans
            ),
        }

    batch_count = min(plan["batch_count"] for plan in half_plans)
    exact_plans = [
        build_l4_merge_batch_plan(
            existing_facts=half,
            pending_facts=queue,
            system_prompt=system_prompt,
            runtime_context_window=runtime_context_window,
            requested_max_tokens=requested_max_tokens,
            runtime_output_reserve=runtime_output_reserve,
            protected_fact_ids=protected_fact_ids,
            max_batch_count=batch_count,
        )
        for half in halves
    ]
    selected = queue[:batch_count]
    return {
        "fits": True,
        "mode": "halves",
        "batch_count": batch_count,
        "pending_facts": selected,
        "pending_ids": [
            normalize_l4_text(fact.get("id"))
            for fact in selected
            if normalize_l4_text(fact.get("id"))
        ],
        "total_pending_count": len(queue),
        "remaining_pending_count": max(0, len(queue) - batch_count),
        "plans": exact_plans,
        "existing_fact_batches": halves,
        "minimum_required_tokens": minimum_required_tokens,
        "runtime_context_window_tokens": max(
            int(plan.get("runtime_context_window_tokens") or 0)
            for plan in exact_plans
        ),
    }


def utc_now_iso() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def l4_timestamp_sort_value(value) -> float:
    text = normalize_l4_text(value)
    if not text:
        return 0.0
    try:
        parsed = datetime.fromisoformat(
            text.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    except (TypeError, ValueError):
        return 0.0


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


def normalize_l4_id(value, *, pending: bool = False) -> str:
    text = normalize_l4_text(value).upper()
    matcher = L4_PENDING_FACT_ID_RE if pending else L4_FACT_ID_RE
    match = matcher.fullmatch(text)
    if not match:
        return ""
    return f"{L4_PENDING_FACT_ID_PREFIX if pending else L4_FACT_ID_PREFIX}{int(match.group(1))}"


def is_l4_fact_id(value) -> bool:
    return bool(normalize_l4_id(value, pending=False))


def is_l4_pending_fact_id(value) -> bool:
    return bool(normalize_l4_id(value, pending=True))


def _l4_id_number(value, *, pending: bool = False) -> int:
    normalized = normalize_l4_id(value, pending=pending)
    if not normalized:
        return 0
    prefix = L4_PENDING_FACT_ID_PREFIX if pending else L4_FACT_ID_PREFIX
    try:
        return int(normalized[len(prefix):])
    except (TypeError, ValueError):
        return 0


def normalize_l4_deleted_fact_ids(value) -> list[str]:
    result = []
    seen = set()
    for candidate in normalize_l4_string_list(value):
        fact_id = normalize_l4_id(candidate, pending=False)
        if not fact_id or fact_id in seen:
            continue
        seen.add(fact_id)
        result.append(fact_id)
    return result


def build_l4_content_hash(content: str) -> str:
    return hashlib.sha256(
        normalize_l4_text(content).encode("utf-8")
    ).hexdigest()[:16]


def build_l4_fact_id(*, sequence: int, pending: bool = False, **_ignored) -> str:
    try:
        number = int(sequence)
    except (TypeError, ValueError) as error:
        raise ValueError("L4 fact sequence must be a positive integer") from error
    if number <= 0:
        raise ValueError("L4 fact sequence must be a positive integer")
    prefix = L4_PENDING_FACT_ID_PREFIX if pending else L4_FACT_ID_PREFIX
    return f"{prefix}{number}"


def _next_l4_sequence(store: dict, *, pending: bool = False) -> int:
    counter_key = "next_pending_fact_id" if pending else "next_fact_id"
    try:
        configured = max(1, int(store.get(counter_key) or 1))
    except (TypeError, ValueError):
        configured = 1

    ids = []
    if pending:
        ids.extend(fact.get("id") for fact in store.get("pending_facts", []) if isinstance(fact, dict))
        for fact in store.get("facts", []):
            if isinstance(fact, dict):
                ids.extend(fact.get("source_fact_ids") or [])
    else:
        ids.extend(fact.get("id") for fact in store.get("facts", []) if isinstance(fact, dict))
        ids.extend(store.get("deleted_fact_ids") or [])
        for fact in store.get("facts", []):
            if isinstance(fact, dict):
                ids.extend(fact.get("source_fact_ids") or [])

    highest = max(
        (_l4_id_number(value, pending=pending) for value in ids),
        default=0,
    )
    return max(configured, highest + 1)


def allocate_l4_fact_id(store: dict, *, pending: bool = False) -> str:
    sequence = _next_l4_sequence(store, pending=pending)
    counter_key = "next_pending_fact_id" if pending else "next_fact_id"
    store[counter_key] = sequence + 1
    return build_l4_fact_id(sequence=sequence, pending=pending)


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
    fact_id = normalize_l4_id(value.get("id"), pending=pending)

    try:
        mention_count = max(1, int(value.get("mention_count") or 1))
    except (TypeError, ValueError):
        mention_count = 1

    try:
        significance = float(
            value.get("significance")
            if value.get("significance") is not None
            else value.get("metabolic_significance", 0.0)
        )
    except (TypeError, ValueError):
        significance = 0.0
    if significance != significance:
        significance = 0.0
    significance = round(max(0.0, min(1.0, significance)), 4)

    return {
        "id": fact_id,
        "key": key,
        "value": fact_value,
        "category": normalize_l4_category(value.get("category")),
        "mention_count": mention_count,
        "significance": significance,
        "significance_updated_at": (
            normalize_l4_text(value.get("significance_updated_at"))
            or normalize_l4_text(value.get("updated_at"))
            or normalize_l4_text(value.get("created_at"))
            or current_time
        ),
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
    existing_significance = float(existing.get("significance", 0.0) or 0.0)
    incoming_significance = float(incoming.get("significance", 0.0) or 0.0)
    if incoming_significance > existing_significance:
        result["significance"] = round(
            max(0.0, min(1.0, incoming_significance)),
            4,
        )
        result["significance_updated_at"] = (
            normalize_l4_text(incoming.get("significance_updated_at"))
            or now
        )
    else:
        result["significance"] = round(
            max(0.0, min(1.0, existing_significance)),
            4,
        )
        result["significance_updated_at"] = (
            normalize_l4_text(existing.get("significance_updated_at"))
            or now
        )
    result["updated_at"] = now
    return result


def deduplicate_l4_facts(facts: list[dict], *, pending: bool, now: str) -> list[dict]:
    result = []
    by_identity = {}

    for raw_fact in facts:
        fact = normalize_l4_fact(raw_fact, pending=pending, now=now)
        if fact is None:
            continue

        identity = fact.get("id") or (
            "semantic",
            fact.get("key"),
            fact.get("value"),
            fact.get("category"),
        )
        existing_index = by_identity.get(identity)
        if existing_index is None:
            by_identity[identity] = len(result)
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
    existing_significance_at = normalize_l4_text(
        existing_fact.get("significance_updated_at")
    )
    incoming_significance_at = normalize_l4_text(
        incoming_fact.get("significance_updated_at")
    )
    existing_significance_time = l4_timestamp_sort_value(
        existing_significance_at
    )
    incoming_significance_time = l4_timestamp_sort_value(
        incoming_significance_at
    )
    if incoming_significance_time > existing_significance_time:
        significance_source = incoming_fact
    elif existing_significance_time > incoming_significance_time:
        significance_source = existing_fact
    else:
        significance_source = max(
            (existing_fact, incoming_fact),
            key=lambda fact: float(
                fact.get("significance", 0.0)
                or 0.0
            ),
        )

    merged = {
        **base,
        "id": existing_id or incoming_id,
        "significance": float(
            significance_source.get("significance", 0.0)
            or 0.0
        ),
        "significance_updated_at": (
            normalize_l4_text(
                significance_source.get("significance_updated_at")
            )
            or now
        ),
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

    # Committed F<number> IDs are durable identities. Never collapse two
    # committed records merely because their keys happen to match; an explicit
    # L4 merge is the only operation allowed to retire a committed ID. Pending
    # PF records may still coalesce by key while they are provisional.
    if pending:
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
                facts.append(dict(fact))
                continue

            facts[existing_index] = merge_l4_snapshot_fact(
                facts[existing_index],
                fact,
                pending=pending,
                now=now,
            )
    else:
        facts = [dict(fact) for fact in normalized_existing]

    by_id = {
        fact["id"]: index
        for index, fact in enumerate(facts)
    }
    by_key = (
        {
            fact["key"]: index
            for index, fact in enumerate(facts)
        }
        if pending
        else {}
    )

    incoming = deduplicate_l4_facts(
        incoming_facts if isinstance(incoming_facts, list) else [],
        pending=pending,
        now=now,
    )

    for fact in incoming:
        existing_index = by_id.get(
            fact["id"]
        )
        if existing_index is None and pending:
            existing_index = by_key.get(
                fact["key"]
            )

        if existing_index is None:
            by_id[fact["id"]] = len(facts)
            if pending:
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
        if pending:
            by_key.pop(
                previous_key,
                None,
            )
        by_id[merged["id"]] = existing_index
        if pending:
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
            pending_id = normalize_l4_id(source_fact_id, pending=True)
            if pending_id:
                processed_ids.add(pending_id)

    return processed_ids


def prune_l4_processed_pending_facts(
    *,
    facts,
    pending_facts,
    ignored_pending_fact_ids=None,
) -> list[dict]:
    processed_ids = collect_l4_processed_pending_fact_ids(facts)
    processed_ids.update(
        pending_id
        for pending_id in (
            normalize_l4_id(raw_id, pending=True)
            for raw_id in normalize_l4_string_list(
                ignored_pending_fact_ids
            )
        )
        if pending_id
    )
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
    ignored_pending_fact_ids = merge_l4_string_lists(
        [
            pending_id
            for pending_id in (
                normalize_l4_id(raw_id, pending=True)
                for raw_id in normalize_l4_string_list(
                    primary.get("ignored_pending_fact_ids")
                )
            )
            if pending_id
        ],
        [
            pending_id
            for pending_id in (
                normalize_l4_id(raw_id, pending=True)
                for raw_id in normalize_l4_string_list(
                    incoming.get("ignored_pending_fact_ids")
                )
            )
            if pending_id
        ],
    )

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
        ignored_pending_fact_ids=ignored_pending_fact_ids,
    )
    next_fact_id = max(
        int(primary.get("next_fact_id") or 1),
        int(incoming.get("next_fact_id") or 1),
    )
    next_pending_fact_id = max(
        int(primary.get("next_pending_fact_id") or 1),
        int(incoming.get("next_pending_fact_id") or 1),
    )
    changed = bool(
        facts != primary.get("facts")
        or pending_facts != primary.get("pending_facts")
        or deleted_fact_ids != primary.get("deleted_fact_ids")
        or ignored_pending_fact_ids
        != primary.get("ignored_pending_fact_ids")
        or next_fact_id != int(primary.get("next_fact_id") or 1)
        or next_pending_fact_id != int(primary.get("next_pending_fact_id") or 1)
    )

    merged = {
        **primary,
        "facts": facts,
        "pending_facts": pending_facts,
        "deleted_fact_ids": deleted_fact_ids,
        "ignored_pending_fact_ids": ignored_pending_fact_ids,
        "next_fact_id": next_fact_id,
        "next_pending_fact_id": next_pending_fact_id,
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


def migrate_l4_store_ids(
    value,
    *,
    now: str | None = None,
) -> tuple[dict, dict[str, str]]:
    """Upgrade legacy hash-like L4 ids to compact sequential F/PF ids.

    Existing F/PF ids are preserved. Legacy ids are remapped deterministically
    in store order so browser and backend snapshots converge on the same ids.
    """

    current_time = now or utc_now_iso()
    if not isinstance(value, dict):
        return empty_l4_store(now=current_time), {}

    migrated = deepcopy(value)
    facts = migrated.get("facts") if isinstance(migrated.get("facts"), list) else []
    pending = (
        migrated.get("pending_facts")
        if isinstance(migrated.get("pending_facts"), list)
        else []
    )
    deleted = (
        migrated.get("deleted_fact_ids")
        if isinstance(migrated.get("deleted_fact_ids"), list)
        else []
    )

    used_fact_numbers = {
        _l4_id_number(fact.get("id"), pending=False)
        for fact in facts
        if isinstance(fact, dict) and is_l4_fact_id(fact.get("id"))
    }
    used_pending_numbers = {
        _l4_id_number(fact.get("id"), pending=True)
        for fact in pending
        if isinstance(fact, dict) and is_l4_pending_fact_id(fact.get("id"))
    }
    used_fact_numbers.discard(0)
    used_pending_numbers.discard(0)

    try:
        next_fact = max(1, int(migrated.get("next_fact_id") or 1))
    except (TypeError, ValueError):
        next_fact = 1
    try:
        next_pending = max(1, int(migrated.get("next_pending_fact_id") or 1))
    except (TypeError, ValueError):
        next_pending = 1

    next_fact = max(next_fact, max(used_fact_numbers, default=0) + 1)
    next_pending = max(next_pending, max(used_pending_numbers, default=0) + 1)
    id_map: dict[str, str] = {}

    def allocate(raw_id, *, is_pending: bool) -> str:
        nonlocal next_fact, next_pending
        text = normalize_l4_text(raw_id)
        normalized = normalize_l4_id(text, pending=is_pending)
        if normalized:
            return normalized
        if text and text in id_map:
            return id_map[text]

        legacy_match = (
            L4_LEGACY_PENDING_FACT_ID_RE.fullmatch(text)
            if is_pending
            else L4_LEGACY_FACT_ID_RE.fullmatch(text)
        )
        if text and not legacy_match:
            return ""

        if is_pending:
            while next_pending in used_pending_numbers:
                next_pending += 1
            assigned = build_l4_fact_id(sequence=next_pending, pending=True)
            used_pending_numbers.add(next_pending)
            next_pending += 1
        else:
            while next_fact in used_fact_numbers:
                next_fact += 1
            assigned = build_l4_fact_id(sequence=next_fact, pending=False)
            used_fact_numbers.add(next_fact)
            next_fact += 1

        if text:
            id_map[text] = assigned
        return assigned

    # Assign actual records first. This makes the migration deterministic and
    # ensures references to those records reuse the same new id.
    for fact in facts:
        if not isinstance(fact, dict):
            continue
        old_id = normalize_l4_text(fact.get("id"))
        new_id = allocate(old_id, is_pending=False)
        if not new_id:
            new_id = allocate("", is_pending=False)
        if old_id and old_id != new_id:
            id_map[old_id] = new_id
        fact["id"] = new_id

    for fact in pending:
        if not isinstance(fact, dict):
            continue
        old_id = normalize_l4_text(fact.get("id"))
        new_id = allocate(old_id, is_pending=True)
        if not new_id:
            new_id = allocate("", is_pending=True)
        if old_id and old_id != new_id:
            id_map[old_id] = new_id
        fact["id"] = new_id

    migrated_deleted = []
    for raw_id in deleted:
        old_id = normalize_l4_text(raw_id)
        new_id = normalize_l4_id(old_id, pending=False) or id_map.get(old_id, "")
        if not new_id and L4_LEGACY_FACT_ID_RE.fullmatch(old_id):
            new_id = allocate(old_id, is_pending=False)
        if new_id and new_id not in migrated_deleted:
            migrated_deleted.append(new_id)

    for fact in [*facts, *pending]:
        if not isinstance(fact, dict):
            continue
        remapped_sources = []
        for raw_id in normalize_l4_string_list(fact.get("source_fact_ids")):
            new_id = normalize_l4_id(raw_id, pending=True)
            if not new_id:
                new_id = normalize_l4_id(raw_id, pending=False)
            if not new_id:
                new_id = id_map.get(raw_id, "")
            if not new_id and L4_LEGACY_PENDING_FACT_ID_RE.fullmatch(raw_id):
                new_id = allocate(raw_id, is_pending=True)
            if not new_id and L4_LEGACY_FACT_ID_RE.fullmatch(raw_id):
                new_id = allocate(raw_id, is_pending=False)
            if new_id and new_id not in remapped_sources:
                remapped_sources.append(new_id)
        fact["source_fact_ids"] = remapped_sources

    try:
        previous_version = int(value.get("version") or 0)
    except (TypeError, ValueError):
        previous_version = 0

    should_bump_revision = bool(
        id_map
        or migrated_deleted != deleted
        or (
            previous_version not in {0, L4_STORE_VERSION}
            and bool(facts or pending or deleted)
        )
    )

    migrated.update({
        "version": L4_STORE_VERSION,
        "facts": facts,
        "pending_facts": pending,
        "deleted_fact_ids": migrated_deleted,
        "next_fact_id": next_fact,
        "next_pending_fact_id": next_pending,
    })
    if should_bump_revision:
        try:
            migrated["revision"] = max(0, int(value.get("revision") or 0)) + 1
        except (TypeError, ValueError):
            migrated["revision"] = 1
        migrated["updated_at"] = current_time

    return migrated, id_map


def empty_l4_store(*, now: str | None = None) -> dict:
    return {
        "version": L4_STORE_VERSION,
        "revision": 0,
        "updated_at": now or "",
        "facts": [],
        "pending_facts": [],
        "deleted_fact_ids": [],
        "ignored_pending_fact_ids": [],
        "next_fact_id": 1,
        "next_pending_fact_id": 1,
    }


def normalize_l4_store(value, *, now: str | None = None) -> dict:
    current_time = now or utc_now_iso()
    if not isinstance(value, dict):
        return empty_l4_store(now=current_time)

    value, _id_map = migrate_l4_store_ids(value, now=current_time)

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
    ignored_pending_fact_ids = [
        pending_id
        for pending_id in (
            normalize_l4_id(raw_id, pending=True)
            for raw_id in normalize_l4_string_list(
                value.get("ignored_pending_fact_ids")
            )
        )
        if pending_id
    ]

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
        ignored_pending_fact_ids=ignored_pending_fact_ids,
    )

    next_fact_id = max(
        _next_l4_sequence({
            **value,
            "facts": facts,
            "pending_facts": pending_facts,
            "deleted_fact_ids": deleted_fact_ids,
        }, pending=False),
        1,
    )
    next_pending_fact_id = max(
        _next_l4_sequence({
            **value,
            "facts": facts,
            "pending_facts": pending_facts,
            "deleted_fact_ids": deleted_fact_ids,
        }, pending=True),
        1,
    )

    return {
        "version": L4_STORE_VERSION,
        "revision": revision,
        "updated_at": normalize_l4_text(value.get("updated_at")) or current_time,
        "facts": facts,
        "pending_facts": pending_facts,
        "deleted_fact_ids": deleted_fact_ids,
        "ignored_pending_fact_ids": ignored_pending_fact_ids,
        "next_fact_id": next_fact_id,
        "next_pending_fact_id": next_pending_fact_id,
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

    try:
        significance = float(field.get("significance", 0.0) or 0.0)
    except (TypeError, ValueError):
        significance = 0.0
    if significance != significance:
        significance = 0.0
    significance = round(max(0.0, min(1.0, significance)), 4)

    return {
        **field,
        "content": content,
        "runtime_snapshot_id": normalize_l4_text(field.get("runtime_snapshot_id")),
        "session_id": normalize_l4_text(field.get("session_id") or session_id),
        "l4_status": status,
        "significance": significance,
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
                "significance": field.get("significance", 0.0),
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
        matched_significance = max(
            (
                float(field.get("significance", 0.0) or 0.0)
                for field in matched_fields
            ),
            default=0.0,
        )
        candidate = normalize_l4_fact(
            {
                **raw_candidate,
                "significance": matched_significance,
                "significance_updated_at": current_time,
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
    by_semantic = {
        (fact.get("key"), fact.get("value"), fact.get("category")): index
        for index, fact in enumerate(pending)
    }
    added_ids = []
    reinforced_ids = []

    for raw_candidate in candidates:
        candidate = normalize_l4_fact(raw_candidate, pending=True, now=current_time)
        if candidate is None:
            continue

        identity = (candidate.get("key"), candidate.get("value"), candidate.get("category"))
        index = by_id.get(candidate.get("id")) if candidate.get("id") else None
        if index is None:
            index = by_semantic.get(identity)

        if index is None:
            candidate["id"] = allocate_l4_fact_id(next_store, pending=True)
            by_id[candidate["id"]] = len(pending)
            by_semantic[identity] = len(pending)
            pending.append(candidate)
            added_ids.append(candidate["id"])
        else:
            candidate["id"] = pending[index]["id"]
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
        pending_id = normalize_l4_id(raw_operation.get("pending_id"), pending=True)
        if action not in L4_ALLOWED_MERGE_ACTIONS or not pending_id:
            continue

        operation = {
            "action": action,
            "pending_id": pending_id,
        }
        target_id = normalize_l4_id(raw_operation.get("target_id"), pending=False)
        if target_id:
            operation["target_id"] = target_id

        if "fact_ids" in raw_operation:
            operation["fact_ids"] = [
                fact_id
                for fact_id in (
                    normalize_l4_id(raw_id, pending=False)
                    for raw_id in normalize_l4_string_list(raw_operation.get("fact_ids"))
                )
                if fact_id
            ]

        for key in ("key", "value", "category"):
            if key in raw_operation:
                operation[key] = raw_operation[key]

        if "comment" in raw_operation:
            comment = normalize_l4_text(raw_operation.get("comment"))
            if comment:
                operation["comment"] = comment

        operations.append(operation)

    return operations


def validate_l4_merge_operations(
    store,
    operations: list[dict],
    *,
    pending_ids: list[str] | None = None,
) -> tuple[bool, str]:
    normalized_store = normalize_l4_store(store)
    pending = normalized_store["pending_facts"]
    all_pending_ids = {fact["id"] for fact in pending}
    facts = normalized_store["facts"]
    fact_ids = {fact["id"] for fact in facts}

    if pending_ids is None:
        expected_pending_ids = all_pending_ids
    else:
        expected_pending_ids = {
            normalize_l4_id(pending_id, pending=True)
            for pending_id in pending_ids
            if normalize_l4_id(pending_id, pending=True)
        }
        if not expected_pending_ids.issubset(all_pending_ids):
            return False, "unknown_pending_batch_id"

    if len(operations) != len(expected_pending_ids):
        return False, "operation_count_mismatch"

    seen_pending = set()
    reserved_committed_ids = set()

    def validate_canonical_fact(operation: dict, *, prefix: str) -> tuple[bool, str, str]:
        final_key = normalize_l4_key(operation.get("key"))
        final_value = normalize_l4_text(operation.get("value"))
        final_category = normalize_l4_key(operation.get("category"))
        if not final_key or not final_value or not final_category:
            return False, f"{prefix}_requires_canonical_fact", ""
        if final_category not in L4_ALLOWED_CATEGORIES:
            return False, f"{prefix}_invalid_category", ""
        return True, "", final_key

    for operation in operations:
        pending_id = operation.get("pending_id")
        if pending_id not in expected_pending_ids:
            return False, "unknown_pending_id"
        if pending_id in seen_pending:
            return False, "duplicate_pending_operation"
        seen_pending.add(pending_id)

        action = operation.get("action")

        if action == "ignore":
            continue

        if action == "create":
            valid, reason, final_key = validate_canonical_fact(
                operation,
                prefix="create",
            )
            if not valid:
                return False, reason
            if any(fact.get("key") == final_key for fact in facts):
                return False, "create_key_already_exists"
            continue

        if action == "update":
            target_id = operation.get("target_id")
            if target_id not in fact_ids:
                return False, "unknown_target_id"
            if target_id in reserved_committed_ids:
                return False, "committed_fact_used_by_multiple_operations"

            valid, reason, final_key = validate_canonical_fact(
                operation,
                prefix="update",
            )
            if not valid:
                return False, reason
            if any(
                fact.get("id") != target_id
                and fact.get("key") == final_key
                for fact in facts
            ):
                return False, "update_key_matches_other_fact"

            reserved_committed_ids.add(target_id)
            continue

        if action == "merge":
            merge_fact_ids = [
                normalize_l4_id(fact_id, pending=False)
                for fact_id in operation.get("fact_ids", [])
                if normalize_l4_id(fact_id, pending=False)
            ]
            if len(merge_fact_ids) < 2:
                return False, "merge_requires_fact_ids"
            if len(set(merge_fact_ids)) != len(merge_fact_ids):
                return False, "duplicate_merge_fact_id"
            if any(fact_id not in fact_ids for fact_id in merge_fact_ids):
                return False, "unknown_merge_fact_id"
            if any(fact_id in reserved_committed_ids for fact_id in merge_fact_ids):
                return False, "committed_fact_used_by_multiple_operations"

            valid, reason, final_key = validate_canonical_fact(
                operation,
                prefix="merge",
            )
            if not valid:
                return False, reason

            merge_id_set = set(merge_fact_ids)
            if any(
                fact.get("id") not in merge_id_set
                and fact.get("key") == final_key
                for fact in facts
            ):
                return False, "merge_key_matches_unselected_fact"

            reserved_committed_ids.update(merge_fact_ids)
            continue

        return False, "unknown_merge_action"

    if seen_pending != expected_pending_ids:
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


def merge_l4_significance(
    *facts: dict,
    now: str,
) -> tuple[float, str]:
    best_value = 0.0
    best_updated_at = now

    for fact in facts:
        if not isinstance(fact, dict):
            continue
        try:
            value = float(fact.get("significance", 0.0) or 0.0)
        except (TypeError, ValueError):
            value = 0.0
        if value != value:
            value = 0.0
        value = max(0.0, min(1.0, value))
        if value >= best_value:
            best_value = value
            best_updated_at = (
                normalize_l4_text(fact.get("significance_updated_at"))
                or now
            )

    return round(best_value, 4), best_updated_at


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
    merged_facts: list[dict] | None = None,
    comment: str = "",
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

    if merged_facts:
        detail["merged_fact_ids"] = [
            fact["id"]
            for fact in merged_facts
            if isinstance(fact, dict) and fact.get("id")
        ]
        detail["merged_facts"] = [
            build_l4_merge_detail_fact(fact)
            for fact in merged_facts
            if isinstance(fact, dict)
        ]

    normalized_comment = normalize_l4_text(comment)
    if normalized_comment:
        detail["comment"] = normalized_comment

    return detail


def apply_l4_merge_operations(
    store,
    operations: list[dict],
    *,
    pending_ids: list[str] | None = None,
    now: str | None = None,
) -> tuple[dict, dict]:
    current_time = now or utc_now_iso()
    base_store = normalize_l4_store(store, now=current_time)
    valid, reason = validate_l4_merge_operations(
        base_store,
        operations,
        pending_ids=pending_ids,
    )
    if not valid:
        return base_store, {
            "valid": False,
            "reason": reason,
            "changed": False,
        }

    facts = [dict(fact) for fact in base_store["facts"]]
    all_pending_by_id = {
        fact["id"]: fact
        for fact in base_store["pending_facts"]
    }
    processed_pending_ids = (
        {
            normalize_l4_id(pending_id, pending=True)
            for pending_id in pending_ids
            if normalize_l4_id(pending_id, pending=True)
        }
        if pending_ids is not None
        else set(all_pending_by_id)
    )
    pending_by_id = {
        pending_id: all_pending_by_id[pending_id]
        for pending_id in processed_pending_ids
    }

    allocation_store = {
        **base_store,
        "facts": facts,
    }
    added_ids = []
    updated_ids = []
    merged_ids = []
    ignored_ids = []
    removed_fact_ids = []
    replacement_fact_ids = []
    replacement_fact_id_map = {}
    operation_details = []

    def rebuild_facts_by_id() -> dict[str, int]:
        return {fact["id"]: index for index, fact in enumerate(facts)}

    for operation in operations:
        action = operation["action"]
        pending = pending_by_id[operation["pending_id"]]
        comment = normalize_l4_text(operation.get("comment"))
        facts_by_id = rebuild_facts_by_id()

        if action == "ignore":
            ignored_ids.append(pending["id"])
            operation_details.append(
                build_l4_merge_operation_detail(
                    action=action,
                    pending=pending,
                    comment=comment,
                )
            )
            continue

        if action == "update":
            index = facts_by_id[operation["target_id"]]
            target = facts[index]
            target_before = dict(target)
            significance, significance_updated_at = merge_l4_significance(
                target,
                pending,
                now=current_time,
            )
            candidate = normalize_l4_fact(
                {
                    **pending,
                    "key": operation["key"],
                    "value": operation["value"],
                    "category": operation["category"],
                    "id": target["id"],
                    "created_at": target.get("created_at"),
                    "updated_at": current_time,
                    "significance": significance,
                    "significance_updated_at": significance_updated_at,
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
            if any(
                fact["id"] != target["id"] and fact["key"] == candidate["key"]
                for fact in facts
            ):
                return base_store, {
                    "valid": False,
                    "reason": "update_key_matches_other_fact",
                    "changed": False,
                }
            facts[index] = candidate
            allocation_store["facts"] = facts
            updated_ids.append(candidate["id"])
            operation_details.append(
                build_l4_merge_operation_detail(
                    action=action,
                    pending=pending,
                    target_before=target_before,
                    target_after=candidate,
                    comment=comment,
                )
            )
            continue

        if action == "merge":
            merge_fact_ids = operation["fact_ids"]
            merged_facts = [
                facts[facts_by_id[fact_id]]
                for fact_id in merge_fact_ids
            ]
            new_fact_id = allocate_l4_fact_id(
                allocation_store,
                pending=False,
            )
            significance, significance_updated_at = merge_l4_significance(
                *merged_facts,
                pending,
                now=current_time,
            )
            candidate = normalize_l4_fact(
                {
                    "id": new_fact_id,
                    "key": operation["key"],
                    "value": operation["value"],
                    "category": operation["category"],
                    "created_at": current_time,
                    "updated_at": current_time,
                    "significance": significance,
                    "significance_updated_at": significance_updated_at,
                    "mention_count": sum(
                        max(1, int(fact.get("mention_count") or 1))
                        for fact in [*merged_facts, pending]
                    ),
                    "source_session_ids": merge_l4_string_lists(
                        *[fact.get("source_session_ids") for fact in merged_facts],
                        pending.get("source_session_ids"),
                    ),
                    "source_runtime_snapshot_ids": merge_l4_string_lists(
                        *[fact.get("source_runtime_snapshot_ids") for fact in merged_facts],
                        pending.get("source_runtime_snapshot_ids"),
                    ),
                    "source_keys": merge_l4_string_lists(
                        *[fact.get("source_keys") for fact in merged_facts],
                        pending.get("source_keys"),
                    ),
                    "source_fact_ids": merge_l4_string_lists(
                        *[fact.get("source_fact_ids") for fact in merged_facts],
                        merge_fact_ids,
                        pending.get("source_fact_ids"),
                        [pending.get("id")],
                    ),
                },
                now=current_time,
            )
            if candidate is None:
                return base_store, {
                    "valid": False,
                    "reason": "invalid_merge_payload",
                    "changed": False,
                }

            merge_id_set = set(merge_fact_ids)
            if any(
                fact["id"] not in merge_id_set and fact["key"] == candidate["key"]
                for fact in facts
            ):
                return base_store, {
                    "valid": False,
                    "reason": "merge_key_matches_unselected_fact",
                    "changed": False,
                }
            facts[:] = [
                fact
                for fact in facts
                if fact["id"] not in merge_id_set
            ]
            facts.append(candidate)
            allocation_store["facts"] = facts
            removed_fact_ids.extend(merge_fact_ids)
            replacement_fact_ids.append(candidate["id"])
            for removed_id in merge_fact_ids:
                replacement_fact_id_map[removed_id] = [candidate["id"]]
            merged_ids.append(candidate["id"])
            operation_details.append(
                build_l4_merge_operation_detail(
                    action=action,
                    pending=pending,
                    created_fact=candidate,
                    merged_facts=merged_facts,
                    comment=comment,
                )
            )
            continue

        # create
        new_fact_id = allocate_l4_fact_id(
            allocation_store,
            pending=False,
        )
        candidate = normalize_l4_fact(
            {
                **pending,
                "key": operation["key"],
                "value": operation["value"],
                "category": operation["category"],
                "id": new_fact_id,
                "created_at": current_time,
                "updated_at": current_time,
                "source_fact_ids": merge_l4_string_lists(
                    pending.get("source_fact_ids"),
                    [pending.get("id")],
                ),
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

        facts.append(candidate)
        allocation_store["facts"] = facts
        added_ids.append(candidate["id"])
        operation_details.append(
            build_l4_merge_operation_detail(
                action=action,
                pending=pending,
                created_fact=candidate,
                comment=comment,
            )
        )

    next_store = {
        **base_store,
        "facts": facts,
        "pending_facts": [
            fact
            for fact in base_store["pending_facts"]
            if fact["id"] not in processed_pending_ids
        ],
        "deleted_fact_ids": merge_l4_string_lists(
            base_store.get("deleted_fact_ids"),
            removed_fact_ids,
        ),
        "ignored_pending_fact_ids": merge_l4_string_lists(
            base_store.get("ignored_pending_fact_ids"),
            ignored_ids,
        ),
        "next_fact_id": allocation_store.get(
            "next_fact_id",
            base_store.get("next_fact_id", 1),
        ),
        "revision": base_store["revision"] + 1,
        "updated_at": current_time,
    }

    return next_store, {
        "valid": True,
        "added_ids": added_ids,
        "updated_ids": updated_ids,
        "merged_ids": merged_ids,
        "removed_fact_ids": removed_fact_ids,
        "replacement_fact_ids": replacement_fact_ids,
        "replacement_fact_id_map": replacement_fact_id_map,
        "ignored_pending_ids": ignored_ids,
        "processed_pending_ids": sorted(processed_pending_ids),
        "operation_details": operation_details,
        "total_facts": len(facts),
        "pending_count": len(next_store["pending_facts"]),
        "changed": True,
    }


def normalize_l4_jin_note_fact_specs(raw_facts) -> list[dict] | None:
    if not isinstance(raw_facts, list):
        return None

    facts = []
    for raw_fact in raw_facts:
        if not isinstance(raw_fact, dict):
            return None

        key = normalize_l4_key(raw_fact.get("key"))
        value = normalize_l4_text(raw_fact.get("value"))
        if not key or not value:
            return None

        facts.append({
            "key": key,
            "value": value,
            "category": normalize_l4_category(raw_fact.get("category")),
        })

    return facts


def normalize_l4_jin_note_result(payload) -> dict:
    if not isinstance(payload, dict):
        return {}

    action = normalize_l4_key(payload.get("action"))
    if action == "keep":
        return {
            "action": "keep",
            "replacement_facts": [],
            "new_facts": [],
        }

    replacement_actions = {"replace", "update", "merge"}
    if action not in {*replacement_actions, "create"}:
        return {}

    raw_replacements = payload.get("replacement_facts")
    if raw_replacements is None:
        raw_replacements = []
    replacements = normalize_l4_jin_note_fact_specs(raw_replacements)
    if replacements is None:
        return {}

    raw_new_facts = payload.get("new_facts")
    if raw_new_facts is None:
        raw_new_facts = []
    new_facts = normalize_l4_jin_note_fact_specs(raw_new_facts)
    if new_facts is None:
        return {}

    if action in replacement_actions and not replacements:
        return {}

    if action == "create" and (replacements or not new_facts):
        return {}

    return {
        "action": action,
        "replacement_facts": replacements,
        "new_facts": new_facts,
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
    expected_action: str = "",
    allow_new_facts: bool = False,
    now: str | None = None,
) -> tuple[dict, dict]:
    current_time = now or utc_now_iso()
    base_store = normalize_l4_store(store, now=current_time)
    selected_ids = normalize_l4_string_list(selected_fact_ids)
    facts_by_id = {fact["id"]: fact for fact in base_store["facts"]}

    if any(fact_id not in facts_by_id for fact_id in selected_ids):
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

    requested_action = normalize_l4_key(expected_action)
    if requested_action and requested_action not in L4_JIN_NOTE_ACTIONS:
        return base_store, {
            "valid": False,
            "reason": "invalid_expected_jin_note_action",
            "changed": False,
        }

    normalized_action = normalized_result["action"]
    if normalized_action == "replace":
        normalized_action = "merge" if len(selected_ids) > 1 else "update"

    if normalized_action == "keep":
        if requested_action:
            return base_store, {
                "valid": False,
                "reason": "jin_note_action_mismatch",
                "changed": False,
            }
        return base_store, {
            "valid": True,
            "changed": False,
            "action": "keep",
            "selected_fact_ids": selected_ids,
            "replacement_fact_ids": [],
        }

    action = normalized_action
    if requested_action and action != requested_action:
        return base_store, {
            "valid": False,
            "reason": "jin_note_action_mismatch",
            "changed": False,
        }

    replacement_specs = normalized_result["replacement_facts"]
    new_fact_specs = normalized_result["new_facts"]
    if (
        requested_action in {"update", "merge"}
        and new_fact_specs
        and not allow_new_facts
    ):
        return base_store, {
            "valid": False,
            "reason": "jin_note_unrequested_new_fact",
            "changed": False,
        }
    has_replacements = bool(replacement_specs)
    if has_replacements and not selected_ids:
        return base_store, {
            "valid": False,
            "reason": "missing_selected_fact_id",
            "changed": False,
        }
    if (
        action == "update"
        and has_replacements
        and len(replacement_specs) != len(selected_ids)
    ):
        return base_store, {
            "valid": False,
            "reason": "update_replacement_count_mismatch",
            "changed": False,
        }
    if action == "merge" and len(replacement_specs) != 1:
        return base_store, {
            "valid": False,
            "reason": "merge_requires_single_replacement",
            "changed": False,
        }

    selected_facts = [facts_by_id[fact_id] for fact_id in selected_ids]
    if action == "update":
        replacement_anchor_ids = selected_ids[:len(replacement_specs)]
        merged_selected_ids = []
    elif action == "merge":
        replacement_anchor_ids = []
        merged_selected_ids = list(selected_ids)
    else:
        replacement_anchor_ids = []
        merged_selected_ids = []

    replacement_anchor_id_set = set(replacement_anchor_ids)
    merged_selected_id_set = set(merged_selected_ids)
    output_facts = [
        dict(fact)
        for fact in base_store["facts"]
        if fact["id"] not in merged_selected_id_set
    ]
    output_indexes_by_id = {
        fact["id"]: index
        for index, fact in enumerate(output_facts)
    }
    allocated_keys = {
        fact["key"]
        for fact in output_facts
        if fact["id"] not in replacement_anchor_id_set
    }
    allocated_ids = {
        fact["id"]
        for fact in output_facts
        if fact["id"] not in replacement_anchor_id_set
    }
    replacement_facts = []
    new_facts = []

    allocation_store = {**base_store, "facts": [*output_facts]}

    def normalize_note_fact(
        raw_fact: dict,
        *,
        fact_id: str,
        created_at: str,
        source_facts: list[dict] | None = None,
        source_fact_ids=(),
        mention_count: int = 1,
        duplicate_key_reason: str,
    ) -> tuple[dict | None, str]:
        source_significance, source_significance_updated_at = (
            merge_l4_significance(
                *(source_facts or []),
                now=current_time,
            )
        )
        fact = normalize_l4_fact(
            {
                **raw_fact,
                "id": fact_id,
                "created_at": created_at,
                "updated_at": current_time,
                "mention_count": mention_count,
                "significance": (
                    raw_fact.get("significance")
                    if raw_fact.get("significance") is not None
                    else source_significance
                ),
                "significance_updated_at": (
                    normalize_l4_text(
                        raw_fact.get("significance_updated_at")
                    )
                    or source_significance_updated_at
                ),
                "source_session_ids": merge_l4_string_lists(
                    *[
                        source_fact.get("source_session_ids")
                        for source_fact in source_facts or []
                    ],
                ),
                "source_runtime_snapshot_ids": merge_l4_string_lists(
                    *[
                        source_fact.get("source_runtime_snapshot_ids")
                        for source_fact in source_facts or []
                    ],
                ),
                "source_keys": merge_l4_string_lists(
                    *[
                        source_fact.get("source_keys")
                        for source_fact in source_facts or []
                    ],
                ),
                "source_fact_ids": merge_l4_string_lists(
                    *[
                        source_fact.get("source_fact_ids")
                        for source_fact in source_facts or []
                    ],
                    source_fact_ids,
                ),
            },
            pending=False,
            now=current_time,
        )
        if fact is None:
            return None, "invalid_note_fact"
        if fact["key"] in allocated_keys:
            return None, duplicate_key_reason
        if fact["id"] in allocated_ids:
            return None, "note_fact_id_collision"
        allocated_keys.add(fact["key"])
        allocated_ids.add(fact["id"])
        allocation_store["facts"].append(fact)
        return fact, ""

    def allocate_note_fact(
        raw_fact: dict,
        *,
        duplicate_key_reason: str,
    ) -> tuple[dict | None, str]:
        return normalize_note_fact(
            raw_fact,
            fact_id=allocate_l4_fact_id(allocation_store, pending=False),
            created_at=current_time,
            duplicate_key_reason=duplicate_key_reason,
        )

    for index, raw_fact in enumerate(replacement_specs):
        anchor_id = (
            replacement_anchor_ids[index]
            if index < len(replacement_anchor_ids)
            else ""
        )
        if action == "merge":
            replacement, reason = normalize_note_fact(
                raw_fact,
                fact_id=allocate_l4_fact_id(allocation_store, pending=False),
                created_at=current_time,
                source_facts=selected_facts,
                source_fact_ids=selected_ids,
                mention_count=sum(
                    max(1, int(fact.get("mention_count") or 1))
                    for fact in selected_facts
                ),
                duplicate_key_reason="replacement_key_matches_existing_fact",
            )
        elif anchor_id:
            anchor = facts_by_id[anchor_id]
            replacement, reason = normalize_note_fact(
                raw_fact,
                fact_id=anchor_id,
                created_at=anchor.get("created_at") or current_time,
                source_facts=[anchor],
                mention_count=max(1, int(anchor.get("mention_count") or 1)),
                duplicate_key_reason="replacement_key_matches_existing_fact",
            )
        else:
            replacement, reason = allocate_note_fact(
                raw_fact,
                duplicate_key_reason="replacement_key_matches_existing_fact",
            )
        if replacement is None:
            return base_store, {
                "valid": False,
                "reason": reason,
                "changed": False,
            }
        if anchor_id:
            output_facts[output_indexes_by_id[anchor_id]] = replacement
        elif action == "merge":
            output_facts.append(replacement)
        replacement_facts.append(replacement)

    for raw_fact in new_fact_specs:
        new_fact, reason = allocate_note_fact(
            raw_fact,
            duplicate_key_reason="new_fact_key_matches_existing_fact",
        )
        if new_fact is None:
            return base_store, {
                "valid": False,
                "reason": reason,
                "changed": False,
            }
        new_facts.append(new_fact)

    before_signatures = sorted(
        _l4_fact_semantic_signature(fact)
        for fact in selected_facts
    )
    after_signatures = sorted(
        _l4_fact_semantic_signature(fact)
        for fact in replacement_facts
    )

    if has_replacements and not new_facts and before_signatures == after_signatures:
        return base_store, {
            "valid": True,
            "changed": False,
            "action": "keep",
            "selected_fact_ids": selected_ids,
            "replacement_fact_ids": [],
        }

    replacement_ids = [fact["id"] for fact in replacement_facts]
    replacement_fact_id_map = (
        {fact_id: list(replacement_ids) for fact_id in merged_selected_ids}
        if action == "merge" and replacement_ids
        else {}
    )
    added_ids = [fact["id"] for fact in new_facts]
    next_store = {
        **base_store,
        "facts": [*output_facts, *new_facts],
        "next_fact_id": allocation_store.get(
            "next_fact_id",
            base_store.get("next_fact_id", 1),
        ),
        "deleted_fact_ids": (
            merge_l4_string_lists(
                base_store.get("deleted_fact_ids"),
                merged_selected_ids,
            )
            if merged_selected_ids
            else base_store.get("deleted_fact_ids", [])
        ),
        "revision": base_store["revision"] + 1,
        "updated_at": current_time,
    }

    return next_store, {
        "valid": True,
        "changed": True,
        "action": action,
        "selected_fact_ids": selected_ids,
        "removed_fact_ids": merged_selected_ids,
        "replacement_fact_ids": replacement_ids,
        "replacement_fact_id_map": replacement_fact_id_map,
        "added_ids": added_ids,
        "selected_facts": [build_l4_merge_detail_fact(fact) for fact in selected_facts],
        "replacement_facts": [
            build_l4_merge_detail_fact(fact)
            for fact in replacement_facts
        ],
        "new_facts": [
            build_l4_merge_detail_fact(fact)
            for fact in new_facts
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
    target_id = normalize_l4_id(fact_id, pending=False)
    if not target_id:
        return next_store, False
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


def format_l4_fact_context_age_suffix(
    fact: dict,
    *,
    now: float | None = None,
) -> str:

    if not isinstance(
        fact,
        dict,
    ):
        return ""

    return (
        format_context_message_age_suffix(
            fact.get(
                "updated_at",
            ),
            now=now,
        )
        or format_context_message_age_suffix(
            fact.get(
                "created_at",
            ),
            now=now,
        )
    )


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

        if action == "merge":
            merged_facts = detail.get("merged_facts") or []
            if isinstance(merged_facts, list):
                for merged_fact in merged_facts:
                    lines.append(
                        f"   source:   {format_l4_merge_detail_fact(merged_fact)}"
                    )
            lines.extend([
                f"   incoming: {format_l4_merge_detail_fact(pending)}",
                f"   created:  {format_l4_merge_detail_fact(created_fact)}",
            ])
            comment = normalize_l4_text(detail.get("comment"))
            if comment:
                lines.append(f"   comment:  {comment}")
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
            comment = normalize_l4_text(detail.get("comment"))
            if comment:
                lines.append(f"   comment: {comment}")

    return "\n".join(
        line
        for line in lines
        if line.strip()
    )


def format_long_term_memory_context(
    facts: list[dict],
    *,
    delayed_memory_ids_by_fact_id=None,
    now: float | None = None,
) -> str:
    lines = []
    delayed_memory_ids_by_fact_id = (
        delayed_memory_ids_by_fact_id
        if isinstance(delayed_memory_ids_by_fact_id, dict)
        else {}
    )

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

        try:
            significance = max(
                0.0,
                min(1.0, float(fact.get("significance", 0.0) or 0.0)),
            )
        except (TypeError, ValueError):
            significance = 0.0

        suffix = (
            f" [ id: {fact_id} ]"
            f" [ significance: {significance:.3f} ]"
        )
        delayed_memory_ids = delayed_memory_ids_by_fact_id.get(
            fact_id.upper(),
            [],
        )
        if isinstance(delayed_memory_ids, str):
            delayed_memory_ids = [delayed_memory_ids]

        seen_delayed_memory_ids = set()
        for delayed_memory_id in delayed_memory_ids or []:
            normalized_delayed_memory_id = str(
                delayed_memory_id or ""
            ).strip().casefold()
            if (
                not normalized_delayed_memory_id
                or normalized_delayed_memory_id in seen_delayed_memory_ids
            ):
                continue
            seen_delayed_memory_ids.add(normalized_delayed_memory_id)
            suffix += (
                " [ delayed_memory_id: "
                f"{normalized_delayed_memory_id} ]"
            )

        age_suffix = format_l4_fact_context_age_suffix(
            fact,
            now=now,
        )
        lines.append(
            f"{line}{suffix}{age_suffix}"
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
