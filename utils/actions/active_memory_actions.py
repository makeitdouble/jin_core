from contracts.rules_assembler import (
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
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
from .update_active_memory_utils import (
    format_update_active_memory_failure_reason,
)


def _update_active_memory_action_event_outcome(
    context,
    action,
    result: dict,
    *,
    failure_reason: str = "",
) -> None:

    events = getattr(
        context,
        "runtime_action_events",
        None,
    )

    if not isinstance(
        events,
        list,
    ):
        return

    action_payload = str(
        getattr(
            action,
            "payload",
            "",
        )
        or ""
    ).strip()
    runtime_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()

    for event in reversed(events):
        if not isinstance(
            event,
            dict,
        ):
            continue

        if str(
            event.get(
                "name",
                "",
            )
            or ""
        ).strip().casefold() != "update_active_memory":
            continue

        event_turn_id = str(
            event.get(
                "runtime_turn_id",
                "",
            )
            or ""
        ).strip()
        if (
            runtime_turn_id
            and event_turn_id
            and event_turn_id != runtime_turn_id
        ):
            continue

        event_payload = str(
            event.get(
                "payload",
                "",
            )
            or ""
        ).strip()
        if (
            action_payload
            and event_payload
            and event_payload != action_payload
        ):
            continue

        event["status"] = (
            "completed"
            if result.get("ok")
            else "failed"
        )
        event["active_memory_id"] = str(
            result.get(
                "id",
                "",
            )
            or ""
        ).strip()

        if result.get("ok"):
            event.pop(
                "error",
                None,
            )
            event.pop(
                "failure_reason",
                None,
            )
        else:
            event["error"] = str(
                result.get(
                    "error",
                    "",
                )
                or ""
            ).strip()
            event["failure_reason"] = str(
                failure_reason
                or "update failed"
            ).strip()

        return



async def emit_rejected_active_memory_results(
    context,
    rejected_active_memory_results,
    *,
    with_action_context,
):
    if not rejected_active_memory_results:
        return

    from utils.brain_client_utils import queue_active_memory_delete_failure

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
        queue_active_memory_delete_failure(
            context,
            result,
        )

        if emit is None:
            continue

        await emit(with_action_context({
            "type": "runtime_action",
            "action": "delete_active_memory",
            "id": result.get(
                "id",
                "",
            ),
            "status": "failed",
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
            ),
            "text": "Active memory delete failed",
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

            if active_memory_line:
                completed_event["active_memory"] = active_memory_line

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
        failure_reason = (
            ""
            if result.get("ok")
            else format_update_active_memory_failure_reason(
                result
            )
        )
        _update_active_memory_action_event_outcome(
            context,
            action,
            result,
            failure_reason=failure_reason,
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
            "id": result.get("id", ""),
            "status": "completed" if result.get("ok") else "failed",
            "display_name": display_name,
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY
            ),
            "text": (
                f"{display_name}: {result.get('title', 'Active memory')}"
                if result.get("ok")
                else (
                    f"{display_name}: failed"
                    + (
                        f" : {failure_reason}"
                        if failure_reason
                        else ""
                    )
                )
            ),
            "active_memory_result": result,
            "active_memory_id": result.get("id", ""),
            "active_memory_title": result.get("title", ""),
            "active_memory_changes": result.get("changes", []),
            "active_memory_requested_changes": result.get(
                "requested_changes",
                [],
            ),
        }

        if not result.get("ok"):
            event["error"] = result.get(
                "error",
                "",
            )
            event["detail"] = failure_reason
            event["failure_reason"] = failure_reason

        if result.get("record"):
            event["active_memory"] = result["record"]

        await emit(with_action_context(event))

    return applied_count


async def apply_delete_active_memory_actions(
    context,
    delete_active_memory_actions,
    *,
    log_runtime,
    with_action_context,
):
    from utils.brain_client_utils import (
        build_active_memory_delete_failure_result,
        normalize_active_memory_content_for_duplicate_check,
        queue_active_memory_delete_failure,
        delete_active_memory_runtime_record,
    )

    deleted_active_memory_count = 0

    if not delete_active_memory_actions:
        return deleted_active_memory_count

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

    for action in delete_active_memory_actions:
        (
            record_deleted,
            active_memory_id,
            deleted_record,
        ) = (
            await delete_active_memory_runtime_record(
                context,
                action.payload,
            )
        )

        if not record_deleted:
            failure_result = build_active_memory_delete_failure_result(
                context,
                action.payload,
                error="active_memory_not_deleted",
            )
            if active_memory_id:
                failure_result["id"] = active_memory_id
            failure_result["detail"] = (
                "Active memory was not deleted. The record may be paused "
                "or may no longer exist. Do not claim that the action "
                "completed."
            )
            queue_active_memory_delete_failure(
                context,
                failure_result,
            )

            if emit is not None:
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "delete_active_memory",
                    "id": active_memory_id,
                    "status": "failed",
                    "display_name": get_runtime_action_display_name(
                        RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
                    ),
                    "close_tag": runtime_action_has_close_tag(
                        RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
                    ),
                    "text": "Active memory delete failed",
                    "active_memory_result": failure_result,
                }))
            continue

        deleted_active_memory_count += 1
        record_runtime_tool_result(
            context,
            TOOL_RESULT_KIND_ACTIVE_MEMORY,
            {
                "ok": True,
                "action": "delete_active_memory",
                "destination": (
                    "active_memory_records -> <ACTIVE_MEMORY> "
                    "(deleted and removed)"
                ),
                "id": active_memory_id,
                "content": (
                    normalize_active_memory_content_for_duplicate_check(
                        deleted_record
                    )
                ),
                "record": deleted_record,
            },
        )

        if emit is None:
            continue

        await emit(with_action_context({
            "type": "runtime_action",
            "action": "delete_active_memory",
            "id": active_memory_id,
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
            ),
            "text": "Active memory deleted",
            "payload": active_memory_id,
            "detail": (
                f"id: {active_memory_id}; "
                "content: "
                + normalize_active_memory_content_for_duplicate_check(
                    deleted_record
                )
            ),
        }))
        await emit(with_action_context({
            "type": "runtime_action",
            "action": "delete_active_memory",
            "id": active_memory_id,
            "status": "completed",
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
            ),
            "payload": active_memory_id,
            "detail": (
                f"id: {active_memory_id}; "
                "content: "
                + normalize_active_memory_content_for_duplicate_check(
                    deleted_record
                )
            ),
        }))

    if deleted_active_memory_count:
        context.runtime_active_memory_records_dirty = True

    return deleted_active_memory_count
