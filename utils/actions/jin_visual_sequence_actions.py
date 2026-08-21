from __future__ import annotations

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


JIN_VISUAL_ACTION_NAMES = {
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
}


def _collect_jin_visual_runs(actions):
    runs = []
    current = []

    for action in actions or []:
        if getattr(action, "name", "") in JIN_VISUAL_ACTION_NAMES:
            current.append(action)
            continue

        if current:
            runs.append(current)
            current = []

    if current:
        runs.append(current)

    return runs


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


async def emit_jin_visual_sequences(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
):
    """Emit contiguous JIN visual markers as ordered animation sequences.

    The client buffers every marker in a run and only starts playback after the
    final marker arrives. This preserves the model's original marker order
    across color/size/speed/position instead of executing them in type groups.
    """

    from utils.brain_client_utils import (
        build_runtime_action_event_display_fields,
    )

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    if emit is None:
        return

    for run in _collect_jin_visual_runs(actions):
        prepared = []

        for action in run:
            event = _build_visual_event(action)

            if event is None:
                continue

            prepared.append((action, event))

        if not prepared:
            continue

        sequence_id = f"jin-{uuid4().hex}"
        sequence_count = len(prepared)

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] "
                f"jin_visual_sequence x{sequence_count}"
            )

        for sequence_index, (action, event) in enumerate(prepared):
            action_name = getattr(action, "name", "")
            payload = event["payload"]

            if action_name == RUNTIME_ACTION_JIN_SPEED:
                context.runtime_avatar_move_speed = event["speed"]
            elif action_name == RUNTIME_ACTION_JIN_POSITION:
                context.runtime_avatar_current_position = {
                    "x": event["x"],
                    "y": event["y"],
                }

            await emit(with_action_context({
                "type": "runtime_action",
                "action": event["action"],
                "id": str(
                    action_display_ids.get(id(action), "")
                    or ""
                ).strip(),
                "status": "completed",
                **build_runtime_action_event_display_fields(
                    action_name,
                    payload,
                ),
                **event,
                "jin_sequence_id": sequence_id,
                "jin_sequence_index": sequence_index,
                "jin_sequence_count": sequence_count,
            }))
