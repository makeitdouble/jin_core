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


class RuntimeAvatarL4RingClientContractTests(unittest.TestCase):

    def test_memory_rings_have_evenly_spaced_delayed_l4_active_radii(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        radii = {}
        for kind in ("l4", "delayed", "active"):
            match = re.search(
                rf"{kind}: Object\.freeze\(\{{\s*radius: (\d+),",
                source,
            )
            self.assertIsNotNone(match, kind)
            radii[kind] = int(match.group(1))

        self.assertEqual(radii["l4"] - radii["delayed"], 10)
        self.assertEqual(radii["active"] - radii["l4"], 10)
        self.assertEqual(radii["delayed"], 158)
        self.assertEqual(radii["l4"], 168)
        self.assertEqual(radii["active"], 178)
        self.assertGreater(radii["l4"], 151)

    def test_l4_facts_are_rendered_as_reference_aware_memory_dashes(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("function getL4MemoryAvatarRecords()", source)
        self.assertIn("window.JinRuntime.l4Memory", source)
        self.assertIn('typeof l4Memory.getFacts === "function"', source)
        self.assertIn('"data-l4-fact-id": options.l4FactId || null', source)
        self.assertIn('kind === "l4"', source)
        self.assertIn("id,\n              key,", source)
        self.assertIn("referenceAliases: record.referenceAliases", source)
        self.assertIn("dot: record.archived", source)
        self.assertIn(
            '"data-delayed-memory-fact-ids":',
            source,
        )
        self.assertIn(
            '"data-delayed-memory-anchor-fact-ids":',
            source,
        )
        self.assertIn('"data-l4-fact-ids":', source)
        self.assertIn('"data-avatar-memory-angle": options.angle', source)
        self.assertIn('class: "jin-avatar-center"', source)
        self.assertIn("function syncMemorySignalLayer(kind", source)
        self.assertIn("function syncL4MemoryArchiveState()", source)
        self.assertIn("function syncDelayedMemoryState()", source)
        self.assertIn("function syncActiveMemoryState()", source)
        self.assertIn("function syncL4MemoryState()", source)
        self.assertIn("setL4MemoryDashArchivedState(", source)
        self.assertIn("syncActiveMemoryState,", source)
        self.assertIn("syncDelayedMemoryState,", source)
        self.assertIn("syncL4MemoryState,", source)
        self.assertIn("applyDelayedMemoryFactLinkGlow()", source)
        self.assertIn("is-delayed-memory-linked-hit", source)
        self.assertIn("strokeWidth: 1.05", source)
        self.assertIn("strokeWidth: 3.10", source)
        self.assertIn("arcTrimPixels: 4", source)
        self.assertIn("function getMemoryDashArcDegrees(layout, slotDegrees)", source)
        self.assertIn("function getMemoryDotRadius(layout)", source)
        self.assertIn("options.arcDegrees,\n        0.8,", source)
        self.assertIn("degreesFromArcPixels(\n        layout.arcTrimPixels,", source)
        self.assertNotIn("MEMORY_DASH_LENS_", source)
        self.assertNotIn("syncMemoryDashEmphasisGeometry", source)
        self.assertNotIn("requestAnimationFrame", source)

        css_source = AVATAR_CSS.read_text(encoding="utf-8")
        self.assertIn(".jin-avatar-memory-dash-l4", css_source)
        self.assertIn(".jin-avatar-memory-dash.is-memory-dot", css_source)
        self.assertIn(".is-delayed-memory-linked-hit", css_source)
        self.assertIn("@keyframes jin-avatar-memory-absorb-dot", css_source)
        self.assertIn("opacity: 0.70;", css_source)

    def test_l4_ring_is_rendered_between_delayed_and_active_rings(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        start = source.index("function appendMemorySignalRings(")
        end = source.index("\n  function appendDefs(", start)
        body = source[start:end]

        l4_index = body.index('"l4"')
        delayed_index = body.index('"delayed"')
        active_index = body.index('"active"')

        self.assertLess(delayed_index, l4_index)
        self.assertLess(l4_index, active_index)

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

    def test_runtime_orbit_highlight_stays_muted_without_filters(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn('orbitGroup.classList.add("has-runtime-change-marker")', source)
        self.assertIn(".jin-avatar-orbit.is-memory-hover-hit", css_source)
        self.assertIn("opacity: 0.88;", css_source)
        self.assertIn("opacity: 0.96;", css_source)
        self.assertNotIn("--jin-avatar-runtime-glow-near", source)
        self.assertNotIn("--jin-avatar-cited-glow-near", source)
        self.assertNotIn("feGaussianBlur", source)
        self.assertNotIn("drop-shadow", css_source)
        self.assertNotIn("filter:", css_source)

    def test_long_field_stripes_are_muted_and_diff_driven(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn("function appendLongFieldStripes(group, record, color, options = {})", source)
        self.assertIn("const energy =", source)
        self.assertIn("const activeStripeCount = energy > 0.32 ? 2 : 1;", source)
        self.assertIn("is-jin-avatar-stripe-breathing", source)
        self.assertIn("diffPercent,", source)
        self.assertIn("effectiveSpeed,", source)
        self.assertIn(".jin-avatar-field-stripe", css_source)
        self.assertIn("@keyframes jin-avatar-field-stripe-breathe", css_source)
        self.assertIn("--jin-avatar-stripe-base-opacity", css_source)

    def test_avatar_shell_aura_uses_jin_color_without_filters(self):
        css_source = AVATAR_CSS.read_text(encoding="utf-8")

        self.assertIn(".jin-runtime-avatar-shell::before", css_source)
        self.assertIn("@keyframes jin-avatar-shell-aura-breathe", css_source)
        self.assertIn("var(--jin-color, #1f4f8f)", css_source)
        self.assertIn("color-mix(in srgb, var(--jin-color, #1f4f8f)", css_source)
        self.assertNotIn("drop-shadow", css_source)
        self.assertNotIn("filter:", css_source)

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
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-memory-ring",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-scaffold",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-orbit-entry",
            css_source,
        )
        self.assertIn(
            ".jin-runtime-avatar.is-memory-layers-hidden .jin-avatar-center-ring",
            css_source,
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
            "/static/css/runtime-avatar.css?v=jin-size-4",
            source,
        )
        self.assertIn(
            "/static/js/runtime/runtime-avatar.js?v=jin-size-4",
            source,
        )
        self.assertIn(
            "/static/js/socket/input.js?v=jin-size-1",
            source,
        )


if __name__ == "__main__":
    unittest.main()
