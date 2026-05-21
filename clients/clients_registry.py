import config

from clients.runtime_client import (
    RuntimeClient,
)


def build_clients(
    http_client,
):

    return {

        "translator": RuntimeClient(
            api_base=(
                config.TRANSLATOR_API_BASE
            ),
            model_uid=(
                config.TRANSLATOR_MODEL_UID
            ),
            timeout=(
                config
                .TRANSLATOR_REQUEST_TIMEOUT
            ),
            client=http_client,
        ),

        "service": RuntimeClient(
            api_base=(
                config.SERVICE_API_BASE
            ),
            model_uid=(
                config.SERVICE_MODEL_UID
            ),
            timeout=(
                config
                .SERVICE_REQUEST_TIMEOUT
            ),
            client=http_client,
        ),

        "brain": RuntimeClient(
            api_base=(
                config.BRAIN_API_BASE
            ),
            model_uid=(
                config.BRAIN_MODEL_UID
            ),
            timeout=(
                config
                .BRAIN_REQUEST_TIMEOUT
            ),
            client=http_client,
        ),
    }
