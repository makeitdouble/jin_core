from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_PANEL_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-panel.js"
SOCKET_INPUT_JS = ROOT / "ui" / "static" / "js" / "socket" / "input.js"
LOGGER_JS = ROOT / "ui" / "static" / "js" / "logger" / "logger.js"
BASE_CSS = ROOT / "ui" / "static" / "css" / "base.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimePanelClientContractTests(unittest.TestCase):

    def test_service_tab_can_display_summarizer_usage_when_service_is_empty(self):
        source = RUNTIME_PANEL_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function buildServiceRuntimeUsageFallback(",
            source,
        )
        self.assertIn(
            "runtimeHasUsage(serviceRuntime)",
            source,
        )
        self.assertIn(
            "runtimeHasUsage(summarizerRuntime)",
            source,
        )
        self.assertIn(
            "return getServiceRuntime();",
            source,
        )

    def test_runtime_counter_uses_live_total_during_reasoning(self):
        source = RUNTIME_PANEL_JS.read_text(encoding="utf-8")

        self.assertIn(
            "used: getRuntimeUsageAmount(",
            source,
        )
        self.assertIn(
            "const used = totalUsed;",
            source,
        )
        self.assertIn(
            "const totalUsed =\n      runtimeInfo\n        ? getRuntimeUsageAmount(",
            source,
        )

    def test_submit_focuses_brain_context_tab(self):
        panel_source = RUNTIME_PANEL_JS.read_text(encoding="utf-8")
        input_source = SOCKET_INPUT_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function focusBrainContextTab()",
            panel_source,
        )
        self.assertIn(
            "window.focusBrainContextTab = function ()",
            panel_source,
        )
        self.assertIn(
            "window.focusBrainContextTab();",
            input_source,
        )

    def test_jin_size_collapsed_avatar_resize_animates_inside_viewport(self):
        logger_source = LOGGER_JS.read_text(encoding="utf-8")
        css_source = BASE_CSS.read_text(encoding="utf-8")

        self.assertIn(
            "const COLLAPSED_AVATAR_SIZE_ANIMATION_MS = 320;",
            logger_source,
        )
        self.assertIn(
            "function resolveCollapsedAvatarSizeTargetGeometry(",
            logger_source,
        )
        self.assertIn(
            "bounds.parentRect.width - targetWidth - bounds.gap",
            logger_source,
        )
        self.assertIn(
            "bounds.parentRect.height - targetHeight - bounds.gap",
            logger_source,
        )
        self.assertIn(
            "function animateCollapsedAvatarSize(panel, width, height)",
            logger_source,
        )
        self.assertIn(
            "setPanelFreeDock(panel);",
            logger_source,
        )
        self.assertNotIn(
            "COLLAPSED_AVATAR_EDGE_BUMP_DISTANCE",
            logger_source,
        )
        self.assertNotIn(
            "bumpProgress",
            logger_source,
        )
        self.assertNotIn(
            "edgeBump",
            logger_source,
        )
        self.assertIn(
            "pendingJinSizeResult.animated !== true",
            logger_source,
        )
        self.assertNotIn(
            "function repaintRuntimeAvatarAfterResize()",
            logger_source,
        )
        self.assertNotIn(
            "typeof avatar.repaint === \"function\"",
            logger_source,
        )
        self.assertNotIn(
            "repaintRuntimeAvatarAfterResize();",
            logger_source,
        )
        self.assertIn(
            "#memory-panel.panel-collapsed.panel-avatar-size-changing",
            css_source,
        )
        self.assertIn(
            "opacity: 1 !important;",
            css_source,
        )
        self.assertIn(
            "#memory-panel.panel-avatar-size-changing #memory-drag-handle",
            css_source,
        )
        self.assertIn(
            "НИКОГДА НЕ ТРОГАТЬ ЭТИ АУРЫ",
            css_source,
        )
        self.assertIn(
            "@keyframes memoryGlowPulse",
            css_source,
        )
        self.assertIn(
            "@keyframes memoryL2GlowPulse",
            css_source,
        )
        self.assertIn(
            "@keyframes memoryL3GlowPulse",
            css_source,
        )
        self.assertIn(
            "@keyframes factCheckGlowPulse",
            css_source,
        )
        self.assertIn(
            "#memory-panel.memory-updating.memory-pulse",
            css_source,
        )
        self.assertIn(
            "#memory-panel.memory-l2-updating.memory-l2-pulse",
            css_source,
        )
        self.assertIn(
            "#memory-panel.memory-l3-updating.memory-l3-pulse",
            css_source,
        )
        self.assertIn(
            "#memory-panel.fact-check-running.fact-check-pulse",
            css_source,
        )

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            "/static/js/runtime/runtime-panel.js?v=live-reasoning-tokens-1",
            source,
        )
        self.assertIn(
            "/static/js/socket/input.js?v=jin-size-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
