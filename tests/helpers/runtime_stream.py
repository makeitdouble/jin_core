class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


class FakeLogger:
    def __init__(self):
        self.messages = []

    async def log_runtime(self, message):
        self.messages.append(("runtime", message))

    async def log_service(self, message):
        self.messages.append(("service", message))

    async def log_validator(self, message, **kwargs):
        self.messages.append(("validator", message, kwargs))

    async def log_error(self, message, **kwargs):
        self.messages.append(("error", message, kwargs))


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, message):
        self.messages.append(message)
