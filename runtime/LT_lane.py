from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from runtime.memory_common import log_memory_event


@dataclass
class LTAttempt:
    id: str
    kind: str
    phase: str = ""
    task: asyncio.Task | None = None
    cancelled: bool = False
    request_visible: bool = False
    terminal_emitted: bool = False
    sealed: bool = False


class LTAttemptPreempted(RuntimeError):
    pass


def _wake_lt_scheduler(context) -> None:
    app_state = getattr(context, "runtime_lt_app_state", None)
    wake_event = getattr(app_state, "lt_memory_scheduler_wake_event", None)
    if wake_event is not None:
        wake_event.set()


def normalize_lt_attempt_phase(phase: str | None) -> str:
    normalized = str(phase or "").strip().casefold().replace("-", "_")
    if normalized in {"extract", "extraction"}:
        return "extraction"
    if normalized in {"merge"}:
        return "merge"
    if normalized in {"jin_note", "jin note", "explicit"}:
        return "jin_note"
    if normalized in {"waiting_frame", "waiting frame"}:
        return "waiting_frame"
    return normalized


def lt_attempt_log_metadata(
    attempt: LTAttempt | None,
    *,
    phase: str | None = None,
) -> dict:
    if attempt is None:
        return {}

    normalized_phase = normalize_lt_attempt_phase(
        phase if phase is not None else attempt.phase
    )
    return {
        "lt_flow_id": attempt.id,
        "lt_flow_kind": attempt.kind,
        **({"lt_phase": normalized_phase} if normalized_phase else {}),
    }


def get_active_lt_attempt(context) -> LTAttempt | None:
    attempt = getattr(context, "runtime_lt_active_attempt", None)
    return attempt if isinstance(attempt, LTAttempt) else None


def get_current_lt_attempt(context) -> LTAttempt | None:
    task = asyncio.current_task()
    if task is not None:
        attempt = getattr(task, "_jin_lt_attempt", None)
        if isinstance(attempt, LTAttempt):
            return attempt

    attempt = get_active_lt_attempt(context)
    if attempt is not None and attempt.task is task:
        return attempt
    return None


def begin_lt_attempt(
    context,
    *,
    kind: str,
    phase: str = "",
) -> LTAttempt:
    active = get_active_lt_attempt(context)
    if active is not None and not active.cancelled:
        task = active.task
        if task is None or not task.done():
            raise RuntimeError(
                f"L-T lane already occupied by {active.kind} attempt {active.id}"
            )

    attempt = LTAttempt(
        id=f"lt-{uuid.uuid4().hex}",
        kind=str(kind or "").strip().casefold() or "auto",
        phase=normalize_lt_attempt_phase(phase),
    )
    context.runtime_lt_active_attempt = attempt
    return attempt


def bind_lt_attempt_task(attempt: LTAttempt, task: asyncio.Task) -> None:
    attempt.task = task
    setattr(task, "_jin_lt_attempt", attempt)


def set_lt_attempt_phase(attempt: LTAttempt | None, phase: str) -> None:
    if attempt is not None:
        attempt.phase = normalize_lt_attempt_phase(phase)


def mark_lt_attempt_request_visible(attempt: LTAttempt | None) -> None:
    if attempt is not None:
        attempt.request_visible = True


def seal_lt_attempt(attempt: LTAttempt | None) -> None:
    if attempt is not None:
        attempt.sealed = True


def lt_attempt_can_commit(context, attempt: LTAttempt | None) -> bool:
    if attempt is None:
        return True
    return (
        not attempt.cancelled
        and get_active_lt_attempt(context) is attempt
    )


def assert_lt_attempt_can_commit(context, attempt: LTAttempt | None) -> None:
    if not lt_attempt_can_commit(context, attempt):
        raise LTAttemptPreempted("L-T attempt is no longer the active lane owner")


def release_lt_attempt(context, attempt: LTAttempt | None) -> None:
    if attempt is None:
        return

    if get_active_lt_attempt(context) is attempt:
        context.runtime_lt_active_attempt = None

    task = attempt.task
    if task is not None and getattr(task, "_jin_lt_attempt", None) is attempt:
        try:
            delattr(task, "_jin_lt_attempt")
        except AttributeError:
            pass

    _wake_lt_scheduler(context)


def runtime_lt_attempt_running(context) -> bool:
    attempt = get_active_lt_attempt(context)
    if attempt is None or attempt.cancelled:
        return False
    task = attempt.task
    return task is None or not task.done()


