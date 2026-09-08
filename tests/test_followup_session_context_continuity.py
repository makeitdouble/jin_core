import time

from agent.nodes.brain import BrainNode
from runtime.runtime_context import RuntimeContext
from utils.context.session_actions import build_session_actions_history_context


def _context_with_current_sequence():
    now = time.time()
    ctx = RuntimeContext(
        websocket=None,
        emitter=None,
        logger=None,
        clients={},
    )
    ctx.runtime_current_turn_id = "turn_2"
    ctx.runtime_current_sequence_turn_id = "turn_2"
    ctx.runtime_turn_started_at = now - 10
    ctx.runtime_current_sequence_started_at = now - 10
    ctx.runtime_action_sequence_turn_ids = ["turn_1"]
    ctx.runtime_session_action_history = [
        {
            "text": "WEB_SEARCH: old query",
            "created_at": now - 100,
            "runtime_turn_id": "turn_1",
            "jin_message_content": "old JIN text must stay hidden",
        },
        {
            "text": "STALE_SAME_TURN",
            "created_at": now - 30,
            "runtime_turn_id": "turn_2",
            "jin_message_content": "stale JIN text must stay hidden",
        },
        {
            "text": "ATTACH_FILE_CONTENT: jin_core/a.py",
            "created_at": now - 2,
            "runtime_turn_id": "turn_2",
            "jin_message_content": "Сейчас открою файл и проверю причину.",
        },
    ]
    return ctx


def test_followup_uses_only_current_sequence_without_quoting_request():
    ctx = _context_with_current_sequence()

    prompt = BrainNode.build_followup_system_prompt(
        "BASE SYSTEM",
        "проверь почему падает загрузка",
        context=ctx,
    )

    assert "<CURRENT_REQUEST_FLOW>" not in prompt
    assert "Current request:" not in prompt
    assert "--- Current sequence ---" not in prompt
    assert "<SESSION_ACTIONS_HISTORY>" not in prompt
    assert "WEB_SEARCH: old query" not in prompt
    assert "JIN: Сейчас открою файл и проверю причину." in prompt
    assert "old JIN text must stay hidden" not in prompt
    assert "stale JIN text must stay hidden" not in prompt

    block = prompt.split("<CURRENT_REQUEST_ACTIONS_HISTORY>", 1)[1].split(
        "</CURRENT_REQUEST_ACTIONS_HISTORY>", 1
    )[0]
    current_sequence = block
    assert "1. ATTACH_FILE_CONTENT:" in block
    assert "ATTACH_FILE_CONTENT: jin_core/a.py" in current_sequence
    assert "STALE_SAME_TURN" not in current_sequence


def test_current_sequence_filter_still_uses_sequence_start_time():
    ctx = _context_with_current_sequence()

    block = build_session_actions_history_context(
        ctx,
        current_sequence=True,
        sequence_user_message="проверь почему падает загрузка",
    )

    assert "проверь почему падает загрузка" not in block
    assert "ATTACH_FILE_CONTENT: jin_core/a.py" in block
    assert "STALE_SAME_TURN" not in block
    assert "WEB_SEARCH: old query" not in block


def test_ordinary_session_history_keeps_jin_text_inside_completed_sequences():
    ctx = _context_with_current_sequence()

    block = build_session_actions_history_context(ctx)

    assert "Current request:" not in block
    assert "JIN: old JIN text must stay hidden" in block
    assert "--- start of sequence ---" in block
    assert "--- end of sequence ---" in block
    assert "Сейчас открою файл и проверю причину." not in block


def test_sequence_completion_restores_global_numbering_and_next_sequence_resets():
    ctx = _context_with_current_sequence()
    first = BrainNode.build_followup_system_prompt("BASE", "request", context=ctx)
    assert "1. ATTACH_FILE_CONTENT:" in first
    assert "2. ATTACH_FILE_CONTENT:" not in first
    # The next ordinary prompt is the path taken after a marker-free answer.
    completed = build_session_actions_history_context(ctx)
    assert "<SESSION_ACTIONS_HISTORY>" in completed
    assert "3. ATTACH_FILE_CONTENT:" in completed
    assert completed.count("--- start of sequence ---") == 2
    assert completed.count("--- end of sequence ---") == 2
    assert completed.index("JIN: Сейчас") < completed.index("3. ATTACH_FILE_CONTENT:")
    ctx.runtime_current_turn_id = ctx.runtime_current_sequence_turn_id = "turn_3"
    ctx.runtime_current_sequence_started_at = time.time()
    ctx.runtime_session_action_history.append({
        "text": "LIST_SKILLS", "runtime_turn_id": "turn_3",
        "created_at": time.time(), "jin_message_content": "Next step",
    })
    next_prompt = BrainNode.build_followup_system_prompt(first, "next request", context=ctx)
    assert next_prompt.count("<CURRENT_REQUEST_ACTIONS_HISTORY>") == 1
    assert "1. LIST_SKILLS" in next_prompt
    assert "ATTACH_FILE_CONTENT:" not in next_prompt
    assert "next request" not in next_prompt
    final = build_session_actions_history_context(ctx)
    assert "4. LIST_SKILLS" in final
    assert final.count("--- start of sequence ---") == 3
    assert final.count("--- end of sequence ---") == 3


def test_empty_sequence_does_not_fall_back_to_session_or_user_quote():
    ctx = _context_with_current_sequence()
    ctx.runtime_current_sequence_started_at = time.time() + 1
    assert build_session_actions_history_context(
        ctx, current_sequence=True, current_request="do not duplicate me"
    ) == ""


def test_sequence_projection_survives_serialization():
    import json
    from types import SimpleNamespace
    ctx = _context_with_current_sequence()
    restored = SimpleNamespace(**json.loads(json.dumps({
        key: getattr(ctx, key) for key in (
            "session_id", "runtime_session_action_history",
            "runtime_action_sequence_turn_ids", "runtime_current_sequence_turn_id",
            "runtime_current_sequence_started_at",
        )
    })))
    assert build_session_actions_history_context(restored) == build_session_actions_history_context(ctx)
    assert build_session_actions_history_context(restored, current_sequence=True) == build_session_actions_history_context(ctx, current_sequence=True)
