import unittest

from utils.stream_handler import StreamHandler


class FakeWebSocket:
    def __init__(self):
        self.messages = []

    async def send_json(self, payload):
        self.messages.append(payload)


class FakeLogger:
    pass


class StreamHandlerProgressTests(unittest.IsolatedAsyncioTestCase):

    async def test_progress_keeps_runtime_progress_websocket_type(self):
        websocket = FakeWebSocket()
        handler = StreamHandler(
            websocket,
            FakeLogger(),
            role="brain",
        )
        handler.message_id = "message-123"

        await handler.send_progress({
            "type": "progress",
            "phase": "model_load",
            "state": "progress",
            "provider": "lm_studio",
            "progress": 0.37,
        })

        self.assertEqual(
            websocket.messages,
            [{
                "type": "runtime_progress",
                "message_id": "message-123",
                "phase": "model_load",
                "state": "progress",
                "provider": "lm_studio",
                "progress": 0.37,
            }],
        )

    async def test_progress_does_not_emit_when_chat_emission_is_disabled(self):
        websocket = FakeWebSocket()
        handler = StreamHandler(
            websocket,
            FakeLogger(),
            role="brain",
        )

        await handler.send_progress(
            {
                "type": "progress",
                "phase": "prompt_processing",
                "progress": 0.5,
            },
            emit=False,
        )

        self.assertEqual(websocket.messages, [])


if __name__ == "__main__":
    unittest.main()
