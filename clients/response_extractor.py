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
    # PROVIDER TYPE
    # ---------------------------------------------------------

    @staticmethod
    def response_type(
        response: dict,
    ) -> str:

        value = str(
            response.get(
                "type",
                "",
            )
            or response.get(
                "object",
                "",
            )
            or ""
        ).strip()

        return value

    @staticmethod
    def _clamp_progress(
        value,
    ) -> float | None:

        try:
            progress = float(value)
        except (
            TypeError,
            ValueError,
        ):
            return None

        if progress < 0.0:
            return 0.0
        if progress > 1.0:
            return 1.0
        return progress

    @staticmethod
    def _llama_prompt_progress_ratio(
        progress_payload,
    ) -> float | None:

        if not isinstance(
            progress_payload,
            dict,
        ):
            return None

        try:
            total = int(
                progress_payload.get(
                    "total",
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            total = 0

        try:
            cache = int(
                progress_payload.get(
                    "cache",
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            cache = 0

        try:
            processed = int(
                progress_payload.get(
                    "processed",
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            processed = 0

        effective_total = total - cache
        effective_processed = processed - cache

        if effective_total > 0:
            return ResponseExtractor._clamp_progress(
                effective_processed / effective_total
            )

        if total > 0:
            return ResponseExtractor._clamp_progress(
                processed / total
            )

        return None

    # ---------------------------------------------------------
    # PROGRESS
    # ---------------------------------------------------------

    @staticmethod
    def extract_progress_event(
        response: dict,
    ):

        response_type = (
            ResponseExtractor
            .response_type(
                response
            )
            .casefold()
        )

        if response_type.startswith(
            "model_load."
        ):
            phase = "model_load"
            provider = "lm_studio"
        elif response_type.startswith(
            "prompt_processing."
        ):
            phase = "prompt_processing"
            provider = "lm_studio"
        else:
            phase = ""
            provider = ""

        if phase:
            state = response_type.split(
                ".",
                1,
            )[1].strip() or "progress"
            progress = (
                ResponseExtractor
                ._clamp_progress(
                    response.get(
                        "progress",
                    )
                )
            )

            if state == "start":
                progress = 0.0
            elif state == "end":
                progress = 1.0

            event = {
                "type": "progress",
                "phase": phase,
                "state": state,
                "provider": provider,
            }

            if progress is not None:
                event["progress"] = progress

            return event

        prompt_progress = response.get(
            "prompt_progress"
        )
        progress = (
            ResponseExtractor
            ._llama_prompt_progress_ratio(
                prompt_progress
            )
        )

        if progress is None:
            return None

        return {
            "type": "progress",
            "phase": "prompt_processing",
            "state": "progress",
            "provider": "llama_cpp",
            "progress": progress,
        }

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

        if isinstance(
            usage,
            dict,
        ):
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

        response_type = (
            ResponseExtractor
            .response_type(response)
            .casefold()
        )

        if response_type != "chat.end":
            return None

        result = response.get(
            "result"
        ) or {}
        if not isinstance(result, dict):
            return None

        stats = result.get(
            "stats"
        ) or {}
        if not isinstance(stats, dict):
            return None

        try:
            prompt_tokens = int(
                stats.get(
                    "input_tokens",
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            prompt_tokens = 0

        try:
            completion_tokens = int(
                stats.get(
                    "total_output_tokens",
                    0,
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            completion_tokens = 0

        return {
            "type": "usage",
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

    # ---------------------------------------------------------
    # REASONING TEXT
    # ---------------------------------------------------------

    @staticmethod
    def extract_reasoning_text(
        response: dict,
    ):

        response_type = (
            ResponseExtractor
            .response_type(response)
            .casefold()
        )

        if response_type == "reasoning.delta":
            content = response.get(
                "content",
                "",
            )
            return content if isinstance(content, str) else ""

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

        response_type = (
            ResponseExtractor
            .response_type(response)
            .casefold()
        )

        if response_type == "message.delta":
            content = response.get(
                "content",
                "",
            )
            return content if isinstance(content, str) else ""

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

                text = (
                    item.get(
                        "text"
                    )
                    or item.get(
                        "content"
                    )
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

        model = (
            response.get(
                "model",
                "",
            )
            or response.get(
                "model_instance_id",
                "",
            )
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

        if isinstance(
            finish_reason,
            str,
        ) and finish_reason.strip():
            return finish_reason.strip()

        response_type = (
            ResponseExtractor
            .response_type(response)
            .casefold()
        )

        if response_type == "chat.end":
            return "stop"

        return ""

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
