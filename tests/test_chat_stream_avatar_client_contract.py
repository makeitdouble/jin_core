import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHAT_JS = ROOT / "ui" / "static" / "js" / "chat.js"
CHAT_CSS = ROOT / "ui" / "static" / "css" / "chat.css"
SOCKET_JS = ROOT / "ui" / "static" / "js" / "socket.js"
EVENT_HANDLERS_JS = ROOT / "ui" / "static" / "js" / "socket" / "event-handlers.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class ChatStreamAvatarClientContractTests(unittest.TestCase):

    def test_stream_reserves_clickable_avatar_before_first_token(self):
        source = CHAT_JS.read_text(encoding="utf-8")
        css = CHAT_CSS.read_text(encoding="utf-8")

        self.assertIn(
            '"jin-stream-wrapper is-awaiting-model mx-auto w-full max-w-4xl"',
            source,
        )
        self.assertIn('"jin-stream-avatar-slot"', source)
        self.assertIn('"jin-stream-avatar",\n    "is-processing"', source)
        self.assertIn("activateStreamAvatar(\n    stream", source)
        self.assertIn(".jin-stream-wrapper.is-awaiting-model", css)
        self.assertIn("@keyframes jin-chat-avatar-processing", css)
        self.assertIn("opacity: 0.48;", css)
        self.assertIn("transform: scale(0.90);", css)

    def test_avatar_tracks_expanded_reasoning_but_not_collapsed_reasoning(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn(
            '!group.thinkContent.classList.contains(\n        "is-collapsed"',
            source,
        )
        self.assertIn(
            "group.thinkContent.offsetHeight\n        - STREAM_AVATAR_SIZE_PX",
            source,
        )
        self.assertIn("new ResizeObserver(", source)
        self.assertIn("__jinStreamAvatarSync", source)
        self.assertIn("function trackStreamAvatarLayoutTransition(", source)
        self.assertIn("STREAM_AVATAR_LAYOUT_TRACK_MS = 340", source)

    def test_answer_settles_avatar_and_retry_reasoning_handoffs_it(self):
        source = CHAT_JS.read_text(encoding="utf-8")

        self.assertIn("function animateStreamAvatarHandoff(", source)
        self.assertIn("previous.group.avatarSlot.getBoundingClientRect()", source)
        self.assertIn("!previous.group.createdAnswer", source)
        self.assertIn("setStreamAvatarProcessing(\n      stream,\n      false", source)
        self.assertIn("disconnectStreamThinkResizeObserver(\n      stream", source)

    def test_runtime_end_abort_and_disconnect_stop_processing_pulse(self):
        socket_source = SOCKET_JS.read_text(encoding="utf-8")
        handlers_source = EVENT_HANDLERS_JS.read_text(encoding="utf-8")

        self.assertGreaterEqual(
            socket_source.count("window.releaseActiveStreamAvatar()"),
            2,
        )
        self.assertGreaterEqual(
            handlers_source.count("window.releaseActiveStreamAvatar()"),
            2,
        )

    def test_stream_avatar_assets_are_cache_busted(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("/static/css/base.css?v=stream-avatar-1", source)
        self.assertIn("/static/css/chat.css?v=stream-avatar-1", source)
        self.assertIn("/static/js/chat.js?v=stream-avatar-2", source)
        self.assertIn("/static/js/socket.js?v=avatar-geometry-1&stream-avatar-1-archived-session-restore-3&anonymous-mode=1&input-focus=2&bubble-utility-retry=1", source)
        self.assertIn(
            "/static/js/socket/event-handlers.js?v=stream-avatar-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
