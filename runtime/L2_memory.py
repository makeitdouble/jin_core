import asyncio
import traceback

from clients.service_client import (
    ask_service_model,
)
from config_loader import (
    config,
)
from runtime.L2_memory_rules import (
    DEFAULT_RUNTIME_L2_MEMORY,
    L2_PATCH_WINDOW,
    L2_REPEATED_KEY_THRESHOLD,
    MIN_L2_TURNS,
)
from runtime.fact_check import (
    ensure_confirmable_memory_markers,
)
from runtime.memory_utils import (
    build_runtime_l2_memory_system_prompt,
    build_runtime_l2_memory_user_prompt,
    build_runtime_l2_repeated_user_message_evidence_memory,
    extract_runtime_l2_pattern_evidence_lines,
    merge_runtime_l2_pattern_evidence_memory,
    remove_runtime_l2_occurrence_pattern_lines,
    remove_runtime_l2_pattern_evidence_lines,
)
from runtime.memory_common import (
    build_memory_failure_details,
    build_memory_update_skip_details,
    build_runtime_summarizer_payload,
    extract_runtime_memory_text,
    is_runtime_memory_response_truncated,
    log_memory_event,
    log_runtime_summarizer_payload,
    log_runtime_summarizer_result,
    looks_like_incomplete_runtime_memory,
    refresh_runtime_memory_summarizer_usage,
)
from runtime.memory_events import (
    emit_runtime_l1_diff_update,
    emit_runtime_memory_snapshot_refresh,
    rebuild_latest_runtime_memory_snapshot,
)

def normalize_memory_key(*args, **kwargs):
    from runtime.L1_memory import (
        normalize_memory_key as _normalize_memory_key,
    )

    return _normalize_memory_key(
        *args,
        **kwargs,
    )


