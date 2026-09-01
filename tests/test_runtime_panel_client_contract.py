from pathlib import Path
import shutil
import subprocess
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

    def test_context_bar_reflows_when_runtime_panel_width_changes(self):
        source = RUNTIME_PANEL_JS.read_text(encoding="utf-8")

        self.assertIn(
            "let contextPanelResizeObserver = null;",
            source,
        )
        self.assertIn(
            'typeof window.ResizeObserver === "function"',
            source,
        )
        self.assertIn(
            "contextPanelResizeObserver.observe(",
            source,
        )
        self.assertIn(
            "contextRuntimePanel",
            source,
        )
        self.assertIn(
            "scheduleRuntimeTelemetryFrame();",
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

    @unittest.skipUnless(
        shutil.which("node"),
        "node is required for the browser-side JIN size test",
    )
    def test_jin_size_relative_units_resolve_against_live_viewport(self):
        script = r'''
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const start = source.indexOf("function normalizeJinSizeLength(");
const end = source.indexOf("function normalizeJinPositionPayload(", start);

if (start < 0 || end < 0) {
  throw new Error("JIN size normalization helpers not found");
}

global.window = { innerWidth: 2000, innerHeight: 1000 };
global.document = {
  documentElement: { clientWidth: 2000, clientHeight: 1000 },
};

const helpers = eval(
  `(() => { ${source.slice(start, end)}; return { normalizeJinSizePayload }; })()`
);
const cases = [
  ["120px", { width: 120, height: 120 }],
  ["w:25vw h:40vh", { width: 500, height: 400 }],
  ["w:50% h:25%", { width: 1000, height: 250 }],
  ["10%", { width: 200, height: 100 }],
  ["w:12.5vw h:20%", { width: 250, height: 200 }],
  [{ size: "w:25vw h:40%", width: 25, height: 40 }, { width: 500, height: 400 }],
];

for (const [input, expected] of cases) {
  const actual = helpers.normalizeJinSizePayload(input);
  if (JSON.stringify(actual) !== JSON.stringify(expected)) {
    throw new Error(`unexpected size for ${JSON.stringify(input)}: ${JSON.stringify(actual)}`);
  }
}

if (helpers.normalizeJinSizePayload("120em") !== null) {
  throw new Error("unsupported CSS unit must not be treated as px");
}
'''
        completed = subprocess.run(
            [
                shutil.which("node"),
                "-e",
                script,
                str(LOGGER_JS),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        self.assertEqual(
            completed.returncode,
            0,
            completed.stderr or completed.stdout,
        )

    def test_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            "/static/js/runtime/runtime-panel.js?v=context-bar-resize-1&status-bootstrap=1",
            source,
        )
        self.assertIn(
            "/static/js/socket/input.js?v=jin-size-1",
            source,
        )
        self.assertIn("jin-size-units=1", source)


if __name__ == "__main__":
    unittest.main()
