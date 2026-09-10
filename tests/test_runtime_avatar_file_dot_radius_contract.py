from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
AVATAR_CSS = ROOT / "ui" / "static" / "css" / "runtime-avatar.css"


class RuntimeAvatarFileDotRadiusContractTests(unittest.TestCase):
    def test_pinned_and_loaded_file_dots_use_large_active_radius(self):
        css = AVATAR_CSS.read_text(encoding="utf-8")
        match = re.search(
            r"\.jin-avatar-file-dot\.is-memory-pinned \.jin-avatar-file-dot-core,\s*"
            r"\.jin-avatar-file-dot\.is-context-loaded \.jin-avatar-file-dot-core\s*\{([^}]*)\}",
            css,
            re.S,
        )

        self.assertIsNotNone(match)
        self.assertIn("fill-opacity: 1 !important;", match.group(1))
        self.assertIn("r: 3.45px;", match.group(1))

    def test_hover_and_context_linked_file_dots_keep_small_radius(self):
        css = AVATAR_CSS.read_text(encoding="utf-8")
        match = re.search(
            r"\.jin-avatar-file-dot:not\(\.is-memory-pinned\):not\(\.is-context-loaded\)\.is-memory-hover-hit \.jin-avatar-file-dot-core,\s*"
            r"\.jin-avatar-file-dot:not\(\.is-memory-pinned\):not\(\.is-context-loaded\)\.is-delayed-memory-context-linked \.jin-avatar-file-dot-core\s*\{([^}]*)\}",
            css,
            re.S,
        )

        self.assertIsNotNone(match)
        self.assertIn("fill-opacity: 0.78 !important;", match.group(1))
        self.assertIn("r: 2.7px;", match.group(1))

    def test_reference_and_delayed_link_file_dots_keep_small_radius(self):
        css = AVATAR_CSS.read_text(encoding="utf-8")
        match = re.search(
            r"\.jin-avatar-file-dot:not\(\.is-memory-pinned\):not\(\.is-context-loaded\)\.is-memory-reference-hit \.jin-avatar-file-dot-core,\s*"
            r"\.jin-avatar-file-dot:not\(\.is-memory-pinned\):not\(\.is-context-loaded\)\.is-delayed-memory-linked-hit \.jin-avatar-file-dot-core\s*\{([^}]*)\}",
            css,
            re.S,
        )

        self.assertIsNotNone(match)
        self.assertIn("fill-opacity: 1 !important;", match.group(1))
        self.assertIn("r: 2.7px;", match.group(1))


if __name__ == "__main__":
    unittest.main()
