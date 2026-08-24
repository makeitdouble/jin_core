import json
from pathlib import Path
from unittest.mock import patch

from utils.session_restore import find_latest_completed_session_restore_payload
from websocket.bootstrap import enrich_session_bootstrap_from_archive


def _write_dialog(root: Path, session_id: str, name: str, rows: list[dict]) -> None:
    directory = root / "2026-08-24" / session_id
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in rows),
        encoding="utf-8",
    )


def test_latest_completed_selector_ignores_newer_blank_boot_session(tmp_path):
    old_session = "old-session"
    fresh_session = "fresh-session"
    blank_session = "blank-session"

    _write_dialog(tmp_path, old_session, "190000", [
        {"ts": "2026-08-24T19:00:00+03:00", "turn": 10, "role": "user", "text": "old user"},
        {"ts": "2026-08-24T19:00:10+03:00", "turn": 10, "role": "jin", "text": "old jin"},
    ])
    _write_dialog(tmp_path, fresh_session, "192134", [
        {"ts": "2026-08-24T19:21:56+03:00", "turn": 265, "role": "user", "text": "напиши быстро тест"},
        {"ts": "2026-08-24T19:22:53+03:00", "turn": 265, "role": "jin", "text": "Тест пройден"},
    ])
    _write_dialog(tmp_path, blank_session, "192328", [
        {"ts": "2026-08-24T19:23:35+03:00", "turn": 264, "role": "jin", "text": ""},
    ])

    payload = find_latest_completed_session_restore_payload(root=tmp_path)

    assert payload is not None
    assert payload["source_session_id"] == fresh_session
    assert payload["recent_turns"][-1]["user"] == "напиши быстро тест"
    assert payload["recent_turns"][-1]["jin"] == "Тест пройден"


def test_mode_specific_selector_uses_separate_log_roots(tmp_path):
    normal_root = tmp_path / "logs"
    anonymous_root = tmp_path / "logs_anon"
    normal_session = "normal-session"
    anonymous_session = "anonymous-session"

    _write_dialog(normal_root, normal_session, "195000", [
        {"ts": "2026-08-24T19:50:00+03:00", "turn": 1, "role": "user", "text": "normal user"},
        {"ts": "2026-08-24T19:50:10+03:00", "turn": 1, "role": "jin", "text": "normal jin"},
    ])
    _write_dialog(anonymous_root, anonymous_session, "195500", [
        {"ts": "2026-08-24T19:55:00+03:00", "turn": 2, "role": "user", "text": "anonymous user"},
        {"ts": "2026-08-24T19:55:10+03:00", "turn": 2, "role": "jin", "text": "anonymous jin"},
    ])

    with (
        patch("utils.chat_log.CHAT_LOG_ROOT", normal_root),
        patch("utils.chat_log.CHAT_LOG_ANON_ROOT", anonymous_root),
    ):
        normal_payload = find_latest_completed_session_restore_payload(
            anonymous_mode=False,
        )
        anonymous_payload = find_latest_completed_session_restore_payload(
            anonymous_mode=True,
        )

    assert normal_payload is not None
    assert normal_payload["source_session_id"] == normal_session
    assert normal_payload["recent_turns"][-1]["user"] == "normal user"
    assert anonymous_payload is not None
    assert anonymous_payload["source_session_id"] == anonymous_session
    assert anonymous_payload["recent_turns"][-1]["user"] == "anonymous user"


def test_normal_bootstrap_never_reads_newer_anonymous_log_root(tmp_path):
    normal_root = tmp_path / "logs"
    anonymous_root = tmp_path / "logs_anon"
    normal_session = "normal-source"
    anonymous_session = "anonymous-newer"

    _write_dialog(normal_root, normal_session, "195000", [
        {"ts": "2026-08-24T19:50:00+03:00", "turn": 1, "role": "user", "text": "normal user"},
        {"ts": "2026-08-24T19:50:10+03:00", "turn": 1, "role": "jin", "text": "normal jin"},
    ])
    _write_dialog(anonymous_root, anonymous_session, "195500", [
        {"ts": "2026-08-24T19:55:00+03:00", "turn": 2, "role": "user", "text": "anonymous user"},
        {"ts": "2026-08-24T19:55:10+03:00", "turn": 2, "role": "jin", "text": "anonymous jin"},
    ])

    with (
        patch("utils.chat_log.CHAT_LOG_ROOT", normal_root),
        patch("utils.chat_log.CHAT_LOG_ANON_ROOT", anonymous_root),
    ):
        enriched = enrich_session_bootstrap_from_archive(
            {
                "type": "session_bootstrap",
                "source_session_id": normal_session,
                "runtime_memory": "browser normal runtime",
            },
            anonymous_mode=False,
        )

    assert enriched["source_session_id"] == normal_session
    assert enriched["recent_turns"][-1]["user"] == "normal user"
    assert enriched["recent_turns"][-1]["jin"] == "normal jin"


