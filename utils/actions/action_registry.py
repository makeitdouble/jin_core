"""Runtime action registry.

Every concrete runtime action is wired here. The dispatcher/runner never branches
on action names: it asks the registry how to prepare and run each emitted call.
"""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Mapping
import json
from typing import Awaitable, Callable, TYPE_CHECKING

from contracts.rules_assembler import (
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_ATTACH_FILE_BY_ID,
    RUNTIME_ACTION_ATTACH_FILE_CONTENT,
    RUNTIME_ACTION_CALL_MCP,
    RUNTIME_ACTION_CHAT_LOG_SEARCH,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_REACTION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_SPEED,
    RUNTIME_ACTION_LIST_FILES,
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_POSTING_BOARD,
    RUNTIME_ACTION_RECALL_FACT_CONTEXT,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_UNLOAD_SKILL,
    RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_WEB_SEARCH,
)
from utils.skills_asset_utils import normalize_skill_name
from utils.tool_results import TOOL_RESULT_KIND_ACTIVE_MEMORY, TOOL_RESULT_KIND_RUNTIME_ACTION, record_runtime_tool_result
from utils.brain_client_utils import (
    build_active_memory_delete_failure_result,
    build_active_memory_runtime_line,
    build_delayed_memory_report,
    collect_context_active_memory_slot_ids,
    collect_context_active_memory_texts,
)

from .active_memory_utils import generate_active_memory_slot_key
from .jin_color_utils import normalize_jin_color_payload
from .jin_position_utils import normalize_jin_position_dict, normalize_jin_position_payload
from .jin_reaction_utils import normalize_jin_reaction_payload
from .jin_size_utils import normalize_jin_size_dict, normalize_jin_size_payload
from .jin_speed_utils import normalize_jin_speed_payload, normalize_jin_speed_value
from .resolve_action_utils import extract_active_memory_delete_slot_id
from .save_active_memory_utils import is_save_active_memory_update_payload
from .update_active_memory_utils import parse_update_active_memory_payload
from .web_search_utils import extract_search_query

if TYPE_CHECKING:
    from .common_action_utils import RuntimeActionCall
    from .action_state import ActionState


Prepare = Callable[["ActionState", "RuntimeActionCall"], bool]
Run = Callable[[object, "RuntimeActionCall", dict], Awaitable[int]]


@dataclass(frozen=True)
class ActionFeedback:
    result: object = None
    message: str = ""


FeedbackHandler = Callable[["RuntimeActionCall", object], ActionFeedback]


def _format_feedback_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        parts = []
        for key, item in value.items():
            if isinstance(item, str):
                rendered = item
            elif isinstance(item, Mapping) or isinstance(item, (list, tuple)):
                rendered = json.dumps(item, ensure_ascii=False, separators=(",", ":"))
            elif item is None:
                rendered = ""
            else:
                rendered = str(item)
            parts.append(f"{key}: {rendered}")
        return ", ".join(parts)
    if isinstance(value, (list, tuple)):
        return ", ".join(_format_feedback_value(item) for item in value)
    return str(value)


def _default_feedback_message(action, fallback=None) -> str:
    value = action.payload if action.payload not in (None, "") else fallback
    rendered = _format_feedback_value(value).strip()
    return f"{action.name}: {rendered}" if rendered else action.name


def default_on_success(action, result) -> ActionFeedback:
    return ActionFeedback(
        result=result,
        message=_default_feedback_message(action, result),
    )


def default_on_fail(action, error) -> ActionFeedback:
    return ActionFeedback(
        result=error,
        message=_default_feedback_message(action, error),
    )


def _event_text_success(action, result) -> ActionFeedback:
    message = ""
    if isinstance(result, Mapping):
        message = str(result.get("text") or result.get("message") or "").strip()
    return ActionFeedback(
        result=result,
        message=message or _default_feedback_message(action, result),
    )


def _event_text_fail(action, error) -> ActionFeedback:
    message = ""
    if isinstance(error, Mapping):
        message = str(
            error.get("text")
            or error.get("message")
            or error.get("detail")
            or error.get("error")
            or ""
        ).strip()
    return ActionFeedback(
        result=error,
        message=message or _default_feedback_message(action, error),
    )


def _size_success(action, result) -> ActionFeedback:
    from .jin_size_utils import format_jin_size_value

    size = normalize_jin_size_dict(action.payload)
    if not size:
        return default_on_success(action, result)
    width = format_jin_size_value(size.get("width"))
    height = format_jin_size_value(size.get("height"))
    return ActionFeedback(
        result=result,
        message=f"{action.name}: w:{width} h:{height}",
    )


