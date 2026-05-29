import asyncio

from settings.config_loader import (
    config,
)
from utils.errors import (
    format_client_error,
)

from utils.tokens import (
    translation_token_limit,
)

from utils.response_extractor import (
    ResponseExtractor,
)


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

def build_translation_system_prompt(
    source_language: str,
    target_language: str,
) -> str:

    return (
        f"Translate {source_language} to {target_language}. "
        f"Output only {target_language}. "
        "Literal translation. "
        "Preserve the exact object being named."
    )


# ---------------------------------------------------------
# TRANSLATE
# ---------------------------------------------------------

async def translate(
    *,
    context,
    text: str,
    source_language: str,
    target_language: str,
):
    client=context.clients[
        "translator"
    ]
    stage = (
        f"{source_language}"
        f"_to_"
        f"{target_language}"
    ).lower()

    try:

        result = await client.ask(
            system_prompt=(
                build_translation_system_prompt(
                    source_language,
                    target_language,
                )
            ),
            user_prompt=(
                text
            ),
            temperature=(
                config
                .TRANSLATION_TEMPERATURE
            ),
            max_tokens=(
                translation_token_limit(
                    text
                )
            ),
        )

        content = (
            ResponseExtractor
            .extract_content_text(
                result
            )
        )

        if content:
            return {
                "content": content,
                "usage": result.get("usage", {}),
            }

        return {
            "content": text,
            "usage": result.get("usage", {}),
        }

    except asyncio.CancelledError:
        raise

    except Exception as error:

        formatted_error = (
            format_client_error(
                stage,
                config.TRANSLATOR_API_BASE,
                config.TRANSLATOR_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )
