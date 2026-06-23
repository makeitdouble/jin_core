import asyncio
import contextlib
import json
import traceback
from clients.service_client import (
    ask_service_model,
)
from config_loader import (
    config,
)
from runtime.fact_check import (
    ensure_confirmable_memory_markers,
)
from runtime.L1_memory_rules import (
    RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_KEY,
    RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_RATINGS,
    build_runtime_memory_system_prompt,
)
from runtime.L2_memory import (
    maybe_summarize_runtime_l2_memory,
    record_runtime_l1_diff,
)
from runtime.L3_memory import (
    maybe_summarize_runtime_session_memory,
)
from runtime.memory_common import (
    build_memory_failure_details,
    build_memory_update_skip_details,
    build_runtime_summarizer_payload,
    build_runtime_summarizer_response_details,
    extract_runtime_memory_text,
    is_runtime_memory_response_truncated,
    latest_turn_context_is_overloaded,
    log_active_memory_event,
    log_memory_event,
    log_runtime_summarizer_payload,
    looks_like_incomplete_runtime_memory,
    refresh_runtime_memory_summarizer_usage,
    runtime_prompt_is_context_overloaded,
)
from runtime.memory_events import (
    emit_runtime_memory_update,
)
from runtime.L1_memory_utils import (
    build_interrupted_assistant_message,
    build_runtime_memory_batch_user_prompt,
    build_runtime_memory_snapshot,
    build_runtime_memory_user_prompt,
    durable_memory_line_text,
    enforce_runtime_turn_fields,
    enrich_active_memory_recall_conditions,
    get_strength_zones,
    has_durable_fact_negation,
    ensure_active_memory_status_suffixes,
    is_durable_memory_key,
    is_runtime_memory_repeatable_key_family,
    normalize_managed_runtime_memory_slots,
    normalize_memory_key,
    normalize_runtime_memory_key_family,
    parse_runtime_memory_lines,
    refresh_active_memory_runtime_metadata,
    repeatable_runtime_memory_values_are_same_slot,
    remove_runtime_memory_placeholder_lines,
    remove_runtime_response_feedback_text,
    remove_runtime_user_idle_lines,
    strip_active_memory_runtime_metadata,
    upsert_runtime_memory_entry_text,
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

    return {
        "rating": rating,
    }


def build_runtime_response_feedback_value(feedback: dict) -> str:

    rating = feedback.get(
        "rating",
        "neutral",
    )

    if rating == "disliked":
        return RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE

    if rating == "liked":
        return RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE

    return RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE





def build_runtime_memory_system_prompt_for_turn(
        *,
        current_memory: str,
        user_message: str,
        last_turn_context_overloaded: bool = False,
) -> str:

    return build_runtime_memory_system_prompt(
        current_memory=current_memory,
        user_message=user_message,
        last_turn_context_overloaded=last_turn_context_overloaded,
    )


def build_runtime_memory_system_prompt_for_turns(
        *,
        current_memory: str,
        turns: list[dict],
        last_turn_context_overloaded: bool = False,
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
        user_message="\n".join(
            message
            for message in user_messages
            if message
        ),
        last_turn_context_overloaded=last_turn_context_overloaded,
    )


async def normalize_active_memory_slots_with_logging(
        context,
        *,
        previous_memory: str,
        candidate_memory: str,
        stage: str,
) -> str:

    collapse_events = []
    result_memory = normalize_managed_runtime_memory_slots(
        previous_memory,
        candidate_memory,
        collapse_events=collapse_events,
    )

    if collapse_events:
        await log_active_memory_event(
            context,
            message=(
                "active_memory duplicate collapsed"
                if len(collapse_events) == 1
                else f"active_memory duplicates collapsed ({len(collapse_events)})"
            ),
            details=json.dumps(
                {
                    "stage": stage,
                    "events": collapse_events,
                    "previous_memory": previous_memory,
                    "candidate_memory": candidate_memory,
                    "result_memory": result_memory,
                },
                ensure_ascii=False,
                indent=2,
            ),
            event="collapse",
        )

    return result_memory


def clear_runtime_response_feedback(
        context,
) -> None:

    if context is None:
        return

    context.runtime_memory = remove_runtime_memory_placeholder_lines(
        remove_runtime_response_feedback_text(
            getattr(
                context,
                "runtime_memory",
                "",
            )
        )
    )

    context.runtime_memory_stable = remove_runtime_memory_placeholder_lines(
        remove_runtime_response_feedback_text(
            getattr(
                context,
                "runtime_memory_stable",
                "",
            )
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

    value = build_runtime_response_feedback_value(
        normalized_feedback
    )

    current_memory = getattr(
        context,
        "runtime_memory",
        "",
    )

    cleaned_memory = remove_runtime_response_feedback_text(
        current_memory
    )

    updated_memory = upsert_runtime_memory_entry_text(
        cleaned_memory,
        RUNTIME_RESPONSE_FEEDBACK_KEY,
        value,
    )

    if updated_memory == current_memory:
        context.runtime_last_response_feedback = normalized_feedback
        return None

    context.runtime_memory = updated_memory
    context.runtime_last_response_feedback = normalized_feedback

    # Rating clicks are an in-place mutation of the current L1 snapshot.
    # Do not increment runtime_memory_updates and do not emit
    # runtime_memory_update here, otherwise the UI creates a new runtime page.
    # This is a transient next-turn alert, not durable L1 memory.
    # Keep runtime_memory_stable clean so L1 cannot preserve it.
    return {
        "applied": True,
        "rating": normalized_feedback["rating"],
        "runtime_memory": updated_memory,
    }

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
            current_memory=current_memory,
            user_message=user_message,
            last_turn_context_overloaded=True,
        )

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context_window=detected_context_window,
    )

    temperature = (
        config.SERVICE_TEMPERATURE
    )
    max_tokens = (
        config.SERVICE_MAX_TOKENS
    )

    await log_runtime_summarizer_payload(
        context,
        label="L1",
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )

    response = await ask_service_model(
        client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=config.SERVICE_REQUEST_TIMEOUT,
    )

    await refresh_runtime_memory_summarizer_usage(
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

    await refresh_runtime_memory_summarizer_usage(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    temperature = (
        config.SERVICE_TEMPERATURE
    )
    max_tokens = (
        config.SERVICE_MAX_TOKENS
    )
    log_label = (
        "L1 batch"
        if len(turns) > 1
        else "L1"
    )

    await log_runtime_summarizer_payload(
        context,
        label=log_label,
        payload=build_runtime_summarizer_payload(
            service_client=service_client,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            max_tokens=max_tokens,
        ),
    )

    response = await ask_service_model(
        client=service_client,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=config.SERVICE_REQUEST_TIMEOUT,
    )

    await refresh_runtime_memory_summarizer_usage(
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
        stored_memory = remove_runtime_memory_placeholder_lines(
            remove_runtime_response_feedback_text(
                getattr(
                    context,
                    "runtime_memory",
                    "",
                )
            )
        )
        updated_memory = refresh_active_memory_runtime_metadata(
            stored_memory,
            previous_memory=stored_memory,
            context=context,
        )
        updated_memory = ensure_active_memory_status_suffixes(
            updated_memory
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
        stored_memory = remove_runtime_memory_placeholder_lines(
            remove_runtime_response_feedback_text(
                getattr(
                    context,
                    "runtime_memory",
                    "",
                )
            )
        )
        updated_memory = refresh_active_memory_runtime_metadata(
            stored_memory,
            previous_memory=stored_memory,
            context=context,
        )
        updated_memory = ensure_active_memory_status_suffixes(
            updated_memory
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
    stored_memory = remove_runtime_memory_placeholder_lines(
        stored_memory
    )
    stored_memory = refresh_active_memory_runtime_metadata(
        stored_memory,
        previous_memory=stored_memory,
        context=context,
    )
    current_memory = strip_active_memory_runtime_metadata(
        stored_memory
    )
    current_memory = ensure_active_memory_status_suffixes(
        current_memory
    )

    context.runtime_memory = stored_memory
    context.runtime_memory_stable = remove_runtime_memory_placeholder_lines(
        remove_runtime_response_feedback_text(
            getattr(
                context,
                "runtime_memory_stable",
                "",
            )
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
            allow_reasoning_fallback=False,
        )
        context.runtime_l1_last_summarizer_response_details = (
            build_runtime_summarizer_response_details(
                response,
                extracted_memory=updated_memory,
                allow_reasoning_fallback=False,
            )
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = ensure_active_memory_status_suffixes(
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
                level="L1",
                message="L1 runtime memory update skipped",
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

        updated_memory = merge_durable_memory_facts(
            current_memory,
            updated_memory,
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = await normalize_active_memory_slots_with_logging(
            context,
            previous_memory=current_memory,
            candidate_memory=updated_memory,
            stage="after durable merge",
        )
        updated_memory = ensure_confirmable_memory_markers(
            updated_memory,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        updated_memory = enrich_active_memory_recall_conditions(
            updated_memory,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        updated_memory = await normalize_active_memory_slots_with_logging(
            context,
            previous_memory=current_memory,
            candidate_memory=updated_memory,
            stage="after confirmable markers",
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = enforce_runtime_turn_fields(
            updated_memory,
            user_message=user_message,
            assistant_message=assistant_message,
            previous_memory=current_memory,
        )
        updated_memory = ensure_active_memory_status_suffixes(
            updated_memory
        )
        updated_memory = remove_runtime_user_idle_lines(
            updated_memory
        )
        updated_memory = refresh_active_memory_runtime_metadata(
            updated_memory,
            previous_memory=stored_memory,
            context=context,
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
            await maybe_summarize_runtime_l2_memory(
                context=context,
            )
            await maybe_summarize_runtime_session_memory(
                context=context,
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
            level="L1",
            message="L1 runtime memory update failed",
            details=build_memory_failure_details(
                stage="L1 runtime memory summarizer",
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
    stored_initial_memory = remove_runtime_memory_placeholder_lines(
        stored_initial_memory
    )
    stored_initial_memory = refresh_active_memory_runtime_metadata(
        stored_initial_memory,
        previous_memory=stored_initial_memory,
        context=context,
    )
    initial_memory = strip_active_memory_runtime_metadata(
        stored_initial_memory
    )
    initial_memory = ensure_active_memory_status_suffixes(
        initial_memory
    )

    context.runtime_memory = remove_runtime_memory_placeholder_lines(
        remove_runtime_response_feedback_text(
            getattr(
                context,
                "runtime_memory",
                "",
            )
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
            allow_reasoning_fallback=False,
        )
        context.runtime_l1_last_summarizer_response_details = (
            build_runtime_summarizer_response_details(
                response,
                extracted_memory=updated_memory,
                allow_reasoning_fallback=False,
            )
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = ensure_active_memory_status_suffixes(
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
                level="L1",
                message="L1 runtime memory update skipped",
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

        updated_memory = merge_durable_memory_facts(
            initial_memory,
            updated_memory,
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = await normalize_active_memory_slots_with_logging(
            context,
            previous_memory=initial_memory,
            candidate_memory=updated_memory,
            stage="batch after durable merge",
        )

        latest_turn = turns[-1] if turns else {}
        latest_user_message = latest_turn.get(
            "user_message",
            "",
        )
        latest_assistant_message = latest_turn.get(
            "assistant_message",
            "",
        )

        updated_memory = ensure_confirmable_memory_markers(
            updated_memory,
            user_message=latest_user_message,
            assistant_message=latest_assistant_message,
        )
        updated_memory = enrich_active_memory_recall_conditions(
            updated_memory,
            user_message=latest_user_message,
            assistant_message=latest_assistant_message,
        )
        updated_memory = await normalize_active_memory_slots_with_logging(
            context,
            previous_memory=initial_memory,
            candidate_memory=updated_memory,
            stage="batch after confirmable markers",
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = enforce_runtime_turn_fields(
            updated_memory,
            user_message=latest_user_message,
            assistant_message=latest_assistant_message,
            previous_memory=initial_memory,
        )
        updated_memory = ensure_active_memory_status_suffixes(
            updated_memory
        )
        updated_memory = remove_runtime_user_idle_lines(
            updated_memory
        )
        updated_memory = refresh_active_memory_runtime_metadata(
            updated_memory,
            previous_memory=stored_initial_memory,
            context=context,
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

            snapshot = await emit_runtime_memory_update(
                context
            )

            await record_runtime_l1_diff(
                context,
                snapshot,
                turns=turns,
            )
            await maybe_summarize_runtime_l2_memory(
                context=context,
            )
            await maybe_summarize_runtime_session_memory(
                context=context,
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
            level="L1",
            message="L1 runtime memory update failed",
            details=build_memory_failure_details(
                stage="L1 pending runtime memory summarizer",
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


def schedule_runtime_memory_update(
        *,
        context,
        user_message: str,
        assistant_message: str,
) -> asyncio.Task | None:

    # Normal turns without a visible assistant answer do not produce
    # enough signal for L1 and can be skipped. A confirmed session-save
    # action is different: the visible answer may be intentionally empty
    # because the brain emitted only the private remember-session marker.
    # In that case still enqueue the turn so the standard L1 -> optional
    # L2 -> L3 save pipeline remains intact.
    if (
            not assistant_message.strip()
            and not getattr(
                context,
                "runtime_remember_session_requested",
                False,
            )
    ):
        return None

    context.runtime_memory_pending_turns.append({
        "user_message": user_message,
        "assistant_message": assistant_message,
    })

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


def schedule_interrupted_runtime_memory_update(
        *,
        context,
) -> asyncio.Task | None:

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
        )
    )

    if not user_message.strip():
        return None

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

def merge_durable_memory_facts(
        previous_memory: str,
        candidate_memory: str,
) -> str:

    previous_memory = remove_runtime_response_feedback_text(
        previous_memory
    )
    candidate_memory = remove_runtime_response_feedback_text(
        candidate_memory
    )

    previous_lines = parse_runtime_memory_lines(
        previous_memory
    )
    candidate_lines = parse_runtime_memory_lines(
        candidate_memory
    )

    candidate_by_key = {
        normalize_memory_key(
            line.get(
                "key",
                "",
            )
        ): line
        for line in candidate_lines
    }

    preserved_lines = []

    for previous_line in previous_lines:

        previous_key = (
            previous_line.get(
                "key",
                "",
            )
            or ""
        ).strip()

        if not is_durable_memory_key(
            previous_key
        ):
            continue

        previous_value = previous_line.get(
            "value",
            "",
        )

        if is_runtime_memory_repeatable_key_family(
                previous_key
        ):
            previous_family = normalize_runtime_memory_key_family(
                previous_key
            )
            candidate_semantic_match = False

            for candidate_line in candidate_lines:
                candidate_key = (
                    candidate_line.get(
                        "key",
                        "",
                    )
                    or ""
                ).strip()

                if not is_runtime_memory_repeatable_key_family(
                        candidate_key
                ):
                    continue

                if (
                        normalize_runtime_memory_key_family(
                            candidate_key
                        )
                        != previous_family
                ):
                    continue

                candidate_value = candidate_line.get(
                    "value",
                    "",
                )

                if has_durable_fact_negation(
                    candidate_value
                ):
                    candidate_semantic_match = True
                    break

                if repeatable_runtime_memory_values_are_same_slot(
                        previous_value,
                        candidate_value,
                ):
                    candidate_semantic_match = True
                    break

            if candidate_semantic_match:
                continue

            preserved_lines.append(
                durable_memory_line_text(
                    previous_line
                )
            )
            continue

        normalized_key = normalize_memory_key(
            previous_key
        )

        candidate_line = candidate_by_key.get(
            normalized_key
        )

        if candidate_line is not None:
            candidate_value = candidate_line.get(
                "value",
                "",
            )

            if has_durable_fact_negation(
                candidate_value
            ):
                continue

            continue

        preserved_lines.append(
            durable_memory_line_text(
                previous_line
            )
        )

    if not preserved_lines:
        return candidate_memory

    candidate_text = (
        candidate_memory
        or ""
    ).strip()

    if not candidate_text:
        return "\n".join(
            preserved_lines
        )

    return (
        "\n".join(
            preserved_lines
        )
        + "\n"
        + candidate_text
    )
