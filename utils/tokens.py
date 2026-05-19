import config

def estimate_tokens(text: str) -> int:

    return max(
        1,
        len(text) // config.TOKEN_ESTIMATION_DIVISOR,
    )

def translation_token_limit(text: str) -> int:

    estimated_tokens = max(
        config.TRANSLATION_MIN_TOKENS,
        estimate_tokens(text) * 2,
    )

    return min(
        config.TRANSLATION_MAX_TOKENS,
        estimated_tokens,
    )
