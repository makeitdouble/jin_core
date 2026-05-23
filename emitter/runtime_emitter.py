class RuntimeEmitter:

    def __init__(
            self,
            websocket,
    ):

        self.websocket = websocket

    async def emit(
            self,
            payload: dict,
    ):

        await self.websocket.send_json(
            payload
        )