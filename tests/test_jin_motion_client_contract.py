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
        self.assertIn("rect.left + (rect.width / 2)", source)
        self.assertIn("rect.top + (rect.height / 2)", source)

    def test_position_coordinates_target_avatar_center(self):
        source = LOGGER_JS.read_text(encoding="utf-8")
        self.assertIn("- (panelRect.width / 2)", source)
        self.assertIn("- (panelRect.height / 2)", source)
        self.assertIn("- (targetWidth / 2)", source)
        self.assertIn("- (targetHeight / 2)", source)

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

    def test_avatar_inspector_restores_world_geometry_and_keeps_model_updates(self):
        source = LOGGER_JS.read_text(encoding="utf-8")
        self.assertIn("let avatarInspectorWorldState = null;", source)
        self.assertIn("beginAvatarInspector(memoryPanel);", source)
        self.assertIn("takeAvatarWorldStateForInspectorClose()", source)
        self.assertIn("animateCollapsedAvatarWorldState(", source)
        self.assertIn("size: pendingJinSize", source)
        self.assertIn("position: pendingJinPosition", source)
        self.assertIn("&& !avatarInspectorWorldState", source)


if __name__ == "__main__":
    unittest.main()