@dataclass(frozen=True)
class Action:
    prepare: Prepare | None = None
    run: Run | None = None
    on_success: FeedbackHandler = default_on_success
    on_fail: FeedbackHandler = default_on_fail


def apply_action_feedback(action_call, event: dict) -> dict:
    """Apply the registered bubble contract to one runtime_action event.

    Running events always show only the action name. Terminal events are
    formatted by the action's on_success/on_fail callbacks. The callback result
    stays local to the runtime contract; only its message is projected to UI.
    """
    if not isinstance(event, dict):
        return event
    event_action = str(event.get("action") or "").strip().casefold()
    if event_action and event_action != str(action_call.name or "").strip().casefold():
        return event

    definition = get_action(action_call.name)
    if definition is None:
        return event

    status = str(event.get("status") or "").strip().casefold()
    if status in {"started", "start", "pending", "running"}:
        message = str(action_call.name or "").strip().upper()
        event["text"] = message
        return event

    if status in {"completed", "complete", "done"}:
        feedback = definition.on_success(action_call, event)
    elif status in {"failed", "interrupted", "aborted"}:
        feedback = definition.on_fail(action_call, event)
    else:
        return event

    if feedback.message:
        event["text"] = feedback.message
    return event


def _prepare_reaction(state, action):
    reaction = normalize_jin_reaction_payload(action.payload)
    return bool(reaction) and state.dedup.accept(action, "__single_reaction__")


def _prepare_color(state, action):
    color = normalize_jin_color_payload(action.payload)
    if not color or color == state.dedup.color:
        return False
    state.dedup.color = color
    state.dedup.colors[state.dedup.visual_scope] = color
    return True


def _prepare_size(state, action):
    size_payload = normalize_jin_size_payload(action.payload)
    size = normalize_jin_size_dict(action.payload)
    if not size_payload or not size or size_payload == state.dedup.size:
        return False
    state.dedup.size = size_payload
    state.dedup.sizes[state.dedup.visual_scope] = size_payload
    return True


def _prepare_position(state, action):
    return bool(
        normalize_jin_position_payload(action.payload)
        and normalize_jin_position_dict(action.payload)
    )


def _prepare_speed(state, action):
    return bool(
        normalize_jin_speed_payload(action.payload)
        and normalize_jin_speed_value(action.payload) is not None
    )


def _prepare_save_delayed(state, action):
    key = str(action.payload or "").strip()
    if key in state.save_delayed_memory_seen:
        return False
    if not build_delayed_memory_report(state.batch.context, action.payload):
        return False
    if not state.dedup.accept(action, key):
        return False
    state.save_delayed_memory_seen.add(key)
    return True


def _prepare_save_active(state, action):
    if is_save_active_memory_update_payload(action.payload):
        active_memory_id, update_fields = parse_update_active_memory_payload(
            action.payload
        )
        if not active_memory_id or not update_fields:
            failure_error = "invalid_active_memory_payload"
            failure_reason = "invalid payload"
            failure_result = {
                "ok": False,
                "action": "save_active_memory",
                "mode": "update",
                "error": failure_error,
                "detail": failure_reason,
                "payload": str(action.payload or "").strip(),
            }
            state.rejected_action_events[id(action)] = {
                "status": "failed",
                "error": failure_error,
                "failure_reason": failure_reason,
                "failed_marker_payload": failure_result["payload"],
            }
            record_runtime_tool_result(
                state.batch.context,
                TOOL_RESULT_KIND_ACTIVE_MEMORY,
                failure_result,
            )
            return False

        return state.dedup.accept(
            action,
            ("update", active_memory_id, tuple(update_fields)),
        )

    active_memory_line = build_active_memory_runtime_line(
        action.payload,
        slot_key=generate_active_memory_slot_key(
            *collect_context_active_memory_texts(state.batch.context)
        ),
        existing_ids=collect_context_active_memory_slot_ids(state.batch.context),
    )
    if not active_memory_line:
        failure_result = {
            "ok": False,
            "action": "save_active_memory",
            "error": "invalid_active_memory_payload",
            "detail": "invalid payload",
            "payload": str(action.payload or "").strip(),
        }
        state.rejected_action_events[id(action)] = {
            "status": "failed",
            "error": failure_result["error"],
            "failure_reason": failure_result["detail"],
            "failed_marker_payload": failure_result["payload"],
        }
        record_runtime_tool_result(
            state.batch.context, TOOL_RESULT_KIND_ACTIVE_MEMORY, failure_result
        )
        return False
    return state.dedup.accept(action, active_memory_line)


