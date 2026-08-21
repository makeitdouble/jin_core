import re
from dataclasses import dataclass

from utils.token_usage import (
    get_runtime_token_estimate_scale,
)
from utils.tokens import (
    estimate_stream_input_tokens,
)


CURRENT_CONTEXT_WINDOW_TAG = "CURRENT_CONTEXT_WINDOW"
CURRENT_CONTEXT_WINDOW_PLACEHOLDER = "__JIN_CURRENT_CONTEXT_WINDOW__"

CURRENT_CONTEXT_WINDOW_RE = re.compile(
    (
        r"(?P<indent>[ \t]*)"
        r"<CURRENT_CONTEXT_WINDOW>"
        r".*?"
        r"</CURRENT_CONTEXT_WINDOW>"
    ),
    re.DOTALL,
)


@dataclass(frozen=True)
class CurrentContextWindowPrompt:
    system_prompt: str
    used_tokens: int
    context_window: int
    value: str


def _as_int(
    value,
) -> int:

    try:
        return int(
            value or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0


def text_from_user_prompt(
    user_prompt,
) -> str:

    if isinstance(
        user_prompt,
        str,
    ):
        return user_prompt

    if isinstance(
        user_prompt,
        list,
    ):
        text_parts = []

        for item in user_prompt:
            if not isinstance(
                item,
                dict,
            ):
                continue

            if item.get(
                "type",
            ) != "text":
                continue

            text_parts.append(
                str(
                    item.get(
                        "text",
                        "",
                    )
                )
            )

        return "\n".join(
            text_parts
        )

    return str(
        user_prompt
        or ""
    )


def provider_counted_user_prompt_text(
    context,
    user_prompt,
) -> str:

    text = text_from_user_prompt(
        user_prompt
    )

    if (
        text == ""
        and bool(
            getattr(
                context,
                "runtime_followup_tick_active",
                False,
            )
        )
    ):
        return " "

    return text


def format_current_context_window_value(
    *,
    used_tokens: int,
    context_window: int,
) -> str:

    used_tokens = max(
        0,
        _as_int(
            used_tokens
        ),
    )
    context_window = _as_int(
        context_window
    )

    if context_window > 0:
        return f"{used_tokens}/{context_window} occupied"

    return f"{used_tokens}/unknown occupied"


def _format_field(
    value: str,
    *,
    indent: str = "    ",
) -> str:

    return (
        f"{indent}<CURRENT_CONTEXT_WINDOW>"
        f"{value}"
        "</CURRENT_CONTEXT_WINDOW>"
    )


def ensure_current_context_window_field(
    system_prompt: str,
    value: str = CURRENT_CONTEXT_WINDOW_PLACEHOLDER,
) -> str:

    prompt = str(
        system_prompt
        or ""
    )

    if CURRENT_CONTEXT_WINDOW_RE.search(
        prompt
    ):
        return CURRENT_CONTEXT_WINDOW_RE.sub(
            lambda match: _format_field(
                value,
                indent=match.group(
                    "indent"
                ),
            ),
            prompt,
            count=1,
        )

    close_tag = "</CURRENT_TRUSTED_RUNTIME_VARIABLES>"
    if close_tag not in prompt:
        return prompt

    for tag in (
        "BRAIN_MODEL_UID",
        "SERVICE_MODEL_UID",
        "CURRENT_SESSION_ID",
    ):
        match = re.search(
            (
                r"(?P<indent>[ \t]*)"
                rf"<{tag}>"
                r".*?"
                rf"</{tag}>"
            ),
            prompt,
            flags=re.DOTALL,
        )

        if not match:
            continue

        return (
            prompt[:match.end()]
            + "\n"
            + _format_field(
                value,
                indent=match.group(
                    "indent"
                ),
            )
            + prompt[match.end():]
        )

    return prompt.replace(
        close_tag,
        (
            _format_field(
                value,
            )
            + "\n"
            + close_tag
        ),
        1,
    )


def estimate_current_context_tokens(
    *,
    context,
    runtime_id: str,
    system_prompt: str,
    user_prompt,
) -> int:

    prompt_text = "\n".join(
        value
        for value in (
            str(
                system_prompt
                or ""
            ),
            provider_counted_user_prompt_text(
                context,
                user_prompt,
            ),
        )
        if value
    )

    return estimate_stream_input_tokens(
        None,
        prompt_text=prompt_text,
        scale=get_runtime_token_estimate_scale(
            context,
            runtime_id,
        ),
    )


def annotate_current_context_window(
    *,
    context,
    runtime_id: str,
    system_prompt: str,
    user_prompt,
    context_window: int,
) -> CurrentContextWindowPrompt:

    prompt = ensure_current_context_window_field(
        system_prompt,
        CURRENT_CONTEXT_WINDOW_PLACEHOLDER,
    )
    value = CURRENT_CONTEXT_WINDOW_PLACEHOLDER
    used_tokens = 0

    for _ in range(6):
        used_tokens = estimate_current_context_tokens(
            context=context,
            runtime_id=runtime_id,
            system_prompt=prompt,
            user_prompt=user_prompt,
        )
        next_value = format_current_context_window_value(
            used_tokens=used_tokens,
            context_window=context_window,
        )

        if next_value == value:
            break

        value = next_value
        prompt = ensure_current_context_window_field(
            prompt,
            value,
        )

    used_tokens = estimate_current_context_tokens(
        context=context,
        runtime_id=runtime_id,
        system_prompt=prompt,
        user_prompt=user_prompt,
    )
    final_value = format_current_context_window_value(
        used_tokens=used_tokens,
        context_window=context_window,
    )

    if final_value != value:
        value = final_value
        prompt = ensure_current_context_window_field(
            prompt,
            value,
        )
        used_tokens = estimate_current_context_tokens(
            context=context,
            runtime_id=runtime_id,
            system_prompt=prompt,
            user_prompt=user_prompt,
        )

    return CurrentContextWindowPrompt(
        system_prompt=prompt,
        used_tokens=used_tokens,
        context_window=_as_int(
            context_window
        ),
        value=value,
    )


def remember_current_context_window(
    context,
    *,
    runtime_id: str,
    prepared: CurrentContextWindowPrompt,
) -> None:

    if context is None:
        return

    value = {
        "runtime_id": runtime_id,
        "used_tokens": prepared.used_tokens,
        "context_window": prepared.context_window,
        "value": prepared.value,
    }

    context.runtime_current_context_window = value
    context.runtime_current_context_window_text = prepared.value


async def resolve_current_context_window(
    client,
    *,
    fallback_context_window: int = 0,
    force_refresh: bool = False,
) -> int:

    resolver = getattr(
        client,
        "resolve_request_context_window",
        None,
    )

    if resolver is not None:
        try:
            resolved = await resolver(
                force_refresh=force_refresh
            )
        except TypeError:
            resolved = await resolver()
        except Exception:
            resolved = None

        resolved_context_window = _as_int(
            resolved
        )
        if resolved_context_window > 0:
            return resolved_context_window

    return max(
        0,
        _as_int(
            fallback_context_window
        ),
    )


async def prepare_current_context_window_prompt(
    *,
    client,
    context,
    runtime_id: str,
    system_prompt: str,
    user_prompt,
    fallback_context_window: int = 0,
    force_refresh: bool = False,
) -> CurrentContextWindowPrompt:

    context_window = await resolve_current_context_window(
        client,
        fallback_context_window=fallback_context_window,
        force_refresh=force_refresh,
    )
    prepared = annotate_current_context_window(
        context=context,
        runtime_id=runtime_id,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        context_window=context_window,
    )
    remember_current_context_window(
        context,
        runtime_id=runtime_id,
        prepared=prepared,
    )

    return prepared
