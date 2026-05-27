import asyncio
from datetime import datetime

from settings.config_loader import (
    config,
)
from contracts.context_contract import (
    ContextContract,
    DEEP_THOUGHT_ACTION,
    RUNTIME_ACTION_DEEP_THOUGHT,
    RUNTIME_ACTION_SEARCH,
    SEARCH_ACTION_TEMPLATE,
    cdata,
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
    extract_search_query,
    extract_runtime_actions,
)


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

def get_enabled_runtime_actions(
    runtime_actions=None,
) -> tuple[str, ...]:

    enabled_actions = []

    action_flags = runtime_actions or {}

    for action_name, config_key in (
        (
            RUNTIME_ACTION_DEEP_THOUGHT,
            "CAN_DEEP_THOUGHT",
        ),
        (
            RUNTIME_ACTION_SEARCH,
            "CAN_SEARCH",
        ),
    ):

        if bool(
            action_flags.get(
                config_key,
                False,
            )
        ):
            enabled_actions.append(
                action_name
            )

    return tuple(
        enabled_actions
    )


def build_runtime_action_instructions(
    enabled_actions: tuple[str, ...],
) -> str:

    instructions = [
        "Use only runtime action markers listed in trusted runtime XML. "
        "Do not invent new marker names or arguments."
    ]

    if RUNTIME_ACTION_DEEP_THOUGHT in enabled_actions:
        instructions.append(
            "Before answering, emit exactly "
            f"{DEEP_THOUGHT_ACTION} once when the current request asks you to "
            "think carefully/deeply, compare designs, make a multi-step judgment, "
            "debug architecture, reflect on your own state, or handle high uncertainty. "
            "Do not emit it for simple greetings, direct factual answers, or casual small talk. "
            "The marker takes no arguments for now. Do not explain it."
        )

    if RUNTIME_ACTION_SEARCH in enabled_actions:
        instructions.append(
            "When the answer needs external search, current facts, or source lookup, "
            "emit the SEARCH runtime action with a short JSON query, for example "
            f"{SEARCH_ACTION_TEMPLATE}. "
            "The SEARCH query must preserve the exact subject, item, product, place, "
            "or entity from the user request. Do not replace it with a related item. "
            "Emit exactly one JSON object with one field: {\"query\":\"plain search query\"}. "
            "The query value must be plain text, not another JSON object or JSON string. "
            "The runtime hides the marker from chat text. Do not present guessed search results "
            "as facts before the runtime provides them."
        )

    if not enabled_actions:
        instructions.append(
            "No runtime actions are currently enabled; do not emit runtime action markers."
        )

    return "\n".join(
        instructions
    )


def build_runtime_state_instructions(
    enabled_actions: tuple[str, ...],
) -> str:

    instructions = [
        "Do not invent, reset, or update internal state values yourself; "
        "only trust the values provided in trusted runtime XML."
    ]

    if RUNTIME_ACTION_DEEP_THOUGHT in enabled_actions:
        instructions.append(
            "DEEP_THOUGHT_COUNTER is telemetry from earlier runtime actions; "
            "it must not by itself trigger or forbid a new runtime action."
        )

    return " ".join(
        instructions
    )


def count_deep_thought_calls(
    text: str,
    runtime_actions=None,
) -> int:

    return (
        extract_runtime_actions(
            text,
            enabled_actions=(
                get_enabled_runtime_actions(
                    runtime_actions
                )
            ),
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
    log_runtime = getattr(
        logger,
        "log_runtime",
        None,
    )

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] "
            f"deep_thought x{call_count}; "
            f"counter={context.deep_thought_count}"
        )

    return call_count


