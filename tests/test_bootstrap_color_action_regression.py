import json
import tempfile
import unittest
from pathlib import Path

from utils.session_restore import build_archived_session_restore_payload


ROOT = Path(__file__).resolve().parents[1]


class BootstrapColorActionRegressionTests(unittest.TestCase):

    def test_archive_recovers_color_actions_from_direct_predecessor_logs(self):
        root = Path(tempfile.mkdtemp())
        previous_session_id = "previous-blue-session"
        current_session_id = "current-red-session"

        previous_dir = root / "2026-08-25" / previous_session_id
        current_dir = root / "2026-08-25" / current_session_id
        previous_dir.mkdir(parents=True)
        current_dir.mkdir(parents=True)

        previous_entries = [
            {
                "ts": "2026-08-25T13:04:05+03:00",
                "turn": 36,
                "turn_id": "turn_000036",
                "session_id": previous_session_id,
                "role": "user",
                "text": "blue",
            },
            {
                "ts": "2026-08-25T13:04:58+03:00",
                "turn": 36,
                "turn_id": "turn_000036",
                "session_id": previous_session_id,
                "role": "runtime",
                "text": "",
                "event": "runtime_action_request",
                "payload": {
                    "action": "JIN_COLOR",
                    "color": "#0000ff",
                    "created_at": 100.0,
                },
            },
            {
                "ts": "2026-08-25T13:04:58+03:00",
                "turn": 36,
                "turn_id": "turn_000036",
                "session_id": previous_session_id,
                "role": "jin",
                "text": "Blue.",
            },
        ]
        current_entries = [
            {
                "ts": "2026-08-25T13:23:28+03:00",
                "turn": 38,
                "turn_id": "turn_000038",
                "session_id": current_session_id,
                "role": "user",
                "text": "red",
            },
            {
                "ts": "2026-08-25T13:24:21+03:00",
                "turn": 38,
                "turn_id": "turn_000038",
                "session_id": current_session_id,
                "role": "runtime",
                "text": "",
                "event": "runtime_action_request",
                "payload": {
                    "action": "JIN_COLOR",
                    "color": "#ff0000",
                    "created_at": 200.0,
                },
            },
            {
                "ts": "2026-08-25T13:24:21+03:00",
                "turn": 38,
                "turn_id": "turn_000038",
                "session_id": current_session_id,
                "role": "jin",
                "text": "Red.",
            },
        ]

        (previous_dir / "session.jsonl").write_text(
            "\n".join(json.dumps(item) for item in previous_entries),
            encoding="utf-8",
        )
        (previous_dir / "session.txt").write_text("", encoding="utf-8")
        (current_dir / "session.jsonl").write_text(
            "\n".join(json.dumps(item) for item in current_entries),
            encoding="utf-8",
        )
        (current_dir / "session.txt").write_text(
            '<RESTORED_SESSION_DIALOG session_id="previous-blue-session">\n'
            "</RESTORED_SESSION_DIALOG>",
            encoding="utf-8",
        )

        payload = build_archived_session_restore_payload(
            current_session_id,
            root=root,
        )

        self.assertEqual(payload["current_jin_color"], "#ff0000")
        self.assertEqual(
            [
                item["parts"][0]["colors"][0]
                for item in payload["session_actions"]
            ],
            ["#0000ff", "#ff0000"],
        )

    def test_server_actions_remain_ui_color_fallback(self):
        websocket_source = (ROOT / "websocket" / "__init__.py").read_text(
            encoding="utf-8"
        )
        handler_source = (
            ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
        ).read_text(encoding="utf-8")
        session_source = (
            ROOT / "ui" / "static" / "js" / "runtime" / "runtime-session.js"
        ).read_text(encoding="utf-8")

        self.assertIn("bootstrap_restore=True", websocket_source)
        self.assertIn("data.bootstrap_restore === true", handler_source)
        self.assertIn("runtimeSession.resolveBootstrapJinColor", handler_source)
        self.assertIn("runtimeSession.applyBootstrapSceneTintShift", handler_source)
        self.assertIn("resolvePersistedJinColor()", session_source)
        self.assertIn(
            'sceneMain.style.removeProperty("background-color")',
            session_source,
        )
        self.assertNotIn("previousMain.transition", session_source)


if __name__ == "__main__":
    unittest.main()
