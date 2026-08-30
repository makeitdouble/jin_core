from __future__ import annotations

import asyncio
import contextlib
import time

from contracts.rules_assembler import (
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from runtime.LT_memory import run_lt_jin_note
from utils.actions.update_lt_facts_utils import parse_update_lt_facts_payload
from utils.chat_log import append_chat_runtime_event
from utils.tool_results import (
    TOOL_RESULT_KIND_LT,
    record_runtime_tool_result,
)
from utils.runtime_action_abort import mark_runtime_action_completed


def _build_update_lt_tool_result(
    result: dict,
    *,
    note: dict,
) -> dict:

    change = (
        result.get("change")
        if isinstance(result.get("change"), dict)
        else {}
    )
    status = str(result.get("status", "") or "").strip()
    summary = {
        "ok": status == "completed",
        "changed": bool(result.get("changed") or change.get("changed")),
    }

    action = str(change.get("action", "") or "").strip()
    if action:
        summary["action"] = action

    source_fact_ids = [
        str(item or "").strip()
        for item in (
            change.get("selected_fact_ids", [])
            or note.get("fact_ids", [])
            or []
        )
        if str(item or "").strip()
    ]
    if source_fact_ids:
        summary["source_fact_ids"] = source_fact_ids

    output_facts = []
    for key in ("replacement_facts", "new_facts"):
        for fact in change.get(key, []) or []:
            if not isinstance(fact, dict):
                continue
            compact_fact = {
                field: str(fact.get(field, "") or "").strip()
                for field in ("id", "key", "value", "category")
                if str(fact.get(field, "") or "").strip()
            }
            if compact_fact:
                output_facts.append(compact_fact)

    if len(output_facts) == 1:
        fact = output_facts[0]
        if fact.get("id"):
            summary["fact_id"] = fact["id"]
        for field in ("key", "value", "category"):
            if fact.get(field):
                summary[field] = fact[field]
    elif output_facts:
        summary["facts"] = output_facts

    if not summary["ok"]:
        summary["error"] = str(
            result.get("reason")
            or "lt_update_failed"
        ).strip()

    return summary


def _record_update_lt_tool_result(
    context,
    *,
    action_id: str,
    note: dict,
    result: dict,
) -> None:

    created_at = time.time()
    summary = _build_update_lt_tool_result(
        result,
        note=note,
    )
    record_runtime_tool_result(
        context,
        TOOL_RESULT_KIND_LT,
        summary,
        result_id=action_id,
        created_at=created_at,
    )

    with contextlib.suppress(Exception):
        append_chat_runtime_event(
            context,
            event="runtime_tool_result",
            payload={
                "kind": TOOL_RESULT_KIND_LT,
                "id": action_id,
                "result": summary,
                "created_at": created_at,
            },
        )


async def _emit_update_lt_facts_result(
    context,
    *,
    action_id: str,
    payload: str,
    result: dict,
    with_action_context,
) -> None:
    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    if emit is None:
        return

    completed = result.get("status") == "completed"
    change = result.get("change") if isinstance(result.get("change"), dict) else {}
    replacement_count = len(change.get("replacement_fact_ids", []) or [])
    added_count = len(change.get("added_ids", []) or [])

    if completed and result.get("changed"):
        detail_parts = []
        if replacement_count:
            detail_parts.append(f"{replacement_count} updated/merged fact(s)")
        if added_count:
            detail_parts.append(f"{added_count} new fact(s)")
        detail = "L-T updated: " + ", ".join(detail_parts or ["changed"])
    elif completed:
        detail = "L-T note reviewed: no change"
    else:
        detail = str(result.get("reason") or "L-T note failed")

    await emit(with_action_context({
        "type": "runtime_action",
        "action": "update_lt_facts",
        "id": action_id,
        "status": "completed" if completed else "failed",
        "display_name": get_runtime_action_display_name(
            RUNTIME_ACTION_UPDATE_LT_FACTS
        ),
        "text": build_runtime_action_display_text(
            RUNTIME_ACTION_UPDATE_LT_FACTS
        ),
        "close_tag": runtime_action_has_close_tag(
            RUNTIME_ACTION_UPDATE_LT_FACTS
        ),
        "payload": payload,
        "detail": detail,
        "lt_result": result,
    }))


async def _run_update_lt_facts_action(
    context,
    *,
    action_id: str,
    payload: str,
    note: dict,
    previous_lt_task,
    previous_lt_kind: str,
    log_runtime,
    with_action_context,
) -> None:
    current_task = asyncio.current_task()

    try:
        if (
            previous_lt_task is not None
            and previous_lt_task is not current_task
            and not previous_lt_task.done()
        ):
            # Explicit user-requested L-T work owns the foreground lane. Idle
            # consolidation must be cancelled without becoming a prerequisite
            # for the edit itself: a provider can take time to unwind a
            # cancelled HTTP generation, and awaiting that task here makes the
            # visible UPDATE_LT_FACTS bubble look stuck. Give cancellation one
            # event-loop turn, then start the focused note immediately.
            if previous_lt_kind == "idle":
                previous_lt_task.cancel()
                await asyncio.sleep(0)
            else:
                try:
                    await previous_lt_task
                except asyncio.CancelledError:
                    pass
                except Exception:
                    # The note still gets its own attempt after a failed
                    # previous foreground L-T edit.
                    pass

        if getattr(context, "runtime_lt_memory_update_task", None) is current_task:
            context.runtime_lt_memory_update_kind = "jin_note"

        result = await run_lt_jin_note(
            context=context,
            note=note,
        )

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] update_lt_facts "
                + (
                    "applied"
                    if result.get("changed")
                    else str(result.get("status") or "completed")
                )
            )

        _record_update_lt_tool_result(
            context,
            action_id=action_id,
            note=note,
            result=result,
        )

        await _emit_update_lt_facts_result(
            context,
            action_id=action_id,
            payload=payload,
            result=result,
            with_action_context=with_action_context,
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        result = {
            "phase": "jin_note",
            "status": "failed",
            "reason": type(error).__name__,
        }
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] update_lt_facts failed: "
                f"{type(error).__name__}"
            )
        _record_update_lt_tool_result(
            context,
            action_id=action_id,
            note=note,
            result=result,
        )
        await _emit_update_lt_facts_result(
            context,
            action_id=action_id,
            payload=payload,
            result=result,
            with_action_context=with_action_context,
        )
    finally:
        mark_runtime_action_completed(
            context,
            action="update_lt_facts",
            action_id=action_id,
        )
        if getattr(context, "runtime_lt_memory_update_task", None) is current_task:
            context.runtime_lt_memory_update_task = None
            if str(getattr(context, "runtime_lt_memory_update_kind", "") or "") == "jin_note":
                context.runtime_lt_memory_update_kind = ""


