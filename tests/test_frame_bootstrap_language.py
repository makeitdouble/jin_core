"""Verify the FRAME language rule in the actual request builders."""
import ast
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from runtime.L1_memory_rules import build_runtime_memory_system_prompt

ROOT = Path(__file__).resolve().parents[1]


class FrameBootstrapLanguageTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        names = {
            "resolve_frame_language_user_message",
            "build_runtime_memory_system_prompt_for_turn",
            "build_runtime_memory_system_prompt_for_turns",
            "ask_runtime_memory_model",
            "ask_runtime_memory_batch_model",
        }
        tree = ast.parse((ROOT / "runtime/L1_memory.py").read_text(encoding="utf-8"))
        self.env = {
            "build_runtime_memory_system_prompt": build_runtime_memory_system_prompt,
            "config": SimpleNamespace(SERVICE_TEMPERATURE=0.1),
            "get_strength_zones": lambda lines: {},
            "refresh_service_runtime_usage": AsyncMock(),
            "ask_frame_summarizer": AsyncMock(return_value={"choices": []}),
            "build_runtime_memory_batch_user_prompt": Mock(return_value="Original bootstrap input"),
            "build_runtime_memory_user_prompt": Mock(return_value="Original single-turn input"),
            "latest_turn_context_is_overloaded": lambda context: False,
            "runtime_prompt_is_context_overloaded": lambda **kwargs: False,
        }
        functions = [node for node in tree.body
                     if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and node.name in names]
        exec(compile(ast.Module(body=functions, type_ignores=[]), "frame_language", "exec"), self.env)

    async def request(self, history, user="", single=False, overloaded=False):
        # Round-trip the inherited dialogue like a browser checkpoint, including
        # the JIN-only greeting appended before the background FRAME request.
        context = SimpleNamespace(runtime_recent_turns=json.loads(json.dumps(history)))
        self.env["latest_turn_context_is_overloaded"] = lambda context: overloaded
        kwargs = dict(context=context, service_client=SimpleNamespace(), current_memory="topic: old")
        if single:
            await self.env["ask_runtime_memory_model"](
                **kwargs, user_message=user, assistant_message="Bootstrap greeting")
        else:
            turns = [{"user_message": user, "assistant_message": "Bootstrap greeting"}]
            await self.env["ask_runtime_memory_batch_model"](**kwargs, turns=turns)
            self.assertEqual(self.env["build_runtime_memory_batch_user_prompt"].call_args.kwargs["turns"], turns)
        return self.env["ask_frame_summarizer"].call_args.kwargs["system_prompt"]

    async def test_bootstrap_uses_latest_real_user_and_skips_jin_greeting(self):
        history = [
            {"user": "Earlier English message", "jin": "English reply"},
            {"user": "сохрани отчёт, заголовок — написание статьи", "jin": ""},
            {"user": "", "jin": "English bootstrap greeting"},
        ]
        for single, overloaded in [(False, False), (True, False), (True, True)]:
            with self.subTest(single=single, overloaded=overloaded):
                prompt = await self.request(history, single=single, overloaded=overloaded)
                self.assertEqual(prompt.count("MANDATORY OUTPUT VALUE LANGUAGE: Russian"), 3)
                self.assertIn("Keep memory keys in English lowercase_snake_case.", prompt)

    async def test_current_user_language_wins_over_restored_russian(self):
        prompt = await self.request([{"user": "сохрани отчёт"}], user="Continue in English")
        self.assertEqual(prompt.count("MANDATORY OUTPUT VALUE LANGUAGE: English"), 3)

    async def test_latest_user_wins_over_older_russian_and_jin_text(self):
        prompt = await self.request([
            {"user": "Старое сообщение"},
            {"user": "Latest English message", "jin": "Ответ по-русски"},
        ])
        self.assertIn("MANDATORY OUTPUT VALUE LANGUAGE: English", prompt)

    async def test_no_history_keeps_default_and_ukrainian_is_detected(self):
        prompt = await self.request([])
        self.assertIn("MANDATORY OUTPUT VALUE LANGUAGE: English", prompt)
        prompt = await self.request([{"user": "Збережи цей звіт"}])
        self.assertIn("MANDATORY OUTPUT VALUE LANGUAGE: Ukrainian", prompt)


if __name__ == "__main__":
    unittest.main()
