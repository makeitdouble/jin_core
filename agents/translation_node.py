from agents.base_node import BaseNode

from clients.translation_client import (
    translate,
)

from settings.app_settings import (
    settings,
)

from utils.runtime_state_sync import (
    refresh_runtime_state,
)


class TranslationNode(BaseNode):

    async def run(
            self,
            state,
            context,
    ):

        state.iteration += 1

        translated = await translate(
            client=context.clients[
                "translator"
            ],
            text=state.user_input,
            source_language="Russian",
            target_language="English",
        )

        translated_text = translated[
            "content"
        ]

        usage = translated.get(
            "usage",
            {},
        )

        await context.logger.log_translation(
            translated_text
        )

        await refresh_runtime_state(
            context,
            runtime_id=(
                settings.TRANSLATOR_MODEL_UID
            ),
            add_tokens=usage.get(
                "total_tokens",
                0,
            ),
            max_tokens=(
                settings.TRANSLATOR_CONTEXT_WINDOW
            ),
            last_error=None,
            status="online",
        )

        state.translated_input = translated_text
