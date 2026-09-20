from types import SimpleNamespace
from unittest.mock import patch

import pytest

from agent.nodes.brain import BrainNode
from config_loader import config
from rules.brain_context_builder import build_brain_context


@pytest.mark.parametrize("keep", [False, True])
@pytest.mark.parametrize("loop", [False, True])
@pytest.mark.parametrize("action", ["posting_board", "web_search", "stuck in a reasoning loop", "context_limit", "followup_limit_reached"])
def test_followup_reasoning_flag(keep, loop, action):
    context = SimpleNamespace(
        runtime_previous_reasoning_content="previous unique thought",
        runtime_turn_reasoning_content="current unique thought",
        runtime_previous_reasoning_loop_contents=["failed unique thought"] if loop else [],
        runtime_reasoning_recovery_pending=loop,
        runtime_turn_interruption_reason="reasoning repetition" if loop else "",
    )
    with patch.object(config, "KEEP_FOLLOW_UP_REASONING", keep):
        base = build_brain_context(
            context, include_previous_reasoning=False,
            include_turn_reasoning=True, crop_previous_reasoning=False,
        )
        prompt = BrainNode.build_followup_system_prompt(
            base, "request", context=context, latest_action=action,
            instruction="Continue after the action.",
        )
    thought = "failed unique thought" if loop else "current unique thought"
    assert (thought in prompt) is keep
    assert "previous unique thought" not in prompt
    assert "Continue after the action." in prompt
    assert context.runtime_turn_reasoning_content == "current unique thought"
    if loop:
        assert "<REASONING_RECOVERY>" in prompt
        assert context.runtime_reasoning_recovery_pending is False


def test_default_and_ordinary_turn_reasoning():
    assert config.KEEP_FOLLOW_UP_REASONING is False
    context = SimpleNamespace(runtime_previous_reasoning_content="ordinary unique thought")
    with patch.object(config, "KEEP_FOLLOW_UP_REASONING", False):
        prompt = build_brain_context(context)
    assert "ordinary unique thought" in prompt


def test_followup_removes_repeated_blocks_with_windows_newlines():
    block = "<PREVIOUS_REASONING_CONTENT>\r\nsecret thought\r\n</PREVIOUS_REASONING_CONTENT>\r\n"
    with patch.object(config, "KEEP_FOLLOW_UP_REASONING", False):
        prompt = BrainNode.build_followup_system_prompt(block + block + "BASE", "request")
    assert "secret thought" not in prompt
    assert "BASE" in prompt
