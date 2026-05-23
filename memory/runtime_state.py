from settings.app_settings import settings

class RuntimeState:

    def __init__(self):

        self.states = {}

        runtimes = [
            (
                settings.SERVICE_MODEL_UID,
                "service",
                settings.SERVICE_CONTEXT_WINDOW,
            ),
            (
                settings.TRANSLATOR_MODEL_UID,
                "translator",
                settings.TRANSLATOR_CONTEXT_WINDOW,
            ),
        ]

        if not settings.USE_SERVICE_AS_BRAIN:
            runtimes.append(
                (
                    settings.BRAIN_MODEL_UID,
                    "brain",
                    settings.BRAIN_CONTEXT_WINDOW,
                )
            )

        for runtime_id, label, max_tokens in runtimes:

            if runtime_id in self.states:
                continue

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
