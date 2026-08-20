# websocket/logger.py

from fastapi import WebSocket


class WebSocketLogger:
    MODEL_OUTPUT_PREVIEW_LIMIT = 100
    MODEL_OUTPUT_PAYLOAD_THRESHOLD = 150

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

    async def _log_model_output(
            self,
            tag: str,
            message: str,
    ):
        full_text = str(
            message
            or ""
        ).strip()

        if not full_text:
            return

        has_payload = (
            len(full_text)
            > self.MODEL_OUTPUT_PAYLOAD_THRESHOLD
        )
        preview = (
            full_text[
                :self.MODEL_OUTPUT_PREVIEW_LIMIT
            ]
            + "..."
            if has_payload
            else full_text
        )

        await self.log(
            tag,
            preview,
            details=(
                full_text
                if has_payload
                else None
            ),
        )

    async def log_brain(self, message: str):
        return None

    async def log_brain_output(self, message: str):
        await self._log_model_output(
            "[BRAIN]",
            message,
        )

    async def log_service(self, message: str):
        return None

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
            tag_suffix: str | None = None,
            **extra,
    ):
        display_level = str(level)
        if tag_suffix:
            display_level += f":{str(tag_suffix).strip().upper()}"

        await self.log(
            f"[MEMORY:{display_level}]",
            message,
            details=details,
            channel="memory",
            memory_level=level,
            memory_event=event,
            **extra,
        )

    async def log_active_memory(
            self,
            message: str,
            details: str | None = None,
            event: str | None = None,
    ):
        await self.log(
            "[ACTIVE_MEMORY]",
            message,
            details=details,
            channel="active_memory",
            active_memory_event=event,
        )

    async def log_service_as_brain(self, message: str):
        return None

    async def log_service_as_brain_output(self, message: str):
        await self._log_model_output(
            "[SERVICE]",
            message,
        )

    async def log_error(
            self,
            message: str,
            details: str | None = None,
            **extra,
    ):
        await self.log(
            "[ERROR]",
            message,
            details=details,
            **extra,
        )


    async def log_runtime(self, message: str):
        await self.log("[RUNTIME]", message)

    async def log_metabolism(
            self,
            message: str,
            details: str | None = None,
            event: str | None = None,
            request_id: str | None = None,
            metabolism_levels: dict | None = None,
    ):
        await self.log(
            "[METABOLISM]",
            message,
            details=details,
            channel="metabolism",
            metabolism_event=event,
            metabolism_request_id=request_id,
            metabolism_levels=metabolism_levels,
        )

    async def log_flow(
            self,
            message: str,
            flow_id: str = "agent-runtime",
    ):
        await self.log(
            "[FLOW]",
            message,
            channel="flow",
            flow_id=flow_id,
            flow_event="agent_route",
        )

    async def log_validator(
            self,
            message: str,
            details: str | None = None,
    ):
        await self.log(
            "[VALIDATOR]",
            message,
            details=details,
        )

    async def log_validator_loop(
            self,
            message: str,
    ):
        await self.log(
            "[VALIDATOR:LOOP]",
            message,
        )
