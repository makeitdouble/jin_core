import contextlib
import json
from datetime import datetime
from difflib import SequenceMatcher

from clients.errors import (
    format_client_error,
)
from clients.response_extractor import (
    ResponseExtractor,
)
from config_loader import (
    config,
)
from app_settings import (
    settings,
)
from runtime.runtime_context import (
    ContextContract,
)
from runtime.L1_memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
)
from runtime.registry import (
    runtime_state,
)
from runtime.state import (
    RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID,
)
from runtime.state_sync import (
    refresh_runtime_state,
)
from utils.tokens import (
    estimate_runtime_tokens,
)


def build_runtime_summarizer_trusted_context(
        context=None,
) -> str:

    timestamp = (
        getattr(
            context,
            "timestamp",
            "",
        )
        if context is not None
        else ""
    )
    current_date = (
        getattr(
            context,
            "current_date",
            "",
        )
        if context is not None
        else ""
    )
    current_time = (
        getattr(
            context,
            "current_time",
            "",
        )
        if context is not None
        else ""
    )
    weekday = (
        getattr(
            context,
            "weekday",
            "",
        )
        if context is not None
        else ""
    )
    year = (
        getattr(
            context,
            "year",
            None,
        )
        if context is not None
        else None
    )
    turn_number = (
        getattr(
            context,
            "turn_number",
            None,
        )
        if context is not None
        else None
    )
    user_message_count = (
        getattr(
            context,
            "user_message_count",
            None,
        )
        if context is not None
        else None
    )
    assistant_message_count = (
        getattr(
            context,
            "assistant_message_count",
            None,
        )
        if context is not None
        else None
    )

    now = None

    if timestamp:
        try:
            now = datetime.fromisoformat(
                str(timestamp).replace(
                    "Z",
                    "+00:00",
                )
            )
        except ValueError:
            now = None

    if now is None:
        now = datetime.now()
        timestamp = timestamp or now.isoformat()

    contract = ContextContract(
        user_input="",
        runtime_mode="SERVICE",
        service_model_uid=settings.SERVICE_MODEL_UID,
        timestamp=str(timestamp),
        current_date=str(
            current_date
            or now.date().isoformat()
        ),
        current_time=str(
            current_time
            or now.strftime("%H:%M:%S")
        ),
        weekday=str(
            weekday
            or now.strftime("%A")
        ),
        year=int(
            year
            or now.year
        ),
        turn_number=turn_number,
        user_message_count=user_message_count,
        assistant_message_count=assistant_message_count,
    )

    return contract.to_runtime_xml()


def build_runtime_summarizer_user_prompt(
        *,
        context=None,
        prompt: str,
) -> str:

    return "\n\n".join([
        build_runtime_summarizer_trusted_context(
            context,
        ),
        prompt,
    ])


def infer_memory_failure_reason(
        error: Exception,
) -> str:

    response = getattr(
        error,
        "response",
        None,
    )
    status_code = getattr(
        response,
        "status_code",
        None,
    )
    response_text = (
        getattr(
            response,
            "text",
            "",
        )
        or ""
    ).strip()

    searchable_text = (
        f"{error}\n{response_text}"
    ).lower()

    token_markers = (
        "token",
        "context length",
        "context window",
        "maximum context",
        "max_tokens",
        "too many tokens",
        "prompt is too long",
    )

    if any(
        marker in searchable_text
        for marker in token_markers
    ):
        return (
            "Token/context limit exceeded or max_tokens is too large "
            "for the remaining context."
        )

    if status_code == 400:
        if response_text:
            return (
                "Provider rejected the memory summarizer request "
                "(400 Bad Request); see provider message below."
            )

        return (
            "Provider rejected the memory summarizer request "
            "(400 Bad Request) without an error body; exact cause is unknown. "
            "Common causes are token/context limit mismatch or an invalid payload."
        )

    if status_code:
        return (
            "Provider rejected the memory summarizer request "
            f"with HTTP {status_code}."
        )

    error_text = str(
        error
    ).strip()

    if error_text:
        return error_text

    return (
        "Memory summarizer failed before returning a result."
    )


def build_memory_failure_details(
        *,
        stage: str,
        error: Exception,
        traceback_text: str,
) -> str:

    request = getattr(
        error,
        "request",
        None,
    )
    request_url = str(
        getattr(
            request,
            "url",
            "",
        )
        or config.SERVICE_API_BASE
    )

    return (
        "Likely reason: "
        f"{infer_memory_failure_reason(error)}"
        "\n\nClient error details:\n"
        f"{format_client_error(stage, request_url, config.SERVICE_MODEL_UID, error)}"
        "\n\nTraceback:\n"
        f"{traceback_text}"
    )

