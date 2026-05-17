import asyncio
import httpx
import config
from clients.errors import format_client_error
from clients.url_utils import join_url


async def _post_translation(payload: dict, stage: str) -> str:
    url = join_url(config.SERVICE_API_BASE, config.CHAT_ENDPOINT)
    timeout = getattr(config, "TRANSLATION_TIMEOUT", 30.0)
    retries = getattr(config, "TRANSLATION_RETRIES", 1)
    last_error = None

    for attempt in range(retries + 1):
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
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
        "Do not add any explanations, introductory text, or corporate fluff. Output ONLY the raw translation."
    )

    payload = {
        "model": config.SERVICE_MODEL_UID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Translate this text: {text_ru}"},
        ],
        "temperature": 0.1,
        "max_tokens": 1024,
    }

    return await _post_translation(payload, "translate_ru_to_en")


async def translate_en_to_ru(text_en: str) -> str:
    system_prompt = (
        "You are an expert, strict translator. Translate the user's input from English to Russian. "
        "Maintain a realistic, non-corporate, blunt tone. Output ONLY the raw translation."
    )

    payload = {
        "model": config.SERVICE_MODEL_UID,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Translate this text: {text_en}"},
        ],
        "temperature": 0.3,
        "max_tokens": 2048,
    }

    return await _post_translation(payload, "translate_en_to_ru")
