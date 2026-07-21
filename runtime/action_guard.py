from __future__ import annotations

import asyncio
import uuid
from typing import Any

from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
)
from rules.runtime import (
    ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
)
from runtime.behavior_contract import (
    get_action_guard_blocker_match,
    get_action_guard_name_for_runtime_action,
    get_action_guard_triggers,
    should_pause_action_guard_for_confirmation,
)
from utils.context.runtime_state import (
    format_runtime_trigger_words_message,
)
from utils.actions import (
    build_runtime_action_id,
    is_noop_jin_color_action,
    normalize_jin_color_payload,
)


def append_action_guard_decision_message(
    context,
    guard_name: str,
    template: str,
) -> None:
    messages = getattr(
        context,
        "runtime_action_failure_followup_messages",
        None,
    )

    if not isinstance(messages, list):
        messages = []
        context.runtime_action_failure_followup_messages = messages

    message = format_runtime_trigger_words_message(
        template,
        get_action_guard_triggers(guard_name),
    )

    if message:
        messages.append(message)


def build_action_guard_confirmation_text(
    action_name: str,
) -> str:
    normalized = str(action_name or "").strip().casefold()

    if normalized == "save_delayed_memory_content":
        return "Saving delayed memory report"

    if normalized == "save_session":
        return "Saving session"

    return normalized.replace("_", " ")


def get_action_guard_display_id(
    context,
    action,
    display_state: dict[str, Any],
) -> str:
    if action.name == RUNTIME_ACTION_JIN_COLOR:
        action_id = str(
            display_state.get("jin_color_action_id", "")
            or ""
        ).strip()

        if not action_id:
            sequence = int(
                getattr(
                    context,
                    "runtime_jin_color_action_sequence",
                    0,
                )
                or 0
            ) + 1
            context.runtime_jin_color_action_sequence = sequence
            action_id = build_runtime_action_id(
                RUNTIME_ACTION_JIN_COLOR,
                sequence,
            )
            display_state["jin_color_action_id"] = action_id

        return action_id

    if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT:
        pending_ids = getattr(
            context,
            "runtime_pending_delayed_memory_action_ids",
            None,
        )

        if isinstance(pending_ids, list) and pending_ids:
            return str(pending_ids[-1] or "").strip()

    return ""


async def wait_for_action_guard_confirmation(
    context,
    action,
    guard_name: str,
    *,
    action_id: str = "",
    context_snapshot: dict | None = None,
) -> tuple[str, str]:
    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    if emit is None:
        return "reject", ""

    pending = getattr(
        context,
        "runtime_action_guard_confirmations",
        None,
    )

    if not isinstance(pending, dict):
        pending = {}
        context.runtime_action_guard_confirmations = pending

    loop = asyncio.get_running_loop()
    confirmation_id = (
        f"{getattr(context, 'runtime_current_turn_id', '')}:"
        f"{action.name.lower()}:{uuid.uuid4().hex[:12]}"
    )
    future = loop.create_future()
    pending[confirmation_id] = future

    action_name = action.name.lower()
    payload = {
        "type": "runtime_action_guard_confirmation",
        "action": action_name,
        "id": str(action_id or "").strip(),
        "confirmation_id": confirmation_id,
        "guard": guard_name,
        "status": "pending",
        "text": build_action_guard_confirmation_text(action_name),
        "detail": (
            "Runtime action marker emitted without matching "
            "behavior-contract trigger words in the user message."
        ),
        "missing_triggers": list(
            get_action_guard_triggers(guard_name)
        ),
        "timeout_ms": 0,
    }

    if action.name == RUNTIME_ACTION_JIN_COLOR:
        color = normalize_jin_color_payload(action.payload)
        if color:
            payload["color"] = color
            payload["payload"] = color

    if isinstance(context_snapshot, dict) and context_snapshot:
        payload["context"] = dict(context_snapshot)

    try:
        await emit(payload)
        decision = str(await future or "reject").strip().casefold()
        return decision, confirmation_id
    finally:
        pending.pop(confirmation_id, None)


async def confirm_runtime_action_guards(
    context,
    actions,
    *,
    user_message: str,
    context_snapshot: dict | None = None,
    confirmed_guard_names: set[str] | None = None,
    rejected_guard_names: set[str] | None = None,
    display_state: dict[str, Any] | None = None,
) -> tuple[set[int], set[int], dict[int, str], dict[int, str]]:
    confirmed_guard_names = (
        confirmed_guard_names
        if isinstance(confirmed_guard_names, set)
        else set()
    )
    rejected_guard_names = (
        rejected_guard_names
        if isinstance(rejected_guard_names, set)
        else set()
    )
    display_state = (
        display_state
        if isinstance(display_state, dict)
        else {}
    )

    confirmed_action_ids: set[int] = set()
    rejected_action_ids: set[int] = set()
    confirmation_ids: dict[int, str] = {}
    action_display_ids: dict[int, str] = {}

    for action in actions:
        if is_noop_jin_color_action(
            context,
            action,
        ):
            continue

        guard_name = get_action_guard_name_for_runtime_action(
            action.name
        )
        action_id = get_action_guard_display_id(
            context,
            action,
            display_state,
        )

        if action_id:
            action_display_ids[id(action)] = action_id

        if not guard_name:
            continue

        if get_action_guard_blocker_match(
            guard_name,
            user_message,
        ):
            continue

        if guard_name in rejected_guard_names:
            rejected_action_ids.add(id(action))
            continue

        if guard_name in confirmed_guard_names:
            confirmed_action_ids.add(id(action))
            continue

        if not should_pause_action_guard_for_confirmation(
            guard_name,
            user_message,
        ):
            continue

        decision, confirmation_id = (
            await wait_for_action_guard_confirmation(
                context,
                action,
                guard_name,
                action_id=action_id,
                context_snapshot=context_snapshot,
            )
        )

        if confirmation_id:
            confirmation_ids[id(action)] = confirmation_id

        if decision == "reject":
            rejected_guard_names.add(guard_name)
            rejected_action_ids.add(id(action))
            append_action_guard_decision_message(
                context,
                guard_name,
                ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
            )
            continue

        confirmed_guard_names.add(guard_name)
        confirmed_action_ids.add(id(action))
        append_action_guard_decision_message(
            context,
            guard_name,
            ACTION_ACCEPTED_MISSING_TRIGGER_WORDS_MESSAGE,
        )

    return (
        confirmed_action_ids,
        rejected_action_ids,
        confirmation_ids,
        action_display_ids,
    )
