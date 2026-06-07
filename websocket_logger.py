# websocket_logger.py

from fastapi import WebSocket


class WebSocketLogger:
    def __init__(self, websocket: WebSocket):
        self.websocket = websocket

    async def log(
            self,
            tag: str,
            message: str,
            details: str | None = None,
            **extra,
    ):
        payload = {
            "type": "log",
            "tag": tag,
            "message": str(message),
        }

        if details:
            payload["details"] = str(details)

        payload.update({
            key: value
            for key, value in extra.items()
            if value is not None
        })

        await self.websocket.send_json(
            payload
        )

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

    async def log_summarizer(
            self,
            message: str,
            details: str | None = None,
    ):
        await self.log(
            "[SUMMARIZER]",
            message,
            details=details,
        )

    async def log_user(
            self,
            message: str,
            details: str | None = None,
    ):
        await self.log(
            "[USER]",
            message,
            details=details,
        )

    async def log_memory(
            self,
            level: str,
            message: str,
            details: str | None = None,
            event: str | None = None,
    ):
        await self.log(
            f"[MEMORY:{level}]",
            message,
            details=details,
            channel="memory",
            memory_level=level,
            memory_event=event,
        )

    async def log_service_as_brain(self, message: str):
        await self.log("[SERVICE as BRAIN]", message)

    async def log_error(
            self,
            message: str,
            details: str | None = None,
    ):
        await self.log(
            "[ERROR]",
            message,
            details=details,
        )

    async def log_translation(self, message: str):
        await self.log("[TRANSLATION]", message)

    async def log_runtime(self, message: str):
        await self.log("[RUNTIME]", message)

    async def log_validator(self, message: str):
        await self.log("[VALIDATOR]", message)
