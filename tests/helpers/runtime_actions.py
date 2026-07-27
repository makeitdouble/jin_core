import unittest
from pathlib import Path
from unittest.mock import patch


class FakeContext:
    pass


class FakeEmitter:
    def __init__(self):
        self.events = []

    async def emit(self, event):
        self.events.append(event)


def legacy_internal_action_marker(marker: str) -> str:
    if marker.startswith(
        "</"
    ):
        return marker.replace(
            "</",
            "</INTERNAL_ACTION_",
            1,
        )

    return marker.replace(
        "<",
        "<INTERNAL_ACTION_",
        1,
    )


def patch_asset_roots(root: Path):
    assets_root = root / "assets"
    return (
        patch("utils.assets_utils.PROJECT_ROOT", root),
        patch("utils.assets_utils.ASSETS_ROOT", assets_root),
        patch("utils.assets_utils.SKILLS_ROOT", assets_root / "skills"),
        patch("utils.assets_utils.WILDCARDS_ROOT", assets_root / "wildcards"),
        patch("utils.assets_utils.PROMPTS_ROOT", assets_root / "prompts"),
        patch("utils.assets_utils.TEMPLATES_ROOT", assets_root / "templates"),
        patch("utils.assets_utils.OUTPUTS_ROOT", assets_root / "outputs"),
    )


class RuntimeActionTestCase(unittest.TestCase):
    def patch_asset_roots(self, root: Path):
        return patch_asset_roots(
            root
        )

    def write_skill_fixture(
        self,
        root: Path,
        filename: str,
        content: str,
    ):
        skill_path = (
            root
            / "assets"
            / "skills"
            / filename
        )
        skill_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        skill_path.write_text(
            content,
            encoding="utf-8",
        )
        return skill_path
