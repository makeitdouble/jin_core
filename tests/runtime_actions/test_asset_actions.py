import asyncio
import contextlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from clients.brain_client import apply_runtime_action_calls
from contracts.rules_assembler import (
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_JIN_COLOR,
    get_runtime_action_private_marker,
)
from rules.brain_context_builder import build_loaded_delayed_memory_context
from tests.helpers.runtime_actions import (
    FakeContext,
    FakeEmitter,
    RuntimeActionTestCase,
    legacy_internal_action_marker,
)
from utils.actions import (
    RuntimeActionCall,
    RuntimeActionRepetitionGuard,
    RuntimeActionStreamFilter,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    extract_runtime_actions,
    get_save_active_memory_marker_fields,
    get_save_active_memory_placeholder_payload,
    normalize_jin_color_payload,
    parse_delayed_memory_payload,
)
from utils.assets_utils import run_asset_action
from utils.brain_client_utils import (
    record_delayed_memory_runtime_result,
    flush_pending_active_memory_resolve_failure_history,
)
from utils.context.context_exports import build_tool_results_context
from utils.file_manager_asset_utils import read_asset_text_preview
from utils.runtime_todo import create_runtime_todo
from utils.skills_asset_utils import (
    list_skills,
    normalize_skill_name,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    TOOL_RESULT_KIND_SEARCH,
    begin_runtime_tool_results_turn,
    record_runtime_tool_result,
)



