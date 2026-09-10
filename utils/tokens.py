from math import ceil

from app_settings import settings


# Model-agnostic fallback reservation, not an exact vision tokenizer count.
# Keep encoded bytes/URLs out of text tokenization. Providers may use different
# crop/patch budgets; this reserve cannot guarantee an exact provider count.
DEFAULT_IMAGE_INPUT_TOKEN_RESERVE = 4096


def estimate_prompt_tokens(*, system_prompt: str, user_prompt, scale=1.0) -> int:
    image_count = 0
    if isinstance(user_prompt, list):
        text_parts = []
        for item in user_prompt:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text_parts.append(str(item.get("text", "")))
            elif item.get("type") == "image_url":
                image_count += 1
        user_text = "\n".join(text_parts)
    else:
        user_text = str(user_prompt or "")
    text = "\n".join(value for value in (system_prompt, user_text) if value)
    return apply_token_estimate_scale(
        estimate_stream_text_tokens(text)
        + image_count * DEFAULT_IMAGE_INPUT_TOKEN_RESERVE, scale,
    )


def estimate_tokens(
        text: str,
) -> int:
    if not text:
        return 1

    word_estimate = len(
        text.split()
    )
    byte_estimate = ceil(
        len(
            text.encode(
                "utf-8"
            )
        ) / 4
    )

    return max(
        1,
        word_estimate,
        byte_estimate,
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
        image_tokens: int = 0,
) -> int:
    return estimate_stream_text_tokens(
        prompt_text,
        scale=scale,
    ) + apply_token_estimate_scale(image_tokens, scale)


def estimate_stream_live_tokens(
        stream,
        *,
        prompt_text: str = "",
        scale: float = 1.0,
        image_tokens: int = 0,
) -> int:
    return estimate_stream_input_tokens(
        stream,
        prompt_text=prompt_text,
        image_tokens=image_tokens,
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
