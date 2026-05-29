import asyncio
import contextlib
import traceback

from clients.service_client import (
    ask_service_model,
)
from settings.config_loader import (
    config,
)
from utils.response_extractor import (
    ResponseExtractor,
)


DEFAULT_RUNTIME_MEMORY = (
    "This session has just begun. "
    "You have no history with the user yet."
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


async def emit_runtime_memory_update(
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

    await safe_call(
        emit,
        {
            "type": "runtime_memory_update",
            "memory": getattr(
                context,
                "runtime_memory",
                "",
            ),
            "updates": getattr(
                context,
                "runtime_memory_updates",
                0,
            ),
        },
    )


def build_runtime_memory_system_prompt() -> str:

    return (
        "You are JIN's runtime memory summarizer.\n"
        "Return only the new compressed memory state as plain text.\n"
        "Do not output JSON.\n"
        "Do not use Markdown headings.\n"
        "Do not explain your reasoning or the summarization process.\n"
        "Write memory as atomic bullet lines, one semantic entity per line.\n"
        "Each line should start with a compact semantic label such as topic, "
        "user intents, potential motifs, focus, priority, active topics, open references, pending choices, "
        "offered options, preferences, expectations, current concern, decisions, patterns, failures or interruptions.\n"
        "Avoid writing about JIN's role unless the role itself changed or matters. "
        "Describe assistant actions neutrally instead.\n"
        "Keep memory actionable: write what helps the next answer, not a recap of "
        "what happened.\n"
        "Do not merge unrelated facts into one sentence. Prefer separate lines "
        "over broad phrasing like 'Topic established: X, specifically Y'.\n"
        "Finish every bullet line completely. Never leave a line mid-phrase.\n"
        "Preserve still-relevant existing memory. Update it instead of replacing it blindly.\n"
        "Drop old details only when they are clearly obsolete, duplicated, or no longer useful.\n"
        "Decide the summary depth from the signal in the latest turn.\n"
        "Use shallow summarization for simple factual, isolated, or low-signal turns: "
        "keep one or two bullet lines with only the dry fact, topic, or unresolved "
        "reference that could help the next answer.\n"
        "Use deep summarization for turns that reveal user intent, project direction, "
        "preferences, recurring patterns, decisions, emotional tone, or a meaningful "
        "shift in the conversation trajectory; use three to six bullet lines when "
        "the turn carries that much signal.\n"
        "If the user asks a follow-up that depends on prior context, preserve the "
        "referent clearly enough for the next brain prompt to resolve it.\n"
        "If the user switches topic, keep the new topic without forcing it into the "
        "previous one; only note a pattern if the sequence itself is meaningful.\n"
        "If the assistant response was aborted or incomplete, mark it as incomplete "
        "and do not treat it as resolved.\n"
        "Do not infer stable user traits from a single turn.\n"
        "Do not over-interpret jokes, tests, or casual topic changes.\n"
        "Prefer compact continuity over transcript-like detail.\n"
        "Remove noise, implementation chatter, and one-off details unless they change "
        "what JIN should understand next.\n"
        "The final memory snapshot should feel like current live trusted state.\n"
    )


def build_runtime_memory_user_prompt(
        *,
        current_memory: str,
        user_message: str,
        assistant_message: str,
) -> str:

    return (
        "Current runtime memory:\n"
        f"{current_memory.strip() or DEFAULT_RUNTIME_MEMORY}\n\n"
        "Latest user message:\n"
        f"{user_message.strip()}\n\n"
        "Latest JIN answer:\n"
        f"{assistant_message.strip()}\n\n"
        "Rewrite the runtime memory now as atomic bullet lines."
    )


def build_runtime_memory_batch_user_prompt(
        *,
        current_memory: str,
        turns: list[dict],
) -> str:

    lines = [
        "Current runtime memory:",
        current_memory.strip() or DEFAULT_RUNTIME_MEMORY,
        "",
        "New completed turns since that memory snapshot:",
        ]

    for index, turn in enumerate(
            turns,
            start=1,
    ):
        lines.extend([
            "",
            f"Turn {index}",
            "Latest user message:",
            (
                turn.get(
                    "user_message",
                    "",
                )
                .strip()
            ),
            "",
            "Latest JIN answer:",
            (
                turn.get(
                    "assistant_message",
                    "",
                )
                .strip()
            ),
        ])

    lines.extend([
        "",
        "Rewrite the runtime memory now as atomic bullet lines.",
        "Use the current memory as the last stable snapshot.",
        "Integrate all new completed turns in order.",
    ])

    return "\n".join(
        lines
    )


def build_interrupted_assistant_message(
        *,
        user_message: str,
        assistant_message: str,
) -> str:

    partial_text = assistant_message.strip()

    if not partial_text:
        partial_text = (
            "No complete assistant answer was delivered."
        )

    return (
        "Assistant response was interrupted by the user and is incomplete. "
        "Do not treat this turn as resolved.\n\n"
        "Interrupted user topic/request:\n"
        f"{user_message.strip()}\n\n"
        "Partial assistant text before interruption:\n"
        f"{partial_text}"
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


async def ask_runtime_memory_model(
        *,
        service_client,
        current_memory: str,
        user_message: str,
        assistant_message: str,
) -> dict:

    return await ask_service_model(
        client=service_client,
        system_prompt=(
            build_runtime_memory_system_prompt()
        ),
        user_prompt=(
            build_runtime_memory_user_prompt(
                current_memory=current_memory,
                user_message=user_message,
                assistant_message=assistant_message,
            )
        ),
        temperature=(
            config.SERVICE_TEMPERATURE
        ),
        max_tokens=(
            config.SERVICE_MAX_TOKENS
        ),
    )


async def ask_runtime_memory_batch_model(
        *,
        service_client,
        current_memory: str,
        turns: list[dict],
) -> dict:

    return await ask_service_model(
        client=service_client,
        system_prompt=(
            build_runtime_memory_system_prompt()
        ),
        user_prompt=(
            build_runtime_memory_batch_user_prompt(
                current_memory=current_memory,
                turns=turns,
            )
        ),
        temperature=(
            config.SERVICE_TEMPERATURE
        ),
        max_tokens=(
            config.SERVICE_MAX_TOKENS
        ),
    )


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

    current_memory = getattr(
        context,
        "runtime_memory",
        "",
    )

    try:
        response = await ask_runtime_memory_model(
            service_client=service_client,
            current_memory=current_memory,
            user_message=user_message,
            assistant_message=assistant_message,
        )

        updated_memory = extract_runtime_memory_text(
            response
        )

        if (
                is_runtime_memory_response_truncated(
                    response
                )
                or looks_like_incomplete_runtime_memory(
            updated_memory
        )
        ):
            await safe_call(
                getattr(
                    getattr(
                        context,
                        "logger",
                        None,
                    ),
                    "log_error",
                    None,
                ),
                "[MEMORY] runtime memory update skipped",
                details=(
                    "Summarizer returned an incomplete memory update."
                ),
            )

            return current_memory

        updates_counter = getattr(
            context,
            "runtime_memory_updates",
            0,
        )

        if updated_memory or updates_counter == 0:
            context.runtime_memory = updated_memory
            context.runtime_memory_stable = updated_memory
            context.runtime_memory_updates = updates_counter + 1

            logger = getattr(
                context,
                "logger",
                None,
            )
            log_service = getattr(
                logger,
                "log_service",
                None,
            )

            await safe_call(
                log_service,
                "[MEMORY] runtime memory updated",
            )

            await emit_runtime_memory_update(
                context
            )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        formatted_traceback = (
            traceback.format_exc()
        )

        logger = getattr(
            context,
            "logger",
            None,
        )
        log_error = getattr(
            logger,
            "log_error",
            None,
        )

        await safe_call(
            log_error,
            "[MEMORY] runtime memory update failed",
            details=formatted_traceback,
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

    initial_memory = getattr(
        context,
        "runtime_memory_stable",
        "",
    )

    try:
        response = await ask_runtime_memory_batch_model(
            service_client=service_client,
            current_memory=initial_memory,
            turns=turns,
        )

        updated_memory = extract_runtime_memory_text(
            response
        )

        if (
                is_runtime_memory_response_truncated(
                    response
                )
                or looks_like_incomplete_runtime_memory(
            updated_memory
        )
        ):
            await safe_call(
                getattr(
                    getattr(
                        context,
                        "logger",
                        None,
                    ),
                    "log_error",
                    None,
                ),
                "[MEMORY] runtime memory update skipped",
                details=(
                    "Summarizer returned an incomplete memory update."
                ),
            )

            return initial_memory

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

            logger = getattr(
                context,
                "logger",
                None,
            )
            log_service = getattr(
                logger,
                "log_service",
                None,
            )

            await safe_call(
                log_service,
                "[MEMORY] runtime memory updated",
            )

            await emit_runtime_memory_update(
                context
            )

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    except asyncio.CancelledError:
        raise

    except Exception:
        formatted_traceback = (
            traceback.format_exc()
        )

        logger = getattr(
            context,
            "logger",
            None,
        )
        log_error = getattr(
            logger,
            "log_error",
            None,
        )

        await safe_call(
            log_error,
            "[MEMORY] runtime memory update failed",
            details=formatted_traceback,
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