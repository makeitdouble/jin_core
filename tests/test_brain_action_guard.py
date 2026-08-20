import asyncio
from types import SimpleNamespace

from clients.brain_client import ask_brain_stream
from config_loader import config


class FakeBrainClient:
    async def stream(self, **_kwargs):
        yield {
            "type": "content",
            "content": "Принято. <JIN_COLOR> #ff0000 </JIN_COLOR>",
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


def test_brain_stream_jin_color_executes_without_confirmation():
    context, chunks = run_color_stream(
        "поставь себе красный яркий",
        "reject",
    )

    assert [
        chunk
        for chunk in chunks
        if chunk.get("type") == "content"
    ] == [{"type": "content", "content": "Принято."}]
    assert [
        chunk
        for chunk in chunks
        if chunk.get("type") == "raw_model_output"
    ] == [{
        "type": "raw_model_output",
        "content": "Принято. <JIN_COLOR> #ff0000 </JIN_COLOR>",
    }]
    assert [
        (event.get("type"), event.get("status"))
        for event in context.emitter.events
    ] == [
        ("runtime_action", "counted"),
        ("runtime_action", "completed"),
        ("runtime_action", "counter_final"),
    ]
    assert context.emitter.events[0]["marker_count"] == 1
    assert context.emitter.events[0]["color"] == "#ff0000"
    assert context.emitter.events[0]["colors"] == ["#ff0000"]
    assert context.runtime_action_events[-1]["name"] == "jin_color"
    assert context.runtime_action_events[-1]["color"] == "#ff0000"


def test_brain_stream_matching_trigger_executes_without_confirmation():
    context, chunks = run_color_stream(
        "поставь цвет красный яркий",
    )

    assert [
        chunk
        for chunk in chunks
        if chunk.get("type") == "content"
    ] == [{"type": "content", "content": "Принято."}]
    assert [
        chunk
        for chunk in chunks
        if chunk.get("type") == "raw_model_output"
    ] == [{
        "type": "raw_model_output",
        "content": "Принято. <JIN_COLOR> #ff0000 </JIN_COLOR>",
    }]
    assert [
        (event.get("type"), event.get("status"))
        for event in context.emitter.events
    ] == [
        ("runtime_action", "counted"),
        ("runtime_action", "completed"),
        ("runtime_action", "counter_final"),
    ]
    assert context.emitter.events[0]["marker_count"] == 1
    assert context.runtime_action_events[-1]["name"] == "jin_color"
