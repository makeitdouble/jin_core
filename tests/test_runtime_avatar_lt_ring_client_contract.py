from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
AVATAR_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
)
RUNTIME_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
AVATAR_CSS = ROOT / "ui" / "static" / "css" / "runtime-avatar.css"
INPUT_JS = ROOT / "ui" / "static" / "js" / "socket" / "input.js"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimeAvatarLTRingClientContractTests(unittest.TestCase):

    def test_memory_rings_expand_by_ten_pixels_and_active_is_dynamic_midpoint(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        radii = {}
        for kind in ("lt", "delayed"):
            match = re.search(
                rf"{kind}: Object\.freeze\(\{{\s*radius: (\d+),",
                source,
            )
            self.assertIsNotNone(match, kind)
            radii[kind] = int(match.group(1))

        file_match = re.search(
            r"FILE_RING_LAYOUT = Object\.freeze\(\{\s*radius: (\d+),",
            source,
        )
        self.assertIsNotNone(file_match)
        file_radius = int(file_match.group(1))

        active_block = re.search(
            r"active: Object\.freeze\(\{(?P<body>.*?)\n    \}\),",
            source,
            re.S,
        )
        self.assertIsNotNone(active_block)

        self.assertEqual(radii["delayed"], 168)
        self.assertEqual(radii["lt"], 178)
        self.assertEqual(file_radius, 198)
        self.assertEqual(radii["lt"] - radii["delayed"], 10)
        self.assertEqual(file_radius - 188, 10)
        self.assertNotIn("radius:", active_block.group("body"))
        self.assertIn("strokeWidth: 2.175", active_block.group("body"))
        self.assertIn("function getOutermostLTMemoryRingRadius(records)", source)
        self.assertIn("function getActiveMemoryRingLayout(ltMemoryRecords)", source)
        self.assertIn("outermostLTRadius", source)
        self.assertIn("+ FILE_RING_LAYOUT.radius", source)
        self.assertIn(") / 2,", source)

        # With 153 facts there are two L-T lanes: 178 / 182.
        # ACTIVE therefore sits exactly at (182 + 198) / 2 = 190.
        outermost_lt_radius = radii["lt"] + 4
        self.assertEqual(outermost_lt_radius, 182)
        self.assertEqual((outermost_lt_radius + file_radius) / 2, 190)

    def test_lt_ring_spills_into_new_outer_lanes_every_hundred_facts(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("const LT_MEMORY_RING_MAX_FACTS = 100;", source)
        self.assertIn("const LT_MEMORY_RING_RADIUS_STEP = 4;", source)
        self.assertIn("function getLTMemoryRingBatches(records)", source)
        self.assertIn("rotationKeySuffix: `:${laneIndex}`", source)
        self.assertIn("records.slice(", source)
        self.assertIn("startIndex + LT_MEMORY_RING_MAX_FACTS", source)
        self.assertIn("+ LT_MEMORY_RING_RADIUS_STEP * laneIndex", source)
        self.assertIn("appendLTMemorySignalRings(", source)
        self.assertIn("captureMemoryRingPhases(svg, kind)", source)
        self.assertIn("restoreMemoryRingPhases(", source)
        self.assertIn("previousRotationPhases", source)
        self.assertIn("nodeState.avatarMemoryRadius = Number(layout.radius);", source)

    def test_lt_sync_repositions_active_ring_when_lane_count_changes(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        start = source.index("function syncLTMemoryState()")
        end = source.index("function syncFileSignalRingState", start)
        body = source[start:end]

        lt_index = body.index('"lt",')
        active_index = body.index('"active",')

        self.assertLess(lt_index, active_index)
        self.assertIn("{ applyGlows: false }", body)
        self.assertIn("applyAvatarReactiveGlows();", body)

    def test_lt_facts_are_rendered_as_reference_aware_memory_dashes(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("function getLTMemoryAvatarRecords()", source)
        self.assertIn("window.JinRuntime.ltMemory", source)
        self.assertIn('typeof ltMemory.getFacts === "function"', source)
        self.assertIn('"data-lt-fact-id": options.ltFactId || null', source)
        self.assertIn('kind === "lt"', source)
        self.assertIn("id,\n              key,", source)
        self.assertIn("referenceAliases: record.referenceAliases", source)
        self.assertIn("dot: record.archived", source)
        self.assertIn("const avatarNodeState = new WeakMap();", source)
        self.assertIn("delayedMemoryFactIds:", source)
        self.assertIn("normalizeLTFactIds(options.delayedMemoryFactIds)", source)
        self.assertIn("delayedMemoryAnchorFactIds:", source)
        self.assertIn("normalizeLTFactIds(options.delayedMemoryAnchorFactIds)", source)
        self.assertIn("ltFactIds:", source)
        self.assertIn("normalizeLTFactIds(options.ltFactIds)", source)
        self.assertIn("nodeState.avatarMemoryAngle = Number(options.angle);", source)
        self.assertNotIn('"data-delayed-memory-fact-ids"', source)
        self.assertNotIn('"data-delayed-memory-anchor-fact-ids"', source)
        self.assertNotIn('"data-lt-fact-ids"', source)
        self.assertNotIn('"data-avatar-memory-angle"', source)
        self.assertIn('class: "jin-avatar-center"', source)
        self.assertIn("function syncMemorySignalLayer(kind", source)
        self.assertIn("function syncLTMemoryArchiveState()", source)
        self.assertIn("function syncDelayedMemoryState()", source)
        self.assertIn("function syncActiveMemoryState()", source)
        self.assertIn("function syncLTMemoryState()", source)
        self.assertIn("setLTMemoryDashArchivedState(", source)
        self.assertIn("syncActiveMemoryState,", source)
        self.assertIn("syncDelayedMemoryState,", source)
        self.assertIn("syncLTMemoryState,", source)
        self.assertIn("applyDelayedMemoryFactLinkGlow()", source)
        self.assertIn("is-delayed-memory-linked-hit", source)
        self.assertIn("strokeWidth: 1.05", source)
        self.assertIn("strokeWidth: 3.10", source)
        self.assertIn("strokeWidth: 2.175", source)
        self.assertIn("arcTrimPixels: 4", source)
        self.assertIn("function getMemoryDashArcDegrees(layout, slotDegrees)", source)
        self.assertIn("function getMemoryDotRadius(layout)", source)
        self.assertIn("options.arcDegrees,\n        0.8,", source)
        self.assertIn("degreesFromArcPixels(\n        layout.arcTrimPixels,", source)
        self.assertNotIn("MEMORY_DASH_LENS_", source)
        self.assertNotIn("syncMemoryDashEmphasisGeometry", source)
        lt_sync_start = source.index("function syncMemorySignalLayer(kind")
        lt_sync_end = source.index("function setDelayedMemoryDashPinned(", lt_sync_start)
        self.assertNotIn(
            "requestAnimationFrame",
            source[lt_sync_start:lt_sync_end],
        )

        css_source = AVATAR_CSS.read_text(encoding="utf-8")
        self.assertIn(".jin-avatar-memory-dash-lt", css_source)
        self.assertIn(".jin-avatar-memory-dash.is-memory-dot", css_source)
        self.assertIn(".is-delayed-memory-linked-hit", css_source)
        self.assertIn("@keyframes jin-avatar-memory-absorb-dot", css_source)
        self.assertIn("rgba(147, 197, 253, 0.30)", css_source)

    def test_lt_ring_is_rendered_between_delayed_and_active_rings(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        start = source.index("function appendMemorySignalRings(")
        end = source.index("\n  function appendDefs(", start)
        body = source[start:end]

        delayed_index = body.index("appendMemorySignalRing(")
        lt_index = body.index("appendLTMemorySignalRings(")
        active_index = body.rindex("appendMemorySignalRing(")

        self.assertLess(delayed_index, lt_index)
        self.assertLess(lt_index, active_index)

    def test_runtime_orbit_radii_follow_snapshot_line_order(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("const sourceOrderRatio =", source)
        self.assertIn(": 1 - index / (lines.length - 1);", source)
        self.assertIn(
            "records.sort((first, second) => first.index - second.index);",
            source,
        )
        self.assertIn("const maximumRadius = previous.radius -", source)
        self.assertNotIn(
            "records.sort((first, second) => first.radius - second.radius);",
            source,
        )

    def test_runtime_orbit_highlight_uses_current_ring_color_glow(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn('orbitGroup.classList.add("has-runtime-change-marker")', source)
        self.assertIn(".jin-avatar-orbit.is-memory-hover-hit", css_source)
        self.assertIn("const ringRgb = hexToRgb(ringColor);", source)
        self.assertIn("--jin-avatar-runtime-glow-near", source)
        self.assertIn("--jin-avatar-cited-glow-near", source)
        self.assertIn("brightness(1.5)", css_source)
        self.assertIn(
            "var(--jin-avatar-runtime-glow-near, var(--jin-avatar-cited-glow-near",
            css_source,
        )
        self.assertIn(
            ".jin-avatar-memory-dash.is-memory-hover-hit {\n    filter:",
            css_source,
        )
        self.assertNotIn("feGaussianBlur", source)

    def test_runtime_ring_stripes_follow_value_punctuation_and_keep_legacy_look(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("function appendLongFieldStripes(group, record, color)", source)
        self.assertIn('if (/[!?]/.test(String(record.value || ""))) {', source)
        self.assertIn("appendLongFieldStripes(orbitGroup, record, ringColor);", source)
        self.assertIn("const stripeCount = Math.round(12 + random() * 24);", source)
        self.assertIn('stroke: color,', source)
        self.assertIn('"stroke-width": 0.75 + random() * 0.8,', source)
        self.assertIn('"stroke-opacity": 0.52 + random() * 0.34,', source)
        self.assertNotIn("if (record.isLong) {", source)
        self.assertNotIn("is-jin-avatar-stripe-breathing", source)

    def test_avatar_shell_aura_uses_jin_color(self):
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn(".jin-runtime-avatar-shell::before", css_source)
        self.assertIn("@keyframes jin-avatar-shell-aura-breathe", css_source)
        self.assertIn("var(--jin-color, #1f4f8f)", css_source)
        self.assertIn("color-mix(in srgb, var(--jin-color, #1f4f8f)", css_source)

    def test_avatar_depth_and_enter_softness_are_restored_without_collapsed_glow(self):
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn(".jin-runtime-avatar-shell::after", css_source)
        self.assertNotIn("#memory-panel.panel-collapsed .jin-runtime-avatar-shell::before", css_source)
        self.assertNotIn("#memory-panel.panel-collapsed .jin-runtime-avatar-shell::after", css_source)
        self.assertNotIn("--jin-avatar-aura-opacity-high: 0.66;", css_source)
        self.assertIn("animation: jin-avatar-orbit-enter 0.92s cubic-bezier(0.16, 0.84, 0.22, 1) forwards;", css_source)
        self.assertIn("transform: scale(0.82);", css_source)
        self.assertIn("transform: scale(1.012);", css_source)

    def test_inactive_runtime_orbit_opacity_skips_nested_dots(self):
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn(
            ".jin-avatar-orbit:not(.has-runtime-change-marker):not(.is-runtime-cited):not(.is-memory-reference-hit):not(.is-memory-hover-hit) > circle[fill=\"none\"]",
            css_source,
        )
        self.assertIn("opacity: 0.5;", css_source)
        self.assertNotIn(
            ".jin-avatar-orbit:not(.is-runtime-cited):not(.is-memory-reference-hit):not(.is-memory-hover-hit) circle[fill]:not([fill=\"none\"])",
            css_source,
        )

    def test_paused_active_memory_keeps_its_ring_slot_but_draws_no_dash(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function getActiveMemoryAvatarRecordStatus(value)",
            source,
        )
        self.assertIn(
            'getActiveMemoryAvatarRecordStatus(value) === "paused";',
            source,
        )
        self.assertIn(
            "paused,\n          text: lineText,",
            source,
        )
        self.assertIn(
            'if (record.paused) {\n          return;\n        }',
            source,
        )
        self.assertIn(
            "const slotDegrees = 360 / records.length;",
            source,
        )
        self.assertNotIn('createSvgElement("title")', source)
        self.assertNotIn("appendTitle(", source)

    def test_memory_ring_changes_can_sync_without_avatar_refresh(self):
        source = RUNTIME_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function syncDelayedMemoryStateToAvatar()",
            source,
        )
        self.assertIn(
            "function syncActiveMemoryStateToAvatar()",
            source,
        )
        self.assertIn(
            "if (!syncActiveMemoryStateToAvatar()) {\n    refreshRuntimeAvatar();",
            source,
        )
        self.assertIn(
            "if (!syncDelayedMemoryStateToAvatar()) {\n    refreshRuntimeAvatar();",
            source,
        )
        self.assertNotIn(
            "function buildDelayedMemoryAvatarLayoutSignature(",
            source,
        )
        self.assertNotIn(
            "function syncDelayedMemoryPinsToAvatar(",
            source,
        )

    def test_avatar_can_repaint_without_changing_geometry_seed(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn(
            "function repaintAvatar()",
            source,
        )
        self.assertIn(
            "seedNonce: avatarRefreshNonce",
            source,
        )
        self.assertIn(
            "repaint: repaintAvatar,",
            source,
        )

    def test_open_delayed_report_keeps_avatar_fact_links_highlighted(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn(
            '"jin:delayed-memory-report-active"',
            source,
        )
        self.assertIn(
            "let delayedMemoryReportActiveState = null;",
            source,
        )
        self.assertIn(
            "function getActiveAvatarMemoryHoverIds()",
            source,
        )
        self.assertIn(
            "window.addEventListener(DELAYED_MEMORY_REPORT_ACTIVE_EVENT",
            source,
        )
        self.assertIn(
            "getFocusedMemoryDashNodes(svg)",
            source,
        )
        self.assertIn(
            "is-delayed-memory-linked-hit",
            source,
        )

    def test_avatar_core_button_toggles_memory_layers_without_refresh(self):
        index_source = INDEX_HTML.read_text(encoding="utf-8")
        avatar_source = AVATAR_JS.read_text(encoding="utf-8")
        input_source = INPUT_JS.read_text(encoding="utf-8")
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn('title="hide"', index_source)
        self.assertIn('aria-label="hide"', index_source)
        self.assertIn('alt="hide"', index_source)
        self.assertIn(
            "function toggleRuntimeAvatarMemoryLayers()",
            input_source,
        )
        self.assertIn(
            "avatar.toggleMemoryLayers();",
            input_source,
        )
        self.assertIn(
            "function setMemoryLayersHidden(hidden)",
            avatar_source,
        )
        self.assertIn("toggleMemoryLayers,", avatar_source)
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-orbit",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-counter-orbit",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-scaffold",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-dormant .jin-avatar-orbit-entry",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-file-ring",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-file-dot",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-center-ring",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar-shell.is-memory-layers-hidden::before",
            css_source,
        )
        self.assertIn(
            'const MEMORY_LAYERS_DORMANT_CLASS = "is-memory-layers-dormant";',
            avatar_source,
        )
        self.assertIn("const MEMORY_LAYERS_FADE_MS = 420;", avatar_source)
        self.assertIn("function setMemoryLayersDormant(dormant)", avatar_source)
        self.assertIn(
            "setMemoryLayersDormant(true);",
            avatar_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-dormant .jin-avatar-orbit",
            css_source,
        )
        self.assertIn("display: none !important;", css_source)
        self.assertIn("animation: none !important;", css_source)
        self.assertIn(
            'const avatarShell = avatarRoot?.closest(".jin-runtime-avatar-shell") || null;',
            avatar_source,
        )
        self.assertIn(
            "avatarShell.classList.toggle(",
            avatar_source,
        )
        self.assertIn('class: "jin-avatar-scaffold"', avatar_source)
        self.assertIn('class: "jin-avatar-center-ring"', avatar_source)

        click_start = input_source.index("if (memoryLayersToggle) {")
        click_end = input_source.index("chatForm.addEventListener", click_start)
        click_block = input_source[click_start:click_end]

        self.assertNotIn("avatar.refresh", click_block)

    def test_avatar_svg_keeps_circular_rings_inside_resized_panel_box(self):
        avatar_source = AVATAR_JS.read_text(encoding="utf-8")
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn(
            'preserveAspectRatio: "xMidYMid meet"',
            avatar_source,
        )
        self.assertNotIn(
            'preserveAspectRatio: "none"',
            avatar_source,
        )
        self.assertIn(
            "aspect-ratio: 1;",
            css_source,
        )
        self.assertIn(
            "height: auto;",
            css_source,
        )
        self.assertIn(
            "align-self: center;",
            css_source,
        )
        self.assertNotIn(
            "--runtime-avatar-panel-width",
            css_source,
        )

    def test_avatar_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            "/static/css/runtime-avatar.css?v=memory-layers-dormant-1&reasoning-whisper=3",
            source,
        )
        self.assertIn(
            "/static/js/runtime/runtime-avatar.js?v=memory-layers-dormant-1&reasoning-whisper=3&stable-render=2",
            source,
        )
        self.assertIn("avatar-radius=2", source)
        self.assertIn(
            "/static/js/socket/input.js?v=jin-size-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
