import unittest
from typing import cast

from fastapi import WebSocket

from agents.agent_state import (
    AgentState,
)
from agents.brain_node import (
    BrainNode,
)
from clients.search_client import (
    build_search_system_prompt,
    build_unavailable_search_result,
    normalize_search_result,
)
from contracts.context_contract import (
    SEARCH_ACTION_CLOSE,
    SEARCH_ACTION_OPEN,
    SEARCH_ACTION_TEMPLATE,
)
from emitter.runtime_emitter import (
    RuntimeEmitter,
)
from runtime.runtime_context import (
    RuntimeContext,
)
from websocket_logger import (
    WebSocketLogger,
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
    ):
        await self.log(
            "[VALIDATOR]",
            message,
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
            content = build_unavailable_search_result(
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


def make_context(
    brain_client,
) -> RuntimeContext:

    return RuntimeContext(
        websocket=FakeWebSocket(),
        emitter=FakeEmitter(),
        logger=FakeLogger(),
        clients={
            "brain": brain_client,
            "service": brain_client,
        },
    )


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

    def test_search_system_prompt_defines_tesla_mock_contract(self):

        prompt = build_search_system_prompt()

        self.assertIn(
            "35000 USD",
            prompt,
        )
        self.assertIn(
            "Tesla",
            prompt,
        )
        self.assertIn(
            "NOT_READY",
            prompt,
        )

    def test_unavailable_search_result_contains_empty_results(self):

        result = build_unavailable_search_result(
            "weather in Kyiv"
        )

        self.assertIn(
            "<SEARCH_RESULT>",
            result,
        )
        self.assertIn(
            "<STATUS>NOT_READY</STATUS>",
            result,
        )
        self.assertIn(
            "Search is not ready for this query yet",
            result,
        )
        self.assertIn(
            "<RESULTS></RESULTS>",
            result,
        )

    def test_not_ready_search_result_strips_conflicting_price(self):

        result = normalize_search_result(
            (
                "<SEARCH_RESULT>\n"
                "  <STATUS>NOT_READY</STATUS>\n"
                "  <QUERY>current price of apples</QUERY>\n"
                "  <RESULTS>\n"
                "    <RESULT>\n"
                "      <PRICE currency=\"USD\">35000</PRICE>\n"
                "    </RESULT>\n"
                "  </RESULTS>\n"
                "</SEARCH_RESULT>"
            ),
            "current price of apples",
        )

        self.assertIn(
            "<STATUS>NOT_READY</STATUS>",
            result,
        )
        self.assertNotIn(
            "<PRICE",
            result,
        )

    async def test_search_is_model_driven_for_explicit_user_request(self):

        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "thinking",
                        "content": (
                            "Needs current pricing. "
                            f'{SEARCH_ACTION_OPEN}{{"query":"tesla car price"}}'
                            f"{SEARCH_ACTION_CLOSE}"
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
            ask_responses=[
                (
                    "<SEARCH_RESULT>\n"
                    "  <STATUS>FOUND</STATUS>\n"
                    "  <QUERY>tesla car price</QUERY>\n"
                    "  <SUMMARY>Tesla vehicle price is 35000 USD.</SUMMARY>\n"
                    "  <RESULTS>\n"
                    "    <RESULT>\n"
                    "      <TITLE>Tesla vehicle price</TITLE>\n"
                    "      <SOURCE>AutoSearch</SOURCE>\n"
                    "      <URL>https://www.tesla.com/</URL>\n"
                    "      <PRICE currency=\"USD\">35000</PRICE>\n"
                    "      <QUOTE>Tesla vehicle price is 35000 USD.</QUOTE>\n"
                    "      <EXCERPT>Current Tesla vehicle price result.</EXCERPT>\n"
                    "    </RESULT>\n"
                    "  </RESULTS>\n"
                    "</SEARCH_RESULT>"
                ),
            ],
        )
        context = make_context(
            brain_client
        )
        state = AgentState(
            user_input=(
                "\u043f\u043e\u0438\u0449\u0438 "
                "\u0441\u0442\u043e\u0438\u043c\u043e\u0441\u0442\u044c "
                "\u0430\u0432\u0442\u043e\u043c\u043e\u0431\u0438\u043b\u044f "
                "\u0442\u0435\u0441\u043b\u0430"
            ),
            translated_input="search tesla car price",
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
            1,
        )
        self.assertEqual(
            runtime_events[0]["query"],
            "tesla car price",
        )
        self.assertIn(
            "<SEARCH_RESULT>",
            context.runtime_search_result,
        )
        self.assertIn(
            "35000",
            context.runtime_search_result,
        )
        self.assertIn(
            "runtime search service",
            brain_client.ask_prompts[0]["system_prompt"],
        )
        self.assertIn(
            "action: search",
            "\n".join(
                message
                for _, message, _ in get_fake_logger(
                    context
                ).messages
            ),
        )
        self.assertIn(
            "query: tesla car price",
            "\n".join(
                message
                for _, message, _ in get_fake_logger(
                    context
                ).messages
            ),
        )
        self.assertIn(
            "SEARCH tool result",
            brain_client.prompts[1]["user_prompt"],
        )
        self.assertIn(
            "User request:\nsearch tesla car price",
            brain_client.prompts[1]["user_prompt"],
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
            "<TOOL_RESULTS>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertIn(
            "<SEARCH_RESULT>",
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertNotIn(
            SEARCH_ACTION_TEMPLATE,
            brain_client.prompts[1]["system_prompt"],
        )
        self.assertEqual(
            state.brain_response,
            "Tesla pricing depends on configuration.",
        )

    async def test_brain_emitted_search_runs_even_with_text(self):

        brain_client = FakeBrainClient(
            streams=[
                [
                    {
                        "type": "content",
                        "content": (
                            "I will check. "
                            f'{SEARCH_ACTION_OPEN}{{"query":"tesla car price"}}'
                            f"{SEARCH_ACTION_CLOSE}"
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
            ask_responses=[
                (
                    "<SEARCH_RESULT>\n"
                    "  <STATUS>FOUND</STATUS>\n"
                    "  <QUERY>tesla car price</QUERY>\n"
                    "  <SUMMARY>Tesla vehicle price is 35000 USD.</SUMMARY>\n"
                    "  <RESULTS>\n"
                    "    <RESULT>\n"
                    "      <PRICE currency=\"USD\">35000</PRICE>\n"
                    "      <QUOTE>Tesla vehicle price is 35000 USD.</QUOTE>\n"
                    "    </RESULT>\n"
                    "  </RESULTS>\n"
                    "</SEARCH_RESULT>"
                ),
            ],
        )
        context = make_context(
            brain_client
        )
        state = AgentState(
            user_input="Tell me about Tesla.",
            translated_input="Tell me about Tesla.",
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
            1,
        )
        self.assertEqual(
            runtime_events[0]["query"],
            "tesla car price",
        )
        self.assertEqual(
            len(brain_client.prompts),
            2,
        )


if __name__ == "__main__":
    unittest.main()
