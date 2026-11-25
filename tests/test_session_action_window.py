from types import SimpleNamespace
from unittest.mock import patch

from utils.context.session_actions import build_session_actions_history_context
from utils.tokens import estimate_tokens


def session_block(*entries):
    context = SimpleNamespace(runtime_session_action_history=entries)
    return build_session_actions_history_context(context)


def expected_block(lines):
    return "\n".join([
        "<SESSION_ACTIONS_HISTORY>",
        *("    " + line for line in lines),
        "</SESSION_ACTIONS_HISTORY>",
    ])


def test_short_history_keeps_all_entries_and_empty_history_has_no_block():
    assert session_block() == ""
    assert session_block("one", "two") == expected_block(["1. one", "2. two"])


def test_long_variable_size_history_keeps_maximal_chronological_suffix():
    entries = [f"action-{i}:" + "СЏ" * (i % 15) for i in range(600)]
    lines = [f"{i}. {entry}" for i, entry in enumerate(entries, 1)]
    start = len(lines) - 1
    while estimate_tokens(expected_block(lines[start - 1:])) <= 1024:
        start -= 1
    assert 0 < start < len(lines) - 1
    assert session_block(*entries) == expected_block(lines[start:])


def test_sequence_entry_fits_exactly_with_all_markup_or_is_omitted_whole():
    jin = "J" * 180
    payload = "&СЏ"
    lines = [
        "--- start of sequence ---",
        f"JIN: {jin[:147]}... ( 1s ago )",
        "2. &amp;СЏ ( 1s ago )",
        "--- end of sequence ---",
    ]
    padding = "x" * (4096 - len(expected_block(lines).encode()))
    lines[2] = f"2. &amp;СЏ{padding} ( 1s ago )"
    entry = dict(text=payload + padding, runtime_turn_id="turn", created_at=99,
                 jin_message_content=jin)
    ctx = SimpleNamespace(runtime_session_action_history=["older", entry],
                          runtime_action_sequence_turn_ids=["turn"])
    with patch("utils.context.session_actions.time.time", return_value=100):
        block = build_session_actions_history_context(ctx)
        assert estimate_tokens(block) == 1024
        assert block == expected_block(lines)
        entry["text"] += "x"
        assert build_session_actions_history_context(ctx) == ""


def test_window_stops_inside_sequence_and_rebuilds_its_jin_line_and_delimiters():
    def entry(text, turn):
        return dict(text=text, runtime_turn_id=turn, jin_message_content="shared")

    ctx = SimpleNamespace(
        runtime_action_sequence_turn_ids=["a", "b"],
        runtime_session_action_history=[
            "old", entry("x" * 4096, "a"), entry("kept", "a"), entry("next", "b"),
        ],
    )
    assert build_session_actions_history_context(ctx) == expected_block([
        "--- start of sequence ---", "JIN: shared", "3. kept", "--- end of sequence ---",
        "--- start of sequence ---", "JIN: shared", "4. next", "--- end of sequence ---",
    ])


def test_request_history_keeps_full_jin_message_beyond_session_budget():
    jin = "answer " * 800 + "end"
    ctx = SimpleNamespace(
        runtime_current_sequence_turn_id="active",
        runtime_action_sequence_turn_ids=["active"],
        runtime_session_action_history=[
            dict(text="older", runtime_turn_id="done"),
            dict(text="one", runtime_turn_id="active"),
            dict(text="two", runtime_turn_id="active", jin_message_content=jin),
        ],
    )
    assert build_session_actions_history_context(ctx) == expected_block([
        "1. older", "--- start of sequence ---", "2. one",
        f"JIN: {jin[:147].rstrip()}...", "3. two", "--- end of sequence ---",
    ])
    request = build_session_actions_history_context(ctx, current_sequence=True)
    assert estimate_tokens(request) > 1024
    assert request == (
        "<REQUEST_ACTIONS_HISTORY>\n"
        f"    1. one\n    JIN: {jin}\n    2. two\n"
        "</REQUEST_ACTIONS_HISTORY>"
    )