def mark_lt_priority_work_started(context) -> None:
    context.runtime_lt_priority_cycle_active = True
    _wake_lt_scheduler(context)


def lt_priority_work_busy(
    context,
    *,
    include_explicit_queue: bool = True,
) -> bool:
    if bool(getattr(context, "runtime_foreground_turn_running", False)):
        return True

    frame_task = getattr(context, "runtime_memory_update_task", None)
    if frame_task is not None and not frame_task.done():
        return True

    queue = getattr(context, "runtime_pending_requests_queue", None)
    if queue is not None:
        try:
            if not queue.empty():
                return True
        except Exception:
            pass

    if include_explicit_queue:
        explicit_queue = getattr(context, "runtime_lt_explicit_note_queue", None)
        if isinstance(explicit_queue, list) and explicit_queue:
            return True

    attempt = get_active_lt_attempt(context)
    if attempt is not None and attempt.kind == "explicit" and not attempt.cancelled:
        task = attempt.task
        if task is None or not task.done():
            return True

    return False


def maybe_mark_lt_priority_finished(context) -> bool:
    if not bool(getattr(context, "runtime_lt_priority_cycle_active", False)):
        return False
    if lt_priority_work_busy(context, include_explicit_queue=True):
        return False

    context.runtime_lt_priority_cycle_active = False
    context.runtime_lt_priority_finished_at = time.monotonic()
    _wake_lt_scheduler(context)
    return True


def track_lt_frame_task(context, task: asyncio.Task | None) -> None:
    if task is None:
        return

    mark_lt_priority_work_started(context)

    def _on_done(_task):
        maybe_mark_lt_priority_finished(context)
        _wake_lt_scheduler(context)

    task.add_done_callback(_on_done)


def invalidate_lt_attempt(
    context,
    attempt: LTAttempt,
) -> bool:
    if attempt.cancelled or attempt.sealed:
        return False

    attempt.cancelled = True
    if get_active_lt_attempt(context) is attempt:
        context.runtime_lt_active_attempt = None

    task = attempt.task
    if task is not None and not task.done():
        task.cancel()

    _wake_lt_scheduler(context)
    return True


async def emit_lt_attempt_preempted(
    context,
    attempt: LTAttempt,
    *,
    reason: str,
) -> None:
    if not attempt.request_visible or attempt.terminal_emitted:
        return

    attempt.terminal_emitted = True
    phase = normalize_lt_attempt_phase(attempt.phase)
    label = "JIN note" if attempt.kind == "explicit" else "background update"
    normalized_reason = str(reason or "user_activity").strip() or "user_activity"
    await log_memory_event(
        context,
        level="L-T",
        message=(
            f"L-T {label} preempted by {normalized_reason}; "
            + (
                "queued for ASAP retry"
                if attempt.kind == "explicit"
                else "pending preserved"
            )
        ),
        event="lt_preempted",
        **lt_attempt_log_metadata(attempt, phase=phase),
    )


async def preempt_lt_attempt(
    context,
    *,
    kind: str | None = None,
    reason: str = "user_activity",
) -> bool:
    attempt = get_active_lt_attempt(context)
    if attempt is None:
        return False
    if kind is not None and attempt.kind != str(kind).strip().casefold():
        return False

    changed = invalidate_lt_attempt(context, attempt)
    if not changed:
        return False

    # Deliver cancellation to a cooperative provider without waiting for a
    # stubborn transport to unwind. The attempt identity already prevents any
    # late response from committing after this point.
    await asyncio.sleep(0)
    await emit_lt_attempt_preempted(
        context,
        attempt,
        reason=reason,
    )
    maybe_mark_lt_priority_finished(context)
    return True


def preempt_lt_attempt_nowait(
    context,
    *,
    kind: str | None = None,
    reason: str = "priority_work",
) -> bool:
    attempt = get_active_lt_attempt(context)
    if attempt is None:
        return False
    if kind is not None and attempt.kind != str(kind).strip().casefold():
        return False

    changed = invalidate_lt_attempt(context, attempt)
    if not changed:
        return False

    if attempt.request_visible and not attempt.terminal_emitted:
        log_task = asyncio.create_task(
            emit_lt_attempt_preempted(
                context,
                attempt,
                reason=reason,
            )
        )
        background_tasks = getattr(context, "background_tasks", None)
        if background_tasks is None:
            background_tasks = set()
            context.background_tasks = background_tasks
        background_tasks.add(log_task)
        log_task.add_done_callback(background_tasks.discard)

    maybe_mark_lt_priority_finished(context)
    return True
