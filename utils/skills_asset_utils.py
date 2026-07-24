from __future__ import annotations

from pathlib import Path
import re

from utils import assets_utils as assets_common


SKILL_MANIFEST_NAMES = (
    "JIN_SKILL.md",
    "SKILL.md",
    "README.md",
)

READER_MODE_SUFFIX = "-mode.md"


def normalize_skill_name(
    name: str,
) -> str:

    normalized = str(
        name
        or ""
    ).strip()

    for suffix in (
        ".txt",
        ".md",
    ):
        if normalized.lower().endswith(
            suffix
        ):
            normalized = normalized[:-len(suffix)]
            break

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


def _find_directory_skill_manifest(
    directory: Path,
) -> Path | None:

    for manifest_name in SKILL_MANIFEST_NAMES:
        candidate = directory / manifest_name
        if candidate.is_file():
            return candidate

    fallback_files = sorted(
        path
        for path in directory.iterdir()
        if path.is_file()
        and path.suffix.lower() in {
            ".txt",
            ".md",
        }
    )

    return (
        fallback_files[0]
        if fallback_files
        else None
    )


def _iter_skill_entries() -> list[tuple[str, Path, Path | None]]:

    entries: list[tuple[str, Path, Path | None]] = []

    for path in sorted(
        assets_common.SKILLS_ROOT.iterdir(),
        key=lambda item: item.name.casefold(),
    ):
        if path.is_file() and path.suffix.lower() == ".txt":
            entries.append((
                normalize_skill_name(
                    path.stem
                ),
                path,
                None,
            ))
            continue

        if not path.is_dir() or path.name.startswith("."):
            continue

        manifest = _find_directory_skill_manifest(
            path
        )
        if manifest is None:
            continue

        entries.append((
            normalize_skill_name(
                path.name
            ),
            manifest,
            path,
        ))

    return entries


def _directory_reader_modes(
    directory: Path | None,
) -> list[str]:

    if directory is None:
        return []

    return [
        path.name
        for path in sorted(
            directory.iterdir(),
            key=lambda value: value.name.casefold(),
        )
        if path.is_file()
        and path.name.casefold().endswith(
            READER_MODE_SUFFIX
        )
    ]


def _skill_item(
    path: Path,
    *,
    skill_name: str | None = None,
    directory: Path | None = None,
    include_content: bool = False,
) -> dict:

    lines = assets_common._read_lines(
        path
    )
    item = {
        "name": normalize_skill_name(
            skill_name
            or path.stem
        ),
        "path": assets_common._relative(
            path
        ),
        "line_count": len(
            lines
        ),
    }

    if directory is not None:
        item["directory"] = assets_common._relative(
            directory
        )
        item["files"] = [
            assets_common._relative(
                child
            )
            for child in sorted(
                directory.iterdir(),
                key=lambda value: value.name.casefold(),
            )
            if child.is_file()
        ]
        reader_modes = _directory_reader_modes(
            directory
        )
        if reader_modes:
            item["modes"] = reader_modes

    if include_content:
        item["content"] = path.read_text(
            encoding="utf-8",
        ).strip()

    return item


def _find_skill_entry(
    skill: str,
) -> tuple[str, Path, Path | None] | None:

    requested = normalize_skill_name(
        skill
    )

    if not requested:
        return None

    for name, path, directory in _iter_skill_entries():
        if name == requested:
            return (
                name,
                path,
                directory,
            )

    return None


def list_skills(skill: str = "") -> dict:
    assets_common.ensure_assets_tree()

    requested = normalize_skill_name(
        skill
    )

    items = []
    for name, path, directory in _iter_skill_entries():
        if (
            requested
            and requested != name
        ):
            continue

        items.append(
            _skill_item(
                path,
                skill_name=name,
                directory=directory,
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
    entry = _find_skill_entry(
        requested
    )

    if entry is None:
        return {
            "ok": False,
            "action": "append_skill",
            "requested": requested,
            "error": "skill_not_found",
        }

    name, path, directory = entry
    item = _skill_item(
        path,
        skill_name=name,
        directory=directory,
        include_content=True,
    )

    return {
        "ok": True,
        "action": "append_skill",
        "requested": requested,
        "skill": item,
    }
