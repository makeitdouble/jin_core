from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
import traceback

from clients.response_extractor import ResponseExtractor
from clients.service_client import ask_service_model
from config_loader import config
from runtime.client import LMStudioAPIError
from runtime.L4_memory_utils import (
    add_l4_pending_candidates,
    apply_l4_jin_note_result,
    apply_l4_merge_operations,
    build_l4_double_batch_plan,
    build_l4_merge_batch_plan,
    build_l4_merge_shard_finalize_user_prompt,
    build_l4_merge_shard_scan_system_prompt,
    build_l4_merge_shard_scan_user_prompt,
    build_l4_merge_user_prompt,
    build_l4_extraction_system_prompt,
    build_l4_extraction_user_prompt,
    build_l4_jin_note_system_prompt,
    build_l4_jin_note_user_prompt,
    build_l4_merge_system_prompt,
    clone_l4_store,
    collect_pending_facts_memory_fields,
    collect_l4_shard_scan_referenced_facts,
    estimate_l4_merge_response_tokens,
    delete_l4_fact_from_store,
    extract_l4_json_payload,
    format_l4_merge_operation_details,
    format_long_term_memory_context,
    infer_l4_jin_note_action,
    inspect_l4_merge_shard_scan,
    l4_jin_note_requests_new_fact,
    mark_facts_memory_fields_analyzed,
    merge_l4_store_snapshots,
    normalize_facts_memory_records,
    normalize_l4_candidates,
    normalize_l4_merge_operations,
    normalize_l4_key,
    normalize_l4_store,
    normalize_l4_text,
    restore_l4_fact_to_store,
    utc_now_iso,
)
from utils.tokens import estimate_runtime_tokens
from utils.actions.save_delayed_memory_utils import (
    collect_anchor_fact_report_ids,
    collect_long_term_fact_ids_from_reports,
    normalize_delayed_memory_fact_ids,
    normalize_long_term_fact_ids,
)
from utils.long_term_facts_file_store import (
    load_long_term_facts_store,
    persist_long_term_facts_store,
)
from runtime.memory_common import (
    build_memory_failure_details,
    build_runtime_summarizer_payload,
    extract_runtime_memory_text,
    is_runtime_memory_response_truncated,
    log_memory_event,
    log_runtime_summarizer_payload,
    log_runtime_summarizer_result,
    refresh_service_runtime_usage,
    safe_call,
)


L4_LOG_LEVEL = "L4"
L4_DEFAULT_IDLE_SECONDS = 15
L4_CLOSED_TABS_INTERVAL_DIVISOR = 3
L4_MERGE_RETRY_BASE_SECONDS = 60
L4_MERGE_RETRY_MAX_SECONDS = 300
L4_MERGE_VALIDATION_RETRY_SECONDS = 50
L4_MERGE_POISON_DEFER_SECONDS = 300


def _positive_int(value) -> int:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return 0
    return normalized if normalized > 0 else 0


def reset_l4_merge_recovery_state(
    context,
    *,
    keep_batch_limit: bool = False,
) -> None:
    if not keep_batch_limit:
        context.runtime_l4_merge_batch_limit = 0
        context.runtime_l4_merge_last_success_batch_limit = 0
        context.runtime_l4_merge_batch_locked = False
        context.runtime_l4_merge_existing_batch_mode = ""
        context.runtime_l4_merge_paused_signature = ""
        context.runtime_l4_merge_deferred_pending_until = {}
        context.runtime_l4_merge_single_retry_pending_ids = set()
        context.runtime_l4_merge_force_single_batch_once = False
    context.runtime_l4_merge_truncation_streak = 0
    context.runtime_l4_merge_retry_not_before = 0.0


def refresh_l4_merge_context_window_state(
    context,
    runtime_context_window: int,
) -> bool:
    """Release learned L4 batching limits when LM Studio's live n_ctx changes."""

    current = _positive_int(runtime_context_window)
    previous = _positive_int(
        getattr(
            context,
            "runtime_l4_merge_context_window_tokens",
            0,
        )
    )
    context.runtime_l4_merge_context_window_tokens = current
    if not previous or not current or previous == current:
        return False

    context.runtime_l4_merge_batch_limit = 0
    context.runtime_l4_merge_last_success_batch_limit = 0
    context.runtime_l4_merge_batch_locked = False
    context.runtime_l4_merge_truncation_streak = 0
    context.runtime_l4_merge_retry_not_before = 0.0
    context.runtime_l4_merge_existing_batch_mode = ""
    context.runtime_l4_merge_paused_signature = ""
    return True


def record_l4_merge_success(
    context,
    *,
    batch_count: int,
    remaining_pending_count: int,
) -> dict:
    """Grow a learned pending batch until a probe fails, then keep the last win."""

    normalized_batch_count = max(1, int(batch_count or 1))
    remaining = max(0, int(remaining_pending_count or 0))
    locked = bool(
        getattr(
            context,
            "runtime_l4_merge_batch_locked",
            False,
        )
    )

    context.runtime_l4_merge_last_success_batch_limit = normalized_batch_count
    context.runtime_l4_merge_truncation_streak = 0
    context.runtime_l4_merge_retry_not_before = 0.0

    if remaining <= 0:
        context.runtime_l4_merge_batch_limit = 0
        context.runtime_l4_merge_last_success_batch_limit = 0
        context.runtime_l4_merge_batch_locked = False
        return {
            "adaptive_batch_limit": 0,
            "adaptive_batch_locked": False,
        }

    if locked:
        context.runtime_l4_merge_batch_limit = normalized_batch_count
        return {
            "adaptive_batch_limit": normalized_batch_count,
            "adaptive_batch_locked": True,
        }

    next_limit = max(
        normalized_batch_count + 1,
        normalized_batch_count * 2,
    )
    context.runtime_l4_merge_batch_limit = next_limit
    return {
        "adaptive_batch_limit": next_limit,
        "adaptive_batch_locked": False,
        "last_success_batch_limit": normalized_batch_count,
    }


def get_l4_merge_retry_backoff(context) -> dict | None:
    retry_not_before = float(
        getattr(
            context,
            "runtime_l4_merge_retry_not_before",
            0.0,
        )
        or 0.0
    )
    if retry_not_before <= 0:
        return None

    remaining = retry_not_before - time.monotonic()
    if remaining <= 0:
        context.runtime_l4_merge_retry_not_before = 0.0
        return None

    return {
        "phase": "merge",
        "status": "skipped",
        "reason": "retry_backoff",
        "retry_in_seconds": max(1, int(remaining + 0.999)),
        "adaptive_batch_limit": _positive_int(
            getattr(
                context,
                "runtime_l4_merge_batch_limit",
                0,
            )
        ),
    }


def record_l4_merge_truncation(
    context,
    *,
    batch_count: int,
) -> dict:
    current_limit = _positive_int(
        getattr(
            context,
            "runtime_l4_merge_batch_limit",
            0,
        )
    )
    normalized_batch_count = max(1, int(batch_count or 1))
    last_success = _positive_int(
        getattr(
            context,
            "runtime_l4_merge_last_success_batch_limit",
            0,
        )
    )
    if last_success and normalized_batch_count > last_success:
        # An expansion probe failed. Pin the runtime to the last batch size that
        # actually completed instead of oscillating forever between N and 2N.
        next_batch_limit = last_success
        context.runtime_l4_merge_batch_locked = True
    else:
        next_batch_limit = max(
            1,
            normalized_batch_count // 2,
        )
        if current_limit:
            next_batch_limit = min(
                current_limit,
                next_batch_limit,
            )

    streak = _positive_int(
        getattr(
            context,
            "runtime_l4_merge_truncation_streak",
            0,
        )
    ) + 1
    retry_after_seconds = min(
        L4_MERGE_RETRY_MAX_SECONDS,
        L4_MERGE_RETRY_BASE_SECONDS
        * (2 ** min(streak - 1, 4)),
    )

    context.runtime_l4_merge_batch_limit = next_batch_limit
    context.runtime_l4_merge_truncation_streak = streak
    context.runtime_l4_merge_retry_not_before = (
        time.monotonic() + retry_after_seconds
    )

    return {
        "adaptive_batch_limit": next_batch_limit,
        "adaptive_batch_locked": bool(
            getattr(context, "runtime_l4_merge_batch_locked", False)
        ),
        "last_success_batch_limit": last_success,
        "truncation_streak": streak,
        "retry_after_seconds": retry_after_seconds,
    }


def clear_l4_merge_pending_recovery(
    context,
    pending_ids,
) -> None:
    deferred = dict(
        getattr(
            context,
            "runtime_l4_merge_deferred_pending_until",
            {},
        )
        or {}
    )
    for pending_id in pending_ids or []:
        deferred.pop(str(pending_id or "").strip(), None)
    context.runtime_l4_merge_deferred_pending_until = deferred

    single_retry_ids = set(
        getattr(
            context,
            "runtime_l4_merge_single_retry_pending_ids",
            set(),
        )
        or set()
    )
    for pending_id in pending_ids or []:
        single_retry_ids.discard(str(pending_id or "").strip())
    context.runtime_l4_merge_single_retry_pending_ids = single_retry_ids


