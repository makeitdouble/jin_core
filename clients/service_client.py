import asyncio
import httpx
import config
from clients.errors import format_client_error
from clients.url_utils import join_url


def _translation_token_limit(text: str, minimum: int, maximum: int) -> int:
    estimated_tokens = max(1, len(text) // 3)
    return min(maximum, max(minimum, estimated_tokens + config.TRANSLATION_EN_TO_RU_MIN_TOKENS))


async def _post_translation(payload: dict, stage: str, *, timeout: float | None = None) -> str:
    url = join_url(config.SERVICE_API_BASE, config.CHAT_ENDPOINT)
    request_timeout = timeout or getattr(config, "TRANSLATION_TIMEOUT", config.TRANSLATION_TIMEOUT)
    retries = getattr(config, "TRANSLATION_RETRIES", config.TRANSLATION_RETRIES)
    last_error = None

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=request_timeout) as client:
                response = await client.post(url, json=payload)
                response.raise_for_status()
                result = response.json()
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            last_error = e
            if attempt < retries:
                await asyncio.sleep(0.5)

    error = format_client_error(
        f"{stage}; attempts={retries + 1}",
        url,
        config.SERVICE_MODEL_UID,
        last_error,
    )
    return f"[TRANSLATION_ERROR: {error}]"


async def translate_ru_to_en(text_ru: str) -> str:
    system_prompt = (
        "You are an expert, strict translator. Translate the user's input from Russian to English. "
        "Return ONLY the raw English translation. Stop immediately after the translation."
    )

    payload = {
        "model": config.SERVICE_MODEL_UID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<text>{text_ru}</text>"},
        ],
        "temperature": config.TRANSLATION_TEMPERATURE,
        "max_tokens": _translation_token_limit(
            text_ru,
            minimum=getattr(config, "TRANSLATION_EN_TO_RU_MAX_TOKENS", config.TRANSLATION_EN_TO_RU_MIN_TOKENS),
            maximum=getattr(config, "TRANSLATION_RU_TO_EN_MAX_TOKENS", config.TRANSLATION_RU_TO_EN_MAX_TOKENS),
        ),
    }

    return await _post_translation(payload, "translate_ru_to_en")


async def translate_en_to_ru(text_en: str) -> str:
    system_prompt = (
        "You are an expert, strict translator. Translate the user's input from English to Russian. "
        "Return ONLY the raw Russian translation. Stop immediately after the translation."
    )

    payload = {
        "model": config.SERVICE_MODEL_UID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"<text>{text_en}</text>"},
        ],
        "temperature": config.TRANSLATION_TEMPERATURE,
        "max_tokens": _translation_token_limit(
            text_en,
            minimum=getattr(config, "TRANSLATION_EN_TO_RU_MAX_TOKENS", config.TRANSLATION_EN_TO_RU_MIN_TOKENS),
            maximum=getattr(config, "TRANSLATION_EN_TO_RU_MAX_TOKENS", config.TRANSLATION_EN_TO_RU_MAX_TOKENS),
        ),
    }

    return await _post_translation(
        payload,
        "translate_en_to_ru",
        timeout=getattr(
            config,
            "TRANSLATION_EN_TO_RU_TIMEOUT",
            getattr(config, "TRANSLATION_TIMEOUT", config.TRANSLATION_TIMEOUT),
        ),
    )
