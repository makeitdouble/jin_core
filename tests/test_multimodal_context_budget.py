import json
import unittest
from types import SimpleNamespace

from app_settings import settings
from runtime.client import LMStudioAPIError, RuntimeClient
from tests.test_runtime_client import FakeHttpClient, FakeStreamContextObject
from utils.current_context_window import estimate_current_context_tokens
from utils.tokens import estimate_prompt_tokens


class MultimodalContextBudgetTests(unittest.IsolatedAsyncioTestCase):
    def test_stream_snapshot_round_trip_counts_images_without_data_url(self):
        from clients.brain_client import build_brain_context_snapshot
        from runtime.stream import RuntimeStream

        snapshot = build_brain_context_snapshot(
            system_prompt="system", user_prompt="hello", model_user_prompt=[
                {"type": "text", "text": "hello"},
                {"type": "image_url", "image_url": {"url": "private-image-bytes"}},
            ],
        )
        serialized = json.dumps(snapshot)
        self.assertNotIn("private-image-bytes", serialized)
        stream = RuntimeStream.__new__(RuntimeStream)
        stream.context_snapshot = json.loads(serialized)
        stream.context = SimpleNamespace()
        stream.runtime_id = "brain"
        stream.stream = SimpleNamespace(response="", reasoning="")
        expected = estimate_prompt_tokens(system_prompt="system", user_prompt="hello") + 4096
        self.assertEqual(stream.estimate_raw_input_tokens(), expected)
        self.assertEqual(stream.estimate_input_tokens(), expected)
        self.assertEqual(stream.estimate_live_tokens(), expected)

    def make_client(self, window=32768):
        http = FakeHttpClient(models_payload={"data": [
            {"id": "test-model", "context_length": window},
        ]})
        return RuntimeClient(api_base="http://runtime.test", model_uid="test-model",
                             timeout=30, client=http), http

    def test_images_count_without_tokenizing_encoded_bytes(self):
        images = [{"type": "image_url", "image_url": {"url": url}}
                  for url in ("data:image/png;base64,abc", "https://test/image", "x" * 100000)]
        prompt = [{"type": "text", "text": "hello"}, *images]
        estimate = estimate_prompt_tokens(system_prompt="system", user_prompt=prompt)
        text_only = estimate_prompt_tokens(system_prompt="system", user_prompt="hello")
        self.assertEqual(estimate - text_only, 3 * 4096)
        self.assertEqual(estimate_current_context_tokens(
            context=SimpleNamespace(), runtime_id="brain", system_prompt="system",
            user_prompt=prompt), estimate)

    async def test_three_images_overflow_blocks_post_and_stream(self):
        client, http = self.make_client()
        prompt = [{"type": "text", "text": "x" * 88000}] + [
            {"type": "image_url", "image_url": {"url": "data:image/png;base64,a"}}
        ] * 3
        args = dict(system_prompt="system", user_prompt=prompt,
                    temperature=0.1, max_tokens=1024)
        with self.assertRaisesRegex(LMStudioAPIError, "Context overflow before request"):
            await client.ask(**args)
        with self.assertRaisesRegex(LMStudioAPIError, "Context overflow before request"):
            async for _ in client.stream(context=FakeStreamContextObject(), **args):
                pass
        self.assertEqual(http.post_calls, [])
        self.assertEqual(http.stream_calls, [])

    async def test_budget_boundary(self):
        reserve = settings.RUNTIME_OUTPUT_TOKEN_RESERVE
        client, _ = self.make_client(reserve + 1)
        with self.assertRaises(LMStudioAPIError):
            await client.resolve_safe_max_tokens(system_prompt="x", user_prompt="",
                                                  requested_max_tokens=10)
        client, _ = self.make_client(reserve + 2)
        self.assertEqual(await client.resolve_safe_max_tokens(
            system_prompt="x", user_prompt="", requested_max_tokens=10), 1)

    def test_provider_limit_formats_and_remembering(self):
        for error in (
            {"error": {"n_ctx": 32768, "n_prompt_tokens": 33856}},
            '"n_ctx":32768',
            "available context size (32768 tokens)",
            "n_ctx = 32768",
            LMStudioAPIError("terminated", details=json.dumps({
                "error": {"n_ctx": 32768, "n_prompt_tokens": 33856}})),
        ):
            with self.subTest(error=error):
                client, _ = self.make_client()
                client.remember_provider_context_window(error)
                self.assertEqual(client.provider_context_window_ceiling, 32768)
        self.assertIsNone(RuntimeClient.extract_context_window_from_error(
            {"n_prompt_tokens": 33856}))