def change_ratio(
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
        return 0.0

    if not previous or not current:
        return 1.0

    similarity = SequenceMatcher(
        None,
        previous.lower(),
        current.lower(),
    ).ratio()

    return round(
        1.0 - similarity,
        3,
        )

async def safe_call(
        call,
        *args,
        **kwargs,
):

    if call is None:
        return

    with contextlib.suppress(Exception):
        await call(
            *args,
            **kwargs,
        )


def get_memory_log_level(
        label: str,
) -> str:

    return (
        label
        .split(
            " ",
            1,
        )[0]
        .upper()
    )


async def log_memory_event(
        context,
        *,
        level: str,
        message: str,
        details: str | None = None,
        fallback_channel: str = "runtime",
        event: str | None = None,
) -> None:

    logger = getattr(
        context,
        "logger",
        None,
    )

    log_memory = getattr(
        logger,
        "log_memory",
        None,
    )

    if log_memory is not None:
        await safe_call(
            log_memory,
            level,
            message,
            details=details,
            event=event,
        )
        return

    fallback = getattr(
        logger,
        f"log_{fallback_channel}",
        None,
    )
    formatted_message = (
        f"[MEMORY:{level}] {message}"
    )

    if (
            details is not None
            and fallback_channel in {
                "error",
                "summarizer",
            }
    ):
        await safe_call(
            fallback,
            formatted_message,
            details=details,
        )
        return

    await safe_call(
        fallback,
        formatted_message,
    )


async def log_active_memory_event(
        context,
        *,
        message: str,
        details: str | None = None,
        fallback_channel: str = "runtime",
        event: str | None = None,
) -> None:

    logger = getattr(
        context,
        "logger",
        None,
    )

    log_active_memory = getattr(
        logger,
        "log_active_memory",
        None,
    )

    if log_active_memory is not None:
        await safe_call(
            log_active_memory,
            message,
            details=details,
            event=event,
        )
        return

    fallback = getattr(
        logger,
        f"log_{fallback_channel}",
        None,
    )
    formatted_message = (
        f"[ACTIVE_MEMORY] {message}"
    )

    if details is not None:
        await safe_call(
            fallback,
            formatted_message,
            details=details,
        )
        return

    await safe_call(
        fallback,
        formatted_message,
    )

def extract_runtime_memory_text(
        response: dict,
        *,
        allow_reasoning_fallback: bool = True,
) -> str:

    text = ResponseExtractor.extract_content_text(
        response
    )

    if (
            not text
            and allow_reasoning_fallback
    ):
        text = ResponseExtractor.extract_reasoning_text(
            response
        )

    return text.strip()


def is_runtime_memory_response_truncated(
        response: dict,
) -> bool:

    finish_reason = (
        ResponseExtractor
        .extract_finish_reason(
            response
        )
        .lower()
    )

    return finish_reason in (
        "length",
        "max_tokens",
    )


def looks_like_incomplete_runtime_memory(
        text: str,
) -> bool:

    stripped = (
            text
            or ""
    ).strip()

    if not stripped:
        return True

    if stripped[-1] in (
            ",",
            ":",
            "(",
            "[",
            "{",
    ):
        return True

    pairs = (
        (
            "(",
            ")",
        ),
        (
            "[",
            "]",
        ),
        (
            "{",
            "}",
        ),
    )

    return any(
        stripped.count(open_char)
        > stripped.count(close_char)
        for open_char, close_char
        in pairs
    )


async def refresh_runtime_memory_summarizer_usage(
        context,
        *,
        system_prompt: str,
        user_prompt: str,
        response: dict | None = None,
        context_window: int | None = None,
) -> None:

    if context is None:
        return

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    if getattr(
        emitter,
        "emit",
        None,
    ) is None:
        return

    usage = (
        ResponseExtractor.extract_usage(
            response
        )
        if isinstance(
            response,
            dict,
        )
        else None
    )

    if (
            response is not None
            and not usage
    ):
        return

    context_tokens = (
        usage.get(
            "prompt_tokens",
            0,
        )
        if usage
        else estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=user_prompt,
        )
    )

    total_tokens = (
        usage.get(
            "total_tokens",
            0,
        )
        if usage
        else context_tokens
    )

    if not context_tokens:
        return

    await refresh_runtime_state(
        context,
        runtime_id=(
            RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID
        ),
        used_tokens=(
            total_tokens
            or context_tokens
        ),
        context_tokens=context_tokens,
        total_tokens=(
            total_tokens
            or context_tokens
        ),
        max_tokens=(
            context_window
            or config.SERVICE_CONTEXT_WINDOW
        ),
        last_error=None,
        status="online",
    )


