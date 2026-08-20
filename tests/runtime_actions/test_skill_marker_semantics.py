import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path

from clients.brain_client import apply_runtime_action_calls
from tests.helpers.runtime_actions import (
    FakeContext,
    FakeEmitter,
    RuntimeActionTestCase,
)
from utils.actions import (
    RuntimeActionCall,
    RuntimeActionCounter,
    extract_runtime_actions,
)
from utils.session_actions_history import (
    compact_session_action_history_since,
    format_session_action_marker_names,
    upsert_session_action_marker_history_since,
)


ROOT = Path(__file__).resolve().parents[2]
LOGGER_JS = ROOT / "ui" / "static" / "js" / "logger" / "log-entries.js"
RUNTIME_ACTIONS_JS = (
    ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
)
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class SkillMarkerSemanticsTests(RuntimeActionTestCase):

    def _write_skills(self, root, *names):
        for name in names:
            self.write_skill_fixture(
                root,
                f"{name}.txt",
                f"{name}\nTest skill.",
            )

    def test_plural_load_skills_is_one_uncounted_marker(self):
        marker = "<LOAD_SKILLS: file_manager, wildcards, porn>"
        parsed = extract_runtime_actions(
            marker,
            enabled_actions=["CAN_USE_ASSETS"],
        )

        self.assertEqual(
            [(action.name, action.payload) for action in parsed.observed_actions],
            [
                (
                    "LOAD_SKILLS",
                    "file_manager, wildcards, porn",
                ),
            ],
        )

        counter = RuntimeActionCounter()
        self.assertEqual(
            counter.record(parsed.observed_actions),
            (),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self._write_skills(
                    root,
                    "file_manager",
                    "wildcards",
                    "porn",
                )
                context = FakeContext()
                context.emitter = FakeEmitter()
                context.runtime_current_turn_id = "turn-1"

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        parsed.actions,
                        runtime_message_id="message-1",
                    )
                )

        self.assertEqual(applied_count, 3)
        self.assertEqual(len(context.emitter.events), 2)
        self.assertEqual(
            {event["action"] for event in context.emitter.events},
            {"load_skills"},
        )
        self.assertEqual(
            {event["id"] for event in context.emitter.events},
            {context.emitter.events[0]["id"]},
        )
        self.assertEqual(
            {event["text"] for event in context.emitter.events},
            {"LOAD_SKILLS: file_manager, wildcards, porn"},
        )
        self.assertTrue(
            all("marker_count" not in event for event in context.emitter.events)
        )
        self.assertTrue(
            all("counter_only" not in event for event in context.emitter.events)
        )
        self.assertEqual(
            [item["text"] for item in context.runtime_session_action_history],
            ["LOAD_SKILLS: file_manager, wildcards, porn"],
        )

    def test_singular_load_skill_markers_stay_separate_without_counter(self):
        parsed = extract_runtime_actions(
            (
                "<LOAD_SKILL: wildcards>\n"
                "<LOAD_SKILL: porn>"
            ),
            enabled_actions=["CAN_USE_ASSETS"],
        )
        counter = RuntimeActionCounter()

        self.assertEqual(
            counter.record(parsed.observed_actions),
            (),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with contextlib.ExitStack() as stack:
                for patcher in self.patch_asset_roots(root):
                    stack.enter_context(patcher)

                self._write_skills(root, "wildcards", "porn")
                context = FakeContext()
                context.emitter = FakeEmitter()
                context.runtime_current_turn_id = "turn-1"

                applied_count = asyncio.run(
                    apply_runtime_action_calls(
                        context,
                        parsed.actions,
                        runtime_message_id="message-1",
                    )
                )

        completed_events = [
            event
            for event in context.emitter.events
            if event.get("status") == "completed"
        ]
        self.assertEqual(applied_count, 2)
        self.assertEqual(
            [event["text"] for event in completed_events],
            [
                "LOAD_SKILL: wildcards",
                "LOAD_SKILL: porn",
            ],
        )
        self.assertEqual(
            len({event["id"] for event in completed_events}),
            2,
        )
        self.assertTrue(
            all("marker_count" not in event for event in context.emitter.events)
        )
        self.assertFalse(
            compact_session_action_history_since(context, 0)
        )
        self.assertEqual(
            [item["text"] for item in context.runtime_session_action_history],
            [
                "LOAD_SKILL: wildcards",
                "LOAD_SKILL: porn",
            ],
        )

    def test_counter_groups_only_identical_marker_payloads(self):
        counter = RuntimeActionCounter()
        counter.record([
            RuntimeActionCall(name="LIST_SKILLS"),
            RuntimeActionCall(name="LIST_SKILLS"),
            RuntimeActionCall(name="WEB_SEARCH", payload="alpha"),
            RuntimeActionCall(name="WEB_SEARCH", payload="beta"),
            RuntimeActionCall(name="WEB_SEARCH", payload="alpha"),
            RuntimeActionCall(name="LOAD_SKILL", payload="wildcards"),
            RuntimeActionCall(name="LOAD_SKILL", payload="porn"),
        ])

        self.assertEqual(
            [
                (entry.name, entry.identity, entry.count)
                for entry in counter.entries()
            ],
            [
                ("LIST_SKILLS", "", 2),
                ("WEB_SEARCH", "alpha", 2),
                ("WEB_SEARCH", "beta", 1),
            ],
        )
        self.assertEqual(
            format_session_action_marker_names(counter.marker_actions()),
            (
                "LIST_SKILLS (count: 2), "
                "WEB_SEARCH - alpha (count: 2), "
                "WEB_SEARCH - beta"
            ),
        )

    def test_visual_marker_sequence_keeps_jin_size_and_color(self):
        counter = RuntimeActionCounter()
        counter.record([
            RuntimeActionCall(name="JIN_SIZE", payload="120px 120px"),
            RuntimeActionCall(name="JIN_COLOR", payload="#ff69b4"),
        ])

        marker_actions = counter.marker_actions(
            display_payloads={
                "JIN_SIZE": ["120px"],
                "JIN_COLOR": ["#ff69b4"],
            },
        )

        self.assertEqual(
            format_session_action_marker_names(marker_actions),
            "JIN_SIZE - 120px, JIN_COLOR",
        )

    def test_active_memory_marker_history_keeps_payloads_separate(self):
        counter = RuntimeActionCounter()
        counter.record([
            RuntimeActionCall(
                name="SAVE_ACTIVE_MEMORY",
                payload="remember tea",
            ),
            RuntimeActionCall(
                name="SAVE_ACTIVE_MEMORY",
                payload="remember coffee",
            ),
        ])

        context = FakeContext()
        context.runtime_current_turn_id = "turn-1"

        self.assertTrue(
            upsert_session_action_marker_history_since(
                context,
                0,
                counter.marker_actions(),
            )
        )
        self.assertEqual(
            [
                item["text"]
                for item in context.runtime_session_action_history
            ],
            [
                "SAVE_ACTIVE_MEMORY - remember tea",
                "SAVE_ACTIVE_MEMORY - remember coffee",
            ],
        )
        self.assertTrue(
            all(
                item.get("runtime_session_action_preserve_separate")
                for item in context.runtime_session_action_history
            )
        )
        self.assertFalse(
            compact_session_action_history_since(
                context,
                0,
            )
        )

    def test_skill_marker_ui_contract_keeps_rows_separate_and_uncounted(self):
        logger_source = LOGGER_JS.read_text(encoding="utf-8")
        runtime_source = RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        index_source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("keepSkillMarkerSeparate", logger_source)
        self.assertIn('"LOAD_SKILLS"', logger_source)
        self.assertIn('"load_skills"', runtime_source)
        self.assertIn("suppressMarkerCount", runtime_source)
        self.assertRegex(
            index_source,
            r'/static/js/logger/log-entries\.js\?v=[^"\s]+',
        )
        self.assertRegex(
            index_source,
            r'/static/js/socket/runtime-actions\.js\?v=[^"\s]+',
        )


if __name__ == "__main__":
    unittest.main()
