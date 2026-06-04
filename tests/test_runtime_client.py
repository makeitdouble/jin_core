import unittest

from runtime.client import RuntimeClient


class FakeResponse:

    def __init__(
            self,
            payload,
            *,
            status_code: int = 200,
    ):

        self.payload = payload
        self.status_code = status_code

    def json(self):

        return self.payload

    def raise_for_status(self):

        if self.status_code >= 400:
            raise RuntimeError(
                f"HTTP {self.status_code}"
            )


class FakeHttpClient:

    def __init__(
            self,
            *,
            models_payload=None,
    ):

        self.models_payload = models_payload
        self.get_calls = []
        self.post_calls = []

    async def get(
            self,
            url: str,
            *,
            timeout,
    ):

        self.get_calls.append({
            "url": url,
            "timeout": timeout,
        })

        return FakeResponse(
            self.models_payload
        )

    async def post(
            self,
            url: str,
            *,
            json,
            timeout,
    ):

        self.post_calls.append({
            "url": url,
            "json": json,
            "timeout": timeout,
        })

        return FakeResponse({
            "choices": [
                {
                    "message": {
                        "content": "ok",
                    },
                }
            ]
        })


class RuntimeClientTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_uses_detected_context_window_for_safe_max_tokens(self):

        http_client = FakeHttpClient(
            models_payload={
                "data": [
                    {
                        "id": "test-model",
                        "context_length": 8192,
                    }
                ]
            }
        )
        client = RuntimeClient(
            api_base="http://runtime.test",
            model_uid="test-model",
            timeout=30.0,
            configured_context_window=4096,
            client=http_client,
        )

        await client.ask(
            system_prompt="system " * 1000,
            user_prompt="user " * 1000,
            temperature=0.1,
            max_tokens=4096,
        )

        self.assertEqual(
            http_client.post_calls[0]["json"]["max_tokens"],
            4096,
        )
        self.assertEqual(
            client.detected_context_window,
            8192,
        )

    async def test_falls_back_to_configured_context_window(self):

        http_client = FakeHttpClient(
            models_payload={
                "data": [
                    {
                        "id": "test-model",
                    }
                ]
            }
        )
        client = RuntimeClient(
            api_base="http://runtime.test",
            model_uid="test-model",
            timeout=30.0,
            configured_context_window=4096,
            client=http_client,
        )

        await client.ask(
            system_prompt="system " * 1000,
            user_prompt="user " * 1000,
            temperature=0.1,
            max_tokens=4096,
        )

        self.assertEqual(
            http_client.post_calls[0]["json"]["max_tokens"],
            1968,
        )
        self.assertIsNone(
            client.detected_context_window,
        )

    async def test_context_window_detection_is_cached(self):

        http_client = FakeHttpClient(
            models_payload={
                "data": [
                    {
                        "id": "test-model",
                        "metadata": {
                            "n_ctx": 8192,
                        },
                    }
                ]
            }
        )
        client = RuntimeClient(
            api_base="http://runtime.test",
            model_uid="test-model",
            timeout=30.0,
            configured_context_window=4096,
            client=http_client,
        )

        await client.ask(
            system_prompt="system",
            user_prompt="user",
            temperature=0.1,
            max_tokens=100,
        )
        await client.ask(
            system_prompt="system",
            user_prompt="user",
            temperature=0.1,
            max_tokens=100,
        )

        self.assertEqual(
            len(http_client.get_calls),
            1,
        )


if __name__ == "__main__":
    unittest.main()
