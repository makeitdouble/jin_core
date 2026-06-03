import asyncio
import json
import os
import sys
import unittest
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(
    0,
    str(ROOT),
)

from agent import (
    AgentRuntime,
    AgentState,
)
from clients import (
    build_clients,
)
from runtime import (
    RuntimeContext,
    RuntimeEmitter,
    build_runtime_memory_snapshot,
    schedule_runtime_memory_update,
)
from websocket import (
    refresh_pending_brain_usage,
    wait_for_runtime_memory_update,
)
from websocket_logger import (
    WebSocketLogger,
)


# Fill these constants for the manual model-flow probe.
# Strings, multiline strings, and arrays of strings are supported.
QUESTION_1 = [
    "TODO: first user message",
]

ANSWER_1 = []

QUESTION_2 = [
    "TODO: second user message",
]

ANSWER_2 = []


RUN_MEMORY_UPDATE = True
WAIT_FOR_MEMORY_UPDATE = True


class CapturingWebSocket:

    def __init__(self):
        self.messages = []

    async def send_json(
        self,
        payload: dict,
    ):
        self.messages.append(
            payload
        )


def render_text(
    value: Any,
) -> str:

    if value is None:
        return ""

    if isinstance(
        value,
        str,
    ):
        return value.strip()

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        return "\n".join(
            render_text(item)
            for item in value
        ).strip()

    return str(
        value
    ).strip()


def expected_fragments(
    value: Any,
) -> list[str]:

    if value is None:
        return []

    if isinstance(
        value,
        str,
    ):
        fragment = value.strip()
        return (
            [fragment]
            if fragment
            else []
        )

    if isinstance(
        value,
        (
            list,
            tuple,
        ),
    ):
        fragments = []

        for item in value:
            fragments.extend(
                expected_fragments(
                    item
                )
            )

        return fragments

    fragment = str(
        value
    ).strip()

    return (
        [fragment]
        if fragment
        else []
    )


async def run_standard_turn(
    context: RuntimeContext,
    user_text: str,
) -> AgentState:

    await wait_for_runtime_memory_update(
        context
    )

    await refresh_pending_brain_usage(
        context,
        user_text,
    )

    context.runtime_turn_user_message = user_text
    context.runtime_turn_assistant_response = ""
    context.runtime_turn_interrupted = False
    context.user_message_count += 1

    if hasattr(
        context,
        "runtime_usage_events",
    ):
        context.runtime_usage_events.clear()
    else:
        context.runtime_usage_events = []

    state = AgentState(
        user_input=user_text
    )

    runtime = AgentRuntime()

    await context.logger.log_system(
        "[TEST] runtime=AgentRuntime"
    )

    await context.websocket.send_json({
        "type": "agent_runtime_start",
    })

    await runtime.run(
        state,
        context,
    )

    await context.websocket.send_json({
        "type": "agent_runtime_end",
    })

    assistant_message = (
        state.final_answer
        or state.brain_response
        or context.runtime_turn_assistant_response
    )

    if RUN_MEMORY_UPDATE:
        schedule_runtime_memory_update(
            context=context,
            user_message=user_text,
            assistant_message=assistant_message,
        )

        if WAIT_FOR_MEMORY_UPDATE:
            await wait_for_runtime_memory_update(
                context
            )

    context.assistant_message_count += 1
    context.turn_number += 1

    return state


def assert_expected_fragments(
    test_case: unittest.TestCase,
    *,
    answer: str,
    expected: Any,
):

    for fragment in expected_fragments(
        expected
    ):
        test_case.assertIn(
            fragment,
            answer,
        )


class TwoTurnFlowInputShapeTests(
    unittest.TestCase
):

    def test_render_text_supports_string_arrays_and_formatted_text(self):

        self.assertEqual(
            render_text(
                "plain text"
            ),
            "plain text",
        )

        self.assertEqual(
            render_text([
                "line one",
                "",
                [
                    "line two",
                    "line three",
                ],
            ]),
            "line one\n\nline two\nline three",
        )

        self.assertEqual(
            render_text(
                """
                formatted block

                with spacing
                """
            ),
            "formatted block\n\n                with spacing",
        )

    def test_expected_fragments_supports_string_and_arrays(self):

        self.assertEqual(
            expected_fragments(
                "one formatted fragment"
            ),
            [
                "one formatted fragment",
            ],
        )

        self.assertEqual(
            expected_fragments([
                "first",
                [
                    "second",
                    "",
                ],
            ]),
            [
                "first",
                "second",
            ],
        )


@unittest.skipUnless(
    os.getenv(
        "JIN_RUN_TWO_TURN_MODEL_FLOW",
        "",
    )
    == "1",
    "Set JIN_RUN_TWO_TURN_MODEL_FLOW=1 to run the two-turn model flow probe.",
)
class TwoTurnModelFlowTests(
    unittest.IsolatedAsyncioTestCase
):

    async def asyncSetUp(self):

        self.http_client = httpx.AsyncClient()
        self.websocket = CapturingWebSocket()

        self.context = RuntimeContext(
            websocket=self.websocket,
            emitter=RuntimeEmitter(
                self.websocket
            ),
            logger=WebSocketLogger(
                self.websocket
            ),
            clients=build_clients(
                self.http_client
            ),
        )

        initial_snapshot = build_runtime_memory_snapshot(
            self.context,
            self.context.runtime_memory,
        )

        self.context.runtime_memory_snapshots.append(
            initial_snapshot
        )

        self.context.runtime_memory_snapshot_index = 0

    async def asyncTearDown(self):

        await wait_for_runtime_memory_update(
            self.context
        )

        await self.http_client.aclose()

    async def test_question_answer_question_answer_flow(self):

        question_1 = render_text(
            QUESTION_1
        )
        question_2 = render_text(
            QUESTION_2
        )

        state_1 = await run_standard_turn(
            self.context,
            question_1,
        )
        answer_1 = (
            state_1.final_answer
            or state_1.brain_response
        )

        assert_expected_fragments(
            self,
            answer=answer_1,
            expected=ANSWER_1,
        )

        state_2 = await run_standard_turn(
            self.context,
            question_2,
        )
        answer_2 = (
            state_2.final_answer
            or state_2.brain_response
        )

        assert_expected_fragments(
            self,
            answer=answer_2,
            expected=ANSWER_2,
        )

        print(
            json.dumps(
                {
                    "question_1": question_1,
                    "answer_1": answer_1,
                    "question_2": question_2,
                    "answer_2": answer_2,
                    "runtime_memory": self.context.runtime_memory,
                    "runtime_l2_memory": self.context.runtime_l2_memory,
                    "turn_number": self.context.turn_number,
                    "user_message_count": self.context.user_message_count,
                    "assistant_message_count": self.context.assistant_message_count,
                    "websocket_message_count": len(
                        self.websocket.messages
                    ),
                },
                ensure_ascii=False,
                indent=2,
            )
        )


if __name__ == "__main__":
    unittest.main()
