from __future__ import annotations

import asyncio

from contracts.rules_assembler import (
    RUNTIME_ACTION_UPDATE_L4_FACTS,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from runtime.L4_memory import run_l4_jin_note
from utils.actions.update_l4_facts_utils import parse_update_l4_facts_payload
from utils.runtime_action_abort import mark_runtime_action_completed


async def _emit_update_l4_facts_result(
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
        detail = "L4 updated: " + ", ".join(detail_parts or ["changed"])
    elif completed:
        detail = "L4 note reviewed: no change"
    else:
        detail = str(result.get("reason") or "L4 note failed")

    await emit(with_action_context({
        "type": "runtime_action",
        "action": "update_l4_facts",
        "id": action_id,
        "status": "completed" if completed else "failed",
        "display_name": get_runtime_action_display_name(
            RUNTIME_ACTION_UPDATE_L4_FACTS
        ),
        "close_tag": runtime_action_has_close_tag(
            RUNTIME_ACTION_UPDATE_L4_FACTS
        ),
        "payload": payload,
        "detail": detail,
        "l4_result": result,
    }))


async def _run_update_l4_facts_action(
    context,
    *,
    action_id: str,
    payload: str,
    note: dict,
    previous_l4_task,
    log_runtime,
    with_action_context,
) -> None:
    current_task = asyncio.current_task()

    try:
        if (
            previous_l4_task is not None
            and previous_l4_task is not current_task
            and not previous_l4_task.done()
        ):
            try:
                await previous_l4_task
            except asyncio.CancelledError:
                pass
            except Exception:
                # The note still gets its own attempt after a failed previous
                # background consolidation.
                pass

        result = await run_l4_jin_note(
            context=context,
            note=note,
        )

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] update_l4_facts "
                + (
                    "applied"
                    if result.get("changed")
                    else str(result.get("status") or "completed")
                )
            )

        await _emit_update_l4_facts_result(
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
                "[RUNTIME ACTION] update_l4_facts failed: "
                f"{type(error).__name__}"
            )
        await _emit_update_l4_facts_result(
            context,
            action_id=action_id,
            payload=payload,
            result=result,
            with_action_context=with_action_context,
        )
    finally:
        mark_runtime_action_completed(
            context,
            action="update_l4_facts",
            action_id=action_id,
        )
        if getattr(context, "runtime_l4_memory_update_task", None) is current_task:
            context.runtime_l4_memory_update_task = None


def schedule_update_l4_facts_actions(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
) -> list[asyncio.Task]:
    tasks = []

    for action in actions:
        note = parse_update_l4_facts_payload(action.payload)
        if not note:
            continue

        action_id = str(
            action_display_ids.get(id(action), "") or ""
        ).strip()
        previous_l4_task = getattr(
            context,
            "runtime_l4_memory_update_task",
            None,
        )
        task = asyncio.create_task(
            _run_update_l4_facts_action(
                context,
                action_id=action_id,
                payload=action.payload,
                note=note,
                previous_l4_task=previous_l4_task,
                log_runtime=log_runtime,
                with_action_context=with_action_context,
            )
        )
        context.runtime_l4_memory_update_task = task

        background_tasks = getattr(context, "background_tasks", None)
        if background_tasks is None:
            background_tasks = set()
            context.background_tasks = background_tasks
        background_tasks.add(task)
        task.add_done_callback(background_tasks.discard)
        tasks.append(task)

    return tasks
