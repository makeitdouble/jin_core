class FakeResponse:
    def __init__(self, payload, *, status_code: int = 200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeStreamResponse:
    def __init__(self, lines, *, status_code: int = 200):
        self.lines = lines
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    async def aiter_lines(self):
        for line in self.lines:
            yield line


class FakeStreamContext:
    def __init__(self, response):
        self.response = response

    async def __aenter__(self):
        return self.response

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeHttpClient:
    def __init__(
        self,
        *,
        models_payload=None,
        models_payloads_by_url=None,
        stream_lines=None,
        stream_lines_by_url=None,
        stream_status_code: int = 200,
    ):
        self.models_payload = models_payload
        self.models_payloads_by_url = models_payloads_by_url or {}
        self.stream_lines = stream_lines or []
        self.stream_lines_by_url = stream_lines_by_url or {}
        self.stream_status_code = stream_status_code
        self.get_calls = []
        self.post_calls = []
        self.stream_calls = []

    async def get(self, url: str, *, timeout):
        self.get_calls.append({"url": url, "timeout": timeout})
        return FakeResponse(self.models_payloads_by_url.get(url, self.models_payload))

    async def post(self, url: str, *, json, timeout):
        self.post_calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse({"choices": [{"message": {"content": "ok"}}]})

    def stream(self, method, url, *, json, timeout):
        self.stream_calls.append(
            {"method": method, "url": url, "json": json, "timeout": timeout}
        )
        return FakeStreamContext(
            FakeStreamResponse(
                self.stream_lines_by_url.get(url, self.stream_lines),
                status_code=self.stream_status_code,
            )
        )


class FakeLogger:
    def __init__(self):
        self.errors = []
        self.error_details = []
        self.logs = []

    async def log(self, tag, message, **_kwargs):
        self.logs.append((tag, message))

    async def log_error(self, message, details=None):
        self.errors.append(message)
        self.error_details.append(details)


class FakeStreamContextObject:
    def __init__(self):
        self.active_streams = {}
        self.logger = FakeLogger()
