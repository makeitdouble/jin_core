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


def estimate_stream_input_tokens(
        stream,
        *,
        prompt_text: str = "",
) -> int:
    return estimate_optional_tokens(
        prompt_text
    )


def estimate_stream_live_tokens(
        stream,
        *,
        prompt_text: str = "",
) -> int:
    return estimate_stream_input_tokens(stream, prompt_text=prompt_text, ) + estimate_optional_tokens(
        getattr(stream, "response", "", )) + estimate_optional_tokens(getattr(stream, "reasoning", "", ))


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
