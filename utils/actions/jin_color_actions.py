from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_COLOR,
)
from utils.actions import (
    normalize_jin_color_payload,
)


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
