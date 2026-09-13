from __future__ import annotations

import json

from contracts.rules_assembler import (
    RUNTIME_ACTION_POSTING_BOARD,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.actions import build_runtime_action_id
from utils.posting_board_client import execute_posting_board_request
from utils.tool_results import (
    TOOL_RESULT_KIND_RUNTIME_ACTION,
    record_runtime_tool_result,
)


def parse_posting_board_payload(payload) -> dict:
    if isinstance(payload, dict):
        value = dict(payload)
    else:
        try:
            value = json.loads(str(payload or "").strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
    return value if isinstance(value, dict) else {}


def posting_board_action_name(payload) -> str:
    parsed = parse_posting_board_payload(payload)
    return str(parsed.get("action") or "").strip().casefold()


def build_posting_board_display_text(payload, *, failed: bool = False) -> str:
    action = posting_board_action_name(payload) or "unknown"
    text = f"POSTING_BOARD: action:{action}"
    if failed:
        text += " - failed"
    return text


def _update_runtime_event(context, action_call, *, result: dict, action_id: str) -> None:
    payload = str(getattr(action_call, "payload", "") or "").strip()
    events = getattr(context, "runtime_action_events", []) or []
    for event in reversed(events):
        if not isinstance(event, dict):
            continue
        if str(event.get("name") or "").casefold() != "posting_board":
            continue
        if payload and str(event.get("payload") or "").strip() != payload:
            continue
        if action_id and event.get("id") and str(event.get("id")) != action_id:
            continue
        event["status"] = "completed" if result.get("ok") is not False else "failed"
        if result.get("ok") is False:
            event["failure_reason"] = str(result.get("detail") or result.get("error") or "failed")
            event["error"] = str(result.get("error") or "posting_board_failed")
        return


async def apply_posting_board_actions(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
):
    results = []
    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    for action_call in actions or ():
        parsed = parse_posting_board_payload(action_call.payload)
        action_id = str(action_display_ids.get(id(action_call), "") or "").strip()
        if not action_id:
            sequence = int(getattr(context, "runtime_posting_board_action_sequence", 0) or 0) + 1
            context.runtime_posting_board_action_sequence = sequence
            action_id = build_runtime_action_id(RUNTIME_ACTION_POSTING_BOARD, sequence)
            action_display_ids[id(action_call)] = action_id

        request_text = build_posting_board_display_text(action_call.payload)

        if emit is not None:
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "posting_board",
                "id": action_id,
                "status": "running",
                "display_name": get_runtime_action_display_name(RUNTIME_ACTION_POSTING_BOARD),
                "text": request_text,
                "payload": str(action_call.payload or "").strip(),
                "posting_board_request": parsed,
                "close_tag": runtime_action_has_close_tag(RUNTIME_ACTION_POSTING_BOARD),
            }))

        if not parsed:
            result = {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": "unknown",
                "error": "invalid_json",
                "detail": "POSTING_BOARD payload must be one JSON object",
                "request": {},
                "response": None,
            }
        else:
            result = await execute_posting_board_request(parsed)

        result["id"] = action_id
        record_runtime_tool_result(
            context,
            TOOL_RESULT_KIND_RUNTIME_ACTION,
            result,
        )
        _update_runtime_event(
            context,
            action_call,
            result=result,
            action_id=action_id,
        )

        if log_runtime is not None:
            board_action = str(result.get("action") or "unknown")
            status = "success" if result.get("ok") is not False else "failed"
            await log_runtime(
                f"[RUNTIME ACTION] posting_board action:{board_action} {status}"
            )

        if emit is not None:
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "posting_board",
                "id": action_id,
                "status": "completed" if result.get("ok") is not False else "failed",
                "display_name": get_runtime_action_display_name(RUNTIME_ACTION_POSTING_BOARD),
                "text": build_posting_board_display_text(
                    action_call.payload,
                    failed=result.get("ok") is False,
                ),
                "payload": str(action_call.payload or "").strip(),
                "detail": str(result.get("detail") or "").strip(),
                "posting_board_result": result,
                "close_tag": runtime_action_has_close_tag(RUNTIME_ACTION_POSTING_BOARD),
            }))

        results.append(result)

    return results
