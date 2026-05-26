import asyncio
from datetime import datetime

from settings.config_loader import (
    config,
)
from contracts.context_contract import (
    ContextContract,
    DEEP_THOUGHT_ACTION,
)

from utils.errors import (
    format_client_error,
)

from clients.service_client import (
    ask_service_model,
    ask_service_model_stream,
)

from utils.response_extractor import (
    ResponseExtractor,
)

from utils.runtime_actions import (
    RuntimeActionStreamFilter,
    extract_runtime_actions,
)


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

def count_deep_thought_calls(
    text: str,
) -> int:

    return (
        extract_runtime_actions(
            text
        )
        .deep_thought_count
    )


async def apply_deep_thought_calls(
    context,
    call_count: int,
) -> int:

    if (
        context is None
        or not call_count
    ):
        return 0

    current_count = getattr(
        context,
        "deep_thought_count",
        0,
    )

    context.deep_thought_count = (
        current_count
        + call_count
    )

    logger = getattr(
        context,
        "logger",
        None,
    )

    if logger is not None:
        await logger.log_runtime(
            "[RUNTIME ACTION] "
            f"deep_thought x{call_count}; "
            f"counter={context.deep_thought_count}"
        )

    return call_count


def record_deep_thought_calls(
    context,
    reasoning: str,
) -> int:

    call_count = count_deep_thought_calls(
        reasoning
    )

    if not call_count:
        return 0

    call_count = min(
        call_count,
        1,
    )

    current_count = getattr(
        context,
        "deep_thought_count",
        0,
    )

    context.deep_thought_count = (
        current_count
        + call_count
    )

    return call_count


def build_brain_runtime_context(
    context=None,
) -> str:

    deep_thought_count = 0

    if context is not None:

        deep_thought_count = getattr(
            context,
            "deep_thought_count",
            0,
        )

    now = datetime.now()

    context_contract = ContextContract(
        user_input="",
        compressed_history="",
        system_state="ACTIVE",
        deep_thought_count=deep_thought_count,
        timestamp=now.isoformat(),
        current_date=now.date().isoformat(),
        current_time=now.strftime("%H:%M:%S"),
        weekday=now.strftime("%A"),
        year=now.year,
    )

    return context_contract.to_runtime_xml()


def build_brain_system_prompt(
    context=None,
) -> str:

    return (
        "You are JIN, a human-like assistant.\n"
        "NEVER explain your reasoning.\n"
        "NEVER analyze the request.\n"
        "NEVER describe your plan.\n"
        "NEVER output chain-of-thought.\n"
        "Reply with ONLY the final answer.\n"
        "Keep responses natural and conversational.\n"
        "When asked what, who, or where you are, answer as JIN in the current conversation. "
        "Do not identify yourself as a language model, LLM, AI model, provider model, "
        "or server process unless the user explicitly asks for technical implementation details.\n"
        "Use the trusted runtime XML as interface data, not as chat content.\n"
        "Runtime action markers are allowed control events, not chat text. "
        "The runtime hides them from the user before rendering.\n"
        "Before answering, emit exactly "
        f"{DEEP_THOUGHT_ACTION} once when the current request asks you to "
        "think carefully/deeply, compare designs, make a multi-step judgment, "
        "debug architecture, reflect on your own state, or handle high uncertainty. "
        "Do not emit it for simple greetings, direct factual answers, or casual small talk. "
        "The marker takes no arguments for now. Do not explain it.\n"
        "Do not invent, reset, or update internal counters yourself; "
        "only trust the values provided in trusted runtime XML. "
        "DEEP_THOUGHT_COUNTER is telemetry from earlier runtime actions; "
        "it must not by itself trigger or forbid a new runtime action.\n"
        "Never mention Initial state, timestamps, internal function names, "
        "or counters in the chat unless the user explicitly asks about them.\n"
        "\n"
        f"{build_brain_runtime_context(context)}"
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
) -> str:

    brain_payload = (
        build_brain_payload(
            text,
            context=context,
        )
    )

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            result = await ask_service_model(
                client=client,
                user_prompt=brain_payload,
                system_prompt=(
                    build_brain_system_prompt(
                        context
                    )
                ),
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

            reasoning_actions = (
                extract_runtime_actions(
                    reasoning
                )
            )

            content_actions = (
                extract_runtime_actions(
                    content
                )
            )

            await apply_deep_thought_calls(
                context,
                min(
                    (
                        reasoning_actions.deep_thought_count
                        + content_actions.deep_thought_count
                    ),
                    1,
                ),
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
            system_prompt=(
                build_brain_system_prompt(
                    context
                )
            ),
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

        reasoning_actions = extract_runtime_actions(
            reasoning
        )

        content_actions = extract_runtime_actions(
            content
        )

        await apply_deep_thought_calls(
            context,
            min(
                (
                    reasoning_actions.deep_thought_count
                    + content_actions.deep_thought_count
                ),
                1,
            ),
        )

        if content_actions.text:
            return content_actions.text

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
            context
        )
    )

    thinking_filter = RuntimeActionStreamFilter()
    content_filter = RuntimeActionStreamFilter()
    deep_thought_action_executed = False

    async def filter_runtime_action_chunk(
        chunk,
    ):

        nonlocal deep_thought_action_executed

        chunk_type = chunk.get(
            "type"
        )

        if chunk_type not in (
            "thinking",
            "content",
        ):
            return chunk

        stream_filter = (
            thinking_filter
            if chunk_type == "thinking"
            else content_filter
        )

        result = stream_filter.filter(
            chunk.get(
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

        if not result.text:
            return None

        return {
            **chunk,
            "content": result.text,
        }

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            async for chunk in (
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
                        chunk
                    )
                )

                if filtered_chunk:
                    yield filtered_chunk

            thinking_tail = thinking_filter.flush()
            if thinking_tail:
                yield {
                    "type": "thinking",
                    "content": thinking_tail,
                }

            content_tail = content_filter.flush()
            if content_tail:
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

        async for chunk in (
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
                    chunk
                )
            )

            if filtered_chunk:
                yield filtered_chunk

        thinking_tail = thinking_filter.flush()
        if thinking_tail:
            yield {
                "type": "thinking",
                "content": thinking_tail,
            }

        content_tail = content_filter.flush()
        if content_tail:
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