async def ask_runtime_l2_memory_model(
        *,
        context=None,
        service_client,
        current_l2_memory: str,
        patches: list[dict],
) -> dict:

    system_prompt = (
        build_runtime_l2_memory_system_prompt()
    )
    user_prompt = (
        build_runtime_l2_memory_user_prompt(
            current_l2_memory=current_l2_memory,
            patches=patches,
        )
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

    await log_runtime_summarizer_payload(
        context,
        label="L2",
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


def get_runtime_l2_user_turn_count(
        context,
) -> int:

    return int(
        getattr(
            context,
            "user_message_count",
            getattr(
                context,
                "turn_number",
                0,
            ),
        )
        or 0
    )


def ensure_runtime_l2_state(
        context,
) -> None:

    if not hasattr(
        context,
        "runtime_l2_memory",
    ):
        context.runtime_l2_memory = DEFAULT_RUNTIME_L2_MEMORY

    if not hasattr(
        context,
        "runtime_l2_pending_patches",
    ):
        context.runtime_l2_pending_patches = []

    if not hasattr(
        context,
        "runtime_l2_last_turn",
    ):
        context.runtime_l2_last_turn = 0


def is_runtime_l2_context_line_key(
        key: str,
) -> bool:

    return (
        str(
            key
            or ""
        )
        .strip()
        .casefold()
        .startswith(
            "l2_pattern_evidence_"
        )
    )


def filter_runtime_l2_context_lines_from_patch(
        patch: dict,
) -> dict:

    if not isinstance(
        patch,
        dict,
    ):
        return {}

    filtered_patch = {
        "added": [],
        "changed": [],
        "removed": [],
    }

    for entry in patch.get(
            "added",
            [],
    ) or []:
        if is_runtime_l2_context_line_key(
                entry.get(
                    "key",
                    "",
                )
        ):
            continue

        filtered_patch["added"].append(
            entry
        )

    for entry in patch.get(
            "changed",
            [],
    ) or []:
        if (
                is_runtime_l2_context_line_key(
                    entry.get(
                        "previous_key",
                        "",
                    )
                )
                or is_runtime_l2_context_line_key(
                    entry.get(
                        "current_key",
                        "",
                    )
                )
        ):
            continue

        filtered_patch["changed"].append(
            entry
        )

    for entry in patch.get(
            "removed",
            [],
    ) or []:
        if is_runtime_l2_context_line_key(
                entry.get(
                    "key",
                    "",
                )
        ):
            continue

        filtered_patch["removed"].append(
            entry
        )

    return filtered_patch


def compact_runtime_l2_user_message_evidence(
        value,
        *,
        limit: int = 160,
) -> str:

    text = str(
        value
        or ""
    ).strip()

    text = " ".join(
        text.split()
    )

    if len(text) <= limit:
        return text

    return text[:limit].rstrip()


def runtime_l1_patch_total_diff(
        patch: dict,
) -> float:

    total_diff = 0

    total_diff += 30 * len(
        patch.get(
            "added",
            [],
        )
        or []
    )
    total_diff += 20 * len(
        patch.get(
            "removed",
            [],
        )
        or []
    )

    for entry in patch.get(
            "changed",
            [],
    ) or []:
        total_diff += round(
            (
                entry.get(
                    "key_change_ratio",
                    0,
                )
                + entry.get(
                    "value_change_ratio",
                    0,
                )
            )
            * 50,
            2,
        )

    return total_diff


async def record_runtime_l1_diff(
        context,
        snapshot: dict,
        turns: list[dict] | None = None,
) -> None:

    ensure_runtime_l2_state(
        context
    )

    patch = snapshot.get(
        "patch",
        {},
    ) or {}
    filtered_patch = filter_runtime_l2_context_lines_from_patch(
        patch
    )
    if patch:
        total_diff = runtime_l1_patch_total_diff(
            filtered_patch
        )
    else:
        total_diff = snapshot.get(
            "total_diff",
            0,
        )
    context.runtime_conversation_activity_diff = total_diff

    observed_turns = list(
        turns
        or []
    )
    observed_user_messages = [
        compact_runtime_l2_user_message_evidence(
            turn.get(
                "user_message",
                "",
            )
        )
        for turn in observed_turns
        if compact_runtime_l2_user_message_evidence(
            turn.get(
                "user_message",
                "",
            )
        )
    ]
    latest_user_message = (
        observed_user_messages[-1]
        if observed_user_messages
        else ""
    )

    user_turn_count = get_runtime_l2_user_turn_count(
        context
    )

    diff_entry = {
        "turn_number": user_turn_count,
        "snapshot_index": snapshot.get(
            "index",
            0,
        ),
        "total_diff": total_diff,
        "changes": filtered_patch,
        "user_message": latest_user_message,
        "user_messages": observed_user_messages[-3:],
    }

    context.runtime_l2_pending_patches.append(
        diff_entry
    )

    if not hasattr(
        context,
        "runtime_l1_diff_history",
    ):
        context.runtime_l1_diff_history = []

    context.runtime_l1_diff_history.append(
        {
            **diff_entry,
            "history_index": len(
                context.runtime_l1_diff_history
            ),
        }
    )

    turns_since_l2 = (
        user_turn_count
        - getattr(
            context,
            "runtime_l2_last_turn",
            0,
        )
    )

    recent_diffs = get_recent_l2_diff_values(
        context
    )
    diff_average = average_diff(
        recent_diffs
    )
    diff_range = diff_value_range(
        recent_diffs
    )
    repeated_keys = get_repeated_l2_patch_keys(
        context
    )
    l2_last_turn = getattr(
        context,
        "runtime_l2_last_turn",
        0,
    )
    l2_turn_label = (
        f"turns since L2 {turns_since_l2}"
        if l2_last_turn
        else f"L2 not run yet; observed turns {user_turn_count}"
    )

    if total_diff == 0:
        latest_turn = (
            observed_turns[-1]
            if observed_turns
            else {}
        )
        context.runtime_zero_diff_alert = {
            "turn_number": user_turn_count,
            "user_message": latest_turn.get(
                "user_message",
                "",
            ),
            "assistant_message": latest_turn.get(
                "assistant_message",
                "",
            ),
            "reason": (
                "Previous L1 memory update produced total_diff 0."
            ),
        }

    await log_memory_event(
        context,
        level="L1",
        message=(
            "L1 diff "
            f"+{format_diff_value(total_diff)}; "
            f"recent diffs {format_diff_values(recent_diffs)}; "
            f"avg {format_diff_value(diff_average)}; "
            f"range {format_diff_value(diff_range)}; "
            f"patch window {len(recent_diffs)}/{L2_PATCH_WINDOW}; "
            f"repeated keys {repeated_keys}; "
            f"{l2_turn_label}"
        ),
        fallback_channel="service",
    )

    await emit_runtime_l1_diff_update(
        context
    )


def get_recent_l2_patches(
        context,
) -> list[dict]:

    return list(
        getattr(
            context,
            "runtime_l2_pending_patches",
            [],
        )
        or []
    )[-L2_PATCH_WINDOW:]


def get_recent_l2_diff_values(
        context,
) -> list[float]:

    return [
        patch.get(
            "total_diff",
            0,
        )
        for patch in get_recent_l2_patches(
            context
        )
    ]


def average_diff(
        diffs: list[float],
) -> float:

    if not diffs:
        return 0

    return round(
        sum(diffs) / len(diffs),
        2,
    )


def format_diff_value(
        value: float,
) -> str:

    return (
        f"{value:.2f}"
        .rstrip(
            "0"
        )
        .rstrip(
            "."
        )
    )


def format_diff_values(
        values: list[float],
) -> str:

    return (
        "["
        + ", ".join(
            format_diff_value(
                value
            )
            for value in values
        )
        + "]"
    )


def diff_value_range(
        diffs: list[float],
) -> float:

    if not diffs:
        return 0

    return round(
        max(diffs) - min(diffs),
        2,
    )


def extract_l2_patch_keys(
        patch: dict,
) -> set[str]:

    changes = patch.get(
        "changes",
        {},
    )

    keys = set()

    for entry in (
            changes.get(
                "added",
                [],
            )
            or []
    ):
        key = normalize_memory_key(
            entry.get(
                "key",
                "",
            )
        )

        if key:
            keys.add(
                key
            )

    for entry in (
            changes.get(
                "changed",
                [],
            )
            or []
    ):
        for key_name in (
                "current_key",
                "previous_key",
        ):
            key = normalize_memory_key(
                entry.get(
                    key_name,
                    "",
                )
            )

            if key:
                keys.add(
                    key
                )

    for entry in (
            changes.get(
                "removed",
                [],
            )
            or []
    ):
        key = normalize_memory_key(
            entry.get(
                "key",
                "",
            )
        )

        if key:
            keys.add(
                key
            )

    return keys


def count_l2_patch_keys(
        patches: list[dict],
) -> dict[str, int]:

    counts = {}

    for patch in patches:
        for key in extract_l2_patch_keys(
                patch
        ):
            counts[key] = (
                counts.get(
                    key,
                    0,
                )
                + 1
            )

    return counts


def get_repeated_l2_patch_keys(
        context,
) -> dict[str, int]:

    counts = count_l2_patch_keys(
        get_recent_l2_patches(
            context
        )
    )

    return {
        key: count
        for key, count in counts.items()
        if count >= L2_REPEATED_KEY_THRESHOLD
    }


def should_run_runtime_l2_memory(
        context,
) -> bool:

    ensure_runtime_l2_state(
        context
    )

    user_turn_count = get_runtime_l2_user_turn_count(
        context
    )
    turns_since_l2 = (
        user_turn_count
        - getattr(
            context,
            "runtime_l2_last_turn",
            0,
        )
    )

    recent_patches = get_recent_l2_patches(
        context
    )
    repeated_keys = count_l2_patch_keys(
        recent_patches
    )

    return (
        turns_since_l2 >= MIN_L2_TURNS
        and len(recent_patches) >= L2_PATCH_WINDOW
        and any(
            count >= L2_REPEATED_KEY_THRESHOLD
            for count in repeated_keys.values()
        )
    )


async def maybe_summarize_runtime_l2_memory(
        *,
        context,
) -> str:

    ensure_runtime_l2_state(
        context
    )

    if not should_run_runtime_l2_memory(
        context
    ):
        return getattr(
            context,
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
        )

    patches = get_recent_l2_patches(
        context
    )

    if not patches:
        return getattr(
            context,
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
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
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
        )

    current_l2_memory = getattr(
        context,
        "runtime_l2_memory",
        DEFAULT_RUNTIME_L2_MEMORY,
    )

    try:
        response = await ask_runtime_l2_memory_model(
            context=context,
            service_client=service_client,
            current_l2_memory=current_l2_memory,
            patches=patches,
        )

        updated_l2_memory = extract_runtime_memory_text(
            response
        )

        skip_reason = None

        if is_runtime_memory_response_truncated(response):
            skip_reason = "L2 summarizer response was truncated by max_tokens."

        elif (
                updated_l2_memory.strip()
                and looks_like_incomplete_runtime_memory(
            updated_l2_memory
        )
        ):
            skip_reason = "L2 summarizer returned text that looks structurally incomplete."

        if skip_reason:
            await log_memory_event(
                context,
                level="L2",
                message="L2 memory update skipped",
                details=build_memory_update_skip_details(
                    reason=skip_reason,
                    previous_memory=current_l2_memory,
                    candidate_memory=updated_l2_memory,
                ),
                fallback_channel="error",
            )

            return current_l2_memory

        updated_l2_memory = ensure_confirmable_memory_markers(
            updated_l2_memory,
        )
        candidate_pattern_evidence = extract_runtime_l2_pattern_evidence_lines(
            updated_l2_memory,
        )
        deterministic_repeated_message_evidence = (
            build_runtime_l2_repeated_user_message_evidence_memory(
                previous_memory=current_l2_memory,
                patches=patches,
            )
        )
        if (
                candidate_pattern_evidence
                and not deterministic_repeated_message_evidence.strip()
        ):
            updated_l2_memory = remove_runtime_l2_occurrence_pattern_lines(
                updated_l2_memory,
            )

        updated_l2_memory = remove_runtime_l2_pattern_evidence_lines(
            updated_l2_memory,
        )
        updated_l2_memory = merge_runtime_l2_pattern_evidence_memory(
            previous_memory=current_l2_memory,
            candidate_memory=updated_l2_memory,
        )

        if deterministic_repeated_message_evidence.strip():
            updated_l2_memory = merge_runtime_l2_pattern_evidence_memory(
                previous_memory=updated_l2_memory,
                candidate_memory=deterministic_repeated_message_evidence,
            )

        context.runtime_l2_memory = updated_l2_memory
        context.runtime_l2_last_turn = get_runtime_l2_user_turn_count(
            context
        )
        context.runtime_l2_pending_patches = []

        await log_memory_event(
            context,
            level="L2",
            message="L2 memory updated",
            fallback_channel="service",
        )

        await log_runtime_summarizer_result(
            context,
            label="L2 pattern memory",
            result=updated_l2_memory,
        )

        await emit_runtime_memory_snapshot_refresh(
            context,
            rebuild_latest_runtime_memory_snapshot(
                context
            ),
        )

        return getattr(
            context,
            "runtime_l2_memory",
            DEFAULT_RUNTIME_L2_MEMORY,
        )

    except asyncio.CancelledError:
        raise

    except Exception as error:
        formatted_traceback = (
            traceback.format_exc()
        )

        await log_memory_event(
            context,
            level="L2",
            message="L2 memory update failed",
            details=build_memory_failure_details(
                stage="L2 memory summarizer",
                error=error,
                traceback_text=formatted_traceback,
            ),
            fallback_channel="error",
        )

        return current_l2_memory
