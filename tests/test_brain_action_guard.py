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
    return asyncio.run(
        collect_color_stream(user_text, decision)
    )


def test_brain_stream_leaves_runtime_markers_for_runtime_stream():
    context, chunks = run_color_stream(
        "поставь себе красный яркий",
        "reject",
    )

    assert chunks == [{
        "type": "content",
        "content": "Принято. <JIN_COLOR> #ff0000 </JIN_COLOR>",
    }]
    assert context.emitter.events == []
    assert not hasattr(context, "runtime_action_events")


def test_brain_stream_does_not_apply_guard_logic_in_provider_transport():
    context, chunks = run_color_stream(
        "поставь цвет красный яркий",
    )

    assert chunks == [{
        "type": "content",
        "content": "Принято. <JIN_COLOR> #ff0000 </JIN_COLOR>",
    }]
    assert context.emitter.events == []
    assert not hasattr(context, "runtime_action_events")
