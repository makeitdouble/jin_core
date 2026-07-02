import asyncio

from config_loader import (
    config,
)
from rules.runtime import (
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)

from clients.errors import (
    format_client_error,
)

from rules.assembler import (
    build_brain_system_prompt,
    get_enabled_runtime_actions,
)

from clients.brain_client_utils import (
    apply_runtime_action_calls,
    log_runtime_action_marker_removals,
    should_execute_save_delayed_memory,
    should_execute_save_session,
)

from clients.service_client import (
    ask_service_model,
    ask_service_model_stream,
)

from clients.response_extractor import (
    ResponseExtractor,
)

from utils.runtime_actions import (
    RuntimeActionStreamFilter,
    extract_runtime_actions,
)


def get_response_enabled_runtime_actions(
    runtime_actions=None,
    user_message: str = "",
) -> tuple[str, ...]:

    enabled_actions = list(
        get_enabled_runtime_actions(
            runtime_actions
        )
    )

    if (
        RUNTIME_ACTION_SAVE_SESSION
        in enabled_actions
        and not should_execute_save_session(
            user_message
        )
    ):
        enabled_actions.remove(
            RUNTIME_ACTION_SAVE_SESSION
        )

    if (
        RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
        in enabled_actions
        and not should_execute_save_delayed_memory(
            user_message
        )
    ):
        enabled_actions.remove(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
        )

    return tuple(
        enabled_actions
    )


async def emit_active_memory_records_update_if_dirty(
    context,
) -> None:

    if context is None:
        return

    if not getattr(
        context,
        "runtime_active_memory_records_dirty",
        False,
    ):
        return

    context.runtime_active_memory_records_dirty = False

    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )

    if emit is None:
        return

    await emit({
        "type": "active_memory_records_update",
        "active_memory_records": list(
            getattr(
                context,
                "active_memory_records",
                [],
            )
            or []
        ),
    })


# ---------------------------------------------------------
# PAYLOAD
# ---------------------------------------------------------

def build_brain_payload(
    text: str,
    context=None,
) -> str:

    return text


# ---------------------------------------------------------
# NORMAL REQUEST
# ---------------------------------------------------------

