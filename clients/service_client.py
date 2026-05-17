import httpx
import config


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

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(config.SERVICE_API_URL, json=payload)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"[TRANSLATION_ERROR: {str(e)}]"


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

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.post(config.SERVICE_API_URL, json=payload)
            response.raise_for_status()
            result = response.json()
            return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            return f"[TRANSLATION_ERROR: {str(e)}]"
