import httpx

import config

from clients.url_utils import join_url

def build_payload(
    system_prompt: str,
    user_prompt: str,
    temperature: float,
    max_tokens: int,
) -> dict:

    return {
        "messages": [
            {
                "role": "system",
                "content": system_prompt,
            },
            {
                "role": "user",
                "content": user_prompt,
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }


async def ask_model(
    *,
    api_base: str,
    model_uid: str,
    user_prompt: str,
    system_prompt: str,
    timeout: float,
    temperature: float,
    max_tokens: int,
    validate_model: bool = False,
) -> str:

    url = join_url(api_base, config.CHAT_ENDPOINT)

    payload = build_payload(
        system_prompt,
        user_prompt,
        temperature,
        max_tokens,
    )

    payload["model"] = model_uid

    async with httpx.AsyncClient(timeout=timeout) as client:

        response = await client.post(
            url,
            json=payload,
        )

        response.raise_for_status()

        result = response.json()

        if validate_model:

            returned_model = result.get("model", "")

            if returned_model != model_uid:

                raise RuntimeError(
                    f"Wrong model loaded. "
                    f"Expected: '{model_uid}', "
                    f"got: '{returned_model}'"
                )

        content = (
            result
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

        content = content.strip()

        if not content:
            raise RuntimeError("Empty model response.")

        return content


