from app_settings import settings

from runtime.client import (
    RuntimeClient,
)


def build_clients(
        http_client,
):

    clients = {

        "translator": RuntimeClient(
            api_base=(
                settings.TRANSLATOR_API_BASE
            ),
            model_uid=(
                settings.TRANSLATOR_MODEL_UID
            ),
            timeout=(
                settings
                .TRANSLATOR_REQUEST_TIMEOUT
            ),
            client=http_client,
        ),

        "service": RuntimeClient(
            api_base=(
                settings.SERVICE_API_BASE
            ),
            model_uid=(
                settings.SERVICE_MODEL_UID
            ),
            timeout=(
                settings
                .SERVICE_REQUEST_TIMEOUT
            ),
            client=http_client,
        ),
    }

    # ---------------------------------------------------------
    # DEDICATED BRAIN RUNTIME
    # ---------------------------------------------------------

    if not settings.USE_SERVICE_AS_BRAIN:

        clients["brain"] = RuntimeClient(
            api_base=(
                settings.BRAIN_API_BASE
            ),
            model_uid=(
                settings.BRAIN_MODEL_UID
            ),
            timeout=(
                settings
                .BRAIN_REQUEST_TIMEOUT
            ),
            client=http_client,
        )

    return clients