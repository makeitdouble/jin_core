import asyncio
import contextlib
import json
import traceback
from datetime import datetime
from difflib import SequenceMatcher

from clients.errors import (
    format_client_error,
)
from clients.service_client import (
    ask_service_model,
)
from runtime.state import (
    RUNTIME_MEMORY_SUMMARIZER_RUNTIME_ID,
)
from config_loader import (
    config,
)
from clients.response_extractor import (
    ResponseExtractor,
)
from runtime.state_sync import (
    refresh_runtime_state,
)
from runtime.context_contract import (
    ContextContract,
)
from utils.tokens import (
    estimate_runtime_tokens,
)
from runtime.memory_rules import (
    DEFAULT_RUNTIME_MEMORY,
    build_interrupted_assistant_message,
    build_runtime_memory_context_text,
    build_runtime_l2_memory_system_prompt,
    build_runtime_l2_memory_user_prompt,
    build_runtime_memory_batch_user_prompt,
    build_runtime_memory_system_prompt,
    build_runtime_memory_user_prompt,
    build_runtime_session_memory_system_prompt,
    build_runtime_session_memory_user_prompt,
    canonicalize_runtime_memory_entry,
)
from runtime.fact_check import (
    ensure_confirmable_memory_markers,
)




RUNTIME_RESPONSE_FEEDBACK_KEY = "JIN_LAST_RESPONSE_USER_FEEDBACK"
RUNTIME_RESPONSE_FEEDBACK_DISLIKED_VALUE = (
    "User disliked your last response. "
    "Before answering, find and understand why it failed using context or memory, then start the next reply with a brief acknowledgement of that miss, then continue with a concrete corrected answer."
)
RUNTIME_RESPONSE_FEEDBACK_NEUTRAL_VALUE = (
    "User gave neutral feedback to your last response. "
    "Continue carefully without changing course too much and treat it as a signal for response improvement."
)
RUNTIME_RESPONSE_FEEDBACK_LIKED_VALUE = (
    "User liked your last response. "
    "Keep the current direction."
)
RUNTIME_RESPONSE_FEEDBACK_RATINGS = {
    "disliked": "disliked",
    "neutral": "neutral",
    "liked": "liked",
}


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

    context.runtime_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )

    context.runtime_memory_stable = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory_stable",
            "",
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

DEFAULT_RUNTIME_L2_MEMORY = ""
DEFAULT_RUNTIME_L3_SESSION_MEMORY = ""
L3_INPUT_TOKEN_TARGET_MAX = 6000
L3_INPUT_TOKEN_RESERVE = 768
L3_OUTPUT_MAX_TOKENS = 2048
MIN_L2_TURNS = 3
L2_PATCH_WINDOW = 5
L2_REPEATED_KEY_THRESHOLD = 3
STRENGTH_DECAY = 0.82
STRENGTH_PRESENCE_BOOST = 0.08
STRENGTH_BOOST = 0.8
STRENGTH_NEW_KEY = 0.5
DURABLE_FLOOR = 0.25
HOT_THRESHOLD = 0.5
FADING_THRESHOLD = 0.1
GENERIC_MEMORY_VALUE_SIMILARITY_MIN = 0.35
GENERIC_MEMORY_MATCH_KEYS = (
    "topic",
    "focus",
    "next step",
    "last jin response",

    "user request",
    "user intent",

    "active topic",
    "active topics",
    "current topic",
    "current topics",

    "open reference",
    "open references",
    "open question",

    "pending choice",
    "pending choices",
    "pending action",
    "pending actions",

    "session status",
    "session state",

    "current concern",
    "current concerns",
    "current task",
    "current tasks",
    "current context",
    "current request",
    "current requests",

    "interaction state",
)
DURABLE_MEMORY_KEY_TOKENS = (
    "fact",
    "identity",
    "profile",
    "preference",
    "stored",
)
DURABLE_MEMORY_NEGATION_MARKERS = (
    "not",
    "not fact",
    "not true",
    "false",
    "obsolete",
    "removed",
    "cancelled",
    "canceled",
    "superseded",
    "no longer",
    "invalid",
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
    )

    return contract.to_runtime_xml()


