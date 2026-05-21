import config


def estimate_tokens(
    text: str,
) -> int:

    if not text:
        return 1

    return len(
        text.split()
    )


def translation_token_limit(
    text: str,
) -> int:

    estimated_tokens = max(
        config.TRANSLATION_MIN_TOKENS,
        estimate_tokens(text),
    )

    return min(
        config.TRANSLATION_MAX_TOKENS,
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
