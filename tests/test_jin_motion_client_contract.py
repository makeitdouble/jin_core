import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGGER_JS = ROOT / "ui" / "static" / "js" / "logger" / "logger.js"
RUNTIME_ACTIONS_JS = ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
SOCKET_JS = ROOT / "ui" / "static" / "js" / "socket.js"


class JinMotionClientContractTests(unittest.TestCase):

    def test_avatar_snapshot_reports_live_geometry_and_window(self):
        source = LOGGER_JS.read_text(encoding="utf-8")
        self.assertIn("speed_px_per_second: getJinMoveSpeed()", source)
        self.assertIn("window_width: Math.max(1, Math.round(window.innerWidth))", source)
        self.assertIn("window_height: Math.max(1, Math.round(window.innerHeight))", source)
        self.assertIn("x: Math.round(rect.left)", source)
        self.assertIn("y: Math.round(rect.top)", source)

    def test_position_and_speed_apply_without_chat_bubbles(self):
        source = RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        speed_index = source.index('if (action === "jin_speed")')
        position_index = source.index('if (action === "jin_position")')
        generic_save_index = source.index('action === "save_active_memory"', position_index)
        self.assertLess(speed_index, generic_save_index)
        self.assertLess(position_index, generic_save_index)
        motion_slice = source[speed_index:generic_save_index]
        self.assertNotIn("window.appendRuntimeAction", motion_slice)
        self.assertIn("setJinMoveSpeed", motion_slice)
        self.assertIn("setPendingJinPosition", motion_slice)

    def test_restore_resume_sends_fresh_browser_geometry(self):
        source = SOCKET_JS.read_text(encoding="utf-8")
        self.assertIn("resumePayload.runtime_avatar", source)
        self.assertIn("getRuntimeAvatarSnapshot()", source)


if __name__ == "__main__":
    unittest.main()
