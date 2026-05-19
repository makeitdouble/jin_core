import config


class RuntimeState:

    def __init__(self):

        self.states = {}

        self.register_runtime(
            runtime_id=(
                config
                .SERVICE_MODEL_UID
            ),
            label="service",
            max_tokens=(
                config
                .SERVICE_CONTEXT_WINDOW
            ),
        )

        self.register_runtime(
            runtime_id=(
                config
                .TRANSLATOR_MODEL_UID
            ),
            label="translator",
            max_tokens=(
                config
                .TRANSLATOR_CONTEXT_WINDOW
            ),
        )

        if not config.USE_SERVICE_AS_BRAIN:

            self.register_runtime(
                runtime_id=(
                    config
                    .BRAIN_MODEL_UID
                ),
                label="brain",
                max_tokens=(
                    config
                    .BRAIN_CONTEXT_WINDOW
                ),
            )

    def register_runtime(
        self,
        *,
        runtime_id: str,
        label: str,
        max_tokens: int,
    ):

        if runtime_id in self.states:
            return

        self.states[runtime_id] = {
            "id": runtime_id,
            "label": label,
            "model": runtime_id,
            "used_tokens": 0,
            "max_tokens": max_tokens,
            "status": "online",
            "last_error": None,
        }

    def update_runtime_state(
        self,
        runtime_id: str,
        used_tokens: int | None = None,
        max_tokens: int | None = None,
        add_tokens: int | None = None,
        last_error: str | None = None,
        status: str | None = None,
    ):

        runtime_state = self.states[
            runtime_id
        ]

        if used_tokens is not None:
            runtime_state["used_tokens"] = (
                used_tokens
            )

        if max_tokens is not None:
            runtime_state["max_tokens"] = (
                max_tokens
            )

        if add_tokens is not None:
            runtime_state["used_tokens"] += (
                add_tokens
            )

        if last_error is not None:
            runtime_state["last_error"] = (
                last_error
            )

        if status is not None:
            runtime_state["status"] = status

    def get_runtime_state(
        self,
        runtime_id: str,
    ):

        return self.states[
            runtime_id
        ].copy()

    def get_all_runtime_states(
        self,
    ):

        return {
            runtime_id: state.copy()
            for runtime_id, state
            in self.states.items()
        }


runtime_state = RuntimeState()
