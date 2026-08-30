from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
AVATAR_JS = (
    ROOT / "ui" / "static" / "js" / "runtime" / "runtime-avatar.js"
)
INDEX_HTML = ROOT / "ui" / "templates" / "index.html"


class RuntimeAvatarNodePayloadClientContractTests(unittest.TestCase):

    def test_rich_avatar_payload_is_kept_out_of_svg_datasets(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertIn("const avatarNodeState = new WeakMap();", source)
        self.assertIn("function setAvatarNodeState(node, values)", source)
        self.assertIn("runtimeLineIdentity:", source)
        self.assertIn("runtimeLineKey:", source)
        self.assertIn("runtimeLineText:", source)
        self.assertIn("referenceAliases", source)
        self.assertIn("delayedMemoryFactIds:", source)
        self.assertIn("delayedMemoryAnchorFactIds:", source)
        self.assertIn("ltFactIds:", source)
        self.assertIn("linkedDelayedMemoryIds:", source)
        self.assertIn("nodeState.avatarMemoryAngle = Number(options.angle);", source)

        for attribute in (
            "data-runtime-line-key",
            "data-runtime-line-text",
            "data-runtime-line-identity",
            "data-memory-reference-aliases",
            "data-lt-fact-ids",
            "data-delayed-memory-fact-ids",
            "data-delayed-memory-anchor-fact-ids",
            "data-avatar-memory-angle",
            "data-linked-delayed-memory-ids",
        ):
            self.assertNotIn(attribute, source)

    def test_svg_keeps_only_lightweight_identity_and_sync_hooks(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        for attribute in (
            "data-avatar-memory-hover-id",
            "data-active-memory-id",
            "data-delayed-memory-id",
            "data-lt-fact-id",
            "data-file-id",
            "data-runtime-line-index",
            "data-avatar-rotation-key",
        ):
            self.assertIn(attribute, source)

        self.assertIn("function getAvatarPayloadNodes(svg)", source)
        self.assertIn("getAvatarNodeState(node)", source)
        self.assertIn("getAvatarMemoryReferenceAliases(node)", source)

    def test_dead_svg_titles_and_per_record_visual_payload_are_gone(self):
        source = AVATAR_JS.read_text(encoding="utf-8")

        self.assertNotIn('createSvgElement("title")', source)
        self.assertNotIn("appendTitle(", source)
        self.assertIn("function getMemorySignalColors(kind, overallColor)", source)
        self.assertIn("setMemoryDashGlowVariables(\n      ring,", source)
        self.assertNotIn(
            'dashGroup.style.setProperty(\n        "--jin-avatar-memory-dot-opacity"',
            source,
        )

    def test_avatar_cache_key_is_bumped_for_node_state_cleanup(self):
        source = INDEX_HTML.read_text(encoding="utf-8")

        self.assertIn("avatar-node-state=1", source)


if __name__ == "__main__":
    unittest.main()
