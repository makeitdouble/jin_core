from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AnonymousModeClientContractTests(unittest.TestCase):

    def test_mode_is_explicit_and_has_no_private_browser_detection(self):
        source = (
            ROOT
            / "ui/static/js/runtime/runtime-anonymous-mode.js"
        ).read_text(encoding="utf-8")

        self.assertIn('ANONYMOUS_MODE_QUERY_PARAM = "anonymous_mode"', source)
        self.assertIn('ANONYMOUS_SESSION_QUERY_PARAM = "anonymous_session_id"', source)
        self.assertIn('ANONYMOUS_SESSION_SUFFIX = "-anon"', source)
        self.assertIn('ANONYMOUS_SESSION_STORAGE_KEY = "jin.anonymousSession.v1"', source)
        self.assertIn("readExplicitRequest", source)
        self.assertIn("buildAnonymousWindowUrl", source)
        self.assertIn("openAnonymousWindow", source)
        self.assertIn("window.sessionStorage", source)
        self.assertIn('classList.add("jin-anonymous-room")', source)
        self.assertNotIn("storage.estimate", source)
        self.assertNotIn("webkitTemporaryStorage", source)
        self.assertNotIn("navigator.userAgent", source)
        self.assertNotIn("jin.normalProfile", source)

    def test_removed_detector_switches_are_not_exposed_by_config_or_template(self):
        config_source = (ROOT / "config.example.py").read_text(encoding="utf-8")
        template_source = (
            ROOT / "ui/templates/index.html"
        ).read_text(encoding="utf-8")
        app_source = (ROOT / "app.py").read_text(encoding="utf-8")

        for text in (
            "ENABLE_DEFAULT_ANONYMOUS_MODE",
            "ENABLE_GLOBAL_ANONYMOUS_MODE",
            "build_anonymous_mode_config",
        ):
            self.assertNotIn(text, config_source)
            self.assertNotIn(text, template_source)
            self.assertNotIn(text, app_source)

    def test_anonymous_room_uses_one_tab_scoped_memory_snapshot(self):
        mode_source = (
            ROOT
            / "ui/static/js/runtime/runtime-anonymous-mode.js"
        ).read_text(encoding="utf-8")
        storage_source = (
            ROOT
            / "ui/static/js/runtime/runtime-storage.js"
        ).read_text(encoding="utf-8")
        lt_source = (
            ROOT
            / "ui/static/js/runtime/runtime-lt-memory.js"
        ).read_text(encoding="utf-8")

        for field in (
            "frame_memory",
            "active_memory",
            "long_term_memory",
            "delayed_memory",
        ):
            self.assertIn(field, mode_source)

        self.assertIn("readAnonymousSessionSnapshot", storage_source)
        self.assertIn("updateAnonymousSessionSnapshotField", storage_source)
        self.assertIn('"active_memory"', storage_source)
        self.assertIn('"delayed_memory"', storage_source)
        self.assertIn('"frame_memory"', storage_source)
        self.assertIn("readAnonymousStore", lt_source)
        self.assertIn("writeAnonymousStore", lt_source)
        self.assertIn('"long_term_memory"', lt_source)
        self.assertNotIn("jin.activeMemory.anonymous.v1", storage_source)
        self.assertNotIn("jin.delayedMemoryReports.anonymous.v1", storage_source)

    def test_socket_marks_explicit_anonymous_connection(self):
        source = (
            ROOT
            / "ui/static/js/socket.js"
        ).read_text(encoding="utf-8")

        self.assertIn('"anonymous_mode",', source)
        self.assertIn('"1"', source)
        self.assertIn("anonymousMode.ready", source)
        self.assertIn('type: "active_memory_store_sync"', source)

    def test_long_press_avatar_opens_anonymous_room_only_after_full_fade(self):
        source = (
            ROOT
            / "ui/static/js/socket/input.js"
        ).read_text(encoding="utf-8")
        css_source = (
            ROOT
            / "ui/static/css/runtime-avatar.css"
        ).read_text(encoding="utf-8")

        self.assertIn("ANONYMOUS_ROOM_LONG_PRESS_MS = 1500", source)
        self.assertNotIn("ANONYMOUS_ROOM_DARK_PAUSE_MS", source)
        self.assertIn('"pointerdown"', source)
        self.assertIn("setPointerCapture(event.pointerId)", source)
        self.assertIn("openAnonymousWindow", source)
        self.assertIn('ANONYMOUS_ROOM_HOLD_CLASS = "is-anonymous-room-hold"', source)
        self.assertIn("setAnonymousRoomHoldVisual(true)", source)
        self.assertIn("setAnonymousRoomHoldVisual(false)", source)
        self.assertIn("anonymousRoomPointerId !== heldPointerId", source)
        self.assertIn("cancelAnonymousRoomPointerHold", source)
        self.assertIn("suppressNextMemoryLayersClick", source)
        self.assertIn("avatar.toggleMemoryLayers();", source)
        self.assertNotIn("avatar.setMemoryLayersHidden(true)", source)
        self.assertIn(".jin-runtime-avatar.is-anonymous-room-hold", css_source)
        self.assertIn("transition: opacity 1.5s linear !important;", css_source)

    def test_anonymous_room_darkens_scene_below_ui(self):
        css_source = (
            ROOT / "ui/static/css/base.css"
        ).read_text(encoding="utf-8")
        template_source = (
            ROOT / "ui/templates/index.html"
        ).read_text(encoding="utf-8")

        self.assertIn('id="scene-anonymous-tint"', template_source)
        self.assertIn("--scene-layer-anonymous: 5", css_source)
        self.assertIn("#scene-anonymous-tint", css_source)
        self.assertIn("html.jin-anonymous-room #scene-anonymous-tint", css_source)

    def test_restricted_write_failure_is_struck_through(self):
        source = (
            ROOT
            / "ui/static/js/socket/runtime-actions.js"
        ).read_text(encoding="utf-8")

        self.assertIn("restrictedWriteFailure", source)
        self.assertIn('=== "restricted_write"', source)
        self.assertIn("strikeThroughFailure", source)

    def test_explicit_mode_loads_before_storage_and_socket(self):
        source = (
            ROOT
            / "ui/templates/index.html"
        ).read_text(encoding="utf-8")

        mode = source.index("runtime-anonymous-mode.js")
        storage = source.index("runtime-storage.js")
        socket = source.index("static/js/socket.js")
        self.assertLess(mode, storage)
        self.assertLess(storage, socket)


if __name__ == "__main__":
    unittest.main()
