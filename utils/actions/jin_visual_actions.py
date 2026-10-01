from __future__ import annotations

import logging
import time
from uuid import uuid4

from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_SPEED,
)
from utils.actions import (
    format_jin_position_payload,
    format_jin_size_payload,
    format_jin_speed_payload,
    normalize_jin_color_payload,
    normalize_jin_position_dict,
    normalize_jin_size_dict,
    normalize_jin_speed_value,
)
from utils.chat_log import append_chat_runtime_event


LOGGER = logging.getLogger(__name__)


def _build_visual_event(action):
    action_name = getattr(action, "name", "")
    raw_payload = getattr(action, "payload", "")

    if action_name == RUNTIME_ACTION_JIN_COLOR:
        color = normalize_jin_color_payload(raw_payload)
        if not color:
            return None
        return {
            "action": "jin_color",
            "payload": color,
            "color": color,
        }

    if action_name == RUNTIME_ACTION_JIN_SIZE:
        size = normalize_jin_size_dict(raw_payload)
        payload = format_jin_size_payload(size)
        if not size or not payload:
            return None
        return {
            "action": "jin_size",
            "payload": payload,
            "size": payload,
            "width": size["width"],
            "height": size["height"],
        }

    if action_name == RUNTIME_ACTION_JIN_SPEED:
        speed = normalize_jin_speed_value(raw_payload)
        payload = format_jin_speed_payload(speed)
        if speed is None or not payload:
            return None
        return {
            "action": "jin_speed",
            "payload": payload,
            "speed": speed,
        }

    if action_name == RUNTIME_ACTION_JIN_POSITION:
        position = normalize_jin_position_dict(raw_payload)
        payload = format_jin_position_payload(position)
        if not position or not payload:
            return None
        return {
            "action": "jin_position",
            "payload": payload,
            "position": payload,
            "x": position["x"],
            "y": position["y"],
        }

    return None


async def emit_jin_visual_action(
    context,
    action,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
):
    """Execute one already-parsed JIN visual action immediately."""

    from utils.brain_client_utils import (
        build_runtime_action_event_display_fields,
    )

    event = _build_visual_event(action)
    if event is None:
        return 0

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)
    if emit is None:
        return 0

    action_name = getattr(action, "name", "")
    payload = event["payload"]
    action_display_id = str(
        action_display_ids.get(id(action), "") or ""
    ).strip()

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] "
            f"{event['action']} x1"
        )

    if action_name == RUNTIME_ACTION_JIN_SPEED:
        context.runtime_avatar_move_speed = event["speed"]
    elif action_name == RUNTIME_ACTION_JIN_POSITION:
        context.runtime_avatar_current_position = {
            "x": event["x"],
            "y": event["y"],
        }
    elif action_name == RUNTIME_ACTION_JIN_COLOR:
        color = event["color"]
        context.jin_color = color
        created_at = time.time()
        event_id = f"jin-{uuid4().hex}"
        session_action = {
            "id": event_id,
            "text": "JIN_COLOR",
            "created_at": created_at,
            "runtime_turn_id": str(
                getattr(
                    context,
                    "runtime_current_turn_id",
                    "",
                )
                or ""
            ).strip(),
            "parts": [{
                "text": "JIN_COLOR",
                "colors": [color],
            }],
        }
        try:
            append_chat_runtime_event(
                context,
                event="runtime_action_request",
                payload={
                    "event_id": event_id,
                    "action": RUNTIME_ACTION_JIN_COLOR,
                    "id": action_display_id,
                    "color": color,
                    "payload": color,
                    "session_action": session_action,
                    "created_at": created_at,
                },
            )
        except Exception:
            LOGGER.exception(
                "Failed to persist JIN_COLOR runtime event %s",
                event_id,
            )

    await emit(with_action_context({
        "type": "runtime_action",
        "action": event["action"],
        "id": action_display_id,
        "status": "completed",
        **build_runtime_action_event_display_fields(
            action_name,
            payload,
        ),
        **event,
    }))
    return 1
