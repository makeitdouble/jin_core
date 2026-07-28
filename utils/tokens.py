from math import ceil

from app_settings import settings


def estimate_tokens(
        text: str,
) -> int:
    if not text:
        return 1

    word_estimate = len(
        text.split()
    )
    char_estimate = ceil(
        len(text) / 4
    )

    if word_estimate <= 1:
        return max(
            1,
            char_estimate,
        )

    return max(
        1,
        min(
            word_estimate,
            char_estimate,
        ),
    )


def estimate_optional_tokens(
        text: str,
) -> int:
    if not text:
        return 0

    return estimate_tokens(
        text
    )


def apply_token_estimate_scale(
        token_count: int,
        scale: float = 1.0,
) -> int:

    if token_count <= 0:
        return 0

    try:
        normalized_scale = float(
            scale
        )
    except (
        TypeError,
        ValueError,
    ):
        normalized_scale = 1.0

    normalized_scale = max(
        1.0,
        normalized_scale,
    )

    return max(
        1,
        ceil(
            token_count
            * normalized_scale
        ),
    )


def estimate_stream_text_tokens(
        text: str,
        *,
        scale: float = 1.0,
) -> int:

    if not text:
        return 0

    word_estimate = len(
        text.split()
    )
    char_estimate = ceil(
        len(
            text.encode(
                "utf-8"
            )
        ) / 4
    )

    raw_estimate = max(
        1,
        word_estimate,
        char_estimate,
    )

    return apply_token_estimate_scale(
        raw_estimate,
        scale,
    )


def estimate_stream_input_tokens(
        stream,
        *,
        prompt_text: str = "",
        scale: float = 1.0,
) -> int:
    return estimate_stream_text_tokens(
        prompt_text,
        scale=scale,
    )


def estimate_stream_live_tokens(
        stream,
        *,
        prompt_text: str = "",
        scale: float = 1.0,
) -> int:
    return estimate_stream_input_tokens(
        stream,
        prompt_text=prompt_text,
        scale=scale,
    ) + estimate_stream_text_tokens(
        getattr(
            stream,
            "response",
            "",
        ),
        scale=scale,
    ) + estimate_stream_text_tokens(
        getattr(
            stream,
            "reasoning",
            "",
        ),
        scale=scale,
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
    total_text = "\n".join(
        value
        for value in (
            user_input,
            system_prompt,
            context_payload,
            response,
            reasoning,
        )
        if value
    )

    return estimate_tokens(
        total_text
    )
