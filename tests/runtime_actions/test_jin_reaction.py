import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from clients.brain_client import ask_brain_stream
from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_REACTION,
    build_runtime_action_contract_instructions,
    get_runtime_action_private_marker,
)
from tests.helpers.runtime_actions import FakeEmitter
from utils.actions import (
    RuntimeActionCall,
    extract_runtime_actions,
    normalize_jin_reaction_payload,
    strip_jin_reaction_markers,
)
from utils.actions.dispatcher import apply_runtime_action_calls
from utils.context.session_actions import build_session_actions_history_context
from utils.session_actions_history import replace_session_action_history_since


class RuntimeJinReactionActionTests(unittest.TestCase):

    def test_contract_exposes_single_emoji_reaction_marker(self):
        self.assertEqual(
            get_runtime_action_private_marker(
                RUNTIME_ACTION_JIN_REACTION
            ),
            "<JIN_REACTION: 😂 >",
        )

        instructions = build_runtime_action_contract_instructions(
            RUNTIME_ACTION_JIN_REACTION
        )
        self.assertIn(
            "using one emoji of its choice",
            instructions,
        )
        self.assertIn(
            "at most one reaction per answer",
            instructions,
        )

    def test_jin_reaction_marker_parses_and_is_removed_from_text(self):
        result = extract_runtime_actions(
            "before <JIN_REACTION: 😂 > after",
            enabled_actions=(
                RUNTIME_ACTION_JIN_REACTION,
            ),
        )

        self.assertEqual(
            result.text,
            "before after",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_REACTION,
                    payload="😂",
                ),
            ),
        )

    def test_jin_reaction_marker_can_stay_in_stream_and_still_execute(self):
        marker = "<JIN_REACTION: 😂 >"
        result = extract_runtime_actions(
            f"before {marker} after",
            enabled_actions=(
                RUNTIME_ACTION_JIN_REACTION,
            ),
            preserve_action_marker=(
                lambda _raw_marker, action:
                action.name == RUNTIME_ACTION_JIN_REACTION
            ),
        )

        self.assertEqual(
            result.text,
            f"before {marker} after",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_REACTION,
                    payload="😂",
                ),
            ),
        )
        self.assertEqual(
            result.removed_markers,
            (),
        )

    def test_quoted_jin_reaction_marker_remains_literal(self):
        text = 'example: "<JIN_REACTION: 😂 >"'
        result = extract_runtime_actions(
            text,
            enabled_actions=(
                RUNTIME_ACTION_JIN_REACTION,
            ),
        )

        self.assertEqual(
            result.text,
            text,
        )
        self.assertEqual(
            result.actions,
            (),
        )
        self.assertEqual(
            strip_jin_reaction_markers(text),
            text,
        )

    def test_jin_reaction_requires_one_unicode_emoji_cluster(self):
        for value in (
            "😂",
            "❤️",
            "👍🏽",
            "👨‍👩‍👧‍👦",
            "🇺🇦",
            "1️⃣",
            "↔️",
            "‼️",
            "ℹ️",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_jin_reaction_payload(value),
                    value,
                )

        for value in (
            "",
            "abc",
            "😂😂",
            "😂 hi",
        ):
            with self.subTest(value=value):
                self.assertEqual(
                    normalize_jin_reaction_payload(value),
                    "",
                )

    def test_brain_client_defers_reaction_to_visible_runtime_stream(self):
        class FakeBrainClient:
            async def stream(self, **_kwargs):
                yield {
                    "content": "before <JIN_REACTION: \U0001f602 > after",
                }

        async def run_case():
            context = SimpleNamespace(
                runtime_loaded_skills=[],
                runtime_session_action_history=[],
                runtime_action_events=[],
                runtime_current_turn_id="turn-reaction",
                logger=None,
                emitter=None,
            )
            applied_actions = []

            async def capture_apply(*_args, **kwargs):
                applied_actions.extend(
                    kwargs.get("actions", ())
                    or ()
                )
                if len(_args) >= 2:
                    applied_actions.extend(_args[1] or ())
                return 0

            with patch(
                "clients.brain_client.prepare_current_context_window_prompt",
                new=AsyncMock(
                    return_value=SimpleNamespace(
                        system_prompt="system",
                    )
                ),
            ), patch(
                "clients.brain_client.apply_runtime_action_calls",
                new=capture_apply,
            ):
                chunks = []
                async for chunk in ask_brain_stream(
                    client=FakeBrainClient(),
                    text="hello",
                    context=context,
                    system_prompt="system",
                    brain_payload="hello",
                    runtime_actions={
                        "CAN_JIN_REACTION": True,
                    },
                ):
                    chunks.append(chunk)

            content = "".join(
                str(chunk.get("content", "") or "")
                for chunk in chunks
                if isinstance(chunk, dict)
            )
            self.assertIn(
                "<JIN_REACTION: \U0001f602 >",
                content,
            )
            self.assertFalse(
                any(
                    action.name == RUNTIME_ACTION_JIN_REACTION
                    for action in applied_actions
                )
            )

        asyncio.run(run_case())

    def test_session_actions_include_reaction_emoji_in_history_and_context(self):
        context = SimpleNamespace(
            runtime_session_action_history=[],
            runtime_action_events=[],
            runtime_current_turn_id="turn-reaction",
        )
        replace_session_action_history_since(
            context,
            0,
            (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_REACTION,
                    payload="\U0001f602",
                ),
            ),
        )

        self.assertEqual(
            context.runtime_session_action_history[0]["text"],
            "JIN_REACTION: \U0001f602",
        )
        self.assertIn(
            "JIN_REACTION: \U0001f602",
            build_session_actions_history_context(context),
        )

    def test_dispatcher_accepts_only_one_reaction_per_message(self):
        async def run_case():
            emitter = FakeEmitter()
            context = SimpleNamespace(
                runtime_action_events=[],
                runtime_current_turn_id="turn-reaction",
                logger=None,
                emitter=emitter,
            )
            actions = (
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_REACTION,
                    payload="😂",
                ),
                RuntimeActionCall(
                    name=RUNTIME_ACTION_JIN_REACTION,
                    payload="❤️",
                ),
            )

            applied_count = await apply_runtime_action_calls(
                context,
                actions,
                user_message="привет",
                runtime_message_id="message-reaction",
            )

            self.assertEqual(
                applied_count,
                1,
            )
            self.assertEqual(
                [
                    event.get("payload")
                    for event in context.runtime_action_events
                    if event.get("name") == "jin_reaction"
                ],
                ["😂"],
            )

            completed = [
                event
                for event in emitter.events
                if event.get("action") == "jin_reaction"
                and event.get("status") == "completed"
            ]
            self.assertEqual(
                len(completed),
                1,
            )
            self.assertEqual(
                completed[0].get("emoji"),
                "😂",
            )
            self.assertEqual(
                completed[0].get("runtime_message_id"),
                "message-reaction",
            )

        asyncio.run(run_case())


if __name__ == "__main__":
    unittest.main()
