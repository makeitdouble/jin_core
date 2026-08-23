from dataclasses import dataclass

from config_loader import (
    config,
)


SERPER_API_KEY_PLACEHOLDERS = {
    "mock-serper-api-key",
    "your-serper-api-key",
    "your_serper_api_key",
}


def is_valid_serper_api_key(
    api_key: str,
) -> bool:

    normalized_key = str(
        api_key
        or ""
    ).strip()

    if not normalized_key:
        return False

    # Serper does not expose a stable client-side key shape contract.
    # Availability means "a real key is configured"; the provider validates
    # the credential when a request is made.
    return (
        normalized_key.casefold()
        not in SERPER_API_KEY_PLACEHOLDERS
    )


def can_use_configured_search(
    *,
    provider: str,
    serper_api_key: str,
) -> bool:

    return (
        str(
            provider
            or ""
        ).strip().casefold() == "serper"
        and is_valid_serper_api_key(
            serper_api_key
        )
    )


@dataclass(frozen=True)
class AppSettings:

    CHAT_ENDPOINT: str
    MODELS_ENDPOINT: str
    NATIVE_MODELS_ENDPOINT: str

    USE_SERVICE_AS_BRAIN: bool
    FORMAT_RESPONSE: bool

    SERVICE_API_BASE: str
    SERVICE_MODEL_UID: str
    SERVICE_CONTEXT_WINDOW: int
    SERVICE_REQUEST_TIMEOUT: float

    BRAIN_API_BASE: str
    BRAIN_MODEL_UID: str
    BRAIN_CONTEXT_WINDOW: int
    BRAIN_REQUEST_TIMEOUT: float

    RUNTIME_OUTPUT_TOKEN_RESERVE: int

    SEARCH_PROVIDER: str
    SEARCH_SERPER_API_KEY: str
    SEARCH_MAX_RESULTS: int
    SEARCH_TIMEOUT: float
    CAN_SEARCH: bool


settings = AppSettings(

    CHAT_ENDPOINT=config.CHAT_ENDPOINT,
    MODELS_ENDPOINT=config.MODELS_ENDPOINT,
    NATIVE_MODELS_ENDPOINT=getattr(
        config,
        "NATIVE_MODELS_ENDPOINT",
        "/api/v1/models",
    ),

    USE_SERVICE_AS_BRAIN=config.USE_SERVICE_AS_BRAIN,
    FORMAT_RESPONSE=getattr(
        config,
        "FORMAT_RESPONSE",
        True,
    ),

    SERVICE_API_BASE=config.SERVICE_API_BASE,
    SERVICE_MODEL_UID=config.SERVICE_MODEL_UID,
    SERVICE_CONTEXT_WINDOW=config.SERVICE_CONTEXT_WINDOW,
    SERVICE_REQUEST_TIMEOUT=config.SERVICE_REQUEST_TIMEOUT,

    BRAIN_API_BASE=config.BRAIN_API_BASE,
    BRAIN_MODEL_UID=config.BRAIN_MODEL_UID,
    BRAIN_CONTEXT_WINDOW=config.BRAIN_CONTEXT_WINDOW,
    BRAIN_REQUEST_TIMEOUT=config.BRAIN_REQUEST_TIMEOUT,

    RUNTIME_OUTPUT_TOKEN_RESERVE=getattr(
        config,
        "RUNTIME_OUTPUT_TOKEN_RESERVE",
        512,
    ),
    SEARCH_PROVIDER=getattr(
        config,
        "SEARCH_PROVIDER",
        "serper",
    ),
    SEARCH_SERPER_API_KEY=getattr(
        config,
        "SEARCH_SERPER_API_KEY",
        "",
    ),
    SEARCH_MAX_RESULTS=getattr(
        config,
        "SEARCH_MAX_RESULTS",
        5,
    ),
    SEARCH_TIMEOUT=getattr(
        config,
        "SEARCH_TIMEOUT",
        20.0,
    ),
    CAN_SEARCH=can_use_configured_search(
        provider=getattr(
            config,
            "SEARCH_PROVIDER",
            "serper",
        ),
        serper_api_key=getattr(
            config,
            "SEARCH_SERPER_API_KEY",
            "",
        ),
    ),
)
