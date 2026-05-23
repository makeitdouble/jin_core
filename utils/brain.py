from settings.app_settings import settings

def get_brain_runtime_config():

    if settings.USE_SERVICE_AS_BRAIN:

        return {
            "runtime_id": (
                settings
                .SERVICE_MODEL_UID
            ),
            "label": "service",
            "context_window": (
                settings.SERVICE_CONTEXT_WINDOW
            ),
            "log_method": (
                "log_service_as_brain"
            ),
        }

    return {
        "runtime_id": (
            settings
            .BRAIN_MODEL_UID
        ),
        "label": "brain",
        "context_window": (
            settings
            .BRAIN_CONTEXT_WINDOW
        ),
        "log_method": (
            "log_brain"
        ),
    }
