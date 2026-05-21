class ResponseExtractor:

    # ---------------------------------------------------------
    # CHOICES
    # ---------------------------------------------------------

    @staticmethod
    def extract_choices(
        response: dict,
    ):

        choices = response.get(
            "choices",
            [],
        )

        if not isinstance(
            choices,
            list,
        ):
            return []

        return choices

    # ---------------------------------------------------------
    # FIRST CHOICE
    # ---------------------------------------------------------

    @staticmethod
    def extract_choice(
        response: dict,
    ):

        choices = (
            ResponseExtractor
            .extract_choices(
                response
            )
        )

        if not choices:
            return {}

        choice = choices[0]

        if not isinstance(
            choice,
            dict,
        ):
            return {}

        return choice

    # ---------------------------------------------------------
    # DELTA
    # ---------------------------------------------------------

    @staticmethod
    def extract_delta(
        response: dict,
    ):

        choice = (
            ResponseExtractor
            .extract_choice(
                response
            )
        )

        delta = (
            choice.get(
                "delta",
                {}
            )
            or {}
        )

        if not isinstance(
            delta,
            dict,
        ):
            return {}

        return delta

    # ---------------------------------------------------------
    # MESSAGE
    # ---------------------------------------------------------

    @staticmethod
    def extract_message(
        response: dict,
    ):

        choice = (
            ResponseExtractor
            .extract_choice(
                response
            )
        )

        message = (
            choice.get(
                "message",
                {}
            )
            or {}
        )

        if not isinstance(
            message,
            dict,
        ):
            return {}

        return message

    # ---------------------------------------------------------
    # USAGE
    # ---------------------------------------------------------

    @staticmethod
    def extract_usage(
        response: dict,
    ):

        usage = response.get(
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

    # ---------------------------------------------------------
    # REASONING TEXT
    # ---------------------------------------------------------

    @staticmethod
    def extract_reasoning_text(
        response: dict,
    ):

        delta = (
            ResponseExtractor
            .extract_delta(
                response
            )
        )

        message = (
            ResponseExtractor
            .extract_message(
                response
            )
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
            or message.get(
                "reasoning_content"
            )
            or message.get(
                "reasoning"
            )
            or message.get(
                "thinking"
            )
        )

        if not isinstance(
            reasoning,
            str,
        ):
            return ""

        return reasoning

    # ---------------------------------------------------------
    # CONTENT TEXT
    # ---------------------------------------------------------

    @staticmethod
    def extract_content_text(
        response: dict,
    ):

        delta = (
            ResponseExtractor
            .extract_delta(
                response
            )
        )

        choice = (
            ResponseExtractor
            .extract_choice(
                response
            )
        )

        message = (
            ResponseExtractor
            .extract_message(
                response
            )
        )

        content = (
            delta.get("content")
            or delta.get("text")
            or choice.get("text")
            or message.get("content")
        )

        # -----------------------------------------------------
        # MULTIMODAL CONTENT ARRAY
        # -----------------------------------------------------

        if isinstance(
            content,
            list,
        ):

            text_parts = []

            for item in content:

                if not isinstance(
                    item,
                    dict,
                ):
                    continue

                text = item.get(
                    "text"
                )

                if text:
                    text_parts.append(
                        text
                    )

            content = "".join(
                text_parts
            )

        if not isinstance(
            content,
            str,
        ):
            return ""

        return content

    # ---------------------------------------------------------
    # MODEL
    # ---------------------------------------------------------

    @staticmethod
    def extract_model(
        response: dict,
    ):

        model = response.get(
            "model",
            "",
        )

        if not isinstance(
            model,
            str,
        ):
            return ""

        return model.strip()

    # ---------------------------------------------------------
    # FINISH REASON
    # ---------------------------------------------------------

    @staticmethod
    def extract_finish_reason(
        response: dict,
    ):

        choice = (
            ResponseExtractor
            .extract_choice(
                response
            )
        )

        finish_reason = (
            choice.get(
                "finish_reason"
            )
            or ""
        )

        if not isinstance(
            finish_reason,
            str,
        ):
            return ""

        return finish_reason.strip()

    # ---------------------------------------------------------
    # NORMALIZED THINKING CHUNK
    # ---------------------------------------------------------

    @staticmethod
    def extract_reasoning_chunk(
        response: dict,
    ):

        reasoning = (
            ResponseExtractor
            .extract_reasoning_text(
                response
            )
        )

        if not reasoning:
            return None

        return {
            "type": "thinking",
            "content": reasoning,
        }

    # ---------------------------------------------------------
    # NORMALIZED CONTENT CHUNK
    # ---------------------------------------------------------

    @staticmethod
    def extract_content_chunk(
        response: dict,
    ):

        content = (
            ResponseExtractor
            .extract_content_text(
                response
            )
        )

        if not content:
            return None

        return {
            "type": "content",
            "content": content,
        }
