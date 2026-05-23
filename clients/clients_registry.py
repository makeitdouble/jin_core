from settings.app_settings import settings

from clients.runtime_client import (
    RuntimeClient,
)


def build_clients(
    http_client,
):

    return {

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

        "brain": RuntimeClient(
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
        ),
    }
