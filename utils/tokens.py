from settings.app_settings import settings

def estimate_tokens(
    text: str,
) -> int:

    if not text:
        return 1

    return len(
        text.split()
    )


def estimate_optional_tokens(
    text: str,
) -> int:

    if not text:
        return 0

    return estimate_tokens(
        text
    )


def estimate_stream_tokens(
    stream,
    *,
    prompt_text: str = "",
) -> int:

    visible_tokens = (
        estimate_optional_tokens(
            getattr(
                stream,
                "response",
                "",
            )
        )
        + estimate_optional_tokens(
            getattr(
                stream,
                "reasoning",
                "",
            )
        )
    )

    prompt_tokens = (
        getattr(
            stream,
            "prompt_tokens",
            0,
        )
        or estimate_optional_tokens(
            prompt_text
        )
    )

    provider_total = (
        getattr(
            stream,
            "total_tokens",
            0,
        )
        or 0
    )

    return max(
        provider_total,
        prompt_tokens + visible_tokens,
        visible_tokens,
    )


def translation_token_limit(
    text: str,
) -> int:

    estimated_tokens = max(
        settings.TRANSLATION_MIN_TOKENS,
        estimate_tokens(text),
    )

    return min(
        settings.TRANSLATION_MAX_TOKENS,
        estimated_tokens,
    )


def estimate_runtime_tokens(
    *,
    user_input: str = "",
    system_prompt: str = "",
    context_payload: str = "",
    response: str = "",
    reasoning: str = "",
) -> int:

    total_text = (
        user_input
        + system_prompt
        + context_payload
        + response
        + reasoning
    )

    return estimate_tokens(
        total_text
    )