def record_l4_merge_shard_scan_failures(
    context,
    *,
    pending_ids: list[str],
) -> dict:
    """Defer only bad shard-scan items and force their retries to be isolated."""

    normalized_pending_ids = []
    seen = set()
    for pending_id in pending_ids or []:
        normalized = str(pending_id or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        normalized_pending_ids.append(normalized)

    deferred = dict(
        getattr(
            context,
            "runtime_l4_merge_deferred_pending_until",
            {},
        )
        or {}
    )
    single_retry_ids = set(
        getattr(
            context,
            "runtime_l4_merge_single_retry_pending_ids",
            set(),
        )
        or set()
    )
    now = time.monotonic()
    poison_ids = []

    for pending_id in normalized_pending_ids:
        # First failed repair gets a short isolated retry. If that same pending
        # fact later fails another isolated shard repair, cool it down longer
        # instead of hammering the service model every idle tick.
        already_isolated = pending_id in single_retry_ids
        retry_after = (
            L4_MERGE_POISON_DEFER_SECONDS
            if already_isolated
            else L4_MERGE_VALIDATION_RETRY_SECONDS
        )
        if already_isolated:
            poison_ids.append(pending_id)
        deferred[pending_id] = now + retry_after
        single_retry_ids.add(pending_id)

    context.runtime_l4_merge_deferred_pending_until = deferred
    context.runtime_l4_merge_single_retry_pending_ids = single_retry_ids

    retry_after_seconds = (
        L4_MERGE_POISON_DEFER_SECONDS
        if poison_ids
        else L4_MERGE_VALIDATION_RETRY_SECONDS
    )
    return {
        "retry_behavior": (
            "The shard scan repair pass still failed only for these pending "
            "facts. Valid pending facts continue immediately; failed facts "
            "stay pending and are retried one at a time after the backoff."
        ),
        "deferred_pending_ids": normalized_pending_ids,
        "single_retry_pending_ids": normalized_pending_ids,
        "poison_deferred_pending_ids": poison_ids,
        "retry_after_seconds": retry_after_seconds,
    }


def get_l4_merge_available_pending_queue(
    context,
    pending_queue: list[dict],
) -> tuple[list[dict], dict | None]:
    deferred = dict(
        getattr(
            context,
            "runtime_l4_merge_deferred_pending_until",
            {},
        )
        or {}
    )
    if not deferred:
        return pending_queue, None

    now = time.monotonic()
    active = []
    waiting = []
    next_deferred = {}

    for fact in pending_queue:
        if not isinstance(fact, dict):
            continue
        pending_id = str(fact.get("id") or "").strip()
        not_before = float(deferred.get(pending_id, 0.0) or 0.0)
        if not_before > now:
            waiting.append((fact, not_before))
            next_deferred[pending_id] = not_before
        else:
            active.append(fact)

    context.runtime_l4_merge_deferred_pending_until = next_deferred
    if active:
        return active, None
    if not waiting:
        return pending_queue, None

    retry_in = max(
        1,
        int(min(not_before for _fact, not_before in waiting) - now + 0.999),
    )
    return [], {
        "phase": "merge",
        "status": "skipped",
        "reason": "pending_batch_deferred",
        "retry_in_seconds": retry_in,
        "deferred_pending_ids": [
            str(fact.get("id") or "").strip()
            for fact, _not_before in waiting
        ],
    }


def record_l4_merge_validation_failure(
    context,
    *,
    pending_ids: list[str],
    batch_count: int,
) -> dict:
    normalized_batch_count = max(1, int(batch_count or 1))
    if normalized_batch_count > 1:
        context.runtime_l4_merge_force_single_batch_once = True
        context.runtime_l4_merge_retry_not_before = (
            time.monotonic() + L4_MERGE_VALIDATION_RETRY_SECONDS
        )
        return {
            "retry_behavior": (
                "The invalid batch was repaired once and still failed. "
                "JIN will retry after the idle backoff with one pending fact "
                "at a time so one bad operation cannot block the queue."
            ),
            "next_batch_count": 1,
            "retry_after_seconds": L4_MERGE_VALIDATION_RETRY_SECONDS,
        }

    pending_id = str((pending_ids or [""])[0] or "").strip()
    if pending_id:
        deferred = dict(
            getattr(
                context,
                "runtime_l4_merge_deferred_pending_until",
                {},
            )
            or {}
        )
        deferred[pending_id] = time.monotonic() + L4_MERGE_POISON_DEFER_SECONDS
        context.runtime_l4_merge_deferred_pending_until = deferred

    return {
        "retry_behavior": (
            "This single pending fact failed both the normal and repair pass. "
            "It stays pending but is temporarily deferred so later facts can "
            "continue through L4 instead of deadlocking behind it."
        ),
        "deferred_pending_ids": [pending_id] if pending_id else [],
        "retry_after_seconds": L4_MERGE_POISON_DEFER_SECONDS,
    }


def build_l4_merge_validation_feedback(
    store: dict,
    operations: list[dict],
    reason: str,
) -> str:
    normalized_store = normalize_l4_store(store)
    facts = normalized_store.get("facts") or []

    if reason == "create_key_already_exists":
        collisions = []
        for operation in operations:
            if operation.get("action") != "create":
                continue
            key = normalize_l4_key(operation.get("key"))
            owners = [
                fact.get("id")
                for fact in facts
                if fact.get("key") == key
            ]
            if key and owners:
                collisions.append(
                    f"{operation.get('pending_id')}: key {key!r} is already owned by "
                    + ", ".join(str(owner) for owner in owners)
                )
        if collisions:
            return (
                "A create cannot reuse an occupied canonical key. "
                + "; ".join(collisions)
                + ". Choose update when one old fact should change, merge when "
                "two or more old facts should become one new fact, or use a "
                "different genuinely canonical key for a truly independent create."
            )

    feedback_by_reason = {
        "operation_count_mismatch": (
            "Return exactly one operation for every pending_id in this batch, "
            "with no omissions or extras."
        ),
        "update_requires_canonical_fact": (
            "Every update must include target_id plus the complete final key, "
            "value, and category."
        ),
        "update_invalid_category": (
            "Use one of the allowed L4 categories for every update."
        ),
        "update_key_matches_other_fact": (
            "An update cannot re-key its target onto a key owned by another "
            "committed fact. Merge the overlapping old facts instead if they "
            "should become one fact."
        ),
        "create_requires_canonical_fact": (
            "Every create must include the complete final key, value, and category."
        ),
        "create_invalid_category": (
            "Use one of the allowed L4 categories for every create."
        ),
        "merge_requires_fact_ids": (
            "Every merge must list at least two existing committed F<number> IDs "
            "in fact_ids."
        ),
        "unknown_merge_fact_id": (
            "A merge may list only committed F<number> IDs present in existing_facts."
        ),
        "duplicate_merge_fact_id": (
            "List each merged F<number> ID only once."
        ),
        "merge_requires_canonical_fact": (
            "Every merge must include fact_ids plus the complete final key, value, "
            "and category for the new canonical replacement."
        ),
        "merge_invalid_category": (
            "Use one of the allowed L4 categories for every merge."
        ),
        "merge_key_matches_unselected_fact": (
            "The merge replacement key is owned by a committed fact not listed in "
            "fact_ids. Include that overlapping fact in the merge only if it truly "
            "belongs in the same canonical fact; otherwise choose a non-colliding key."
        ),
        "committed_fact_used_by_multiple_operations": (
            "Within one batch, a committed fact may be mutated by only one operation. "
            "Resolve duplicate candidates with ignore rather than updating or merging "
            "the same old fact twice."
        ),
        "unknown_target_id": (
            "An update target_id must be an existing committed F<number> ID."
        ),
        "invalid_json": (
            "Return one valid JSON object only, with an operations array matching the "
            "four-action contract: create, update, merge, or ignore."
        ),
    }
    return feedback_by_reason.get(
        reason,
        "Return corrected JSON that exactly satisfies the four-action L4 merge contract.",
    )


async def resolve_l4_request_limits(
    *,
    service_client,
    system_prompt: str,
    user_prompt: str,
    requested_max_tokens: int | None,
) -> dict:
    context_window = 0
    context_window_resolver = getattr(
        service_client,
        "resolve_request_context_window",
        None,
    )

    if context_window_resolver is not None:
        try:
            context_window = _positive_int(
                await context_window_resolver()
            )
        except Exception:
            context_window = 0

    if not context_window:
        context_window = _positive_int(
            getattr(
                service_client,
                "configured_context_window",
                None,
            )
            or getattr(
                service_client,
                "context_window",
                None,
            )
            or getattr(config, "SERVICE_CONTEXT_WINDOW", 0)
        )

    requested_limit = _positive_int(
        requested_max_tokens
    )
    effective_max_tokens = requested_limit
    safe_max_tokens_resolver = getattr(
        service_client,
        "resolve_safe_max_tokens",
        None,
    )

    if safe_max_tokens_resolver is not None:
        try:
            resolved_safe_max_tokens = _positive_int(
                await safe_max_tokens_resolver(
                    system_prompt=system_prompt,
                    user_prompt=user_prompt,
                    requested_max_tokens=requested_max_tokens,
                )
            )
            if resolved_safe_max_tokens:
                effective_max_tokens = (
                    min(
                        requested_limit,
                        resolved_safe_max_tokens,
                    )
                    if requested_limit
                    else resolved_safe_max_tokens
                )
        except Exception:
            pass

    return {
        "requested_max_tokens": requested_limit,
        "effective_max_tokens": effective_max_tokens,
        "context_window_tokens": context_window,
    }


def build_l4_truncation_details(
    response: dict,
    *,
    phase: str,
    pending_count: int | None = None,
    pending_ids: list[str] | None = None,
    selected_fields_count: int | None = None,
) -> dict:
    response = response if isinstance(response, dict) else {}
    request_meta = response.get("_jin_l4_request_meta", {})
    if not isinstance(request_meta, dict):
        request_meta = {}

    usage = response.get("usage", {})
    if not isinstance(usage, dict):
        usage = {}

    prompt_tokens = _positive_int(usage.get("prompt_tokens"))
    completion_tokens = _positive_int(usage.get("completion_tokens"))
    total_tokens = _positive_int(usage.get("total_tokens"))
    if not total_tokens and (prompt_tokens or completion_tokens):
        total_tokens = prompt_tokens + completion_tokens

    requested_max_tokens = _positive_int(
        request_meta.get("requested_max_tokens")
    )
    effective_max_tokens = _positive_int(
        request_meta.get("effective_max_tokens")
    )
    context_window_tokens = _positive_int(
        request_meta.get("context_window_tokens")
    )

    content = ResponseExtractor.extract_content_text(response).strip()
    reasoning = ResponseExtractor.extract_reasoning_text(response).strip()
    finish_reason = ResponseExtractor.extract_finish_reason(response).lower()
    model = (
        ResponseExtractor.extract_model(response)
        or str(request_meta.get("model") or "").strip()
    )

    hit_effective_output_limit = bool(
        effective_max_tokens
        and completion_tokens
        and completion_tokens >= effective_max_tokens
    )
    filled_context_window = bool(
        context_window_tokens
        and total_tokens
        and total_tokens >= context_window_tokens
    )
    effective_limit_reduced = bool(
        requested_max_tokens
        and effective_max_tokens
        and effective_max_tokens < requested_max_tokens
    )

    if filled_context_window:
        limit_type = "context_window"
        limit_label = "service context window"
    elif hit_effective_output_limit:
        limit_type = "effective_output_limit"
        limit_label = "effective output limit"
    else:
        limit_type = "provider_length_limit"
        limit_label = "provider generation limit"

    if reasoning and not content:
        output_state = (
            "The model generated reasoning, but emitted no final assistant "
            "content or JSON response."
        )
    elif content:
        output_state = (
            "The model started a final assistant response, but the provider "
            "stopped it before completion."
        )
    else:
        output_state = (
            "The provider stopped generation before any assistant response "
            "was emitted."
        )

    if effective_limit_reduced and context_window_tokens:
        budget_note = (
            f"The runtime reduced max_tokens from {requested_max_tokens} to "
            f"{effective_max_tokens} so the request could fit the "
            f"{context_window_tokens}-token service context window."
        )
    elif effective_max_tokens:
        budget_note = (
            f"The effective output budget was {effective_max_tokens} tokens."
        )
    else:
        budget_note = "The provider did not report the exact output budget."

    summary = (
        f"Generation stopped at the {limit_label} "
        f"(finish_reason={finish_reason or 'length'}). "
        f"{budget_note} {output_state} JIN discarded the incomplete L4 "
        "result and kept the pending facts unchanged."
    )

    retry_note = (
        "Because the pending facts were kept, a later idle tick can start "
        "another L4 request for the same batch."
    )

    details = {
        "kind": "l4_skip",
        "phase": phase,
        "status": "skipped",
        "reason": "response_truncated",
        "summary": summary,
        "retry_behavior": retry_note,
        "finish_reason": finish_reason or "length",
        "limit_type": limit_type,
        "model": model,
        "context_window_tokens": context_window_tokens,
        "requested_max_output_tokens": requested_max_tokens,
        "effective_max_output_tokens": effective_max_tokens,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "assistant_content": "present" if content else "empty",
        "assistant_content_chars": len(content),
        "reasoning_generated": bool(reasoning),
        "reasoning_chars": len(reasoning),
    }

    if pending_count is not None:
        details["pending_count"] = int(pending_count)
    if pending_ids:
        details["pending_ids"] = list(pending_ids)
    if selected_fields_count is not None:
        details["selected_fields_count"] = int(selected_fields_count)

    return details


def l4_memory_enabled() -> bool:
    return bool(getattr(config, "L4_MEMORY_ENABLED", True))


def get_l4_idle_seconds() -> int:
    return (
        _positive_int(
            getattr(
                config,
                "L4_IDLE_SECONDS",
                L4_DEFAULT_IDLE_SECONDS,
            )
        )
        or L4_DEFAULT_IDLE_SECONDS
    )


def get_l4_scheduler_interval_seconds(
    *,
    tabs_open: bool,
) -> float:
    idle_seconds = float(get_l4_idle_seconds())
    if tabs_open:
        return idle_seconds
    return idle_seconds / float(L4_CLOSED_TABS_INTERVAL_DIVISOR)


def _l4_scheduler_wake_event(app_state):
    if app_state is None:
        return None
    return getattr(
        app_state,
        "l4_memory_scheduler_wake_event",
        None,
    )


def wake_l4_memory_server_scheduler(context) -> None:
    app_state = getattr(
        context,
        "runtime_l4_app_state",
        None,
    )
    wake_event = _l4_scheduler_wake_event(app_state)
    if wake_event is not None:
        wake_event.set()


def bind_l4_runtime_app_state(
    context,
    app_state,
) -> None:
    context.runtime_l4_app_state = app_state
    wake_l4_memory_server_scheduler(context)


def register_l4_websocket_connection(
    context,
    *,
    app_state,
    websocket,
) -> None:
    bind_l4_runtime_app_state(
        context,
        app_state,
    )
    connection_ids = getattr(
        app_state,
        "l4_open_websocket_ids",
        None,
    )
    if connection_ids is None:
        connection_ids = set()
        app_state.l4_open_websocket_ids = connection_ids
    connection_ids.add(id(websocket))
    context.runtime_l4_websocket_connected = True
    wake_l4_memory_server_scheduler(context)


def unregister_l4_websocket_connection(
    context,
    *,
    app_state,
    websocket,
) -> None:
    connection_ids = getattr(
        app_state,
        "l4_open_websocket_ids",
        None,
    )
    if isinstance(connection_ids, set):
        connection_ids.discard(id(websocket))

    if getattr(context, "websocket", None) is websocket:
        context.runtime_l4_websocket_connected = False

    wake_l4_memory_server_scheduler(context)


def note_l4_user_activity(context) -> None:
    now = time.monotonic()
    app_state = getattr(
        context,
        "runtime_l4_app_state",
        None,
    )
    if app_state is not None:
        app_state.l4_last_user_activity_at = now
    wake_l4_memory_server_scheduler(context)


def note_l4_foreground_state(
    context,
    *,
    running: bool,
) -> None:
    context.runtime_foreground_turn_running = bool(running)
    wake_l4_memory_server_scheduler(context)


def _facts_memory_identity(
    session_id: str,
    key: str,
    field: dict,
) -> tuple[str, str, str]:
    return (
        normalize_l4_text(session_id),
        normalize_l4_key(key),
        normalize_l4_text(field.get("l4_content_hash")),
    )


def _preserve_server_analyzed_facts_memory(
    incoming_records: list[dict],
    server_records: list[dict],
) -> list[dict]:
    analyzed_by_identity = {}
    for record in normalize_facts_memory_records(server_records):
        session_id = record.get("session_id", "")
        for key, field in record.get("signals", {}).items():
            if field.get("l4_status") != "analyzed":
                continue
            analyzed_by_identity[
                _facts_memory_identity(session_id, key, field)
            ] = str(field.get("l4_analyzed_at", "") or "")

    reconciled = normalize_facts_memory_records(incoming_records)
    for record in reconciled:
        session_id = record.get("session_id", "")
        for key, field in record.get("signals", {}).items():
            analyzed_at = analyzed_by_identity.get(
                _facts_memory_identity(session_id, key, field)
            )
            if analyzed_at is None:
                continue
            field["l4_status"] = "analyzed"
            field["l4_analyzed_at"] = analyzed_at

    return reconciled


def _publish_server_facts_memory_state(context) -> None:
    app_state = getattr(
        context,
        "runtime_l4_app_state",
        None,
    )
    if app_state is None:
        return
    if bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    ):
        return

    app_state.l4_facts_memory_records = normalize_facts_memory_records(
        getattr(context, "runtime_facts_memory_records", [])
    )
    app_state.l4_runtime_context = context
    context.runtime_l4_profile_sync_at = time.monotonic()
    wake_l4_memory_server_scheduler(context)


def l4_memory_has_pending_work(context) -> bool:
    if collect_pending_facts_memory_fields(
        getattr(
            context,
            "runtime_facts_memory_records",
            [],
        )
    ):
        return True

    return bool(
        ensure_runtime_l4_state(context).get(
            "pending_facts"
        )
    )