def build_runtime_summarizer_user_prompt(
        *,
        context=None,
        prompt: str,
) -> str:

    return "\n\n".join([
        build_runtime_summarizer_trusted_context(
            context
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


async def emit_runtime_memory_update(
        context,
) -> dict:

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    memory = getattr(context, "runtime_memory", "")
    display_memory = build_runtime_memory_context_text(
        memory,
        context,
    )

    if not hasattr(
        context,
        "runtime_memory_snapshots",
    ):
        context.runtime_memory_snapshots = []

    snapshot = build_runtime_memory_snapshot(context, memory)

    context.runtime_memory_snapshots.append(snapshot)
    context.runtime_memory_snapshot_index = snapshot["index"]

    emit = getattr(
        emitter,
        "emit",
        None,
    )

    await safe_call(
        emit,
        {
            "type": "runtime_memory_update",
            "memory": display_memory,
            "updates": getattr(context, "runtime_memory_updates", 0),
            "snapshot": snapshot,
            "snapshots_count": len(context.runtime_memory_snapshots),
            "snapshot_index": context.runtime_memory_snapshot_index,
        },
    )

    return snapshot


def build_runtime_l1_diff_stats(
        diff_history: list[dict],
) -> dict:

    values = [
        item.get(
            "total_diff",
            0,
        )
        for item in diff_history
    ]

    return {
        "count": len(values),
        "average": average_diff(values),
        "range": diff_value_range(values),
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
    }


async def emit_runtime_l1_diff_update(
        context,
) -> None:

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

    history = list(
        getattr(
            context,
            "runtime_l1_diff_history",
            [],
        )
        or []
    )

    snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )
    latest_lines = (
        snapshots[-1].get("lines", [])
        if snapshots
        else []
    )

    await safe_call(
        emit,
        {
            "type": "runtime_l1_diff_update",
            "diffs": history,
            "stats": build_runtime_l1_diff_stats(
                history
            ),
            "strength_map": build_strength_map(
                latest_lines
            ),
            "strength_zones": get_strength_zones(
                latest_lines
            ),
        },
    )


async def emit_runtime_session_memory_update(
        context,
        *,
        persist_browser: bool = False,
) -> None:

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

    memory = getattr(
        context,
        "runtime_l3_session_memory",
        "",
    ) or getattr(
        context,
        "session_memory",
        "",
    )
    event_snapshots = list(
        getattr(
            context,
            "runtime_session_event_snapshots",
            [],
        )
        or []
    )

    await safe_call(
        emit,
        {
            "type": "runtime_session_memory_update",
            "memory": memory,
            "event_snapshots": event_snapshots,
            "updates": getattr(
                context,
                "runtime_session_memory_updates",
                0,
            ),
            "source": getattr(
                context,
                "session_memory_source",
                "",
            ),
            "persist": persist_browser,
        },
    )


async def emit_runtime_action_completed(
        context,
        *,
        action: str,
) -> None:

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

    await safe_call(
        emit,
        {
            "type": "runtime_action",
            "action": action,
            "status": "completed",
        },
    )


def extract_runtime_memory_text(
        response: dict,
) -> str:

    text = (
            ResponseExtractor.extract_content_text(
                response
            )
            or ResponseExtractor.extract_reasoning_text(
        response
    )
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


async def ask_runtime_memory_model(
        *,
        context=None,
        service_client,
        current_memory: str,
        user_message: str,
        assistant_message: str,
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
            build_runtime_memory_user_prompt(
                current_memory=current_memory,
                user_message=user_message,
                assistant_message=assistant_message,
                current_l2_memory=getattr(
                    context,
                    "runtime_l2_memory",
                    "",
                ),
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
                current_l2_memory=getattr(
                    context,
                    "runtime_l2_memory",
                    "",
                ),
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


async def record_runtime_l1_diff(
        context,
        snapshot: dict,
        turns: list[dict] | None = None,
) -> None:

    ensure_runtime_l2_state(
        context
    )

    total_diff = snapshot.get(
        "total_diff",
        0,
    )
    context.runtime_conversation_activity_diff = total_diff

    observed_turns = list(
        turns
        or []
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
        "changes": snapshot.get(
            "patch",
            {},
        ),
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

    context.runtime_memory = current_memory
    context.runtime_memory_stable = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory_stable",
            "",
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
        updated_memory = ensure_confirmable_memory_markers(
            updated_memory,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        updated_memory = remove_runtime_response_feedback_text(
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

            await log_memory_event(
                context,
                level="L1",
                message="L1 runtime memory updated",
                fallback_channel="service",
            )

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

    context.runtime_memory = remove_runtime_response_feedback_text(
        getattr(
            context,
            "runtime_memory",
            "",
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

        latest_turn = turns[-1] if turns else {}
        updated_memory = ensure_confirmable_memory_markers(
            updated_memory,
            user_message=latest_turn.get(
                "user_message",
                "",
            ),
            assistant_message=latest_turn.get(
                "assistant_message",
                "",
            ),
        )
        updated_memory = remove_runtime_response_feedback_text(
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

            await log_memory_event(
                context,
                level="L1",
                message="L1 runtime memory updated",
                fallback_channel="service",
            )

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

    if not assistant_message.strip():
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

def build_memory_update_skip_details(
        *,
        reason: str,
        previous_memory: str,
        candidate_memory: str,
) -> str:

    return (
        f"{reason}\n\n"
        "Previous memory:\n"
        "----------------\n"
        f"{previous_memory.strip() or DEFAULT_RUNTIME_MEMORY}\n\n"
        "Candidate memory:\n"
        "-----------------\n"
        f"{candidate_memory.strip() or '<empty>'}"
    )

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
    hot, crystallized, fading = [], [], []
    for line in lines:
        key = line.get("key", "")
        strength = line.get("strength", 0.0)
        durable = is_durable_memory_key(key)
        if strength >= HOT_THRESHOLD:
            hot.append(key)
        elif durable and strength <= DURABLE_FLOOR + 0.05:
            crystallized.append(key)
        elif strength <= FADING_THRESHOLD:
            fading.append(key)
    return {"hot": hot, "crystallized": crystallized, "fading": fading}


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


def collapse_duplicate_runtime_memory_keys(
        memory: str,
) -> str:

    output_entries = []
    grouped_by_key = {}
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

    return "\n".join(
        (
            (
                f'{entry["key"]}: {", ".join(entry["values"])}'
                if entry["key"]
                else ", ".join(entry["values"])
            )
            if isinstance(
                entry,
                dict,
            )
            else entry
        )
        for entry in output_entries
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
            candidate_text
            + "\n"
            + "\n".join(
                preserved_lines
            )
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
