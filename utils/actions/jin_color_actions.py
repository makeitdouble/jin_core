from contracts.rules_assembler import (
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.actions import (
    normalize_jin_color_payload,
    parse_idle_seconds,
)


async def apply_idle_actions(
    context,
    idle_actions,
    *,
    assistant_message,
    resolved_user_message,
    action_context_snapshot,
    log_runtime,
    with_action_context,
):
    from utils.brain_client_utils import (
        build_runtime_action_event_display_fields,
        schedule_idle_followup,
    )

    idle_records = []

    for action in idle_actions:
        seconds = parse_idle_seconds(
            action.payload
        )
        if seconds is None:
            continue

        idle_record = schedule_idle_followup(
            context,
            seconds=seconds,
            source_message=str(assistant_message or ""),
            user_message=resolved_user_message,
            context_snapshot=action_context_snapshot,
        )
        idle_records.append(idle_record)

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] "
                f"idle scheduled for {seconds}s "
                f"id={idle_record['id']!r}"
            )

    if idle_records:
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
            for idle_record in idle_records:
                idle_id = str(
                    idle_record.get(
                        "id",
                        "",
                    )
                    or ""
                )
                idle_payload = (
                    f"{int(idle_record.get('seconds', 0) or 0)}s"
                )
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "idle",
                    "id": idle_id,
                    "status": "started",
                    **build_runtime_action_event_display_fields(
                        RUNTIME_ACTION_IDLE,
                        idle_payload,
                    ),
                    "payload": idle_payload,
                    "detail": idle_payload,
                }))
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "idle",
                    "id": idle_id,
                    "status": "completed",
                    "display_name": get_runtime_action_display_name(
                        RUNTIME_ACTION_IDLE
                    ),
                    "close_tag": runtime_action_has_close_tag(
                        RUNTIME_ACTION_IDLE
                    ),
                    "payload": idle_payload,
                    "detail": idle_payload,
                }))

    return idle_records


async def emit_jin_color_actions(
    context,
    jin_color_actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
):
    if not jin_color_actions:
        return

    from utils.brain_client_utils import (
        build_runtime_action_event_display_fields,
    )

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] "
            f"jin_color x{len(jin_color_actions)}"
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

    if emit is not None:
        for action in jin_color_actions:
            color = normalize_jin_color_payload(
                action.payload
            )
            if not color:
                continue

            await emit(with_action_context({
                "type": "runtime_action",
                "action": "jin_color",
                "id": str(
                    action_display_ids.get(
                        id(action),
                        "",
                    )
                    or ""
                ).strip(),
                "status": "completed",
                **build_runtime_action_event_display_fields(
                    RUNTIME_ACTION_JIN_COLOR,
                    color,
                ),
                "color": color,
                "payload": color,
            }))
