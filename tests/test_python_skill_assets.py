import asyncio
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import assets_utils
from utils.python_skill_asset_utils import (
    _build_iteration_system_prompt,
    _emit_document_reader_progress,
    _extract_model_content,
    _resolve_reader_mode,
    _format_document_reader_elapsed,
    _resolve_reader_budgets,
    run_document_reader_action,
    run_python_skill_action,
)
from utils.brain_client_utils import (
    apply_runtime_action_calls,
)
from utils.actions import (
    RuntimeActionCall,
)
from utils.skills_asset_utils import (
    list_skills,
    load_skill,
)
from utils.session_actions_history import (
    build_asset_action_history_text,
)


class FakeBrainClient:

    def __init__(
        self,
        context_window=2048,
    ):
        self.context_window = context_window
        self.calls = []

    async def resolve_request_context_window(self):
        return self.context_window

    async def ask(
        self,
        *,
        system_prompt,
        user_prompt,
        temperature,
        max_tokens,
        timeout=None,
    ):
        self.calls.append({
            "system_prompt": system_prompt,
            "user_prompt": user_prompt,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "timeout": timeout,
        })
        return {
            "choices": [
                {
                    "message": {
                        "content": (
                            f"RESULT AFTER CHUNK {len(self.calls)} "
                            f"[c{len(self.calls)}]"
                        ),
                    },
                },
            ],
        }


