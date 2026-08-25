from pathlib import Path
from unittest.mock import patch

from websocket.bootstrap import enrich_session_bootstrap_from_archive


ROOT = Path(__file__).resolve().parents[1]
MESSAGES_PY = ROOT / "websocket" / "messages.py"
STREAM_PY = ROOT / "runtime" / "stream.py"
HANDLERS_JS = ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"


def test_visible_message_end_carries_current_turn_bootstrap_preview():
    stream_source = STREAM_PY.read_text(encoding="utf-8")

    assert "def build_message_end_checkpoint_payload" in stream_source
    assert '"session_snapshot": session_snapshot' in stream_source
    assert "end_payload_builder=(" in stream_source
    assert "self.build_message_end_checkpoint_payload" in stream_source

    source = MESSAGES_PY.read_text(encoding="utf-8")
    start = source.index("async def process_message(")
    block = source[start:]
    recent_index = block.index("append_runtime_recent_turn(")
    agent_end_index = block.index('"type": "agent_runtime_end"')
    assert recent_index < agent_end_index
    assert '"session_snapshot": completed_session_snapshot' in block


def test_message_end_persists_bootstrap_checkpoint_before_finishing_bubble():
    source = HANDLERS_JS.read_text(encoding="utf-8")
    start = source.index("function handleMessageEnd(")
    end = source.index("function handleMessageError(", start)
    block = source[start:end]

    persist_index = block.index("persistLiveSessionCheckpoint")
    finish_index = block.index("finishStreamMessage(")

    assert "data.session_snapshot" in block
    assert persist_index < finish_index


def test_archive_dialogue_freshness_is_not_blocked_by_newer_runtime_saved_at():
    archived = {
        "source_session_id": "source-session",
        "archive_tail_at": "2026-08-24T18:20:00+03:00",
        "recent_turns": [
            {
                "user": "new user",
                "jin": "new jin",
                "user_created_at": 200.0,
                "jin_created_at": 201.0,
            },
        ],
        "dialog_context": "<RESTORED_SESSION_DIALOG>new</RESTORED_SESSION_DIALOG>",
        "previous_reasoning": "new reasoning",
        "session_actions": [{"id": "archive-action"}],
    }

    with patch(
        "utils.session_restore.build_archived_session_restore_payload",
        return_value=archived,
    ):
        enriched = enrich_session_bootstrap_from_archive(
            {
                "type": "session_bootstrap",
                "source_session_id": "source-session",
                # This runtime snapshot is newer than the raw archive tail, but
                # its copied dialogue is older. Dialogue must still advance.
                "saved_at": "2026-08-24T18:30:00+03:00",
                "recent_turns": [
                    {
                        "user": "old user",
                        "jin": "old jin",
                        "user_created_at": 100.0,
                        "jin_created_at": 101.0,
                    },
                ],
                "session_actions": [{"id": "browser-action"}],
                "runtime_memory": "current runtime",
            }
        )

    assert enriched["recent_turns"] == archived["recent_turns"]
    assert enriched["previous_reasoning"] == "new reasoning"
    # The atomic checkpoint owns actions committed before saved_at. Only a raw
    # action with a strictly newer created_at may extend this list.
    assert enriched["session_actions"] == [{"id": "browser-action"}]


def test_agent_runtime_end_commits_user_only_completed_turn_checkpoint():
    source = MESSAGES_PY.read_text(encoding="utf-8")
    start = source.index("async def process_message(")
    block = source[start:]
    agent_end_index = block.index('"type": "agent_runtime_end"')
    preceding = block[:agent_end_index]

    assert "completed_turn_commit = bool(" in preceding
    assert 'and str(user_text or "").strip()' in preceding
    assert '"completed_turn_commit": completed_turn_commit' in block[agent_end_index:]

    handler_source = HANDLERS_JS.read_text(encoding="utf-8")
    start = handler_source.index("function handleAgentRuntimeEnd(data)")
    end = handler_source.index("function handleMessageStart(", start)
    handler = handler_source[start:end]

    assert "completed_turn_commit: Boolean(" in handler
    assert "data.completed_turn_commit === true" in handler
