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

    def update_node_state(
        self,
        node_name: str,
        *,
        model=None,
        used_tokens=None,
        max_tokens=None,
        add_tokens=None,
    ):

        node = getattr(self, node_name)

        if model is not None:
            node["model"] = model

        if used_tokens is not None:
            node["used_tokens"] = used_tokens

        if add_tokens is not None:
            node["used_tokens"] += add_tokens

        if max_tokens is not None:
            node["max_tokens"] = max_tokens


runtime_state = RuntimeState()
