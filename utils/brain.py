from app_settings import settings


SERVICE_AS_BRAIN_RUNTIME_ACTIONS = {
    "CAN_DEEP_THOUGHT": False,
    "CAN_WEB_SEARCH": True,
    "CAN_REMEMBER_SESSION": True,
    "CAN_REMEMBER_EVENT": True,
}

BRAIN_RUNTIME_ACTIONS = {
    "CAN_DEEP_THOUGHT": False,
    "CAN_WEB_SEARCH": True,
    "CAN_REMEMBER_SESSION": True,
    "CAN_REMEMBER_EVENT": True,
}


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
            "runtime_actions": (
                SERVICE_AS_BRAIN_RUNTIME_ACTIONS
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
        "runtime_actions": (
            BRAIN_RUNTIME_ACTIONS
        ),
    }
