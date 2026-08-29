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
    extract_active_memory_delete_slot_id,
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
    flush_pending_active_memory_delete_failure_history,
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



class RuntimeTodoActionTests(RuntimeActionTestCase):

    def test_asset_action_writes_actual_path_back_to_runtime_todo(self):

        Emitter = FakeEmitter

        Context = FakeContext

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                context = Context()
                context.emitter = Emitter()
                create_runtime_todo(
                    context,
                    "1. Создать новый файл-вайлдкард `assets/wildcards/shoes/` с 10 видами обуви.",
                )

                payload = json.dumps(
                    {
                        "action": "create_wildcard_file",
                        "path": "assets/wildcards/shoes/",
                        "lines": [
                            "sneakers",
                            "boots",
                        ],
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
                    context.runtime_todo[0]["status"],
                    "resolved",
                )
                self.assertEqual(
                    context.runtime_todo[0]["result_path"],
                    "assets/wildcards/shoes.txt",
                )
                self.assertEqual(
                    context.runtime_asset_results[0]["runtime_todo_item"]["result_path"],
                    "assets/wildcards/shoes.txt",
                )

