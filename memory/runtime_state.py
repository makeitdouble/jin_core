import config


class RuntimeState:

    def __init__(self):

        if config.BYPASS_BRAIN:

            self.brain = {
                "model": config.SERVICE_MODEL_UID,
                "used_tokens": 0,
                "max_tokens": config.SERVICE_CONTEXT_WINDOW,
            }

            self.service = {
                "model": "BYPASSED",
                "used_tokens": 0,
                "max_tokens": 0,
            }

        else:

            self.brain = {
                "model": config.BRAIN_MODEL_UID,
                "used_tokens": 0,
                "max_tokens": config.BRAIN_CONTEXT_WINDOW,
            }

            self.service = {
                "model": config.SERVICE_MODEL_UID,
                "used_tokens": 0,
                "max_tokens": config.SERVICE_CONTEXT_WINDOW,
            }


runtime_state = RuntimeState()