class PythonSkillAssetTests(unittest.TestCase):

    def test_document_reader_elapsed_format_uses_minutes_and_seconds(self):
        self.assertEqual(
            _format_document_reader_elapsed(59),
            "59s",
        )
        self.assertEqual(
            _format_document_reader_elapsed(60),
            "1m 0s",
        )
        self.assertEqual(
            _format_document_reader_elapsed(61),
            "1m 1s",
        )

    def test_document_reader_progress_distinguishes_chunks_from_requests(self):
        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.runtime_active_asset_action_id = "asset:test"

        asyncio.run(
            _emit_document_reader_progress(
                context,
                attachment_name="document.pdf",
                mode="plain-mode.md",
                chunk_index=2,
                estimated_chunks=3,
                processed_words=820,
                target_words=1000,
                total_words=1000,
                pages_label="9",
                stage="processing",
                elapsed_seconds=61,
                request_index=5,
            )
        )

        event = context.emitter.events[-1]

        self.assertIn(
            "82→100%",
            event["text"],
        )
        self.assertIn(
            "chunk 2",
            event["text"],
        )
        self.assertNotIn(
            "attempt",
            event["text"].casefold(),
        )
        self.assertNotIn(
            "/~3",
            event["text"],
        )
        self.assertNotIn(
            "request 5",
            event["text"],
        )
        self.assertIn(
            "model request 5",
            event["detail"],
        )
        self.assertIn(
            "1m 1s",
            event["text"],
        )
        self.assertIn(
            "plain-mode.md",
            event["text"],
        )
        self.assertEqual(
            event["progress"]["request"],
            5,
        )
        self.assertNotIn(
            "attempt",
            event["progress"],
        )
        self.assertEqual(
            event["progress"]["target_percent"],
            100,
        )


    def test_document_reader_bubble_uses_exact_mode_filename(self):
        text = build_asset_action_history_text({
            "action": "run_document_reader",
            "ok": True,
            "mode": "plain-mode.md",
        })

        self.assertEqual(
            text,
            "Read document iteratively - plain-mode.md",
        )

    def test_document_reader_does_not_retry_invalid_model_output(self):
        class EmptyServiceClient(FakeBrainClient):
            async def ask(
                self,
                *,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                timeout=None,
            ):
                self.calls.append({
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                })
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "",
                            },
                        },
                    ],
                }

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        client = EmptyServiceClient(
            context_window=2048,
        )
        context.clients = {
            "service": client,
        }
        context.emitter = Emitter()
        context.runtime_active_asset_action_id = "asset:test"
        context.runtime_appended_skills = [
            {
                "name": "chunk_reader",
            },
        ]
        context.runtime_turn_attachments = [
            {
                "name": "short.txt",
                "kind": "text",
                "type": "text/plain",
                "text_content": " ".join(
                    f"word-{index}"
                    for index in range(100)
                ),
            },
        ]

        result = asyncio.run(
            run_document_reader_action(
                context,
                {
                    "action": "run_document_reader",
                    "skill": "chunk_reader",
                    "attachment": "short.txt",
                    "mode": "plain-mode.md",
                    "question": "Summarize.",
                },
            )
        )

        self.assertFalse(
            result["ok"],
        )
        self.assertEqual(
            result["error"],
            "invalid_model_output",
        )
        self.assertEqual(
            len(client.calls),
            1,
        )
        self.assertIn(
            "No automatic retry",
            result["detail"],
        )
        self.assertFalse(
            any(
                event.get("progress", {}).get("stage") == "retrying"
                for event in context.emitter.events
            ),
        )


    def test_document_reader_commits_length_limited_output_without_retry(self):
        class LengthLimitedServiceClient(FakeBrainClient):
            async def ask(
                self,
                *,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                timeout=None,
            ):
                self.calls.append({
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                })
                return {
                    "choices": [
                        {
                            "finish_reason": "length",
                            "message": {
                                "content": f"usable result {len(self.calls)}",
                            },
                        },
                    ],
                }

        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        client = LengthLimitedServiceClient(
            context_window=8192,
        )
        context.clients = {
            "service": client,
        }
        context.emitter = Emitter()
        context.runtime_active_asset_action_id = "asset:test"
        context.runtime_appended_skills = [
            {
                "name": "chunk_reader",
            },
        ]
        context.runtime_turn_attachments = [
            {
                "name": "split.txt",
                "kind": "text",
                "type": "text/plain",
                "text_content": " ".join(
                    f"word-{index}"
                    for index in range(5000)
                ),
            },
        ]

        result = asyncio.run(
            run_document_reader_action(
                context,
                {
                    "action": "run_document_reader",
                    "skill": "chunk_reader",
                    "attachment": "split.txt",
                    "mode": "plain-mode.md",
                    "question": "Summarize.",
                },
            )
        )

        self.assertTrue(
            result["ok"],
        )
        self.assertEqual(
            len(client.calls),
            result["chunks"],
        )
        self.assertEqual(
            result["length_limited_chunks"],
            result["chunks"],
        )
        self.assertFalse(
            any(
                event.get("progress", {}).get("stage") == "retrying"
                for event in context.emitter.events
            ),
        )
        self.assertTrue(
            all(
                "attempt" not in str(event.get("text", "")).casefold()
                for event in context.emitter.events
            ),
        )


    def test_document_reader_uses_service_model_and_server_context_window(self):
        class DetectedServiceClient(FakeBrainClient):
            def __init__(self):
                super().__init__(context_window=8192)
                self.configured_context_window = 4096
                self.force_refresh_values = []

            async def resolve_request_context_window(
                self,
                *,
                force_refresh=False,
            ):
                self.force_refresh_values.append(force_refresh)
                return 8192

        class Context:
            pass

        context = Context()
        service_client = DetectedServiceClient()
        brain_client = FakeBrainClient(
            context_window=4096,
        )
        context.clients = {
            "service": service_client,
            "brain": brain_client,
        }
        context.runtime_appended_skills = [
            {
                "name": "chunk_reader",
            },
        ]
        context.runtime_turn_attachments = [
            {
                "name": "short.txt",
                "kind": "text",
                "type": "text/plain",
                "text_content": " ".join(
                    f"word-{index}"
                    for index in range(100)
                ),
            },
        ]

        result = asyncio.run(
            run_document_reader_action(
                context,
                {
                    "action": "run_document_reader",
                    "skill": "chunk_reader",
                    "attachment": "short.txt",
                    "mode": "plain-mode.md",
                    "question": "Summarize.",
                },
            )
        )

        self.assertTrue(result["ok"])
        self.assertTrue(service_client.calls)
        self.assertFalse(brain_client.calls)
        self.assertEqual(result["context_window"], 8192)
        self.assertEqual(
            service_client.force_refresh_values,
            [True],
        )

    def test_directory_skill_is_listed_and_loaded_from_manifest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets_root = root / "assets"
            skills_root = assets_root / "skills"
            skill_root = skills_root / "chunk_reader"
            skill_root.mkdir(parents=True)
            (skill_root / "JIN_SKILL.md").write_text(
                "chunk_reader\nUse ASSET_ACTION.",
                encoding="utf-8",
            )
            (skill_root / "reader.py").write_text(
                "print('ok')\n",
                encoding="utf-8",
            )
            (skill_root / "plain-mode.md").write_text(
                "# Plain mode\nNeutral instruction.",
                encoding="utf-8",
            )
            (skill_root / "deep-mode.md").write_text(
                "# Deep mode\nDetailed instruction.",
                encoding="utf-8",
            )

            with (
                patch.object(assets_utils, "PROJECT_ROOT", root),
                patch.object(assets_utils, "ASSETS_ROOT", assets_root),
                patch.object(assets_utils, "SKILLS_ROOT", skills_root),
                patch.object(assets_utils, "WILDCARDS_ROOT", assets_root / "wildcards"),
                patch.object(assets_utils, "PROMPTS_ROOT", assets_root / "prompts"),
                patch.object(assets_utils, "TEMPLATES_ROOT", assets_root / "templates"),
                patch.object(assets_utils, "OUTPUTS_ROOT", assets_root / "outputs"),
            ):
                skills = list_skills()["skills"]
                loaded = load_skill("chunk_reader")

            self.assertEqual(
                [skill["name"] for skill in skills],
                ["chunk_reader"],
            )
            self.assertEqual(
                skills[0]["path"],
                "assets/skills/chunk_reader/JIN_SKILL.md",
            )
            self.assertIn(
                "assets/skills/chunk_reader/reader.py",
                skills[0]["files"],
            )
            self.assertTrue(
                loaded["ok"]
            )
            self.assertEqual(
                loaded["skill"]["modes"],
                [
                    "deep-mode.md",
                    "plain-mode.md",
                ],
            )
            self.assertIn(
                "Use ASSET_ACTION",
                loaded["skill"]["content"],
            )

    def test_reader_mode_is_loaded_by_exact_mode_filename(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            skill_root = Path(temp_dir)
            (skill_root / "plain-mode.md").write_text(
                "# Plain mode\nNeutral instruction.",
                encoding="utf-8",
            )

            mode_name, instruction = _resolve_reader_mode(
                skill_root,
                "PLAIN-MODE.MD",
            )

        self.assertEqual(
            mode_name,
            "plain-mode.md",
        )
        self.assertIn(
            "Neutral instruction",
            instruction,
        )

    def test_document_reader_can_run_multiple_named_mode_files(self):
        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            skills_root = Path(temp_dir)
            skill_root = skills_root / "chunk_reader"
            shutil.copytree(
                assets_utils.SKILLS_ROOT / "chunk_reader",
                skill_root,
            )
            (skill_root / "plain-mode.md").write_text(
                "# Plain mode\nSummarize directly.",
                encoding="utf-8",
            )
            (skill_root / "compact-mode.md").write_text(
                "# Compact mode\nKeep only essential facts.",
                encoding="utf-8",
            )

            context = Context()
            client = FakeBrainClient(
                context_window=2048,
            )
            context.clients = {
                "service": client,
            }
            context.runtime_appended_skills = [
                {
                    "name": "chunk_reader",
                },
            ]
            context.runtime_turn_attachments = [
                {
                    "name": "short.txt",
                    "kind": "text",
                    "type": "text/plain",
                    "text_content": " ".join(
                        f"word-{index}"
                        for index in range(100)
                    ),
                },
            ]

            with patch.object(
                assets_utils,
                "SKILLS_ROOT",
                skills_root,
            ):
                result = asyncio.run(
                    run_document_reader_action(
                        context,
                        {
                            "action": "run_document_reader",
                            "skill": "chunk_reader",
                            "attachment": "short.txt",
                            "modes": [
                                "plain-mode.md",
                                "compact-mode.md",
                            ],
                            "question": "Compare summaries.",
                        },
                    )
                )

        self.assertTrue(
            result["ok"],
        )
        self.assertEqual(
            result["modes"],
            [
                "plain-mode.md",
                "compact-mode.md",
            ],
        )
        self.assertEqual(
            set(result["results"]),
            {
                "plain-mode.md",
                "compact-mode.md",
            },
        )
        self.assertEqual(
            len(client.calls),
            2,
        )

    def test_reader_budget_shrinks_as_result_grows(self):
        empty = _resolve_reader_budgets(
            context_window=4096,
            output_token_limit=2048,
            instruction="method",
            question="question",
            current_result="",
        )
        full = _resolve_reader_budgets(
            context_window=4096,
            output_token_limit=2048,
            instruction="method",
            question="question",
            current_result="result " * 1000,
        )

        self.assertGreater(
            empty["chunk_words"],
            full["chunk_words"],
        )
        self.assertEqual(
            empty["context_window"],
            4096,
        )

    def test_reader_budget_scales_on_large_context_without_static_4096_cap(self):
        budgets = _resolve_reader_budgets(
            context_window=262144,
            output_token_limit=8192,
            instruction="method",
            question="question",
            current_result="",
        )

        self.assertGreater(
            budgets["chunk_tokens"],
            4096,
        )
        self.assertEqual(
            budgets["result_token_cap"],
            8192,
        )

    def test_reader_uses_content_only_and_never_falls_back_to_reasoning(self):
        response = {
            "choices": [
                {
                    "message": {
                        "content": "",
                        "reasoning_content": "PRIVATE REASONING",
                    },
                },
            ],
        }

        self.assertEqual(
            _extract_model_content(
                response
            ),
            "",
        )

    def test_iteration_prompt_is_mode_agnostic_and_forbids_reasoning(self):
        prompt = _build_iteration_system_prompt(
            "CUSTOM MODE INSTRUCTION",
            4096,
        )

        self.assertIn(
            "private reasoning",
            prompt,
        )
        self.assertIn(
            "Never replace prior content",
            prompt,
        )
        self.assertIn(
            "CUSTOM MODE INSTRUCTION",
            prompt,
        )
        self.assertNotIn(
            "DOCUMENT_STATE",
            prompt,
        )

    def test_document_reader_runs_all_chunks_and_returns_final_result(self):
        class Context:
            pass

        context = Context()
        client = FakeBrainClient(
            context_window=2048,
        )
        context.clients = {
            "service": client,
        }
        context.runtime_appended_skills = [
            {
                "name": "chunk_reader",
            },
        ]
        context.runtime_turn_attachments = [
            {
                "name": "long.txt",
                "kind": "text",
                "type": "text/plain",
                "text_content": " ".join(
                    f"word-{index}"
                    for index in range(2000)
                ),
            },
        ]

        result = asyncio.run(
            run_document_reader_action(
                context,
                {
                    "action": "run_document_reader",
                    "skill": "chunk_reader",
                    "attachment": "long.txt",
                    "mode": "plain-mode.md",
                    "question": "What is in the file?",
                },
            )
        )

        self.assertTrue(
            result["ok"]
        )
        self.assertEqual(
            result["action"],
            "run_document_reader",
        )
        self.assertEqual(
            result["total_words"],
            2000,
        )
        self.assertGreater(
            result["chunks"],
            1,
        )
        self.assertEqual(
            len(client.calls),
            result["chunks"],
        )
        self.assertIn(
            f"RESULT AFTER CHUNK {result['chunks']}",
            result["result"],
        )

    def test_asset_action_dispatches_document_reader_and_records_result(self):
        class Emitter:
            def __init__(self):
                self.events = []

            async def emit(self, event):
                self.events.append(event)

        class Context:
            pass

        context = Context()
        context.emitter = Emitter()
        context.clients = {
            "service": FakeBrainClient(
                context_window=2048,
            ),
        }
        context.runtime_appended_skills = [
            {
                "name": "chunk_reader",
            },
        ]
        context.runtime_turn_attachments = [
            {
                "name": "short.txt",
                "kind": "text",
                "text_content": " ".join(
                    f"token-{index}"
                    for index in range(100)
                ),
            },
        ]

        applied = asyncio.run(
            apply_runtime_action_calls(
                context,
                (
                    RuntimeActionCall(
                        name="ASSET_ACTION",
                        payload=json.dumps({
                            "action": "run_document_reader",
                            "skill": "chunk_reader",
                            "attachment": "short.txt",
                            "mode": "plain-mode.md",
                            "question": "Summarize.",
                        }),
                    ),
                ),
                user_message="Read the attached file.",
            )
        )

        self.assertEqual(
            applied,
            1,
        )
        self.assertEqual(
            context.runtime_asset_results[-1]["action"],
            "run_document_reader",
        )
        self.assertTrue(
            context.runtime_asset_results[-1]["ok"]
        )
        running_events = [
            event
            for event in context.emitter.events
            if event.get("status") == "running"
        ]
        self.assertTrue(
            running_events
        )
        self.assertEqual(
            running_events[0]["id"],
            context.emitter.events[-1]["id"],
        )
        self.assertIn(
            "percent",
            running_events[-1]["progress"],
        )
        self.assertEqual(
            context.emitter.events[-1]["status"],
            "completed",
        )

    def test_generic_python_skill_receives_attachment_path_without_shell(self):
        class Context:
            pass

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            assets_root = root / "assets"
            skills_root = assets_root / "skills"
            skill_root = skills_root / "echo_skill"
            skill_root.mkdir(parents=True)
            (skill_root / "echo.py").write_text(
                """
import json
import pathlib
import sys
path = pathlib.Path(sys.argv[1])
print(json.dumps({"name": path.name, "text": path.read_text(encoding="utf-8")}))
""".strip(),
                encoding="utf-8",
            )
            context = Context()
            context.runtime_appended_skills = [
                {
                    "name": "echo_skill",
                },
            ]
            context.runtime_turn_attachments = [
                {
                    "name": "sample.txt",
                    "text_content": "hello skill",
                },
            ]

            with patch.object(
                assets_utils,
                "SKILLS_ROOT",
                skills_root,
            ):
                result = asyncio.run(
                    run_python_skill_action(
                        context,
                        {
                            "skill": "echo_skill",
                            "script": "echo.py",
                            "args": [
                                "$ATTACHMENT",
                            ],
                            "attachment": "sample.txt",
                        },
                    )
                )

            self.assertTrue(
                result["ok"]
            )
            parsed = json.loads(
                result["stdout"]
            )
            self.assertEqual(
                parsed["name"],
                "sample.txt",
            )
            self.assertEqual(
                parsed["text"],
                "hello skill",
            )


if __name__ == "__main__":
    unittest.main()
