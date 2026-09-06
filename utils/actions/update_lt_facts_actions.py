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
from runtime.memory_common import log_memory_event
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


def _resolve_update_lt_fact_sources(context) -> list[dict]:
    """Return durable provenance for an explicit UPDATE_LT_FACTS note.

    A normal Brain turn is anchored to the current USER turn. The hidden
    archived-session resume turn is different: it has no USER row of its own,
    so persisting its synthetic turn id creates a source that RECALL can never
    resolve. In that case anchor the note to the latest real USER turn from the
    restored predecessor session instead.
    """
    from runtime.fact_sources import normalize_sources

    current = normalize_sources([{
        "session_id": str(getattr(context, "session_id", "") or ""),
        "turn_id": str(getattr(context, "runtime_current_turn_id", "") or ""),
    }])

    if not bool(getattr(context, "runtime_session_restore_priming", False)):
        return current

    source_session_id = str(
        getattr(context, "runtime_archived_session_id", "") or ""
    ).strip()
    if not source_session_id:
        return current

    try:
        # Import lazily: session_restore imports utils.actions for marker
        # normalizers, so a module-level import here would create a cycle.
        from utils.session_restore import build_archived_session_restore_payload

        archived = build_archived_session_restore_payload(source_session_id)
    except Exception:
        archived = None

    if isinstance(archived, dict):
        for message in reversed(archived.get("messages", []) or []):
            if not isinstance(message, dict):
                continue
            if str(message.get("role", "") or "").strip().casefold() != "user":
                continue
            restored = normalize_sources([{
                "session_id": source_session_id,
                "turn_id": str(message.get("turn_id", "") or ""),
            }])
            if restored:
                return restored

    # Do not invent a predecessor turn if the archive is unavailable. Keeping
    # the current synthetic source preserves the old failure semantics instead
    # of silently attaching the fact to unrelated history.
    return current



def _ensure_update_lt_facts_queue(context) -> list[dict]:
    queue = getattr(
        context,
        "runtime_lt_explicit_note_queue",
        None,
    )
    if not isinstance(queue, list):
        queue = []
        context.runtime_lt_explicit_note_queue = queue
    return queue


async def _emit_update_lt_facts_queued(
    context,
    *,
    action_id: str,
    payload: str,
    with_action_context,
) -> None:
    """Retire the chat action marker as soon as its async L-T job is queued."""
    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    if emit is not None:
        await emit(with_action_context({
            "type": "runtime_action",
            "action": "update_lt_facts",
            "id": action_id,
            "status": "completed",
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
            "detail": "Queued for L-T update.",
            "lt_queued": True,
        }))

    # The marker represents the command being accepted, not the service-model
    # work that follows. The latter is surfaced by the normal [MEMORY:L-T]
    # progress card and must not keep the chat marker glowing.
    mark_runtime_action_completed(
        context,
        action="update_lt_facts",
        action_id=action_id,
    )


