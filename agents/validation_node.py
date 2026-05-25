from agents.base_node import BaseNode

from runtime.runtime_stream import (
    RuntimeStream,
)

from settings.app_settings import (
    settings,
)


class ValidationNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        state.validation_error = ""

        response = (
                state.brain_response
                or ""
        ).strip()

        # ---------------------------------------------------------
        # EMPTY RESPONSE
        # ---------------------------------------------------------

        if not response:

            state.validation_error = (
                "Empty brain response."
            )

            return

        # ---------------------------------------------------------
        # NO RESPONSE TRANSLATION
        # ---------------------------------------------------------

        if not state.translate_response:

            state.final_answer = response

            return

        # ---------------------------------------------------------
        # RESPONSE TRANSLATION
        # ---------------------------------------------------------

        prompt = f"""
Переведи текст на русский.

Верни ТОЛЬКО итоговый перевод.
Без объяснений.
Без markdown.
Без reasoning.

TEXT:
{response}
"""

        generator = (
            context.clients["service"]
            .stream(
                context=context,
                system_prompt="""
Ты translation engine.

Запрещено:
- reasoning
- chain of thought
- explanations
- markdown
- analysis

Верни только итоговый перевод.
""",
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=1200,
            )
        )

        stream = RuntimeStream(
            context=context,
            runtime_id=(
                settings.SERVICE_MODEL_UID
            ),
            role="service",
            context_window=(
                settings.SERVICE_CONTEXT_WINDOW
            ),
            log_method=(
                context.logger
                .log_service
            ),
        )

        translated_response = (
            await stream.run(
                generator
            )
        )

        translated_response = (
            translated_response
            .strip()
        )

        # ---------------------------------------------------------
        # FALLBACK
        # ---------------------------------------------------------

        if not translated_response:

            translated_response = response

        state.final_answer = (
            translated_response
        )