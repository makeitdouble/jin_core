import asyncio
import contextlib
import traceback
from clients.service_client import (
    ask_service_model,
)
from config_loader import (
    config,
)
from runtime.L1_memory_rules import (
    build_runtime_memory_system_prompt,
)
from runtime.L1_memory_pending import (
    clear_pending_l1_update,
    persist_pending_l1_update,
)
from rules.signal import (
    RUNTIME_RESPONSE_FEEDBACK_RATINGS,
)
from runtime.memory_common import (
    build_memory_failure_details,
    build_memory_update_skip_details,
    build_runtime_summarizer_payload,
    build_runtime_summarizer_response_details,
    extract_runtime_memory_text,
    is_runtime_memory_response_truncated,
    latest_turn_context_is_overloaded,
    log_memory_event,
    log_runtime_summarizer_payload,
    looks_like_incomplete_runtime_memory,
    refresh_service_runtime_usage,
    runtime_prompt_is_context_overloaded,
)
from runtime.L1_memory_utils import (
    emit_runtime_memory_update,
    record_runtime_l1_diff,
)
from runtime.L1_memory_utils import (
    build_empty_assistant_message,
    build_interrupted_assistant_message,
    build_runtime_response_feedback_value,
    build_runtime_memory_batch_user_prompt,
    build_runtime_memory_snapshot,
    build_runtime_memory_user_prompt,
    get_strength_zones,
    normalize_compound_runtime_memory_lines,
    parse_runtime_memory_lines,
    remove_runtime_response_feedback_text,
    remove_runtime_user_idle_lines,
)
from utils.actions import (
    refresh_active_memory_runtime_metadata,
    remove_active_memory_entries,
)


def normalize_runtime_response_feedback(feedback) -> dict | None:

    if not isinstance(feedback, dict):
        return None

    raw_rating = str(
        feedback.get("rating")
        or ""
    ).strip().casefold()

    rating = RUNTIME_RESPONSE_FEEDBACK_RATINGS.get(
        raw_rating
    )

    if rating is None:
        return None

    normalized = {
        "rating": rating,
    }

    try:
        clicks_count = int(
            feedback.get("clicks_count")
            or feedback.get("clicksCount")
            or feedback.get("activeRatingClickCount")
            or feedback.get("bubbleClickCount")
            or 0
        )
    except (TypeError, ValueError):
        clicks_count = 0

    if clicks_count > 0:
        normalized["clicks_count"] = clicks_count

    return normalized


def resolve_frame_language_user_message(context, user_message: str) -> str:
    if str(user_message or "").strip():
        return user_message

    # Hidden bootstrap has no USER text. Use the newest real USER move from
    # the hydrated session, skipping JIN-only continuation rows.
    for turn in reversed(getattr(context, "runtime_recent_turns", []) or []):
        if not isinstance(turn, dict):
            continue
        previous_user_message = str(turn.get("user", "") or "").strip()
        if previous_user_message:
            return previous_user_message
    return ""


def build_runtime_memory_system_prompt_for_turn(
        *,
        current_memory: str,
        user_message: str,
        last_turn_context_overloaded: bool = False,
        context=None,
) -> str:

    return build_runtime_memory_system_prompt(
        current_memory=current_memory,
        user_message=resolve_frame_language_user_message(context, user_message),
        last_turn_context_overloaded=last_turn_context_overloaded,
    )


def build_runtime_memory_system_prompt_for_turns(
        *,
        current_memory: str,
        turns: list[dict],
        last_turn_context_overloaded: bool = False,
        context=None,
) -> str:

    user_messages = [
        str(
            turn.get(
                "user_message",
                "",
            )
            or ""
        ).strip()
        for turn in (
            turns
            or []
        )
    ]

    return build_runtime_memory_system_prompt_for_turn(
        current_memory=current_memory,
        context=context,
        user_message="\n".join(
            message
            for message in user_messages
            if message
        ),
        last_turn_context_overloaded=last_turn_context_overloaded,
    )


def clear_runtime_response_feedback(
        context,
) -> None:

    if context is None:
        return

    context.runtime_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )

    context.runtime_memory_stable = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory_stable",
            "",
        )
    )

    context.runtime_last_response_feedback = None


