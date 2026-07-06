import unittest
from dataclasses import dataclass, field

from clients.brain_context_builder import append_current_runtime_todo
from clients.brain_client import build_brain_context_snapshot
from utils.runtime_actions import RuntimeActionStreamFilter, extract_runtime_actions
from utils.runtime_todo import (
    apply_runtime_todo_action_result,
    check_runtime_todo_item,
    create_runtime_todo,
    normalize_file_exists_for_runtime_todo,
    parse_runtime_todo_payload,
    resolve_runtime_todo_item,
)
from rules.assembler import (
    BRAIN_RUNTIME_ACTIONS,
    build_brain_system_prompt,
    get_enabled_runtime_actions,
)


@dataclass
class DummyContext:
    runtime_todo: list[dict] = field(default_factory=list)


class RuntimeTodoTests(unittest.TestCase):
    def enabled_actions_with_runtime_todo(self):
        return (
            *get_enabled_runtime_actions(BRAIN_RUNTIME_ACTIONS),
            "CREATE_TODO_LIST",
            "RESOLVE_TODO",
            "CHECK_TODO",
        )

    def test_extract_create_todo_block_with_next_action(self):
        enabled_actions = self.enabled_actions_with_runtime_todo()
        result = extract_runtime_actions(
            "<TODO_LIST>\n"
            "1. LIST_SKILLS\n"
            "2. APPEND_SKILL wildcards\n"
            "</TODO_LIST>\n"
            "<INTERNAL_ACTION_LIST_SKILLS>",
            enabled_actions=enabled_actions,
        )

        self.assertEqual(result.text.strip(), "")
        self.assertEqual(
            [(action.name, action.payload) for action in result.actions],
            [
                ("CREATE_TODO_LIST", "1. LIST_SKILLS\n2. APPEND_SKILL wildcards"),
                ("LIST_SKILLS", ""),
            ],
        )



    def test_extract_internal_action_todo_list_alias_block(self):
        enabled_actions = self.enabled_actions_with_runtime_todo()
        result = extract_runtime_actions(
            "<INTERNAL_ACTION_TODO_LIST>\n"
            "1. Create wildcard file assets/wildcards/clothing/shoes.txt with 10 shoe types.\n"
            "2. Generate prompt batch and save it.\n"
            "</INTERNAL_ACTION_TODO_LIST>\n"
            "<INTERNAL_ACTION_ASSET_ACTION>\n"
            "create_wildcard_file\n"
            "</INTERNAL_ACTION_ASSET_ACTION>",
            enabled_actions=enabled_actions,
        )

        self.assertEqual(result.text.strip(), "")
        self.assertEqual(
            [(action.name, action.payload) for action in result.actions],
            [
                (
                    "CREATE_TODO_LIST",
                    "1. Create wildcard file assets/wildcards/clothing/shoes.txt with 10 shoe types.\n"
                    "2. Generate prompt batch and save it.",
                ),
                ("ASSET_ACTION", "create_wildcard_file"),
            ],
        )


    def test_stream_filter_extracts_plain_todo_list_block(self):
        enabled_actions = self.enabled_actions_with_runtime_todo()
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=enabled_actions,
        )

        result = stream_filter.filter(
            "<TODO_LIST>\n"
            "1. Create a new wildcard file named 'shoes' in the assets/wildcards/clothing directory\n"
            "containing 10 shoe types.\n"
            "2. Generate 10 expanded prompts.\n"
            "3. Save the final list.\n"
            "</TODO_LIST>"
        )

        self.assertEqual(result.text.strip(), "")
        self.assertEqual(
            [(action.name, action.payload) for action in result.actions],
            [
                (
                    "CREATE_TODO_LIST",
                    "1. Create a new wildcard file named 'shoes' in the assets/wildcards/clothing directory\n"
                    "containing 10 shoe types.\n"
                    "2. Generate 10 expanded prompts.\n"
                    "3. Save the final list.",
                ),
            ],
        )

    def test_stream_filter_extracts_plain_todo_list_across_chunks(self):
        enabled_actions = self.enabled_actions_with_runtime_todo()
        stream_filter = RuntimeActionStreamFilter(
            enabled_actions=enabled_actions,
        )

        first = stream_filter.filter("<TODO")
        second = stream_filter.filter("_LIST>\n1. Create file.\n")
        third = stream_filter.filter("2. Save file.\n</TODO_LIST>")

        self.assertEqual(first.text, "")
        self.assertEqual(first.actions, ())
        self.assertEqual(second.text, "")
        self.assertEqual(second.actions, ())
        self.assertEqual(third.text.strip(), "")
        self.assertEqual(
            [(action.name, action.payload) for action in third.actions],
            [("CREATE_TODO_LIST", "1. Create file.\n2. Save file.")],
        )

    def test_todo_list_ignores_headings_and_plain_lines(self):
        items = parse_runtime_todo_payload(
            "TODO ID 1: Wrong heading\n"
            "Steps:\n"
            "1. Create file shoes.txt\n"
            "2. Save prompts\n"
            "plain explanation should not become item"
        )

        self.assertEqual(
            items,
            [
                {"id": 1, "text": "Create file shoes.txt", "status": "pending"},
                {"id": 2, "text": "Save prompts", "status": "pending"},
            ],
        )

    def test_parse_todo_list_with_wrapped_item_line(self):
        payload = (
            "1. Create a new wildcard file in assets/wildcards/clothing/shoes.txt "
            "containing 10 types of shoes.\n"
            "2. Generate 10 prompts using the template \"photo of a woman "
            "wearing [RANDOM_TOP] and [RANDOM\n"
            "BOTTOM] and [RANDOM_SHOES], studio lighting\" and save them "
            "to assets/prompts/test_prompts.txt."
        )

        items = parse_runtime_todo_payload(payload)

        self.assertEqual(len(items), 2)
        self.assertEqual(
            items[1],
            {
                "id": 2,
                "text": (
                    "Generate 10 prompts using the template \"photo of a woman "
                    "wearing [RANDOM_TOP] and [RANDOM BOTTOM] and "
                    "[RANDOM_SHOES], studio lighting\" and save them "
                    "to assets/prompts/test_prompts.txt."
                ),
                "status": "pending",
            },
        )

    def test_parse_and_update_runtime_todo(self):
        context = DummyContext()
        created = create_runtime_todo(
            context,
            "1. LIST_SKILLS\n2. Create shoes wildcard file",
        )
        self.assertTrue(created["ok"])
        self.assertEqual(len(context.runtime_todo), 2)

        checked = check_runtime_todo_item(context, 2)
        self.assertTrue(checked["ok"])
        self.assertEqual(context.runtime_todo[1]["status"], "checking")

        resolved = resolve_runtime_todo_item(context, 2)
        self.assertTrue(resolved["ok"])
        self.assertEqual(context.runtime_todo[1]["status"], "done")

    def test_current_runtime_todo_context_xml(self):
        context = DummyContext(
            runtime_todo=parse_runtime_todo_payload("1. LIST_SKILLS\n2. Save file")
        )
        parts = []
        append_current_runtime_todo(parts, context)
        rendered = "\n".join(parts)

        self.assertIn("<CURRENT_RUNTIME_TODO_LIST>", rendered)
        self.assertIn('<ITEM id="1" status="pending">LIST_SKILLS</ITEM>', rendered)
        self.assertIn('<ITEM id="2" status="pending">Save file</ITEM>', rendered)

    def test_context_snapshot_hides_internal_action_rules_when_todo_active(self):
        context = DummyContext(
            runtime_todo=parse_runtime_todo_payload("1. Generate prompt batch")
        )
        system_prompt = build_brain_system_prompt(
            context,
            runtime_actions=BRAIN_RUNTIME_ACTIONS,
        )

        snapshot = build_brain_context_snapshot(
            context=context,
            system_prompt=system_prompt,
            user_prompt="generate prompts",
            runtime_actions=BRAIN_RUNTIME_ACTIONS,
        )

        self.assertTrue(
            snapshot["hide_internal_action_rules"],
        )
        self.assertIn(
            "Runtime Actions are internal mechanics",
            snapshot["system_prompt"],
        )
        self.assertNotIn(
            "Runtime Actions are internal mechanics",
            snapshot["visible_system_prompt"],
        )
        self.assertNotIn(
            "SAVE_SESSION: high priority action",
            snapshot["visible_system_prompt"],
        )
        self.assertIn(
            "<CURRENT_RUNTIME_TODO_LIST>",
            snapshot["visible_system_prompt"],
        )


    def test_action_result_path_is_added_to_runtime_todo_context(self):
        context = DummyContext()
        create_runtime_todo(
            context,
            "1. Создать новый файл-вайлдкард `assets/wildcards/shoes/` с 10 видами обуви.",
        )

        updated_item = apply_runtime_todo_action_result(
            context,
            context.runtime_todo[0],
            {
                "ok": True,
                "action": "create_wildcard_file",
                "path": "assets/wildcards/shoes.txt",
                "line_count": 10,
            },
        )

        self.assertIsNotNone(updated_item)
        self.assertEqual(context.runtime_todo[0]["status"], "resolved")
        self.assertEqual(
            context.runtime_todo[0]["result_path"],
            "assets/wildcards/shoes.txt",
        )
        self.assertEqual(
            context.runtime_todo[0]["result_action"],
            "create_wildcard_file",
        )

        parts = []
        append_current_runtime_todo(parts, context)
        rendered = "\n".join(parts)

        self.assertIn(
            'actual_path="assets/wildcards/shoes.txt"',
            rendered,
        )
        self.assertIn(
            'result_action="create_wildcard_file"',
            rendered,
        )

    def test_failed_action_result_does_not_leave_todo_resolved(self):
        context = DummyContext()
        create_runtime_todo(context, "1. Generate prompt batch")

        apply_runtime_todo_action_result(
            context,
            context.runtime_todo[0],
            {
                "ok": False,
                "action": "generate_prompt_batch",
                "error": "missing_wildcards",
                "missing": [
                    {
                        "wildcard": "shoes",
                        "path": "assets/wildcards/shoes.txt",
                    }
                ],
            },
        )

        self.assertEqual(context.runtime_todo[0]["status"], "failed")
        self.assertEqual(
            context.runtime_todo[0]["result_path"],
            "assets/wildcards/shoes.txt",
        )
        self.assertEqual(
            context.runtime_todo[0]["result_error"],
            "missing_wildcards",
        )

    def test_file_exists_satisfies_active_todo(self):
        context = DummyContext()
        create_runtime_todo(context, "1. Ensure shoes wildcard file exists")
        result = normalize_file_exists_for_runtime_todo(
            {
                "ok": False,
                "action": "create_wildcard_file",
                "error": "file_exists",
                "path": "assets/wildcards/clothing/shoes.txt",
            },
            context,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["status"], "noop_file_already_exists")
        self.assertTrue(result["satisfies_todo"])
        self.assertNotIn("error", result)


if __name__ == "__main__":
    unittest.main()
