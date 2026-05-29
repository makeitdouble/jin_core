from agents.base_node import BaseNode

from clients.translation_client import (
    translate,
)

from settings.app_settings import (
    settings,
)

from utils.token_usage import (
    record_token_usage,
)


class TranslationNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        state.iteration += 1

        translated = await translate(
            context=context,
            text=state.user_input,
            source_language="Russian",
            target_language="English",
        )

        if isinstance(translated, str):
            translated_text = translated
            usage = {}
        else:
            translated_text = translated["content"]
            usage = translated.get("usage", {})

        await context.logger.log_translation(
            translated_text
        )

        if usage:
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

        state.translated_input = translated_text
