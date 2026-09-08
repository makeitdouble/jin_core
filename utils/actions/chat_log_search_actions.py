"""CHAT_LOG_SEARCH uses the ordinary action/tool-result lifecycle."""
import asyncio
import time

from utils.chat_log import append_chat_runtime_event
from utils.chat_log_search import (
    extract_chat_log_search_query,
    normalize_chat_log_search,
    search_chat_logs,
)
from utils.context.runtime_action_result_text import format_runtime_action_result
from utils.tool_results import TOOL_RESULT_KIND_RUNTIME_ACTION, record_runtime_tool_result
from utils.actions.common_action_utils import build_runtime_action_id


async def apply_chat_log_search_actions(context, actions, *, log_runtime, with_action_context, action_display_ids):
    results = []
    for action in actions:
        action_id = str(action_display_ids.get(id(action), "") or "")
        if not action_id:
            sequence = int(
                getattr(
                    context,
                    "runtime_chat_log_search_action_sequence",
                    0,
                )
                or 0
            ) + 1
            context.runtime_chat_log_search_action_sequence = sequence
            action_id = build_runtime_action_id(
                "CHAT_LOG_SEARCH",
                sequence,
            )

        query_text = extract_chat_log_search_query(action.payload)
        running_text = (
            f"CHAT_LOG_SEARCH: {query_text}"
            if query_text
            else "CHAT_LOG_SEARCH"
        )
        event = {"type": "runtime_action", "action": "chat_log_search", "id": action_id,
                 "display_name": "CHAT_LOG_SEARCH", "close_tag": True, "payload": action.payload}
        if query_text:
            event["query"] = query_text
        emit = getattr(getattr(context, "emitter", None), "emit", None)
        if emit:
            await emit(with_action_context({**event, "status": "running", "text": running_text, "detail": action.payload}))
        try:
            request = normalize_chat_log_search(action.payload)
        except ValueError as exc:
            result = {"ok": False, "action": "CHAT_LOG_SEARCH", "error": "invalid_request", "detail": str(exc), "payload": action.payload}
        else:
            query_text = extract_chat_log_search_query(request) or query_text
            try:
                result = await asyncio.to_thread(search_chat_logs, context, request)
                result["payload"] = action.payload
            except (OSError, UnicodeError) as exc:
                result = {"ok": False, "action": "CHAT_LOG_SEARCH", "error": "archive_read_failed", "detail": str(exc), "payload": action.payload}
        created_at = time.time()
        record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result, result_id=action_id, created_at=created_at)
        tool_id = context.runtime_tool_results[-1]["tool_id"]
        # Persist through the same raw event consumed by bootstrap enrichment.
        try:
            append_chat_runtime_event(context, event="runtime_tool_result", payload={
                "kind": TOOL_RESULT_KIND_RUNTIME_ACTION, "id": action_id, "tool_id": tool_id,
                "result": result, "created_at": created_at,
            })
        except OSError:
            pass
        status = "completed" if result["ok"] else "failed"
        for recorded in reversed(context.runtime_action_events):
            if recorded.get("name") == "chat_log_search" and recorded.get("payload") == action.payload:
                recorded["status"] = status
                recorded["id"] = action_id
                if query_text:
                    recorded["query"] = query_text
                if result["ok"]:
                    recorded["result_count"] = len(result["results"])
                if not result["ok"]:
                    recorded["failure_reason"] = result["detail"]
                break
        detail = format_runtime_action_result(result, runtime_action="CHAT_LOG_SEARCH")
        if result["ok"]:
            result_count = len(result["results"])
            text = (
                f"CHAT_LOG_SEARCH: {query_text} : {result_count} results"
                if query_text
                else f"CHAT_LOG_SEARCH: {result_count} results"
            )
        else:
            text = (
                f"CHAT_LOG_SEARCH: {query_text} : failed - {result['detail']}"
                if query_text
                else f"CHAT_LOG_SEARCH: failed - {result['detail']}"
            )
        if log_runtime:
            await log_runtime(f"[RUNTIME ACTION] {text}")
        if emit:
            terminal_event = {**event, "status": status, "text": text, "detail": detail,
                              "error": result.get("error", ""), "failure_reason": result.get("detail", "")}
            if query_text:
                terminal_event["query"] = query_text
            if result["ok"]:
                terminal_event["result_count"] = len(result["results"])
            await emit(with_action_context(terminal_event))
        results.append(result)
    return results
