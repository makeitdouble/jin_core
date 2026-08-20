from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
)
from utils.actions.jin_position_utils import (
    format_jin_position_payload,
    normalize_jin_position_dict,
)
from utils.actions.jin_speed_utils import (
    format_jin_speed_payload,
    normalize_jin_speed_value,
)


async def emit_jin_motion_actions(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
):
    motion_actions = [
        action
        for action in (actions or [])
        if action.name in {
            RUNTIME_ACTION_JIN_POSITION,
            RUNTIME_ACTION_JIN_SPEED,
        }
    ]

    if not motion_actions:
        return

    from utils.brain_client_utils import (
        build_runtime_action_event_display_fields,
    )

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    if emit is None:
        return

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] "
            f"jin_motion x{len(motion_actions)}"
        )

    # Preserve the model's marker order so a JIN_SPEED marker immediately
    # before JIN_POSITION controls that exact movement.
    for action in motion_actions:
        action_id = str(
            action_display_ids.get(id(action), "")
            or ""
        ).strip()

        if action.name == RUNTIME_ACTION_JIN_SPEED:
            speed = normalize_jin_speed_value(action.payload)
            payload = format_jin_speed_payload(speed)

            if speed is None or not payload:
                continue

            context.runtime_avatar_move_speed = speed

            await emit(with_action_context({
                "type": "runtime_action",
                "action": "jin_speed",
                "id": action_id,
                "status": "completed",
                **build_runtime_action_event_display_fields(
                    RUNTIME_ACTION_JIN_SPEED,
                    payload,
                ),
                "speed": speed,
                "payload": payload,
            }))
            continue

        position = normalize_jin_position_dict(action.payload)
        payload = format_jin_position_payload(position)

        if not position or not payload:
            continue

        context.runtime_avatar_current_position = dict(position)

        await emit(with_action_context({
            "type": "runtime_action",
            "action": "jin_position",
            "id": action_id,
            "status": "completed",
            **build_runtime_action_event_display_fields(
                RUNTIME_ACTION_JIN_POSITION,
                payload,
            ),
            "position": payload,
            "x": position["x"],
            "y": position["y"],
            "payload": payload,
        }))