def coerce_positive_int(
        value,
) -> int:

    try:
        number = int(
            value
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0

    return max(
        0,
        number,
    )


def runtime_usage_is_context_overloaded(
        runtime: dict | None,
) -> bool:

    if not isinstance(
            runtime,
            dict,
    ):
        return False

    max_tokens = coerce_positive_int(
        runtime.get(
            "max_tokens"
        )
    )

    if not max_tokens:
        return False

    used_tokens = max(
        coerce_positive_int(
            runtime.get(
                "context_tokens"
            )
        ),
        coerce_positive_int(
            runtime.get(
                "total_tokens"
            )
        ),
        coerce_positive_int(
            runtime.get(
                "used_tokens"
            )
        ),
    )

    return used_tokens > max_tokens


def latest_turn_context_is_overloaded(
        context,
) -> bool:

    explicit_value = getattr(
        context,
        "runtime_last_turn_context_overloaded",
        None,
    )

    if explicit_value is not None:
        return bool(
            explicit_value
        )

    runtime_id = (
        config.SERVICE_MODEL_UID
        if config.USE_SERVICE_AS_BRAIN
        else config.BRAIN_MODEL_UID
    )

    runtime = (
        runtime_state
        .get_all_runtime_states()
        .get(
            runtime_id
        )
    )

    return runtime_usage_is_context_overloaded(
        runtime
    )


def runtime_prompt_is_context_overloaded(
        *,
        system_prompt: str,
        user_prompt: str,
        context_window: int | None,
) -> bool:

    resolved_context_window = coerce_positive_int(
        context_window
    )

    if not resolved_context_window:
        return False

    prompt_tokens = estimate_runtime_tokens(
        system_prompt=system_prompt,
        user_input=user_prompt,
    )

    return prompt_tokens > resolved_context_window


def build_runtime_summarizer_payload(
        *,
        service_client,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
) -> dict:

    return {
        "model": getattr(
            service_client,
            "model_uid",
            "<service>",
        ),
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }


async def log_runtime_summarizer_payload(
        context,
        *,
        label: str,
        payload: dict,
) -> None:

    await log_memory_event(
        context,
        level=get_memory_log_level(
            label
        ),
        message=f"{label} summarizer request",
        details=json.dumps(
            payload,
            ensure_ascii=False,
            indent=2,
        ),
        fallback_channel="summarizer",
        event="summarizer_request",
    )


async def log_runtime_summarizer_result(
        context,
        *,
        label: str,
        result: str,
) -> None:

    await log_memory_event(
        context,
        level=get_memory_log_level(
            label
        ),
        message=f"{label} summarizer result",
        details=(
            result.strip()
            or "<empty>"
        ),
        fallback_channel="summarizer",
        event="summarizer_result",
    )

def build_runtime_summarizer_response_details(
        response: dict,
        *,
        extracted_memory: str = "",
        allow_reasoning_fallback: bool = False,
) -> str:

    content = ResponseExtractor.extract_content_text(
        response
    )
    reasoning = ResponseExtractor.extract_reasoning_text(
        response
    )
    message = ResponseExtractor.extract_message(
        response
    )
    choice = ResponseExtractor.extract_choice(
        response
    )
    usage = response.get(
        "usage",
        {},
    )

    if not isinstance(
            usage,
            dict,
    ):
        usage = {}

    payload = {
        "kind": "summarizer_response",
        "model": ResponseExtractor.extract_model(
            response
        ),
        "finish_reason": ResponseExtractor.extract_finish_reason(
            response
        ),
        "content": content,
        "reasoning_content": reasoning,
        "extracted_memory": extracted_memory,
        "allow_reasoning_fallback": allow_reasoning_fallback,
        "used_reasoning_fallback": (
            bool(reasoning)
            and not bool(content)
            and allow_reasoning_fallback
        ),
        "usage": usage,
        "message": message,
        "choice_index": choice.get(
            "index",
            0,
        ),
    }

    return json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    )


def build_memory_update_skip_details(
        *,
        reason: str,
        previous_memory: str,
        candidate_memory: str,
        summarizer_response_details: str = "",
) -> str:

    sections = [
        f"Likely reason: {reason}",
        "",
        "Previous memory:",
        "----------------",
        previous_memory.strip() or DEFAULT_RUNTIME_MEMORY,
        "",
        "Candidate memory:",
        "-----------------",
        candidate_memory.strip() or "<empty>",
    ]

    response_details = (
        str(summarizer_response_details or "").strip()
    )

    if response_details:
        sections.extend([
            "",
            "Summarizer response details:",
            "----------------------------",
            response_details,
        ])

    return "\n".join(sections)
