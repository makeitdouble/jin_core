"""Runtime action history and started/rejected notifications."""

from contracts.rules_assembler import (
    RUNTIME_ACTION_CHAT_LOG_SEARCH,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_REACTION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_WEB_SEARCH,
    RUNTIME_ACTION_POSTING_BOARD,
    RUNTIME_ACTION_CALL_MCP,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
    runtime_action_follows_up_on_fail,
)
from utils.actions import (
    build_runtime_action_id,
    extract_active_memory_delete_slot_id,
    extract_search_query,
    normalize_jin_color_payload,
    normalize_jin_reaction_payload,
    normalize_jin_position_dict,
    normalize_jin_position_payload,
    normalize_jin_speed_payload,
    normalize_jin_speed_value,
    normalize_jin_size_dict,
    normalize_jin_size_payload,
)
from utils.runtime_action_abort import mark_runtime_action_started
from utils.chat_log_search import extract_chat_log_search_query
from utils.actions.posting_board_actions import build_posting_board_display_text
from utils.actions.mcp_actions import build_call_mcp_display_text
from utils.brain_client_utils import (
    collect_context_active_memory_slot_ids,
    normalize_active_memory_runtime_payload,
)

_SEQUENCE_ATTRIBUTES = {
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY: "runtime_active_memory_action_sequence",
    RUNTIME_ACTION_POSTING_BOARD: "runtime_posting_board_action_sequence",
    RUNTIME_ACTION_CALL_MCP: "runtime_mcp_action_sequence",
    RUNTIME_ACTION_CHAT_LOG_SEARCH: "runtime_chat_log_search_action_sequence",
}
_QUERY_EXTRACTORS = {
    RUNTIME_ACTION_CHAT_LOG_SEARCH: extract_chat_log_search_query,
    RUNTIME_ACTION_DEEP_WEB_SEARCH: extract_search_query,
    RUNTIME_ACTION_WEB_SEARCH: extract_search_query,
}
_DISPLAY_BUILDERS = {
    RUNTIME_ACTION_POSTING_BOARD: build_posting_board_display_text,
    RUNTIME_ACTION_CALL_MCP: build_call_mcp_display_text,
}


def snapshot_search_counts(context):
    return {
        name: sum((event.get("name") == name.lower() for event in context.runtime_action_events))
        for name in (RUNTIME_ACTION_WEB_SEARCH, RUNTIME_ACTION_DEEP_WEB_SEARCH)
    }


def _display_id(context, action, action_display_ids):
    display_id = str(action_display_ids.get(id(action), "") or "").strip()
    attribute = _SEQUENCE_ATTRIBUTES.get(action.name)
    if not display_id and attribute:
        sequence = int(getattr(context, attribute, 0) or 0) + 1
        setattr(context, attribute, sequence)
        display_id = build_runtime_action_id(action.name, sequence)
        action_display_ids[id(action)] = display_id
    return display_id


def _project_jin_reaction(action, event):
    emoji = normalize_jin_reaction_payload(action.payload)
    if emoji:
        event["emoji"] = emoji
        event["payload"] = emoji


def _project_jin_color(action, event):
    color = normalize_jin_color_payload(action.payload)
    if color:
        event["color"] = color
        event["payload"] = color


def _project_jin_size(action, event):
    size = normalize_jin_size_dict(action.payload)
    payload = normalize_jin_size_payload(action.payload)
    if size and payload:
        event.update(
            size=payload,
            width=size["width"],
            height=size["height"],
            payload=payload,
        )


def _project_jin_position(action, event):
    position = normalize_jin_position_dict(action.payload)
    payload = normalize_jin_position_payload(action.payload)
    if position and payload:
        event.update(
            position=payload,
            x=position["x"],
            y=position["y"],
            payload=payload,
        )


def _project_jin_speed(action, event):
    speed = normalize_jin_speed_value(action.payload)
    payload = normalize_jin_speed_payload(action.payload)
    if speed is not None and payload:
        event.update(speed=speed, payload=payload)


def _project_payload(action, event):
    if not action.payload:
        return
    payload = action.payload
    if action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY:
        payload = normalize_active_memory_runtime_payload(action.payload)
    if payload:
        event["payload"] = payload


_VISUAL_PROJECTIONS = {
    RUNTIME_ACTION_JIN_REACTION: _project_jin_reaction,
    RUNTIME_ACTION_JIN_COLOR: _project_jin_color,
    RUNTIME_ACTION_JIN_SIZE: _project_jin_size,
    RUNTIME_ACTION_JIN_POSITION: _project_jin_position,
    RUNTIME_ACTION_JIN_SPEED: _project_jin_speed,
}


async def _emit_rejection(batch, selection, action):
    rejected_event = selection.rejected_action_events.get(id(action))
    if rejected_event is None:
        return
    if (
        not rejected_event.get("confirmation_id")
        and not rejected_event.get("failure_followup_message")
        and rejected_event.get("error")
        not in {"behavior_contract_blocker_matched", "restricted_write"}
        and not runtime_action_follows_up_on_fail(action.name)
    ):
        return

    emit = getattr(getattr(batch.context, "emitter", None), "emit", None)
    if emit is None:
        return

    payload = {
        "type": "runtime_action",
        "action": action.name.lower(),
        "status": "failed",
        "display_name": get_runtime_action_display_name(action.name),
        "close_tag": runtime_action_has_close_tag(action.name),
        "text": rejected_event.get("title")
        or rejected_event.get("error")
        or f"{action.name} blocked",
        "error": rejected_event.get("error", ""),
        "detail": rejected_event.get("failure_followup_message", "")
        or rejected_event.get("failure_reason", ""),
    }
    action_display_id = str(batch.action_display_ids.get(id(action), "") or "").strip()
    if action_display_id:
        payload["id"] = action_display_id
    project = _VISUAL_PROJECTIONS.get(action.name)
    if project and action.name != RUNTIME_ACTION_JIN_REACTION:
        project(action, payload)
    confirmation_id = str(rejected_event.get("confirmation_id", "") or "").strip()
    if confirmation_id:
        payload["confirmation_id"] = confirmation_id
    await emit(batch.with_action_context_for(action)(payload))


async def record_action_event(batch, selection, action, search_counts, *, accepted):
    """Record exactly one action at its source position.

    Returns the recorded event, or ``None`` for silent skips/reuse.
    """

    rejected_event = selection.rejected_action_events.get(id(action))
    if not accepted and rejected_event is None:
        return None

    action_event = {
        "name": action.name.lower(),
        "payload": str(action.payload or "").strip(),
    }
    action_display_id = _display_id(batch.context, action, batch.action_display_ids)
    if action_display_id:
        action_event["id"] = action_display_id

    runtime_turn_id = str(getattr(batch.context, "runtime_current_turn_id", "") or "").strip()
    if runtime_turn_id:
        action_event["runtime_turn_id"] = runtime_turn_id
    if batch.resolved_runtime_message_id:
        action_event["runtime_message_id"] = batch.resolved_runtime_message_id

    extractor = _QUERY_EXTRACTORS.get(action.name)
    extracted_query = extractor(action.payload) if extractor else ""
    query = extracted_query if action.name == RUNTIME_ACTION_WEB_SEARCH else ""
    deep_search_objective = (
        extracted_query if action.name == RUNTIME_ACTION_DEEP_WEB_SEARCH else ""
    )
    chat_log_search_query = (
        extracted_query if action.name == RUNTIME_ACTION_CHAT_LOG_SEARCH else ""
    )

    if chat_log_search_query:
        action_event["query"] = chat_log_search_query

    if action.name == RUNTIME_ACTION_DELETE_ACTIVE_MEMORY:
        active_memory_id = extract_active_memory_delete_slot_id(
            action.payload,
            existing_ids=collect_context_active_memory_slot_ids(batch.context),
        )
        if active_memory_id:
            action_event["id"] = active_memory_id

    if deep_search_objective:
        search_counts[RUNTIME_ACTION_DEEP_WEB_SEARCH] += 1
        tool_call_id = action_display_id or build_runtime_action_id(
            action.name, search_counts[RUNTIME_ACTION_DEEP_WEB_SEARCH]
        )
        batch.action_display_ids[id(action)] = tool_call_id
        action_event.update(id=tool_call_id, query=deep_search_objective)
    elif query:
        search_counts[RUNTIME_ACTION_WEB_SEARCH] += 1
        tool_call_id = action_display_id or build_runtime_action_id(
            action.name, search_counts[RUNTIME_ACTION_WEB_SEARCH]
        )
        batch.action_display_ids[id(action)] = tool_call_id
        action_event.update(id=tool_call_id, query=query)
    else:
        _VISUAL_PROJECTIONS.get(action.name, _project_payload)(action, action_event)

    if rejected_event is not None:
        action_event.update(
            {
                key: value
                for key, value in rejected_event.items()
                if value and not str(key).startswith("_")
            }
        )
        failure_followup_message = str(
            rejected_event.get("failure_followup_message", "") or ""
        ).strip()
        if failure_followup_message:
            messages = getattr(
                batch.context, "runtime_action_failure_followup_messages", None
            )
            if not isinstance(messages, list):
                messages = []
                batch.context.runtime_action_failure_followup_messages = messages
            messages.append(failure_followup_message)

    batch.context.runtime_action_events.append(action_event)

    if rejected_event is not None:
        await _emit_rejection(batch, selection, action)
        return action_event

    display_name = get_runtime_action_display_name(action.name)
    display_text = build_runtime_action_display_text(action.name, action.payload)
    runtime_action_id = str(action_event.get("id", action_display_id) or "").strip()
    if deep_search_objective:
        display_text = f"{display_name}: {deep_search_objective}"
    elif chat_log_search_query:
        display_text = f"{display_name}: {chat_log_search_query}"
    else:
        display_builder = _DISPLAY_BUILDERS.get(action.name)
        if display_builder:
            display_text = display_builder(action.payload)

    mark_runtime_action_started(
        batch.context,
        action=action_event.get("name", action.name.lower()),
        action_id=runtime_action_id,
        display_name=display_name,
        text=display_text,
        payload=action_event.get("payload", "")
        or action_event.get("query", "")
        or action.payload,
        close_tag=runtime_action_has_close_tag(action.name),
        context_snapshot=batch.action_context_snapshot,
    )

    if deep_search_objective:
        emit = getattr(getattr(batch.context, "emitter", None), "emit", None)
        if emit is not None:
            await emit(
                batch.with_action_context_for(action)(
                    {
                        "type": "runtime_action",
                        "action": RUNTIME_ACTION_DEEP_WEB_SEARCH.lower(),
                        "id": runtime_action_id,
                        "status": "running",
                        "display_name": display_name,
                        "text": display_text,
                        "query": deep_search_objective,
                        "scene_effect": "search",
                        "deep_search_parent": True,
                        "deep_search_payload_ready": True,
                        "close_tag": runtime_action_has_close_tag(action.name),
                    }
                )
            )

    return action_event
