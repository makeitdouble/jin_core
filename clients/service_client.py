import asyncio
import httpx
import config

from clients.errors import format_client_error
from clients.url_utils import join_url


def _translation_token_limit(text: str) -> int:
    estimated_tokens = max(32, len(text) // 3)
    return min(config.TRANSLATION_MAX_TOKENS, estimated_tokens)


async def _post_translation(
    payload: dict,
    stage: str,
    *,
    timeout: float,
) -> str:

    url = join_url(config.SERVICE_API_BASE, config.CHAT_ENDPOINT)
    last_error = None

    for attempt in range(config.TRANSLATION_RETRIES + 1):

        try:
            async with httpx.AsyncClient(timeout=timeout) as client:

                response = await client.post(url, json=payload)

                response.raise_for_status()

                result = response.json()

                return result["choices"][0]["message"]["content"].strip()

        except Exception as e:

            last_error = e

            if attempt < config.TRANSLATION_RETRIES:
                await asyncio.sleep(0.5)

    error = format_client_error(
        stage,
        url,
        config.SERVICE_MODEL_UID,
        last_error,
    )

    raise RuntimeError(error)


async def translate_ru_to_en(text_ru: str) -> str:

    system_prompt = (
        "You are an expert, strict translator. "
        "Translate the user's input from Russian to English. "
        "Return ONLY the raw English translation."
    )

    payload = {
        "model": config.SERVICE_MODEL_UID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<text>{text_ru}</text>"},
        ],
        "temperature": config.TRANSLATION_TEMPERATURE,
        "max_tokens": _translation_token_limit(text_ru),
    }

    return await _post_translation(
        payload,
        "translate_ru_to_en",
        timeout=config.TRANSLATION_TIMEOUT,
    )


async def translate_en_to_ru(text_en: str) -> str:

    system_prompt = (
        "You are an expert, strict translator. "
        "Translate the user's input from English to Russian. "
        "Return ONLY the raw Russian translation."
    )

    payload = {
        "model": config.SERVICE_MODEL_UID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<text>{text_en}</text>"},
        ],
        "temperature": config.TRANSLATION_TEMPERATURE,
        "max_tokens": _translation_token_limit(text_en),
    }

    return await _post_translation(
        payload,
        "translate_en_to_ru",
        timeout=config.TRANSLATION_EN_TO_RU_TIMEOUT,
    )