def runtime_l4_file_store_enabled(context) -> bool:

    explicit = getattr(
        context,
        "runtime_l4_file_store_enabled",
        None,
    )
    if explicit is not None:
        return bool(
            explicit
        )

    return getattr(
        context,
        "websocket",
        None,
    ) is not None


def get_runtime_l4_file_store_root(context):

    return getattr(
        context,
        "runtime_l4_file_store_root",
        None,
    )


def load_runtime_l4_file_store(context) -> dict:

    root = get_runtime_l4_file_store_root(
        context,
    )

    if root is None:
        store, _warnings = load_long_term_facts_store()
    else:
        store, _warnings = load_long_term_facts_store(
            root=root,
        )

    return store


def persist_runtime_l4_file_store(context, store) -> None:

    if bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    ):
        return

    if not runtime_l4_file_store_enabled(
        context,
    ):
        return

    root = get_runtime_l4_file_store_root(
        context,
    )

    if root is None:
        persist_long_term_facts_store(
            store,
        )
        return

    persist_long_term_facts_store(
        store,
        root=root,
    )


def merge_with_runtime_l4_file_store(context, store) -> tuple[dict, bool]:

    if not runtime_l4_file_store_enabled(
        context,
    ):
        return normalize_l4_store(
            store,
        ), False

    file_store = load_runtime_l4_file_store(
        context,
    )
    merged, change = merge_l4_store_snapshots(
        file_store,
        store,
    )

    if change.get(
        "changed",
    ):
        persist_runtime_l4_file_store(
            context,
            merged,
        )

    return merged, bool(
        change.get(
            "changed",
        )
    )


def set_runtime_l4_state(context, store) -> dict:

    merged, _changed = merge_with_runtime_l4_file_store(
        context,
        store,
    )
    context.runtime_long_term_memory_store = merged
    return merged


def get_loaded_delayed_memory_reports(
    context,
) -> dict:

    from utils.brain_client_utils import (
        get_loaded_delayed_memory_reports,
    )

    return get_loaded_delayed_memory_reports(
        context
    )


def get_context_delayed_memory_reports(
    context,
) -> dict:

    loaded_reports = get_loaded_delayed_memory_reports(
        context
    )
    context_reports = {
        report_id: {
            **report,
            "id": report_id,
        }
        for report_id, report in loaded_reports.items()
        if isinstance(report, dict)
    }
    stored_reports = getattr(
        context,
        "delayed_memory_reports",
        {},
    )

    if not isinstance(stored_reports, dict):
        return context_reports

    # Pinning is a direct context state, just like an explicit load. Keep this
    # helper pure: L4 visibility must not depend on another prompt builder
    # having called include_pinned_delayed_memory_reports() first.
    for raw_report_id, report in stored_reports.items():
        if (
            not isinstance(report, dict)
            or not bool(report.get("pinned", False))
        ):
            continue

        report_id = str(
            raw_report_id
            or report.get("id", "")
            or ""
        ).strip().casefold()

        if not report_id:
            continue

        context_reports[report_id] = {
            **report,
            "id": report_id,
        }

    return context_reports


def collect_loaded_delayed_memory_fact_ids(
    context,
) -> set[str]:

    return collect_long_term_fact_ids_from_reports(
        get_context_delayed_memory_reports(
            context
        )
    )


def collect_loaded_delayed_memory_fact_report_ids(
    context,
) -> dict[str, list[str]]:

    reports = get_context_delayed_memory_reports(
        context
    )

    if not isinstance(
        reports,
        dict,
    ):
        return {}

    report_ids_by_fact: dict[str, list[str]] = {}

    for report_id, report in reports.items():
        if not isinstance(
            report,
            dict,
        ):
            continue

        normalized_report_id = str(
            report_id
            or report.get(
                "id",
                "",
            )
            or ""
        ).strip().casefold()

        if not normalized_report_id:
            continue

        _anchor_ids, fact_ids = normalize_delayed_memory_fact_ids(
            report.get(
                "anchor_fact_ids",
                [],
            ),
            report.get(
                "facts_ids",
                [],
            ),
            legacy_absorbed_fact_ids=report.get(
                "absorbed_fact_ids",
                [],
            ),
            legacy_long_term_fact_ids=report.get(
                "long_term_facts_ids",
                [],
            ),
        )

        for fact_id in fact_ids:
            report_ids_by_fact.setdefault(
                fact_id,
                [],
            )
            if normalized_report_id not in report_ids_by_fact[fact_id]:
                report_ids_by_fact[fact_id].append(
                    normalized_report_id
                )

    return report_ids_by_fact


def merge_l4_fact_report_id_maps(
    *maps,
) -> dict[str, list[str]]:

    merged: dict[str, list[str]] = {}

    for mapping in maps:
        if not isinstance(
            mapping,
            dict,
        ):
            continue

        for fact_id, report_ids in mapping.items():
            normalized_fact_id = str(
                fact_id
                or ""
            ).strip().upper()

            if not normalized_fact_id:
                continue

            if isinstance(
                report_ids,
                str,
            ):
                candidates = [
                    report_ids,
                ]
            elif isinstance(
                report_ids,
                list,
            ):
                candidates = report_ids
            else:
                candidates = []

            merged.setdefault(
                normalized_fact_id,
                [],
            )

            for report_id in candidates:
                normalized_report_id = str(
                    report_id
                    or ""
                ).strip().casefold()

                if (
                    normalized_report_id
                    and normalized_report_id
                    not in merged[normalized_fact_id]
                ):
                    merged[normalized_fact_id].append(
                        normalized_report_id
                    )

    return merged


def refresh_runtime_l4_archived_fact_ids(
    context,
) -> set[str]:

    reports = getattr(
        context,
        "delayed_memory_reports",
        {},
    )
    fact_ids = collect_long_term_fact_ids_from_reports(
        reports
    )
    # Anchor is a global visibility guarantee: if any delayed report keeps a
    # fact as an anchor, another report cannot accidentally hide it.
    anchor_fact_ids = set(
        collect_anchor_fact_report_ids(
            reports
        )
    )
    fact_ids.difference_update(anchor_fact_ids)
    # A loaded delayed-memory report is in the prompt as an active context
    # attachment, so every L4 fact represented by that report becomes visible
    # again for the duration of the load.
    fact_ids.difference_update(
        collect_loaded_delayed_memory_fact_ids(
            context
        )
    )
    context.runtime_l4_archived_fact_ids = set(
        fact_ids
    )
    return context.runtime_l4_archived_fact_ids

def ensure_runtime_l4_state(context) -> dict:
    context.runtime_facts_memory_records = normalize_facts_memory_records(
        getattr(context, "runtime_facts_memory_records", [])
    )
    normalized_store = normalize_l4_store(
        getattr(context, "runtime_long_term_memory_store", None)
    )
    context.runtime_long_term_memory_store = set_runtime_l4_state(
        context,
        normalized_store,
    )
    return context.runtime_long_term_memory_store


def apply_facts_memory_store_sync(context, raw_records) -> dict:
    incoming_records = normalize_facts_memory_records(raw_records)
    restricted = bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    )
    app_state = getattr(
        context,
        "runtime_l4_app_state",
        None,
    )
    server_records = (
        getattr(
            app_state,
            "l4_facts_memory_records",
            [],
        )
        if app_state is not None
        else []
    )
    records = (
        incoming_records
        if restricted
        else _preserve_server_analyzed_facts_memory(
            incoming_records,
            server_records,
        )
    )
    context.runtime_facts_memory_records = records
    _publish_server_facts_memory_state(context)
    return {
        "records_count": len(records),
        "signals_count": sum(int(record.get("signal_count") or 0) for record in records),
        "pending_count": len(collect_pending_facts_memory_fields(records)),
    }


def apply_l4_memory_store_sync(context, raw_store) -> bool:
    if bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    ):
        ensure_runtime_l4_state(context)
        return False

    incoming = normalize_l4_store(raw_store)
    current = ensure_runtime_l4_state(context)
    merged, change = merge_l4_store_snapshots(
        current,
        incoming,
    )
    changed = bool(
        change.get(
            "changed",
        )
    )
    context.runtime_long_term_memory_store = merged

    if changed:
        persist_runtime_l4_file_store(
            context,
            merged,
        )

    return changed


def runtime_l4_memory_update_running(context) -> bool:
    task = getattr(context, "runtime_l4_memory_update_task", None)
    return task is not None and not task.done()


async def cancel_l4_memory_idle_update(
    context,
    *,
    reason: str = "user_activity",
) -> bool:
    """Preempt only background-idle L4 work so foreground chat wins.

    Pending fields/facts live in the runtime stores and are not consumed until a
    consolidation result is committed, so cancelling an in-flight model request
    leaves them available for the next genuine idle window.
    """
    # Every real user turn starts a new configured background-idle cycle even
    # when no L4 task happens to be running at this exact moment.
    context.runtime_l4_idle_last_started_at = time.monotonic()

    task = getattr(context, "runtime_l4_memory_update_task", None)
    kind = str(getattr(context, "runtime_l4_memory_update_kind", "") or "")

    if task is None or task.done() or kind != "idle":
        return False

    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    except Exception:
        # Cancellation is best-effort; foreground work must not be blocked by
        # cleanup from a background maintenance request.
        pass

    if getattr(context, "runtime_l4_memory_update_task", None) is task:
        context.runtime_l4_memory_update_task = None
    if str(getattr(context, "runtime_l4_memory_update_kind", "") or "") == "idle":
        context.runtime_l4_memory_update_kind = ""

    # Merge recovery/quarantine state is intentionally preserved. Cancellation
    # changes only scheduling; it must not resurrect a known poison PF or forget
    # an adaptive batch limit.

    log_runtime = getattr(getattr(context, "logger", None), "log_runtime", None)
    await safe_call(
        log_runtime,
        "[MEMORY:L4] idle work preempted by "
        f"{normalize_l4_text(reason) or 'user_activity'}; pending preserved",
    )
    return True


async def emit_facts_memory_store_update(context) -> None:
    emit = getattr(getattr(context, "emitter", None), "emit", None)
    await safe_call(
        emit,
        {
            "type": "facts_memory_store_update",
            "records": normalize_facts_memory_records(
                getattr(context, "runtime_facts_memory_records", [])
            ),
        },
    )


async def emit_l4_memory_update(context, *, change: dict | None = None) -> None:
    emit = getattr(getattr(context, "emitter", None), "emit", None)
    await safe_call(
        emit,
        {
            "type": "l4_memory_update",
            "store": clone_l4_store(ensure_runtime_l4_state(context)),
            "change": change or {},
        },
    )


def remap_delayed_memory_l4_fact_ids(
    context,
    *,
    removed_fact_ids: list[str],
    replacement_fact_ids: list[str],
    replacement_fact_id_map: dict | None = None,
) -> dict:
    removed_ids = set(normalize_long_term_fact_ids(removed_fact_ids))
    replacement_ids = normalize_long_term_fact_ids(replacement_fact_ids)
    normalized_replacement_map = {}
    if isinstance(replacement_fact_id_map, dict):
        for raw_removed_id, raw_replacement_ids in replacement_fact_id_map.items():
            normalized_removed = normalize_long_term_fact_ids([raw_removed_id])
            if not normalized_removed:
                continue
            normalized_targets = normalize_long_term_fact_ids(
                raw_replacement_ids
                if isinstance(raw_replacement_ids, (list, tuple, set))
                else [raw_replacement_ids]
            )
            if normalized_targets:
                normalized_replacement_map[normalized_removed[0]] = normalized_targets

    def replacements_for(removed_ids_for_report: list[str]) -> list[str]:
        mapped = []
        for removed_id in removed_ids_for_report:
            targets = normalized_replacement_map.get(removed_id)
            if targets is None:
                # Backwards-compatible path for one replacement (the original
                # JIN-note merge shape). Never spray multiple independent merge
                # replacements onto every removed ID.
                targets = replacement_ids if len(replacement_ids) <= 1 else []
            mapped.extend(targets)
        return normalize_long_term_fact_ids(mapped)

    if not removed_ids:
        return {
            "changed": False,
            "report_ids": [],
            "removed_report_refs": [],
            "file_errors": [],
        }

    reports = getattr(context, "delayed_memory_reports", None)
    if not isinstance(reports, dict):
        return {
            "changed": False,
            "report_ids": [],
            "removed_report_refs": [],
            "file_errors": [],
        }

    from utils.brain_client_utils import get_loaded_delayed_memory_reports

    loaded_reports = get_loaded_delayed_memory_reports(context)
    changed_reports = {}
    removed_report_refs = []

    for report_id, report in list(reports.items()):
        if not isinstance(report, dict):
            continue

        current_anchor_ids, current_fact_ids = (
            normalize_delayed_memory_fact_ids(
                report.get("anchor_fact_ids", []),
                report.get("facts_ids", []),
                legacy_absorbed_fact_ids=report.get("absorbed_fact_ids", []),
                legacy_long_term_fact_ids=report.get("long_term_facts_ids", []),
            )
        )
        removed_anchor_ids = [
            fact_id
            for fact_id in current_anchor_ids
            if fact_id in removed_ids
        ]
        removed_fact_ids_for_report = [
            fact_id
            for fact_id in current_fact_ids
            if fact_id in removed_ids
        ]
        removed_anchor = bool(removed_anchor_ids)
        removed_fact = bool(removed_fact_ids_for_report)

        if not removed_anchor and not removed_fact:
            continue

        removed_report_refs.append({
            "report_id": str(report_id or "").strip(),
            "anchor_fact_ids": removed_anchor_ids,
            "facts_ids": removed_fact_ids_for_report,
        })

        next_anchor_ids = [
            fact_id
            for fact_id in current_anchor_ids
            if fact_id not in removed_ids
        ]
        next_fact_ids = [
            fact_id
            for fact_id in current_fact_ids
            if fact_id not in removed_ids
        ]

        if removed_anchor:
            next_anchor_ids.extend(replacements_for(removed_anchor_ids))
        if removed_fact:
            next_fact_ids.extend(replacements_for(removed_fact_ids_for_report))

        next_anchor_ids, next_fact_ids = (
            normalize_delayed_memory_fact_ids(
                next_anchor_ids,
                next_fact_ids,
            )
        )
        updated_report = {
            **report,
            "anchor_fact_ids": next_anchor_ids,
            "facts_ids": next_fact_ids,
        }
        updated_report.pop("absorbed_fact_ids", None)
        updated_report.pop("long_term_facts_ids", None)
        reports[report_id] = updated_report
        changed_reports[report_id] = updated_report

        if report_id in loaded_reports:
            loaded_reports[report_id] = {
                **updated_report,
                "id": report_id,
            }

    file_errors = []
    if changed_reports and bool(
        getattr(context, "delayed_memory_file_store_enabled", False)
    ):
        from utils.delayed_memory_file_store import persist_delayed_memory_reports

        file_errors = persist_delayed_memory_reports(changed_reports)

    if changed_reports:
        refresh_runtime_l4_archived_fact_ids(context)

    return {
        "changed": bool(changed_reports),
        "report_ids": sorted(changed_reports),
        "removed_report_refs": sorted(
            removed_report_refs,
            key=lambda item: item["report_id"],
        ),
        "file_errors": file_errors,
    }


