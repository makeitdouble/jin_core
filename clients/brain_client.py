import httpx
import config
from xml.etree import ElementTree
from clients.errors import format_client_error
from clients.url_utils import join_url


def _build_payload(prompt: str, temperature: float, max_tokens: int) -> dict:
    payload = {
        "messages": [
            {
                "role": "user",
                "content": prompt,
            }
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    return payload


def _build_service_brain_prompt(contract_xml: str) -> str:
    try:
        root = ElementTree.fromstring(contract_xml)
        user_input = root.findtext("ACTIVE_USER_INPUT", default="").strip()
        compressed_history = root.findtext("COMPRESSED_HISTORY", default="").strip()
    except ElementTree.ParseError:
        user_input = contract_xml.strip()
        compressed_history = ""

    history_block = f"\nContext memory: {compressed_history}" if compressed_history else ""

    return (
        "You are JIN brain emulator running on the small service model. "
        "The user input is already translated to English. "
        "Answer in plain natural English only. Be direct, concise, and useful. "
        "Do not mention XML, runtime, models, or internal pipeline."
        f"{history_block}\nUser input: {user_input}"
    )


async def _ask_model(
    url: str,
    model: str,
    prompt: str,
    *,
    timeout: float,
    temperature: float,
    max_tokens: int,
) -> str:
    payload = _build_payload(prompt, temperature, max_tokens)
    payload["model"] = model

    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            url,
            json=payload,
        )

        response.raise_for_status()
        result = response.json()

        return result["choices"][0]["message"]["content"].strip()


async def ask_brain(prompt: str) -> str:
    if config.USE_SERVICE_AS_BRAIN:
        try:
            url = join_url(config.SERVICE_API_BASE, config.CHAT_ENDPOINT)
            service_prompt = _build_service_brain_prompt(prompt)
            return await _ask_model(
                url,
                config.SERVICE_MODEL_UID,
                service_prompt,
                timeout=getattr(config, "SERVICE_BRAIN_TIMEOUT", 90.0),
                temperature=getattr(config, "SERVICE_BRAIN_TEMPERATURE", 0.4),
                max_tokens=getattr(config, "SERVICE_BRAIN_MAX_TOKENS", 512),
            )
        except Exception as service_error:
            error = format_client_error(
                "service_as_brain",
                url,
                config.SERVICE_MODEL_UID,
                service_error,
            )
            return f"[SERVICE_BRAIN_ERROR: {error}]"

    try:
        url = join_url(config.BRAIN_API_BASE, config.CHAT_ENDPOINT)
        return await _ask_model(
            url,
            config.BRAIN_MODEL_UID,
            prompt,
            timeout=getattr(config, "BRAIN_REQUEST_TIMEOUT", config.HTTP_TIMEOUT),
            temperature=getattr(config, "BRAIN_TEMPERATURE", 0.7),
            max_tokens=getattr(config, "BRAIN_MAX_TOKENS", 2048),
        )
    except Exception as brain_error:
        try:
            url = join_url(config.SERVICE_API_BASE, config.CHAT_ENDPOINT)
            service_prompt = _build_service_brain_prompt(prompt)
            return await _ask_model(
                url,
                config.SERVICE_MODEL_UID,
                service_prompt,
                timeout=getattr(config, "SERVICE_BRAIN_TIMEOUT", 90.0),
                temperature=getattr(config, "SERVICE_BRAIN_TEMPERATURE", 0.4),
                max_tokens=getattr(config, "SERVICE_BRAIN_MAX_TOKENS", 512),
            )
        except Exception as service_error:
            brain_error_text = format_client_error(
                "primary_brain",
                join_url(config.BRAIN_API_BASE, config.CHAT_ENDPOINT),
                config.BRAIN_MODEL_UID,
                brain_error,
            )
            service_error_text = format_client_error(
                "service_brain_fallback",
                url,
                config.SERVICE_MODEL_UID,
                service_error,
            )
            return (
                f"[QWEN_ERROR: {brain_error_text}] "
                f"[SERVICE_BRAIN_ERROR: {service_error_text}]"
            )