def schedule_update_lt_facts_actions(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
) -> list[asyncio.Task]:
    tasks = []

    for action in actions:
        note = parse_update_lt_facts_payload(action.payload)
        if not note:
            continue

        action_id = str(
            action_display_ids.get(id(action), "") or ""
        ).strip()
        created_at = time.time()
        message = str(note.get("message", "") or "").strip()
        session_action = {
            "text": (
                f"UPDATE_LT_FACTS: {message}"
                if message
                else "UPDATE_LT_FACTS"
            ),
            "created_at": created_at,
            "parts": [{
                "text": "UPDATE_LT_FACTS",
                **({"id": action_id} if action_id else {}),
                **({"message": message} if message else {}),
            }],
        }
        with contextlib.suppress(Exception):
            append_chat_runtime_event(
                context,
                event="runtime_action_request",
                payload={
                    "action": RUNTIME_ACTION_UPDATE_LT_FACTS,
                    "id": action_id,
                    "fact_ids": list(note.get("fact_ids", []) or []),
                    "message": message,
                    "session_action": session_action,
                    "created_at": created_at,
                },
            )
        previous_lt_task = getattr(
            context,
            "runtime_lt_memory_update_task",
            None,
        )
        previous_lt_kind = str(
            getattr(context, "runtime_lt_memory_update_kind", "") or ""
        )
        task = asyncio.create_task(
            _run_update_lt_facts_action(
                context,
                action_id=action_id,
                payload=action.payload,
                note=note,
                previous_lt_task=previous_lt_task,
                previous_lt_kind=previous_lt_kind,
                log_runtime=log_runtime,
                with_action_context=with_action_context,
            )
        )
        context.runtime_lt_memory_update_task = task
        context.runtime_lt_memory_update_kind = "jin_note"

        background_tasks = getattr(context, "background_tasks", None)
        if background_tasks is None:
            background_tasks = set()
            context.background_tasks = background_tasks
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        tasks.append(task)

    return tasks
