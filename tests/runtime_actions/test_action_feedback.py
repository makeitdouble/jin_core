from utils.actions import RuntimeActionCall
from utils.actions.action_registry import apply_action_feedback


def test_running_event_shows_only_action_name():
    event = apply_action_feedback(
        RuntimeActionCall(name="JIN_COLOR", payload="#ff0000"),
        {"type": "runtime_action", "action": "jin_color", "status": "running", "text": "old"},
    )
    assert event["text"] == "JIN_COLOR"


def test_default_success_uses_full_string_payload():
    event = apply_action_feedback(
        RuntimeActionCall(name="JIN_COLOR", payload="#ff0000"),
        {"type": "runtime_action", "action": "jin_color", "status": "completed"},
    )
    assert event["text"] == "JIN_COLOR: #ff0000"


def test_default_success_formats_mapping_payload():
    event = apply_action_feedback(
        RuntimeActionCall(name="JIN_POSITION", payload={"x": 10, "y": 20}),
        {"type": "runtime_action", "action": "jin_position", "status": "completed"},
    )
    assert event["text"] == "JIN_POSITION: x: 10, y: 20"


def test_clean_tool_results_success_keeps_emitted_summary_out_of_event_context():
    event = apply_action_feedback(
        RuntimeActionCall(name="CLEAN_TOOL_RESULTS", payload=""),
        {
            "type": "runtime_action",
            "action": "clean_tool_results",
            "status": "completed",
            "text": "All tool results cleared",
            "context": {
                "system_prompt": "PRIVATE SYSTEM PROMPT",
                "user_prompt": "PRIVATE USER PROMPT",
            },
        },
    )

    assert event["text"] == "All tool results cleared"
    assert "PRIVATE SYSTEM PROMPT" not in event["text"]
    assert "PRIVATE USER PROMPT" not in event["text"]


def test_clean_tool_results_failure_keeps_emitted_failure_summary():
    event = apply_action_feedback(
        RuntimeActionCall(name="CLEAN_TOOL_RESULTS", payload="T404"),
        {
            "type": "runtime_action",
            "action": "clean_tool_results",
            "status": "failed",
            "text": "Unknown or invalid tool_id list: T404",
            "context": {"system_prompt": "PRIVATE SYSTEM PROMPT"},
        },
    )

    assert event["text"] == "Unknown or invalid tool_id list: T404"


def test_jin_size_success_uses_normalized_size_message():
    event = apply_action_feedback(
        RuntimeActionCall(name="JIN_SIZE", payload="150 100"),
        {"type": "runtime_action", "action": "jin_size", "status": "completed"},
    )
    assert event["text"] == "JIN_SIZE: w:150px h:100px"


def test_default_fail_uses_payload_but_keeps_failed_status():
    event = apply_action_feedback(
        RuntimeActionCall(name="JIN_COLOR", payload="#ff0000"),
        {"type": "runtime_action", "action": "jin_color", "status": "failed", "error": "boom"},
    )
    assert event["status"] == "failed"
    assert event["text"] == "JIN_COLOR: #ff0000"
