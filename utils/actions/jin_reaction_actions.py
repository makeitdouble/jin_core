from __future__ import annotations

from contracts.rules_assembler import RUNTIME_ACTION_JIN_REACTION
from .jin_reaction_utils import normalize_jin_reaction_payload


async def emit_jin_reactions(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
) -> None:
    from utils.brain_client_utils import (
        build_runtime_action_event_display_fields,
    )

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    for action in actions or ():
        emoji = normalize_jin_reaction_payload(
            getattr(action, "payload", "")
        )
        if not emoji:
            continue

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] "
                f"jin_reaction {emoji}"
            )

        if emit is None:
            continue

        event = {
            "type": "runtime_action",
            "action": RUNTIME_ACTION_JIN_REACTION.lower(),
            "status": "completed",
            **build_runtime_action_event_display_fields(
                RUNTIME_ACTION_JIN_REACTION,
                emoji,
            ),
            "emoji": emoji,
            "payload": emoji,
        }
        action_id = str(
            action_display_ids.get(
                id(action),
                "",
            )
            or ""
        ).strip()
        if action_id:
            event["id"] = action_id

        await emit(
            with_action_context(event)
        )