async def apply_runtime_action_calls(
    context,
    actions,
) -> int:

    if (
        context is None
        or not actions
    ):
        return 0

    if not hasattr(
        context,
        "runtime_action_events",
    ):
        context.runtime_action_events = []

    for action in actions:

        action_event = {
            "name": action.name.lower(),
        }

        query = ""

        if action.name == RUNTIME_ACTION_SEARCH:
            query = extract_search_query(
                action.payload
            )

        if query:
            action_event["query"] = query

        elif action.payload:
            action_event["payload"] = (
                action.payload
            )

        context.runtime_action_events.append(
            action_event
        )

    deep_thought_count = sum(
        1
        for action in actions
        if action.name == RUNTIME_ACTION_DEEP_THOUGHT
    )

    applied_count = await apply_deep_thought_calls(
        context,
        min(
            deep_thought_count,
            1,
        ),
    )

    search_queries = [
        query
        for query in (
            extract_search_query(
                action.payload
            )
            for action in actions
            if action.name == RUNTIME_ACTION_SEARCH
        )
        if query
    ]

    if search_queries:
        if not hasattr(
            context,
            "runtime_search_queries",
        ):
            context.runtime_search_queries = []

        context.runtime_search_queries.extend(
            search_queries
        )

    logger = getattr(
        context,
        "logger",
        None,
    )
    log_runtime = getattr(
        logger,
        "log_runtime",
        None,
    )

    if (
        log_runtime is not None
        and search_queries
    ):
        await log_runtime(
            "[RUNTIME ACTION] "
            f"search x{len(search_queries)}"
        )

    return applied_count + len(
        search_queries
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
    runtime_actions=None,
) -> str:

    deep_thought_count = 0
    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )

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
        can_deep_thought=(
            RUNTIME_ACTION_DEEP_THOUGHT
            in enabled_actions
        ),
        can_search=(
            RUNTIME_ACTION_SEARCH
            in enabled_actions
        ),
        timestamp=now.isoformat(),
        current_date=now.date().isoformat(),
        current_time=now.strftime("%H:%M:%S"),
        weekday=now.strftime("%A"),
        year=now.year,
    )

    runtime_xml = (
        context_contract
        .to_runtime_xml()
    )

    search_result = ""

    if context is not None:
        search_result = getattr(
            context,
            "runtime_search_result",
            "",
        )

    if not search_result:
        return runtime_xml

    tool_results_xml = (
        "<TOOL_RESULTS>\n"
        "    <TOOL_RESULT name=\"SEARCH\">\n"
        f"        {cdata(search_result)}\n"
        "    </TOOL_RESULT>\n"
        "</TOOL_RESULTS>"
    )

    return (
        runtime_xml
        + "\n"
        + tool_results_xml
    )


def build_brain_system_prompt(
    context=None,
    runtime_actions=None,
) -> str:

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )

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
        f"{build_runtime_action_instructions(enabled_actions)}\n"
        f"{build_runtime_state_instructions(enabled_actions)}\n"
        "Never mention Initial state, timestamps, internal function names, "
        "or counters in the chat unless the user explicitly asks about them.\n"
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
                        context,
                        runtime_actions,
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
                    reasoning,
                    enabled_actions=(
                        get_enabled_runtime_actions(
                            runtime_actions
                        )
                    ),
                )
            )

            content_actions = (
                extract_runtime_actions(
                    content,
                    enabled_actions=(
                        get_enabled_runtime_actions(
                            runtime_actions
                        )
                    ),
                )
            )

            await apply_runtime_action_calls(
                context,
                (
                    reasoning_actions.actions
                    + content_actions.actions
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
                    context,
                    runtime_actions,
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
            reasoning,
            enabled_actions=(
                get_enabled_runtime_actions(
                    runtime_actions
                )
            ),
        )

        content_actions = extract_runtime_actions(
            content,
            enabled_actions=(
                get_enabled_runtime_actions(
                    runtime_actions
                )
            ),
        )

        await apply_runtime_action_calls(
            context,
            (
                reasoning_actions.actions
                + content_actions.actions
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

    thinking_filter = RuntimeActionStreamFilter(
        enabled_actions=enabled_actions
    )
    content_filter = RuntimeActionStreamFilter(
        enabled_actions=enabled_actions
    )
    deep_thought_action_executed = False

    async def filter_runtime_action_chunk(
        action_chunk,
    ):

        nonlocal deep_thought_action_executed

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
            )

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