def normalize_l4_fact_restore_report_refs(value) -> list[dict]:
    if not isinstance(value, dict):
        return []

    refs = value.get("delayed_memory_report_refs")
    if not isinstance(refs, list):
        return []

    clean_refs = []
    seen = set()
    for ref in refs:
        if not isinstance(ref, dict):
            continue

        report_id = str(ref.get("report_id") or "").strip()
        if not report_id:
            continue

        anchor_fact_ids = normalize_long_term_fact_ids(
            ref.get("anchor_fact_ids", [])
        )
        fact_ids = normalize_long_term_fact_ids(
            ref.get("facts_ids", [])
        )
        if not anchor_fact_ids and not fact_ids:
            continue

        dedupe_key = (
            report_id,
            tuple(anchor_fact_ids),
            tuple(fact_ids),
        )
        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        clean_refs.append({
            "report_id": report_id,
            "anchor_fact_ids": anchor_fact_ids,
            "facts_ids": fact_ids,
        })

    return clean_refs


def build_l4_deleted_fact_restore_meta(delayed_memory_change: dict) -> dict:
    refs = normalize_l4_fact_restore_report_refs({
        "delayed_memory_report_refs": (
            delayed_memory_change.get("removed_report_refs")
            if isinstance(delayed_memory_change, dict)
            else []
        ),
    })
    if not refs:
        return {}

    return {
        "version": 1,
        "delayed_memory_report_refs": refs,
    }


def restore_delayed_memory_l4_fact_refs(
    context,
    *,
    fact_id: str,
    restore_meta: dict,
) -> dict:
    normalized_fact_ids = normalize_long_term_fact_ids([fact_id])
    if not normalized_fact_ids:
        return {
            "changed": False,
            "report_ids": [],
            "missing_report_ids": [],
            "file_errors": [],
        }

    target_id = normalized_fact_ids[0]
    refs = [
        ref
        for ref in normalize_l4_fact_restore_report_refs(restore_meta)
        if (
            target_id in ref.get("anchor_fact_ids", [])
            or target_id in ref.get("facts_ids", [])
        )
    ]
    if not refs:
        return {
            "changed": False,
            "report_ids": [],
            "missing_report_ids": [],
            "file_errors": [],
        }

    reports = getattr(context, "delayed_memory_reports", None)
    if not isinstance(reports, dict):
        return {
            "changed": False,
            "report_ids": [],
            "missing_report_ids": [
                ref["report_id"]
                for ref in refs
            ],
            "file_errors": [],
        }

    from utils.brain_client_utils import get_loaded_delayed_memory_reports

    loaded_reports = get_loaded_delayed_memory_reports(context)
    changed_reports = {}
    missing_report_ids = []

    for ref in refs:
        report_id = ref["report_id"]
        report = reports.get(report_id)
        if not isinstance(report, dict):
            missing_report_ids.append(report_id)
            continue

        current_anchor_ids, current_fact_ids = (
            normalize_delayed_memory_fact_ids(
                report.get("anchor_fact_ids", []),
                report.get("facts_ids", []),
                legacy_absorbed_fact_ids=report.get("absorbed_fact_ids", []),
                legacy_long_term_fact_ids=report.get("long_term_facts_ids", []),
            )
        )
        next_anchor_ids = list(current_anchor_ids)
        next_fact_ids = list(current_fact_ids)

        if (
            target_id in ref.get("anchor_fact_ids", [])
            and target_id not in next_anchor_ids
        ):
            next_anchor_ids.append(target_id)
        if (
            target_id in ref.get("facts_ids", [])
            and target_id not in next_fact_ids
        ):
            next_fact_ids.append(target_id)

        next_anchor_ids, next_fact_ids = (
            normalize_delayed_memory_fact_ids(
                next_anchor_ids,
                next_fact_ids,
            )
        )
        if (
            next_anchor_ids == current_anchor_ids
            and next_fact_ids == current_fact_ids
        ):
            continue

        updated_report = {
            **report,
            "anchor_fact_ids": next_anchor_ids,
            "facts_ids": next_fact_ids,
        }
        updated_report.pop("absorbed_fact_ids", None)
        updated_report.pop("long_term_facts_ids", None)
        reports[report_id] = updated_report
        changed_reports[report_id] = updated_report

        if report_id in loaded_reports:
            loaded_reports[report_id] = {
                **updated_report,
                "id": report_id,
            }

    file_errors = []
    if changed_reports and bool(
        getattr(context, "delayed_memory_file_store_enabled", False)
    ):
        from utils.delayed_memory_file_store import persist_delayed_memory_reports

        file_errors = persist_delayed_memory_reports(changed_reports)

    if changed_reports:
        refresh_runtime_l4_archived_fact_ids(context)

    return {
        "changed": bool(changed_reports),
        "report_ids": sorted(changed_reports),
        "missing_report_ids": sorted(set(missing_report_ids)),
        "file_errors": file_errors,
    }


async def emit_delayed_memory_reference_update(context) -> None:
    emit = getattr(getattr(context, "emitter", None), "emit", None)
    if emit is None:
        return

    from utils.delayed_memory_file_store import normalize_delayed_memory_reports

    await safe_call(
        emit,
        {
            "type": "delayed_memory_store_snapshot",
            "delayed_memory_reports": normalize_delayed_memory_reports(
                getattr(context, "delayed_memory_reports", {})
            ),
        },
    )


async def ask_l4_model(
    *,
    context,
    service_client,
    label: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int | None,
) -> dict:
    request_limits = await resolve_l4_request_limits(
        service_client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        requested_max_tokens=max_tokens,
    )
    effective_max_tokens = (
        request_limits.get("effective_max_tokens")
        or 1
    )

    await refresh_service_runtime_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context_window=request_limits.get("context_window_tokens") or None,
    )
    await log_runtime_summarizer_payload(
        context,
        label=label,
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=getattr(config, "SERVICE_TEMPERATURE", 0.1),
            max_tokens=effective_max_tokens,
        ),
    )

    response = await ask_service_model(
        client=service_client,
        context=context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=getattr(config, "SERVICE_TEMPERATURE", 0.1),
        max_tokens=effective_max_tokens,
        timeout=getattr(config, "SERVICE_REQUEST_TIMEOUT", 1000.0),
        track_usage=False,
    )
    if isinstance(response, dict):
        response["_jin_l4_request_meta"] = {
            **request_limits,
            "model": getattr(
                service_client,
                "model_uid",
                "",
            ),
        }

    response_text = extract_runtime_memory_text(
        response,
    )

    if response_text:
        await log_runtime_summarizer_result(
            context,
            label=label,
            result=response_text,
        )
    await refresh_service_runtime_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response=response,
        context_window=request_limits.get("context_window_tokens") or None,
    )
    return response


async def log_l4_skip_event(
    context,
    *,
    phase: str,
    message_phase: str,
    reason: str,
    details: dict | None = None,
) -> dict:
    result = {
        "phase": phase,
        "status": "skipped",
        "reason": reason,
    }

    if details:
        result.update(details)

    display_reason = (
        "output truncated before final response"
        if reason == "response_truncated"
        else reason
    )

    await log_memory_event(
        context,
        level=L4_LOG_LEVEL,
        message=f"L4 {message_phase} skipped: {display_reason}",
        details=json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        fallback_channel="summarizer",
        event=f"{phase}_skipped",
        trace_reason=result.get("summary"),
    )

    return result


def build_l4_merge_budget_skip_details(
    *,
    service_client,
    system_prompt: str,
    batch_plan: dict,
    pending_queue: list[dict],
    provider_context_window_recovered: bool = False,
) -> dict:
    context_window = _positive_int(
        batch_plan.get("runtime_context_window_tokens")
    )
    estimated_total = _positive_int(
        batch_plan.get("estimated_total_tokens")
    )
    first_pending = (
        dict(pending_queue[0])
        if pending_queue
        and isinstance(pending_queue[0], dict)
        else {}
    )
    first_pending_id = str(
        first_pending.get("id") or ""
    ).strip()
    user_prompt = str(
        batch_plan.get("user_prompt") or ""
    )
    request_payload = build_runtime_summarizer_payload(
        service_client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=getattr(
            config,
            "SERVICE_TEMPERATURE",
            0.1,
        ),
        max_tokens=batch_plan.get(
            "requested_max_output_tokens"
        ),
    )

    return {
        "kind": "l4_skip",
        "summary": (
            "The next FIFO L4 merge candidate could not fit inside the "
            "service context budget even after batching was reduced to one "
            "pending fact. No L4 data was changed."
        ),
        "retry_behavior": (
            "The pending candidate remains queued. A later idle merge can "
            "retry after the context budget changes."
        ),
        "pending_count": len(pending_queue),
        "first_pending_id": first_pending_id,
        "runtime_context_window_tokens": context_window,
        "estimated_prompt_tokens": batch_plan[
            "estimated_prompt_tokens"
        ],
        "estimated_response_tokens": batch_plan[
            "estimated_response_tokens"
        ],
        "runtime_output_reserve_tokens": batch_plan[
            "runtime_output_reserve_tokens"
        ],
        "response_headroom_tokens": batch_plan[
            "response_headroom_tokens"
        ],
        "default_response_headroom_tokens": batch_plan.get(
            "default_response_headroom_tokens",
            batch_plan["response_headroom_tokens"],
        ),
        "response_headroom_squeezed": bool(
            batch_plan.get("response_headroom_squeezed")
        ),
        "estimated_total_tokens": estimated_total,
        "overflow_tokens": max(
            0,
            estimated_total - context_window,
        ),
        "provider_context_window_recovered": bool(
            provider_context_window_recovered
        ),
        # Keep the candidate separately for a readable first view, then expose
        # the exact would-be service request below it in the logger modal.
        "merge_candidate": first_pending,
        "request_payload": request_payload,
    }


async def run_l4_extraction_phase(
    *,
    context,
    service_client,
    pending_fields: list[dict],
) -> dict:
    system_prompt = build_l4_extraction_system_prompt()
    user_prompt = build_l4_extraction_user_prompt(pending_fields=pending_fields)
    response = await ask_l4_model(
        context=context,
        service_client=service_client,
        label="L4 extraction",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=None,
    )

    if is_runtime_memory_response_truncated(response):
        return await log_l4_skip_event(
            context,
            phase="extract",
            message_phase="extraction",
            reason="response_truncated",
            details=build_l4_truncation_details(
                response,
                phase="extract",
                selected_fields_count=len(pending_fields),
            ),
        )

    payload = extract_l4_json_payload(
        extract_runtime_memory_text(
            response,
        )
    )
    if payload is None:
        return await log_l4_skip_event(
            context,
            phase="extract",
            message_phase="extraction",
            reason="invalid_json",
            details={
                "selected_fields_count": len(pending_fields),
            },
        )

    raw_candidates = payload.get("facts")
    if not isinstance(raw_candidates, list):
        return await log_l4_skip_event(
            context,
            phase="extract",
            message_phase="extraction",
            reason="invalid_facts_payload",
            details={
                "selected_fields_count": len(pending_fields),
            },
        )

    candidates = normalize_l4_candidates(
        payload,
        source_fields=pending_fields,
    )
    if len(candidates) != len(raw_candidates):
        return await log_l4_skip_event(
            context,
            phase="extract",
            message_phase="extraction",
            reason="invalid_candidates",
            details={
                "selected_fields_count": len(pending_fields),
                "raw_candidates_count": len(raw_candidates),
                "valid_candidates_count": len(candidates),
            },
        )
    store, pending_change = add_l4_pending_candidates(
        ensure_runtime_l4_state(context),
        candidates,
    )
    context.runtime_long_term_memory_store = store
    persist_runtime_l4_file_store(
        context,
        store,
    )

    records, records_changed = mark_facts_memory_fields_analyzed(
        getattr(context, "runtime_facts_memory_records", []),
        pending_fields,
    )
    context.runtime_facts_memory_records = records
    _publish_server_facts_memory_state(context)

    if records_changed:
        await emit_facts_memory_store_update(context)
    if pending_change.get("changed"):
        await emit_l4_memory_update(context, change=pending_change)

    return {
        "phase": "extract",
        "status": "completed",
        "selected_fields_count": len(pending_fields),
        "candidates_count": len(candidates),
        "pending_change": pending_change,
    }