async def ask_brain(
    *,
    client,
    text: str,
    context=None,
    runtime_actions=None,
) -> str:

    brain_payload = (
        build_brain_payload(
            text,
            context=context,
        )
    )

    system_prompt = (
        build_brain_system_prompt(
            context,
            runtime_actions,
            user_input=brain_payload,
            commit_active_memory_refresh=True,
        )
    )

    await emit_active_memory_records_update_if_dirty(
        context
    )

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            result = await ask_service_model(
                client=client,
                user_prompt=brain_payload,
                system_prompt=system_prompt,
                temperature=(
                    config.BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config.BRAIN_MAX_TOKENS
                ),
            )

            reasoning = (
                ResponseExtractor.extract_reasoning_text(
                    result
                )
            )

            content = (
                ResponseExtractor
                .extract_content_text(
                    result
                )
            )

            enabled_actions = get_response_enabled_runtime_actions(
                runtime_actions,
                text,
            )

            content_actions = (
                extract_runtime_actions(
                    content,
                    enabled_actions=enabled_actions,
                )
            )

            await log_runtime_action_marker_removals(
                context,
                content_actions,
                source="brain content",
            )

            await apply_runtime_action_calls(
                context,
                content_actions.actions,
                user_message=text,
            )

            return content_actions.text

        except Exception as error:

            formatted_error = (
                format_client_error(
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        result = await client.ask(
            system_prompt=system_prompt,
            user_prompt=brain_payload,
            temperature=(
                config
                .BRAIN_TEMPERATURE
            ),
            max_tokens=(
                config
                .BRAIN_MAX_TOKENS
            ),
        )

        returned_model = (
            ResponseExtractor
            .extract_model(
                result
            )
        )

        if (
            returned_model
            != config.BRAIN_MODEL_UID
        ):

            raise RuntimeError(
                f"Wrong model loaded. "
                f"Expected "
                f"'{config.BRAIN_MODEL_UID}', "
                f"got "
                f"'{returned_model}'"
            )

        reasoning = (
            ResponseExtractor
            .extract_reasoning_text(
                result
            )
        )

        content = (
            ResponseExtractor
            .extract_content_text(
                result
            )
        )

        enabled_actions = get_response_enabled_runtime_actions(
            runtime_actions,
            text,
        )

        content_actions = extract_runtime_actions(
            content,
            enabled_actions=enabled_actions,
        )

        await log_runtime_action_marker_removals(
            context,
            content_actions,
            source="brain content",
        )

        await apply_runtime_action_calls(
            context,
            content_actions.actions,
            user_message=text,
        )

        if content_actions.text:
            return content_actions.text

        reasoning_actions = extract_runtime_actions(
            reasoning,
            enabled_actions=enabled_actions,
        )

        await log_runtime_action_marker_removals(
            context,
            reasoning_actions,
            source="brain reasoning fallback",
        )

        return reasoning_actions.text

    except Exception as error:

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )


# ---------------------------------------------------------
# STREAM REQUEST
# ---------------------------------------------------------

async def ask_brain_stream(
    *,
    client,
    text: str,
    context,
    system_prompt: str | None = None,
    brain_payload: str | None = None,
    runtime_actions=None,
):

    resolved_brain_payload: str = (
        brain_payload
        or build_brain_payload(
            text,
            context=context,
        )
    )

    resolved_system_prompt: str = (
        system_prompt
        or build_brain_system_prompt(
            context,
            runtime_actions,
            user_input=resolved_brain_payload,
            commit_active_memory_refresh=True,
        )
    )

    if system_prompt is None:
        await emit_active_memory_records_update_if_dirty(
            context
        )

    enabled_actions = get_response_enabled_runtime_actions(
        runtime_actions,
        text,
    )

    content_filter = RuntimeActionStreamFilter(
        enabled_actions=enabled_actions,
        #preserve_action_text=True
    )
    stop_for_runtime_action = False
    delayed_memory_bubble_started = False

    async def emit_delayed_memory_bubble_started():

        nonlocal delayed_memory_bubble_started

        if delayed_memory_bubble_started:
            return

        pending = str(
            getattr(
                content_filter,
                "pending",
                "",
            )
            or ""
        ).upper()

        if "INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT" not in pending:
            return

        delayed_memory_bubble_started = True

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            await emit({
                "type": "runtime_action",
                "action": "save_delayed_memory_content",
                "status": "started",
                "text": "Saving delayed memory report",
            })

    async def filter_runtime_action_chunk(
        action_chunk,
    ):

        nonlocal stop_for_runtime_action

        chunk_type = action_chunk.get(
            "type"
        )

        if chunk_type not in (
            "thinking",
            "content",
        ):
            return action_chunk

        if chunk_type == "thinking":
            return action_chunk

        result = content_filter.filter(
            action_chunk.get(
                "content",
                "",
            )
        )

        await emit_delayed_memory_bubble_started()

        await log_runtime_action_marker_removals(
            context,
            result,
            source="brain stream content",
        )

        if await apply_runtime_action_result(
            result
        ):

            if not stop_for_runtime_action:
                if not result.text:
                    return None

                return {
                    **action_chunk,
                    "content": result.text,
                }

            return None

        if not result.text:
            return None

        return {
            **action_chunk,
            "content": result.text,
        }

    async def apply_runtime_action_result(
        result,
    ) -> bool:

        nonlocal stop_for_runtime_action

        runtime_action_calls = tuple(
            result.actions
        )

        if not runtime_action_calls:
            return False

        await apply_runtime_action_calls(
            context,
            runtime_action_calls,
            user_message=text,
        )

        if any(
            action.name in (
                RUNTIME_ACTION_WEB_SEARCH,
                RUNTIME_ACTION_LIST_SKILLS,
            )
            for action in runtime_action_calls
        ):
            stop_for_runtime_action = True

        return True

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            async for model_chunk in (
                ask_service_model_stream(
                    context=context,
                    client=client,
                    user_prompt=(
                        resolved_brain_payload
                    ),
                    system_prompt=(
                        resolved_system_prompt
                    ),
                    temperature=(
                        config
                        .BRAIN_TEMPERATURE
                    ),
                    max_tokens=(
                        config
                        .BRAIN_MAX_TOKENS
                    ),
                )
            ):

                filtered_chunk = (
                    await filter_runtime_action_chunk(
                        model_chunk
                    )
                )

                if filtered_chunk:
                    yield filtered_chunk

                if stop_for_runtime_action:
                    break

            tail_result = content_filter.flush_result()

            await log_runtime_action_marker_removals(
                context,
                tail_result,
                source="brain stream tail",
            )

            await apply_runtime_action_result(
                tail_result
            )

            content_tail = tail_result.text
            if (
                content_tail
                and not stop_for_runtime_action
            ):
                yield {
                    "type": "content",
                    "content": content_tail,
                }

            return

        except asyncio.CancelledError:
            raise

        except Exception as error:

            formatted_error = (
                format_client_error(
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        async for model_chunk in (
            client.stream(
                context=context,
                system_prompt=(
                    resolved_system_prompt
                ),
                user_prompt=resolved_brain_payload,
                temperature=(
                    config
                    .BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config
                    .BRAIN_MAX_TOKENS
                ),
            )
        ):

            filtered_chunk = (
                await filter_runtime_action_chunk(
                    model_chunk
                )
            )

            if filtered_chunk:
                yield filtered_chunk

            if stop_for_runtime_action:
                break

        tail_result = content_filter.flush_result()

        await log_runtime_action_marker_removals(
            context,
            tail_result,
            source="brain stream tail",
        )

        await apply_runtime_action_result(
            tail_result
        )

        content_tail = tail_result.text
        if (
            content_tail
            and not stop_for_runtime_action
        ):
            yield {
                "type": "content",
                "content": content_tail,
            }

    except asyncio.CancelledError:
        raise

    except Exception as error:

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )
