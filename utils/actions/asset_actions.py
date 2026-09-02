from contracts.rules_assembler import (
    RUNTIME_ACTION_ASSET_ACTION,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.actions import build_runtime_action_id
from utils.python_skill_asset_utils import run_context_asset_action
from utils.session_actions_history import (
    build_asset_action_marker_text,
    build_asset_action_context_detail,
    build_asset_action_history_text,
    record_session_action_history,
)


async def apply_asset_actions(
    context,
    asset_actions,
    *,
    log_runtime,
    with_action_context,
):
    from utils.brain_client_utils import (
        append_asset_runtime_result,
        build_pending_asset_action_preview,
        build_runtime_action_event_display_fields,
        preserve_failed_asset_action_for_retry,
    )

    saved_asset_results = []

    if not asset_actions:
        return saved_asset_results

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] asset_action requested"
        )

    for action in asset_actions:
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
        pending_result = build_pending_asset_action_preview(
            action.payload
        )
        pending_text = build_asset_action_marker_text(
            pending_result
        )
        pending_action = str(
            pending_result.get(
                "action",
                "asset_action",
            )
            or "asset_action"
        )
        pending_asset_action_ids = getattr(
            context,
            "runtime_pending_asset_action_ids",
            None,
        )
        pending_action_id = (
            pending_asset_action_ids.pop(0)
            if isinstance(
                pending_asset_action_ids,
                list,
            )
            and pending_asset_action_ids
            else build_runtime_action_id(
                pending_action,
                len(
                    getattr(
                        context,
                        "runtime_asset_results",
                        [],
                    )
                    or []
                )
                + 1,
            )
        )
        if emit is not None:
            started_payload = with_action_context({
                "type": "runtime_action",
                "action": "asset_action",
                "id": pending_action_id,
                "status": "started",
                **build_runtime_action_event_display_fields(
                    RUNTIME_ACTION_ASSET_ACTION,
                ),
                "text": pending_text,
                "detail": str(
                    action.payload
                    or ""
                ).strip(),
                "asset_result": pending_result,
            })
            await emit(
                started_payload
            )
        else:
            started_payload = with_action_context({})

        previous_active_asset_action_id = getattr(
            context,
            "runtime_active_asset_action_id",
            "",
        )
        previous_active_asset_action_message_id = getattr(
            context,
            "runtime_active_asset_action_message_id",
            "",
        )
        context.runtime_active_asset_action_id = (
            pending_action_id
        )
        context.runtime_active_asset_action_message_id = str(
            started_payload.get(
                "runtime_message_id",
                "",
            )
            or ""
        )

        try:
            result = await run_context_asset_action(
                action.payload,
                context=context,
            )
        finally:
            context.runtime_active_asset_action_id = (
                previous_active_asset_action_id
            )
            context.runtime_active_asset_action_message_id = (
                previous_active_asset_action_message_id
            )
        result["runtime_action_id"] = pending_action_id
        append_asset_runtime_result(
            context,
            result,
        )
        preserve_failed_asset_action_for_retry(
            context,
            result,
            action.payload,
        )
        if (
            log_runtime is not None
            and result.get("ok") is False
        ):
            await log_runtime(
                "[RUNTIME ACTION] asset_action failed: "
                + build_asset_action_history_text(
                    result
                )
            )
        saved_asset_results.append(
            result
        )

    return saved_asset_results


async def emit_saved_asset_results(
    context,
    saved_asset_results,
    *,
    with_action_context,
):
    saved_asset_result_texts = [
        (
            result,
            build_asset_action_history_text(
                result
            ),
        )
        for result in saved_asset_results
    ]

    for result, text in saved_asset_result_texts:
        context_detail = build_asset_action_context_detail(
            result
        )
        display_parts = (
            [
                {
                    "text": "ASSET_ACTION",
                    "detail": context_detail,
                    "context_detail": context_detail,
                },
            ]
            if context_detail
            else None
        )
        history_before = len(
            getattr(
                context,
                "runtime_session_action_history",
                [],
            )
            or []
        )
        record_session_action_history(
            context,
            text,
            display_parts=display_parts,
        )
        history = getattr(
            context,
            "runtime_session_action_history",
            None,
        )
        if (
            isinstance(history, list)
            and len(history) > history_before
            and isinstance(history[-1], dict)
        ):
            # Keep the existing human-readable history text for UI/backward
            # compatibility; context rendering uses the structured parts above.
            history[-1]["text"] = text

    if not saved_asset_result_texts:
        return

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

    if emit is None:
        return

    first_asset_result_index = max(
        len(
            getattr(
                context,
                "runtime_asset_results",
                [],
            )
        )
        - len(
            saved_asset_results
        ),
        0,
    )

    for result_index, result in enumerate(
        saved_asset_results,
        start=1,
    ):
        result_action = str(
            result.get(
                "action",
                "assets",
            )
            or "assets"
        )
        action_name = "asset_action"
        text = (
            saved_asset_result_texts[
                result_index - 1
            ][1]
        )
        action_id = (
            result.get(
                "runtime_action_id",
                "",
            )
            or build_runtime_action_id(
                result_action
                or action_name,
                first_asset_result_index
                + result_index,
            )
        )
        from utils.project_reader import PROJECT_ACTIONS, format_project_result
        project_detail = format_project_result(result) if result_action in PROJECT_ACTIONS else ""
        await emit(with_action_context({
            "type": "runtime_action",
            "action": action_name,
            "id": action_id,
            "status": (
                "completed"
                if result.get("ok")
                else "failed"
            ),
            "display_name": get_runtime_action_display_name(
                action_name
            ),
            "close_tag": runtime_action_has_close_tag(
                action_name
            ),
            "text": text,
            "detail": project_detail or str(
                result.get(
                    "detail",
                    "",
                )
                or result.get(
                    "error",
                    "",
                )
                or ""
            ),
            "asset_result": result,
        }))
