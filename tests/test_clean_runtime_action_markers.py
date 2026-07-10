import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


class CleanRuntimeActionMarkerTests(unittest.TestCase):

    def test_builtin_asset_skills_use_clean_tags(self):

        for relative_path in (
            "assets/skills/file_manager.txt",
            "assets/skills/wildcards.txt",
        ):
            content = (
                PROJECT_ROOT
                / relative_path
            ).read_text(
                encoding="utf-8",
            )

            self.assertIn(
                "<ASSET_ACTION>",
                content,
            )
            self.assertIn(
                "</ASSET_ACTION>",
                content,
            )
            self.assertNotIn(
                "<INTERNAL_ACTION_ASSET_ACTION>",
                content,
            )
            self.assertNotIn(
                "</INTERNAL_ACTION_ASSET_ACTION>",
                content,
            )


if __name__ == "__main__":
    unittest.main()
