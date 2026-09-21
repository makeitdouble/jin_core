import asyncio
from types import SimpleNamespace

from contracts.rules_assembler import (
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_REACTION,
)
from tests.helpers.runtime_actions import FakeEmitter
from utils.actions import RuntimeActionCall
from utils.actions.action_registry import ACTIONS
from utils.actions.common_action_utils import KNOWN_RUNTIME_ACTIONS
from utils.actions.dispatcher import apply_runtime_action_calls


def test_registry_covers_all_known_runtime_actions():
    assert set(KNOWN_RUNTIME_ACTIONS).issubset(ACTIONS)


def test_runtime_actions_run_in_model_emission_order():
    async def run_case():
        emitter = FakeEmitter()
        context = SimpleNamespace(
            runtime_action_events=[],
            runtime_search_calls=[],
            runtime_deep_search_calls=[],
            runtime_loaded_skills=[],
            runtime_skill_state_barrier_active=False,
            runtime_current_turn_id="turn-order",
            runtime_action_failure_followup_messages=[],
            logger=None,
            emitter=emitter,
        )
        actions = (
            RuntimeActionCall(name=RUNTIME_ACTION_JIN_COLOR, payload="#ff0000"),
            RuntimeActionCall(name=RUNTIME_ACTION_JIN_REACTION, payload="😂"),
            RuntimeActionCall(name=RUNTIME_ACTION_JIN_COLOR, payload="#00ff00"),
        )

        applied = await apply_runtime_action_calls(context, actions)

        assert applied == 3
        assert [event["name"] for event in context.runtime_action_events] == [
            "jin_color",
            "jin_reaction",
            "jin_color",
        ]
        assert [event["action"] for event in emitter.events] == [
            "jin_color",
            "jin_reaction",
            "jin_color",
        ]
        assert context.jin_color == "#00ff00"

    asyncio.run(run_case())
