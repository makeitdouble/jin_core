from contracts.rules_assembler import (
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from .active_memory_utils import (
    collect_active_memory_slot_ids,
    extract_active_memory_creation_custom_fields,
    get_active_memory_record_title,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    record_runtime_tool_result,
)


async def emit_rejected_active_memory_results(
    context,
    rejected_active_memory_results,
    *,
    with_action_context,
):
    if not rejected_active_memory_results:
        return

    from utils.brain_client_utils import queue_active_memory_resolve_failure

    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )

    for result in rejected_active_memory_results:
        queue_active_memory_resolve_failure(
            context,
            result,
        )

        if emit is None:
            continue

        await emit(with_action_context({
            "type": "runtime_action",
            "action": "resolve_active_memory",
            "id": result.get(
                "id",
                "",
            ),
            "status": "failed",
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
            ),
            "text": "Active memory resolve failed",
            "active_memory_result": result,
        }))


async def apply_save_active_memory_actions(
    context,
    save_active_memory_actions,
    *,
    log_runtime,
    with_action_context,
    action_display_ids=None,
):
    from utils.brain_client_utils import (
        save_active_memory_runtime_record,
        normalize_active_memory_runtime_payload,
    )

    saved_active_memory_texts = []
    save_active_memory_results = []
    resolved_action_display_ids = (
        action_display_ids
        if isinstance(
            action_display_ids,
            dict,
        )
        else {}
    )

    if not save_active_memory_actions:
        return saved_active_memory_texts

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] save_active_memory requested"
        )

    for action in save_active_memory_actions:
        if not action.payload:
            continue

        active_memory_text = normalize_active_memory_runtime_payload(
            action.payload
        )
        if not active_memory_text:
            continue

        action_display_id = str(
            resolved_action_display_ids.get(
                id(action),
                "",
            )
            or ""
        ).strip()

        records_before = list(
            getattr(
                context,
                "active_memory_records",
                [],
            )
            or []
        )
        record_saved = (
            await save_active_memory_runtime_record(
                context,
                active_memory_text,
            )
        )
        records_after = list(
            getattr(
                context,
                "active_memory_records",
                [],
            )
            or []
        )
        active_memory_line = (
            records_after[-1]
            if (
                record_saved
                and len(records_after) > len(records_before)
            )
            else ""
        )

        visible_active_memory_text, _ = (
            extract_active_memory_creation_custom_fields(
                active_memory_text
            )
        )
        if active_memory_line:
            visible_active_memory_text = (
                get_active_memory_record_title(
                    active_memory_line
                )
            )

        save_active_memory_results.append(
            (
                visible_active_memory_text,
                active_memory_line,
                action_display_id,
            )
        )

        if record_saved:
            saved_active_memory_texts.append(
                visible_active_memory_text
            )
            record_runtime_tool_result(
                context,
                TOOL_RESULT_KIND_ACTIVE_MEMORY,
                {
                    "ok": True,
                    "action": "save_active_memory",
                    "destination": (
                        "active_memory_records -> <ACTIVE_MEMORY>"
                    ),
                    "content": visible_active_memory_text,
                    "record": active_memory_line,
                },
            )

        if (
            log_runtime is not None
            and record_saved
        ):
            await log_runtime(
                "[RUNTIME ACTION] active_memory record saved"
            )

    if saved_active_memory_texts:
        # Tells schedule_runtime_memory_update() that this turn is
        # meaningful for L1 even if the visible assistant text ends up
        # empty (e.g. the model was instructed to only emit the
        # marker and say nothing else).
        context.runtime_active_memory_saved_this_turn = True

    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )

    if emit is not None:
        for (
            active_memory_text,
            active_memory_line,
            action_display_id,
        ) in save_active_memory_results:
            display_name = get_runtime_action_display_name(
                RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
            )
            active_memory_ids = collect_active_memory_slot_ids(
                active_memory_line
            )
            active_memory_id = (
                sorted(active_memory_ids)[0]
                if active_memory_ids
                else ""
            )
            event = {
                "type": "runtime_action",
                "action": "save_active_memory",
                "display_name": display_name,
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
                    active_memory_text,
                ),
                "payload": active_memory_text,
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
                ),
            }

            if action_display_id:
                event["id"] = action_display_id

            if active_memory_id:
                event["active_memory_id"] = active_memory_id

            if active_memory_line:
                event["active_memory"] = active_memory_line

            await emit(with_action_context(
                event
            ))
            completed_event = {
                "type": "runtime_action",
                "action": "save_active_memory",
                "status": "completed",
                "display_name": display_name,
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
                ),
            }

            if action_display_id:
                completed_event["id"] = action_display_id

            if active_memory_id:
                completed_event["active_memory_id"] = active_memory_id

            await emit(with_action_context(
                completed_event
            ))

    return saved_active_memory_texts


