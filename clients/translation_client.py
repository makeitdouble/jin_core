import config

from clients.model_client import (
    ask_model,
)

from utils.errors import (
    format_client_error,
)

from utils.tokens import (
    translation_token_limit,
)


def build_translation_system_prompt(
    source_language: str,
    target_language: str,
) -> str:

    return (
        f"Strict translator "
        f"from {source_language} "
        f"to {target_language}. "
        f"Preserve {target_language} "
        "tokens exactly. "
        "Preserve original punctuation, "
        "casing, spacing, slang, typos. "
        "Output only translation."
    )


async def translate(
    *,
    text: str,
    source_language: str,
    target_language: str,
    stage: str,
) -> str:

    try:

        return await ask_model(
            api_base=(
                config.TRANSLATOR_API_BASE
            ),
            model_uid=(
                config.TRANSLATOR_MODEL_UID
            ),
            user_prompt=(
                f"<input>{text}</input>"
            ),
            system_prompt=(
                build_translation_system_prompt(
                    source_language,
                    target_language,
                )
            ),
            timeout=(
                config
                .TRANSLATOR_REQUEST_TIMEOUT
            ),
            temperature=(
                config
                .TRANSLATION_TEMPERATURE
            ),
            max_tokens=(
                translation_token_limit(
                    text
                )
            ),
        )

    except Exception as error:

        formatted_error = (
            format_client_error(
                stage,
                config.TRANSLATOR_API_BASE,
                config.TRANSLATOR_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )


async def translate_ru_to_en(
    text: str,
) -> str:

    return await translate(
        text=text,
        source_language="Russian",
        target_language="English",
        stage="translate_ru_to_en",
    )


async def translate_en_to_ru(
    text: str,
) -> str:

    return await translate(
        text=text,
        source_language="English",
        target_language="Russian",
        stage="translate_en_to_ru",
    )
