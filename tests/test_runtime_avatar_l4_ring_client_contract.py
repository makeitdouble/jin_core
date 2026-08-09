from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
AVATAR_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
)
RUNTIME_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime.js"
AVATAR_CSS = ROOT / "ui" / "static" / "css" / "runtime-avatar.css"
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimeAvatarL4RingClientContractTests(unittest.TestCase):

    def test_memory_rings_have_evenly_spaced_l4_delayed_active_radii(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        radii = {}
        for kind in ("l4", "delayed", "active"):
            match = re.search(
                rf"{kind}: Object\.freeze\(\{{\s*radius: (\d+),",
                source,
            )
            self.assertIsNotNone(match, kind)
            radii[kind] = int(match.group(1))

        self.assertEqual(radii["delayed"] - radii["l4"], 10)
        self.assertEqual(radii["active"] - radii["delayed"], 10)
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

        css_source = AVATAR_CSS.read_text(encoding="utf-8")
        self.assertIn(".jin-avatar-memory-dash-l4", css_source)
        self.assertIn(".jin-avatar-memory-dash.is-memory-dot", css_source)
        self.assertIn(".is-delayed-memory-linked-hit", css_source)
        self.assertIn("@keyframes jin-avatar-memory-absorb-dot", css_source)
        self.assertIn("rgba(147, 197, 253, 0.30)", css_source)

    def test_l4_ring_is_appended_inside_delayed_and_active_rings(self):
        source = AVATAR_JS.read_text(encoding="utf-8")
        start = source.index("function appendMemorySignalRings(")
        end = source.index("\n  function appendDefs(", start)
        body = source[start:end]

        l4_index = body.index('"l4"')
        delayed_index = body.index('"delayed"')
        active_index = body.index('"active"')

        self.assertLess(l4_index, delayed_index)
        self.assertLess(delayed_index, active_index)

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

    def test_avatar_cache_versions_are_bumped(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn(
            "/static/css/runtime-avatar.css?v=memory-rings-6",
            source,
        )
        self.assertIn(
            "/static/js/runtime/runtime-avatar.js?v=memory-rings-17",
            source,
        )


if __name__ == "__main__":
    unittest.main()
