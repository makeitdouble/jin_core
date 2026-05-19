# memory/runtime_state.py

import config


class RuntimeState:

    def __init__(self):

        brain_model = (
            config.SERVICE_MODEL_UID
            if config.USE_SERVICE_AS_BRAIN
            else config.BRAIN_MODEL_UID
        )

        brain_context = (
            config.SERVICE_CONTEXT_WINDOW
            if config.USE_SERVICE_AS_BRAIN
            else config.BRAIN_CONTEXT_WINDOW
        )

        self.brain = {
            "model": brain_model,
            "used_tokens": 0,
            "max_tokens": brain_context,
        }

        self.service = {
            "model": (
                config.SERVICE_MODEL_UID
            ),
            "used_tokens": 0,
            "max_tokens": (
                config.SERVICE_CONTEXT_WINDOW
            ),
        }

        self.translator = {
            "model": (
                config.TRANSLATOR_MODEL_UID
            ),
            "used_tokens": 0,
            "max_tokens": (
                config.TRANSLATOR_CONTEXT_WINDOW
            ),
        }

    def update_node_state(
        self,
        node_name: str,
        model: str | None = None,
        used_tokens: int | None = None,
        max_tokens: int | None = None,
        add_tokens: int | None = None,
    ):

        node = getattr(
            self,
            node_name,
        )

        if model is not None:
            node["model"] = model

        if used_tokens is not None:
            node["used_tokens"] = used_tokens

        if max_tokens is not None:
            node["max_tokens"] = max_tokens

        if add_tokens is not None:
            node["used_tokens"] += add_tokens


runtime_state = RuntimeState()
