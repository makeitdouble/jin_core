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
from runtime.LT_lane import (
    begin_lt_attempt,
    bind_lt_attempt_task,
    get_active_lt_attempt,
    get_current_lt_attempt,
    lt_attempt_log_metadata,
    mark_lt_priority_work_started,
    maybe_mark_lt_priority_finished,
    preempt_lt_attempt,
    preempt_lt_attempt_nowait,
    release_lt_attempt,
    set_lt_attempt_phase,
)
from runtime.memory_common import log_memory_event
from utils.actions.update_lt_facts_utils import parse_update_lt_facts_payload
from utils.chat_log import append_chat_runtime_event
from utils.tool_results import (
    TOOL_RESULT_KIND_LT,
    record_runtime_tool_result,
)
from utils.runtime_action_abort import mark_runtime_action_completed


def _bind_update_lt_frame_gate(
    context,
    *,
    frame_task=None,
    frame_request_event=None,
) -> None:
    """Bind the current turn's FRAME boundary to still-unclaimed LT notes."""
    for entry in _ensure_update_lt_facts_queue(context):
        if entry.get("_lt_frame_gate_bound"):
            continue
        entry["_lt_frame_gate_bound"] = True
        entry["_lt_frame_task"] = frame_task
        entry["_lt_frame_request_event"] = frame_request_event


def _clear_update_lt_frame_gates(context) -> None:
    """Force every pending explicit note to wait for the next FRAME boundary."""
    for entry in _ensure_update_lt_facts_queue(context):
        entry["_lt_frame_gate_bound"] = False
        entry["_lt_frame_task"] = None
        entry["_lt_frame_request_event"] = None


def _resume_explicit_lt_after_task(context, task: asyncio.Task) -> None:
    """Resume a queued explicit note after a sealed auto commit finishes."""
    marker = "_jin_lt_explicit_resume_registered"
    if getattr(task, marker, False):
        return
    setattr(task, marker, True)

    def _resume(_task):
        queue = _ensure_update_lt_facts_queue(context)
        if not queue:
            maybe_mark_lt_priority_finished(context)
            return

        # schedule_pending_update_lt_facts_actions() originally bound this
        # queue item to a concrete FRAME gate before the sealed auto tail was
        # allowed to finish. A newer USER turn clears that binding. Do not
        # accidentally turn the callback into an immediate/no-FRAME launch;
        # the new turn will bind the item again at its own FRAME boundary.
        if not queue[0].get("_lt_frame_gate_bound"):
            return

        schedule_pending_update_lt_facts_actions(context)

    task.add_done_callback(_resume)


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
    done = getattr(frame_task, "done", None)
    if frame_task is not None and callable(done) and done():
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
        if frame_task is None:
            await waiter
        else:
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
    """Run one queued note; False preserves the exact queue item for retry."""
    note = entry["note"]
    action_id = str(entry.get("action_id", "") or "")
    log_runtime = entry.get("log_runtime")

    try:
        result = await run_lt_jin_note(
            context=context,
            note=note,
        )

        status = str(result.get("status", "") or "")
        reason = str(result.get("reason", "") or "")
        if status == "cancelled" and reason == "preempted":
            return False

        # A concurrent direct L-T edit is a transient conflict, not successful
        # consumption of Brain's queued instruction. Preserve it for the next
        # ordered explicit attempt instead of silently dropping the command.
        if status == "skipped" and reason == "store_changed_during_jin_note":
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
        attempt = get_current_lt_attempt(context)
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
            **lt_attempt_log_metadata(attempt, phase="jin_note"),
        )
        _record_update_lt_tool_result(
            context,
            action_id=action_id,
            note=note,
            result=result,
        )
        return True


