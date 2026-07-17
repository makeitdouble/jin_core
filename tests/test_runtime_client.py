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
            models_payloads_by_url=None,
    ):

        self.models_payload = models_payload
        self.models_payloads_by_url = models_payloads_by_url or {}
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
            self.models_payloads_by_url.get(
                url,
                self.models_payload,
            )
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
            1840,
        )
        self.assertIsNone(
            client.detected_context_window,
        )


    async def test_symbol_heavy_prompt_does_not_over_shrink_output_budget(self):

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
            system_prompt="* " * 7000,
            user_prompt="user",
            temperature=0.1,
            max_tokens=8192,
        )

        self.assertGreater(
            http_client.post_calls[0]["json"]["max_tokens"],
            3000,
        )

    async def test_uses_lmstudio_native_loaded_context_when_openai_models_has_no_context(self):

        http_client = FakeHttpClient(
            models_payloads_by_url={
                "http://runtime.test/v1/models": {
                    "data": [
                        {
                            "id": "test-model",
                        }
                    ]
                },
                "http://runtime.test/api/v0/models": {
                    "data": [
                        {
                            "id": "test-model",
                            "max_context_length": 131072,
                            "loaded_context_length": 8192,
                            "loaded_instances": [
                                {
                                    "config": {
                                        "context_length": 8192,
                                    }
                                }
                            ],
                        }
                    ]
                },
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
            client.detected_context_window,
            8192,
        )
        self.assertEqual(
            http_client.post_calls[0]["json"]["max_tokens"],
            4096,
        )
        self.assertEqual(
            len(http_client.get_calls),
            2,
        )

    async def test_prefers_loaded_context_over_theoretical_max_context(self):

        context_window = RuntimeClient.extract_context_window_from_model({
            "id": "test-model",
            "max_context_length": 131072,
            "loaded_context_length": 8192,
        })

        self.assertEqual(
            context_window,
            8192,
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

    async def test_context_window_detection_skips_model_without_id(self):

        http_client = FakeHttpClient(
            models_payload={
                "data": [
                    {
                        "context_length": 1024,
                    },
                    {
                        "id": "test-model",
                        "context_length": 8192,
                    },
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

        self.assertEqual(
            client.detected_context_window,
            8192,
        )

    async def test_preserves_configured_max_tokens_when_context_window_is_detected(self):

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
            configured_max_tokens=4096,
            client=http_client,
        )

        await client.ask(
            system_prompt="system",
            user_prompt="user",
            temperature=0.1,
            max_tokens=4096,
        )

        self.assertEqual(
            http_client.post_calls[0]["json"]["max_tokens"],
            4096,
        )

    async def test_preserves_configured_max_tokens_when_explicit_server_output_cap_is_higher(self):

        http_client = FakeHttpClient(
            models_payload={
                "data": [
                    {
                        "id": "test-model",
                        "context_length": 8192,
                        "max_output_tokens": 6144,
                    }
                ]
            }
        )
        client = RuntimeClient(
            api_base="http://runtime.test",
            model_uid="test-model",
            timeout=30.0,
            configured_context_window=4096,
            configured_max_tokens=4096,
            client=http_client,
        )

        await client.ask(
            system_prompt="system",
            user_prompt="user",
            temperature=0.1,
            max_tokens=4096,
        )

        self.assertEqual(
            http_client.post_calls[0]["json"]["max_tokens"],
            4096,
        )

    async def test_preserves_smaller_per_call_max_tokens_when_server_max_fallback_is_enabled(self):

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
            configured_max_tokens=4096,
            client=http_client,
        )

        await client.ask(
            system_prompt="system",
            user_prompt="user",
            temperature=0.1,
            max_tokens=512,
        )

        self.assertEqual(
            http_client.post_calls[0]["json"]["max_tokens"],
            512,
        )



if __name__ == "__main__":
    unittest.main()
