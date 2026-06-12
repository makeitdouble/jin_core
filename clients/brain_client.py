import asyncio

from config_loader import (
    config,
)
from runtime.context_contract import (
    RUNTIME_ACTION_DEEP_THOUGHT,
    RUNTIME_ACTION_WEB_SEARCH,
)
from bootstrap.brain_bootstrap import (
    ZERO_DIFF_STALL_ACTIVE_RULE,
    build_brain_runtime_interface_rules,
    build_brain_soft_success_rules,
    build_identity_context,
    get_image_input_rules,
)

from clients.errors import (
    format_client_error,
)

from clients.brain_context_builder import (
    build_brain_runtime_context,
)

from clients.brain_client_utils import (
    MAX_PREVIOUS_THINK_CHARS,
    MAX_PREVIOUS_THINK_SECTION_CHARS,
    apply_runtime_action_calls,
    build_conditional_prompt_rules,
    build_previous_think_block,
    count_deep_thought_calls,
    extract_previous_think_tail,
    get_enabled_runtime_actions,
    get_enabled_thinking_runtime_actions,
    get_previous_think_context_block,
    has_zero_diff_stall_alert,
    is_user_initiated_remember_event,
    log_previous_think_payload,
    record_deep_thought_calls,
    record_previous_think,
    should_execute_remember_session,
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




def build_brain_system_prompt(
    context=None,
    runtime_actions=None,
) -> str:

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )

    zero_diff_stall_active = has_zero_diff_stall_alert(
        context
    )

    soft_rules = ""

    if zero_diff_stall_active:
        soft_rules = (
            ZERO_DIFF_STALL_ACTIVE_RULE
        )
    else:
        soft_rules = build_brain_soft_success_rules()

    return (
        f"{build_identity_context(context)}"
        f"{soft_rules}"
        f"{build_conditional_prompt_rules(context)}"
        f"{build_brain_runtime_interface_rules(enabled_actions)}"
        "\n"
        f"{build_brain_runtime_context(context, runtime_actions)}"
    )


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
        )
    )

    await log_previous_think_payload(
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

            enabled_actions = get_enabled_runtime_actions(
                runtime_actions
            )
            thinking_actions = get_enabled_thinking_runtime_actions(
                runtime_actions
            )

            reasoning_actions = (
                extract_runtime_actions(
                    reasoning,
                    enabled_actions=thinking_actions,
                    preserve_action_text=True,
                )
            )

            content_actions = (
                extract_runtime_actions(
                    content,
                    enabled_actions=enabled_actions,
                )
            )

            await apply_runtime_action_calls(
                context,
                (
                    reasoning_actions.actions
                    + content_actions.actions
                ),
                user_message=text,
            )

            record_previous_think(
                context,
                reasoning,
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

        enabled_actions = get_enabled_runtime_actions(
            runtime_actions
        )
        thinking_actions = get_enabled_thinking_runtime_actions(
            runtime_actions
        )

        reasoning_actions = extract_runtime_actions(
            reasoning,
            enabled_actions=thinking_actions,
            preserve_action_text=True,
        )

        content_actions = extract_runtime_actions(
            content,
            enabled_actions=enabled_actions,
        )

        await apply_runtime_action_calls(
            context,
            (
                reasoning_actions.actions
                + content_actions.actions
            ),
            user_message=text,
        )

        record_previous_think(
            context,
            reasoning,
        )

        if content_actions.text:
            return content_actions.text

        return extract_runtime_actions(
            reasoning,
            enabled_actions=thinking_actions,
        ).text

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
        )
    )

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )
    thinking_actions = get_enabled_thinking_runtime_actions(
        runtime_actions
    )

    thinking_filter = RuntimeActionStreamFilter(
        enabled_actions=thinking_actions,
        preserve_action_text=True,
    )
    content_filter = RuntimeActionStreamFilter(
        enabled_actions=enabled_actions
    )
    deep_thought_action_executed = False
    stop_for_runtime_action = False

    async def filter_runtime_action_chunk(
        action_chunk,
    ):

        nonlocal deep_thought_action_executed
        nonlocal stop_for_runtime_action

        chunk_type = action_chunk.get(
            "type"
        )

        if chunk_type not in (
            "thinking",
            "content",
        ):
            return action_chunk

        stream_filter = (
            thinking_filter
            if chunk_type == "thinking"
            else content_filter
        )

        result = stream_filter.filter(
            action_chunk.get(
                "content",
                "",
            )
        )

        if (
            result.deep_thought_count
            and not deep_thought_action_executed
        ):

            deep_thought_action_executed = True

            await apply_deep_thought_calls(
                context,
                1,
            )

        non_deep_actions = tuple(
            action
            for action in result.actions
            if action.name != RUNTIME_ACTION_DEEP_THOUGHT
        )

        if non_deep_actions:
            await apply_runtime_action_calls(
                context,
                non_deep_actions,
                user_message=text,
            )

            stop_for_runtime_action = any(
                action.name == RUNTIME_ACTION_WEB_SEARCH
                for action in non_deep_actions
            )

            if not stop_for_runtime_action:
                if not result.text:
                    return None

                return {
                    **action_chunk,
                    "content": result.text,
                }

            if (
                chunk_type == "thinking"
                and result.text
            ):
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

            thinking_tail = thinking_filter.flush()
            if (
                thinking_tail
                and not stop_for_runtime_action
            ):
                yield {
                    "type": "thinking",
                    "content": thinking_tail,
                }

            content_tail = content_filter.flush()
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

        thinking_tail = thinking_filter.flush()
        if (
            thinking_tail
            and not stop_for_runtime_action
        ):
            yield {
                "type": "thinking",
                "content": thinking_tail,
            }

        content_tail = content_filter.flush()
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