def _prepare_update_active(state, action):
    active_memory_id, update_fields = parse_update_active_memory_payload(action.payload)
    if not active_memory_id or not update_fields:
        failure_error = "invalid_update_active_memory_payload"
        failure_reason = "invalid payload"
        failure_result = {
            "ok": False,
            "action": "update_active_memory",
            "error": failure_error,
            "detail": failure_reason,
            "payload": str(action.payload or "").strip(),
        }
        state.rejected_action_events[id(action)] = {
            "status": "failed",
            "error": failure_error,
            "failure_reason": failure_reason,
            "failed_marker_payload": failure_result["payload"],
        }
        record_runtime_tool_result(
            state.batch.context, TOOL_RESULT_KIND_ACTIVE_MEMORY, failure_result
        )
        return False
    return state.dedup.accept(action, (active_memory_id, tuple(update_fields)))


def _prepare_delete_active(state, action):
    active_memory_id = extract_active_memory_delete_slot_id(
        action.payload,
        existing_ids=collect_context_active_memory_slot_ids(state.batch.context),
    )
    if not active_memory_id:
        failure_result = build_active_memory_delete_failure_result(
            state.batch.context, action.payload
        )
        failure_key = str(
            failure_result.get("id", "")
            or failure_result.get("requested", "")
            or "unknown"
        ).strip().casefold()
        if failure_key in state.delete_active_memory_failures_seen:
            return False
        state.delete_active_memory_failures_seen.add(failure_key)
        state.rejected_active_memory_results.append(failure_result)
        state.rejected_action_events[id(action)] = {
            "status": "failed",
            "error": failure_result["error"],
            "id": failure_result.get("id", ""),
            "requested": failure_result.get("requested", ""),
        }
        return False
    if active_memory_id in state.delete_active_memory_ids_seen:
        return False
    if not state.dedup.accept(action, active_memory_id):
        return False
    state.delete_active_memory_ids_seen.add(active_memory_id)
    return True


def _prepare_deep_search(state, action):
    objective = extract_search_query(action.payload)
    if not objective or state.had_deep_search_calls:
        return False
    return state.dedup.accept(action, objective)


def _prepare_search(state, action):
    query = extract_search_query(action.payload)
    if not query or state.had_search_queries:
        return False
    return state.dedup.accept(action, query)


def _prepare_load_skill(state, action):
    requested = normalize_skill_name(action.payload)
    if not requested or not state.dedup.accept(action, requested):
        return False
    if requested in state.loaded_skill_names:
        return False
    state.loaded_skill_names.add(requested)
    return True


def _prepare_unload_skill(state, action):
    requested = normalize_skill_name(action.payload)
    if not requested or not state.dedup.accept(action, requested):
        return False
    state.loaded_skill_names.discard(requested)
    return True


def _prepare_always(state, action):
    return True


