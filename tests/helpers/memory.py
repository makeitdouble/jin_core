def assert_contains_text(test_case, text: str, needle: str) -> None:
    test_case.assertTrue(
        needle in text,
        f"expected text to contain: {needle!r}",
    )


def assert_not_contains_text(test_case, text: str, needle: str) -> None:
    test_case.assertFalse(
        needle in text,
        f"expected text to omit: {needle!r}",
    )


class FakeServiceClient:

    def __init__(
        self,
        response_text,
        finish_reasons=None,
        usage=None,
        context_window=None,
    ):

        self.response_text = response_text
        self.finish_reasons = list(
            finish_reasons
            or []
        )
        self.usage = usage
        self.context_window = context_window
        self.calls = []

    async def resolve_request_context_window(self):

        return self.context_window

    async def ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        timeout: float | None = None,
    ):

        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })

        if isinstance(
            self.response_text,
            Exception,
        ):
            raise self.response_text

        if isinstance(
            self.response_text,
            list,
        ):
            content = self.response_text[
                len(
                    self.calls
                )
                - 1
            ]
        else:
            content = self.response_text

        choice = {
            "message": {
                "content": content,
            },
        }

        if self.finish_reasons:
            choice["finish_reason"] = (
                self.finish_reasons.pop(0)
            )

        response = {
            "choices": [
                choice,
            ],
        }

        if self.usage is not None:
            response["usage"] = self.usage

        return response


class FakeLogger:

    def __init__(self):
        self.service_logs = []
        self.summarizer_logs = []
        self.active_memory_logs = []
        self.runtime_logs = []
        self.errors = []

    async def log_runtime(
        self,
        message: str,
    ):

        self.runtime_logs.append(
            message
        )

    async def log_service(
        self,
        message: str,
    ):

        self.service_logs.append(
            message
        )

    async def log_summarizer(
            self,
            message: str,
            details: str | None = None,
    ):

        self.summarizer_logs.append(
            (
                message,
                details,
            )
        )

    async def log_active_memory(
            self,
            message: str,
            details: str | None = None,
            event: str | None = None,
    ):

        self.active_memory_logs.append(
            (
                message,
                details,
                event,
            )
        )

    async def log_error(
        self,
        message: str,
        details: str | None = None,
    ):

        self.errors.append(
            (
                message,
                details,
            )
        )
