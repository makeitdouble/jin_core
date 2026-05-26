import config
import asyncio
from datetime import datetime
from contracts.context_contract import (
    ContextContract,
    DEEP_THOUGHT_CALL,
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


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

def count_deep_thought_calls(
    text: str,
) -> int:

    if not text:
        return 0

    return text.count(
        DEEP_THOUGHT_CALL
    )


def record_deep_thought_calls(
    context,
    reasoning: str,
) -> int:

    call_count = count_deep_thought_calls(
        reasoning
    )

    if not call_count:
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

    return call_count


def build_brain_system_prompt():

    return (
        "You are JIN, a human-like assistant.\n"
        "NEVER explain your reasoning.\n"
        "NEVER analyze the request.\n"
        "NEVER describe your plan.\n"
        "NEVER output chain-of-thought.\n"
        "Reply with ONLY the final answer.\n"
        "Keep responses natural and conversational.\n"
        "Use the XML context as interface data, not as chat content.\n"
        "If private reasoning genuinely needs a deep reflection marker, "
        f"write exactly {DEEP_THOUGHT_CALL} once in private reasoning. "
        "It takes no arguments for now.\n"
        "Do not invent, reset, or update internal counters yourself; "
        "only trust the values provided in XML.\n"
        "Never mention Initial state, timestamps, internal function names, "
        "or counters in the chat unless the user explicitly asks about them.\n"
    )


# ---------------------------------------------------------
# PAYLOAD
# ---------------------------------------------------------

def build_brain_payload(
    text: str,
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
        user_input=text,
        compressed_history="",
        system_state="ACTIVE",
        deep_thought_count=deep_thought_count,
        timestamp=now.isoformat(),
        current_date=now.date().isoformat(),
        current_time=now.strftime("%H:%M:%S"),
        weekday=now.strftime("%A"),
        year=now.year,
    )

    return context_contract.to_xml()


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
                    build_brain_system_prompt()
                ),
                temperature=(
                    config.BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config.BRAIN_MAX_TOKENS
                ),
            )

            if context is not None:

                record_deep_thought_calls(
                    context,
                    ResponseExtractor.extract_reasoning_text(
                        result
                    ),
                )

            return (
                ResponseExtractor
                .extract_content_text(
                    result
                )
            )

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
                build_brain_system_prompt()
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

        content = (
            ResponseExtractor
            .extract_content_text(
                result
            )
        )

        if context is not None:

            record_deep_thought_calls(
                context,
                ResponseExtractor.extract_reasoning_text(
                    result
                ),
            )

        if content:
            return content

        return (
            ResponseExtractor
            .extract_reasoning_text(
                result
            )
        )

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
    context
):

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

            async for chunk in (
                ask_service_model_stream(
                    context=context,
                    client=client,
                    user_prompt=(
                        brain_payload
                    ),
                    system_prompt=(
                        build_brain_system_prompt()
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

                yield chunk

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
                    build_brain_system_prompt()
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
        ):

            yield chunk

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
