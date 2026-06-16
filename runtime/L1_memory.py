import asyncio
import contextlib
import traceback
from difflib import SequenceMatcher

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
    DURABLE_FLOOR,
    DURABLE_MEMORY_KEY_TOKENS,
    DURABLE_MEMORY_NEGATION_MARKERS,
    GENERIC_MEMORY_MATCH_KEYS,
    GENERIC_MEMORY_VALUE_SIMILARITY_MIN,
    HOT_THRESHOLD,
    HOT_TRACE_EXCLUDED_KEYS,
    RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_KEY,
    RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE,
    RUNTIME_RESPONSE_FEEDBACK_RATINGS,
    STRENGTH_BOOST,
    STRENGTH_DECAY,
    STRENGTH_NEW_KEY,
    STRENGTH_PRESENCE_BOOST,
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
    build_runtime_summarizer_user_prompt,
    change_ratio,
    extract_runtime_memory_text,
    is_runtime_memory_response_truncated,
    latest_turn_context_is_overloaded,
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
    build_runtime_memory_context_text,
    build_runtime_memory_user_prompt,
    canonicalize_runtime_memory_entry,
    is_runtime_memory_repeatable_key_family,
    normalize_runtime_memory_key_family,
    normalize_runtime_memory_slot_text,
    runtime_memory_slot_similarity,
    remove_runtime_memory_placeholder_lines,
    remove_runtime_user_idle_lines,
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



def remove_runtime_memory_entry_text(
        memory: str,
        key: str,
) -> str:

    target_key = str(key or "").strip()
    if not target_key:
        return memory or ""

    target_key_normalized = target_key.casefold()

    lines = [
        line.rstrip()
        for line in str(memory or "").splitlines()
    ]

    kept_lines = []

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        current_key = stripped.split(":", 1)[0].strip().casefold()

        if current_key == target_key_normalized:
            continue

        kept_lines.append(stripped)

    return "\n".join(kept_lines).strip()


def upsert_runtime_memory_entry_text(
        memory: str,
        key: str,
        value: str,
) -> str:

    target_key = str(key or "").strip()
    if not target_key:
        return memory or ""

    target_key_normalized = target_key.casefold()
    replacement = f"{target_key}: {str(value or '').strip()}"

    lines = [
        line.rstrip()
        for line in str(memory or "").splitlines()
    ]

    updated_lines = []
    replaced = False

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        current_key = stripped.split(":", 1)[0].strip().casefold()

        if current_key == target_key_normalized:
            if not replaced:
                updated_lines.append(replacement)
                replaced = True
            continue

        updated_lines.append(stripped)

    if not replaced:
        updated_lines.append(replacement)

    return "\n".join(updated_lines).strip()


