import asyncio
from types import SimpleNamespace

from clients.brain_client import ask_brain_stream
from config_loader import config


class FakeBrainClient:
    async def stream(self, **_kwargs):
        yield {
            "type": "content",
            "content": "Принято. <JIN_COLOR: #ff0000 >",
        }


class ConfirmingEmitter:
    def __init__(self, context, decision):
        self.context = context
        self.decision = decision
        self.events = []

    async def emit(self, payload):
        self.events.append(dict(payload))

        if payload.get("type") != "runtime_action_guard_confirmation":
            return

        assert not any(
            event.get("type") == "runtime_action"
            and event.get("status") == "completed"
            for event in self.events
        )
        future = self.context.runtime_action_guard_confirmations[
            payload["confirmation_id"]
        ]
        future.set_result(self.decision)


async def collect_color_stream(user_text, decision="continue"):
    context = SimpleNamespace()
    context.emitter = ConfirmingEmitter(context, decision)

    chunks = [
        chunk
        async for chunk in ask_brain_stream(
            client=FakeBrainClient(),
            text=user_text,
            context=context,
            runtime_actions={"CAN_JIN_COLOR": True},
        )
    ]
    return context, chunks


def run_color_stream(user_text, decision="continue"):
    previous = config.USE_SERVICE_AS_BRAIN
    config.USE_SERVICE_AS_BRAIN = False
    try:
        return asyncio.run(
            collect_color_stream(user_text, decision)
        )
    finally:
        config.USE_SERVICE_AS_BRAIN = previous


def test_brain_stream_waits_for_missing_trigger_confirmation():
    context, chunks = run_color_stream(
        "поставь себе красный яркий",
        "continue",
    )

    assert chunks == [{"type": "content", "content": "Принято."}]
    assert [
        (event.get("type"), event.get("status"))
        for event in context.emitter.events
    ] == [
        ("runtime_action_guard_confirmation", "pending"),
        ("runtime_action", "completed"),
    ]
    assert context.runtime_action_events[-1]["name"] == "jin_color"
    assert context.runtime_action_events[-1]["color"] == "#ff0000"


def test_brain_stream_reject_skips_action_and_continues():
    context, chunks = run_color_stream(
        "поставь себе красный яркий",
        "reject",
    )

    assert chunks == [{"type": "content", "content": "Принято."}]
    assert [
        (event.get("type"), event.get("status"))
        for event in context.emitter.events
    ] == [
        ("runtime_action_guard_confirmation", "pending"),
        ("runtime_action", "failed"),
    ]
    assert context.runtime_action_events[-1]["status"] == "failed"
    assert not any(
        event.get("status") == "completed"
        for event in context.emitter.events
    )


def test_brain_stream_matching_trigger_executes_without_confirmation():
    context, chunks = run_color_stream(
        "поставь цвет красный яркий",
    )

    assert chunks == [{"type": "content", "content": "Принято."}]
    assert [
        (event.get("type"), event.get("status"))
        for event in context.emitter.events
    ] == [
        ("runtime_action", "completed"),
    ]
    assert context.runtime_action_events[-1]["name"] == "jin_color"
