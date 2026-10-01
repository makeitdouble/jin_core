import asyncio
from types import SimpleNamespace
from unittest.mock import patch

from utils.actions import RuntimeActionCall
from utils.actions.action_counter_utils import RuntimeActionCounter
from utils.session_actions_history import (
    emit_session_actions_update,
    replace_session_action_history_since,
)
from utils.session_restore import (
    _build_runtime_event_session_actions,
    _build_session_actions,
    _runtime_tool_result_timestamp_queues,
)


class _Emitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def test_marker_history_keeps_action_observation_timestamp():
    counter = RuntimeActionCounter()
    action = RuntimeActionCall(
        name="CHAT_LOG_SEARCH",
        payload='{"query":"pizza"}',
    )

    with patch(
        "utils.actions.action_counter_utils.time.time",
        return_value=1234.5,
    ):
        counter.record([action])

    context = SimpleNamespace(
        session_id="session-a",
        runtime_current_turn_id="turn-a",
        runtime_session_action_history=[],
        runtime_action_events=[],
    )

    with patch(
        "utils.session_actions_history.time.time",
        return_value=9999.0,
    ):
        replace_session_action_history_since(
            context,
            0,
            counter.marker_actions(),
        )

    assert context.runtime_session_action_history[0]["created_at"] == 1234.5


def test_non_payload_distinct_marker_keeps_action_observation_timestamp():
    counter = RuntimeActionCounter()
    action = RuntimeActionCall(
        name="JIN_COLOR",
        payload="#ff0000",
    )

    with patch(
        "utils.actions.action_counter_utils.time.time",
        return_value=333.0,
    ):
        counter.record([action])

    context = SimpleNamespace(
        session_id="session-a",
        runtime_current_turn_id="turn-a",
        runtime_session_action_history=[],
        runtime_action_events=[],
    )

    with patch(
        "utils.session_actions_history.time.time",
        return_value=9999.0,
    ):
        replace_session_action_history_since(
            context,
            0,
            counter.marker_actions(),
        )

    assert context.runtime_session_action_history[0]["created_at"] == 333.0


def test_final_session_actions_snapshot_preserves_item_timestamps():
    emitter = _Emitter()
    context = SimpleNamespace(
        session_id="session-a",
        runtime_current_turn_id="turn-a",
        runtime_session_action_history=[{
            "text": "CHAT_LOG_SEARCH: pizza",
            "created_at": 1234.5,
            "session_id": "session-a",
            "parts": [{"text": "CHAT_LOG_SEARCH: pizza"}],
        }],
        emitter=emitter,
    )

    with patch("utils.chat_log.append_chat_runtime_event") as append_event:
        asyncio.run(
            emit_session_actions_update(
                context,
                current_sequence=False,
            )
        )

    append_event.assert_called_once()
    kwargs = append_event.call_args.kwargs
    assert kwargs["event"] == "session_actions_snapshot"
    assert kwargs["payload"]["items"][0]["created_at"] == 1234.5


def test_live_sequence_updates_do_not_write_full_history_snapshots():
    emitter = _Emitter()
    context = SimpleNamespace(
        session_id="session-a",
        runtime_current_turn_id="turn-a",
        runtime_current_sequence_turn_id="turn-a",
        runtime_session_action_history=[{
            "text": "CHAT_LOG_SEARCH: pizza",
            "created_at": 1234.5,
            "session_id": "session-a",
            "runtime_turn_id": "turn-a",
            "parts": [{"text": "CHAT_LOG_SEARCH: pizza"}],
        }],
        emitter=emitter,
    )

    with patch("utils.chat_log.append_chat_runtime_event") as append_event:
        asyncio.run(
            emit_session_actions_update(
                context,
                current_sequence=True,
            )
        )

    append_event.assert_not_called()


def test_restore_uses_latest_generic_session_action_snapshot():
    entries = [{
        "ts": "2026-09-10T10:00:00+03:00",
        "turn_id": "turn-a",
        "event": "session_actions_snapshot",
        "payload": {
            "items": [
                {
                    "text": "CHAT_LOG_SEARCH: pizza",
                    "created_at": 111.0,
                    "parts": [{"text": "CHAT_LOG_SEARCH: pizza"}],
                },
                {
                    "text": "ATTACH_FILE_CONTENT: source.py",
                    "created_at": 222.0,
                    "parts": [{"text": "ATTACH_FILE_CONTENT", "detail": "source.py"}],
                },
            ]
        },
    }]

    restored = _build_runtime_event_session_actions(entries)

    assert [item["created_at"] for item in restored] == [111.0, 222.0]
    assert [item["text"] for item in restored] == [
        "CHAT_LOG_SEARCH: pizza",
        "ATTACH_FILE_CONTENT: source.py",
    ]


def test_legacy_tool_result_action_uses_raw_runtime_event_timestamp():
    entries = [{
        "ts": "2026-09-10T10:00:00+03:00",
        "event": "runtime_tool_result",
        "payload": {
            "kind": "runtime_action",
            "id": "chat_search_001",
            "tool_id": "T7",
            "created_at": 1234.5,
            "result": {
                "ok": True,
                "action": "CHAT_LOG_SEARCH",
                "payload": '{"query":"pizza"}',
            },
        },
    }]
    context_text = (
        '<TOOL_RESULT tool_id="T7" name="CHAT_LOG_SEARCH" '
        'id="chat_search_001">\n'
        '{"ok":true,"action":"CHAT_LOG_SEARCH","payload":"pizza"}\n'
        '</TOOL_RESULT>'
    )

    restored = _build_session_actions(
        context_text,
        9999.0,
        runtime_tool_result_created_ats=(
            _runtime_tool_result_timestamp_queues(entries)
        ),
    )

    assert restored[0]["created_at"] == 1234.5
