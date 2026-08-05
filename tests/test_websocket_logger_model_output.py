from pathlib import Path
import unittest

from clients.brain_client import ask_brain_stream
from config_loader import config
from websocket.logger import WebSocketLogger


ROOT = Path(__file__).resolve().parents[1]


class FakeWebSocket:

    def __init__(self):
        self.events = []

    async def send_json(self, payload):
        self.events.append(payload)


class WebSocketLoggerModelOutputTests(unittest.IsolatedAsyncioTestCase):

    async def test_memory_log_tag_suffix_preserves_l4_memory_level(self):
        websocket = FakeWebSocket()
        logger = WebSocketLogger(websocket)

        await logger.log_memory(
            "L4",
            "L4 fact deleted",
            event="fact_deleted",
            tag_suffix="DELETED",
        )

        self.assertEqual(websocket.events[0]["tag"], "[MEMORY:L4:DELETED]")
        self.assertEqual(websocket.events[0]["memory_level"], "L4")
        self.assertEqual(websocket.events[0]["memory_event"], "fact_deleted")

    async def test_brain_output_over_150_chars_uses_100_char_preview_and_payload(self):
        websocket = FakeWebSocket()
        logger = WebSocketLogger(websocket)
        text = "<ASSET_ACTION>" + ("x" * 140) + "</ASSET_ACTION>"

        await logger.log_brain_output(text)

        self.assertEqual(len(websocket.events), 1)
        payload = websocket.events[0]
        self.assertEqual(payload["tag"], "[BRAIN]")
        self.assertEqual(payload["message"], text[:100] + "...")
        self.assertEqual(payload["details"], text)

    async def test_brain_output_up_to_150_chars_is_shown_in_full_without_payload(self):
        websocket = FakeWebSocket()
        logger = WebSocketLogger(websocket)
        text = "x" * 150

        await logger.log_brain_output(text)

        self.assertEqual(len(websocket.events), 1)
        payload = websocket.events[0]
        self.assertEqual(payload["message"], text)
        self.assertNotIn("details", payload)

    async def test_brain_output_strips_outer_blank_lines(self):
        websocket = FakeWebSocket()
        logger = WebSocketLogger(websocket)

        await logger.log_brain_output("\n\n  <ASSET_ACTION></ASSET_ACTION>  \n\n")

        self.assertEqual(len(websocket.events), 1)
        payload = websocket.events[0]
        self.assertEqual(
            payload["message"],
            "<ASSET_ACTION></ASSET_ACTION>",
        )
        self.assertNotIn("details", payload)

    async def test_stream_model_output_contains_answer_without_reasoning(self):

        class FakeBrainClient:

            async def stream(self, **_kwargs):
                yield {
                    "type": "thinking",
                    "content": "hidden reasoning\n",
                }
                yield {
                    "type": "content",
                    "content": "\n\n<ASSET_ACTION></ASSET_ACTION>\n",
                }

        class Context:
            pass

        original_use_service_as_brain = config.USE_SERVICE_AS_BRAIN
        config.USE_SERVICE_AS_BRAIN = False

        try:
            chunks = [
                chunk
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="test",
                    context=Context(),
                    runtime_actions={},
                )
            ]
        finally:
            config.USE_SERVICE_AS_BRAIN = original_use_service_as_brain

        raw_output = [
            chunk
            for chunk in chunks
            if chunk.get("type") == "raw_model_output"
        ]

        self.assertEqual(
            raw_output,
            [
                {
                    "type": "raw_model_output",
                    "content": "\n\n<ASSET_ACTION></ASSET_ACTION>\n",
                },
            ],
        )
        self.assertNotIn(
            "hidden reasoning",
            raw_output[0]["content"],
        )

    async def test_service_as_brain_uses_service_tag_without_enabling_service_logs(self):
        websocket = FakeWebSocket()
        logger = WebSocketLogger(websocket)

        await logger.log_service_as_brain_output("service answer")
        await logger.log_service("ordinary service worker output")

        self.assertEqual(len(websocket.events), 1)
        self.assertEqual(websocket.events[0]["tag"], "[SERVICE]")
        self.assertEqual(websocket.events[0]["message"], "service answer")
        self.assertNotIn("details", websocket.events[0])

    def test_logger_ui_has_model_output_cards_and_payload_button(self):
        source = (
            ROOT
            / "ui"
            / "static"
            / "js"
            / "logger"
            / "log-entries.js"
        ).read_text(encoding="utf-8")

        self.assertIn('normalizedTag === "[BRAIN]"', source)
        self.assertIn('normalizedTag === "[SERVICE]"', source)
        self.assertIn('isModelOutput\n        ? "payload"', source)
        self.assertIn('? "Brain output"', source)
        self.assertIn('? "Service as brain output"', source)


if __name__ == "__main__":
    unittest.main()