def get_runtime_l4_explicit_edit_fact_ids(context) -> list[str]:
    current_turn_id = str(
        getattr(context, "runtime_current_turn_id", "")
        or ""
    ).strip()
    protected_turn_id = str(
        getattr(context, "runtime_l4_explicit_edit_turn_id", "")
        or ""
    ).strip()

    if not current_turn_id or protected_turn_id != current_turn_id:
        return []

    return normalize_long_term_fact_ids(
        list(
            getattr(context, "runtime_l4_explicit_edit_fact_ids", set())
            or []
        )
    )


def mark_runtime_l4_explicit_edit(
    context,
    fact_ids,
) -> None:
    current_turn_id = str(
        getattr(context, "runtime_current_turn_id", "")
        or ""
    ).strip()
    normalized_ids = set(
        normalize_long_term_fact_ids(fact_ids)
    )

    if not current_turn_id or not normalized_ids:
        return

    protected_turn_id = str(
        getattr(context, "runtime_l4_explicit_edit_turn_id", "")
        or ""
    ).strip()
    existing_ids = (
        set(
            getattr(context, "runtime_l4_explicit_edit_fact_ids", set())
            or set()
        )
        if protected_turn_id == current_turn_id
        else set()
    )

    context.runtime_l4_explicit_edit_turn_id = current_turn_id
    context.runtime_l4_explicit_edit_fact_ids = (
        existing_ids | normalized_ids
    )


def protect_explicit_l4_edits_from_merge(
    operations: list[dict],
    protected_fact_ids,
) -> tuple[list[dict], list[str]]:
    protected_ids = set(
        normalize_long_term_fact_ids(protected_fact_ids)
    )
    if not protected_ids:
        return operations, []

    protected_pending_ids = []
    next_operations = []

    for operation in operations:
        if not isinstance(operation, dict):
            continue

        action = operation.get("action")
        touches_protected = (
            action == "update"
            and operation.get("target_id") in protected_ids
        ) or (
            action == "merge"
            and any(
                fact_id in protected_ids
                for fact_id in operation.get("fact_ids", [])
            )
        )
        if touches_protected:
            pending_id = str(
                operation.get("pending_id") or ""
            ).strip()
            if pending_id:
                protected_pending_ids.append(pending_id)
            next_operations.append({
                "action": "ignore",
                "pending_id": pending_id,
                "comment": "Protected by an explicit L4 edit in this turn.",
            })
            continue

        next_operations.append(operation)

    return next_operations, protected_pending_ids


def _l4_fact_semantic_signature(fact) -> tuple[str, str, str]:
    if not isinstance(fact, dict):
        return ("", "", "")

    return (
        normalize_l4_key(fact.get("key")),
        normalize_l4_text(fact.get("value")),
        normalize_l4_key(fact.get("category")),
    )


def rebase_l4_merge_operations(
    *,
    base_store,
    current_store,
    operations: list[dict],
    pending_ids: list[str],
) -> tuple[dict, dict]:
    """Apply an already-generated merge result to the newest L4 snapshot.

    The service model reasons over ``base_store``. While that request is in
    flight another tab/runtime action can legitimately advance the canonical
    store. A whole-store equality guard is therefore too coarse: it throws
    away a still-valid model result and the next idle tick asks the model the
    same question again.

    Rebase only when the records actually touched by the model are unchanged
    semantically. Unrelated additions/revisions and provenance-only updates are
    safe. If a touched committed/pending fact changed meaning, keep the pending
    work for a later pass instead of overwriting a concurrent edit.
    """

    base = clone_l4_store(base_store)
    current = clone_l4_store(current_store)

    base_facts = {
        str(fact.get("id") or "").strip(): fact
        for fact in base.get("facts") or []
        if str(fact.get("id") or "").strip()
    }
    current_facts = {
        str(fact.get("id") or "").strip(): fact
        for fact in current.get("facts") or []
        if str(fact.get("id") or "").strip()
    }
    base_pending = {
        str(fact.get("id") or "").strip(): fact
        for fact in base.get("pending_facts") or []
        if str(fact.get("id") or "").strip()
    }
    current_pending = {
        str(fact.get("id") or "").strip(): fact
        for fact in current.get("pending_facts") or []
        if str(fact.get("id") or "").strip()
    }

    selected_pending_ids = [
        str(pending_id or "").strip()
        for pending_id in pending_ids
        if str(pending_id or "").strip()
    ]
    active_pending_ids = [
        pending_id
        for pending_id in selected_pending_ids
        if pending_id in current_pending
    ]
    superseded_pending_ids = [
        pending_id
        for pending_id in selected_pending_ids
        if pending_id not in current_pending
    ]

    # Another writer may already have consumed all selected PFs. That is a
    # successful convergence, not a reason to ask the model again.
    if not active_pending_ids:
        return current, {
            "valid": True,
            "changed": False,
            "rebased": True,
            "superseded_pending_ids": superseded_pending_ids,
            "processed_pending_ids": superseded_pending_ids,
            "pending_count": len(current.get("pending_facts") or []),
            "operation_details": [],
            "removed_fact_ids": [],
            "replacement_fact_ids": [],
            "replacement_fact_id_map": {},
        }

    active_pending_id_set = set(active_pending_ids)
    rebased_operations = [
        dict(operation)
        for operation in operations
        if str(operation.get("pending_id") or "").strip()
        in active_pending_id_set
    ]

    conflict_pending_ids = []
    conflict_fact_ids = []

    for operation in rebased_operations:
        pending_id = str(operation.get("pending_id") or "").strip()
        if (
            _l4_fact_semantic_signature(base_pending.get(pending_id))
            != _l4_fact_semantic_signature(current_pending.get(pending_id))
        ):
            conflict_pending_ids.append(pending_id)
            continue

        action = operation.get("action")
        touched_fact_ids = []
        if action == "update":
            target_id = str(operation.get("target_id") or "").strip()
            if target_id:
                touched_fact_ids.append(target_id)
        elif action == "merge":
            touched_fact_ids.extend(
                str(fact_id or "").strip()
                for fact_id in operation.get("fact_ids", [])
                if str(fact_id or "").strip()
            )

        for fact_id in touched_fact_ids:
            if (
                _l4_fact_semantic_signature(base_facts.get(fact_id))
                != _l4_fact_semantic_signature(current_facts.get(fact_id))
            ):
                conflict_fact_ids.append(fact_id)

        # A concurrent writer may have created exactly the fact this operation
        # planned to create. Fold the pending provenance into that fact rather
        # than rejecting the stale create and generating another request.
        if action == "create":
            desired_signature = (
                normalize_l4_key(operation.get("key")),
                normalize_l4_text(operation.get("value")),
                normalize_l4_key(operation.get("category")),
            )
            same_key = [
                fact
                for fact in current_facts.values()
                if normalize_l4_key(fact.get("key")) == desired_signature[0]
            ]
            if same_key:
                exact_matches = [
                    fact
                    for fact in same_key
                    if _l4_fact_semantic_signature(fact) == desired_signature
                ]
                if len(exact_matches) == 1:
                    operation["action"] = "update"
                    operation["target_id"] = exact_matches[0]["id"]
                else:
                    conflict_pending_ids.append(pending_id)

    conflict_pending_ids = sorted(set(conflict_pending_ids))
    conflict_fact_ids = sorted(set(conflict_fact_ids))
    if conflict_pending_ids or conflict_fact_ids:
        return current, {
            "valid": False,
            "changed": False,
            "reason": "store_changed_on_merge_targets",
            "rebased": False,
            "conflict_pending_ids": conflict_pending_ids,
            "conflict_fact_ids": conflict_fact_ids,
            "superseded_pending_ids": superseded_pending_ids,
        }

    rebased_store, rebased_change = apply_l4_merge_operations(
        current,
        rebased_operations,
        pending_ids=active_pending_ids,
    )
    if not rebased_change.get("valid"):
        return current, {
            **rebased_change,
            "reason": "store_changed_rebase_conflict",
            "rebase_validation_reason": rebased_change.get("reason"),
            "rebased": False,
            "superseded_pending_ids": superseded_pending_ids,
        }

    rebased_change["rebased"] = True
    rebased_change["base_revision"] = base.get("revision")
    rebased_change["rebased_onto_revision"] = current.get("revision")
    if superseded_pending_ids:
        rebased_change["superseded_pending_ids"] = superseded_pending_ids
        rebased_change["processed_pending_ids"] = sorted(set(
            list(rebased_change.get("processed_pending_ids") or [])
            + superseded_pending_ids
        ))

    return rebased_store, rebased_change


async def log_l4_context_paused(
    context,
    *,
    minimum_required: int,
    maximum_available: int,
    pending_count: int,
    existing_fact_count: int,
) -> dict:
    minimum_required = max(1, int(minimum_required or 1))
    maximum_available = max(1, int(maximum_available or 1))
    signature = (
        f"{minimum_required}:{maximum_available}:"
        f"{pending_count}:{existing_fact_count}"
    )
    already_logged = (
        str(
            getattr(
                context,
                "runtime_l4_merge_paused_signature",
                "",
            )
            or ""
        )
        == signature
    )
    context.runtime_l4_merge_paused_signature = signature

    result = {
        "phase": "merge",
        "status": "paused",
        "reason": "not_enough_context_window_size",
        "minimum_required": minimum_required,
        "maximum_available": maximum_available,
        "pending_count": max(0, int(pending_count or 0)),
        "existing_fact_count": max(0, int(existing_fact_count or 0)),
    }
    if already_logged:
        return result

    message = (
        "Not enough context window size\n"
        f"Minimum required: {minimum_required}\n"
        f"Maximum available: {maximum_available}"
    )
    await log_memory_event(
        context,
        level=L4_LOG_LEVEL,
        message=message,
        details=json.dumps(
            {
                "kind": "l4_context_paused",
                **result,
            },
            ensure_ascii=False,
            indent=2,
        ),
        fallback_channel="summarizer",
        event="merge_paused",
        tag_suffix="PAUSED",
    )
    return result


