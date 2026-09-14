from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class RuntimeProgressAvatarClientContractTests(unittest.TestCase):

    def test_chat_avatar_has_buffered_clockwise_progress_ring(self):
        source = (ROOT / "ui/static/js/chat.js").read_text(encoding="utf-8")

        self.assertIn("jin-chat-avatar-progress-ring", source)
        self.assertIn("pendingStreamAvatarProgress", source)
        self.assertIn("--jin-chat-avatar-progress-angle", source)
        self.assertIn("setStreamAvatarProgress", source)

    def test_runtime_progress_socket_event_reaches_chat_avatar(self):
        source = (
            ROOT / "ui/static/js/socket/event-handlers.js"
        ).read_text(encoding="utf-8")

        self.assertIn('"runtime_progress"', source)
        self.assertIn("handleRuntimeProgress", source)
        self.assertIn("window.setStreamAvatarProgress", source)

    def test_load_and_prompt_phases_have_requested_colors(self):
        source = (ROOT / "ui/static/css/chat.css").read_text(encoding="utf-8")

        self.assertIn("progress-phase-model-load", source)
        self.assertIn("rgba(255, 255, 255, 0.96)", source)
        self.assertIn("progress-phase-prompt-processing", source)
        self.assertIn("rgba(245, 199, 84, 0.98)", source)


if __name__ == "__main__":
    unittest.main()