def test_bootstrap_replaces_stale_source_with_newer_complete_raw_session():
    stale = {
        "source_session_id": "stale-session",
        "recent_turns": [{
            "user": "old user",
            "jin": "old jin",
            "user_created_at": 100.0,
            "jin_created_at": 101.0,
        }],
        "dialog_context": "<RESTORED_SESSION_DIALOG>old</RESTORED_SESSION_DIALOG>",
    }
    fresh = {
        "source_session_id": "fresh-session",
        "recent_turns": [{
            "user": "напиши быстро тест",
            "jin": "Тест пройден",
            "user_created_at": 200.0,
            "jin_created_at": 201.0,
        }],
        "dialog_context": "<RESTORED_SESSION_DIALOG>fresh</RESTORED_SESSION_DIALOG>",
    }

    with (
        patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=stale,
        ),
        patch(
            "utils.session_restore.find_latest_completed_session_restore_payload",
            return_value=fresh,
        ),
    ):
        enriched = enrich_session_bootstrap_from_archive({
            "type": "session_bootstrap",
            "source_session_id": "stale-session",
            "recent_turns": stale["recent_turns"],
            "runtime_memory": "browser runtime",
        })

    assert enriched["source_session_id"] == "fresh-session"
    assert enriched["recent_turns"] == fresh["recent_turns"]
    assert enriched["dialog_context"] == fresh["dialog_context"]


def test_bootstrap_does_not_override_browser_dialogue_that_is_newer_than_raw_log():
    requested = {
        "source_session_id": "requested-session",
        "recent_turns": [{
            "user": "archive user",
            "jin": "archive jin",
            "user_created_at": 100.0,
            "jin_created_at": 101.0,
        }],
    }
    latest_raw = {
        "source_session_id": "other-session",
        "recent_turns": [{
            "user": "other user",
            "jin": "other jin",
            "user_created_at": 200.0,
            "jin_created_at": 201.0,
        }],
    }
    browser_turns = [{
        "user": "browser user",
        "jin": "browser jin",
        "user_created_at": 300.0,
        "jin_created_at": 301.0,
    }]

    with (
        patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=requested,
        ),
        patch(
            "utils.session_restore.find_latest_completed_session_restore_payload",
            return_value=latest_raw,
        ),
    ):
        enriched = enrich_session_bootstrap_from_archive({
            "type": "session_bootstrap",
            "source_session_id": "requested-session",
            "recent_turns": browser_turns,
            "runtime_memory": "browser runtime",
        })

    assert enriched["source_session_id"] == "requested-session"
    assert enriched["recent_turns"] == browser_turns


def test_latest_selector_accepts_committed_user_only_action_turn(tmp_path):
    previous_session = "previous-complete"
    action_session = "action-only"

    _write_dialog(tmp_path, previous_session, "200000", [
        {"ts": "2026-08-24T20:00:00+03:00", "turn": 1, "role": "user", "text": "напиши быстро тест"},
        {"ts": "2026-08-24T20:00:10+03:00", "turn": 1, "role": "jin", "text": "Тест готов"},
    ])
    _write_dialog(tmp_path, action_session, "200500", [
        {"ts": "2026-08-24T20:05:00+03:00", "turn": 2, "role": "user", "text": "поставь себе вечерний цвет и громадный размер"},
        # Marker/action response was consumed by runtime and leaves no visible
        # answer, but this row proves runtime.run completed the turn.
        {"ts": "2026-08-24T20:05:05+03:00", "turn": 2, "role": "jin", "text": ""},
    ])

    payload = find_latest_completed_session_restore_payload(root=tmp_path)

    assert payload is not None
    assert payload["source_session_id"] == action_session
    assert payload["messages"][-1]["role"] == "user"
    assert payload["messages"][-1]["text"] == "поставь себе вечерний цвет и громадный размер"
    assert payload["recent_turns"][-1]["user"] == "поставь себе вечерний цвет и громадный размер"
    assert payload["recent_turns"][-1]["jin"] == ""


def test_latest_selector_ignores_unfinished_bare_user_turn(tmp_path):
    complete_session = "complete"
    interrupted_session = "interrupted"

    _write_dialog(tmp_path, complete_session, "201000", [
        {"ts": "2026-08-24T20:10:00+03:00", "turn": 1, "role": "user", "text": "complete user"},
        {"ts": "2026-08-24T20:10:05+03:00", "turn": 1, "role": "jin", "text": "complete jin"},
    ])
    _write_dialog(tmp_path, interrupted_session, "201500", [
        {"ts": "2026-08-24T20:15:00+03:00", "turn": 2, "role": "user", "text": "in flight"},
    ])

    payload = find_latest_completed_session_restore_payload(root=tmp_path)

    assert payload is not None
    assert payload["source_session_id"] == complete_session
    assert payload["recent_turns"][-1]["jin"] == "complete jin"