async def run_l4_merge_phase(*, context, service_client) -> dict:
    base_store = clone_l4_store(ensure_runtime_l4_state(context))
    pending_queue = list(base_store.get("pending_facts") or [])
    if not pending_queue:
        reset_l4_merge_recovery_state(context)
        return {
            "phase": "merge",
            "status": "skipped",
            "reason": "no_pending_long_term_facts",
        }

    retry_backoff = get_l4_merge_retry_backoff(context)
    if retry_backoff is not None:
        return retry_backoff

    pending_queue, deferred_backoff = get_l4_merge_available_pending_queue(
        context,
        pending_queue,
    )
    if deferred_backoff is not None:
        return deferred_backoff

    all_pending_ids = {
        str(fact.get("id") or "").strip()
        for fact in base_store.get("pending_facts") or []
        if isinstance(fact, dict) and str(fact.get("id") or "").strip()
    }
    single_retry_ids = {
        pending_id
        for pending_id in set(
            getattr(
                context,
                "runtime_l4_merge_single_retry_pending_ids",
                set(),
            )
            or set()
        )
        if pending_id in all_pending_ids
    }
    context.runtime_l4_merge_single_retry_pending_ids = single_retry_ids

    single_retry_pending_id = next(
        (
            str(fact.get("id") or "").strip()
            for fact in pending_queue
            if isinstance(fact, dict)
            and str(fact.get("id") or "").strip() in single_retry_ids
        ),
        "",
    )
    if single_retry_pending_id:
        # Once a repaired shard item has failed, retry that candidate alone.
        # Move only the due retry to the front without mutating canonical FIFO
        # storage; later valid items remain available on the following tick.
        pending_queue = [
            *[
                fact
                for fact in pending_queue
                if str(fact.get("id") or "").strip()
                == single_retry_pending_id
            ],
            *[
                fact
                for fact in pending_queue
                if str(fact.get("id") or "").strip()
                != single_retry_pending_id
            ],
        ]

    system_prompt = build_l4_merge_system_prompt()
    runtime_context_window = 0
    context_window_resolver = getattr(
        service_client,
        "resolve_request_context_window",
        None,
    )
    if context_window_resolver is not None:
        try:
            runtime_context_window = _positive_int(
                await context_window_resolver(
                    force_refresh=True,
                )
            )
        except TypeError:
            # Compatibility with lightweight test doubles / older clients.
            runtime_context_window = _positive_int(
                await context_window_resolver()
            )
        except Exception:
            runtime_context_window = 0

    if not runtime_context_window:
        runtime_context_window = _positive_int(
            getattr(service_client, "configured_context_window", 0)
        ) or _positive_int(
            getattr(config, "SERVICE_CONTEXT_WINDOW", 0)
        ) or 4096

    refresh_l4_merge_context_window_state(
        context,
        runtime_context_window,
    )

    runtime_output_reserve = _positive_int(
        getattr(config, "RUNTIME_OUTPUT_TOKEN_RESERVE", 256)
    )
    protected_fact_ids = get_runtime_l4_explicit_edit_fact_ids(context)
    force_single_batch = bool(
        single_retry_pending_id
        or getattr(
            context,
            "runtime_l4_merge_force_single_batch_once",
            False,
        )
    )

    async def execute_double_batch_plan(double_plan: dict) -> dict:
        merge_mode = str(double_plan.get("mode") or "full")
        selected_pending = list(double_plan.get("pending_facts") or [])
        selected_pending_ids = list(double_plan.get("pending_ids") or [])
        plans = list(double_plan.get("plans") or [])
        existing_batches = list(
            double_plan.get("existing_fact_batches") or []
        )

        if merge_mode == "full":
            request_plan = plans[0]
            merge_user_prompt = request_plan["user_prompt"]
            merge_response = await ask_l4_model(
                context=context,
                service_client=service_client,
                label="L4 merge",
                system_prompt=system_prompt,
                user_prompt=merge_user_prompt,
                max_tokens=request_plan["requested_max_output_tokens"],
            )
            return {
                "response": merge_response,
                "batch_plan": {
                    **request_plan,
                    "remaining_pending_count": max(
                        0,
                        len(pending_queue) - len(selected_pending),
                    ),
                },
                "pending_facts": selected_pending,
                "pending_ids": selected_pending_ids,
                "merge_mode": merge_mode,
                "shard_scan": [],
                "shard_previous_facts": [],
                "shard_second_half": [],
                "shard_scan_recovery": {},
                "finalize_budget_trimmed": False,
            }

        first_half, second_half = existing_batches
        first_plan, second_plan = plans
        scan_system_prompt = build_l4_merge_shard_scan_system_prompt()
        scan_user_prompt = build_l4_merge_shard_scan_user_prompt(
            existing_facts=first_half,
            pending_facts=selected_pending,
            protected_fact_ids=protected_fact_ids,
        )
        scan_response = await ask_l4_model(
            context=context,
            service_client=service_client,
            label="L4 merge",
            system_prompt=scan_system_prompt,
            user_prompt=scan_user_prompt,
            max_tokens=first_plan["requested_max_output_tokens"],
        )
        if is_runtime_memory_response_truncated(scan_response):
            details = build_l4_truncation_details(
                scan_response,
                phase="merge",
                pending_count=len(selected_pending),
                pending_ids=selected_pending_ids,
            )
            details.update(
                record_l4_merge_truncation(
                    context,
                    batch_count=len(selected_pending),
                )
            )
            details["existing_batch_mode"] = "halves"
            details["shard"] = 1
            terminal = await log_l4_skip_event(
                context,
                phase="merge",
                message_phase="merge",
                reason="response_truncated",
                details=details,
            )
            return {"terminal": terminal}

        scan_payload = extract_l4_json_payload(
            extract_runtime_memory_text(scan_response)
        )
        visible_first_half_ids = [
            fact.get("id")
            for fact in first_half
            if isinstance(fact, dict)
        ]
        scan_inspection = inspect_l4_merge_shard_scan(
            scan_payload,
            pending_ids=selected_pending_ids,
            visible_fact_ids=visible_first_half_ids,
        )
        scan_results = list(scan_inspection["results"])
        shard_scan_recovery = {}
        initial_invalid_ids = list(scan_inspection["invalid_pending_ids"])

        if initial_invalid_ids:
            invalid_id_set = set(initial_invalid_ids)
            repair_pending = [
                fact
                for fact in selected_pending
                if str(fact.get("id") or "").strip() in invalid_id_set
            ]
            repair_context = {
                "validation_error": "invalid_shard_scan_items",
                "required_pending_ids": initial_invalid_ids,
                "pending_errors": scan_inspection["pending_errors"],
                "global_errors": scan_inspection["global_errors"],
                "previous_scan": (
                    scan_payload.get("scan", [])
                    if isinstance(scan_payload, dict)
                    else []
                ),
                "instruction": (
                    "Repair only the required pending_ids. Return exactly one "
                    "valid scan row for each required pending_id and no rows "
                    "for any other pending_id. Use only fact IDs visible in "
                    "this shard. Return corrected JSON only."
                ),
            }
            repair_prompt = build_l4_merge_shard_scan_user_prompt(
                existing_facts=first_half,
                pending_facts=repair_pending,
                protected_fact_ids=protected_fact_ids,
                repair_context=repair_context,
            )
            repair_response = await ask_l4_model(
                context=context,
                service_client=service_client,
                label="L4 merge",
                system_prompt=scan_system_prompt,
                user_prompt=repair_prompt,
                max_tokens=first_plan["requested_max_output_tokens"],
            )
            repair_error = ""
            if is_runtime_memory_response_truncated(repair_response):
                repair_inspection = {
                    "results": [],
                    "valid_pending_ids": [],
                    "invalid_pending_ids": initial_invalid_ids,
                    "pending_errors": {
                        pending_id: ["repair_response_truncated"]
                        for pending_id in initial_invalid_ids
                    },
                    "global_errors": ["repair_response_truncated"],
                }
                repair_error = "response_truncated"
            else:
                repair_payload = extract_l4_json_payload(
                    extract_runtime_memory_text(repair_response)
                )
                repair_inspection = inspect_l4_merge_shard_scan(
                    repair_payload,
                    pending_ids=initial_invalid_ids,
                    visible_fact_ids=visible_first_half_ids,
                )

            results_by_pending = {
                item["pending_id"]: item
                for item in [
                    *scan_results,
                    *repair_inspection["results"],
                ]
            }
            scan_results = [
                results_by_pending[pending_id]
                for pending_id in selected_pending_ids
                if pending_id in results_by_pending
            ]
            repaired_pending_ids = list(
                repair_inspection["valid_pending_ids"]
            )
            unrepaired_pending_ids = list(
                repair_inspection["invalid_pending_ids"]
            )
            shard_scan_recovery = {
                "repair_attempted": True,
                "initial_invalid_pending_ids": initial_invalid_ids,
                "initial_validation_errors": scan_inspection["pending_errors"],
                "initial_global_errors": scan_inspection["global_errors"],
                "repaired_pending_ids": repaired_pending_ids,
                "repair_validation_errors": repair_inspection["pending_errors"],
                "repair_global_errors": repair_inspection["global_errors"],
                **({"repair_error": repair_error} if repair_error else {}),
            }

            if unrepaired_pending_ids:
                isolation = record_l4_merge_shard_scan_failures(
                    context,
                    pending_ids=unrepaired_pending_ids,
                )
                shard_scan_recovery.update(isolation)

            if not scan_results:
                terminal = await log_l4_skip_event(
                    context,
                    phase="merge",
                    message_phase="merge",
                    reason="invalid_shard_scan",
                    details={
                        "pending_count": len(selected_pending),
                        "pending_ids": selected_pending_ids,
                        "existing_batch_mode": "halves",
                        "shard": 1,
                        **shard_scan_recovery,
                    },
                )
                return {"terminal": terminal}

        # The first pass returns only compact overlap evidence. Before the
        # second request, trim the pending prefix if that hand-off metadata
        # consumes the last bit of the live context budget. Extra first-pass
        # scan results are harmless and remain queued for the next idle tick.
        scan_valid_ids = {
            item.get("pending_id")
            for item in scan_results
            if item.get("pending_id")
        }
        final_pending = [
            fact
            for fact in selected_pending
            if str(fact.get("id") or "").strip() in scan_valid_ids
        ]
        scan_eligible_pending_count = len(final_pending)
        final_scan = list(scan_results)
        final_prompt = ""
        final_previous_facts = []
        minimum_finalize_required = 0
        while final_pending:
            final_ids = {
                str(fact.get("id") or "").strip()
                for fact in final_pending
            }
            final_scan = [
                item
                for item in scan_results
                if item.get("pending_id") in final_ids
            ]
            final_previous_facts = collect_l4_shard_scan_referenced_facts(
                first_half,
                final_scan,
            )
            final_prompt = build_l4_merge_shard_finalize_user_prompt(
                existing_facts=second_half,
                pending_facts=final_pending,
                previous_shard_scan=final_scan,
                previous_shard_facts=final_previous_facts,
                all_existing_facts=base_store.get("facts") or [],
                protected_fact_ids=protected_fact_ids,
            )
            minimum_finalize_required = (
                estimate_runtime_tokens(
                    system_prompt=system_prompt,
                    user_input=final_prompt,
                )
                + estimate_l4_merge_response_tokens(final_pending)
                + runtime_output_reserve
                + 128
            )
            if minimum_finalize_required <= runtime_context_window:
                break
            final_pending.pop()

        if not final_pending:
            terminal = await log_l4_context_paused(
                context,
                minimum_required=minimum_finalize_required,
                maximum_available=runtime_context_window,
                pending_count=len(pending_queue),
                existing_fact_count=len(base_store.get("facts") or []),
            )
            return {"terminal": terminal}

        final_pending_ids = [
            str(fact.get("id") or "").strip()
            for fact in final_pending
            if str(fact.get("id") or "").strip()
        ]
        merge_response = await ask_l4_model(
            context=context,
            service_client=service_client,
            label="L4 merge",
            system_prompt=system_prompt,
            user_prompt=final_prompt,
            max_tokens=second_plan["requested_max_output_tokens"],
        )
        return {
            "response": merge_response,
            "batch_plan": {
                **second_plan,
                "user_prompt": final_prompt,
                "pending_facts": final_pending,
                "pending_ids": final_pending_ids,
                "batch_count": len(final_pending),
                "remaining_pending_count": max(
                    0,
                    len(pending_queue) - len(final_pending),
                ),
            },
            "pending_facts": final_pending,
            "pending_ids": final_pending_ids,
            "merge_mode": merge_mode,
            "shard_scan": final_scan,
            "shard_previous_facts": final_previous_facts,
            "shard_second_half": second_half,
            "shard_scan_recovery": shard_scan_recovery,
            "finalize_budget_trimmed": (
                len(final_pending) < scan_eligible_pending_count
            ),
        }

    execution = None
    for provider_attempt in range(2):
        configured_batch_limit = _positive_int(
            getattr(
                context,
                "runtime_l4_merge_batch_limit",
                0,
            )
        )
        double_plan = build_l4_double_batch_plan(
            existing_facts=base_store.get("facts") or [],
            pending_facts=pending_queue,
            system_prompt=system_prompt,
            runtime_context_window=runtime_context_window,
            requested_max_tokens=None,
            runtime_output_reserve=runtime_output_reserve,
            protected_fact_ids=protected_fact_ids,
            max_batch_count=(
                1
                if force_single_batch
                else configured_batch_limit or None
            ),
        )
        if not double_plan.get("fits"):
            return await log_l4_context_paused(
                context,
                minimum_required=double_plan.get("minimum_required_tokens") or 1,
                maximum_available=runtime_context_window,
                pending_count=len(pending_queue),
                existing_fact_count=len(base_store.get("facts") or []),
            )

        context.runtime_l4_merge_paused_signature = ""
        context.runtime_l4_merge_existing_batch_mode = str(
            double_plan.get("mode") or "full"
        )

        planned_batch_count = int(double_plan.get("batch_count") or 0)
        if (
            configured_batch_limit
            and planned_batch_count
            and planned_batch_count < configured_batch_limit
            and double_plan.get("remaining_pending_count")
        ):
            # The local budget itself rejected the expansion target. Keep the
            # largest locally-fitting size instead of probing the same failure
            # on every idle tick.
            context.runtime_l4_merge_batch_limit = planned_batch_count
            context.runtime_l4_merge_batch_locked = True

        if force_single_batch:
            context.runtime_l4_merge_force_single_batch_once = False

        try:
            execution = await execute_double_batch_plan(double_plan)
            break
        except LMStudioAPIError:
            provider_context_window = _positive_int(
                getattr(
                    service_client,
                    "provider_context_window_ceiling",
                    0,
                )
            )
            if (
                provider_attempt
                or not provider_context_window
                or provider_context_window >= runtime_context_window
            ):
                raise

            runtime_context_window = provider_context_window
            refresh_l4_merge_context_window_state(
                context,
                runtime_context_window,
            )

    if execution is None:
        raise RuntimeError("L4 merge execution did not start")
    if execution.get("terminal") is not None:
        return execution["terminal"]

    response = execution["response"]
    batch_plan = execution["batch_plan"]
    pending_facts = execution["pending_facts"]
    pending_ids = execution["pending_ids"]
    merge_mode = execution["merge_mode"]
    shard_scan = execution["shard_scan"]
    shard_previous_facts = execution["shard_previous_facts"]
    shard_second_half = execution["shard_second_half"]
    shard_scan_recovery = execution.get("shard_scan_recovery") or {}
    finalize_budget_trimmed = bool(execution.get("finalize_budget_trimmed"))
    user_prompt = batch_plan["user_prompt"]
    if (
        finalize_budget_trimmed
        and planned_batch_count
        and len(pending_facts) < planned_batch_count
        and len(pending_queue) > len(pending_facts)
    ):
        context.runtime_l4_merge_batch_limit = len(pending_facts)
        context.runtime_l4_merge_batch_locked = True
    if is_runtime_memory_response_truncated(response):
        truncation_details = build_l4_truncation_details(
            response,
            phase="merge",
            pending_count=len(pending_facts),
            pending_ids=pending_ids,
        )
        truncation_details["existing_batch_mode"] = merge_mode
        if shard_scan_recovery:
            truncation_details["shard_scan_recovery"] = shard_scan_recovery
        truncation_details.update(
            record_l4_merge_truncation(
                context,
                batch_count=len(pending_facts),
            )
        )
        truncation_details["retry_behavior"] = (
            "JIN will retry later with the learned smaller FIFO batch; idle "
            "ticks during the backoff are ignored without starting another "
            "service request."
        )
        return await log_l4_skip_event(
            context,
            phase="merge",
            message_phase="merge",
            reason="response_truncated",
            details=truncation_details,
        )

    response_text = extract_runtime_memory_text(response)
    payload = extract_l4_json_payload(response_text)
    operations = []
    protected_pending_ids = []
    next_store = base_store
    merge_change = {
        "valid": False,
        "reason": "invalid_json",
        "changed": False,
    }

    if payload is not None:
        operations = normalize_l4_merge_operations(payload)
        operations, protected_pending_ids = protect_explicit_l4_edits_from_merge(
            operations,
            protected_fact_ids,
        )
        next_store, merge_change = apply_l4_merge_operations(
            base_store,
            operations,
            pending_ids=pending_ids,
        )

    initial_validation_reason = (
        merge_change.get("reason") or "invalid_operations"
    )
    repaired = False

    if not merge_change.get("valid"):
        feedback = build_l4_merge_validation_feedback(
            base_store,
            operations,
            initial_validation_reason,
        )
        repair_context = {
            "validation_error": initial_validation_reason,
            "feedback": feedback,
            "required_pending_ids": pending_ids,
            "previous_operations": (
                payload.get("operations", [])
                if isinstance(payload, dict)
                else []
            ),
            "instruction": (
                "Repair the previous result. Return corrected JSON only; "
                "do not repeat the invalid structure."
            ),
        }
        if merge_mode == "halves":
            repair_prompt = build_l4_merge_shard_finalize_user_prompt(
                existing_facts=shard_second_half,
                pending_facts=pending_facts,
                previous_shard_scan=shard_scan,
                previous_shard_facts=shard_previous_facts,
                all_existing_facts=base_store.get("facts") or [],
                protected_fact_ids=protected_fact_ids,
                repair_context=repair_context,
            )
        else:
            repair_prompt = build_l4_merge_user_prompt(
                existing_facts=base_store.get("facts") or [],
                pending_facts=pending_facts,
                protected_fact_ids=protected_fact_ids,
                repair_context=repair_context,
            )
        repair_response = await ask_l4_model(
            context=context,
            service_client=service_client,
            label="L4 merge",
            system_prompt=system_prompt,
            user_prompt=repair_prompt,
            max_tokens=batch_plan["requested_max_output_tokens"],
        )

        if is_runtime_memory_response_truncated(repair_response):
            recovery = record_l4_merge_validation_failure(
                context,
                pending_ids=pending_ids,
                batch_count=len(pending_facts),
            )
            details = {
                "pending_count": len(pending_facts),
                "pending_ids": pending_ids,
                "remaining_pending_count": batch_plan[
                    "remaining_pending_count"
                ],
                "repair_attempted": True,
                "initial_validation_error": initial_validation_reason,
                "repair_error": "response_truncated",
                "validation_feedback": feedback,
                **recovery,
            }
            return await log_l4_skip_event(
                context,
                phase="merge",
                message_phase="merge",
                reason="repair_response_truncated",
                details=details,
            )

        repair_payload = extract_l4_json_payload(
            extract_runtime_memory_text(repair_response)
        )
        repair_operations = []
        repair_protected_pending_ids = []
        if repair_payload is None:
            repair_change = {
                "valid": False,
                "reason": "invalid_json",
                "changed": False,
            }
            repair_next_store = base_store
        else:
            repair_operations = normalize_l4_merge_operations(repair_payload)
            (
                repair_operations,
                repair_protected_pending_ids,
            ) = protect_explicit_l4_edits_from_merge(
                repair_operations,
                protected_fact_ids,
            )
            repair_next_store, repair_change = apply_l4_merge_operations(
                base_store,
                repair_operations,
                pending_ids=pending_ids,
            )

        if not repair_change.get("valid"):
            repair_reason = repair_change.get("reason") or "invalid_operations"
            recovery = record_l4_merge_validation_failure(
                context,
                pending_ids=pending_ids,
                batch_count=len(pending_facts),
            )
            return await log_l4_skip_event(
                context,
                phase="merge",
                message_phase="merge",
                reason=repair_reason,
                details={
                    "pending_count": len(pending_facts),
                    "operations_count": len(repair_operations),
                    "pending_ids": pending_ids,
                    "remaining_pending_count": batch_plan[
                        "remaining_pending_count"
                    ],
                    "repair_attempted": True,
                    "initial_validation_error": initial_validation_reason,
                    "validation_feedback": feedback,
                    **recovery,
                },
            )

        operations = repair_operations
        protected_pending_ids = repair_protected_pending_ids
        next_store = repair_next_store
        merge_change = repair_change
        repaired = True

    if merge_change.get("valid") and protected_pending_ids:
        merge_change["protected_pending_ids"] = sorted(
            set(protected_pending_ids)
        )
    if repaired:
        merge_change["repaired"] = True
        merge_change["initial_validation_error"] = initial_validation_reason

    current_store = clone_l4_store(ensure_runtime_l4_state(context))
    if current_store != base_store:
        next_store, rebased_change = rebase_l4_merge_operations(
            base_store=base_store,
            current_store=current_store,
            operations=operations,
            pending_ids=pending_ids,
        )
        if not rebased_change.get("valid"):
            return await log_l4_skip_event(
                context,
                phase="merge",
                message_phase="merge",
                reason=rebased_change.get("reason") or "store_changed_rebase_conflict",
                details={
                    "base_revision": base_store.get("revision"),
                    "current_revision": current_store.get("revision"),
                    "pending_count": len(pending_facts),
                    "pending_ids": pending_ids,
                    **rebased_change,
                },
            )

        if repaired:
            rebased_change["repaired"] = True
            rebased_change["initial_validation_error"] = initial_validation_reason
        if protected_pending_ids:
            rebased_change["protected_pending_ids"] = sorted(
                set(protected_pending_ids)
            )
        merge_change = rebased_change

    if shard_scan_recovery:
        merge_change["shard_scan_recovery"] = shard_scan_recovery

    context.runtime_long_term_memory_store = next_store
    clear_l4_merge_pending_recovery(
        context,
        merge_change.get("processed_pending_ids", pending_ids),
    )
    batching_recovery = record_l4_merge_success(
        context,
        batch_count=len(pending_facts),
        remaining_pending_count=len(next_store.get("pending_facts") or []),
    )
    merge_change["batching"] = {
        "existing_batch_mode": merge_mode,
        **batching_recovery,
    }
    persist_runtime_l4_file_store(
        context,
        next_store,
    )

    delayed_memory_change = remap_delayed_memory_l4_fact_ids(
        context,
        removed_fact_ids=merge_change.get("removed_fact_ids", []),
        replacement_fact_ids=merge_change.get("replacement_fact_ids", []),
        replacement_fact_id_map=merge_change.get("replacement_fact_id_map", {}),
    )
    if delayed_memory_change.get("changed"):
        merge_change["delayed_memory_change"] = delayed_memory_change

    merge_details = format_l4_merge_operation_details(
        merge_change,
    )
    if merge_details:
        await log_memory_event(
            context,
            level=L4_LOG_LEVEL,
            message="L4 merge applied",
            details=merge_details,
            fallback_channel="summarizer",
            event="merge_applied",
        )
    await emit_l4_memory_update(context, change=merge_change)
    if delayed_memory_change.get("changed"):
        await emit_delayed_memory_reference_update(context)

    return {
        "phase": "merge",
        "status": "completed",
        "operations_count": len(operations),
        "batch_count": len(pending_facts),
        "remaining_pending_count": merge_change.get("pending_count", 0),
        "merge_change": merge_change,
    }