class RuntimeAssetActionTests(RuntimeActionTestCase):

    def test_extracts_asset_action_block(self):

        result = extract_runtime_actions(
            (
                "<ASSET_ACTION>\n"
                '{"action":"list_wildcards"}\n'
                "</ASSET_ACTION>\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload='{"action":"list_wildcards"}',
                ),
            ),
        )


    def test_extracts_asset_action_block_with_args_payload(self):

        result = extract_runtime_actions(
            (
                "<ASSET_ACTION>\n"
                '{"action":"create_wildcard_file","args":{"path":"clothing/test_tops","content":"cropped tank top\\nlace camisole"}}\n'
                "</ASSET_ACTION>\n"
                "Создал файл."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Создал файл.",
        )
        self.assertEqual(
            result.count("ASSET_ACTION"),
            1,
        )
        self.assertNotIn(
            "ASSET_ACTION",
            result.text,
        )


    def test_extracts_asset_action_block_closed_by_repeated_open_tag(self):

        result = extract_runtime_actions(
            (
                "<ASSET_ACTION>\n"
                '{"action":"append_asset_file","path":"assets/outputs/posing_woman_prompts.txt","content":"\\nBatch 1 complete."}\n'
                "<ASSET_ACTION>\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload='{"action":"append_asset_file","path":"assets/outputs/posing_woman_prompts.txt","content":"\\nBatch 1 complete."}',
                ),
            ),
        )


    def test_extracts_asset_action_block_with_spaced_closing_tag(self):

        result = extract_runtime_actions(
            (
                "< ASSET_ACTION >\n"
                '{"action":"append_asset_file","path":"assets/outputs/woman_prompts.txt","content":"Batch 1"}\n'
                "< /ASSET_ACTION >\n"
                "Done."
            ),
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        self.assertEqual(
            result.text,
            "Done.",
        )
        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload='{"action":"append_asset_file","path":"assets/outputs/woman_prompts.txt","content":"Batch 1"}',
                ),
            ),
        )


    def test_empty_asset_action_markers_remain_visible_text(self):

        variants = (
            "<ASSET_ACTION>",
            "<ASSET_ACTION/>",
            "<ASSET_ACTION></ASSET_ACTION>",
            "</ASSET_ACTION>",
            "<ASSET_ACTION>\n   \n</ASSET_ACTION>",
        )

        for marker in variants:
            with self.subTest(marker=marker):
                result = extract_runtime_actions(
                    marker,
                    enabled_actions=[
                        "CAN_USE_ASSETS",
                    ],
                )

                self.assertEqual(
                    result.text,
                    marker,
                )
                self.assertEqual(
                    result.actions,
                    (),
                )
                self.assertEqual(
                    result.removed_markers,
                    (),
                )


    def test_stream_filter_keeps_empty_asset_action_markers_as_text(self):

        variants = (
            ("<ASSET_ACTION>",),
            ("<ASSET_ACTION/>",),
            ("<ASSET_ACTION></ASSET_ACTION>",),
            ("</ASSET_ACTION>",),
            ("<ASSET_ACTION>", "</ASSET_ACTION>"),
            ("<ASSET_ACTION>", "</ASSET", "_ACTION>"),
            ("<ASSET_ACTION>", "< / ASSET", "_ACTION >"),
            ("<ASSET_ACTION>\n", "   \n", "</ASSET_ACTION>"),
        )

        for chunks in variants:
            with self.subTest(chunks=chunks):
                stream_filter = RuntimeActionStreamFilter(
                    enabled_actions=[
                        "CAN_USE_ASSETS",
                    ],
                )
                results = [
                    stream_filter.filter(chunk)
                    for chunk in chunks
                ]
                results.append(
                    stream_filter.flush_result()
                )

                self.assertEqual(
                    "".join(result.text for result in results),
                    "".join(chunks),
                )
                self.assertTrue(
                    all(not result.actions for result in results)
                )
                self.assertTrue(
                    all(not result.started_actions for result in results)
                )
                self.assertTrue(
                    all(not result.removed_markers for result in results)
                )


    def test_stream_filter_does_not_start_asset_action_from_prose_after_open_tag(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_CLEAN_TOOL_RESULTS",
                "CAN_USE_ASSETS",
            ],
        )
        result = stream_filter.filter(
            (
                "<CLEAN_TOOL_RESULTS>\n"
                "<ASSET_ACTION>\n"
                "Продолжаем тест. Следующий маркер – ASSET_ACTION."
            )
        )
        tail = stream_filter.flush_result()

        self.assertEqual(
            result.actions,
            (
                RuntimeActionCall(
                    name="CLEAN_TOOL_RESULTS",
                    payload="",
                ),
            ),
        )
        self.assertEqual(
            result.started_actions,
            (),
        )
        self.assertEqual(
            tail.actions,
            (),
        )
        self.assertIn(
            "<ASSET_ACTION>",
            tail.text,
        )
        self.assertIn(
            "Продолжаем тест.",
            tail.text,
        )


    def test_stream_filter_strips_asset_action_block(self):

        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=[
                "CAN_USE_ASSETS",
            ],
        )

        first = stream_filter.filter(
            (
                "<ASSET_ACTION>\n"
                '{"action":"create_wildcard_file","args":{"path":"clothing/test_tops",'
            )
        )
        second = stream_filter.filter(
            (
                '"content":"cropped tank top\\nlace camisole"}}\n'
                "</ASSET_ACTION>\n"
                "Создал файл."
            )
        )

        self.assertEqual(
            first.text,
            "",
        )
        self.assertEqual(
            first.actions,
            (),
        )
        self.assertEqual(
            second.text,
            "Создал файл.",
        )
        self.assertEqual(
            second.count("ASSET_ACTION"),
            1,
        )
        self.assertEqual(
            first.started_actions,
            (
                RuntimeActionCall(
                    name="ASSET_ACTION",
                    payload="",
                ),
            ),
        )


    def test_stream_filter_strips_asset_action_block_boundary_variants(self):

        variants = [
            [
                (
                    "<ASSET_ACTION>\n"
                    '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n'
                    "</ASSET_ACTION>"
                ),
            ],
            [
                "<AS",
                "SET_ACTION>\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "</ASSET_ACTION>",
            ],
            [
                "\n\n  <ASSET_ACTION>\n",
                '{\n  "action": "create_wildcard_file",\n  "args": {\n    "path": "clothing/shoes",\n    "content": "sneakers\\nboots"\n  }\n}\n',
                "</ASSET_ACTION>\n",
            ],
            [
                "<ASSET_ACTION>\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "<ASSET_ACTION>\n",
            ],
            [
                "< ASSET_ACTION >\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "< / ASSET_ACTION >\n",
            ],
            [
                "<ASSET_ACTION>\n",
                '{"action":"create_wildcard_file","args":{"path":"clothing/shoes","content":"sneakers\\nboots"}}\n',
                "< /ASSET_ACTION>\n",
            ],
        ]

        for chunks in variants:
            with self.subTest(chunks=chunks):
                stream_filter = RuntimeActionStreamFilter(
                    enabled_actions=[
                        "CAN_USE_ASSETS",
                    ],
                )
                visible_text = []
                actions = []

                for chunk in chunks:
                    result = stream_filter.filter(
                        chunk
                    )
                    visible_text.append(
                        result.text
                    )
                    actions.extend(
                        result.actions
                    )

                tail = stream_filter.flush_result()
                visible_text.append(
                    tail.text
                )
                actions.extend(
                    tail.actions
                )

                joined_visible_text = "".join(
                    visible_text
                )

                self.assertNotIn(
                    "ASSET_ACTION",
                    joined_visible_text,
                )
                self.assertEqual(
                    joined_visible_text.strip(),
                    "",
                )
                self.assertEqual(
                    len(actions),
                    1,
                )
                self.assertEqual(
                    actions[0].name,
                    "ASSET_ACTION",
                )


    def test_apply_runtime_action_calls_runs_asset_action(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "path": "clothing/test_tops",
                        "lines": [
                            "linen shirt",
                            "wool sweater",
                        ],
                    }
                )

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                output_path = (
                    root
                    / "assets"
                    / "wildcards"
                    / "clothing"
                    / "test_tops.txt"
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "linen shirt\nwool sweater\n",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["line_count"],
                    2,
                )
                self.assertEqual(
                    context.emitter.events[0]["action"],
                    "asset_action",
                )
                self.assertEqual(
                    context.emitter.events[0]["id"],
                    "create_wildcard_file_001",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    (
                        "ASSET_ACTION: create_wildcard_file - "
                        "assets/wildcards/clothing/test_tops.txt"
                    ),
                )
                self.assertTrue(
                    context.emitter.events[0]["close_tag"],
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertEqual(
                    context.emitter.events[1]["action"],
                    "asset_action",
                )
                self.assertEqual(
                    context.emitter.events[1]["id"],
                    "create_wildcard_file_001",
                )
                self.assertEqual(
                    context.emitter.events[1]["text"],
                    "Created wildcard file - assets/wildcards/clothing/test_tops.txt",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "completed",
                )
                self.assertEqual(
                    len(context.emitter.events),
                    2,
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "Created wildcard file - assets/wildcards/clothing/test_tops.txt",
                )
                self.assertIsInstance(
                    context.runtime_session_action_history[0]["created_at"],
                    float,
                )


    def test_failed_create_asset_file_preserves_payload_for_retry(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "gemma.txt"
                )
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                output_path.write_text(
                    "old text\n",
                    encoding="utf-8",
                )

                context = Context()
                context.emitter = Emitter()
                context.runtime_current_turn_id = "turn_000001"
                payload_data = {
                    "action": "create_asset_file",
                    "path": "assets/outputs/gemma.txt",
                    "content": "new text",
                }
                payload = json.dumps(
                    payload_data
                )

                asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                result = context.runtime_asset_results[0]
                self.assertFalse(
                    result["ok"],
                )
                self.assertEqual(
                    result["error"],
                    "file_exists",
                )
                self.assertEqual(
                    result["payload"],
                    payload_data,
                )
                self.assertEqual(
                    result["runtime_turn_id"],
                    "turn_000001",
                )
                self.assertEqual(
                    context.runtime_asset_retry_results,
                    [result],
                )
                self.assertIsNot(
                    context.runtime_asset_retry_results[0],
                    result,
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "old text\n",
                )


    def test_create_asset_file_emits_started_with_path_before_completed(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_asset_file",
                        "path": "assets/outputs/rain_script.py",
                        "content": "print('rain')",
                    }
                )

                asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    len(context.emitter.events),
                    2,
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    (
                        "ASSET_ACTION: create_asset_file - "
                        "assets/outputs/rain_script.py"
                    ),
                )
                self.assertTrue(
                    context.emitter.events[0]["close_tag"],
                )
                self.assertEqual(
                    context.emitter.events[0]["id"],
                    "create_asset_file_001",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "completed",
                )
                self.assertEqual(
                    context.emitter.events[1]["id"],
                    "create_asset_file_001",
                )


    def test_apply_runtime_action_calls_runs_asset_action_args_payload(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "args": {
                            "path": "clothing/test_tops",
                            "content": "cropped tank top\nlace camisole",
                        },
                    }
                )

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                output_path = (
                    root
                    / "assets"
                    / "wildcards"
                    / "clothing"
                    / "test_tops.txt"
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "cropped tank top\nlace camisole\n",
                )


    def test_create_and_append_asset_file_actions_stay_inside_assets(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                create_result = run_asset_action(json.dumps({
                    "action": "create_asset_file",
                    "path": "assets/outputs/test_notes",
                    "content": "first line\nsecond line",
                }))
                append_result = run_asset_action(json.dumps({
                    "action": "append_asset_file",
                    "path": "assets/outputs/test_notes",
                    "content": "third line",
                }))

                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "test_notes.txt"
                )

                self.assertTrue(
                    create_result["ok"],
                )
                self.assertEqual(
                    create_result["path"],
                    "assets/outputs/test_notes.txt",
                )
                self.assertTrue(
                    append_result["ok"],
                )
                self.assertEqual(
                    append_result["line_count"],
                    3,
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "first line\nsecond line\nthird line\n",
                )


    def test_read_asset_text_preview_returns_attachment_modal_payload(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_asset_file",
                    "path": "assets/outputs/test_notes",
                    "content": "first line\nsecond line",
                }))

                result = read_asset_text_preview({
                    "path": "assets/outputs/test_notes.txt",
                    "max_chars": 8,
                })

                self.assertTrue(
                    result["ok"],
                )
                self.assertEqual(
                    result["kind"],
                    "text",
                )
                self.assertEqual(
                    result["path"],
                    "assets/outputs/test_notes.txt",
                )
                self.assertEqual(
                    result["text_content"],
                    "first li",
                )
                self.assertTrue(
                    result["truncated"],
                )


    def test_create_asset_file_content_preserves_indentation(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                content = (
                    "def generate_rain_sound():\n"
                    "    print(\"start\")\n"
                    "    if True:\n"
                    "        print(\"nested\")\n"
                    "\n"
                    "if __name__ == \"__main__\":\n"
                    "    generate_rain_sound()\n"
                )
                result = run_asset_action(json.dumps({
                    "action": "create_asset_file",
                    "path": "assets/outputs/rain_script.py",
                    "content": content,
                }))
                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "rain_script.py"
                )

                self.assertTrue(
                    result["ok"],
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    content,
                )
                self.assertEqual(
                    result["examples"][1],
                    "    print(\"start\")",
                )


    def test_append_asset_file_content_preserves_existing_formatting(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                output_path = (
                    root
                    / "assets"
                    / "outputs"
                    / "script.py"
                )
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                output_path.write_text(
                    "def main():\n"
                    "    print(\"before\")",
                    encoding="utf-8",
                )

                result = run_asset_action(json.dumps({
                    "action": "append_asset_file",
                    "path": "assets/outputs/script.py",
                    "content": (
                        "    print(\"after\")\n"
                        "    return True\n"
                    ),
                }))

                self.assertTrue(
                    result["ok"],
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    (
                        "def main():\n"
                        "    print(\"before\")\n"
                        "    print(\"after\")\n"
                        "    return True\n"
                    ),
                )


    def test_generate_prompt_batch_expands_wildcards_and_accepts_assets_prompts_path(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_tops",
                    "lines": [
                        "linen shirt",
                    ],
                }))
                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_bottoms",
                    "lines": [
                        "black skirt",
                    ],
                }))

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 2,
                    "template": "woman wearing __clothing/test_tops__ and __clothing/test_bottoms__, studio lighting.",
                    "path": "assets/prompts/test_prompts.txt",
                }))

                self.assertTrue(
                    result.get("ok"),
                    result,
                )
                output_path = (
                    root
                    / "assets"
                    / "prompts"
                    / "test_prompts.txt"
                )
                self.assertTrue(
                    output_path.exists(),
                )
                self.assertFalse(
                    (root / "assets" / "prompts" / "assets").exists(),
                )
                self.assertFalse(
                    (root / "assets" / "wildcards" / "assets").exists(),
                )
                content = output_path.read_text(encoding="utf-8")
                self.assertEqual(
                    content,
                    (
                        "woman wearing linen shirt and black skirt, studio lighting.\n"
                        "woman wearing linen shirt and black skirt, studio lighting.\n"
                    ),
                )
                self.assertNotIn(
                    "__clothing/",
                    content,
                )


    def test_generate_prompt_batch_overwrites_existing_prompt_file_by_default(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_tops",
                    "lines": [
                        "linen shirt",
                    ],
                }))

                output_path = (
                    root
                    / "assets"
                    / "prompts"
                    / "test_prompts.txt"
                )
                output_path.parent.mkdir(
                    parents=True,
                    exist_ok=True,
                )
                output_path.write_text(
                    "old prompt\n",
                    encoding="utf-8",
                )

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 1,
                    "template": "woman wearing __clothing/test_tops__",
                    "path": "assets/prompts/test_prompts.txt",
                }))

                self.assertTrue(
                    result.get("ok"),
                    result,
                )
                self.assertEqual(
                    result.get("path"),
                    "assets/prompts/test_prompts.txt",
                )
                self.assertEqual(
                    output_path.read_text(encoding="utf-8"),
                    "woman wearing linen shirt\n",
                )
                self.assertFalse(
                    (
                        root
                        / "assets"
                        / "prompts"
                        / "test_prompts_002.txt"
                    ).exists(),
                )


    def test_generate_prompt_batch_still_accepts_output_file_alias(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "clothing/test_tops",
                    "lines": [
                        "linen shirt",
                    ],
                }))

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 1,
                    "template": "woman wearing __clothing/test_tops__",
                    "output_file": "assets/prompts/legacy_prompts.txt",
                }))

                self.assertTrue(
                    result.get("ok"),
                    result,
                )
                self.assertEqual(
                    result.get("path"),
                    "assets/prompts/legacy_prompts.txt",
                )


    def test_generate_prompt_batch_reports_missing_wildcards(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                result = run_asset_action(json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 2,
                    "template": "woman wearing __clothing/missing_tops__",
                    "path": "assets/prompts/test_prompts.txt",
                }))

                self.assertFalse(
                    result.get("ok"),
                )
                self.assertEqual(
                    result.get("error"),
                    "missing_wildcards",
                )
                self.assertEqual(
                    result.get("missing", [])[0].get("wildcard"),
                    "clothing/missing_tops",
                )


    def test_failed_generate_prompt_batch_runtime_bubble_shows_failed(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps({
                    "action": "generate_prompt_batch",
                    "count": 2,
                    "template": "woman wearing __clothing/missing_tops__",
                    "path": "assets/prompts/test_prompts.txt",
                })

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    (
                        "ASSET_ACTION: generate_prompt_batch - "
                        "assets/prompts/test_prompts.txt"
                    ),
                )
                self.assertTrue(
                    context.emitter.events[0]["close_tag"],
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertEqual(
                    context.emitter.events[1]["text"],
                    "Generated prompt batch - failed: missing_wildcards",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "failed",
                )
                self.assertEqual(
                    len(context.emitter.events),
                    2,
                )
                self.assertEqual(
                    context.runtime_session_action_history[0]["text"],
                    "Generated prompt batch - failed: missing_wildcards",
                )
                self.assertIsInstance(
                    context.runtime_session_action_history[0]["created_at"],
                    float,
                )


    def test_invalid_asset_action_payload_emits_failed_runtime_action(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload="not json",
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["ok"],
                    False,
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["error"],
                    "invalid_json",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "ASSET_ACTION: invalid payload",
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertIn(
                    "Asset action - invalid payload - failed: invalid_json",
                    context.emitter.events[1]["text"],
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "failed",
                )


    def test_unknown_asset_action_names_specific_operation_in_bubble(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                payload = json.dumps(
                    {
                        "action": "analyze_image",
                        "asset_id": "image.png",
                    }
                )

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "ASSET_ACTION: analyze_image",
                )
                self.assertEqual(
                    context.emitter.events[1]["text"],
                    (
                        "Asset action - failed: "
                        "unknown_asset_action: analyze_image"
                    ),
                )


    def test_asset_action_reuses_stream_pending_id_for_specific_bubble(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                context.runtime_pending_asset_action_ids = [
                    "asset_action_001",
                ]
                payload = json.dumps(
                    {
                        "action": "analyze_image",
                        "asset_id": "image.png",
                    }
                )

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        (
                            RuntimeActionCall(
                                name="ASSET_ACTION",
                                payload=payload,
                            ),
                        ),
                    )
                )

                self.assertEqual(
                    applied_count,
                    1,
                )
                self.assertEqual(
                    context.runtime_pending_asset_action_ids,
                    [],
                )
                self.assertEqual(
                    context.emitter.events[0]["id"],
                    "asset_action_001",
                )
                self.assertEqual(
                    context.emitter.events[0]["text"],
                    "ASSET_ACTION: analyze_image",
                )
                self.assertEqual(
                    context.emitter.events[0]["status"],
                    "started",
                )
                self.assertEqual(
                    context.emitter.events[1]["id"],
                    "asset_action_001",
                )
                self.assertEqual(
                    context.emitter.events[1]["status"],
                    "failed",
                )


    def test_create_wildcard_file_rejects_assets_prompts_path(self):

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                result = run_asset_action(json.dumps({
                    "action": "create_wildcard_file",
                    "path": "assets/prompts/test_prompts.txt",
                    "lines": [
                        "bad prompt",
                    ],
                }))

                self.assertFalse(
                    result.get("ok"),
                )
                self.assertEqual(
                    result.get("error"),
                    "ValueError",
                )
                self.assertFalse(
                    (root / "assets" / "wildcards" / "assets").exists(),
                )

