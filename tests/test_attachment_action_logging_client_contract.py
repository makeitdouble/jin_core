from pathlib import Path


def test_attachment_action_logger_keeps_instances_and_hides_restore_replay():
    source = (
        Path(__file__).parents[1]
        / "ui"
        / "static"
        / "js"
        / "logger"
        / "log-entries.js"
    ).read_text(encoding="utf-8")

    assert '"ATTACH_FILE",' in source
    assert '"DETACH_FILE",' in source
    assert "if (data.restore_replay === true)" in source
    assert "attachmentFailureDetail" in source
    assert "FAILED: ${attachmentFailureDetail}" in source


def test_dispatcher_tags_restore_replay_runtime_events():
    source = (
        Path(__file__).parents[1]
        / "utils"
        / "actions"
        / "dispatcher.py"
    ).read_text(encoding="utf-8")

    assert '"runtime_session_restore_replay_in_progress"' in source
    assert 'enriched_payload["restore_replay"] = True' in source
