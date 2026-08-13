from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_SIZE,
)
from utils.actions.jin_size_utils import (
    format_jin_size_payload,
    normalize_jin_size_dict,
)


async def emit_jin_size_actions(
    context,
    jin_size_actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
):
    if not jin_size_actions:
        return

    from utils.brain_client_utils import (
        build_runtime_action_event_display_fields,
    )

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] "
            f"jin_size x{len(jin_size_actions)}"
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

    if emit is None:
        return

    for action in jin_size_actions:
        size = normalize_jin_size_dict(
            action.payload
        )
        payload = format_jin_size_payload(
            size
        )

        if not size or not payload:
            continue

        await emit(with_action_context({
            "type": "runtime_action",
            "action": "jin_size",
            "id": str(
                action_display_ids.get(
                    id(action),
                    "",
                )
                or ""
            ).strip(),
            "status": "completed",
            **build_runtime_action_event_display_fields(
                RUNTIME_ACTION_JIN_SIZE,
                payload,
            ),
            "size": payload,
            "width": size["width"],
            "height": size["height"],
            "payload": payload,
        }))
