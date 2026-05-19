import config


def get_brain_runtime_config():

    if config.USE_SERVICE_AS_BRAIN:

        return {
            "model_uid": (
                config.SERVICE_MODEL_UID
            ),
            "context_window": (
                config.SERVICE_CONTEXT_WINDOW
            ),
            "log_method": (
                "log_service_as_brain"
            ),
        }

    return {
        "model_uid": (
            config.BRAIN_MODEL_UID
        ),
        "context_window": (
            config.BRAIN_CONTEXT_WINDOW
        ),
        "log_method": (
            "log_brain"
        ),
    }
