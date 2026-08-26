from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
AVATAR_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
MEMORY_VIEW_JS = ROOT / "ui" / "static" / "js" / "runtime" / "runtime-memory-view.js"
AVATAR_CSS = ROOT / "ui" / "static" / "css" / "runtime-avatar.css"
DOC = ROOT / "LIVE_AVATAR.md"


class DelayedMemoryHighlightContractTests(unittest.TestCase):
    def test_pin_and_load_are_both_secondary_link_sources(self):
        avatar = AVATAR_JS.read_text(encoding="utf-8")
        view = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn(
            "record && (record.pinned || record.loaded)",
            avatar,
        )
        self.assertIn(".filter(isDelayedMemoryReportInContext)", view)
        self.assertNotIn("isDelayedMemoryReportExplicitlyLoaded", view)

    def test_secondary_target_is_tier1_not_tier2(self):
        css = AVATAR_CSS.read_text(encoding="utf-8")
        tier2 = re.search(
            r"(\.jin-avatar-memory-dash-delayed\.is-memory-pinned,[^{]+)\{\s*filter:",
            css,
            re.S,
        )
        tier1 = re.search(
            r"(\.jin-avatar-memory-dash-delayed:not\(\.is-memory-pinned\):not\(\.is-context-loaded\)\.is-runtime-cited,[^{]+)\{\s*filter:",
            css,
            re.S,
        )

        self.assertIsNotNone(tier2)
        self.assertIsNotNone(tier1)
        self.assertNotIn("is-delayed-memory-secondary-linked", tier2.group(1))
        self.assertIn("is-delayed-memory-secondary-linked", tier1.group(1))

    def test_delayed_ring_has_exactly_two_filter_tiers(self):
        css = AVATAR_CSS.read_text(encoding="utf-8")
        delayed_filter_blocks = []
        for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
            owns_delayed_selector = any(
                re.match(r"^\s*\.jin-avatar-memory-dash-delayed(?:[.:#\[]|$)", selector)
                for selector in selectors.split(",")
            )
            if owns_delayed_selector and "filter:" in body:
                delayed_filter_blocks.append(selectors)

        self.assertEqual(len(delayed_filter_blocks), 2, delayed_filter_blocks)


    def test_delayed_memory_uses_one_base_hue(self):
        avatar = AVATAR_JS.read_text(encoding="utf-8")

        self.assertNotIn("DELAYED_MEMORY_RING_ACTIVE_COLOR", avatar)
        self.assertIn(
            "mixColors(DELAYED_MEMORY_RING_COLOR, overallColor, 0.12)",
            avatar,
        )
        self.assertIn("glowColor: color", avatar)
        self.assertIn(
            'getMemorySignalColors("delayed", overallColor)',
            avatar,
        )
        self.assertNotIn("data-metabolism-base-color", avatar)
        self.assertNotIn("data-metabolism-glow-color", avatar)

    def test_direct_dm_links_all_own_l4_facts_but_secondary_does_not(self):
        avatar = AVATAR_JS.read_text(encoding="utf-8")
        view = MEMORY_VIEW_JS.read_text(encoding="utf-8")

        self.assertIn("const linkedFactIds =", avatar)
        self.assertIn("report.anchor_fact_ids,", avatar)
        self.assertIn("report.facts_ids,", avatar)
        self.assertIn("report.absorbed_fact_ids,", avatar)
        self.assertIn("report.long_term_facts_ids,", avatar)
        self.assertIn("delayedMemoryFactIds: record.linkedFactIds", avatar)
        self.assertIn(
            '".jin-avatar-memory-dash-delayed.is-memory-pinned, "',
            avatar,
        )
        self.assertNotIn(
            '".jin-avatar-memory-dash-delayed.is-delayed-memory-secondary-linked, "',
            avatar,
        )
        self.assertIn(".filter(isDelayedMemoryReportInContext)", view)
        self.assertIn("report.anchor_fact_ids,", view)
        self.assertIn("report.facts_ids,", view)
        self.assertIn("report.absorbed_fact_ids,", view)
        self.assertIn("report.long_term_facts_ids,", view)

    def test_secondary_link_does_not_become_panel_sort_signal(self):
        view = MEMORY_VIEW_JS.read_text(encoding="utf-8")
        sort_start = view.index("function sortHighlightedMemoryRows(")
        sort_end = view.index(
            "function getActiveThinkMemoryCitationIdentitySets(",
            sort_start,
        )
        sort_body = view[sort_start:sort_end]

        self.assertNotIn("runtime-memory-delayed-row-secondary-linked", sort_body)
        self.assertIn("runtime-memory-context-loaded-hit", sort_body)

    def test_delayed_tier2_is_visibly_stronger_than_tier1(self):
        css = AVATAR_CSS.read_text(encoding="utf-8")
        tier2 = re.search(
            r"\.jin-avatar-memory-dash-delayed\.is-memory-pinned,[^{]+\{([^}]*)\}",
            css,
            re.S,
        )
        tier1 = re.search(
            r"\.jin-avatar-memory-dash-delayed:not\(\.is-memory-pinned\):not\(\.is-context-loaded\)\.is-runtime-cited,[^{]+\{([^}]*)\}",
            css,
            re.S,
        )

        self.assertIsNotNone(tier2)
        self.assertIsNotNone(tier1)
        self.assertIn("brightness(2.20)", tier2.group(1))
        self.assertIn("saturate(1.90)", tier2.group(1))
        self.assertIn("brightness(1.46)", tier1.group(1))
        self.assertNotIn("brightness(2.20)", tier1.group(1))

    def test_dm_to_l4_relation_reuses_soft_tier(self):
        css = AVATAR_CSS.read_text(encoding="utf-8")
        match = re.search(
            r"\.jin-avatar-memory-dash-l4\.is-delayed-memory-linked-hit\s*\{([^}]*)\}",
            css,
            re.S,
        )
        self.assertIsNotNone(match)
        self.assertIn("brightness(1.46)", match.group(1))
        self.assertNotIn("brightness(1.72)", match.group(1))

    def test_contract_is_documented(self):
        doc = DOC.read_text(encoding="utf-8")
        self.assertIn("### Delayed Memory Highlight Contract", doc)
        self.assertIn("exactly two highlight tiers", doc)
        self.assertIn("secondary cross-linked DM", doc)


if __name__ == "__main__":
    unittest.main()
