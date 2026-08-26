import unittest
from typing import cast
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from fastapi import WebSocket

from agent import (
    AgentState,
)
from agent.nodes import (
    BrainNode,
)
from clients.search_client import (
    build_empty_search_result,
    build_failed_search_result,
    build_search_result_fallback_answer,
    format_search_provider_error,
    normalize_search_results,
)
from clients.search_provider import normalize_serper_item
from runtime.runtime_context import (
    RuntimeContext,
    RuntimeEmitter,
)
from websocket.logger import (
    WebSocketLogger,
)
from rules.brain_context_builder import (
    build_brain_context,
    get_enabled_runtime_actions,
    SERVICE_AS_BRAIN_RUNTIME_ACTIONS,
)
from app_settings import (
    is_valid_serper_api_key,
)


class FakeWebSocket:

    def __init__(self):
        self.messages = []

    async def send_json(
        self,
        payload: dict,
    ):
        self.messages.append(
            payload
        )


async def fake_receive():
    return {
        "type": "websocket.disconnect",
    }


async def fake_send(_message):
    return None


def make_logger_websocket() -> WebSocket:
    return WebSocket(
        {
            "type": "websocket",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "scheme": "ws",
            "server": (
                "test",
                80,
            ),
            "client": (
                "test",
                123,
            ),
            "root_path": "",
        },
        fake_receive,
        fake_send,
    )


class FakeEmitter(RuntimeEmitter):

    def __init__(self):
        super().__init__(
            FakeWebSocket()
        )
        self.payloads = []

    async def emit(
        self,
        payload: dict,
    ):
        self.payloads.append(
            payload
        )


class FakeLogger(WebSocketLogger):

    def __init__(self):
        super().__init__(
            make_logger_websocket()
        )
        self.messages = []

    async def log(
        self,
        tag: str,
        message: str,
        details: str | None = None,
    ):
        self.messages.append(
            (
                tag,
                message,
                details,
            )
        )

    async def log_runtime(
        self,
        message: str,
    ):
        await self.log(
            "[RUNTIME]",
            message,
        )

    async def log_brain(
        self,
        message: str,
    ):
        await self.log(
            "[BRAIN]",
            message,
        )

    async def log_service(
        self,
        message: str,
    ):
        await self.log(
            "[SERVICE]",
            message,
        )

    async def log_service_as_brain(
        self,
        message: str,
    ):
        await self.log(
            "[SERVICE as BRAIN]",
            message,
        )

    async def log_error(
        self,
        message: str,
        details: str | None = None,
    ):
        await self.log(
            "[ERROR]",
            message,
            details,
        )

    async def log_validator(
        self,
        message: str,
        details: str | None = None,
    ):
        await self.log(
            "[VALIDATOR]",
            message,
            details,
        )


class FakeBrainClient:

    def __init__(
        self,
        streams,
        ask_responses=None,
    ):
        self.streams = list(
            streams
        )
        self.prompts = []
        self.ask_prompts = []
        self.ask_responses = list(
            ask_responses
            or []
        )

    async def ask(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ):
        self.ask_prompts.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )

        if self.ask_responses:
            content = self.ask_responses.pop(0)
        else:
            content = build_empty_search_result(
                "unknown"
            )

        return {
            "choices": [
                {
                    "message": {
                        "content": content,
                    },
                },
            ],
        }

    async def stream(
        self,
        *,
        context,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
    ):
        self.prompts.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
            }
        )

        chunks = self.streams.pop(0)

        for chunk in chunks:
            yield chunk


class FakeSearchProvider:

    def __init__(
        self,
        results=None,
        error: Exception | None = None,
    ):
        self.results = list(
            results
            or []
        )
        self.error = error
        self.queries = []

    async def __call__(
        self,
        query: str,
    ):
        self.queries.append(
            query
        )

        if self.error is not None:
            raise self.error

        return list(
            self.results
        )


