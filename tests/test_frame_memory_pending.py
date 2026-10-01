import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from runtime.frame_memory import summarize_runtime_memory_pending_turns
from runtime.frame_memory_rules import INITIAL_RUNTIME_MEMORY


class FrameMemoryPendingTests(unittest.IsolatedAsyncioTestCase):
    async def test_pending_frame_update_preserves_model_values_without_confirmation_injection(self):
        memory = "user_fact: Prefers quiet places.\nactive_topic: Current discussion."
        response = {"choices": [{"message": {"content": memory}, "finish_reason": "stop"}]}
        turns = [
            {
                "turn_id": "turn-current",
                "user_message": "это факт",
                "assistant_message": "OK",
            }
        ]
        context = SimpleNamespace(
            clients={"service": object()},
            runtime_memory="",
            runtime_memory_stable="",
            runtime_memory_updates=0,
            runtime_memory_pending_turns=list(turns),
        )

        with patch(
            "runtime.frame_memory.ask_runtime_memory_batch_model",
            new=AsyncMock(return_value=response),
        ), patch(
            "runtime.frame_memory.emit_runtime_memory_update",
            new=AsyncMock(),
        ) as emit, patch(
            "runtime.frame_memory.record_runtime_frame_diff",
            new=AsyncMock(),
        ):
            result = await summarize_runtime_memory_pending_turns(context=context)

        self.assertEqual(context.runtime_memory_pending_turns, [])
        expected = f"{INITIAL_RUNTIME_MEMORY}\n{memory}"
        self.assertEqual(result, expected)
        self.assertEqual(context.runtime_memory_stable, expected)
        self.assertEqual(context.runtime_memory_updates, 1)
        emit.assert_awaited_once()
        self.assertIs(emit.await_args.args[0], context)
        self.assertEqual(emit.await_args.kwargs["source_turns"], turns)


if __name__ == "__main__":
    unittest.main()
