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
    _build_iteration_user_prompt,
    _emit_document_reader_progress,
    _estimate_document_reader_total_chunks,
    _estimate_reader_tokens,
    _extract_model_content,
    _resolve_reader_mode,
    _format_document_reader_elapsed,
    _resolve_reader_budgets,
    run_context_asset_action,
    run_document_reader_action,
    run_python_skill_action,
    _select_attachment,
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
            "chunk 2/3",
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

    def test_document_reader_estimated_chunks_stays_stable(self):
        estimate = _estimate_document_reader_total_chunks(
            total_words=21481,
            chunk_index=7,
            nominal_chunk_words=1100,
            prior_estimated_chunks=20,
        )

        self.assertEqual(
            estimate,
            20,
        )

        self.assertEqual(
            _estimate_document_reader_total_chunks(
                total_words=21481,
                chunk_index=8,
                nominal_chunk_words=1100,
                prior_estimated_chunks=estimate,
            ),
            20,
        )

        self.assertEqual(
            _estimate_document_reader_total_chunks(
                total_words=21481,
                chunk_index=21,
                nominal_chunk_words=1100,
                prior_estimated_chunks=20,
            ),
            21,
        )

    def test_document_reader_finds_sequence_attachment_in_followup(self):
        class Context:
            pass

        context = Context()
        context.runtime_turn_attachments = []
        context.runtime_current_sequence_turn_id = "turn_000001"
        context.runtime_current_sequence_attachments_turn_id = "turn_000001"
        context.runtime_current_sequence_attachments = [
            {
                "name": "README.md",
                "kind": "text",
                "type": "text/markdown",
                "size_label": "304.8 KB",
                "text_content": "# file body",
            },
        ]

        attachment = _select_attachment(
            context,
            "README.md",
        )

        self.assertEqual(
            attachment["text_content"],
            "# file body",
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

    def test_document_reader_failed_history_includes_reason(self):
        text = build_asset_action_history_text({
            "action": "run_document_reader",
            "ok": False,
            "mode": "plain-mode.md",
            "detail": "HTTP 400 Bad Request: context overflow",
        })

        self.assertEqual(
            text,
            (
                "Read document iteratively - plain-mode.md - failed: "
                "HTTP 400 Bad Request: context overflow"
            ),
        )

    def test_document_reader_http_error_detail_includes_response_body(self):
        class Response:
            status_code = 400
            reason_phrase = "Bad Request"
            text = '{"error":{"message":"max_tokens exceeds limit"}}'

        class BadRequestError(Exception):
            response = Response()

        class FailingServiceClient(FakeBrainClient):
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
                raise BadRequestError(
                    "Client error '400 Bad Request'"
                )

        class Context:
            pass

        context = Context()
        context.clients = {
            "service": FailingServiceClient(
                context_window=2048,
            ),
        }
        context.runtime_loaded_skills = [
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
            run_context_asset_action(
                json.dumps({
                    "action": "run_document_reader",
                    "skill": "chunk_reader",
                    "attachment": "short.txt",
                    "mode": "plain-mode.md",
                    "question": "Summarize.",
                }),
                context=context,
            )
        )

        self.assertFalse(
            result["ok"],
        )
        self.assertEqual(
            result["mode"],
            "plain-mode.md",
        )
        self.assertIn(
            "HTTP 400 Bad Request",
            result["detail"],
        )
        self.assertIn(
            "max_tokens exceeds limit",
            result["detail"],
        )

    def test_document_reader_shrinks_expensive_chunks_to_context(self):
        class GuardedServiceClient(FakeBrainClient):
            async def ask(
                self,
                *,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                timeout=None,
            ):
                prompt_tokens = _estimate_reader_tokens(
                    system_prompt
                    + "\n"
                    + user_prompt
                )
                self.calls.append({
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                    "prompt_tokens": prompt_tokens,
                })
                if (
                    prompt_tokens + max_tokens + 256
                    > self.context_window
                ):
                    raise AssertionError(
                        "document reader prompt exceeded service context"
                    )
                return {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    f"RESULT AFTER CHUNK {len(self.calls)}"
                                ),
                            },
                        },
                    ],
                }

        class Context:
            pass

        client = GuardedServiceClient(
            context_window=4096,
        )
        context = Context()
        context.clients = {
            "service": client,
        }
        context.runtime_loaded_skills = [
            {
                "name": "chunk_reader",
            },
        ]
        context.runtime_turn_attachments = [
            {
                "name": "expensive.md",
                "kind": "text",
                "type": "text/markdown",
                "text_content": " ".join(
                    (
                        "РЎР»РѕРІР°СЂСЊ"
                        + ("%D0%BF" * 10)
                        + str(index)
                    )
                    for index in range(80)
                ),
            },
        ]

        result = asyncio.run(
            run_context_asset_action(
                json.dumps({
                    "action": "run_document_reader",
                    "skill": "chunk_reader",
                    "attachment": "expensive.md",
                    "mode": "plain-mode.md",
                    "question": "Summarize.",
                }),
                context=context,
            )
        )

        self.assertTrue(
            result["ok"],
        )
        self.assertGreater(
            len(client.calls),
            1,
        )
        self.assertLess(
            result["chunk_budget"]["actual_words_min"],
            result["chunk_budget"]["requested_words_first"],
        )

    def test_document_reader_retries_context_400_with_smaller_chunk(self):
        class Response:
            status_code = 400
            reason_phrase = "Bad Request"
            text = (
                '{"error":{"message":"The number of tokens to keep from '
                'the initial prompt is greater than the context length. '
                'Try to load the model with a larger context length, or '
                'provide a shorter input."}}'
            )

        class BadRequestError(Exception):
            response = Response()

        class StrictServerClient(FakeBrainClient):
            def __init__(self):
                super().__init__(
                    context_window=4096,
                )
                self.failures = 0

            async def ask(
                self,
                *,
                system_prompt,
                user_prompt,
                temperature,
                max_tokens,
                timeout=None,
            ):
                prompt_tokens = (
                    len(
                        (
                            system_prompt
                            + "\n"
                            + user_prompt
                        ).encode(
                            "utf-8"
                        )
                    )
                )

                if prompt_tokens > self.context_window - 256:
                    self.failures += 1
                    raise BadRequestError(
                        "Client error '400 Bad Request'"
                    )

                self.calls.append({
                    "system_prompt": system_prompt,
                    "user_prompt": user_prompt,
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                    "timeout": timeout,
                    "prompt_tokens": prompt_tokens,
                })
                return {
                    "choices": [
                        {
                            "message": {
                                "content": "STRICT RESULT",
                            },
                        },
                    ],
                }

        class Context:
            pass

        client = StrictServerClient()
        context = Context()
        context.clients = {
            "service": client,
        }
        context.runtime_loaded_skills = [
            {
                "name": "chunk_reader",
            },
        ]
        context.runtime_turn_attachments = [
            {
                "name": "strict.md",
                "kind": "text",
                "type": "text/markdown",
                "text_content": " ".join(
                    (
                        "РЎР»РѕРІР°СЂСЊ"
                        + ("%D0%BF" * 8)
                        + str(index)
                    )
                    for index in range(40)
                ),
            },
        ]

        result = asyncio.run(
            run_context_asset_action(
                json.dumps({
                    "action": "run_document_reader",
                    "skill": "chunk_reader",
                    "attachment": "strict.md",
                    "mode": "plain-mode.md",
                    "question": "Summarize.",
                }),
                context=context,
            )
        )

        self.assertTrue(
            result["ok"],
        )
        self.assertGreater(
            client.failures,
            0,
        )
        self.assertEqual(
            result["result"],
            "STRICT RESULT",
        )

    def test_document_reader_retries_invalid_model_output_with_smaller_chunk(self):
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
        context.runtime_loaded_skills = [
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
            3,
        )
        self.assertIn(
            "after 2 retry attempt(s)",
            result["detail"],
        )
        self.assertFalse(
            any(
                event.get("progress", {}).get("stage") == "retrying"
                for event in context.emitter.events
            ),
        )

    def test_document_reader_commits_after_invalid_output_retry(self):
        class FlakyServiceClient(FakeBrainClient):
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
                                    ""
                                    if len(self.calls) == 1
                                    else "RECOVERED RESULT"
                                ),
                            },
                        },
                    ],
                }

        class Context:
            pass

        context = Context()
        client = FlakyServiceClient(
            context_window=8192,
        )
        context.clients = {
            "service": client,
        }
        context.runtime_loaded_skills = [
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
                    for index in range(20)
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

        self.assertTrue(
            result["ok"],
        )
        self.assertGreaterEqual(
            len(client.calls),
            2,
        )
        self.assertEqual(
            result["result"],
            "RECOVERED RESULT",
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
        context.runtime_loaded_skills = [
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
        self.assertNotIn(
            "question",
            result,
        )
        self.assertFalse(
            any(
                "What is in the file?" in call["user_prompt"]
                or "USER QUESTION" in call["user_prompt"]
                for call in client.calls
            )
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
        context.runtime_loaded_skills = [
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
            context.runtime_loaded_skills = [
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
            current_result="",
        )
        full = _resolve_reader_budgets(
            context_window=4096,
            output_token_limit=2048,
            instruction="method",
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

    def test_iteration_user_prompt_does_not_include_task_question(self):
        prompt = _build_iteration_user_prompt(
            attachment_name="source.md",
            chunk_index=1,
            chunk={
                "offset": 0,
                "pages_in_chunk": [1],
                "eof": False,
                "text": "source text",
            },
            current_result="current text",
        )

        self.assertNotIn(
            "USER QUESTION",
            prompt,
        )
        self.assertNotIn(
            "Summarize",
            prompt,
        )
        self.assertIn(
            "NEXT SOURCE CHUNK",
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
        context.runtime_loaded_skills = [
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
                    for index in range(600)
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
            600,
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
        context.runtime_loaded_skills = [
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
                runtime_message_id="asset-message-1",
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
        self.assertEqual(
            {
                event.get("runtime_message_id")
                for event in context.emitter.events
                if event.get("type") == "runtime_action"
            },
            {
                "asset-message-1",
            },
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
            context.runtime_loaded_skills = [
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
