import asyncio
import uuid

from agent.nodes.base import BaseNode

from clients.translation_client import (
    translate,
)

from app_settings import (
    settings,
)

from utils.token_usage import (
    record_token_usage,
)


class TranslationNode(BaseNode):

    @staticmethod
    def _unpack_translation_result(
            translated,
    ) -> tuple[str, dict]:

        if isinstance(
            translated,
            str,
        ):
            return (
                translated,
                {},
            )

        return (
            translated.get(
                "content",
                "",
            ),
            translated.get(
                "usage",
                {},
            ),
        )

    @staticmethod
    def _record_usage(
            context,
            usage: dict,
    ):

        if not usage:
            return

        record_token_usage(
            context,
            runtime_id=(
                settings.TRANSLATOR_MODEL_UID
            ),
            role="translator",
            kind="service",
            prompt_tokens=(
                usage.get(
                    "prompt_tokens",
                    0,
                )
            ),
            completion_tokens=(
                usage.get(
                    "completion_tokens",
                    0,
                )
            ),
            total_tokens=(
                usage.get(
                    "total_tokens",
                    0,
                )
            ),
        )


    @staticmethod
    def _split_visible_chunks(
            text: str,
            *,
            max_chars: int = 64,
    ):

        buffer = ""

        for part in text.split(
                " ",
        ):

            next_part = (
                part
                if not buffer
                else f" {part}"
            )

            if (
                    buffer
                    and len(buffer) + len(next_part) > max_chars
            ):
                yield buffer
                buffer = part
                continue

            buffer += next_part

        if buffer:
            yield buffer

    @staticmethod
    async def _emit_final_answer(
            state,
            context,
            text: str,
    ):

        message = (
            text
            or ""
        ).strip()

        if not message:
            return

        message_id = str(
            uuid.uuid4()
        )

        payload = {
            "type": "message_start",
            "message_id": message_id,
            "role": (
                state.visible_response_role
                or "brain"
            ),
        }

        if state.visible_response_context:
            payload["context"] = (
                state.visible_response_context
            )

        await context.websocket.send_json(
            payload
        )

        for chunk in TranslationNode._split_visible_chunks(
                message,
        ):
            await context.websocket.send_json({
                "type": "message_chunk",
                "message_id": message_id,
                "chunk": chunk,
            })
            await asyncio.sleep(
                0.01
            )

        await context.websocket.send_json({
            "type": "message_end",
            "message_id": message_id,
        })

    async def _translate_input(
            self,
            state,
            context,
    ):

        translated = await translate(
            context=context,
            text=state.user_input,
            source_language="Russian",
            target_language="English",
        )

        translated_text, usage = (
            self._unpack_translation_result(
                translated
            )
        )

        translated_text = (
            translated_text
            or state.user_input
        )

        await context.logger.log_translation(
            translated_text
        )

        self._record_usage(
            context,
            usage,
        )

        state.translated_input = translated_text

    async def _translate_response(
            self,
            state,
            context,
    ):

        response = (
            state.final_answer
            or state.brain_response
            or ""
        ).strip()

        if not response:
            return

        translated = await translate(
            context=context,
            text=response,
            source_language="English",
            target_language="Russian",
        )

        translated_text, usage = (
            self._unpack_translation_result(
                translated
            )
        )

        translated_text = (
            translated_text
            or response
        )

        await context.logger.log_translation(
            translated_text
        )

        self._record_usage(
            context,
            usage,
        )

        state.final_answer = translated_text
        context.runtime_turn_assistant_response = (
            translated_text
        )

        await self._emit_final_answer(
            state,
            context,
            translated_text,
        )

    async def run(
            self,
            state,
            context,
    ):

        state.iteration += 1

        if state.translate_response and state.final_answer:
            await self._translate_response(
                state,
                context,
            )
            return

        await self._translate_input(
            state,
            context,
        )
