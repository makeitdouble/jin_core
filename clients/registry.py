from app_settings import settings

from runtime.client import (
    RuntimeClient,
)


def build_clients(
        http_client,
):

    brain_client = RuntimeClient(
        api_base=settings.BRAIN_API_BASE,
        model_uid=settings.BRAIN_MODEL_UID,
        timeout=settings.BRAIN_REQUEST_TIMEOUT,
        configured_context_window=(
            settings.BRAIN_CONTEXT_WINDOW
        ),
        client=http_client,
    )

    clients = {
        "brain": brain_client,
        "service": brain_client,
    }

    if settings.SERVICE_CONFIGURED:
        clients["service"] = RuntimeClient(
            api_base=settings.SERVICE_API_BASE,
            model_uid=settings.SERVICE_MODEL_UID,
            timeout=settings.SERVICE_REQUEST_TIMEOUT,
            configured_context_window=(
                settings.SERVICE_CONTEXT_WINDOW
            ),
            client=http_client,
        )

    return clients
