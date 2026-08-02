from __future__ import annotations

import asyncio
import json
import traceback

from clients.service_client import ask_service_model
from config_loader import config
from runtime.L4_memory_utils import (
    add_l4_pending_candidates,
    apply_l4_merge_operations,
    build_l4_extraction_system_prompt,
    build_l4_extraction_user_prompt,
    build_l4_merge_system_prompt,
    build_l4_merge_user_prompt,
    clone_l4_store,
    collect_pending_facts_memory_fields,
    delete_l4_fact_from_store,
    extract_l4_json_payload,
    format_long_term_memory_context,
    mark_facts_memory_fields_analyzed,
    normalize_facts_memory_records,
    normalize_l4_candidates,
    normalize_l4_merge_operations,
    normalize_l4_store,
)
from runtime.memory_common import (
    build_memory_failure_details,
    build_runtime_summarizer_payload,
    extract_runtime_memory_text,
    is_runtime_memory_response_truncated,
    log_memory_event,
    log_runtime_summarizer_payload,
    log_runtime_summarizer_result,
    refresh_runtime_memory_summarizer_usage,
    safe_call,
)


L4_LOG_LEVEL = "L4"
L4_DEFAULT_IDLE_SECONDS = 60


def l4_memory_enabled() -> bool:
    return bool(getattr(config, "L4_MEMORY_ENABLED", True))


def get_l4_idle_seconds() -> int:
    return int(
        getattr(config, "L4_IDLE_SECONDS", L4_DEFAULT_IDLE_SECONDS)
        or L4_DEFAULT_IDLE_SECONDS
    )


def ensure_runtime_l4_state(context) -> dict:
    context.runtime_facts_memory_records = normalize_facts_memory_records(
        getattr(context, "runtime_facts_memory_records", [])
    )
    context.runtime_long_term_memory_store = normalize_l4_store(
        getattr(context, "runtime_long_term_memory_store", None)
    )
    return context.runtime_long_term_memory_store


def apply_facts_memory_store_sync(context, raw_records) -> dict:
    records = normalize_facts_memory_records(raw_records)
    context.runtime_facts_memory_records = records
    return {
        "records_count": len(records),
        "signals_count": sum(int(record.get("signal_count") or 0) for record in records),
        "pending_count": len(collect_pending_facts_memory_fields(records)),
    }


def apply_l4_memory_store_sync(context, raw_store) -> bool:
    incoming = normalize_l4_store(raw_store)
    current = ensure_runtime_l4_state(context)
    incoming_revision = int(incoming.get("revision") or 0)
    current_revision = int(current.get("revision") or 0)
    current_has_data = bool(current.get("facts") or current.get("pending_facts"))

    if incoming_revision < current_revision:
        return False
    if current_has_data and incoming_revision == current_revision and incoming != current:
        return False

    context.runtime_long_term_memory_store = incoming
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


async def ask_l4_model(
    *,
    context,
    service_client,
    label: str,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
) -> dict:
    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )
    await log_runtime_summarizer_payload(
        context,
        label=label,
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=getattr(config, "SERVICE_TEMPERATURE", 0.1),
            max_tokens=max_tokens,
        ),
    )

    response = await ask_service_model(
        client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=getattr(config, "SERVICE_TEMPERATURE", 0.1),
        max_tokens=max_tokens,
        timeout=getattr(config, "SERVICE_REQUEST_TIMEOUT", 1000.0),
    )
    response_text = extract_runtime_memory_text(response)

    await log_runtime_summarizer_result(
        context,
        label=label,
        result=response_text,
    )
    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response=response,
    )
    return response


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
        max_tokens=int(getattr(config, "SERVICE_MAX_TOKENS", 4096) or 4096),
    )

    if is_runtime_memory_response_truncated(response):
        return {"phase": "extract", "status": "skipped", "reason": "response_truncated"}

    payload = extract_l4_json_payload(extract_runtime_memory_text(response))
    if payload is None:
        return {"phase": "extract", "status": "skipped", "reason": "invalid_json"}

    raw_candidates = payload.get("facts")
    if not isinstance(raw_candidates, list):
        return {"phase": "extract", "status": "skipped", "reason": "invalid_facts_payload"}

    candidates = normalize_l4_candidates(
        payload,
        source_fields=pending_fields,
    )
    if len(candidates) != len(raw_candidates):
        return {"phase": "extract", "status": "skipped", "reason": "invalid_candidates"}
    store, pending_change = add_l4_pending_candidates(
        ensure_runtime_l4_state(context),
        candidates,
    )
    context.runtime_long_term_memory_store = store

    records, records_changed = mark_facts_memory_fields_analyzed(
        getattr(context, "runtime_facts_memory_records", []),
        pending_fields,
    )
    context.runtime_facts_memory_records = records

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


