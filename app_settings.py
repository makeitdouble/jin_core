from dataclasses import dataclass

from config_loader import (
    config,
    get_env_override,
)


CHAT_ENDPOINT = "/v1/chat/completions"
MODELS_ENDPOINT = "/v1/models"
NATIVE_MODELS_ENDPOINT = "/api/v1/models"
BRAIN_REQUEST_TIMEOUT = 1000.0
RUNTIME_OUTPUT_TOKEN_RESERVE = 256
SEARCH_TIMEOUT = 100.0

SERPER_API_KEY_PLACEHOLDERS = {
    "mock-serper-api-key",
    "your-serper-api-key",
    "your_serper_api_key",
}


def is_valid_serper_api_key(api_key: str) -> bool:
    normalized_key = str(api_key or "").strip()
    if not normalized_key:
        return False
    return normalized_key.casefold() not in SERPER_API_KEY_PLACEHOLDERS


def can_use_configured_search(*, provider: str, serper_api_key: str) -> bool:
    return (
        str(provider or "").strip().casefold() == "serper"
        and is_valid_serper_api_key(serper_api_key)
    )


@dataclass(frozen=True)
class AppSettings:
    CHAT_ENDPOINT: str
    MODELS_ENDPOINT: str
    NATIVE_MODELS_ENDPOINT: str
    SERVICE_CONFIGURED: bool
    SERVICE_API_BASE: str
    SERVICE_MODEL_UID: str
    SERVICE_REQUEST_TIMEOUT: float
    BRAIN_API_BASE: str
    BRAIN_MODEL_UID: str
    BRAIN_REQUEST_TIMEOUT: float
    RUNTIME_OUTPUT_TOKEN_RESERVE: int
    SEARCH_PROVIDER: str
    SEARCH_SERPER_API_KEY: str
    SEARCH_MAX_RESULTS: int
    SEARCH_TIMEOUT: float
    CAN_SEARCH: bool


_serper_api_key = str(get_env_override("SEARCH_SERPER_API_KEY") or "").strip()

settings = AppSettings(
    CHAT_ENDPOINT=CHAT_ENDPOINT,
    MODELS_ENDPOINT=MODELS_ENDPOINT,
    NATIVE_MODELS_ENDPOINT=NATIVE_MODELS_ENDPOINT,
    SERVICE_CONFIGURED=bool(getattr(config, "SERVICE_CONFIGURED", False)),
    SERVICE_API_BASE=config.SERVICE_API_BASE,
    SERVICE_MODEL_UID=config.SERVICE_MODEL_UID,
    SERVICE_REQUEST_TIMEOUT=BRAIN_REQUEST_TIMEOUT,
    BRAIN_API_BASE=config.BRAIN_API_BASE,
    BRAIN_MODEL_UID=config.BRAIN_MODEL_UID,
    BRAIN_REQUEST_TIMEOUT=BRAIN_REQUEST_TIMEOUT,
    RUNTIME_OUTPUT_TOKEN_RESERVE=RUNTIME_OUTPUT_TOKEN_RESERVE,
    SEARCH_PROVIDER=getattr(config, "SEARCH_PROVIDER", "serper"),
    SEARCH_SERPER_API_KEY=_serper_api_key,
    SEARCH_MAX_RESULTS=getattr(config, "SEARCH_MAX_RESULTS", 5),
    SEARCH_TIMEOUT=SEARCH_TIMEOUT,
    CAN_SEARCH=can_use_configured_search(
        provider=getattr(config, "SEARCH_PROVIDER", "serper"),
        serper_api_key=_serper_api_key,
    ),
)