async def _wait_for_frame_request_boundary(
    frame_task,
    frame_request_event,
) -> None:
    """Start explicit L-T only after FRAME has emitted its request card."""
    if frame_task is None:
        return

    done = getattr(frame_task, "done", None)
    if callable(done) and done():
        return

    is_set = getattr(frame_request_event, "is_set", None)
    if frame_request_event is None or not callable(is_set):
        # No boundary signal exists (legacy/direct caller). Yield once so a
        # previously-created FRAME task still gets the first event-loop slot.
        await asyncio.sleep(0)
        return

    if is_set():
        return

    waiter = asyncio.create_task(frame_request_event.wait())
    try:
        await asyncio.wait(
            {waiter, frame_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
    finally:
        if not waiter.done():
            waiter.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await waiter


async def _run_update_lt_facts_entry(
    context,
    *,
    entry: dict,
) -> bool:
    """Run one queued note. Return False only when user preemption preserves it."""
    note = entry["note"]
    action_id = str(entry.get("action_id", "") or "")
    log_runtime = entry.get("log_runtime")
    attempt_generation = int(
        getattr(context, "runtime_lt_jin_note_generation", 0)
        or 0
    )

    try:
        result = await run_lt_jin_note(
            context=context,
            note=note,
        )

        if (
            str(result.get("status", "") or "") == "cancelled"
            and str(result.get("reason", "") or "") == "preempted"
        ):
            return False

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
        return True

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
        await log_memory_event(
            context,
            level="L-T",
            message=(
                "L-T JIN note failed: "
                f"{type(error).__name__}"
            ),
            details=str(error),
            fallback_channel="error",
            event="jin_note_failed",
        )
        _record_update_lt_tool_result(
            context,
            action_id=action_id,
            note=note,
            result=result,
        )
        return True

    finally:
        if (
            int(
                getattr(
                    context,
                    "runtime_lt_jin_note_request_visible_generation",
                    -1,
                )
            )
            == attempt_generation
        ):
            context.runtime_lt_jin_note_request_visible_generation = -1


async def _drain_update_lt_facts_queue(
    context,
    *,
    frame_task=None,
    frame_request_event=None,
) -> None:
    current_task = asyncio.current_task()

    try:
        await _wait_for_frame_request_boundary(
            frame_task,
            frame_request_event,
        )

        while True:
            queue = _ensure_update_lt_facts_queue(context)
            if not queue:
                return

            entry = queue[0]
            consumed = await _run_update_lt_facts_entry(
                context,
                entry=entry,
            )

            if not consumed:
                # User activity cancelled this attempt. Keep the exact queue
                # item at the head; the next completed Brain turn will kick it
                # again immediately after that turn's FRAME request starts.
                return

            if queue and queue[0] is entry:
                queue.pop(0)
            else:
                with contextlib.suppress(ValueError):
                    queue.remove(entry)

    finally:
        if getattr(context, "runtime_lt_memory_update_task", None) is current_task:
            context.runtime_lt_memory_update_task = None
            if str(getattr(context, "runtime_lt_memory_update_kind", "") or "") == "jin_note":
                context.runtime_lt_memory_update_kind = ""


def schedule_pending_update_lt_facts_actions(
    context,
    *,
    frame_task=None,
    frame_request_event=None,
) -> asyncio.Task | None:
    """Kick queued explicit notes without waiting for the browser idle timer."""
    if not _ensure_update_lt_facts_queue(context):
        return None

    running_task = getattr(
        context,
        "runtime_lt_memory_update_task",
        None,
    )
    running_kind = str(
        getattr(context, "runtime_lt_memory_update_kind", "")
        or ""
    )

    if (
        running_task is not None
        and not running_task.done()
    ):
        if running_kind == "jin_note":
            return running_task

        if running_kind == "idle":
            # Explicit JIN-directed work outranks idle consolidation. Do not
            # await provider cleanup here; foreground memory work should start
            # as soon as its FRAME ordering boundary is satisfied.
            running_task.cancel()
        else:
            return running_task

    task = asyncio.create_task(
        _drain_update_lt_facts_queue(
            context,
            frame_task=frame_task,
            frame_request_event=frame_request_event,
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
    return task


async def preempt_update_lt_facts_actions(
    context,
    *,
    reason: str = "user_activity",
) -> bool:
    """Cancel the active explicit L-T attempt while preserving its queue item."""
    task = getattr(
        context,
        "runtime_lt_memory_update_task",
        None,
    )
    kind = str(
        getattr(context, "runtime_lt_memory_update_kind", "")
        or ""
    )

    if task is None or task.done() or kind != "jin_note":
        return False

    generation = int(
        getattr(context, "runtime_lt_jin_note_generation", 0)
        or 0
    )
    request_visible = (
        int(
            getattr(
                context,
                "runtime_lt_jin_note_request_visible_generation",
                -1,
            )
        )
        == generation
    )

    # Invalidate this attempt before cancelling it. If a provider is slow to
    # unwind and still returns a response, run_lt_jin_note() will discard that
    # stale result instead of committing it beside the retried request.
    context.runtime_lt_jin_note_generation = generation + 1
    task.cancel()
    await asyncio.sleep(0)

    if task.done():
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task

    if getattr(context, "runtime_lt_memory_update_task", None) is task:
        context.runtime_lt_memory_update_task = None
    if str(getattr(context, "runtime_lt_memory_update_kind", "") or "") == "jin_note":
        context.runtime_lt_memory_update_kind = ""

    if request_visible:
        await log_memory_event(
            context,
            level="L-T",
            message=(
                "L-T JIN note preempted by "
                f"{str(reason or 'user_activity').strip() or 'user_activity'}; "
                "queued for ASAP retry"
            ),
            event="jin_note_preempted",
        )

    return True


async def schedule_update_lt_facts_actions(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
) -> list[asyncio.Task]:
    """Accept UPDATE_LT_FACTS now; execute it on the ordered L-T lane later."""
    queued_any = False

    for action in actions:
        note = parse_update_lt_facts_payload(action.payload)
        if not note:
            continue

        # Capture before queueing: the L-T request intentionally outlives this
        # Brain action dispatch and may be retried after the user's next turn.
        note["sources"] = _resolve_update_lt_fact_sources(context)

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

        _ensure_update_lt_facts_queue(context).append({
            "action_id": action_id,
            "note": note,
            "log_runtime": log_runtime,
        })
        queued_any = True

        await _emit_update_lt_facts_queued(
            context,
            action_id=action_id,
            payload=action.payload,
            with_action_context=with_action_context,
        )

    # Direct/unit callers have no foreground Brain->FRAME tail to kick the
    # queue, so preserve standalone behavior by starting immediately there.
    # Production chat keeps foreground_turn_running=True until process_message
    # schedules FRAME and explicitly starts this queue behind its request card.
    task = None
    if (
        queued_any
        and not bool(
            getattr(context, "runtime_foreground_turn_running", False)
        )
    ):
        task = schedule_pending_update_lt_facts_actions(
            context,
        )

    return [task] if task is not None else []
