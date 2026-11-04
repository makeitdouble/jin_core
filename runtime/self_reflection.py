"""Optional initial-heartbeat action, using the ordinary action/Service lifecycle."""
import asyncio
import logging

from clients.response_extractor import ResponseExtractor
from clients.service_client import ask_service_model
from config_loader import config
from runtime.anonymous_mode import is_anonymous_session_id, persistent_writes_restricted
from runtime.memory_common import build_runtime_summarizer_payload, log_runtime_summarizer_payload, log_runtime_summarizer_result
from runtime.self_reflection_rules import SELF_REFLECTION_RULES
from utils import self_reflection_store as store
from utils.chat_log import append_chat_runtime_event, chat_log_root_for_context
from utils.self_reflection_history import archive_paths, normalize_session, serialize_history, stamp

logger = logging.getLogger(__name__)


def live_session_ids(context):
    from utils.subtask_memory import contexts
    # Retained server runtimes can still finish writes while disconnected.
    return {str(getattr(c, "session_id", "")) for c in contexts(context)}


def _candidate_first_stamp(history, paths):
    values = [stamp(record.get("ts")) for record in history if record.get("ts")]
    values = [value for value in values if value]
    if values:
        return min(values)
    path = paths[0]
    day = path.parent.parent.name
    clock = "".join(character for character in path.stem if character.isdigit())[:6]
    if len(clock) == 6:
        value = stamp(f"{day}T{clock[:2]}:{clock[2:4]}:{clock[4:6]}")
        if value:
            return value
    try:
        return path.stat().st_mtime
    except OSError:
        return 0


def candidate(context, state):
    live = live_session_ids(context)
    candidates = []
    for session_id, paths in archive_paths(chat_log_root_for_context(context)).items():
        saved = state["sessions"].get(session_id, {})
        if session_id in live or saved.get("completed"):
            continue
        try:
            history = saved.get("history")
            if history is None:
                history = normalize_session(session_id, paths)
        except (OSError, ValueError) as error:
            logger.warning("Cannot read reflection archive %s: %s", session_id, error)
            continue
        first = _candidate_first_stamp(history, paths)
        candidates.append((first, paths[0].as_posix(), session_id, history, saved.get("cursor", 0)))
    if not candidates:
        return None
    _, _, session_id, history, cursor = min(candidates, key=lambda item: item[:2])
    return session_id, history, cursor


def available(context):
    if context is None or persistent_writes_restricted(context) or getattr(context, "runtime_anonymous_mode", False) or is_anonymous_session_id(getattr(context, "session_id", "")):
        return False
    if store.ANALYSIS_LOCK.locked():
        return False
    if getattr(context, "runtime_turn_abort_requested", False):
        return False
    try:
        return candidate(context, store.load_state()) is not None
    except (OSError, ValueError, KeyError, TypeError) as error:
        logger.warning("Self-reflection unavailable: %s", error)
        return False


