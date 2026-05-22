import config
import asyncio
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
        f"Strict translator "
        f"from {source_language} "
        f"to {target_language}. "
        f"Preserve {target_language} "
        "tokens exactly. "
        "Preserve original punctuation, "
        "casing, spacing, slang, typos. "
        "Output only translation."
    )


# ---------------------------------------------------------
# TRANSLATE
# ---------------------------------------------------------

async def translate(
    *,
    client,
    text: str,
    source_language: str,
    target_language: str,
):

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
                f"<input>{text}</input>"
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
                "usage": (
                    result.get(
                        "usage",
                        {},
                    )
                ),
            }

        return (
            ResponseExtractor
            .extract_reasoning_text(
                result
            )
        )

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
