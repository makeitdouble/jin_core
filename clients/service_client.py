import asyncio
import httpx
import config

from clients.errors import format_client_error
from clients.url_utils import join_url
from clients.model_client import ask_model


TRANSLATOR_SYSTEM_PROMPT = """
You are a machine translation engine.

Translate text exactly.

Rules:
- preserve formatting
- preserve markdown
- preserve emojis
- preserve punctuation
- preserve line breaks
- do not summarize
- do not explain
- do not answer
- output translation only
""".strip()

def _build_translation_prompt(
    text: str,
    source_language: str,
    target_language: str,
) -> str:

    return f"""
Translate from {source_language} to {target_language}.

<START_TEXT>
{text}
</START_TEXT>
""".strip()

def _translation_token_limit(text: str) -> int:

    estimated_tokens = max(
        config.TRANSLATION_MIN_TOKENS,
        len(text),
    )

    return min(
        config.TRANSLATION_MAX_TOKENS,
        estimated_tokens,
    )

async def ask_service_model(
    *,
    user_prompt: str,
    system_prompt: str,
    temperature: float,
    max_tokens: int,
) -> str:

    return await ask_model(
        api_base=config.SERVICE_API_BASE,
        model_uid=config.SERVICE_MODEL_UID,
        user_prompt=user_prompt,
        system_prompt=system_prompt,
        timeout=config.SERVICE_REQUEST_TIMEOUT,
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

    translation_prompt = _build_translation_prompt(
        text=text,
        source_language=source_language,
        target_language=target_language,
    )

    try:

        return await ask_service_model(
            user_prompt=translation_prompt,
            system_prompt=TRANSLATOR_SYSTEM_PROMPT,
            temperature=config.TRANSLATION_TEMPERATURE,
            max_tokens=_translation_token_limit(text),
        )

    except Exception as e:

        error = format_client_error(
            stage,
            config.SERVICE_API_BASE,
            config.SERVICE_MODEL_UID,
            e,
        )

        raise RuntimeError(error)


async def translate_ru_to_en(text_ru: str) -> str:

    return await ask_translation_service(
        text=text_ru,
        source_language="Russian",
        target_language="English",
        stage="translate_ru_to_en",
    )


async def translate_en_to_ru(text_en: str) -> str:

    return await ask_translation_service(
        text=text_en,
        source_language="English",
        target_language="Russian",
        stage="translate_en_to_ru",
    )