async def apply_runtime_response_feedback(
        context,
        feedback,
) -> dict | None:

    normalized_feedback = normalize_runtime_response_feedback(
        feedback
    )

    if normalized_feedback is None:
        return None

    current_memory = getattr(
        context,
        "runtime_memory",
        "",
    )

    cleaned_memory = remove_runtime_response_feedback_text(
        current_memory
    )

    context.runtime_last_response_feedback = normalized_feedback

    if cleaned_memory != current_memory:
        context.runtime_memory = cleaned_memory

    return {
        "applied": True,
        "rating": normalized_feedback["rating"],
        "runtime_memory": cleaned_memory,
    }

async def ask_frame_summarizer(
        *,
        context,
        service_client,
        label: str,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int | None,
) -> dict:

    await log_runtime_summarizer_payload(
        context,
        label=label,
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            stream=False,
        ),
    )

    try:
        return await ask_service_model(
            client=service_client,
            context=context,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=config.SERVICE_REQUEST_TIMEOUT,
            track_usage=False,
        )
    except asyncio.CancelledError:
        await log_memory_event(
            context,
            level="FRAME",
            message="FRAME summarizer cancelled",
            details="The FRAME request was cancelled before completion.",
            event="summarizer_cancelled",
        )
        raise


async def ask_runtime_memory_model(
        *,
        context=None,
        service_client,
        current_memory: str,
        user_message: str,
        assistant_message: str,
) -> dict:

    resolve_request_context_window = getattr(
        service_client,
        "resolve_request_context_window",
        None,
    )
    detected_context_window = None

    if resolve_request_context_window is not None:
        detected_context_window = (
            await resolve_request_context_window()
        )

    system_prompt = build_runtime_memory_system_prompt_for_turn(
        context=context,
        current_memory=current_memory,
        user_message=user_message,
    )
    _snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )
    _latest_lines = (
        _snapshots[-1].get("lines", [])
        if _snapshots
        else []
    )
    user_prompt = build_runtime_memory_user_prompt(
        current_memory=current_memory,
        user_message=user_message,
        assistant_message=assistant_message,
        strength_zones=get_strength_zones(
            _latest_lines
        ),
    )

    last_turn_context_overloaded = (
        latest_turn_context_is_overloaded(
            context
        )
        or runtime_prompt_is_context_overloaded(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            context_window=detected_context_window,
        )
    )

    if last_turn_context_overloaded:
        system_prompt = build_runtime_memory_system_prompt_for_turn(
            context=context,
            current_memory=current_memory,
            user_message=user_message,
            last_turn_context_overloaded=True,
        )

    await refresh_service_runtime_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context_window=detected_context_window,
    )

    temperature = (
        config.SERVICE_TEMPERATURE
    )
    max_tokens = None

    response = await ask_frame_summarizer(
        context=context,
        service_client=service_client,
        label="FRAME",
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    await refresh_service_runtime_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response=response,
        context_window=detected_context_window,
    )

    return response


async def ask_runtime_memory_batch_model(
        *,
        context=None,
        service_client,
        current_memory: str,
        turns: list[dict],
) -> dict:

    system_prompt = build_runtime_memory_system_prompt_for_turns(
        context=context,
        current_memory=current_memory,
        turns=turns,
    )
    _snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )
    _latest_lines = (
        _snapshots[-1].get("lines", [])
        if _snapshots
        else []
    )
    user_prompt = build_runtime_memory_batch_user_prompt(
        current_memory=current_memory,
        turns=turns,
        strength_zones=get_strength_zones(
            _latest_lines
        ),
    )

    await refresh_service_runtime_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    temperature = (
        config.SERVICE_TEMPERATURE
    )
    max_tokens = None
    log_label = (
        "FRAME batch"
        if len(turns) > 1
        else "FRAME"
    )

    response = await ask_frame_summarizer(
        context=context,
        service_client=service_client,
        label=log_label,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
    )

    await refresh_service_runtime_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        response=response,
    )

    return response


