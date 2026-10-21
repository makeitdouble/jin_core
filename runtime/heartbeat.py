"""Per-room idle deadlines; execution belongs to the existing request queue."""
import asyncio
import json
import math
import time

HEARTBEAT_USER_IDLE_SECONDS = 300
DEFAULT_HEARTBEAT_TICK_SPEED = 600

HEARTBEAT_TICK_MESSAGE = """<HEARTBEAT_TICK_MESSAGE>
This is an autonomous heartbeat tick. USER DID NOT SEND A NEW MESSAGE.
The user is idle. Examine the ordinary current context and decide whether
you have a reason to act. You may speak, use available ACTIONS, FOLLOW-UP,
subagents and ACTIVE MEMORY under their existing rules. You may freely set
your next heartbeat interval with SET_HEARTBEAT_TICK_SPEED.
There is no assigned task and no obligation to act. If nothing calls for
action, finish silently without starting further actions or follow-ups.
This notification applies only to this initial heartbeat request.
</HEARTBEAT_TICK_MESSAGE>"""


def validate_tick_speed(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("seconds must be a finite number, at least 60")
    if not math.isfinite(value) or value < 60:
        raise ValueError("seconds must be a finite number, at least 60")
    return value


def restore_tick_speed(context, payload):
    try:
        context.heartbeat_tick_speed = validate_tick_speed(
            payload.get("heartbeat_tick_speed", DEFAULT_HEARTBEAT_TICK_SPEED)
        )
    except (TypeError, ValueError, OverflowError):
        context.heartbeat_tick_speed = DEFAULT_HEARTBEAT_TICK_SPEED


def cancel_deadline(context):
    handle = getattr(context, "runtime_heartbeat_handle", None)
    if handle is not None:
        handle.cancel()
    context.runtime_heartbeat_handle = None


def note_activity(context):
    context.runtime_heartbeat_last_activity = time.monotonic()
    context.runtime_heartbeat_generation = getattr(context, "runtime_heartbeat_generation", 0) + 1
    arm_deadline(context)


def arm_deadline(context):
    cancel_deadline(context)
    enqueue = getattr(context, "runtime_heartbeat_enqueue", None)
    if enqueue is None:
        return
    now = time.monotonic()
    last = getattr(context, "runtime_heartbeat_last_activity", now)
    delay = max(0, last + HEARTBEAT_USER_IDLE_SECONDS - now) + context.heartbeat_tick_speed
    generation = context.runtime_heartbeat_generation
    context.runtime_heartbeat_handle = asyncio.get_running_loop().call_later(
        delay, enqueue, generation
    )


def eligible(context, generation):
    transport = getattr(context, "runtime_transport", None)
    return (
        generation == context.runtime_heartbeat_generation
        and time.monotonic() - context.runtime_heartbeat_last_activity >= HEARTBEAT_USER_IDLE_SECONDS
        and not getattr(transport, "stopping", False)
        and (transport is None or transport.socket is not None)
    )


def stop_heartbeat(context):
    cancel_deadline(context)
    context.runtime_heartbeat_enqueue = None
    context.runtime_heartbeat_generation += 1
    waiting = getattr(context, "runtime_heartbeat_frame_wait", None)
    if waiting is not None:
        waiting[0].remove_done_callback(waiting[1])
        context.runtime_heartbeat_frame_wait = None


def finish_activity(context):
    """FRAME is part of the existing turn tail; start the interval after it."""
    cancel_deadline(context)
    frame = getattr(context, "runtime_memory_update_task", None)
    if frame is not None and not frame.done():
        waiting = getattr(context, "runtime_heartbeat_frame_wait", None)
        if waiting is not None and waiting[0] is frame:
            return
        if waiting is not None:
            waiting[0].remove_done_callback(waiting[1])
        def completed(_):
            context.runtime_heartbeat_frame_wait = None
            arm_deadline(context)
        context.runtime_heartbeat_frame_wait = (frame, completed)
        frame.add_done_callback(completed)
    else:
        arm_deadline(context)


def mark_heartbeat_activity(context):
    """Materialize at the first visible output or action attempt."""
    if not getattr(context, "runtime_heartbeat_active", False):
        return
    if getattr(context, "runtime_heartbeat_meaningful", False):
        return
    from utils.chat_log import append_chat_log_entry
    context.runtime_heartbeat_meaningful = True
    # An ownership event is not an empty assistant reply. The ordinary turn
    # completion/Stop path persists the actual visible response and reasoning.
    append_chat_log_entry(context, role="runtime", text="")


async def apply_tick_speed(batch, action, _state):
    from rules.runtime import ACTION_FAILURE_FOLLOWUP_MESSAGE
    from utils.tool_results import TOOL_RESULT_KIND_RUNTIME_ACTION, record_runtime_tool_result
    try:
        payload = json.loads(action.payload)
        if not isinstance(payload, dict) or set(payload) != {"seconds"}:
            raise ValueError('Expected {"seconds": number}')
        seconds = validate_tick_speed(payload["seconds"])
    except (ValueError, TypeError, OverflowError) as error:
        result = {"action": action.name.lower(), "status": "failed", "ok": False,
                  "error": str(error), "supplied_payload": action.payload}
    else:
        batch.context.heartbeat_tick_speed = seconds
        result = {"action": action.name.lower(), "status": "completed", "ok": True, "seconds": seconds}
    record_runtime_tool_result(batch.context, TOOL_RESULT_KIND_RUNTIME_ACTION, result)
    for recorded in reversed(getattr(batch.context, "runtime_action_events", [])):
        if recorded.get("name") == action.name.lower() and recorded.get("payload") == action.payload:
            recorded.update(status=result["status"], result=result)
            if result["status"] == "failed":
                recorded["failure_reason"] = result["error"]
            break
    event = {
        "type": "runtime_action", **result,
        "id": str(batch.action_display_ids.get(id(action), "") or ""),
        "payload": result,
        "text": (f"Heartbeat interval: {result['seconds']} seconds"
                 if result["status"] == "completed" else result["error"]),
    }
    if result["status"] == "failed":
        event["failure_followup_message"] = ACTION_FAILURE_FOLLOWUP_MESSAGE
    await batch.context.emitter.emit(batch.with_action_context_for(action)(event))
    return 1
