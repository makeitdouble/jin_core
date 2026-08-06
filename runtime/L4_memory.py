from __future__ import annotations

import asyncio
import json
import traceback

from clients.service_client import ask_service_model
from config_loader import config
from runtime.L4_memory_utils import (
    add_l4_pending_candidates,
    apply_l4_jin_note_result,
    apply_l4_merge_operations,
    build_l4_extraction_system_prompt,
    build_l4_extraction_user_prompt,
    build_l4_jin_note_system_prompt,
    build_l4_jin_note_user_prompt,
    build_l4_merge_system_prompt,
    build_l4_merge_user_prompt,
    clone_l4_store,
    collect_pending_facts_memory_fields,
    delete_l4_fact_from_store,
    extract_l4_json_payload,
    format_l4_merge_operation_details,
    format_long_term_memory_context,
    mark_facts_memory_fields_analyzed,
    merge_l4_store_snapshots,
    normalize_facts_memory_records,
    normalize_l4_candidates,
    normalize_l4_merge_operations,
    normalize_l4_store,
    restore_l4_fact_to_store,
)
from utils.actions.save_delayed_memory_utils import (
    collect_long_term_fact_ids_from_reports,
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


def refresh_runtime_l4_archived_fact_ids(
    context,
) -> set[str]:

    fact_ids = collect_long_term_fact_ids_from_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
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
) -> dict:
    removed_ids = set(normalize_long_term_fact_ids(removed_fact_ids))
    replacement_ids = normalize_long_term_fact_ids(replacement_fact_ids)

    if not removed_ids:
        return {
            "changed": False,
            "report_ids": [],
            "file_errors": [],
        }

    reports = getattr(context, "delayed_memory_reports", None)
    if not isinstance(reports, dict):
        return {
            "changed": False,
            "report_ids": [],
            "file_errors": [],
        }

    from utils.brain_client_utils import get_appended_delayed_memory_report

    appended_reports = get_appended_delayed_memory_report(context)
    changed_reports = {}

    for report_id, report in list(reports.items()):
        if not isinstance(report, dict):
            continue

        current_ids = normalize_long_term_fact_ids(
            report.get("long_term_facts_ids", [])
        )
        if not any(fact_id in removed_ids for fact_id in current_ids):
            continue

        next_ids = normalize_long_term_fact_ids([
            *(fact_id for fact_id in current_ids if fact_id not in removed_ids),
            *replacement_ids,
        ])
        updated_report = {
            **report,
            "long_term_facts_ids": next_ids,
        }
        reports[report_id] = updated_report
        changed_reports[report_id] = updated_report

        if report_id in appended_reports:
            appended_reports[report_id] = {
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

    await log_memory_event(
        context,
        level=L4_LOG_LEVEL,
        message=f"L4 {message_phase} skipped: {reason}",
        details=json.dumps(
            result,
            ensure_ascii=False,
            indent=2,
        ),
        fallback_channel="summarizer",
        event=f"{phase}_skipped",
    )

    return result


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
        return await log_l4_skip_event(
            context,
            phase="extract",
            message_phase="extraction",
            reason="response_truncated",
            details={
                "selected_fields_count": len(pending_fields),
            },
        )

    payload = extract_l4_json_payload(extract_runtime_memory_text(response))
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
        return await log_l4_skip_event(
            context,
            phase="merge",
            message_phase="merge",
            reason="response_truncated",
            details={
                "pending_count": len(pending_facts),
                "pending_ids": [
                    fact.get("id")
                    for fact in pending_facts
                    if fact.get("id")
                ],
            },
        )

    payload = extract_l4_json_payload(extract_runtime_memory_text(response))
    if payload is None:
        return await log_l4_skip_event(
            context,
            phase="merge",
            message_phase="merge",
            reason="invalid_json",
            details={
                "pending_count": len(pending_facts),
                "pending_ids": [
                    fact.get("id")
                    for fact in pending_facts
                    if fact.get("id")
                ],
            },
        )

    current_store = clone_l4_store(ensure_runtime_l4_state(context))
    if current_store != base_store:
        return await log_l4_skip_event(
            context,
            phase="merge",
            message_phase="merge",
            reason="store_changed_during_merge",
            details={
                "base_revision": base_store.get("revision"),
                "current_revision": current_store.get("revision"),
                "pending_count": len(pending_facts),
                "pending_ids": [
                    fact.get("id")
                    for fact in pending_facts
                    if fact.get("id")
                ],
            },
        )

    operations = normalize_l4_merge_operations(payload)
    next_store, merge_change = apply_l4_merge_operations(base_store, operations)
    if not merge_change.get("valid"):
        return await log_l4_skip_event(
            context,
            phase="merge",
            message_phase="merge",
            reason=merge_change.get("reason") or "invalid_operations",
            details={
                "pending_count": len(pending_facts),
                "operations_count": len(operations),
                "pending_ids": [
                    fact.get("id")
                    for fact in pending_facts
                    if fact.get("id")
                ],
            },
        )

    context.runtime_long_term_memory_store = next_store
    persist_runtime_l4_file_store(
        context,
        next_store,
    )
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

    return {
        "phase": "merge",
        "status": "completed",
        "operations_count": len(operations),
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
    base_store = clone_l4_store(ensure_runtime_l4_state(context))
    existing_ids = {fact.get("id") for fact in base_store.get("facts", [])}

    if (
        not selected_fact_ids
        or not message
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

    system_prompt = build_l4_jin_note_system_prompt()
    user_prompt = build_l4_jin_note_user_prompt(
        existing_facts=base_store.get("facts") or [],
        selected_fact_ids=selected_fact_ids,
        message=message,
    )
    response = await ask_l4_model(
        context=context,
        service_client=service_client,
        label="L4 JIN note",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        max_tokens=int(getattr(config, "SERVICE_MAX_TOKENS", 4096) or 4096),
    )

    if is_runtime_memory_response_truncated(response):
        return await log_l4_skip_event(
            context,
            phase="jin_note",
            message_phase="JIN note",
            reason="response_truncated",
            details={
                "selected_fact_ids": selected_fact_ids,
            },
        )

    payload = extract_l4_json_payload(extract_runtime_memory_text(response))
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

    if runtime_l4_memory_update_running(context):
        return getattr(context, "runtime_l4_memory_update_task", None)

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
        ).strip().casefold()
        in archived_fact_ids
        for candidate_id in candidate_ids
    )


def build_runtime_l4_memory_context(*, context) -> str:
    if not l4_memory_enabled():
        return ""

    store = ensure_runtime_l4_state(context)
    archived_fact_ids = refresh_runtime_l4_archived_fact_ids(
        context
    )
    active_facts = [
        fact
        for fact in store.get("facts") or []
        if not l4_fact_matches_archived_ids(
            fact,
            archived_fact_ids,
        )
    ]
    return format_long_term_memory_context(
        active_facts
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
    await log_memory_event(
        context,
        level=L4_LOG_LEVEL,
        message="L4 fact deleted",
        details=json.dumps(
            {
                "fact": deleted_fact,
                "revision": store.get("revision"),
                "total_facts": len(store.get("facts") or []),
            },
            ensure_ascii=False,
            indent=2,
        ),
        event="fact_deleted",
        tag_suffix="DELETED",
        deleted_fact=deleted_fact,
    )
    await emit_l4_memory_update(
        context,
        change={"removed_ids": [target_id], "changed": True},
    )
    return True


async def restore_l4_memory_fact(context, fact) -> bool:
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
    await emit_l4_memory_update(
        context,
        change={
            "restored_ids": [restored_fact["id"]],
            "changed": True,
        },
    )
    return True
