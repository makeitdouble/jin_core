from contracts.rules_assembler import (
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_RUNTIME_ACTION,
    clean_runtime_tool_results_by_ids,
    clear_runtime_tool_results_before_current_turn,
    record_runtime_tool_result,
)


async def apply_clean_tool_results_actions(
    context,
    clean_tool_result_actions,
    *,
    action_display_ids,
    with_action_context,
):
    if not clean_tool_result_actions:
        return

    from runtime.frame_memory_utils import build_runtime_session_checkpoint
    from utils.context.runtime_action_result_text import format_runtime_action_result
    from utils.chat_log import append_chat_runtime_event

    emit = getattr(getattr(context, "emitter", None), "emit", None)
    for clean_action in clean_tool_result_actions:
        target_payload = str(clean_action.payload or "").strip()
        raw_parts = target_payload.split(",") if target_payload else []
        target_ids = tuple((part.strip() for part in raw_parts if part.strip()))
        malformed_id_list = bool(target_payload) and (
            not target_ids or any((not part.strip() for part in raw_parts))
        )
        if target_payload:
            ok = not malformed_id_list and clean_runtime_tool_results_by_ids(context, target_ids)
        else:
            # Empty CLEAN drops only results from earlier turns. Results emitted
            # earlier in this model turn stay alive regardless of stream chunks.
            clear_runtime_tool_results_before_current_turn(context)
            ok = True
        reason = "" if ok else f"Unknown or invalid tool_id list: {target_payload}"
        event = next(
            (
                event
                for event in context.runtime_action_events
                if event.get("name") == "clean_tool_results"
                and event.get("payload", "") == target_payload
                and (event.get("status") not in {"completed", "failed"})
            ),
            None,
        )
        if event is not None:
            event.update(status="completed" if ok else "failed", failure_reason=reason)
        failure = {
            "action": "clean_tool_results",
            "ok": False,
            "error": "invalid_tool_id",
            "detail": reason,
            "payload": target_payload,
        }
        if not ok:
            record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, failure)
        payload = with_action_context(
            {
                "type": "runtime_action",
                "action": "clean_tool_results",
                "id": action_display_ids.get(id(clean_action), ""),
                "status": "completed" if ok else "failed",
                "display_name": get_runtime_action_display_name(RUNTIME_ACTION_CLEAN_TOOL_RESULTS),
                "close_tag": runtime_action_has_close_tag(RUNTIME_ACTION_CLEAN_TOOL_RESULTS),
                "text": (
                    (
                        f"Tool results {', '.join(target_ids)} cleared"
                        if len(target_ids) > 1
                        else f"Tool result {target_ids[0]} cleared"
                    )
                    if target_ids
                    else "All tool results cleared"
                )
                if ok
                else reason,
                "detail": "" if ok else format_runtime_action_result(failure),
                "failure_reason": reason,
                "payload": target_payload,
            }
        )
        if ok:
            checkpoint = build_runtime_session_checkpoint(context)
            payload["tool_results"] = checkpoint["tool_results"]
            payload["tool_result_sequence"] = checkpoint["tool_result_sequence"]
        if emit is not None:
            await emit(payload)
        append_chat_runtime_event(context, event="runtime_action", payload=payload)
