# logger.py

from fastapi import WebSocket


class WebSocketLogger:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def log(self, tag: str, message: str):
        await self.websocket.send_json({
            "type": "log",
            "tag": tag,
            "message": str(message),
        })

    async def log_before_hook(self, message: str):
        await self.log("[BEFORE_HOOK]", message)

    async def log_after_hook(self, message: str):
        await self.log("[AFTER_HOOK]", message)

    async def log_system(self, message: str):
        await self.log("[SYSTEM]", message)

    async def log_payload(self, payload: str, limit: int = 500):
        await self.log("[PAYLOAD]", payload[:limit])

    async def log_brain(self, message: str):
        await self.log("[BRAIN]", message)

    async def log_service(self, message: str):
        await self.log("[SERVICE]", message)

    async def log_service_as_brain(self, message: str):
        await self.log("[SERVICE as BRAIN]", message)

    async def log_error(self, message: str):
        await self.log("[ERROR]", message)

    async def log_translation(self, message: str):
        await self.log("[TRANSLATION]", message)

    async def log_runtime(self, message: str):
        await self.log("[RUNTIME]", message)