def make_result(
    *,
    title: str = "Tesla vehicle price",
    source: str = "tesla.com",
    url: str = "https://www.tesla.com/",
    quote: str = "Tesla vehicle price result.",
    excerpt: str = "Current Tesla vehicle price result.",
) -> dict:

    return {
        "title": title,
        "source": source,
        "url": url,
        "quote": quote,
        "excerpt": excerpt,
    }


def make_context(
    brain_client,
    search_provider=None,
) -> RuntimeContext:

    context = RuntimeContext(
        websocket=FakeWebSocket(),
        emitter=FakeEmitter(),
        logger=FakeLogger(),
        clients={
            "brain": brain_client,
            "service": brain_client,
        },
    )

    if search_provider is not None:
        context.search_provider = search_provider

    return context


def get_fake_websocket(
    context: RuntimeContext,
) -> FakeWebSocket:

    return cast(
        FakeWebSocket,
        context.websocket,
    )


def get_fake_logger(
    context: RuntimeContext,
) -> FakeLogger:

    return cast(
        FakeLogger,
        context.logger,
    )


class SearchFlowTests(
    unittest.IsolatedAsyncioTestCase
):

    def setUp(self):
        self._original_service_web_search = (
            SERVICE_AS_BRAIN_RUNTIME_ACTIONS.get(
                "CAN_WEB_SEARCH",
                False,
            )
        )
        self._original_service_deep_web_search = (
            SERVICE_AS_BRAIN_RUNTIME_ACTIONS.get(
                "CAN_DEEP_WEB_SEARCH",
                False,
            )
        )
        SERVICE_AS_BRAIN_RUNTIME_ACTIONS["CAN_WEB_SEARCH"] = True
        SERVICE_AS_BRAIN_RUNTIME_ACTIONS["CAN_DEEP_WEB_SEARCH"] = True

    def tearDown(self):
        SERVICE_AS_BRAIN_RUNTIME_ACTIONS["CAN_WEB_SEARCH"] = (
            self._original_service_web_search
        )
        SERVICE_AS_BRAIN_RUNTIME_ACTIONS["CAN_DEEP_WEB_SEARCH"] = (
            self._original_service_deep_web_search
        )

    def test_serper_key_validation_accepts_any_configured_real_key(self):

        for value in (
            "7037beeecf37f7555e12ac2c06904634a283ff0",
            "r/7037beeecf37f7555e12ac2c06904634a283ff0",
            "serper-live-key-with-provider-defined-format",
        ):
            with self.subTest(value=value):
                self.assertTrue(
                    is_valid_serper_api_key(
                        value
                    )
                )

        for value in (
            "",
            "   ",
            "mock-serper-api-key",
            "your-serper-api-key",
            "your_serper_api_key",
        ):
            with self.subTest(value=value):
                self.assertFalse(
                    is_valid_serper_api_key(
                        value
                    )
                )

    def test_configured_serper_key_keeps_search_actions_in_context(self):

        runtime_actions = {
            "CAN_WEB_SEARCH": True,
            "CAN_DEEP_WEB_SEARCH": True,
        }

        with patch(
            "rules.brain_context_builder.settings",
            SimpleNamespace(CAN_SEARCH=True),
        ):
            prompt = build_brain_context(
                runtime_actions=runtime_actions
            )

            self.assertEqual(
                get_enabled_runtime_actions(
                    runtime_actions
                ),
                (
                    "DEEP_WEB_SEARCH",
                    "WEB_SEARCH",
                ),
            )

        self.assertIn(
            "Use WEB_SEARCH",
            prompt,
        )
        self.assertIn(
            "Use DEEP_WEB_SEARCH",
            prompt,
        )

    def test_invalid_serper_key_hides_search_actions_from_context(self):

        runtime_actions = {
            "CAN_WEB_SEARCH": True,
            "CAN_DEEP_WEB_SEARCH": True,
        }

        with patch(
            "rules.brain_context_builder.settings",
            SimpleNamespace(CAN_SEARCH=False),
        ):
            prompt = build_brain_context(
                runtime_actions=runtime_actions
            )

            self.assertEqual(
                get_enabled_runtime_actions(
                    runtime_actions
                ),
                (),
            )

        self.assertNotIn(
            "Use WEB_SEARCH",
            prompt,
        )
        self.assertNotIn(
            "Use DEEP_WEB_SEARCH",
            prompt,
        )

    def test_found_search_result_contains_results(self):

        result = normalize_search_results(
            [
                make_result(
                    title="Python & docs",
                    quote="A < B & C",
                    excerpt="Use > carefully",
                ),
            ],
            "latest Python version",
        )

        self.assertIn(
            "<STATUS>FOUND</STATUS>",
            result,
        )
        self.assertIn(
            "<TITLE>Python &amp; docs</TITLE>",
            result,
        )
        self.assertIn(
            "<QUOTE>A &lt; B &amp; C</QUOTE>",
            result,
        )

    def test_empty_search_result_contains_empty_results(self):

        result = build_empty_search_result(
            "weather in Kyiv"
        )

        self.assertIn(
            "<SEARCH_RESULT>",
            result,
        )
        self.assertIn(
            "<STATUS>NOT_FOUND</STATUS>",
            result,
        )
        self.assertIn(
            "No search results found.",
            result,
        )
        self.assertIn(
            "<RESULTS></RESULTS>",
            result,
        )
        self.assertNotIn(
            "<![CDATA[",
            result,
        )

    def test_failed_search_result_does_not_leak_provider_details(self):

        result = build_failed_search_result(
            "current price of apples",
        )

        self.assertIn(
            "<STATUS>FAILED</STATUS>",
            result,
        )
        self.assertNotIn(
            "Traceback",
            result,
        )

    def test_provider_error_log_redacts_request_url(self):

        request = httpx.Request(
            "POST",
            (
                "https://google.serper.dev/search"
            ),
            headers={
                "X-API-KEY": "secret-api-key",
            },
        )
        response = httpx.Response(
            403,
            request=request,
        )
        error = httpx.HTTPStatusError(
            "forbidden",
            request=request,
            response=response,
        )

        result = format_search_provider_error(
            error
        )

        self.assertEqual(
            result,
            "HTTP 403 from search provider",
        )
        self.assertNotIn(
            "secret-api-key",
            result,
        )

    def test_serper_item_normalizes_organic_result(self):

        result = normalize_serper_item({
            "title": "Python 3.15.0 docs",
            "link": "https://www.python.org/downloads/",
            "snippet": "Latest Python release information.",
        })

        self.assertEqual(
            result,
            {
                "title": "Python 3.15.0 docs",
                "source": "python.org",
                "url": "https://www.python.org/downloads/",
                "quote": "Latest Python release information.",
                "excerpt": "Latest Python release information.",
            },
        )

    def test_search_result_fallback_answer_hides_xml(self):

        search_result = normalize_search_results(
            [
                make_result(
                    title="Python releases",
                    source="python.org",
                    url="https://www.python.org/downloads/",
                    quote="Python 3.14.5 May 10, 2026.",
                ),
            ],
            "latest Python version",
        )

        result = build_search_result_fallback_answer(
            search_result
        )

        self.assertIn(
            "Found 1 search result.",
            result,
        )
        self.assertIn(
            "Python releases (python.org)",
            result,
        )
        self.assertIn(
            "Python 3.14.5",
            result,
        )
        self.assertNotIn(
            "<SEARCH_RESULT>",
            result,
        )

    async def test_search_is_model_driven_for_explicit_user_request(self):

        search_provider = FakeSearchProvider(
            results=[
                make_result(
                    quote="Tesla vehicle price is 35000 USD.",
                    excerpt="Current Tesla vehicle price result.",
                ),
            ],
        )
        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "content",
                        "content": (
                            "Needs current pricing. "
                            "<WEB_SEARCH:tesla car price>"
                        ),
                    },
                ],
                [
                    {
                        "type": "content",
                        "content": "Tesla pricing depends on configuration.",
                    },
                ],
            ],
        )
        context = make_context(
            brain_client,
            search_provider=search_provider,
        )
        state = AgentState(
            user_input=(
                "\u043f\u043e\u0438\u0449\u0438 "
                "\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c "
                "\u0430\u0432\u0442\u043e\u043c\u043e\u0431\u0438\u043b\u044f "
                "\u0442\u0435\u0441\u043b\u0430"
            ),
        )

        await BrainNode().run(
            state,
            context,
        )

        runtime_events = [
            message
            for message in get_fake_websocket(
                context
            ).messages
            if message.get("type") == "runtime_action"
        ]
        thinking_chunks = [
            message.get(
                "chunk",
                "",
            )
            for message in get_fake_websocket(
                context
            ).messages
            if message.get("type") == "thinking_chunk"
        ]

        self.assertEqual(
            len(runtime_events),
            2,
        )
        self.assertEqual(
            runtime_events[0]["query"],
            "tesla car price",
        )
        self.assertEqual(
            runtime_events[0]["id"],
            "web_search_001",
        )
        self.assertEqual(
            runtime_events[0]["display_name"],
            "WEB_SEARCH",
        )
        self.assertEqual(
            runtime_events[0]["text"],
            "WEB_SEARCH: tesla car price",
        )
        self.assertNotIn(
            "Searching for",
            runtime_events[0]["text"],
        )
        self.assertEqual(
            runtime_events[1],
            {
                "type": "runtime_action",
                "action": "web_search",
                "display_name": "WEB_SEARCH",
                "id": "web_search_001",
                "status": "completed",
                "scene_effect": "search",
            },
        )
        self.assertIn(
            "<SEARCH_RESULT>",
            context.runtime_search_result,
        )
        self.assertIn(
            "35000",
            context.runtime_search_result,
        )
        self.assertEqual(
            search_provider.queries,
            [
                "tesla car price",
            ],
        )
        logger_text = "\n".join(
            message
            for _, message, _ in get_fake_logger(
                context
            ).messages
        )
        self.assertIn(
            "[RUNTIME ACTION] executing search",
            logger_text,
        )
        self.assertIn(
            "id='web_search_001'",
            logger_text,
        )
        self.assertIn(
            "query='tesla car price'",
            logger_text,
        )
        self.assertIn(
            "<CURRENT_REQUEST_FLOW>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertIn(
            f"<ORIGINAL_USER_REQUEST>\n        {state.user_input}",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertIn(
            "<LAST_EXECUTED_ACTION>WEB_SEARCH</LAST_EXECUTED_ACTION>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertNotIn(
            "<SEQUENCE_ORIGIN_REQUEST>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertNotIn(
            "\u043f\u043e\u0438\u0449\u0438",
            brain_client.prompts[1]["user_prompt"],
        )
        self.assertNotIn(
            "<SEARCH_RESULT>",
            brain_client.prompts[1]["user_prompt"],
        )
        self.assertIn(
            '<TOOL_RESULT name="WEB_SEARCH" id="web_search_001"',
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertIn(
            "<CURRENT_TRUSTED_RUNTIME_VARIABLES>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertIn(
            "<SEARCH_RESULT>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertNotIn(
            "<![CDATA[<SEARCH_RESULT>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertNotIn(
            "<RESULTS></RESULTS>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertEqual(
            state.brain_response,
            "Tesla pricing depends on configuration.",
        )

    async def test_brain_emitted_search_runs_even_with_text(self):

        search_provider = FakeSearchProvider(
            results=[
                make_result(
                    quote="Tesla vehicle price is 35000 USD.",
                ),
            ],
        )
        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "content",
                        "content": (
                            "I will check. "
                            "<WEB_SEARCH:tesla car price>"
                        ),
                    },
                ],
                [
                    {
                        "type": "content",
                        "content": "Tesla pricing summary from search result.",
                    },
                ],
            ],
        )
        context = make_context(
            brain_client,
            search_provider=search_provider,
        )
        state = AgentState(
            user_input="Tell me about Tesla.",
        )

        await BrainNode().run(
            state,
            context,
        )

        runtime_events = [
            message
            for message in get_fake_websocket(
                context
            ).messages
            if message.get("type") == "runtime_action"
        ]

        self.assertEqual(
            len(runtime_events),
            2,
        )
        self.assertEqual(
            runtime_events[0]["query"],
            "tesla car price",
        )
        self.assertEqual(
            runtime_events[1]["status"],
            "completed",
        )
        self.assertEqual(
            len(brain_client.prompts),
            2,
        )

    async def test_search_action_preserves_initial_brain_stream(self):

        search_provider = FakeSearchProvider(
            results=[
                make_result(
                    title="Apple price",
                    quote="Apple price result.",
                    excerpt="Apple price result.",
                ),
            ],
        )
        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "content",
                        "content": (
                            "Needs current pricing. "
                            "<WEB_SEARCH:apple price>"
                        ),
                    },
                    {
                        "type": "content",
                        "content": "Guessed apple price before search.",
                    },
                ],
                [
                    {
                        "type": "content",
                        "content": "Apple price from search result.",
                    },
                ],
            ],
        )
        context = make_context(
            brain_client,
            search_provider=search_provider,
        )
        state = AgentState(
            user_input="How much are apples?",
        )

        await BrainNode().run(
            state,
            context,
        )

        message_chunks = [
            message.get(
                "chunk",
                "",
            )
            for message in get_fake_websocket(
                context
            ).messages
            if message.get("type") == "message_chunk"
        ]

        visible_text = "".join(
            message_chunks
        )
        self.assertIn(
            "Needs current pricing.",
            visible_text,
        )
        self.assertIn(
            "Guessed apple price before search.",
            visible_text,
        )
        self.assertIn(
            "Apple price from search result.",
            visible_text,
        )
        self.assertNotIn(
            "<WEB_SEARCH:",
            visible_text,
        )
        self.assertEqual(
            state.brain_response,
            "Apple price from search result.",
        )
        self.assertEqual(
            len(brain_client.prompts),
            2,
        )

    async def test_deep_search_marker_runs_child_search_bubbles(self):

        search_provider = FakeSearchProvider(
            results=[
                make_result(
                    title="Blue tomato evidence",
                    quote="Blue tomato anthocyanin evidence.",
                ),
            ],
        )
        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "content",
                        "content": (
                            "<DEEP_WEB_SEARCH>\n"
                            "Research blue tomato varieties.\n"
                            "</DEEP_WEB_SEARCH>"
                        ),
                    },
                ],
                [
                    {
                        "type": "content",
                        "content": "Blue tomato summary from deep search.",
                    },
                ],
            ],
            ask_responses=[
                (
                    '{"queries":["blue tomato varieties",'
                    '"blue tomato anthocyanins"],'
                    '"spawn":[],"report":"need two sources",'
                    '"done":true}'
                ),
                (
                    '{"queries":[],"spawn":[],'
                    '"report":"blue tomato final report",'
                    '"done":true}'
                ),
            ],
        )
        context = make_context(
            brain_client,
            search_provider=search_provider,
        )
        state = AgentState(
            user_input="Research blue tomatoes.",
        )

        await BrainNode().run(
            state,
            context,
        )

        runtime_events = [
            message
            for message in get_fake_websocket(
                context
            ).messages
            if message.get("type") == "runtime_action"
            and message.get("action") == "web_search"
        ]
        deep_search_events = [
            message
            for message in (
                context.emitter.payloads
                + get_fake_websocket(
                    context
                ).messages
            )
            if message.get("type") == "runtime_action"
            and message.get("action") == "deep_web_search"
        ]
        deep_search_lifecycle_events = [
            event
            for event in deep_search_events
            if event.get("status") in {
                "started",
                "completed",
            }
        ]
        started = [
            event
            for event in runtime_events
            if event.get("status") == "started"
        ]
        completed = [
            event
            for event in runtime_events
            if event.get("status") == "completed"
        ]
        message_chunks = [
            message.get(
                "chunk",
                "",
            )
            for message in get_fake_websocket(
                context
            ).messages
            if message.get("type") == "message_chunk"
        ]
        visible_text = "".join(
            message_chunks
        )

        self.assertEqual(
            search_provider.queries,
            [
                "blue tomato varieties",
                "blue tomato anthocyanins",
            ],
        )
        self.assertEqual(
            [
                event.get("status")
                for event in deep_search_lifecycle_events
            ],
            [
                "started",
                "completed",
            ],
        )
        self.assertEqual(
            [event.get("status") for event in deep_search_events],
            ["started", "running", "completed"],
        )
        self.assertFalse(
            any(
                event.get("counter_only")
                for event in deep_search_events
            )
        )
        self.assertEqual(
            deep_search_lifecycle_events[0].get("text"),
            "DEEP_WEB_SEARCH",
        )
        self.assertEqual(
            deep_search_lifecycle_events[1].get("text"),
            "DEEP_WEB_SEARCH: Research blue tomato varieties.",
        )
        self.assertEqual(
            deep_search_lifecycle_events[0].get("id"),
            deep_search_lifecycle_events[1].get("id"),
        )
        self.assertEqual(
            [event.get("query") for event in started],
            search_provider.queries,
        )
        self.assertEqual(
            [event.get("query") for event in completed],
            search_provider.queries,
        )
        self.assertTrue(
            all(
                event.get("deep_search_child") is True
                for event in runtime_events
            )
        )
        self.assertTrue(
            all(
                event.get("deep_search_parent_id")
                == deep_search_lifecycle_events[0].get("id")
                for event in runtime_events
            )
        )
        self.assertNotIn(
            "<DEEP_WEB_SEARCH",
            visible_text,
        )
        self.assertNotIn(
            "</DEEP_WEB_SEARCH>",
            visible_text,
        )
        self.assertEqual(
            state.brain_response,
            "Blue tomato summary from deep search.",
        )
        followup_prompt = brain_client.prompts[1]["system_prompt"]
        self.assertIn(
            "DEEP_WEB_SEARCH:",
            followup_prompt,
        )
        self.assertIn(
            "WEB_SEARCH:",
            followup_prompt,
        )
        self.assertNotIn(
            "do not start another web search",
            followup_prompt,
        )

    async def test_empty_search_results_are_removed_from_brain_context(self):

        search_provider = FakeSearchProvider()
        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "content",
                        "content": (
                            "<WEB_SEARCH:jupiter cost>"
                        ),
                    },
                ],
                [
                    {
                        "type": "content",
                        "content": "No usable search result was available.",
                    },
                ],
            ],
        )
        context = make_context(
            brain_client,
            search_provider=search_provider,
        )
        state = AgentState(
            user_input="How much does Jupiter cost?",
        )

        await BrainNode().run(
            state,
            context,
        )

        self.assertIn(
            "<SEARCH_RESULT>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertNotIn(
            "<RESULTS",
            brain_client.prompts[1]["system_prompt"],
        )

    async def test_empty_followup_does_not_return_raw_search_xml(self):

        search_provider = FakeSearchProvider(
            results=[
                make_result(
                    title="Python releases",
                    source="python.org",
                    quote="Python 3.14.5 May 10, 2026.",
                ),
            ],
        )
        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "content",
                        "content": (
                            "<WEB_SEARCH:latest Python version>"
                        ),
                    },
                ],
                [],
            ],
        )
        context = make_context(
            brain_client,
            search_provider=search_provider,
        )
        state = AgentState(
            user_input="Latest Python?",
        )

        await BrainNode().run(
            state,
            context,
        )

        self.assertIn(
            "Python releases",
            state.brain_response,
        )
        self.assertNotIn(
            "<SEARCH_RESULT>",
            state.brain_response,
        )


if __name__ == "__main__":
    unittest.main()


