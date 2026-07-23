from __future__ import annotations

from pathlib import Path
import re

from utils import assets_utils as assets_common


def normalize_skill_name(
    name: str,
) -> str:

    normalized = str(
        name
        or ""
    ).strip()

    if normalized.lower().endswith(
        ".txt"
    ):
        normalized = normalized[:-4]

    normalized = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        normalized,
    ).strip(
        "_"
    ).lower()

    normalized = re.sub(
        r"_+",
        "_",
        normalized,
    )

    return normalized


def _skill_item(
    path: Path,
    *,
    include_content: bool = False,
) -> dict:

    lines = assets_common._read_lines(
        path
    )
    item = {
        "name": normalize_skill_name(
            path.stem
        ),
        "path": assets_common._relative(
            path
        ),
        "line_count": len(
            lines
        ),
    }

    if include_content:
        item["content"] = path.read_text(
            encoding="utf-8",
        ).strip()

    return item


def _find_skill_path(
    skill: str,
) -> Path | None:

    requested = normalize_skill_name(
        skill
    )

    if not requested:
        return None

    for path in sorted(
        assets_common.SKILLS_ROOT.glob("*.txt")
    ):
        if normalize_skill_name(
            path.stem
        ) == requested:
            return path

    return None


def list_skills(skill: str = "") -> dict:
    assets_common.ensure_assets_tree()

    requested = normalize_skill_name(
        skill
    )

    items = []
    for path in sorted(
        assets_common.SKILLS_ROOT.glob("*.txt")
    ):
        if (
            requested
            and requested != normalize_skill_name(path.stem)
        ):
            continue

        items.append(
            _skill_item(
                path
            )
        )

    return {
        "ok": True,
        "action": "list_skills",
        "requested": requested,
        "skills": items,
    }


def load_skill(
    skill: str,
) -> dict:

    assets_common.ensure_assets_tree()

    requested = normalize_skill_name(
        skill
    )
    path = _find_skill_path(
        requested
    )

    if path is None:
        return {
            "ok": False,
            "action": "append_skill",
            "requested": requested,
            "error": "skill_not_found",
        }

    item = _skill_item(
        path,
        include_content=True,
    )

    return {
        "ok": True,
        "action": "append_skill",
        "requested": requested,
        "skill": item,
    }
