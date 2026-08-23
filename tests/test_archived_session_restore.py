import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from agent.nodes.brain import replay_session_restore_resource_actions
from rules.brain_context_builder import build_brain_context
from rules.runtime import SESSION_RESTORE_MESSAGE
from runtime.client import RuntimeClient
from runtime.runtime_context import RuntimeContext
from utils.context.session_actions import build_session_actions_history_context
from utils.context.tool_results import build_tool_results_context
from utils.session_actions_history import record_session_action_history
from utils.session_restore import build_archived_session_restore_payload
from websocket.bootstrap import (
    apply_archived_session_continuation_state,
    apply_session_bootstrap,
    enrich_session_bootstrap_from_archive,
)


class ArchivedSessionRestoreTests(unittest.TestCase):

    def test_archived_restore_keeps_fresh_runtime_session_identity(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
            session_id="fresh-session",
        )

        apply_archived_session_continuation_state(
            context,
            {
                "source_session_id": "archived-session",
                "source_session_date": "2026-08-18",
                "archived_session_restore": True,
            },
        )

        self.assertEqual(context.session_id, "fresh-session")
        self.assertEqual(
            context.runtime_archived_session_id,
            "archived-session",
        )
        self.assertTrue(context.runtime_session_restore_priming)
        self.assertFalse(
            hasattr(
                context,
                "runtime_chat_log_bootstrap_reference_path",
            )
        )

    def test_archived_bootstrap_preserves_saved_runtime_lifecycle_timestamps(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
            session_id="fresh-session",
        )
        saved_snapshot_timestamp = "2026-08-20T19:14:16+03:00"
        saved_created_at = "2026-08-20T16:14:16+00:00"

        restored = apply_session_bootstrap(
            context,
            {
                "type": "session_bootstrap",
                "source_session_id": "archived-session",
                "archived_session_restore": True,
                "runtime_memory": (
                    "user_message: old message [ created: 2s ago ]"
                ),
                "runtime_memory_updates": 7,
                "runtime_snapshot": {
                    "index": 4,
                    "timestamp": saved_snapshot_timestamp,
                    "created_at": saved_created_at,
                    "raw_memory": "user_message: old message",
                    "lines": [
                        {
                            "key": "user_message",
                            "value": "old message",
                            "status": "same",
                            "created_at": saved_created_at,
                            "updated_at": "",
                            "memory_lifecycle_status": "created",
                        }
                    ],
                },
            },
        )

        self.assertTrue(restored)
        self.assertEqual(
            context.runtime_memory,
            "user_message: old message",
        )
        snapshot = context.runtime_memory_snapshots[0]
        self.assertEqual(snapshot["index"], 0)
        self.assertEqual(
            snapshot["timestamp"],
            saved_snapshot_timestamp,
        )
        self.assertEqual(
            snapshot["created_at"],
            saved_created_at,
        )
        self.assertEqual(
            snapshot["lines"][0]["created_at"],
            saved_created_at,
        )
        self.assertEqual(
            snapshot["session_id"],
            "archived-session",
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )
        self.assertIn(
            'session_id="archived-session"',
            prompt,
        )
        self.assertNotIn(
            'session_id="fresh-session"',
            prompt,
        )

    def test_browser_only_predecessor_does_not_prime_archive_restore(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
            session_id="fresh-session",
        )

        apply_archived_session_continuation_state(
            context,
            {
                "source_session_id": "browser-only-session",
                "archived_session_restore": False,
            },
        )

        self.assertEqual(context.session_id, "fresh-session")
        self.assertEqual(context.runtime_archived_session_id, "")
        self.assertFalse(context.runtime_session_restore_priming)

    def _build_fixture(self):
        root = Path(tempfile.mkdtemp())
        session_id = "d6170547-ea4a-4ad3-9502-fb204963c011"
        session_dir = root / "2026-08-16" / session_id
        reasoning_dir = session_dir / "reasoning"
        reasoning_dir.mkdir(parents=True)

        entries = [
            {
                "ts": "2026-08-16T23:05:18+03:00",
                "turn": 5,
                "turn_id": "turn_000005",
                "session_id": session_id,
                "role": "user",
                "text": "давай поговорим о булщите",
                "attachments": [],
                "active_memory_ids": [],
                "delayed_memory_ids": ["ehfw65"],
            },
            {
                "ts": "2026-08-16T23:09:39+03:00",
                "turn": 5,
                "turn_id": "turn_000005",
                "session_id": session_id,
                "role": "jin",
                "text": "Булшит для меня — ошибка аппроксимации.",
                "attachments": [],
                "active_memory_ids": [],
                "delayed_memory_ids": ["ehfw65"],
                "reasoning_path": (
                    f"/logs/2026-08-16/{session_id}/reasoning/"
                    "222828_turn_000005.txt"
                ),
            },
        ]

        (session_dir / "222828.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in entries),
            encoding="utf-8",
        )
        (reasoning_dir / "222828_turn_000005.txt").write_text(
            "reasoning: keep it on chill",
            encoding="utf-8",
        )
        (session_dir / "222828.txt").write_text(
            """
<TOOLS_RESULTS>
<TOOL_RESULT name="SAVE_SESSION">
{
  "action": "save_session",
  "ok": true,
  "message": "Session snapshot saved successfully."
}
</TOOL_RESULT>
<TOOL_RESULT name="WEB_SEARCH">
<SEARCH_RESULT>
  <STATUS>FOUND</STATUS>
  <QUERY>noir soundtrack</QUERY>
  <SUMMARY>Found 1 search result.</SUMMARY>
  <RESULTS>
    <RESULT>
      <TITLE>Reddit thread</TITLE>
      <SOURCE>reddit.com</SOURCE>
      <URL>https://reddit.com/thread</URL>
      <QUOTE>People recommend cold noir music.</QUOTE>
      <EXCERPT></EXCERPT>
    </RESULT>
  </RESULTS>
</SEARCH_RESULT>
</TOOL_RESULT>
</TOOLS_RESULTS>
<LOADED_DELAYED_MEMORY>
{
  "id": "ehfw65",
  "title": "Old vibe",
  "summary": "Archived context",
  "tags": ["vibe"],
  "body": "body"
}
</LOADED_DELAYED_MEMORY>
<PREVIOUS_RUNTIME_STATE ( 1m ago )>
last_jin_response: Булшит для меня — ошибка аппроксимации.
open_question: продолжить разговор
active_memory: chill mode [ active_memory_id: am0001 ]
</PREVIOUS_RUNTIME_STATE>
<CURRENT_TRUSTED_RUNTIME_VARIABLES>
<RUNTIME_MODE>BRAIN</RUNTIME_MODE>
<CURRENT_JIN_COLOR>#9370db</CURRENT_JIN_COLOR>
<CURRENT_JIN_SIZE>width: 333px height: 333px</CURRENT_JIN_SIZE>
</CURRENT_TRUSTED_RUNTIME_VARIABLES>
<PREVIOUS_SESSION_STATE priority="higher_than_runtime_memory">
session_saved_at: 2026-08-16 22:33, Sunday
session_snapshot_first_turn: 1
session_snapshot_last_turn: 1
</PREVIOUS_SESSION_STATE>
""".strip(),
            encoding="utf-8",
        )

        return root, session_id

    def test_payload_restores_dialog_reasoning_runtime_and_actions(self):
        root, session_id = self._build_fixture()

        payload = build_archived_session_restore_payload(
            session_id,
            root=root,
        )

        self.assertIsNotNone(payload)
        self.assertEqual(payload["source_session_id"], session_id)
        self.assertEqual(len(payload["messages"]), 2)
        self.assertEqual(
            payload["messages"][1]["reasoning"],
            "reasoning: keep it on chill",
        )
        self.assertIn("open_question: продолжить разговор", payload["runtime_memory"])
        self.assertEqual(payload["loaded_memory_ids"], ["ehfw65"])
        self.assertIn("ehfw65", payload["delayed_memory_reports"])
        self.assertEqual(payload["active_memory_records"], [
            "active_memory: chill mode [ active_memory_id: am0001 ]"
        ])
        self.assertEqual(payload["current_jin_color"], "#9370db")
        self.assertEqual(payload["current_jin_size"], {
            "width": 333,
            "height": 333,
        })
        self.assertEqual(payload["runtime_mode"], "BRAIN")
        self.assertEqual(payload["session_actions"][0]["parts"][0]["text"], "Saved session")
        self.assertEqual(payload["tool_results"][0]["kind"], "search")
        self.assertIn("People recommend cold noir music.", payload["tool_results"][0]["result"])


    def test_restore_payload_uses_primary_context_and_ignores_bootstrap_snapshot(self):
        root, session_id = self._build_fixture()
        session_dir = root / "2026-08-16" / session_id
        (session_dir / "222828.bootstrap.txt").write_text(
            """
<SESSION_RESTORE>bootstrap only</SESSION_RESTORE>
<PREVIOUS_RUNTIME_STATE>
last_jin_response: WRONG BOOTSTRAP VALUE
open_question: wrong bootstrap question
</PREVIOUS_RUNTIME_STATE>
""".strip(),
            encoding="utf-8",
        )

        payload = build_archived_session_restore_payload(
            session_id,
            root=root,
        )

        self.assertIsNotNone(payload)
        self.assertIn(
            "last_jin_response: Булшит для меня — ошибка аппроксимации.",
            payload["runtime_memory"],
        )
        self.assertIn(
            "open_question: продолжить разговор",
            payload["runtime_memory"],
        )
        self.assertNotIn("WRONG BOOTSTRAP VALUE", payload["runtime_memory"])
        self.assertEqual(payload["context_file"], "222828.txt")

    def test_restored_dialog_keeps_three_newest_complete_pairs_chronological(self):
        root = Path(tempfile.mkdtemp())
        session_id = "reverse-three-pairs"
        session_dir = root / "2026-08-17" / session_id
        session_dir.mkdir(parents=True)

        entries = []
        for turn in range(1, 5):
            entries.extend([
                {
                    "ts": f"2026-08-17T10:0{turn}:00+03:00",
                    "turn": turn,
                    "turn_id": f"turn_{turn:06d}",
                    "session_id": session_id,
                    "role": "user",
                    "text": f"question {turn}",
                },
                {
                    "ts": f"2026-08-17T10:0{turn}:30+03:00",
                    "turn": turn,
                    "turn_id": f"turn_{turn:06d}",
                    "session_id": session_id,
                    "role": "jin",
                    "text": f"answer {turn}",
                },
            ])

        (session_dir / "dialog.jsonl").write_text(
            "\n".join(
                json.dumps(item, ensure_ascii=False)
                for item in entries
            ),
            encoding="utf-8",
        )
        (session_dir / "dialog.txt").write_text(
            "<PREVIOUS_RUNTIME_STATE>open_question: next</PREVIOUS_RUNTIME_STATE>",
            encoding="utf-8",
        )

        payload = build_archived_session_restore_payload(
            session_id,
            root=root,
        )

        dialog = payload["dialog_context"]
        self.assertNotIn("question 1", dialog)
        self.assertNotIn("answer 1", dialog)
        self.assertLess(dialog.index("question 2"), dialog.index("answer 2"))
        self.assertLess(dialog.index("answer 2"), dialog.index("question 3"))
        self.assertLess(dialog.index("answer 3"), dialog.index("question 4"))
        self.assertLess(dialog.index("question 4"), dialog.index("answer 4"))

    def test_payload_recovers_adjacent_json_objects_and_skips_empty_restore_rows(self):
        root = Path(tempfile.mkdtemp())
        session_id = "damaged-jsonl-session"
        session_dir = root / "2026-08-17" / session_id
        session_dir.mkdir(parents=True)

        user_entry = {
            "ts": "2026-08-16T23:20:10+03:00",
            "turn": 6,
            "turn_id": "turn_000006",
            "session_id": session_id,
            "role": "user",
            "text": "save it",
            "attachments": [],
            "active_memory_ids": [],
            "delayed_memory_ids": ["ehfw65"],
        }
        jin_entry = {
            "ts": "2026-08-16T23:26:55+03:00",
            "turn": 6,
            "turn_id": "turn_000006",
            "session_id": session_id,
            "role": "jin",
            "text": "final archived JIN bubble",
            "attachments": [],
            "active_memory_ids": [],
            "delayed_memory_ids": ["ehfw65"],
        }
        prior_restore_entry = {
            "ts": "2026-08-17T15:13:19+03:00",
            "turn": 7,
            "turn_id": "restore_000007",
            "session_id": session_id,
            "role": "jin",
            "text": "prior restore continuation",
            "attachments": [],
            "active_memory_ids": [],
            "delayed_memory_ids": ["ehfw65"],
        }
        empty_restore_entry = {
            "ts": "2026-08-17T15:48:34+03:00",
            "turn": 8,
            "turn_id": "restore_000008",
            "session_id": session_id,
            "role": "jin",
            "text": "",
            "attachments": [],
            "active_memory_ids": [],
            "delayed_memory_ids": [],
        }

        (session_dir / "222828.jsonl").write_text(
            "\n".join([
                json.dumps(user_entry, ensure_ascii=False),
                json.dumps(jin_entry, ensure_ascii=False)
                + json.dumps(prior_restore_entry, ensure_ascii=False),
                json.dumps(empty_restore_entry, ensure_ascii=False),
            ]),
            encoding="utf-8",
        )

        payload = build_archived_session_restore_payload(
            session_id,
            root=root,
        )

        self.assertIsNotNone(payload)
        self.assertEqual(
            [message["text"] for message in payload["messages"]],
            [
                "save it",
                "final archived JIN bubble",
                "prior restore continuation",
            ],
        )
        self.assertEqual(payload["loaded_memory_ids"], ["ehfw65"])
        self.assertEqual(payload["runtime_turn_counter"], 8)

    def test_restore_reasoning_dump_is_newest_first_limited_and_middle_cropped(self):
        root = Path(tempfile.mkdtemp())
        session_id = "restore-reasoning-session"
        session_dir = root / "2026-08-17" / session_id
        reasoning_dir = session_dir / "reasoning"
        reasoning_dir.mkdir(parents=True)

        entries = []
        for turn in range(1, 7):
            turn_id = f"turn_{turn:06d}"
            entries.extend([
                {
                    "ts": f"2026-08-17T10:{turn:02d}:00+03:00",
                    "turn": turn,
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "role": "user",
                    "text": f"user {turn}",
                    "attachments": [],
                    "active_memory_ids": [],
                    "delayed_memory_ids": ["abc123", "def456"],
                },
                {
                    "ts": f"2026-08-17T10:{turn:02d}:30+03:00",
                    "turn": turn,
                    "turn_id": turn_id,
                    "session_id": session_id,
                    "role": "jin",
                    "text": (
                        "latest answer cites F42"
                        if turn == 6
                        else f"jin {turn}"
                    ),
                    "attachments": [],
                    "active_memory_ids": [],
                    "delayed_memory_ids": ["abc123", "def456"],
                    "reasoning_path": (
                        f"/logs/2026-08-17/{session_id}/reasoning/"
                        f"session_{turn_id}.txt"
                    ),
                },
            ])

            reasoning = f"reasoning-{turn}-start " + ("x" * 80) + f" reasoning-{turn}-end"
            if turn == 6:
                reasoning = (
                    "LATEST-HEAD F99 "
                    + ("middle-noise " * 700)
                    + " LATEST-TAIL"
                )
            (reasoning_dir / f"session_{turn_id}.txt").write_text(
                reasoning,
                encoding="utf-8",
            )

        (session_dir / "session.jsonl").write_text(
            "\n".join(json.dumps(item, ensure_ascii=False) for item in entries),
            encoding="utf-8",
        )
        (session_dir / "session.txt").write_text(
            """
<LOADED_DELAYED_MEMORY>
{
  "id": "abc123",
  "title": "First report",
  "body": "DO NOT PRIME THIS BODY"
}
</LOADED_DELAYED_MEMORY>
<LOADED_DELAYED_MEMORY>
{
  "id": "def456",
  "title": "Second report",
  "body": "DO NOT PRIME THIS BODY EITHER"
}
</LOADED_DELAYED_MEMORY>
<ATTACHED_FILES>
alpha.txt [ id: file-a ]
beta.png [ id: file-b ]
</ATTACHED_FILES>
<PREVIOUS_RUNTIME_STATE>
topic: restored raw state
</PREVIOUS_RUNTIME_STATE>
<PREVIOUS_SESSION_STATE>
open_question: continue
</PREVIOUS_SESSION_STATE>
""".strip(),
            encoding="utf-8",
        )

        payload = build_archived_session_restore_payload(
            session_id,
            root=root,
        )

        self.assertIsNotNone(payload)
        dump = payload["restore_reasoning_dump"]
        self.assertEqual(dump.count("<REASONING "), 5)
        self.assertLess(
            dump.index('turn_id="turn_000006"'),
            dump.index('turn_id="turn_000005"'),
        )
        self.assertNotIn('turn_id="turn_000001"', dump)
        self.assertIn("LATEST-HEAD F99", dump)
        self.assertIn("LATEST-TAIL", dump)
        self.assertIn("MIDDLE CHARS", dump)

        latest_block = dump.split("</REASONING>", 1)[0]
        latest_body = latest_block.split("<REASONING ", 1)[1].split(">\n", 1)[1].rstrip("\n")
        self.assertLessEqual(len(latest_body), 5000)
        self.assertEqual(
            payload["restore_l4_fact_ids"],
            ["F99", "F42"],
        )
        self.assertEqual(
            payload["restore_delayed_memory_metadata"],
            [
                {"id": "abc123", "title": "First report"},
                {"id": "def456", "title": "Second report"},
            ],
        )
        self.assertEqual(
            payload["restore_attached_file_metadata"],
            [
                {"id": "file-a", "title": "alpha.txt"},
                {"id": "file-b", "title": "beta.png"},
            ],
        )

    def test_browser_session_bootstrap_is_enriched_from_raw_archive(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        archived = {
            "source_session_id": "archive-session",
            "dialog_context": "<RESTORED_SESSION_DIALOG>old flow</RESTORED_SESSION_DIALOG>",
            "recent_turns": [{"user": "old user", "jin": "old jin"}],
            "previous_reasoning": "latest raw reasoning",
            "restore_reasoning_dump": "<RESTORED_SESSION_REASONING_DUMP>raw</RESTORED_SESSION_REASONING_DUMP>",
            "restore_l4_fact_ids": ["F7"],
            "restore_delayed_memory_metadata": [{"id": "abc123", "title": "Old report"}],
            "restore_attached_file_metadata": [{"id": "file1", "title": "old.txt"}],
            "session_actions": [],
            "runtime_turn_counter": 9,
            "user_message_count": 4,
            "assistant_message_count": 5,
            "attached_file_ids": ["file1"],
            "runtime_memory": "archive runtime",
            "runtime_memory_updates": 9,
            "session_memory": "archive session",
            "session_memory_updates": 1,
            "loaded_memory_ids": ["abc123"],
            "active_memory_records": [],
        }

        with patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=archived,
        ):
            restored = apply_session_bootstrap(
                context,
                {
                    "type": "session_bootstrap",
                    "source_session_id": "archive-session",
                    "session_memory": "browser L3 checkpoint",
                    "session_memory_updates": 1,
                    "runtime_memory": "browser L1 checkpoint",
                    "runtime_memory_updates": 9,
                    "loaded_memory_ids": ["abc123"],
                },
            )

        self.assertTrue(restored)
        self.assertTrue(context.runtime_session_restore_priming)
        self.assertEqual(context.runtime_archived_session_id, "archive-session")
        self.assertIn("old flow", context.runtime_restored_session_dialog)
        self.assertIn("raw", context.runtime_session_restore_reasoning_dump)
        self.assertEqual(context.runtime_session_restore_l4_fact_ids, ["F7"])
        self.assertIn("browser L1 checkpoint", context.runtime_memory)
        self.assertEqual(context.session_memory, "browser L3 checkpoint")
        self.assertEqual(
            context.runtime_session_restore_pending_loaded_memory_ids,
            ["abc123"],
        )
        self.assertEqual(
            context.runtime_session_restore_pending_attached_file_ids,
            ["file1"],
        )
        self.assertEqual(context.runtime_attached_file_ids, [])


    def test_browser_checkpoint_does_not_mix_in_older_raw_dialogue(self):
        archived = {
            "source_session_id": "archive-session",
            "messages": [
                {
                    "ts": "2026-08-19T17:24:52+03:00",
                    "role": "jin",
                    "text": "Жду тебя — обсудим Эндермена.",
                },
            ],
            "dialog_context": (
                "<RESTORED_SESSION_DIALOG>Enderman</RESTORED_SESSION_DIALOG>"
            ),
            "recent_turns": [
                {"user": "про ендера", "jin": "обсудим ендера"},
            ],
            "previous_reasoning": "reasoning about Enderman",
            "restore_reasoning_dump": (
                "<RESTORED_SESSION_REASONING_DUMP>Enderman</RESTORED_SESSION_REASONING_DUMP>"
            ),
            "runtime_memory": "active_topic: stale archive topic",
            "runtime_memory_updates": 10,
        }

        with patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=archived,
        ):
            enriched = enrich_session_bootstrap_from_archive(
                {
                    "type": "session_bootstrap",
                    "source_session_id": "archive-session",
                    "saved_at": "2026-08-19T17:11:06.500000Z",
                    "runtime_memory": (
                        "active_topic: Cooking instructions for macaroni and sausages"
                    ),
                    "runtime_memory_updates": 20,
                    "session_memory": "saved L3",
                    "session_memory_updates": 1,
                }
            )

        self.assertEqual(
            enriched["runtime_memory"],
            "active_topic: Cooking instructions for macaroni and sausages",
        )
        self.assertNotIn("dialog_context", enriched)
        self.assertNotIn("recent_turns", enriched)
        self.assertNotIn("previous_reasoning", enriched)
        self.assertNotIn("restore_reasoning_dump", enriched)
        self.assertTrue(enriched["archived_session_restore"])

    def test_browser_checkpoint_explicit_empty_tool_results_stays_empty(self):
        archived = {
            "source_session_id": "archive-session",
            "messages": [
                {
                    "ts": "2026-08-23T10:30:00+03:00",
                    "role": "jin",
                    "text": "current tail",
                },
            ],
            "tool_results": [
                {
                    "kind": "search",
                    "result": "stale search result",
                    "created_at": 1.0,
                },
            ],
        }

        with patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=archived,
        ):
            enriched = enrich_session_bootstrap_from_archive(
                {
                    "type": "session_bootstrap",
                    "source_session_id": "archive-session",
                    "saved_at": "2026-08-23T10:29:00+03:00",
                    "runtime_memory": "active_topic: current",
                    "tool_results": [],
                }
            )

        self.assertIn("tool_results", enriched)
        self.assertEqual(enriched["tool_results"], [])

    def test_empty_memory_collections_keep_archive_fallback_semantics(self):
        archived = {
            "source_session_id": "archive-session",
            "messages": [
                {
                    "ts": "2026-08-23T10:30:00+03:00",
                    "role": "jin",
                    "text": "current tail",
                },
            ],
            "loaded_memory_ids": ["delayed-1"],
            "active_memory_records": [
                {"id": "active-1", "conditions": "keep me"},
            ],
        }

        with patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=archived,
        ):
            enriched = enrich_session_bootstrap_from_archive(
                {
                    "type": "session_bootstrap",
                    "source_session_id": "archive-session",
                    "saved_at": "2026-08-23T10:29:00+03:00",
                    "runtime_memory": "active_topic: current",
                    "loaded_memory_ids": [],
                    "active_memory_records": [],
                }
            )

        self.assertEqual(enriched["loaded_memory_ids"], ["delayed-1"])
        self.assertEqual(
            enriched["active_memory_records"],
            [{"id": "active-1", "conditions": "keep me"}],
        )


    def test_browser_checkpoint_still_uses_raw_dialogue_when_log_reaches_save(self):
        archived = {
            "source_session_id": "archive-session",
            "messages": [
                {
                    "ts": "2026-08-19T20:11:06+03:00",
                    "role": "jin",
                    "text": "current tail",
                },
            ],
            "dialog_context": (
                "<RESTORED_SESSION_DIALOG>current tail</RESTORED_SESSION_DIALOG>"
            ),
            "restore_reasoning_dump": (
                "<RESTORED_SESSION_REASONING_DUMP>current reasoning</RESTORED_SESSION_REASONING_DUMP>"
            ),
        }

        with patch(
            "utils.session_restore.build_archived_session_restore_payload",
            return_value=archived,
        ):
            enriched = enrich_session_bootstrap_from_archive(
                {
                    "type": "session_bootstrap",
                    "source_session_id": "archive-session",
                    "saved_at": "2026-08-19T17:11:06.900000Z",
                    "runtime_memory": "active_topic: macaroni",
                    "session_memory": "saved L3",
                }
            )

        self.assertIn("dialog_context", enriched)
        self.assertIn("restore_reasoning_dump", enriched)
        self.assertTrue(enriched["archived_session_restore"])

    def test_restore_resource_replay_uses_real_runtime_action_dispatcher(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_session_restore_priming = True
        context.runtime_session_restore_pending_loaded_memory_ids = [
            "abc123",
            "abc123",
        ]
        context.runtime_session_restore_pending_attached_file_ids = [
            "file001",
            "file001",
        ]
        context.runtime_session_restore_pending_jin_color = "#9370db"
        context.runtime_session_restore_pending_jin_size = {
            "width": 333,
            "height": 333,
        }
        context.runtime_session_restore_reasoning_dump = "reasoning"
        context.runtime_session_restore_l4_fact_ids = ["F7"]
        context.runtime_session_restore_delayed_memory_metadata = [
            {"id": "abc123", "title": "Old report"},
        ]
        context.runtime_session_restore_attached_file_metadata = [
            {"id": "file001", "title": "old.txt"},
        ]

        captured = {}

        async def fake_apply(
            _context,
            actions,
            **kwargs,
        ):
            captured["context"] = _context
            captured["actions"] = list(actions)
            captured["kwargs"] = kwargs
            return len(actions)

        with patch(
            "agent.nodes.brain.apply_runtime_action_calls",
            side_effect=fake_apply,
        ):
            applied = asyncio.run(
                replay_session_restore_resource_actions(
                    context,
                    assistant_message="restore answer",
                    context_snapshot={"prompt": "restore"},
                )
            )

        self.assertEqual(applied, 4)
        self.assertEqual(
            [action.name for action in captured["actions"]],
            [
                "LOAD_DELAYED_MEMORY",
                "ATTACH_FILE",
                "JIN_COLOR",
                "JIN_SIZE",
            ],
        )
        self.assertEqual(
            [action.payload for action in captured["actions"]],
            [
                "abc123",
                "file001",
                "#9370db",
                {"width": 333, "height": 333},
            ],
        )
        self.assertEqual(
            captured["kwargs"]["assistant_message"],
            "restore answer",
        )
        self.assertEqual(
            captured["kwargs"]["context_snapshot"],
            {"prompt": "restore"},
        )
        self.assertFalse(context.runtime_session_restore_priming)
        self.assertEqual(
            context.runtime_session_restore_pending_loaded_memory_ids,
            [],
        )
        self.assertEqual(
            context.runtime_session_restore_pending_attached_file_ids,
            [],
        )
        self.assertEqual(
            context.runtime_session_restore_pending_jin_color,
            "",
        )
        self.assertIsNone(
            context.runtime_session_restore_pending_jin_size
        )
        self.assertEqual(context.runtime_session_restore_reasoning_dump, "")
        self.assertEqual(context.runtime_session_restore_l4_fact_ids, [])
        self.assertEqual(
            context.runtime_session_restore_delayed_memory_metadata,
            [],
        )
        self.assertEqual(
            context.runtime_session_restore_attached_file_metadata,
            [],
        )

    def test_restore_prompt_is_clean_one_shot_context(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_session_restore_priming = True
        context.runtime_restored_session_dialog = (
            "<RESTORED_SESSION_DIALOG>EXACT OLD FLOW</RESTORED_SESSION_DIALOG>"
        )
        context.runtime_session_restore_reasoning_dump = (
            "<RESTORED_SESSION_REASONING_DUMP>RAW REASONING</RESTORED_SESSION_REASONING_DUMP>"
        )
        context.runtime_session_restore_l4_fact_ids = ["F42"]
        context.runtime_session_restore_delayed_memory_metadata = [
            {"id": "abc123", "title": "Old report"},
        ]
        context.runtime_session_restore_attached_file_metadata = [
            {"id": "file1", "title": "old.txt"},
        ]
        context.runtime_loaded_delayed_memory = {
            "abc123": {
                "title": "Old report",
                "body": "HEAVY DELAYED BODY",
            },
        }
        context.runtime_loaded_delayed_memory_ids = ["abc123"]
        context.delayed_memory_reports = dict(context.runtime_loaded_delayed_memory)
        context.runtime_attached_file_ids = ["file1"]
        context.session_memory = (
            "session_status: STALE CHECKPOINT\n"
            "open_question: STALE OLD QUESTION"
        )

        with patch(
            "runtime.L4_memory.build_runtime_l4_memory_context",
            return_value="<LONG_TERM_MEMORY>ONLY F42</LONG_TERM_MEMORY>",
        ) as l4_builder:
            prompt = build_brain_context(
                context=context,
                runtime_actions={"CAN_WEB_SEARCH": True},
            )

        self.assertTrue(prompt.startswith(SESSION_RESTORE_MESSAGE))
        self.assertIn("EXACT OLD FLOW", prompt)
        self.assertIn("RAW REASONING", prompt)
        self.assertIn("Old report [ id: abc123 ]", prompt)
        self.assertIn("old.txt [ id: file1 ]", prompt)
        self.assertNotIn("HEAVY DELAYED BODY", prompt)
        self.assertNotIn("<PREVIOUS_SESSION_STATE", prompt)
        self.assertNotIn("STALE CHECKPOINT", prompt)
        self.assertNotIn("STALE OLD QUESTION", prompt)
        self.assertIn("ONLY F42", prompt)
        l4_builder.assert_called_once_with(
            context=context,
            fact_ids=["F42"],
        )

        context.runtime_session_restore_priming = False
        ordinary_prompt = build_brain_context(
            context=context,
            runtime_actions={"CAN_WEB_SEARCH": False},
        )
        self.assertNotIn("RAW REASONING", ordinary_prompt)
        self.assertIn("HEAVY DELAYED BODY", ordinary_prompt)
        self.assertIn("<PREVIOUS_SESSION_STATE", ordinary_prompt)
        self.assertIn("STALE CHECKPOINT", ordinary_prompt)

    def test_restore_tick_uses_provider_whitespace_without_fake_user_text(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_session_restore_priming = True
        self.assertEqual(
            RuntimeClient.provider_user_prompt(context, ""),
            " ",
        )

    def test_session_bootstrap_hydrates_continuation_state(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )

        restored = apply_session_bootstrap(
            context,
            {
                "runtime_memory": "topic: restored",
                "runtime_memory_updates": 6,
                "recent_turns": [
                    {
                        "user": "old user",
                        "jin": "old jin",
                        "user_created_at": 1.0,
                        "jin_created_at": 2.0,
                    }
                ],
                "previous_reasoning": "old reasoning",
                "session_actions": [
                    {
                        "text": "Saved session",
                        "created_at": 3.0,
                        "parts": [{"text": "Saved session"}],
                    }
                ],
                "runtime_turn_counter": 6,
                "user_message_count": 6,
                "assistant_message_count": 6,
            },
        )

        self.assertTrue(restored)
        self.assertEqual(context.runtime_recent_turns[-1]["user"], "old user")
        self.assertEqual(context.runtime_previous_reasoning_content, "old reasoning")
        self.assertEqual(context.runtime_session_action_history[-1]["text"], "Saved session")
        self.assertGreaterEqual(context.runtime_turn_counter, 6)
        self.assertGreaterEqual(context.user_message_count, 6)
        self.assertGreaterEqual(context.assistant_message_count, 6)

    def test_session_bootstrap_restores_tool_results_and_previous_actions(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
            session_id="fresh-session",
        )

        restored = apply_session_bootstrap(
            context,
            {
                "type": "session_bootstrap",
                "source_session_id": "old-session",
                "runtime_memory": "topic: restored",
                "session_actions": [
                    {"text": "JIN_COLOR: #111111", "created_at": 1.0},
                    {"text": "JIN_COLOR: #222222", "created_at": 2.0},
                    {"text": "JIN_COLOR: #333333", "created_at": 3.0},
                    {"text": "JIN_COLOR: #444444", "created_at": 4.0},
                ],
                "tool_results": [
                    {
                        "kind": "deep_search",
                        "result": "Deep web search report\nReport:\nReddit says cold noir.",
                        "created_at": 5.0,
                    },
                ],
            },
        )

        self.assertTrue(restored)
        self.assertEqual(
            [item["text"] for item in context.runtime_session_action_history],
            [
                "JIN_COLOR: #222222",
                "JIN_COLOR: #333333",
                "JIN_COLOR: #444444",
            ],
        )
        self.assertTrue(
            all(
                item.get("runtime_session_action_previous_bootstrap")
                for item in context.runtime_session_action_history
            )
        )

        record_session_action_history(
            context,
            "WEB_SEARCH: new session query",
        )
        session_actions = build_session_actions_history_context(
            context
        )
        self.assertIn("----- Previous actions -----", session_actions)
        self.assertIn("----- Current session actions -----", session_actions)
        self.assertIn("JIN_COLOR: #222222", session_actions)
        self.assertIn("WEB_SEARCH: new session query", session_actions)

        tool_results = build_tool_results_context(
            context
        )
        self.assertIn("DEEP_WEB_SEARCH", tool_results)
        self.assertIn("Reddit says cold noir.", tool_results)


class ArchivedSessionRestoreClientContractTests(unittest.TestCase):

    def test_delayed_memory_session_id_opens_archived_restore_tab(self):
        root = Path(__file__).resolve().parents[1]
        memory_view = (
            root
            / "ui"
            / "static"
            / "js"
            / "runtime"
            / "runtime-memory-view.js"
        ).read_text(encoding="utf-8")
        index = (root / "ui" / "templates" / "index.html").read_text(encoding="utf-8")
        restore_script = (
            root / "ui" / "static" / "js" / "session-restore.js"
        ).read_text(encoding="utf-8")
        runtime_session = (
            root / "ui" / "static" / "js" / "runtime" / "runtime-session.js"
        ).read_text(encoding="utf-8")
        socket_script = (
            root / "ui" / "static" / "js" / "socket.js"
        ).read_text(encoding="utf-8")

        self.assertIn("restore_session=${encodeURIComponent(sessionId)}", memory_view)
        self.assertIn("appendDelayedMemorySessionIdsField(\n        fields,\n        \"Session\"", memory_view)
        self.assertLess(
            index.index("session-restore.js"),
            index.index("socket.js"),
        )
        self.assertIn("jinArchivedSessionRestoreReady", restore_script)
        self.assertIn("jin-session-restore-divider", restore_script)
        self.assertIn("formatRestoreBoundaryTimestamp", restore_script)
        self.assertIn("appendRestoreBoundary(payload)", restore_script)
        self.assertIn("appendThinkingChunk", restore_script)
        self.assertIn("replaceLoadedDelayedMemoryReportIds", restore_script)
        self.assertIn("updateSessionActionsLog", restore_script)
        self.assertIn("readLatestSavedRuntimeMemory", restore_script)
        self.assertIn("payload.runtime_snapshot", restore_script)
        self.assertIn("jinArchivedSessionBootstrap", runtime_session)
        self.assertIn("snapshotRuntimeMemory", runtime_session)
        self.assertIn("sourceSnapshot.lines.map", runtime_session)
        self.assertNotIn(
            "created_at:\n              isArchivedRestore ? restoredAt : line.created_at",
            runtime_session,
        )
        self.assertIn("runtimeMemory.saved_at", runtime_session)
        self.assertIn('type: "archived_session_resume"', socket_script)
        self.assertNotIn(
            'bootstrap.archived_session_restore !== true',
            socket_script,
        )


if __name__ == "__main__":
    unittest.main()