def remove_runtime_response_feedback_text(
        memory: str,
) -> str:

    return remove_runtime_memory_entry_text(
        memory or "",
        RUNTIME_RESPONSE_FEEDBACK_KEY,
    ).strip()


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

    system_prompt = (
        build_runtime_memory_system_prompt()
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
    user_prompt = build_runtime_summarizer_user_prompt(
        context=context,
        prompt=(
            build_runtime_memory_user_prompt(
                current_memory=current_memory,
                user_message=user_message,
                assistant_message=assistant_message,
                strength_zones=get_strength_zones(
                    _latest_lines
                ),
            )
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
        system_prompt = (
            build_runtime_memory_system_prompt(
                last_turn_context_overloaded=True,
            )
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

    system_prompt = (
        build_runtime_memory_system_prompt()
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
    user_prompt = build_runtime_summarizer_user_prompt(
        context=context,
        prompt=(
            build_runtime_memory_batch_user_prompt(
                current_memory=current_memory,
                turns=turns,
                strength_zones=get_strength_zones(
                    _latest_lines
                ),
            )
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

    current_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )
    current_memory = remove_runtime_memory_placeholder_lines(
        current_memory
    )

    context.runtime_memory = current_memory
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
            response
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
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
                ),
                fallback_channel="error",
            )

            return current_memory

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
        updated_memory = ensure_confirmable_memory_markers(
            updated_memory,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = remove_runtime_user_idle_lines(
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

    initial_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory_stable",
            "",
        )
    )
    initial_memory = remove_runtime_memory_placeholder_lines(
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
    context.runtime_memory_stable = initial_memory
    context.runtime_last_response_feedback = None

    try:
        response = await ask_runtime_memory_batch_model(
            context=context,
            service_client=service_client,
            current_memory=initial_memory,
            turns=turns,
        )

        updated_memory = extract_runtime_memory_text(
            response
        )
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
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
                ),
                fallback_channel="error",
            )

            return initial_memory

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
        updated_memory = remove_runtime_response_feedback_text(
            updated_memory
        )
        updated_memory = remove_runtime_memory_placeholder_lines(
            updated_memory
        )
        updated_memory = remove_runtime_user_idle_lines(
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

def parse_runtime_memory_lines(memory: str) -> list[dict]:
    lines = []

    for raw_line in (memory or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()

        if not line:
            continue

        if ":" in line:
            key, value = line.split(":", 1)
        else:
            key, value = "note", line

        key, value = canonicalize_runtime_memory_entry(
            key,
            value,
        )

        lines.append({
            "key": key,
            "value": value,
            "status": "same",
        })

    return lines

def normalize_memory_key(
        key: str,
) -> str:

    return (
        key
        .strip()
        .lower()
    )


def is_durable_memory_key(
        key: str,
) -> bool:

    normalized_key = normalize_memory_key(
        key
    )

    return any(
        token in normalized_key
        for token in DURABLE_MEMORY_KEY_TOKENS
    )


def compute_line_strength(
        prev_strength: float | None,
        change_ratio_val: float,
        is_durable: bool,
        is_new: bool,
) -> float:
    if is_new:
        raw = STRENGTH_NEW_KEY
    else:
        raw = (
            (prev_strength or 0.0) * STRENGTH_DECAY
            + STRENGTH_PRESENCE_BOOST
            + change_ratio_val * STRENGTH_BOOST
        )

    floor = DURABLE_FLOOR if is_durable else 0.0

    return round(
        min(
            1.0,
            max(
                floor,
                raw,
            ),
        ),
        4,
    )


def get_strength_zones(
        lines: list[dict],
) -> dict:
    hot = []
    excluded_hot_trace_keys = {
        normalize_memory_key(
            key
        )
        for key in HOT_TRACE_EXCLUDED_KEYS
    }

    for line in lines:
        key = line.get("key", "")
        strength = line.get("strength", 0.0)
        if strength >= HOT_THRESHOLD:
            if normalize_memory_key(
                key
            ) in excluded_hot_trace_keys:
                continue
            hot.append(key)

    return {
        "hot": hot,
    }


def build_strength_map(
        lines: list[dict],
) -> dict[str, float]:
    return {
        line.get("key", ""): line.get("strength", 0.0)
        for line in lines
        if line.get("key")
    }


def has_durable_fact_negation(
        value: str,
) -> bool:

    normalized_value = (
        value
        or ""
    ).strip().lower()

    return any(
        marker in normalized_value
        for marker in DURABLE_MEMORY_NEGATION_MARKERS
    )


def durable_memory_line_text(
        line: dict,
) -> str:

    key = (
        line.get(
            "key",
            "",
        )
        or ""
    ).strip()

    value = (
        line.get(
            "value",
            "",
        )
        or ""
    ).strip()

    if not key:
        return value

    return f"{key}: {value}"


def split_memory_value_parts(
        value: str,
) -> list[str]:

    return [
        part.strip()
        for part in (
            value
            or ""
        ).split(",")
        if part.strip()
    ]


def strip_runtime_memory_key_ordinal(
        key: str,
) -> str:

    clean_key = (
        key
        or ""
    ).strip()

    prefix, separator, suffix = clean_key.rpartition(
        "_"
    )

    if (
            separator
            and suffix.isdigit()
            and prefix
    ):
        return prefix

    return clean_key


def repeatable_runtime_memory_values_are_same_slot(
        left: str,
        right: str,
) -> bool:

    left_text = normalize_runtime_memory_slot_text(
        left
    )
    right_text = normalize_runtime_memory_slot_text(
        right
    )

    if not left_text or not right_text:
        return False

    left_tokens = {
        token
        for token in left_text.split()
        if len(token) >= 3
    }
    right_tokens = {
        token
        for token in right_text.split()
        if len(token) >= 3
    }

    if left_tokens and right_tokens:
        overlap = len(
            left_tokens & right_tokens
        )
        coverage = overlap / max(
            1,
            max(
                len(left_tokens),
                len(right_tokens),
            ),
        )

        if coverage >= 0.75:
            return True

    shorter = min(
        len(left_text),
        len(right_text),
    )
    longer = max(
        len(left_text),
        len(right_text),
    )

    if not longer:
        return False

    length_ratio = shorter / longer

    return (
        length_ratio >= 0.75
        and runtime_memory_slot_similarity(
            left,
            right,
        ) >= 0.90
    )


def collapse_duplicate_runtime_memory_keys(
        memory: str,
) -> str:

    output_entries = []
    grouped_by_key = {}
    grouped_repeatable_by_family = {}
    duplicate_found = False

    for raw_line in (
        memory
        or ""
    ).splitlines():

        stripped_line = raw_line.strip()

        if not stripped_line:
            output_entries.append(
                raw_line
            )
            continue

        line = stripped_line.lstrip("-").strip()

        if ":" not in line:
            output_entries.append(
                raw_line
            )
            continue

        key, value = line.split(
            ":",
            1,
        )

        key, value = canonicalize_runtime_memory_entry(
            key,
            value,
        )

        normalized_key = normalize_memory_key(
            key
        )

        if (
            not normalized_key
            or not is_durable_memory_key(
                key
            )
        ):
            output_entries.append(
                raw_line
            )
            continue

        if is_runtime_memory_repeatable_key_family(
                key
        ):
            family = normalize_runtime_memory_key_family(
                key
            )
            existing = grouped_repeatable_by_family.get(
                family
            )

            if existing is None:
                existing = {
                    "repeatable": True,
                    "base_key": strip_runtime_memory_key_ordinal(
                        key
                    ),
                    "items": [],
                }
                grouped_repeatable_by_family[family] = existing
                output_entries.append(
                    existing
                )
            else:
                duplicate_found = True

            clean_value = normalize_runtime_memory_slot_text(
                value
            )

            matched_item = None

            for item in existing["items"]:
                if repeatable_runtime_memory_values_are_same_slot(
                        value,
                        item["value"],
                ):
                    matched_item = item
                    break

            if matched_item is None:
                existing["items"].append({
                    "key": key,
                    "value": value.strip(),
                    "clean_value": clean_value,
                })
                continue

            duplicate_found = True

            # Keep the first wording for a repeatable semantic slot.
            # The deterministic repeated suffix pass decides whether the
            # latest turn actually reactivated it and increments [ repeated: N ].
            continue

        existing = grouped_by_key.get(
            normalized_key
        )

        if existing is None:
            existing = {
                "key": key,
                "values": [],
                "seen_values": set(),
            }
            grouped_by_key[normalized_key] = existing
            output_entries.append(
                existing
            )
        else:
            duplicate_found = True

        for part in split_memory_value_parts(
            value
        ):
            normalized_value = part.casefold()

            if normalized_value in existing["seen_values"]:
                continue

            existing["seen_values"].add(
                normalized_value
            )
            existing["values"].append(
                part
            )

    if not duplicate_found:
        return memory

    rendered_lines = []

    for entry in output_entries:
        if not isinstance(
                entry,
                dict,
        ):
            rendered_lines.append(
                entry
            )
            continue

        if entry.get(
                "repeatable"
        ):
            items = entry.get(
                "items",
                [],
            )

            if not items:
                continue

            if len(items) == 1:
                item = items[0]
                rendered_lines.append(
                    f'{item["key"]}: {item["value"]}'
                )
                continue

            base_key = entry.get(
                "base_key",
                "",
            )

            for index, item in enumerate(
                    items,
                    start=1,
            ):
                rendered_lines.append(
                    f'{base_key}_{index}: {item["value"]}'
                )

            continue

        rendered_lines.append(
            (
                f'{entry["key"]}: {", ".join(entry["values"])}'
                if entry["key"]
                else ", ".join(entry["values"])
            )
        )

    return "\n".join(
        rendered_lines
    )

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
        return collapse_duplicate_runtime_memory_keys(
            candidate_memory
        )

    candidate_text = (
        candidate_memory
        or ""
    ).strip()

    if not candidate_text:
        return collapse_duplicate_runtime_memory_keys(
            "\n".join(
                preserved_lines
            )
        )

    return collapse_duplicate_runtime_memory_keys(
        (
            "\n".join(
                preserved_lines
            )
            + "\n"
            + candidate_text
        )
    )


def normalize_generic_memory_key(
        key: str,
) -> str:

    return (
        normalize_memory_key(
            key
        )
        .replace(
            "_",
            " ",
        )
        .replace(
            "-",
            " ",
        )
    )


def is_generic_memory_match_key(
        key: str,
) -> bool:

    return normalize_generic_memory_key(
        key
    ) in GENERIC_MEMORY_MATCH_KEYS


def memory_value_similarity(
        previous: str,
        current: str,
) -> float:

    previous = (
        previous
        or ""
    ).strip()
    current = (
        current
        or ""
    ).strip()

    if not previous and not current:
        return 1.0

    if not previous or not current:
        return 0.0

    return round(
        SequenceMatcher(
            None,
            previous.lower(),
            current.lower(),
        ).ratio(),
        3,
    )


def should_match_previous_memory_line(
        *,
        key: str,
        value: str,
        previous_line: dict | None,
) -> bool:

    if previous_line is None:
        return False

    previous_key = previous_line.get(
        "key",
        "",
    )

    if not (
            is_generic_memory_match_key(
                key
            )
            or is_generic_memory_match_key(
                previous_key
            )
    ):
        return True

    similarity = memory_value_similarity(
        previous_line.get(
            "value",
            "",
        ),
        value,
    )

    return similarity >= GENERIC_MEMORY_VALUE_SIMILARITY_MIN


def find_best_previous_line(
        key: str,
        previous_lines: list[dict],
        value: str = "",
) -> dict | None:

    normalized_key = normalize_memory_key(
        key
    )

    best_line = None
    best_score = 0.0

    for previous_line in previous_lines:

        previous_key = normalize_memory_key(
            previous_line.get(
                "key",
                ""
            )
        )

        if not previous_key:
            continue

        score = SequenceMatcher(
            None,
            previous_key,
            normalized_key,
        ).ratio()

        if score > best_score:
            best_score = score
            best_line = previous_line

    if (
            best_score >= 0.58
            and should_match_previous_memory_line(
                key=key,
                value=value,
                previous_line=best_line,
            )
    ):
        return best_line

    return None

def apply_runtime_memory_diff(
        current_lines: list[dict],
        previous_snapshot: dict | None,
) -> list[dict]:

    if not previous_snapshot:
        for line in current_lines:
            line["key_status"] = "new"
            line["value_status"] = "new"
            line["key_change_ratio"] = 1.0
            line["value_change_ratio"] = 1.0
            line["status"] = "new"
            line["strength"] = compute_line_strength(
                prev_strength=None,
                change_ratio_val=1.0,
                is_durable=is_durable_memory_key(
                    line.get("key", "")
                ),
                is_new=True,
            )

        return current_lines

    previous_lines = (
            previous_snapshot.get(
                "lines",
                []
            )
            or []
    )

    previous_by_normalized_key = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                ""
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

    for line in current_lines:

        key = (
                line.get(
                    "key",
                    ""
                )
                or ""
        ).strip()

        value = (
                line.get(
                    "value",
                    ""
                )
                or ""
        ).strip()

        normalized_key = normalize_memory_key(
            key
        )

        previous_line = previous_by_normalized_key.get(
            normalized_key
        )

        if not should_match_previous_memory_line(
                key=key,
                value=value,
                previous_line=previous_line,
        ):
            previous_line = None

        if previous_line is None:
            previous_line = find_best_previous_line(
                key,
                previous_lines,
                value=value,
            )

        # -----------------------------------------
        # EXACT KEY NOT FOUND
        # -----------------------------------------

        if previous_line is None:
            line["key_status"] = "new"
            line["value_status"] = "new"
            line["key_change_ratio"] = 1.0
            line["value_change_ratio"] = 1.0
            line["status"] = "new"
            line["strength"] = compute_line_strength(
                prev_strength=None,
                change_ratio_val=1.0,
                is_durable=is_durable_memory_key(key),
                is_new=True,
            )

            continue

        previous_key = (
                previous_line.get(
                    "key",
                    ""
                )
                or ""
        ).strip()

        previous_value = (
                previous_line.get(
                    "value",
                    ""
                )
                or ""
        ).strip()

        key_delta = change_ratio(
            previous_key,
            key,
        )

        value_delta = change_ratio(
            previous_value,
            value,
        )

        line["key_change_ratio"] = key_delta
        line["value_change_ratio"] = value_delta

        line["key_status"] = (
            "changed"
            if key_delta > 0
            else "same"
        )

        line["value_status"] = (
            "changed"
            if value_delta > 0
            else "same"
        )

        if (
                line["key_status"] == "changed"
                or line["value_status"] == "changed"
        ):
            line["status"] = "changed"

        else:
            line["status"] = "same"

        line["strength"] = compute_line_strength(
            prev_strength=previous_line.get("strength"),
            change_ratio_val=max(key_delta, value_delta),
            is_durable=is_durable_memory_key(key),
            is_new=False,
        )

    return current_lines


def build_runtime_memory_patch(
        current_lines: list[dict],
        previous_snapshot: dict | None,
) -> dict:

    patch = {
        "added": [],
        "changed": [],
        "removed": [],
    }
    total_diff = 0

    if not previous_snapshot:
        for line in current_lines:
            patch["added"].append({
                "key": line.get(
                    "key",
                    "",
                ),
                "value": line.get(
                    "value",
                    "",
                ),
                "strength": line.get(
                    "strength",
                    0.0,
                ),
            })
            total_diff += 30

        return {
            "patch": patch,
            "total_diff": total_diff,
        }

    previous_lines = (
            previous_snapshot.get(
                "lines",
                [],
            )
            or []
    )

    previous_by_normalized_key = {}

    for previous_line in previous_lines:
        normalized_key = normalize_memory_key(
            previous_line.get(
                "key",
                "",
            )
        )

        if normalized_key:
            previous_by_normalized_key[normalized_key] = previous_line

    matched_previous_ids = set()

    for line in current_lines:

        key = (
                line.get(
                    "key",
                    "",
                )
                or ""
        ).strip()

        value = (
                line.get(
                    "value",
                    "",
                )
                or ""
        ).strip()

        normalized_key = normalize_memory_key(
            key
        )

        previous_line = previous_by_normalized_key.get(
            normalized_key
        )

        if not should_match_previous_memory_line(
                key=key,
                value=value,
                previous_line=previous_line,
        ):
            previous_line = None

        if previous_line is None:
            previous_line = find_best_previous_line(
                key,
                previous_lines,
                value=value,
            )

        if previous_line is None:
            patch["added"].append({
                "key": key,
                "value": line.get(
                    "value",
                    "",
                ),
                "strength": line.get(
                    "strength",
                    0.0,
                ),
            })
            total_diff += 30
            continue

        matched_previous_ids.add(
            id(previous_line)
        )

        key_delta = line.get(
            "key_change_ratio",
            0,
        )
        value_delta = line.get(
            "value_change_ratio",
            0,
        )

        if key_delta or value_delta:
            patch["changed"].append({
                "previous_key": previous_line.get(
                    "key",
                    "",
                ),
                "previous_value": previous_line.get(
                    "value",
                    "",
                ),
                "current_key": key,
                "current_value": line.get(
                    "value",
                    "",
                ),
                "key_change_ratio": key_delta,
                "value_change_ratio": value_delta,
                "previous_strength": previous_line.get(
                    "strength",
                    0.0,
                ),
                "current_strength": line.get(
                    "strength",
                    0.0,
                ),
            })
            total_diff += round(
                (
                    key_delta
                    + value_delta
                )
                * 50,
                2,
            )

    for previous_line in previous_lines:
        if id(previous_line) in matched_previous_ids:
            continue

        patch["removed"].append({
            "key": previous_line.get(
                "key",
                "",
            ),
            "value": previous_line.get(
                "value",
                "",
            ),
            "strength": previous_line.get(
                "strength",
                0.0,
            ),
        })
        total_diff += 20

    return {
        "patch": patch,
        "total_diff": total_diff,
    }


def build_runtime_memory_snapshot(
        context,
        memory: str,
) -> dict:

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    previous_snapshot = (
        snapshots[-1]
        if snapshots
        else None
    )

    display_memory = build_runtime_memory_context_text(
        memory,
        context,
    )

    lines = parse_runtime_memory_lines(
        display_memory
    )

    lines = apply_runtime_memory_diff(
        lines,
        previous_snapshot,
    )

    patch_details = build_runtime_memory_patch(
        lines,
        previous_snapshot,
    )

    return {
        "session_id": getattr(context, "session_id", ""),
        "index": len(snapshots),
        "raw_memory": display_memory,
        "lines": lines,
        "patch": patch_details["patch"],
        "total_diff": patch_details["total_diff"],
    }
