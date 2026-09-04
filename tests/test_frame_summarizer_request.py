"""Test the FRAME request boundary without loading app/server dependencies."""
import ast
import asyncio
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock


ROOT = Path(__file__).resolve().parents[1]


class FrameSummarizerRequestTests(unittest.IsolatedAsyncioTestCase):
    def load_request(self, response=None, error=None):
        tree = ast.parse((ROOT / "runtime/L1_memory.py").read_text(encoding="utf-8"))
        request = next(node for node in tree.body
                       if isinstance(node, ast.AsyncFunctionDef)
                       and node.name == "ask_frame_summarizer")
        common = ast.parse((ROOT / "runtime/memory_common.py").read_text(encoding="utf-8"))
        payload = next(node for node in common.body
                       if isinstance(node, ast.FunctionDef)
                       and node.name == "build_runtime_summarizer_payload")
        namespace = {
            "asyncio": asyncio,
            "config": SimpleNamespace(SERVICE_REQUEST_TIMEOUT=45),
            "ask_service_model": AsyncMock(return_value=response, side_effect=error),
            "log_runtime_summarizer_payload": AsyncMock(),
            "log_memory_event": AsyncMock(),
        }
        exec(compile(ast.Module(body=[payload, request], type_ignores=[]),
                     "frame_request", "exec"), namespace)
        return namespace

    async def call(self, namespace):
        return await namespace["ask_frame_summarizer"](
            context=SimpleNamespace(),
            service_client=SimpleNamespace(model_uid="test-model", stream=AsyncMock()),
            label="FRAME", system_prompt="system", user_prompt="user",
            temperature=0.1, max_tokens=None,
        )

    async def test_complete_response_and_request_are_preserved_without_streaming(self):
        response = {"choices": [{"message": {"content": "key: value"}}],
                    "usage": {"total_tokens": 15}}
        namespace = self.load_request(response=response)
        result = await self.call(namespace)
        self.assertIs(result, response)
        logged = namespace["log_runtime_summarizer_payload"].call_args.kwargs
        self.assertEqual(logged["label"], "FRAME")
        self.assertFalse(logged["payload"]["stream"])
        self.assertEqual(logged["payload"]["messages"][1]["content"], "user")
        args = namespace["ask_service_model"].call_args.kwargs
        args["client"].stream.assert_not_called()
        self.assertEqual(args["timeout"], 45)
        self.assertFalse(args["track_usage"])

    async def test_cancellation_finishes_card_and_still_propagates(self):
        namespace = self.load_request(error=asyncio.CancelledError())
        with self.assertRaises(asyncio.CancelledError):
            await self.call(namespace)
        logged = namespace["log_memory_event"].call_args.kwargs
        self.assertEqual(logged["level"], "FRAME")
        self.assertEqual(logged["event"], "summarizer_cancelled")

    async def test_request_failure_reaches_existing_memory_failure_handler(self):
        namespace = self.load_request(error=RuntimeError("provider failed"))
        with self.assertRaisesRegex(RuntimeError, "provider failed"):
            await self.call(namespace)
        namespace["log_runtime_summarizer_payload"].assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
