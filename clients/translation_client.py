import config

from clients.runtime_client import (
    RuntimeClient,
)

from utils.errors import (
    format_client_error,
)

from utils.tokens import (
    translation_token_limit,
)


translator_client = RuntimeClient(
    api_base=(
        config.TRANSLATOR_API_BASE
    ),
    model_uid=(
        config.TRANSLATOR_MODEL_UID
    ),
    timeout=(
        config
        .TRANSLATOR_REQUEST_TIMEOUT
    ),
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

        result = await translator_client.ask(
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

        message = (
            result
            .get("choices", [{}])[0]
            .get("message", {})
        )

        content = (
            message.get(
                "content",
                "",
            ).strip()
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

        reasoning = (
            message.get(
                "reasoning_content",
                "",
            ).strip()
        )

        return {
            "content": reasoning,
            "usage": (
                result.get(
                    "usage",
                    {},
                )
            ),
        }

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
