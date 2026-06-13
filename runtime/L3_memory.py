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
    L3_INPUT_TOKEN_RESERVE,
    L3_INPUT_TOKEN_TARGET_MAX,
    L3_OUTPUT_MAX_TOKENS,
)
from runtime.memory_utils import (
    build_runtime_session_memory_system_prompt,
    build_runtime_session_memory_user_prompt,
)
from runtime.memory_common import (
    build_memory_failure_details,
    build_memory_update_skip_details,
    build_runtime_summarizer_payload,
    build_runtime_summarizer_user_prompt,
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
from utils.tokens import (
    estimate_runtime_tokens,
)

def build_l3_session_memory_max_tokens(
        *,
        system_prompt: str,
        user_prompt: str,
        context_window: int | None = None,
) -> int:

    prompt_tokens = estimate_runtime_tokens(
        system_prompt=system_prompt,
        user_input=user_prompt,
    )
    effective_context_window = (
        context_window
        or config.SERVICE_CONTEXT_WINDOW
    )
    response_budget = (
        effective_context_window
        - prompt_tokens
        - 128
    )

    return max(
        128,
        min(
            config.SERVICE_MAX_TOKENS,
            response_budget,
        ),
    )


class L3PromptBudgetExceeded(
    RuntimeError,
):

    def __init__(
            self,
            diagnostic: dict,
    ):

        super().__init__(
            "L3 session digest exceeds safe input budget"
        )
        self.diagnostic = diagnostic


def get_l3_input_token_budget(
        context_window: int | None,
) -> int:

    effective_context_window = (
        context_window
        or config.SERVICE_CONTEXT_WINDOW
    )

    return max(
        1,
        min(
            L3_INPUT_TOKEN_TARGET_MAX,
            effective_context_window
            - L3_INPUT_TOKEN_RESERVE,
        ),
    )


async def build_budgeted_l3_session_user_prompt(
        *,
        context,
        system_prompt: str,
        current_session_memory: str,
        runtime_memory_snapshots: list[dict],
        diff_history: list[dict],
        runtime_l2_memory: str,
        session_event_snapshots: list[dict],
        context_window: int | None,
) -> tuple[str, dict]:

    target_budget = get_l3_input_token_budget(
        context_window
    )

    for minimal in (
            False,
            True,
    ):
        raw_user_prompt = build_runtime_session_memory_user_prompt(
            current_session_memory=current_session_memory,
            runtime_memory_snapshots=runtime_memory_snapshots,
            diff_history=diff_history,
            runtime_l2_memory=runtime_l2_memory,
            session_event_snapshots=session_event_snapshots,
            minimal=minimal,
        )
        user_prompt = build_runtime_summarizer_user_prompt(
            context=context,
            prompt=raw_user_prompt,
        )
        input_tokens = estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=user_prompt,
        )
        diagnostic = {
            "minimal": minimal,
            "context_window": context_window,
            "input_tokens": input_tokens,
            "target_budget": target_budget,
            "prompt_chars": len(user_prompt),
            "system_prompt_chars": len(system_prompt),
        }

        if input_tokens <= target_budget:
            return user_prompt, diagnostic

    raise L3PromptBudgetExceeded(
        diagnostic
    )


async def ask_runtime_session_memory_model(
        *,
        context=None,
        service_client,
        current_session_memory: str,
        runtime_memory_snapshots: list[dict],
        diff_history: list[dict],
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
                getattr(
                    context,
                    "runtime_session_event_snapshots",
                    [],
                )
                or []
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
            level="L3",
            message=(
                "L3 session output token budget capped at "
                f"{L3_OUTPUT_MAX_TOKENS}"
            ),
            fallback_channel="runtime",
        )

    await log_runtime_summarizer_payload(
        context,
        label="L3 session",
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
            action="remember_session",
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
            level="L3",
            message="L3 session save skipped: no snapshots",
            fallback_channel="runtime",
        )

        await emit_runtime_action_completed(
            context,
            action="remember_session",
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

    try:
        response = await ask_runtime_session_memory_model(
            context=context,
            service_client=service_client,
            current_session_memory=current_session_memory,
            runtime_memory_snapshots=snapshots,
            diff_history=list(
                getattr(
                    context,
                    "runtime_l1_diff_history",
                    [],
                )
                or []
            ),
        )

        updated_session_memory = extract_runtime_memory_text(
            response
        )

        skip_reason = None

        if is_runtime_memory_response_truncated(response):
            await log_memory_event(
                context,
                level="L3",
                message="L3 session summarizer reached max_tokens",
                fallback_channel="runtime",
            )

            skip_reason = "L3 session summarizer response was truncated by max_tokens."

        elif (
                updated_session_memory.strip()
                and looks_like_incomplete_runtime_memory(
            updated_session_memory
        )
        ):
            skip_reason = "L3 session summarizer returned text that looks structurally incomplete."

        if skip_reason:
            await log_memory_event(
                context,
                level="L3",
                message="L3 session memory update skipped",
                details=build_memory_update_skip_details(
                    reason=skip_reason,
                    previous_memory=current_session_memory,
                    candidate_memory=updated_session_memory,
                ),
                fallback_channel="error",
            )

            await emit_runtime_action_completed(
                context,
                action="remember_session",
            )

            return current_session_memory

        if updated_session_memory.strip():
            context.runtime_l3_session_memory = updated_session_memory
            context.session_memory = updated_session_memory
            context.session_memory_source = "L3"
            context.runtime_session_memory_updates = (
                getattr(
                    context,
                    "runtime_session_memory_updates",
                    0,
                )
                + 1
            )
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
                level="L3",
                message="L3 session memory updated",
                fallback_channel="service",
            )

            await log_runtime_summarizer_result(
                context,
                label="L3 session memory",
                result=updated_session_memory,
            )

            await emit_runtime_session_memory_update(
                context,
                persist_browser=True,
            )

        await emit_runtime_action_completed(
            context,
            action="remember_session",
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
            level="L3",
            message="L3 session memory update skipped",
            details=(
                "Reason: compact digest still exceeds safe input budget.\n\n"
                + json.dumps(
                    error.diagnostic,
                    ensure_ascii=False,
                    indent=2,
                )
            ),
            fallback_channel="error",
        )

        await emit_runtime_action_completed(
            context,
            action="remember_session",
        )

        return current_session_memory

    except Exception as error:
        formatted_traceback = (
            traceback.format_exc()
        )

        await log_memory_event(
            context,
            level="L3",
            message="L3 session memory update failed",
            details=build_memory_failure_details(
                stage="L3 session memory summarizer",
                error=error,
                traceback_text=formatted_traceback,
            ),
            fallback_channel="error",
        )

        await emit_runtime_action_completed(
            context,
            action="remember_session",
        )

        return current_session_memory
