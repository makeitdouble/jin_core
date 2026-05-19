import config


def get_brain_runtime_config():

    if config.USE_SERVICE_AS_BRAIN:

        return {
            "runtime_id": (
                config
                .SERVICE_MODEL_UID
            ),
            "label": "service",
            "context_window": (
                config.SERVICE_CONTEXT_WINDOW
            ),
            "log_method": (
                "log_service_as_brain"
            ),
        }

    return {
        "runtime_id": (
            config
            .BRAIN_MODEL_UID
        ),
        "label": "brain",
        "context_window": (
            config
            .BRAIN_CONTEXT_WINDOW
        ),
        "log_method": (
            "log_brain"
        ),
    }