async def run_l4_jin_note(
    *,
    context,
    note: dict,
) -> dict:
    ensure_runtime_l4_state(context)

    if not l4_memory_enabled():
        return {
            "phase": "jin_note",
            "status": "skipped",
            "reason": "l4_memory_disabled",
        }

    service_client = getattr(context, "clients", {}).get("service")
    if service_client is None:
        return {
            "phase": "jin_note",
            "status": "skipped",
            "reason": "service_client_unavailable",
        }

    selected_fact_ids = normalize_long_term_fact_ids(
        note.get("fact_ids", []) if isinstance(note, dict) else []
    )
    message = " ".join(
        str(note.get("message", "") if isinstance(note, dict) else "").split()
    ).strip()
    requested_action = infer_l4_jin_note_action(
        selected_fact_ids=selected_fact_ids,
        message=message,
    )
    base_store = clone_l4_store(ensure_runtime_l4_state(context))
    existing_ids = {fact.get("id") for fact in base_store.get("facts", [])}

    if (
        not message
        or not requested_action
        or any(fact_id not in existing_ids for fact_id in selected_fact_ids)
    ):
        return await log_l4_skip_event(
            context,
            phase="jin_note",
            message_phase="JIN note",
            reason="invalid_or_stale_note",
            details={
                "selected_fact_ids": selected_fact_ids,
            },
        )

    selected_fact_id_set = set(selected_fact_ids)
    focused_existing_facts = [
        fact
        for fact in base_store.get("facts", []) or []
        if fact.get("id") in selected_fact_id_set
    ]
    system_prompt = build_l4_jin_note_system_prompt()
    user_prompt = build_l4_jin_note_user_prompt(
        existing_facts=focused_existing_facts,
        selected_fact_ids=selected_fact_ids,
        message=message,
        requested_action=requested_action,
    )
    response = await ask_l4_model(
        context=context,
        service_client=service_client,
        label="L4 JIN note",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=None,
    )

    if is_runtime_memory_response_truncated(response):
        return await log_l4_skip_event(
            context,
            phase="jin_note",
            message_phase="JIN note",
            reason="response_truncated",
            details={
                **build_l4_truncation_details(
                    response,
                    phase="jin_note",
                ),
                "selected_fact_ids": selected_fact_ids,
            },
        )

    payload = extract_l4_json_payload(
        extract_runtime_memory_text(
            response,
        )
    )
    if payload is None:
        return await log_l4_skip_event(
            context,
            phase="jin_note",
            message_phase="JIN note",
            reason="invalid_json",
            details={
                "selected_fact_ids": selected_fact_ids,
            },
        )

    current_store = clone_l4_store(ensure_runtime_l4_state(context))
    if current_store != base_store:
        return await log_l4_skip_event(
            context,
            phase="jin_note",
            message_phase="JIN note",
            reason="store_changed_during_jin_note",
            details={
                "selected_fact_ids": selected_fact_ids,
            },
        )

    next_store, change = apply_l4_jin_note_result(
        base_store,
        selected_fact_ids=selected_fact_ids,
        result=payload,
        expected_action=requested_action,
        allow_new_facts=l4_jin_note_requests_new_fact(message),
    )
    if not change.get("valid"):
        return await log_l4_skip_event(
            context,
            phase="jin_note",
            message_phase="JIN note",
            reason=change.get("reason") or "invalid_jin_note_result",
            details={
                "selected_fact_ids": selected_fact_ids,
            },
        )

    mark_runtime_l4_explicit_edit(
        context,
        [
            *selected_fact_ids,
            *(change.get("replacement_fact_ids", []) or []),
            *(change.get("added_ids", []) or []),
        ],
    )

    if not change.get("changed"):
        await log_memory_event(
            context,
            level=L4_LOG_LEVEL,
            message="L4 JIN note required no change",
            details=json.dumps(
                {
                    "selected_fact_ids": selected_fact_ids,
                    "message": message,
                },
                ensure_ascii=False,
                indent=2,
            ),
            fallback_channel="summarizer",
            event="jin_note_no_change",
        )
        return {
            "phase": "jin_note",
            "status": "completed",
            "changed": False,
            "change": change,
        }

    context.runtime_long_term_memory_store = next_store
    persist_runtime_l4_file_store(context, next_store)
    delayed_memory_change = remap_delayed_memory_l4_fact_ids(
        context,
        removed_fact_ids=change.get("removed_fact_ids", []),
        replacement_fact_ids=change.get("replacement_fact_ids", []),
        replacement_fact_id_map=change.get("replacement_fact_id_map", {}),
    )

    await log_memory_event(
        context,
        level=L4_LOG_LEVEL,
        message="L4 JIN note applied",
        details=json.dumps(
            {
                "message": message,
                "change": change,
                "delayed_memory_change": delayed_memory_change,
            },
            ensure_ascii=False,
            indent=2,
        ),
        fallback_channel="summarizer",
        event="jin_note_applied",
    )
    await emit_l4_memory_update(context, change=change)
    if delayed_memory_change.get("changed"):
        await emit_delayed_memory_reference_update(context)

    return {
        "phase": "jin_note",
        "status": "completed",
        "changed": True,
        "change": change,
        "delayed_memory_change": delayed_memory_change,
    }


async def maybe_update_runtime_l4_memory(
    *,
    context,
    user_idle_seconds: int | None = None,
) -> dict:
    try:
        ensure_runtime_l4_state(context)

        if not l4_memory_enabled():
            return {"status": "disabled"}

        if user_idle_seconds is not None:
            try:
                normalized_idle_seconds = int(float(user_idle_seconds))
            except (TypeError, ValueError):
                normalized_idle_seconds = 0
            if normalized_idle_seconds < get_l4_idle_seconds():
                return {"status": "skipped", "reason": "user_not_idle_enough"}

        service_client = getattr(context, "clients", {}).get("service")
        if service_client is None:
            return {"status": "skipped", "reason": "service_client_unavailable"}

        extraction_result = None
        pending_fields = collect_pending_facts_memory_fields(
            getattr(context, "runtime_facts_memory_records", [])
        )
        if pending_fields:
            extraction_result = await run_l4_extraction_phase(
                context=context,
                service_client=service_client,
                pending_fields=pending_fields,
            )
            if extraction_result.get("status") != "completed":
                return extraction_result

        if ensure_runtime_l4_state(context).get("pending_facts"):
            merge_result = await run_l4_merge_phase(
                context=context,
                service_client=service_client,
            )
            if extraction_result is not None:
                return {
                    **merge_result,
                    "extraction_result": extraction_result,
                }
            return merge_result

        if extraction_result is not None:
            return extraction_result

        reset_l4_merge_recovery_state(context)
        return {"status": "skipped", "reason": "nothing_pending"}

    except asyncio.CancelledError:
        raise
    except Exception as error:
        await log_memory_event(
            context,
            level=L4_LOG_LEVEL,
            message="L4 update failed",
            details=build_memory_failure_details(
                stage="L4 memory update",
                error=error,
                traceback_text=traceback.format_exc(),
            ),
            fallback_channel="error",
        )
        return {"status": "failed", "reason": type(error).__name__}
    finally:
        if getattr(context, "runtime_l4_memory_update_task", None) is asyncio.current_task():
            context.runtime_l4_memory_update_task = None
            if str(getattr(context, "runtime_l4_memory_update_kind", "") or "") == "idle":
                context.runtime_l4_memory_update_kind = ""


