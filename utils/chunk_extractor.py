class ChunkExtractor:

    @staticmethod
    def extract_usage(
        chunk: dict,
    ):

        usage = chunk.get(
            "usage"
        )

        if not usage:
            return None

        return {
            "type": "usage",
            "prompt_tokens": (
                usage.get(
                    "prompt_tokens",
                    0,
                )
            ),
            "completion_tokens": (
                usage.get(
                    "completion_tokens",
                    0,
                )
            ),
            "total_tokens": (
                usage.get(
                    "total_tokens",
                    0,
                )
            ),
        }

    @staticmethod
    def extract_reasoning(
        chunk: dict,
    ):

        choices = chunk.get(
            "choices",
            [],
        )

        if not choices:
            return None

        delta = (
            choices[0]
            .get("delta", {})
        )

        reasoning = (
            delta.get(
                "reasoning_content"
            )
            or delta.get(
                "reasoning"
            )
            or delta.get(
                "thinking"
            )
        )

        if not reasoning:
            return None

        return {
            "type": "thinking",
            "content": reasoning,
        }

    @staticmethod
    def extract_content(
        chunk: dict,
    ):

        choices = chunk.get(
            "choices",
            [],
        )

        if not choices:
            return None

        choice = choices[0]

        delta = (
            choice.get(
                "delta",
                {}
            )
            or {}
        )

        message = (
            choice.get("message")
            or {}
        )

        content = (
            delta.get("content")
            or delta.get("text")
            or choice.get("text")
            or message.get("content")
        )

        if isinstance(content, list):

            text_parts = []

            for item in content:

                if not isinstance(item, dict):
                    continue

                text = item.get("text")

                if text:
                    text_parts.append(text)

            content = "".join(text_parts)

        if not isinstance(content, str):
            return None

        return {
            "type": "content",
            "content": content,
        }
