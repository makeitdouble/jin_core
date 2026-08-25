import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from utils.actions import RuntimeActionCall
from utils.actions.jin_visual_sequence_actions import (
    emit_jin_visual_sequences,
)


class _Emitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def test_jin_color_action_is_persisted_for_log_bootstrap():
    async def run_case():
        emitter = _Emitter()
        context = SimpleNamespace(
            emitter=emitter,
            runtime_current_turn_id="turn-color-persist",
        )
        action = RuntimeActionCall(
            name="JIN_COLOR",
            payload="#00ff00",
        )

        async def log_runtime(_message):
            return None

        with patch(
            "utils.actions.jin_visual_sequence_actions.append_chat_runtime_event"
        ) as append_event:
            await emit_jin_visual_sequences(
                context,
                [action],
                action_display_ids={id(action): "color-action"},
                log_runtime=log_runtime,
                with_action_context=lambda event: event,
            )

        assert len(emitter.events) == 1
        append_event.assert_called_once()
        kwargs = append_event.call_args.kwargs
        assert kwargs["event"] == "runtime_action_request"
        assert kwargs["payload"]["action"] == "JIN_COLOR"
        assert kwargs["payload"]["color"] == "#00ff00"
        assert kwargs["payload"]["event_id"].startswith("jin-")
        assert (
            kwargs["payload"]["session_action"]["id"]
            == kwargs["payload"]["event_id"]
        )
        assert (
            kwargs["payload"]["session_action"]["parts"][0]["colors"]
            == ["#00ff00"]
        )

    asyncio.run(run_case())


def test_jin_color_log_failure_is_visible_without_blocking_ui_event():
    async def run_case():
        emitter = _Emitter()
        context = SimpleNamespace(
            emitter=emitter,
            runtime_current_turn_id="turn-color-log-failure",
        )
        action = RuntimeActionCall(
            name="JIN_COLOR",
            payload="#ff0000",
        )

        with (
            patch(
                "utils.actions.jin_visual_sequence_actions.append_chat_runtime_event",
                side_effect=OSError("disk full"),
            ),
            patch(
                "utils.actions.jin_visual_sequence_actions.LOGGER.exception"
            ) as log_exception,
        ):
            await emit_jin_visual_sequences(
                context,
                [action],
                action_display_ids={id(action): "color-action"},
                log_runtime=None,
                with_action_context=lambda event: event,
            )

        assert len(emitter.events) == 1
        log_exception.assert_called_once()

    asyncio.run(run_case())