async def summarize_runtime_memory(
        *,
        context,
        user_message: str,
        assistant_message: str,
) -> str:

    if not assistant_message.strip():
        stored_memory = remove_runtime_response_feedback_text(
            getattr(
                context,
                "runtime_memory",
                "",
            )
        )
        updated_memory = remove_active_memory_entries(
            stored_memory
        )
        context.runtime_memory = updated_memory
        context.runtime_memory_stable = updated_memory
        return updated_memory

    service_client = (
        getattr(
            context,
            "clients",
            {},
        )
        .get(
            "service"
        )
    )

    if service_client is None:
        stored_memory = remove_runtime_response_feedback_text(
            getattr(
                context,
                "runtime_memory",
                "",
            )
        )
        updated_memory = remove_active_memory_entries(
            stored_memory
        )
        context.runtime_memory = updated_memory
        context.runtime_memory_stable = updated_memory
        return updated_memory

    stored_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )
    stored_memory = remove_active_memory_entries(
        stored_memory
    )
    current_memory = stored_memory

    context.runtime_memory = stored_memory
    context.runtime_memory_stable = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory_stable",
            "",
        )
    )
    context.runtime_last_response_feedback = None

    try:
        response = await ask_runtime_memory_model(
            context=context,
            service_client=service_client,
            current_memory=current_memory,
            user_message=user_message,
            assistant_message=assistant_message,
        )

        updated_memory = extract_runtime_memory_text(
            response,
        )
        updated_memory = normalize_compound_runtime_memory_lines(
            updated_memory
        )
        context.runtime_l1_last_summarizer_response_details = (
            build_runtime_summarizer_response_details(
                response,
                extracted_memory=updated_memory,
            )
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )

        if (
                is_runtime_memory_response_truncated(
                    response
                )
                or looks_like_incomplete_runtime_memory(
            updated_memory
        )
        ):
            await log_memory_event(
                context,
                level="FRAME",
                message="FRAME runtime memory update skipped",
                event="summarizer_skipped",
                details=build_memory_update_skip_details(
                    reason="Summarizer returned an incomplete memory update.",
                    previous_memory=current_memory,
                    candidate_memory=updated_memory,
                    summarizer_response_details=(
                        context.runtime_l1_last_summarizer_response_details
                    ),
                ),
                fallback_channel="error",
            )

            return stored_memory

        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_user_idle_lines(
            updated_memory
        )
        updated_memory = remove_active_memory_entries(
            updated_memory
        )

        updates_counter = getattr(
            context,
            "runtime_memory_updates",
            0,
        )

        if updated_memory or updates_counter == 0:
            context.runtime_memory = updated_memory
            context.runtime_memory_stable = updated_memory
            context.runtime_memory_updates = updates_counter + 1

            snapshot = await emit_runtime_memory_update(
                context
            )

            await record_runtime_l1_diff(
                context,
                snapshot,
                turns=[
                    {
                        "user_message": user_message,
                        "assistant_message": assistant_message,
                    },
                ],
            )

        else:
            await log_memory_event(
                context,
                level="FRAME",
                message="FRAME empty extraction skipped",
                details="The summarizer returned no FRAME fields; existing memory was retained.",
                event="summarizer_skipped",
            )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    except asyncio.CancelledError:
        raise

    except Exception as error:
        formatted_traceback = (
            traceback.format_exc()
        )

        await log_memory_event(
            context,
            level="FRAME",
            message="FRAME runtime memory update failed",
            event="summarizer_failed",
            details=build_memory_failure_details(
                stage="FRAME runtime memory summarizer",
                error=error,
                traceback_text=formatted_traceback,
            ),
            fallback_channel="error",
        )

        return getattr(
            context,
            "runtime_memory",
            "",
        )