async def _drain_update_lt_facts_queue(
    context,
    *,
    frame_task=None,
    frame_request_event=None,
) -> None:
    current_task = asyncio.current_task()

    try:
        while True:
            queue = _ensure_update_lt_facts_queue(context)
            if not queue:
                return

            entry = queue[0]
            if not entry.get("_lt_frame_gate_bound"):
                return

            await _wait_for_frame_request_boundary(
                entry.get("_lt_frame_task", frame_task),
                entry.get("_lt_frame_request_event", frame_request_event),
            )

            attempt = get_current_lt_attempt(context)
            if attempt is None:
                attempt = begin_lt_attempt(
                    context,
                    kind="explicit",
                    phase="jin_note",
                )
                bind_lt_attempt_task(attempt, current_task)
            else:
                set_lt_attempt_phase(attempt, "jin_note")

            consumed = await _run_update_lt_facts_entry(
                context,
                entry=entry,
            )

            if not consumed:
                # Preemption or a transient store conflict keeps this logical
                # command at the head. Rebind it to the next foreground FRAME
                # boundary before retrying with a fresh flow id.
                entry["_lt_frame_gate_bound"] = False
                entry["_lt_frame_task"] = None
                entry["_lt_frame_request_event"] = None
                return

            if queue and queue[0] is entry:
                queue.pop(0)
            else:
                with contextlib.suppress(ValueError):
                    queue.remove(entry)

            release_lt_attempt(context, attempt)
            if queue and queue[0].get("_lt_frame_gate_bound"):
                next_attempt = begin_lt_attempt(
                    context,
                    kind="explicit",
                    phase="waiting_frame",
                )
                bind_lt_attempt_task(next_attempt, current_task)
            elif queue:
                return

    finally:
        release_lt_attempt(
            context,
            get_current_lt_attempt(context),
        )
        maybe_mark_lt_priority_finished(context)


def schedule_pending_update_lt_facts_actions(
    context,
    *,
    frame_task=None,
    frame_request_event=None,
) -> asyncio.Task | None:
    """Kick queued explicit notes on the single ordered L-T lane."""
    if not _ensure_update_lt_facts_queue(context):
        maybe_mark_lt_priority_finished(context)
        return None

    _bind_update_lt_frame_gate(
        context,
        frame_task=frame_task,
        frame_request_event=frame_request_event,
    )

    active = get_active_lt_attempt(context)
    if active is not None:
        task = active.task
        if task is not None and task.done():
            release_lt_attempt(context, active)
            active = None
        elif active.kind == "explicit":
            return task
        elif active.kind == "auto":
            # Explicit Brain-directed work outranks consolidation. If the auto
            # attempt has not committed yet, invalidate it immediately. A sealed
            # attempt has already crossed its atomic commit boundary, so let its
            # short post-commit tail finish and resume this queue afterwards.
            preempted = preempt_lt_attempt_nowait(
                context,
                kind="auto",
                reason="explicit_update",
            )
            if not preempted:
                if task is not None and not task.done():
                    _resume_explicit_lt_after_task(context, task)
                    return task
                release_lt_attempt(context, active)
        else:
            return task

    mark_lt_priority_work_started(context)
    attempt = begin_lt_attempt(
        context,
        kind="explicit",
        phase="waiting_frame",
    )
    try:
        task = asyncio.create_task(
            _drain_update_lt_facts_queue(
                context,
                frame_task=frame_task,
                frame_request_event=frame_request_event,
            )
        )
    except Exception:
        release_lt_attempt(context, attempt)
        raise
    bind_lt_attempt_task(attempt, task)

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
    """Cancel the active explicit attempt while preserving its queue item."""
    # A new foreground turn rebinds every still-pending explicit command to
    # that turn's FRAME boundary. Do this even when the active attempt is
    # already sealed: its committed tail may finish, but it must not start the
    # next queued command underneath the new Brain turn.
    if _ensure_update_lt_facts_queue(context):
        _clear_update_lt_frame_gates(context)

    return await preempt_lt_attempt(
        context,
        kind="explicit",
        reason=reason,
    )


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
            "_lt_frame_gate_bound": False,
            "_lt_frame_task": None,
            "_lt_frame_request_event": None,
        })
        mark_lt_priority_work_started(context)
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
