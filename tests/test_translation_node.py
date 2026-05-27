import os
import re
import unittest
from types import SimpleNamespace

import httpx

from agents.agent_state import (
    AgentState,
)

from agents.translation_node import (
    TranslationNode,
)

from clients.clients_registry import (
    build_clients,
)


TRANSLATION_CASES = [
    (
        "\u043f\u0440\u0438\u0432\u0435\u0442",
        {
            "hi",
            "hello",
        },
    ),
    (
        "\u043a\u0442\u043e \u0442\u044b",
        {
            "who are you",
        },
    ),
    (
        "\u0441\u043f\u0430\u0441\u0438\u0431\u043e",
        {
            "thank you",
            "thanks",
        },
    ),
    (
        "\u0434\u043e\u0431\u0440\u043e\u0435 \u0443\u0442\u0440\u043e",
        {
            "good morning",
        },
    ),
    (
        "\u0434\u043e \u0441\u0432\u0438\u0434\u0430\u043d\u0438\u044f",
        {
            "goodbye",
        },
    ),
]


def normalize_translation(
    text: str,
) -> str:

    text = text.strip().lower()
    text = re.sub(
        r"[.!?]+$",
        "",
        text,
    )
    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text


class SilentEmitter:

    async def emit(
        self,
        payload: dict,
    ):
        pass


class SilentLogger:

    async def log_runtime(
        self,
        message: str,
    ):
        pass

    async def log_translation(
        self,
        message: str,
    ):
        pass

    async def log_error(
        self,
        message: str,
        details: str | None = None,
    ):
        pass


class SilentWebSocket:

    async def send_json(
        self,
        payload: dict,
    ):
        pass


@unittest.skipUnless(
    os.getenv(
        "JIN_RUN_TRANSLATION_MODEL_TESTS"
    ) == "1",
    "Set JIN_RUN_TRANSLATION_MODEL_TESTS=1 to run translator model tests.",
)
class TranslationNodeModelTests(
    unittest.IsolatedAsyncioTestCase
):

    async def asyncSetUp(self):

        self.http_client = httpx.AsyncClient()

        self.context = SimpleNamespace(
            websocket=SilentWebSocket(),
            emitter=SilentEmitter(),
            logger=SilentLogger(),
            clients=build_clients(
                self.http_client
            ),
        )

        self.node = TranslationNode()

    async def asyncTearDown(self):

        await self.http_client.aclose()

    async def test_simple_russian_to_english_phrases(self):

        failures = []

        for source_text, expected_outputs in TRANSLATION_CASES:

            with self.subTest(
                source_text=source_text
            ):

                state = AgentState(
                    user_input=source_text
                )

                await self.node.run(
                    state,
                    self.context,
                )

                normalized = normalize_translation(
                    state.translated_input
                )

                if normalized not in expected_outputs:
                    failures.append(
                        (
                            source_text,
                            sorted(
                                expected_outputs
                            ),
                            state.translated_input,
                        )
                    )

        if failures:
            details = "\n".join(
                (
                    f"{source!r} -> {actual!r}; "
                    f"expected one of {expected!r}"
                )
                for source, expected, actual
                in failures
            )

            self.fail(
                "Translator returned unexpected outputs:\n"
                f"{details}"
            )


if __name__ == "__main__":
    unittest.main()
