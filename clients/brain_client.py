import httpx
import config


async def ask_brain(prompt: str) -> str:
    payload = {
        "model": config.BRAIN_MODEL_UID,
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": 0.7,
        "max_tokens": 2048,
    }

    try:
        async with httpx.AsyncClient(timeout=config.HTTP_TIMEOUT) as client:
            response = await client.post(
                config.BRAIN_API_URL,
                json=payload,
            )

            response.raise_for_status()
            result = response.json()

            return result["choices"][0]["message"]["content"].strip()
    except Exception as e:
        return f"[QWEN_ERROR: {str(e)}]"