async def run_l4_merge_phase(*, context, service_client) -> dict:
    base_store = clone_l4_store(ensure_runtime_l4_state(context))
    pending_facts = list(base_store.get("pending_facts") or [])
    if not pending_facts:
        return {"phase": "merge", "status": "skipped", "reason": "no_pending_long_term_facts"}

    system_prompt = build_l4_merge_system_prompt()
    user_prompt = build_l4_merge_user_prompt(
        existing_facts=base_store.get("facts") or [],
        pending_facts=pending_facts,
    )
    response = await ask_l4_model(
        context=context,
        service_client=service_client,
        label="L4 merge",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=int(getattr(config, "SERVICE_MAX_TOKENS", 4096) or 4096),
    )

    if is_runtime_memory_response_truncated(response):
        return {"phase": "merge", "status": "skipped", "reason": "response_truncated"}

    payload = extract_l4_json_payload(extract_runtime_memory_text(response))
    if payload is None:
        return {"phase": "merge", "status": "skipped", "reason": "invalid_json"}

    current_store = clone_l4_store(ensure_runtime_l4_state(context))
    if current_store != base_store:
        return {"phase": "merge", "status": "skipped", "reason": "store_changed_during_merge"}

    operations = normalize_l4_merge_operations(payload)
    next_store, merge_change = apply_l4_merge_operations(base_store, operations)
    if not merge_change.get("valid"):
        return {
            "phase": "merge",
            "status": "skipped",
            "reason": merge_change.get("reason") or "invalid_operations",
        }

    context.runtime_long_term_memory_store = next_store
    await emit_l4_memory_update(context, change=merge_change)

    return {
        "phase": "merge",
        "status": "completed",
        "operations_count": len(operations),
        "merge_change": merge_change,
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

        pending_fields = collect_pending_facts_memory_fields(
            getattr(context, "runtime_facts_memory_records", [])
        )
        if pending_fields:
            return await run_l4_extraction_phase(
                context=context,
                service_client=service_client,
                pending_fields=pending_fields,
            )

        if ensure_runtime_l4_state(context).get("pending_facts"):
            return await run_l4_merge_phase(
                context=context,
                service_client=service_client,
            )

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


def schedule_l4_memory_idle_update(
    *,
    context,
    user_idle_seconds: int | None = None,
) -> asyncio.Task | None:
    if not l4_memory_enabled():
        return None

    previous_task = getattr(context, "runtime_l4_memory_update_task", None)
    if previous_task is not None and not previous_task.done():
        return previous_task

    task = asyncio.create_task(
        maybe_update_runtime_l4_memory(
            context=context,
            user_idle_seconds=user_idle_seconds,
        )
    )
    context.runtime_l4_memory_update_task = task

    background_tasks = getattr(context, "background_tasks", None)
    if background_tasks is None:
        background_tasks = set()
        context.background_tasks = background_tasks
    background_tasks.add(task)
    task.add_done_callback(background_tasks.discard)
    return task


def build_runtime_l4_memory_context(*, context) -> str:
    if not l4_memory_enabled():
        return ""
    store = ensure_runtime_l4_state(context)
    return format_long_term_memory_context(store.get("facts") or [])


async def delete_l4_memory_fact(context, fact_id: str) -> bool:
    store, changed = delete_l4_fact_from_store(
        ensure_runtime_l4_state(context),
        fact_id,
    )
    if not changed:
        return False

    context.runtime_long_term_memory_store = store
    await log_memory_event(
        context,
        level=L4_LOG_LEVEL,
        message="L4 fact deleted",
        details=json.dumps(
            {
                "fact_id": fact_id,
                "revision": store.get("revision"),
                "total_facts": len(store.get("facts") or []),
            },
            ensure_ascii=False,
            indent=2,
        ),
    )
    await emit_l4_memory_update(
        context,
        change={"removed_ids": [fact_id], "changed": True},
    )
    return True