async def summarize_runtime_memory_pending_turns(
        *,
        context,
) -> str:

    turns = list(
        context.runtime_memory_pending_turns
    )

    if not turns:
        return getattr(
            context,
            "runtime_memory",
            "",
        )

    service_client = (
        getattr(
            context,
            "clients",
            {},
        )
        .get(
            "service"
        )
    )

    if service_client is None:
        return getattr(
            context,
            "runtime_memory",
            "",
        )

    stored_initial_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory_stable",
            "",
        )
    )
    stored_initial_memory = remove_active_memory_entries(
        stored_initial_memory
    )
    initial_memory = stored_initial_memory

    context.runtime_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )
    context.runtime_memory_stable = stored_initial_memory
    context.runtime_last_response_feedback = None

    try:
        response = await ask_runtime_memory_batch_model(
            context=context,
            service_client=service_client,
            current_memory=initial_memory,
            turns=turns,
        )

        updated_memory = extract_runtime_memory_text(
            response,
        )
        updated_memory = normalize_compound_runtime_memory_lines(
            updated_memory
        )
        context.runtime_l1_last_summarizer_response_details = (
            build_runtime_summarizer_response_details(
                response,
                extracted_memory=updated_memory,
            )
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )

        skip_reason = None

        if is_runtime_memory_response_truncated(response):
            skip_reason = "Summarizer response was truncated by max_tokens."

        elif looks_like_incomplete_runtime_memory(updated_memory):
            skip_reason = "Summarizer returned text that looks structurally incomplete."

        if skip_reason:
            await log_memory_event(
                context,
                level="FRAME",
                message="FRAME runtime memory update skipped",
                event="summarizer_skipped",
                details=build_memory_update_skip_details(
                    reason="Summarizer returned an incomplete memory update.",
                    previous_memory=initial_memory,
                    candidate_memory=updated_memory,
                    summarizer_response_details=(
                        context.runtime_l1_last_summarizer_response_details
                    ),
                ),
                fallback_channel="error",
            )

            return stored_initial_memory

        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )

        updated_memory = remove_runtime_user_idle_lines(
            updated_memory
        )
        updated_memory = remove_active_memory_entries(
            updated_memory
        )

        updates_counter = getattr(
            context,
            "runtime_memory_updates",
            0,
        )

        if updated_memory or updates_counter == 0:
            context.runtime_memory = updated_memory
            context.runtime_memory_stable = updated_memory
            context.runtime_memory_updates = updates_counter + 1

            context.runtime_memory_pending_turns = [
                turn
                for turn in context.runtime_memory_pending_turns
                if turn not in turns
            ]

            if context.runtime_memory_pending_turns:
                context.runtime_memory_pending_base_updates = (
                    context.runtime_memory_updates
                )
                persist_pending_l1_update(
                    context
                )

            snapshot = await emit_runtime_memory_update(
                context
            )

            await record_runtime_l1_diff(
                context,
                snapshot,
                turns=turns,
            )

        else:
            await log_memory_event(
                context,
                level="FRAME",
                message="FRAME empty extraction skipped",
                details="The summarizer returned no FRAME fields; existing memory was retained.",
                event="summarizer_skipped",
            )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    except asyncio.CancelledError:
        raise

    except Exception as error:
        formatted_traceback = (
            traceback.format_exc()
        )

        await log_memory_event(
            context,
            level="FRAME",
            message="FRAME runtime memory update failed",
            event="summarizer_failed",
            details=build_memory_failure_details(
                stage="FRAME pending runtime memory summarizer",
                error=error,
                traceback_text=formatted_traceback,
            ),
            fallback_channel="error",
        )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    finally:
        if (
                getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )
                is asyncio.current_task()
        ):
            context.runtime_memory_update_task = None


def _start_runtime_memory_update_task(
        context,
) -> asyncio.Task:

    previous_task = getattr(
        context,
        "runtime_memory_update_task",
        None,
    )

    if (
            previous_task is not None
            and not previous_task.done()
    ):
        previous_task.cancel()

    task = asyncio.create_task(
        summarize_runtime_memory_pending_turns(
            context=context,
        )
    )

    context.runtime_memory_update_task = task

    background_tasks = getattr(
        context,
        "background_tasks",
        None,
    )

    if background_tasks is None:
        background_tasks = set()
        context.background_tasks = background_tasks

    background_tasks.add(
        task
    )
    task.add_done_callback(
        background_tasks.discard
    )

    return task


