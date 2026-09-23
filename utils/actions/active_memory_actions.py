from contracts.rules_assembler import (
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from .active_memory_utils import (
    collect_active_memory_slot_ids,
    extract_active_memory_creation_custom_fields,
    get_active_memory_record_title,
    normalize_active_memory_slot_id,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    record_runtime_tool_result,
)
from .update_active_memory_utils import (
    format_update_active_memory_failure_reason,
)
from .save_active_memory_utils import (
    is_save_active_memory_update_payload,
)


def _set_save_active_memory_update_event_outcome(
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
        ).strip().casefold() != "save_active_memory":
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
        update_active_memory_runtime_record,
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

        action_display_id = str(
            resolved_action_display_ids.get(
                id(action),
                "",
            )
            or ""
        ).strip()

        if is_save_active_memory_update_payload(action.payload):
            result = await update_active_memory_runtime_record(
                context,
                action.payload,
            )
            result = dict(result)
            failure_reason = (
                ""
                if result.get("ok")
                else format_update_active_memory_failure_reason(result)
            )
            if failure_reason:
                result["detail"] = failure_reason

            _set_save_active_memory_update_event_outcome(
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

            active_memory_line = str(
                result.get("record", "")
                or ""
            ).strip()
            visible_active_memory_text = str(
                result.get("title", "")
                or ""
            ).strip()

            save_active_memory_results.append({
                "mode": "update",
                "payload": str(action.payload or "").strip(),
                "text": visible_active_memory_text,
                "record": active_memory_line,
                "display_id": action_display_id,
                "result": result,
                "failure_reason": failure_reason,
            })

            if result.get("ok"):
                saved_active_memory_texts.append(
                    visible_active_memory_text
                    or result.get("id", "")
                )
                if log_runtime is not None:
                    await log_runtime(
                        "[RUNTIME ACTION] active_memory record updated"
                    )

            continue

        active_memory_text = normalize_active_memory_runtime_payload(
            action.payload
        )
        if not active_memory_text:
            continue

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

        save_active_memory_results.append({
            "mode": "create",
            "payload": str(action.payload or "").strip(),
            "text": visible_active_memory_text,
            "record": active_memory_line,
            "display_id": action_display_id,
            "result": {
                "ok": bool(record_saved),
                "action": "save_active_memory",
                "mode": "create",
                "record": active_memory_line,
            },
            "failure_reason": "",
        })

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
        # meaningful for FRAME even if the visible assistant text ends up
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
        for save_result in save_active_memory_results:
            active_memory_mode = str(
                save_result.get("mode", "create")
                or "create"
            ).strip().casefold()
            active_memory_text = str(
                save_result.get("text", "")
                or ""
            ).strip()
            action_payload = str(
                save_result.get("payload", "")
                or ""
            ).strip()
            active_memory_line = str(
                save_result.get("record", "")
                or ""
            ).strip()
            action_display_id = str(
                save_result.get("display_id", "")
                or ""
            ).strip()
            result = save_result.get("result", {})
            if not isinstance(result, dict):
                result = {}
            failure_reason = str(
                save_result.get("failure_reason", "")
                or ""
            ).strip()
            display_name = get_runtime_action_display_name(
                RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
            )
            active_memory_id = str(
                result.get("id", "")
                or ""
            ).strip().casefold()
            if not active_memory_id:
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
                "active_memory_mode": active_memory_mode,
                "display_name": display_name,
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
                    active_memory_text or action_payload,
                ),
                "payload": str(
                    result.get("payload", "")
                    or action_payload
                    or active_memory_text
                ).strip(),
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

            if active_memory_mode == "update":
                event["active_memory_result"] = result
                event["active_memory_key"] = result.get("key", "")
                event["active_memory_title"] = result.get("title", "")
                event["active_memory_changes"] = result.get("changes", [])
                event["active_memory_requested_changes"] = result.get(
                    "requested_changes",
                    [],
                )

            await emit(with_action_context(
                event
            ))
            completed_event = {
                "type": "runtime_action",
                "action": "save_active_memory",
                "active_memory_mode": active_memory_mode,
                "status": "completed" if result.get("ok") else "failed",
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

            if active_memory_mode == "update":
                completed_event["active_memory_result"] = result
                completed_event["active_memory_key"] = result.get("key", "")
                completed_event["active_memory_title"] = result.get("title", "")
                completed_event["active_memory_changes"] = result.get("changes", [])
                completed_event["active_memory_requested_changes"] = result.get(
                    "requested_changes",
                    [],
                )
                if not result.get("ok"):
                    completed_event["error"] = result.get("error", "")
                    completed_event["detail"] = failure_reason
                    completed_event["failure_reason"] = failure_reason

            await emit(with_action_context(
                completed_event
            ))

    return saved_active_memory_texts
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
