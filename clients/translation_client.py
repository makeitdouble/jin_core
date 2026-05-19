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
            f"Strict translator from {source_language} to {target_language}. "
            f"Preserve {target_language} tokens exactly. "
            "Preserve original punctuation, casing, spacing, slang, typos."
            "Output only translation."
        )


def build_translation_user_prompt(
    text: str,
    source_language: str,
    target_language: str,
) -> str:

    return (
        f"<input>{text}</input>"
    )


async def ask_translator_model(
    *,
    user_prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:

    return await ask_model(
        api_base=config.TRANSLATOR_API_BASE,
        model_uid=config.TRANSLATOR_MODEL_UID,
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        timeout=config.TRANSLATOR_REQUEST_TIMEOUT,
        temperature=temperature,
        max_tokens=max_tokens,
        validate_model=False,
    )


async def ask_translation_service(
    *,
    text: str,
    source_language: str,
    target_language: str,
    stage: str,
) -> str:

    translation_user_prompt = (
        build_translation_user_prompt(
            text=text,
            source_language=source_language,
            target_language=target_language,
        )
    )

    translation_system_prompt = (
        build_translation_system_prompt(
            source_language=source_language,
            target_language=target_language,
        )
    )

    try:

        return await ask_translator_model(
            user_prompt=translation_user_prompt,
            system_prompt=translation_system_prompt,
            temperature=(
                config.TRANSLATION_TEMPERATURE
            ),
            max_tokens=(
                translation_token_limit(text)
            ),
        )

    except Exception as e:

        error = format_client_error(
            stage,
            config.TRANSLATOR_API_BASE,
            config.TRANSLATOR_MODEL_UID,
            e,
        )

        raise RuntimeError(error)


async def translate_ru_to_en(
    text_ru: str,
) -> str:

    return await ask_translation_service(
        text=text_ru,
        source_language="Russian",
        target_language="English",
        stage="translate_ru_to_en",
    )


async def translate_en_to_ru(
    text_en: str,
) -> str:

    return await ask_translation_service(
        text=text_en,
        source_language="English",
        target_language="Russian",
        stage="translate_en_to_ru",
    )