def schedule_l4_memory_idle_update(
    *,
    context,
    user_idle_seconds: int | None = None,
    minimum_interval_seconds: float | None = None,
) -> asyncio.Task | None:
    if bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    ):
        return None

    if not l4_memory_enabled():
        return None

    if user_idle_seconds is not None:
        try:
            normalized_idle_seconds = int(float(user_idle_seconds))
        except (TypeError, ValueError):
            normalized_idle_seconds = 0
        if normalized_idle_seconds < get_l4_idle_seconds():
            return None

    if runtime_l4_memory_update_running(context):
        return getattr(context, "runtime_l4_memory_update_task", None)

    if not l4_memory_has_pending_work(context):
        # An empty browser tick is only a poll. It must not consume the
        # configured cadence and delay work that appears a moment later.
        reset_l4_merge_recovery_state(context)
        return None

    now = time.monotonic()
    last_started_at = float(
        getattr(context, "runtime_l4_idle_last_started_at", 0.0) or 0.0
    )
    interval_seconds = (
        float(minimum_interval_seconds)
        if minimum_interval_seconds is not None
        else float(get_l4_idle_seconds())
    )
    if (
        last_started_at > 0
        and now - last_started_at < interval_seconds
    ):
        return None

    context.runtime_l4_idle_last_started_at = now
    task = asyncio.create_task(
        maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=user_idle_seconds,
        )
    )
    context.runtime_l4_memory_update_task = task
    context.runtime_l4_memory_update_kind = "idle"

    background_tasks = getattr(context, "background_tasks", None)
    if background_tasks is None:
        background_tasks = set()
        context.background_tasks = background_tasks
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


def _l4_server_contexts(app_state) -> list:
    store = getattr(
        app_state,
        "websocket_runtime_contexts",
        None,
    )
    if not isinstance(store, dict):
        return []
    return [
        context
        for context in store.values()
        if context is not None
    ]


def _l4_server_context(app_state):
    context = getattr(
        app_state,
        "l4_runtime_context",
        None,
    )
    if (
        context is not None
        and not bool(
            getattr(
                context,
                "runtime_persistent_writes_restricted",
                False,
            )
        )
    ):
        return context

    candidates = [
        candidate
        for candidate in _l4_server_contexts(app_state)
        if not bool(
            getattr(
                candidate,
                "runtime_persistent_writes_restricted",
                False,
            )
        )
    ]
    if not candidates:
        return None

    context = max(
        candidates,
        key=lambda candidate: float(
            getattr(candidate, "runtime_l4_profile_sync_at", 0.0)
            or 0.0
        ),
    )
    app_state.l4_runtime_context = context
    return context


def _l4_server_tabs_open(app_state) -> bool:
    connection_ids = getattr(
        app_state,
        "l4_open_websocket_ids",
        None,
    )
    return bool(connection_ids)


def _l4_server_foreground_busy(app_state) -> bool:
    for context in _l4_server_contexts(app_state):
        if bool(
            getattr(
                context,
                "runtime_foreground_turn_running",
                False,
            )
        ):
            return True

        queue = getattr(
            context,
            "runtime_pending_requests_queue",
            None,
        )
        if queue is not None:
            try:
                if not queue.empty():
                    return True
            except Exception:
                pass

    return False


async def _wait_for_l4_scheduler_wake(
    wake_event,
    *,
    timeout: float | None = None,
) -> None:
    if timeout is None:
        await wake_event.wait()
        return

    try:
        await asyncio.wait_for(
            wake_event.wait(),
            timeout=max(0.0, float(timeout)),
        )
    except asyncio.TimeoutError:
        pass


async def run_l4_memory_server_scheduler(app_state) -> None:
    wake_event = _l4_scheduler_wake_event(app_state)
    if wake_event is None:
        wake_event = asyncio.Event()
        app_state.l4_memory_scheduler_wake_event = wake_event

    while True:
        wake_event.clear()

        context = _l4_server_context(app_state)
        if context is None or not l4_memory_enabled():
            await _wait_for_l4_scheduler_wake(wake_event)
            continue

        if _l4_server_foreground_busy(app_state):
            await _wait_for_l4_scheduler_wake(
                wake_event,
                timeout=0.25,
            )
            continue

        if not l4_memory_has_pending_work(context):
            await _wait_for_l4_scheduler_wake(wake_event)
            continue

        tabs_open = _l4_server_tabs_open(app_state)
        interval_seconds = get_l4_scheduler_interval_seconds(
            tabs_open=tabs_open,
        )
        now = time.monotonic()
        last_user_activity_at = float(
            getattr(app_state, "l4_last_user_activity_at", 0.0)
            or 0.0
        )
        last_started_at = float(
            getattr(context, "runtime_l4_idle_last_started_at", 0.0)
            or 0.0
        )
        profile_sync_at = float(
            getattr(context, "runtime_l4_profile_sync_at", 0.0)
            or 0.0
        )
        cadence_anchor = max(
            last_user_activity_at,
            last_started_at,
            profile_sync_at,
        )
        remaining_seconds = (
            interval_seconds
            - max(0.0, now - cadence_anchor)
        )
        if remaining_seconds > 0:
            await _wait_for_l4_scheduler_wake(
                wake_event,
                timeout=remaining_seconds,
            )
            continue

        task = schedule_l4_memory_idle_update(
            context=context,
            minimum_interval_seconds=interval_seconds,
        )
        if task is None:
            await _wait_for_l4_scheduler_wake(
                wake_event,
                timeout=min(0.25, interval_seconds),
            )
            continue

        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            scheduler_task = asyncio.current_task()
            if (
                scheduler_task is not None
                and scheduler_task.cancelling()
            ):
                if not task.done():
                    task.cancel()
                raise
            if task.cancelled():
                continue
            raise


def start_l4_memory_server_scheduler(app_state) -> asyncio.Task:
    existing = getattr(
        app_state,
        "l4_memory_scheduler_task",
        None,
    )
    if existing is not None and not existing.done():
        return existing

    app_state.l4_open_websocket_ids = set()
    app_state.l4_facts_memory_records = []
    app_state.l4_last_user_activity_at = 0.0
    app_state.l4_memory_scheduler_wake_event = asyncio.Event()
    task = asyncio.create_task(
        run_l4_memory_server_scheduler(app_state)
    )
    app_state.l4_memory_scheduler_task = task
    return task


async def stop_l4_memory_server_scheduler(app_state) -> None:
    task = getattr(
        app_state,
        "l4_memory_scheduler_task",
        None,
    )
    if task is None:
        return

    task.cancel()
    with contextlib.suppress(
        asyncio.CancelledError,
        Exception,
    ):
        await task
    app_state.l4_memory_scheduler_task = None


def l4_fact_matches_archived_ids(
    fact: dict,
    archived_fact_ids: set[str],
) -> bool:

    if not archived_fact_ids:
        return False

    candidate_ids = [
        fact.get(
            "id",
            "",
        ),
        *(
            fact.get(
                "source_fact_ids",
                [],
            )
            if isinstance(
                fact.get(
                    "source_fact_ids",
                    [],
                ),
                list,
            )
            else []
        ),
    ]

    return any(
        str(
            candidate_id
            or ""
        ).strip().upper()
        in archived_fact_ids
        for candidate_id in candidate_ids
    )


def _get_l4_fact_anchor_report_ids(
    fact: dict,
    anchor_report_ids_by_fact_id: dict[str, list[str]],
) -> list[str]:
    candidate_ids = [
        fact.get("id", ""),
        *(
            fact.get("source_fact_ids", [])
            if isinstance(fact.get("source_fact_ids", []), list)
            else []
        ),
    ]
    report_ids = []

    for candidate_id in candidate_ids:
        fact_id = str(candidate_id or "").strip().upper()
        for report_id in anchor_report_ids_by_fact_id.get(fact_id, []):
            if report_id not in report_ids:
                report_ids.append(report_id)

    return report_ids


def build_runtime_l4_memory_context(*, context, fact_ids=None, user_input: str = "") -> str:
    if not l4_memory_enabled():
        return ""

    store = ensure_runtime_l4_state(context)
    archived_fact_ids = refresh_runtime_l4_archived_fact_ids(
        context
    )
    reports = getattr(context, "delayed_memory_reports", {})
    anchor_report_ids_by_fact_id = collect_anchor_fact_report_ids(
        reports
    )
    loaded_report_ids_by_fact_id = (
        collect_loaded_delayed_memory_fact_report_ids(
            context
        )
    )
    report_ids_by_fact_id = merge_l4_fact_report_id_maps(
        anchor_report_ids_by_fact_id,
        loaded_report_ids_by_fact_id,
    )
    requested_fact_ids = None
    if fact_ids is not None:
        requested_fact_ids = {
            str(fact_id or "").strip().upper()
            for fact_id in fact_ids
            if str(fact_id or "").strip()
        }

    active_facts = [
        fact
        for fact in store.get("facts") or []
        if not l4_fact_matches_archived_ids(
            fact,
            archived_fact_ids,
        )
        and (
            requested_fact_ids is None
            or str(fact.get("id", "") or "").strip().upper()
            in requested_fact_ids
        )
    ]

    # L4 prompt order stays independent from panel/avatar order. Fresh facts
    # are nearest to the model by default; memory attention may bubble a
    # narrow 1..3-fact relevance cone for this prompt only.
    try:
        from runtime.memory_attention import rank_l4_facts_for_context

        active_facts = rank_l4_facts_for_context(
            active_facts,
            context=context,
            user_input=user_input,
        )
    except Exception:
        def _fact_sort_key(fact):
            match = re.fullmatch(
                r"F([1-9]\d*)",
                str((fact or {}).get("id", "") or "").strip(),
                flags=re.IGNORECASE,
            )
            if match:
                return (0, -int(match.group(1)), "")
            return (
                1,
                0,
                str((fact or {}).get("id", "") or "").strip().casefold(),
            )

        active_facts = sorted(active_facts, key=_fact_sort_key)

    delayed_memory_ids_by_fact_id = {}

    for fact in active_facts:
        fact_id = str(fact.get("id", "") or "").strip().upper()
        if not fact_id:
            continue
        report_ids = _get_l4_fact_anchor_report_ids(
            fact,
            report_ids_by_fact_id,
        )
        if report_ids:
            delayed_memory_ids_by_fact_id[fact_id] = report_ids

    return format_long_term_memory_context(
        active_facts,
        delayed_memory_ids_by_fact_id=delayed_memory_ids_by_fact_id,
    )


async def delete_l4_memory_fact(context, fact_id: str) -> bool:
    current_store = ensure_runtime_l4_state(context)
    target_id = str(fact_id or "").strip()
    deleted_fact = next(
        (
            dict(fact)
            for fact in current_store.get("facts") or []
            if str(fact.get("id") or "").strip() == target_id
        ),
        None,
    )
    store, changed = delete_l4_fact_from_store(
        current_store,
        target_id,
    )
    if not changed or deleted_fact is None:
        return False

    context.runtime_long_term_memory_store = store
    persist_runtime_l4_file_store(
        context,
        store,
    )
    delayed_memory_change = remap_delayed_memory_l4_fact_ids(
        context,
        removed_fact_ids=[target_id],
        replacement_fact_ids=[],
    )
    restore_meta = build_l4_deleted_fact_restore_meta(
        delayed_memory_change
    )
    deleted_fact_for_restore = (
        {
            **deleted_fact,
            "_restore_meta": restore_meta,
        }
        if restore_meta
        else deleted_fact
    )
    await log_memory_event(
        context,
        level=L4_LOG_LEVEL,
        message="L4 fact deleted",
        details=json.dumps(
            {
                "fact": deleted_fact_for_restore,
                "delayed_memory_change": delayed_memory_change,
                "revision": store.get("revision"),
                "total_facts": len(store.get("facts") or []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        event="fact_deleted",
        tag_suffix="DELETED",
        deleted_fact=deleted_fact_for_restore,
    )
    await emit_l4_memory_update(
        context,
        change={"removed_ids": [target_id], "changed": True},
    )
    if delayed_memory_change.get("changed"):
        await emit_delayed_memory_reference_update(context)
    return True


async def restore_l4_memory_fact(context, fact) -> bool:
    restore_meta = (
        fact.get("_restore_meta", {})
        if isinstance(fact, dict)
        else {}
    )
    store, changed = restore_l4_fact_to_store(
        ensure_runtime_l4_state(context),
        fact,
    )
    if not changed:
        return False

    restored_fact = next(
        (
            dict(item)
            for item in store.get("facts") or []
            if str(item.get("id") or "").strip()
            == str((fact or {}).get("id") or "").strip()
        ),
        None,
    )
    if restored_fact is None:
        return False

    context.runtime_long_term_memory_store = store
    persist_runtime_l4_file_store(
        context,
        store,
    )
    delayed_memory_change = restore_delayed_memory_l4_fact_refs(
        context,
        fact_id=restored_fact["id"],
        restore_meta=restore_meta,
    )
    await emit_l4_memory_update(
        context,
        change={
            "restored_ids": [restored_fact["id"]],
            "changed": True,
            "delayed_memory_report_ids": (
                delayed_memory_change.get("report_ids", [])
            ),
        },
    )
    if delayed_memory_change.get("changed"):
        await emit_delayed_memory_reference_update(context)
    return True
