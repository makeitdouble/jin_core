import asyncio
import contextlib

from clients.service_client import (
    ask_service_model,
)
from settings.config_loader import (
    config,
)
from utils.response_extractor import (
    ResponseExtractor,
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


def build_runtime_memory_system_prompt() -> str:

    return (
        "You are JIN's runtime memory summarizer.\n"
        "Return only the new compressed memory state as plain text.\n"
        "Do not output JSON.\n"
        "Do not use Markdown headings.\n"
        "Do not explain your reasoning or the summarization process.\n"
        "Preserve still-relevant existing memory. Update it instead of replacing it blindly.\n"
        "Drop old details only when they are clearly obsolete, duplicated, or no longer useful.\n"
        "Decide the summary depth from the signal in the latest turn.\n"
        "Use shallow summarization for simple factual, isolated, or low-signal turns: "
        "keep only the dry fact, topic, or unresolved reference that could help "
        "the next answer.\n"
        "Use deep summarization for turns that reveal user intent, project direction, "
        "preferences, recurring patterns, decisions, emotional tone, or a meaningful "
        "shift in the conversation trajectory.\n"
        "If the user asks a follow-up that depends on prior context, preserve the "
        "referent clearly enough for the next brain prompt to resolve it.\n"
        "If the user switches topic, keep the new topic without forcing it into the "
        "previous one; only note a pattern if the sequence itself is meaningful.\n"
        "Do not infer stable user traits from a single turn.\n"
        "Do not over-interpret jokes, tests, or casual topic changes.\n"
        "Prefer compact continuity over transcript-like detail.\n"
        "Remove noise, implementation chatter, and one-off details unless they change "
        "what JIN should understand next.\n"
        "Keep the memory under 1200 characters unless the latest turn is highly important.\n"
        "The final memory should feel like live state, not chat history.\n"
    )


def build_runtime_memory_user_prompt(
    *,
    current_memory: str,
    user_message: str,
    assistant_message: str,
) -> str:

    return (
        "Current runtime memory:\n"
        f"{current_memory.strip() or 'User and JIN just started interacting.'}\n\n"
        "Latest user message:\n"
        f"{user_message.strip()}\n\n"
        "Latest JIN answer:\n"
        f"{assistant_message.strip()}\n\n"
        "Rewrite the runtime memory now."
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
        response = await ask_service_model(
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
                min(
                    config.SERVICE_MAX_TOKENS,
                    512,
                )
            ),
        )

        updated_memory = extract_runtime_memory_text(
            response
        )

        if updated_memory:
            context.runtime_memory = updated_memory
            context.runtime_memory_updates = (
                getattr(
                    context,
                    "runtime_memory_updates",
                    0,
                )
                + 1
            )

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

        return getattr(
            context,
            "runtime_memory",
            "",
        )

    except asyncio.CancelledError:
        raise

    except Exception as error:
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
            details=str(
                error
            ),
        )

        return getattr(
            context,
            "runtime_memory",
            "",
        )


def schedule_runtime_memory_update(
    *,
    context,
    user_message: str,
    assistant_message: str,
) -> asyncio.Task | None:

    if not assistant_message.strip():
        return None

    task = asyncio.create_task(
        summarize_runtime_memory(
            context=context,
            user_message=user_message,
            assistant_message=assistant_message,
        )
    )

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