async def _run_visual(batch, action, _state):
    from .jin_visual_sequence_actions import emit_jin_visual_sequences

    logger = getattr(batch.context, "logger", None)
    await emit_jin_visual_sequences(
        batch.context,
        (action,),
        action_display_ids=batch.action_display_ids,
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return 1


async def _run_reaction(batch, action, _state):
    from .jin_reaction_actions import emit_jin_reactions

    logger = getattr(batch.context, "logger", None)
    await emit_jin_reactions(
        batch.context,
        (action,),
        action_display_ids=batch.action_display_ids,
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return 1


async def _run_search(batch, action, _state):
    query = extract_search_query(action.payload)
    if not query:
        return 0
    if not hasattr(batch.context, "runtime_search_queries"):
        batch.context.runtime_search_queries = []
    if not hasattr(batch.context, "runtime_search_calls"):
        batch.context.runtime_search_calls = []
    batch.context.runtime_search_queries.append(query)
    batch.context.runtime_search_calls.append({
        "id": str(batch.action_display_ids.get(id(action), "") or ""),
        "query": query,
        "payload": action.payload,
        "context": batch.action_context_snapshot,
    })
    logger = getattr(batch.context, "logger", None)
    log_runtime = getattr(logger, "log_runtime", None)
    if log_runtime is not None:
        await log_runtime("[RUNTIME ACTION] search x1")
    return 1


async def _run_deep_search(batch, action, _state):
    objective = extract_search_query(action.payload)
    if not objective:
        return 0
    if not hasattr(batch.context, "runtime_deep_search_calls"):
        batch.context.runtime_deep_search_calls = []
    batch.context.runtime_deep_search_calls.append({
        "id": str(batch.action_display_ids.get(id(action), "") or ""),
        "query": objective,
        "payload": action.payload,
        "context": batch.action_context_snapshot,
    })
    return 1


async def _run_clean(batch, action, state):
    from .clean_tool_results_actions import apply_clean_tool_results_actions

    await apply_clean_tool_results_actions(
        batch.context,
        (action,),
        tool_results_clean_state=state["tool_results_clean_state"],
        action_display_ids=batch.action_display_ids,
        with_action_context=batch.with_action_context_for(action),
    )
    return 1


async def _run_skill(batch, action, _state):
    from .asset_actions import emit_saved_asset_results
    from .skill_actions import apply_skill_actions, emit_skill_state_results

    logger = getattr(batch.context, "logger", None)
    results = await apply_skill_actions(
        batch.context,
        load_skill_actions=(action,) if action.name == RUNTIME_ACTION_LOAD_SKILL else (),
        unload_skill_actions=(action,) if action.name == RUNTIME_ACTION_UNLOAD_SKILL else (),
        log_runtime=getattr(logger, "log_runtime", None),
    )
    loaded = results["loaded_skill_results"]
    unloaded = results["unloaded_skill_results"]
    for skill_result in loaded + unloaded:
        if not isinstance(skill_result, dict):
            continue
        if skill_result.get("ok") is False and skill_result.get("error") == "skill_not_found":
            continue
        public_result = {
            key: value
            for key, value in skill_result.items()
            if not str(key or "").startswith("_runtime_")
        }
        record_runtime_tool_result(
            batch.context, TOOL_RESULT_KIND_RUNTIME_ACTION, public_result
        )
    if results["saved_asset_results"]:
        await emit_saved_asset_results(
            batch.context,
            results["saved_asset_results"],
            with_action_context=batch.with_action_context_for(action),
        )
    await emit_skill_state_results(
        batch.context,
        loaded + unloaded,
        with_action_context=batch.with_action_context_for(action),
    )
    return len(results["saved_asset_results"]) + len(loaded) + len(unloaded)


async def _run_asset(batch, action, _state):
    from .asset_actions import apply_asset_actions, emit_saved_asset_results

    logger = getattr(batch.context, "logger", None)
    results = await apply_asset_actions(
        batch.context,
        (action,),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    await emit_saved_asset_results(
        batch.context, results, with_action_context=batch.with_action_context_for(action)
    )
    return len(results)


async def _run_attachment(batch, action, _state):
    from .attachment_actions import apply_attachment_actions

    logger = getattr(batch.context, "logger", None)
    results = await apply_attachment_actions(
        batch.context,
        list_actions=(action,) if action.name == RUNTIME_ACTION_LIST_FILES else (),
        attach_actions=(action,) if action.name != RUNTIME_ACTION_LIST_FILES else (),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return len(results)


async def _run_update_lt(batch, action, _state):
    from .update_lt_facts_actions import schedule_update_lt_facts_actions

    logger = getattr(batch.context, "logger", None)
    await schedule_update_lt_facts_actions(
        batch.context,
        (action,),
        action_display_ids=batch.action_display_ids,
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return 1


async def _run_recall_fact(batch, action, _state):
    from .recall_fact_context_actions import apply_recall_fact_context_actions

    logger = getattr(batch.context, "logger", None)
    results = await apply_recall_fact_context_actions(
        batch.context,
        (action,),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return len(results)


async def _run_chat_log_search(batch, action, _state):
    from .chat_log_search_actions import apply_chat_log_search_actions

    logger = getattr(batch.context, "logger", None)
    results = await apply_chat_log_search_actions(
        batch.context,
        (action,),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
        action_display_ids=batch.action_display_ids,
    )
    return len(results)


async def _run_posting_board(batch, action, _state):
    from .posting_board_actions import apply_posting_board_actions

    logger = getattr(batch.context, "logger", None)
    results = await apply_posting_board_actions(
        batch.context,
        (action,),
        action_display_ids=batch.action_display_ids,
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return len(results)


async def _run_mcp(batch, action, _state):
    from .mcp_actions import apply_mcp_actions

    logger = getattr(batch.context, "logger", None)
    results = await apply_mcp_actions(
        batch.context,
        (action,),
        action_display_ids=batch.action_display_ids,
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return len(results)


async def _run_delayed_memory(batch, action, _state):
    from .delayed_memory_actions import apply_delayed_memory_actions, emit_delayed_memory_results

    logger = getattr(batch.context, "logger", None)
    results = await apply_delayed_memory_actions(
        batch.context,
        load_delayed_memory_actions=(action,) if action.name == RUNTIME_ACTION_LOAD_DELAYED_MEMORY else (),
        unload_delayed_memory_actions=(action,) if action.name == RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY else (),
        log_runtime=getattr(logger, "log_runtime", None),
    )
    await emit_delayed_memory_results(
        batch.context, results, with_action_context=batch.with_action_context_for(action)
    )
    return len(results)


async def _run_save_active(batch, action, _state):
    from .active_memory_actions import apply_save_active_memory_actions

    logger = getattr(batch.context, "logger", None)
    results = await apply_save_active_memory_actions(
        batch.context,
        (action,),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
        action_display_ids=batch.action_display_ids,
    )
    return len(results)


async def _run_update_active(batch, action, _state):
    from .active_memory_actions import apply_update_active_memory_actions

    logger = getattr(batch.context, "logger", None)
    return await apply_update_active_memory_actions(
        batch.context,
        (action,),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )


async def _run_delete_active(batch, action, _state):
    from .active_memory_actions import apply_delete_active_memory_actions

    logger = getattr(batch.context, "logger", None)
    return await apply_delete_active_memory_actions(
        batch.context,
        (action,),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )


async def _run_save_delayed(batch, action, _state):
    from .delayed_memory_actions import apply_save_delayed_memory_actions

    logger = getattr(batch.context, "logger", None)
    results = await apply_save_delayed_memory_actions(
        batch.context,
        (action,),
        log_runtime=getattr(logger, "log_runtime", None),
        with_action_context=batch.with_action_context_for(action),
    )
    return len(results)


ACTIONS = {
    RUNTIME_ACTION_CHAT_LOG_SEARCH: Action(prepare=_prepare_always, run=_run_chat_log_search, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_DEEP_WEB_SEARCH: Action(prepare=_prepare_deep_search, run=_run_deep_search),
    RUNTIME_ACTION_WEB_SEARCH: Action(prepare=_prepare_search, run=_run_search),
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS: Action(run=_run_clean),
    RUNTIME_ACTION_LOAD_SKILL: Action(prepare=_prepare_load_skill, run=_run_skill, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_UNLOAD_SKILL: Action(prepare=_prepare_unload_skill, run=_run_skill, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_ASSET_ACTION: Action(run=_run_asset, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_LIST_FILES: Action(run=_run_attachment, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_ATTACH_FILE_BY_ID: Action(run=_run_attachment, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_ATTACH_FILE_CONTENT: Action(run=_run_attachment, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_JIN_COLOR: Action(prepare=_prepare_color, run=_run_visual),
    RUNTIME_ACTION_JIN_REACTION: Action(prepare=_prepare_reaction, run=_run_reaction),
    RUNTIME_ACTION_JIN_SIZE: Action(prepare=_prepare_size, run=_run_visual, on_success=_size_success),
    RUNTIME_ACTION_JIN_POSITION: Action(prepare=_prepare_position, run=_run_visual),
    RUNTIME_ACTION_JIN_SPEED: Action(prepare=_prepare_speed, run=_run_visual),
    RUNTIME_ACTION_UPDATE_LT_FACTS: Action(run=_run_update_lt, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_RECALL_FACT_CONTEXT: Action(run=_run_recall_fact, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_POSTING_BOARD: Action(run=_run_posting_board, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_CALL_MCP: Action(run=_run_mcp, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY: Action(run=_run_delayed_memory, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY: Action(run=_run_delayed_memory, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY: Action(prepare=_prepare_save_active, run=_run_save_active, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY: Action(prepare=_prepare_update_active, run=_run_update_active, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY: Action(prepare=_prepare_delete_active, run=_run_delete_active, on_success=_event_text_success, on_fail=_event_text_fail),
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY: Action(prepare=_prepare_save_delayed, run=_run_save_delayed, on_success=_event_text_success, on_fail=_event_text_fail),
}

# Skill state changes create a follow-up barrier. Only these actions are allowed
# to continue in the same emitted stream once that barrier is active.
SKILL_WORKFLOW_ACTIONS = frozenset({
    RUNTIME_ACTION_CHAT_LOG_SEARCH,
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_UNLOAD_SKILL,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_WEB_SEARCH,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_REACTION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_RECALL_FACT_CONTEXT,
    RUNTIME_ACTION_POSTING_BOARD,
    RUNTIME_ACTION_CALL_MCP,
})




KEEP_ACTIVE_ACTIONS = frozenset({
    RUNTIME_ACTION_WEB_SEARCH,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
})


# Actions whose repeated source markers are meaningful inside one model response.
# Their prepare callbacks own any adjacency/alternation rules.
SOURCE_REPEAT_ACTIONS = frozenset({
    RUNTIME_ACTION_CHAT_LOG_SEARCH,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_REACTION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
})


def get_action(name: str) -> Action | None:
    return ACTIONS.get(name)