def resume_runtime_memory_pending_update(
        context,
) -> asyncio.Task | None:

    pending_turns = getattr(
        context,
        "runtime_memory_pending_turns",
        [],
    )

    if not pending_turns:
        return None

    running_task = getattr(
        context,
        "runtime_memory_update_task",
        None,
    )

    if (
            running_task is not None
            and not running_task.done()
    ):
        return running_task

    try:
        base_updates = int(
            getattr(
                context,
                "runtime_memory_pending_base_updates",
                0,
            )
            or 0
        )
        current_updates = int(
            getattr(
                context,
                "runtime_memory_updates",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        base_updates = 0
        current_updates = 0

    # The pending journal records the L1 revision that existed before the
    # request. A newer persisted revision proves that the browser already
    # received this commit; otherwise replay is the safe crash-recovery path.
    if current_updates > base_updates:
        context.runtime_memory_pending_turns = []
        clear_pending_l1_update(
            context
        )
        return None

    # The journal is also the monotonic revision floor. If an older
    # bootstrap omitted the counter, the replay must still commit past the
    # revision at which this pending request began.
    context.runtime_memory_updates = max(
        current_updates,
        base_updates,
    )

    return _start_runtime_memory_update_task(
        context
    )

def schedule_runtime_memory_update(
        *,
        context,
        user_message: str,
        assistant_message: str,
) -> asyncio.Task | None:

    # Normal turns without a visible assistant answer or a created
    # active-memory record carry no
    # textual signal of their own. Previously such turns were skipped
    # outright — but "the model produced nothing" is itself a fact
    # (e.g. the user explicitly asked for a blank/empty reply and got
    # one), and silently dropping the turn means L1 never learns the
    # request happened at all. Instead of skipping, such turns are still
    # enqueued with an explicit placeholder describing the emptiness, so
    # L1 records the exchange as resolved rather than losing it.
    if (
            not assistant_message.strip()
            and not getattr(
                context,
                "runtime_active_memory_saved_this_turn",
                False,
            )
    ):

        if not user_message.strip():
            return None

        assistant_message = build_empty_assistant_message(
            user_message=user_message,
        )

    context.runtime_memory_pending_turns.append({
        "user_message": user_message,
        "assistant_message": assistant_message,
    })

    if len(context.runtime_memory_pending_turns) == 1:
        context.runtime_memory_pending_base_updates = getattr(
            context,
            "runtime_memory_updates",
            0,
        )

    persist_pending_l1_update(
        context
    )

    return _start_runtime_memory_update_task(
        context
    )


def schedule_interrupted_runtime_memory_update(
        *,
        context,
) -> asyncio.Task | None:

    if getattr(
        context,
        "runtime_turn_interrupted_memory_update_scheduled",
        False,
    ):
        return getattr(
            context,
            "runtime_memory_update_task",
            None,
        )

    user_message = getattr(
        context,
        "runtime_turn_user_message",
        "",
    )

    assistant_message = (
        build_interrupted_assistant_message(
            user_message=user_message,
            assistant_message=getattr(
                context,
                "runtime_turn_assistant_response",
                "",
            ),
            interruption_reason=getattr(
                context,
                "runtime_turn_interruption_reason",
                "",
            ),
            interruption_quote=getattr(
                context,
                "runtime_turn_interruption_quote",
                "",
            ),
            aborted_actions=getattr(
                context,
                "runtime_turn_aborted_actions",
                [],
            ),
        )
    )

    if not user_message.strip():
        return None

    context.runtime_turn_interrupted_memory_update_scheduled = True

    return schedule_runtime_memory_update(
        context=context,
        user_message=user_message,
        assistant_message=assistant_message,
    )


async def cancel_runtime_memory_update(
        context,
) -> None:

    task = getattr(
        context,
        "runtime_memory_update_task",
        None,
    )

    if (
            task is None
            or task.done()
    ):
        return

    task.cancel()

    with contextlib.suppress(
            asyncio.CancelledError,
            Exception,
    ):
        await task

    context.runtime_memory_update_task = None


async def discard_latest_runtime_memory_pending_turn(
        context,
) -> bool:
    """Drop the pending L1 turn that is being replaced by a user retry."""

    await cancel_runtime_memory_update(
        context
    )

    pending_turns = list(
        getattr(
            context,
            "runtime_memory_pending_turns",
            [],
        )
        or []
    )

    if not pending_turns:
        return False

    pending_turns.pop()
    context.runtime_memory_pending_turns = pending_turns

    if pending_turns:
        persist_pending_l1_update(
            context
        )
        resume_runtime_memory_pending_update(
            context
        )
    else:
        context.runtime_memory_pending_base_updates = getattr(
            context,
            "runtime_memory_updates",
            0,
        )
        clear_pending_l1_update(
            context
        )

    return True
