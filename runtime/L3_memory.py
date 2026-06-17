import asyncio
import json
import traceback

from clients.service_client import (
    ask_service_model,
)
from config_loader import (
    config,
)
from runtime.L3_memory_rules import (
    DEFAULT_RUNTIME_L3_SESSION_MEMORY,
    L3_ACTION_REMEMBER_SESSION,
    L3_BUDGET_EXCEEDED_DETAILS_TEMPLATE,
    L3_LOG_LABEL_SESSION,
    L3_LOG_LABEL_SESSION_MEMORY,
    L3_LOG_LEVEL,
    L3_OUTPUT_MAX_TOKENS,
    L3_OUTPUT_TOKEN_BUDGET_CAPPED_TEMPLATE,
    L3_RESPONSE_TRUNCATED_REASON,
    L3_SESSION_MEMORY_SOURCE,
    L3_SKIP_NO_NEW_SNAPSHOTS_MESSAGE,
    L3_SKIP_NO_SNAPSHOTS_MESSAGE,
    L3_STRUCTURALLY_INCOMPLETE_REASON,
    L3_SUMMARIZER_REACHED_MAX_TOKENS_MESSAGE,
    L3_SUMMARIZER_STAGE,
    L3_UPDATE_FAILED_MESSAGE,
    L3_UPDATE_SKIPPED_MESSAGE,
    L3_UPDATED_MESSAGE,
)
from runtime.L3_memory_utils import (
    L3PromptBudgetExceeded,
    build_budgeted_l3_session_user_prompt,
    build_l3_session_memory_max_tokens,
    build_runtime_session_memory_system_prompt,
    parse_l3_session_snapshot_metadata,
    prepend_l3_session_snapshot_metadata,
    select_l3_unsaved_diff_history,
    select_l3_unsaved_runtime_snapshots,
    select_l3_unsaved_session_events,
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
    emit_runtime_action_completed,
    emit_runtime_session_memory_update,
)
async def ask_runtime_session_memory_model(
        *,
        context=None,
        service_client,
        current_session_memory: str,
        runtime_memory_snapshots: list[dict],
        diff_history: list[dict],
        session_event_snapshots: list[dict] | None = None,
) -> dict:

    system_prompt = (
        build_runtime_session_memory_system_prompt()
    )

    resolve_request_context_window = getattr(
        service_client,
        "resolve_request_context_window",
        None,
    )
    detected_context_window = None

    if resolve_request_context_window is not None:
        detected_context_window = await resolve_request_context_window()

    user_prompt, _prompt_diagnostic = (
        await build_budgeted_l3_session_user_prompt(
            context=context,
            system_prompt=system_prompt,
            current_session_memory=current_session_memory,
            runtime_memory_snapshots=runtime_memory_snapshots,
            diff_history=diff_history,
            runtime_l2_memory=getattr(
                context,
                "runtime_l2_memory",
                "",
            ),
            session_event_snapshots=list(
                session_event_snapshots
                if session_event_snapshots is not None
                else (
                    getattr(
                        context,
                        "runtime_session_event_snapshots",
                        [],
                    )
                    or []
                )
            ),
            context_window=detected_context_window,
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
    max_tokens = build_l3_session_memory_max_tokens(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context_window=detected_context_window,
    )
    calculated_max_tokens = max_tokens
    max_tokens = min(
        max_tokens,
        L3_OUTPUT_MAX_TOKENS,
    )

    if max_tokens < calculated_max_tokens:
        await log_memory_event(
            context,
            level=L3_LOG_LEVEL,
            message=L3_OUTPUT_TOKEN_BUDGET_CAPPED_TEMPLATE.format(
                max_tokens=L3_OUTPUT_MAX_TOKENS,
            ),
            fallback_channel="runtime",
        )

    await log_runtime_summarizer_payload(
        context,
        label=L3_LOG_LABEL_SESSION,
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


async def maybe_summarize_runtime_session_memory(
        *,
        context,
) -> str:

    if not getattr(
        context,
        "runtime_remember_session_requested",
        False,
    ):
        return getattr(
            context,
            "runtime_l3_session_memory",
            DEFAULT_RUNTIME_L3_SESSION_MEMORY,
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
        await emit_runtime_action_completed(
            context,
            action=L3_ACTION_REMEMBER_SESSION,
        )

        return getattr(
            context,
            "runtime_l3_session_memory",
            DEFAULT_RUNTIME_L3_SESSION_MEMORY,
        )

    snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )

    if not snapshots:
        await log_memory_event(
            context,
            level=L3_LOG_LEVEL,
            message=L3_SKIP_NO_SNAPSHOTS_MESSAGE,
            fallback_channel="runtime",
        )

        await emit_runtime_action_completed(
            context,
            action=L3_ACTION_REMEMBER_SESSION,
        )

        return getattr(
            context,
            "runtime_l3_session_memory",
            DEFAULT_RUNTIME_L3_SESSION_MEMORY,
        )

    current_session_memory = getattr(
        context,
        "runtime_l3_session_memory",
        "",
    ) or getattr(
        context,
        "session_memory",
        "",
    )

    saved_runtime_snapshot_index = getattr(
        context,
        "runtime_l3_saved_runtime_snapshot_index",
        None,
    )
    unsaved_snapshots = select_l3_unsaved_runtime_snapshots(
        snapshots,
        saved_runtime_snapshot_index=saved_runtime_snapshot_index,
    )

    if not unsaved_snapshots:
        await log_memory_event(
            context,
            level=L3_LOG_LEVEL,
            message=L3_SKIP_NO_NEW_SNAPSHOTS_MESSAGE,
            fallback_channel="runtime",
        )

        context.runtime_remember_session_armed = False
        context.runtime_remember_session_requested = False

        await emit_runtime_action_completed(
            context,
            action=L3_ACTION_REMEMBER_SESSION,
        )

        return current_session_memory

    unsaved_diff_history = select_l3_unsaved_diff_history(
        list(
            getattr(
                context,
                "runtime_l1_diff_history",
                [],
            )
            or []
        ),
        saved_runtime_snapshot_index=saved_runtime_snapshot_index,
    )
    unsaved_session_event_snapshots = select_l3_unsaved_session_events(
        list(
            getattr(
                context,
                "runtime_session_event_snapshots",
                [],
            )
            or []
        ),
        saved_runtime_snapshot_index=saved_runtime_snapshot_index,
    )

    try:
        response = await ask_runtime_session_memory_model(
            context=context,
            service_client=service_client,
            current_session_memory=current_session_memory,
            runtime_memory_snapshots=unsaved_snapshots,
            diff_history=unsaved_diff_history,
            session_event_snapshots=unsaved_session_event_snapshots,
        )

        updated_session_memory = extract_runtime_memory_text(
            response
        )

        skip_reason = None

        if is_runtime_memory_response_truncated(response):
            await log_memory_event(
                context,
                level=L3_LOG_LEVEL,
                message=L3_SUMMARIZER_REACHED_MAX_TOKENS_MESSAGE,
                fallback_channel="runtime",
            )

            skip_reason = L3_RESPONSE_TRUNCATED_REASON

        elif (
                updated_session_memory.strip()
                and looks_like_incomplete_runtime_memory(
            updated_session_memory
        )
        ):
            skip_reason = L3_STRUCTURALLY_INCOMPLETE_REASON

        if skip_reason:
            await log_memory_event(
                context,
                level=L3_LOG_LEVEL,
                message=L3_UPDATE_SKIPPED_MESSAGE,
                details=build_memory_update_skip_details(
                    reason=skip_reason,
                    previous_memory=current_session_memory,
                    candidate_memory=updated_session_memory,
                ),
                fallback_channel="error",
            )

            await emit_runtime_action_completed(
                context,
                action=L3_ACTION_REMEMBER_SESSION,
            )

            return current_session_memory

        if updated_session_memory.strip():
            updated_session_memory = prepend_l3_session_snapshot_metadata(
                updated_session_memory,
                previous_session_memory=current_session_memory,
                runtime_memory_snapshots=unsaved_snapshots,
            )
            session_metadata = parse_l3_session_snapshot_metadata(
                updated_session_memory
            )

            context.runtime_l3_session_memory = updated_session_memory
            context.session_memory = updated_session_memory
            context.session_memory_source = L3_SESSION_MEMORY_SOURCE
            context.runtime_l3_session_first_turn = session_metadata.get(
                "session_snapshot_first_turn"
            )
            context.runtime_l3_session_last_turn = session_metadata.get(
                "session_snapshot_last_turn"
            )
            context.runtime_l3_saved_runtime_snapshot_index = max(
                snapshot.get(
                    "index",
                    0,
                )
                for snapshot in unsaved_snapshots
            )
            context.runtime_session_memory_updates = (
                getattr(
                    context,
                    "runtime_session_memory_updates",
                    0,
                )
                + 1
            )
            context.runtime_remember_session_armed = False
            context.runtime_remember_session_requested = False

            runtime_snapshots = getattr(
                context,
                "runtime_memory_snapshots",
                [],
            )
            if runtime_snapshots:
                context.runtime_memory_snapshot_index = (
                    len(runtime_snapshots) - 1
                )

            await log_memory_event(
                context,
                level=L3_LOG_LEVEL,
                message=L3_UPDATED_MESSAGE,
                fallback_channel="service",
            )

            await log_runtime_summarizer_result(
                context,
                label=L3_LOG_LABEL_SESSION_MEMORY,
                result=updated_session_memory,
            )

            await emit_runtime_session_memory_update(
                context,
                persist_browser=True,
            )

        await emit_runtime_action_completed(
            context,
            action=L3_ACTION_REMEMBER_SESSION,
        )

        return getattr(
            context,
            "runtime_l3_session_memory",
            DEFAULT_RUNTIME_L3_SESSION_MEMORY,
        )

    except asyncio.CancelledError:
        raise

    except L3PromptBudgetExceeded as error:
        await log_memory_event(
            context,
            level=L3_LOG_LEVEL,
            message=L3_UPDATE_SKIPPED_MESSAGE,
            details=L3_BUDGET_EXCEEDED_DETAILS_TEMPLATE.format(
                diagnostic=json.dumps(
                    error.diagnostic,
                    ensure_ascii=False,
                    indent=2,
                ),
            ),
            fallback_channel="error",
        )

        await emit_runtime_action_completed(
            context,
            action=L3_ACTION_REMEMBER_SESSION,
        )

        return current_session_memory

    except Exception as error:
        formatted_traceback = (
            traceback.format_exc()
        )

        await log_memory_event(
            context,
            level=L3_LOG_LEVEL,
            message=L3_UPDATE_FAILED_MESSAGE,
            details=build_memory_failure_details(
                stage=L3_SUMMARIZER_STAGE,
                error=error,
                traceback_text=formatted_traceback,
            ),
            fallback_channel="error",
        )

        await emit_runtime_action_completed(
            context,
            action=L3_ACTION_REMEMBER_SESSION,
        )

        return current_session_memory
