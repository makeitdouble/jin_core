import os
import re
import unittest
from types import SimpleNamespace

import httpx

from clients.clients_registry import (
    build_clients,
)

from pipelines.translation_pipeline import (
    TranslationPipeline,
)


TRANSLATION_CASES = [
    (
        "привет",
        {
            "hi",
            "hello",
        },
    ),
    (
        "кто ты",
        {
            "who are you",
        },
    ),
    (
        "спасибо",
        {
            "thank you",
            "thanks",
        },
    ),
    (
        "доброе утро",
        {
            "good morning",
        },
    ),
    (
        "до свидания",
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
class TranslationPipelineModelTests(
    unittest.IsolatedAsyncioTestCase
):

    async def asyncSetUp(self):

        self.http_client = httpx.AsyncClient()

        self.context = SimpleNamespace(
            websocket=SilentWebSocket(),
            logger=SilentLogger(),
            clients=build_clients(
                self.http_client
            ),
        )

        self.pipeline = TranslationPipeline()

    async def asyncTearDown(self):

        await self.http_client.aclose()

    async def test_simple_russian_to_english_phrases(self):

        failures = []

        for source_text, expected_outputs in TRANSLATION_CASES:

            with self.subTest(
                source_text=source_text
            ):

                translated = await self.pipeline.translate_input(
                    self.context,
                    source_text,
                )

                normalized = normalize_translation(
                    translated or ""
                )

                if normalized not in expected_outputs:
                    failures.append(
                        (
                            source_text,
                            sorted(
                                expected_outputs
                            ),
                            translated,
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