async def apply_update_active_memory_actions(
    context,
    update_active_memory_actions,
    *,
    log_runtime,
    with_action_context,
):
    from utils.brain_client_utils import update_active_memory_runtime_record

    applied_count = 0

    if not update_active_memory_actions:
        return applied_count

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] update_active_memory requested"
        )

    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )

    for action in update_active_memory_actions:
        result = await update_active_memory_runtime_record(
            context,
            action.payload,
        )
        record_runtime_tool_result(
            context,
            TOOL_RESULT_KIND_ACTIVE_MEMORY,
            result,
        )

        if result.get("ok"):
            applied_count += 1
            context.runtime_active_memory_saved_this_turn = True

            if log_runtime is not None:
                await log_runtime(
                    "[RUNTIME ACTION] active_memory record updated"
                )

        if emit is None:
            continue

        display_name = get_runtime_action_display_name(
            RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY
        )
        event = {
            "type": "runtime_action",
            "action": "update_active_memory",
            "status": "completed" if result.get("ok") else "failed",
            "display_name": display_name,
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY
            ),
            "text": (
                f"{display_name}: {result.get('title', 'Active memory')}"
                if result.get("ok")
                else f"{display_name}: failed"
            ),
            "active_memory_result": result,
            "active_memory_id": result.get("id", ""),
            "active_memory_title": result.get("title", ""),
            "active_memory_changes": result.get("changes", []),
        }

        if result.get("record"):
            event["active_memory"] = result["record"]

        await emit(with_action_context(event))

    return applied_count


async def apply_resolve_active_memory_actions(
    context,
    resolve_active_memory_actions,
    *,
    log_runtime,
    with_action_context,
):
    from utils.brain_client_utils import (
        build_active_memory_resolve_failure_result,
        normalize_active_memory_content_for_duplicate_check,
        queue_active_memory_resolve_failure,
        resolve_active_memory_runtime_record,
    )

    resolved_active_memory_count = 0

    if not resolve_active_memory_actions:
        return resolved_active_memory_count

    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )

    for action in resolve_active_memory_actions:
        (
            record_resolved,
            active_memory_id,
            resolved_record,
        ) = (
            await resolve_active_memory_runtime_record(
                context,
                action.payload,
            )
        )

        if not record_resolved:
            failure_result = build_active_memory_resolve_failure_result(
                context,
                action.payload,
                error="active_memory_not_resolved",
            )
            if active_memory_id:
                failure_result["id"] = active_memory_id
            failure_result["detail"] = (
                "Active memory was not resolved. The record may be paused "
                "or may no longer exist. Do not claim that the action "
                "completed."
            )
            queue_active_memory_resolve_failure(
                context,
                failure_result,
            )

            if emit is not None:
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "resolve_active_memory",
                    "id": active_memory_id,
                    "status": "failed",
                    "display_name": get_runtime_action_display_name(
                        RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
                    ),
                    "close_tag": runtime_action_has_close_tag(
                        RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
                    ),
                    "text": "Active memory resolve failed",
                    "active_memory_result": failure_result,
                }))
            continue

        resolved_active_memory_count += 1
        record_runtime_tool_result(
            context,
            TOOL_RESULT_KIND_ACTIVE_MEMORY,
            {
                "ok": True,
                "action": "resolve_active_memory",
                "destination": (
                    "active_memory_records -> <ACTIVE_MEMORY> "
                    "(resolved and removed)"
                ),
                "id": active_memory_id,
                "content": (
                    normalize_active_memory_content_for_duplicate_check(
                        resolved_record
                    )
                ),
                "record": resolved_record,
            },
        )

        if emit is None:
            continue

        await emit(with_action_context({
            "type": "runtime_action",
            "action": "resolve_active_memory",
            "id": active_memory_id,
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
            ),
            "text": "Active memory resolved",
            "payload": active_memory_id,
            "detail": (
                f"id: {active_memory_id}; "
                "content: "
                + normalize_active_memory_content_for_duplicate_check(
                    resolved_record
                )
            ),
        }))
        await emit(with_action_context({
            "type": "runtime_action",
            "action": "resolve_active_memory",
            "id": active_memory_id,
            "status": "completed",
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
            ),
            "payload": active_memory_id,
            "detail": (
                f"id: {active_memory_id}; "
                "content: "
                + normalize_active_memory_content_for_duplicate_check(
                    resolved_record
                )
            ),
        }))

    if resolved_active_memory_count:
        context.runtime_active_memory_records_dirty = True

    return resolved_active_memory_count
