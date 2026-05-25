from agents.base_node import BaseNode

from runtime.runtime_stream import (
    RuntimeStream,
)

from settings.app_settings import (
    settings,
)


class TranslationNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        state.iteration += 1

        prompt = f"""
Переведи текст на английский.
Верни ТОЛЬКО итоговый перевод.
Без объяснений.
Без reasoning.
Без markdown.
TEXT:
{state.user_input}


"""
#VALIDATION ERROR:
#{state.validation_error}
        generator = (
            context.clients["service"]
            .stream(
                context=context,
                system_prompt=(
                    "Ты translation agent."
                ),
                user_prompt=prompt,
                temperature=0.2,
                max_tokens=800,
            )
        )

        stream = RuntimeStream(
            context=context,
            runtime_id=(
                settings
                .SERVICE_MODEL_UID
            ),
            role="service",
            context_window=(
                settings
                .TRANSLATOR_CONTEXT_WINDOW
            ),
            log_method=(
                context.logger
                .log_translation
            ),
        )

        text = await stream.run(
            generator
        )

        state.translated_input = text