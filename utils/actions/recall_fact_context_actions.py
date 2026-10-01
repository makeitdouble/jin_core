from __future__ import annotations

import asyncio
import contextlib
import time

from contracts.rules_assembler import (
    RUNTIME_ACTION_RECALL_FACT_CONTEXT,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from runtime.LT_memory import ensure_runtime_lt_state
from runtime.fact_context import (
    normalize_fact_id,
    recall_fact_context,
)
from runtime.recall_fact_context_budget import (
    fit_recall_fact_context,
    recall_fact_context_budget,
)
from utils.chat_log import append_chat_runtime_event
from utils.tool_results import (
    TOOL_RESULT_KIND_FACT_CONTEXT,
    record_runtime_tool_result,
)


_RECALL_FACT_CONTEXT_FAILURE_REASONS = {
    "source_not_saved": "source not found",
    "source_unavailable": "source not found",
    "fact_not_found": "fact not found",
    "invalid_fact_id": "invalid fact id",
    "ambiguous_source_archive": "ambiguous source archive",
}


def _format_recall_fact_context_failure_reason(error) -> str:
    normalized = str(error or "").strip()
    if not normalized:
        return "unknown error"
    return _RECALL_FACT_CONTEXT_FAILURE_REASONS.get(
        normalized,
        normalized.replace("_", " "),
    )


def _record_recall_fact_context_outcome(
    context,
    *,
    fact_id: str,
    status: str,
    error: str = "",
    failure_reason: str = "",
) -> None:
    events = getattr(context, "runtime_action_events", None)
    if not isinstance(events, list):
        return

    current_turn_id = str(
        getattr(context, "runtime_current_turn_id", "") or ""
    ).strip()
    action_name = RUNTIME_ACTION_RECALL_FACT_CONTEXT.casefold()

    for event in events:
        if not isinstance(event, dict):
            continue
        if str(event.get("name") or "").strip().casefold() != action_name:
            continue
        if str(event.get("status") or "").strip().casefold() in {
            "completed",
            "failed",
        }:
            continue
        event_turn_id = str(event.get("runtime_turn_id") or "").strip()
        if current_turn_id and event_turn_id and event_turn_id != current_turn_id:
            continue
        event_payload = normalize_fact_id(event.get("payload"))
        if fact_id and event_payload and event_payload != fact_id:
            continue

        event["status"] = status
        if status == "failed":
            if error:
                event["error"] = error
            if failure_reason:
                event["failure_reason"] = failure_reason
        return


async def apply_recall_fact_context_actions(
    context,
    actions,
    *,
    log_runtime,
    with_action_context,
) -> list[dict]:
    if not actions:
        return []
    results = []
    budget = recall_fact_context_budget(context)
    facts_by_id = {
        normalize_fact_id(fact.get("id")): fact
        for fact in ensure_runtime_lt_state(context).get("facts", [])
        if isinstance(fact, dict) and normalize_fact_id(fact.get("id"))
    }

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    for action in actions:
        fact_id = normalize_fact_id(action.payload)
        fact = facts_by_id.get(fact_id)
        if not fact_id:
            recalled = {"ok": False, "fact_id": "", "error": "invalid_fact_id"}
        elif fact is None:
            recalled = {"ok": False, "fact_id": fact_id, "error": "fact_not_found"}
        else:
            recalled = await asyncio.to_thread(recall_fact_context, context, fact)

        tool_result, cost = fit_recall_fact_context(context, recalled, budget)
        budget = max(0, budget - cost)

        created_at = time.time()
        record_runtime_tool_result(
            context,
            TOOL_RESULT_KIND_FACT_CONTEXT,
            tool_result,
            result_id=fact_id,
            created_at=created_at,
        )
        with contextlib.suppress(Exception):
            append_chat_runtime_event(
                context,
                event="runtime_tool_result",
                payload={
                    "kind": TOOL_RESULT_KIND_FACT_CONTEXT,
                    "id": fact_id,
                    "result": tool_result,
                    "created_at": created_at,
                },
            )

        status = "completed" if tool_result["ok"] else "failed"
        raw_error = str(tool_result.get("error") or "").strip()
        failure_reason = (
            _format_recall_fact_context_failure_reason(raw_error)
            if status == "failed"
            else ""
        )
        display_text = build_runtime_action_display_text(
            RUNTIME_ACTION_RECALL_FACT_CONTEXT,
            fact_id,
        )
        if status == "failed":
            display_text = f"{display_text}: failed - {failure_reason}"

        _record_recall_fact_context_outcome(
            context,
            fact_id=fact_id,
            status=status,
            error=raw_error,
            failure_reason=failure_reason,
        )

        if log_runtime is not None:
            runtime_log_text = (
                f"[RUNTIME ACTION] recall_fact_context: {fact_id}: completed"
                if status == "completed"
                else (
                    f"[RUNTIME ACTION] recall_fact_context: {fact_id}: "
                    f"failed - {failure_reason}"
                )
            )
            await log_runtime(runtime_log_text)

        if emit is not None:
            event = {
                "type": "runtime_action",
                "action": "recall_fact_context",
                "id": fact_id,
                "status": status,
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_RECALL_FACT_CONTEXT
                ),
                "text": display_text,
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_RECALL_FACT_CONTEXT
                ),
                "payload": fact_id,
            }
            if raw_error:
                event["error"] = raw_error
            if failure_reason:
                event["failure_reason"] = failure_reason
            await emit(with_action_context(event))

        results.append(tool_result)

    return results