async def apply_self_reflection(batch, action, _state):
    from utils.tool_results import TOOL_RESULT_KIND_RUNTIME_ACTION, record_runtime_tool_result

    context = batch.context
    action_id = str(batch.action_display_ids.get(id(action), "") or "")
    acquired = False
    cancelled = False
    result = None

    async def emit(status, text, **extra):
        await context.emitter.emit(batch.with_action_context_for(action)({
            "type": "runtime_action", "action": action.name.lower(), "id": action_id,
            "status": status, "text": text, "display_name": action.name, "close_tag": False,
            **extra,
        }))

    try:
        if getattr(context, "runtime_turn_abort_requested", False):
            raise asyncio.CancelledError()
        turn_id = str(getattr(context, "runtime_current_turn_id", "") or batch.resolved_runtime_message_id)
        if not getattr(context, "runtime_self_reflection_allowed", False) or not getattr(context, "runtime_heartbeat_active", False) or getattr(context, "runtime_followup_tick_active", False):
            raise ValueError("Self-reflection is available only on the initial heartbeat request")
        if action.payload.strip():
            raise ValueError("RUN_SELF_REFLECTION has no payload")
        if getattr(context, "runtime_self_reflection_attempted_turn", None) == turn_id:
            raise ValueError("Self-reflection was already attempted on this heartbeat")
        context.runtime_self_reflection_attempted_turn = turn_id
        if not available(context):
            raise ValueError("No eligible archive, or reflection is already running")
        acquired = store.ANALYSIS_LOCK.acquire(blocking=False)
        if not acquired:
            raise ValueError("Reflection is already running; wait for another heartbeat")
        state = store.load_state(persist_migration=True)
        selected = candidate(context, state)
        if selected is None:
            raise ValueError("No eligible archive remains")
        session_id, history, cursor = selected
        await emit("running", action.name)
        sent_from = cursor + 1 if cursor < len(history) else None
        sent_through = len(history) if cursor < len(history) else None
        characteristics = store.characteristics_for_service(state)
        append_chat_runtime_event(context, event="runtime_action_request", payload={
            "action": action.name, "id": action_id, "status": "running",
            "source_session_id": session_id, "sent_from": sent_from,
            "sent_through": sent_through, "characteristic_count": len(characteristics)})
        client = context.clients["service"]
        prompt = serialize_history(session_id, history, cursor, characteristics)
        temperature = config.SERVICE_TEMPERATURE
        await log_runtime_summarizer_payload(context, label="SELF_REFLECTION", payload=build_runtime_summarizer_payload(
            service_client=client, system_prompt=SELF_REFLECTION_RULES, user_prompt=prompt,
            temperature=temperature, max_tokens=None, stream=False))
        response = await ask_service_model(client=client, context=context, user_prompt=prompt,
            system_prompt=SELF_REFLECTION_RULES, temperature=temperature, max_tokens=None, timeout=1000.0)
        text = ResponseExtractor.extract_content_text(response)
        await log_runtime_summarizer_result(context, label="SELF_REFLECTION", result=text)
        if ResponseExtractor.extract_finish_reason(response) in {"length", "max_tokens"}:
            raise ValueError("Service response was truncated")
        parsed = store.validate_result(text, session_id, history, cursor, state)
        # Last cancellable boundary, before the synchronous atomic transaction.
        await asyncio.sleep(0)
        if asyncio.current_task().cancelling() or getattr(context, "runtime_turn_abort_requested", False):
            raise asyncio.CancelledError()
        if session_id in live_session_ids(context) or session_id not in archive_paths(chat_log_root_for_context(context)):
            raise ValueError("Source archive is now live or has been deleted")
        transaction = store.commit_result(state, session_id, history, parsed)
        sent_range = (f"{transaction['sent_from']}–{transaction['sent_through']}"
                      if transaction["sent_from"] is not None else "empty")
        event_range = (f"{transaction['event_from']}–{transaction['event_through']}"
                       if transaction["event_from"] is not None else "none")
        if transaction["operation"] == "SKIP":
            summary = (f"session={session_id}; sent={sent_range}; event=none; operation=SKIP; "
                       f"reviewed remainder and found no clear event; "
                       f"cursor={transaction['cursor_before']}→{transaction['cursor_after']}")
        else:
            summary = (f"session={session_id}; sent={sent_range}; event={event_range}; "
                       f"operation={transaction['operation']}; "
                       f"characteristic={transaction['characteristic_id']}; "
                       f"behavior={transaction['description']}; "
                       f"outcome={transaction['outcome']}; "
                       f"cursor={transaction['cursor_before']}→{transaction['cursor_after']}")
        result = {"action": action.name.lower(), "ok": True, "status": "completed",
                  "text": summary, "reflection": parsed, **transaction}
    except asyncio.CancelledError:
        cancelled = True
        result = {"action": action.name.lower(), "ok": False, "status": "failed",
                  "error": "cancelled", "text": "Self-reflection cancelled; progress unchanged"}
    except Exception as error:
        result = {"action": action.name.lower(), "ok": False, "status": "failed",
                  "error": str(error), "text": f"Self-reflection failed: {error}; retry on a later heartbeat"}
    finally:
        if acquired:
            store.ANALYSIS_LOCK.release()

    record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result)
    for event in reversed(context.runtime_action_events):
        if event.get("name") == action.name.lower() and event.get("id", "") == action_id:
            event.update(status=result["status"], result=result, summary=result["text"])
            break
    append_chat_runtime_event(context, event="runtime_action_result", payload=result)
    await emit(result["status"], f"{action.name}: {result['text']}", payload=result, detail=result["text"])
    if cancelled:
        raise asyncio.CancelledError()
    return 1
