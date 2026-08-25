from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ACTIONS_JS = (
    ROOT / "ui" / "static" / "js" / "socket" / "runtime-actions.js"
)
AVATAR_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
AVATAR_CSS = ROOT / "ui" / "static" / "css" / "runtime-avatar.css"
LOGGER_JS = ROOT / "ui" / "static" / "js" / "logger" / "logger.js"
RUNTIME_SESSION_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-session.js"
)
RUNTIME_STORAGE_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-storage.js"
)
WEBSOCKET_BOOTSTRAP_PY = ROOT / "websocket" / "bootstrap.py"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class JinColorTransitionClientContractTests(unittest.TestCase):

    def test_live_jin_color_uses_one_two_second_avatar_and_tint_transition(self):
        actions_source = RUNTIME_ACTIONS_JS.read_text(encoding="utf-8")
        avatar_source = AVATAR_JS.read_text(encoding="utf-8")
        avatar_css = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn("const JIN_VISUAL_SEQUENCE_COLOR_MS = 2000;", actions_source)
        self.assertEqual(
            actions_source.count(
                "transitionDurationMs: JIN_VISUAL_SEQUENCE_COLOR_MS"
            ),
            2,
        )
        self.assertIn(
            '"--scene-jin-tint-transition-duration",\n      durationValue',
            avatar_source,
        )
        self.assertIn(
            '"--jin-avatar-center-color-transition-duration",\n      durationValue',
            avatar_source,
        )
        self.assertIn(
            "Math.max(CENTER_COLOR_STEP_MS, transitionDurationMs)",
            avatar_source,
        )
        self.assertIn(
            "var(--jin-avatar-center-color-transition-duration, 0.16s)",
            avatar_css,
        )

    def test_every_center_color_change_defaults_to_two_seconds(self):
        avatar_source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn(
            "const DEFAULT_CENTER_COLOR_TRANSITION_MS = 2000;",
            avatar_source,
        )
        self.assertIn(
            ": DEFAULT_CENTER_COLOR_TRANSITION_MS;",
            avatar_source,
        )

    def test_common_checkpoint_color_is_immediate_and_boots_first(self):
        logger_source = LOGGER_JS.read_text(encoding="utf-8")
        session_source = RUNTIME_SESSION_JS.read_text(encoding="utf-8")
        storage_source = RUNTIME_STORAGE_JS.read_text(encoding="utf-8")
        bootstrap_source = WEBSOCKET_BOOTSTRAP_PY.read_text(encoding="utf-8")
        persist_start = logger_source.index("function persistRoomStateNow(")
        persist_end = logger_source.index(
            "function scheduleRoomStatePersist()",
            persist_start,
        )
        persist_block = logger_source[persist_start:persist_end]
        stored_start = logger_source.index("function getStoredRoomState()")
        stored_end = logger_source.index(
            "function enableRoomStatePersistence(",
            stored_start,
        )
        stored_block = logger_source[stored_start:stored_end]
        init_start = logger_source.index("function initRoomStatePersistence()")
        init_end = logger_source.index(
            "function clearConsoleStreamDetachTimer()",
            init_start,
        )
        init_block = logger_source[init_start:init_end]

        self.assertIn("current_jin_color: color", persist_block)
        self.assertIn("previousSnapshot.room_state", persist_block)
        self.assertIn("...checkpoint", persist_block)
        self.assertNotIn("saved_at:", persist_block)
        self.assertLess(
            persist_block.index("if (colorOnly)"),
            persist_block.index("const currentSessionId"),
        )

        self.assertIn("snapshot.current_jin_color", stored_block)
        self.assertIn("roomState.avatar.color = color;", stored_block)
        self.assertNotIn("delete roomState.avatar.color;", stored_block)
        self.assertNotIn("resolveBootstrapRoomState", stored_block)
        self.assertIn("applyBootstrapSceneTintShift", init_block)
        self.assertIn(
            "persistRoomStateNow({ colorOnly: true });",
            init_block,
        )
        self.assertIn("enableRoomStatePersistence(false);", init_block)
        self.assertNotIn("latestJinColor", storage_source)

        bootstrap_start = bootstrap_source.index(
            "browser_color = normalize_jin_color_payload("
        )
        bootstrap_end = bootstrap_source.index(
            "# Browser persistence is the exact checkpoint when available.",
            bootstrap_start,
        )
        bootstrap_block = bootstrap_source[bootstrap_start:bootstrap_end]

        self.assertIn("if browser_color:", bootstrap_block)
        self.assertIn("else:", bootstrap_block)
        self.assertIn("_bootstrap_latest_session_action_color", bootstrap_block)

        apply_start = session_source.index(
            "function applyPersistedSessionBootstrap(bootstrap)"
        )
        apply_end = session_source.index(
            "function getPersistedSessionBootstrap()",
            apply_start,
        )
        apply_block = session_source[apply_start:apply_end]

        self.assertIn("delete localRoomState.avatar.color;", apply_block)
        self.assertNotIn("applyBootstrapSceneTintShift(", apply_block)

    def test_changed_assets_have_matching_cache_bumps(self):
        index_source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertEqual(index_source.count("jin-color-transition=2"), 2)
        self.assertIn("runtime-session.js?v=", index_source)
        self.assertIn("&room-state=7&", index_source)
        self.assertIn("logger.js?v=", index_source)
        self.assertIn("&room-state=5&", index_source)


if __name__ == "__main__":
    unittest.main()
