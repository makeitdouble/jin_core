from __future__ import annotations

import random
import re
from pathlib import Path

from utils import assets_utils as assets_common


PROMPT_BATCH_OVERWRITE_EXISTING = True

WILDCARD_TOKEN_RE = re.compile(
    r"__([A-Za-z0-9_\-/]+)__"
)


def list_wildcards(category: str = "") -> dict:
    assets_common.ensure_assets_tree()

    root = assets_common.WILDCARDS_ROOT
    if category:
        root = assets_common._asset_path(
            assets_common.WILDCARDS_ROOT,
            category,
        )

    if not root.exists():
        return {
            "ok": True,
            "action": "list_wildcards",
            "wildcards": [],
        }

    items = []
    for path in sorted(
        root.rglob("*.txt")
    ):
        if not path.is_file():
            continue

        lines = assets_common._read_lines(path)
        items.append({
            "path": assets_common._relative(path),
            "wildcard": str(
                path.relative_to(assets_common.WILDCARDS_ROOT)
                .with_suffix("")
            ).replace(
                "\\",
                "/",
            ),
            "line_count": len(lines),
        })

    return {
        "ok": True,
        "action": "list_wildcards",
        "wildcards": items,
    }


def create_wildcard_file(payload: dict) -> dict:
    path = assets_common._asset_path(
        assets_common.WILDCARDS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    lines = assets_common._clean_lines(
        payload.get("lines")
        or payload.get("content")
    )

    result = assets_common._write_text_file(
        path,
        lines,
        overwrite=False,
    )
    result["action"] = "create_wildcard_file"
    return result


def append_wildcard_file(payload: dict) -> dict:
    path = assets_common._asset_path(
        assets_common.WILDCARDS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    lines = assets_common._clean_lines(
        payload.get("lines")
        or payload.get("content")
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    existing_lines = assets_common._read_lines(path) if path.exists() else []
    merged_lines = existing_lines + lines
    path.write_text(
        "\n".join(merged_lines).strip() + ("\n" if merged_lines else ""),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "action": "append_wildcard_file",
        "path": assets_common._relative(path),
        "appended_count": len(lines),
        "line_count": len(merged_lines),
    }


def create_wildcard_library(payload: dict) -> dict:
    files = payload.get(
        "files",
        {},
    )
    if not isinstance(
        files,
        dict,
    ):
        files = {}

    results = []
    for path, lines in files.items():
        result = create_wildcard_file({
            "path": path,
            "lines": lines,
        })
        results.append(
            result
        )

    return {
        "ok": all(
            result.get("ok")
            for result in results
        ),
        "action": "create_wildcard_library",
        "files": results,
    }


def sample_wildcard(payload: dict) -> dict:
    path = assets_common._asset_path(
        assets_common.WILDCARDS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    count = int(
        payload.get("count", 5)
        or 5
    )
    lines = assets_common._read_lines(path)
    sample_count = max(
        0,
        min(
            count,
            len(lines),
        ),
    )

    return {
        "ok": True,
        "action": "sample_wildcard",
        "path": assets_common._relative(path),
        "items": random.sample(
            lines,
            sample_count,
        ) if sample_count else [],
    }


def _wildcard_path(name: str) -> Path:
    return assets_common._asset_path(
        assets_common.WILDCARDS_ROOT,
        name,
        default_suffix=".txt",
    )


def _template_wildcards(template: str) -> list[str]:
    return sorted(
        set(
            WILDCARD_TOKEN_RE.findall(
                template
                or ""
            )
        )
    )


def _missing_template_wildcards(template: str) -> list[dict]:
    missing = []

    for name in _template_wildcards(template):
        path = _wildcard_path(name)
        if not path.exists():
            missing.append({
                "wildcard": name,
                "path": assets_common._relative(path),
            })

    return missing


def _random_wildcard_line(name: str) -> str:
    path = _wildcard_path(
        name
    )
    lines = assets_common._read_lines(path)

    if not lines:
        return ""

    return random.choice(
        lines
    )


def expand_template(payload: dict) -> dict:
    template = str(
        payload.get("template", "")
        or ""
    )
    count = int(
        payload.get("count", 1)
        or 1
    )

    missing = _missing_template_wildcards(
        template
    )
    if missing:
        return {
            "ok": False,
            "action": "expand_template",
            "error": "missing_wildcards",
            "missing": missing,
        }

    prompts = []
    for _ in range(
        max(0, count)
    ):
        prompts.append(
            WILDCARD_TOKEN_RE.sub(
                lambda match: _random_wildcard_line(
                    match.group(1)
                ),
                template,
            ).strip()
        )

    return {
        "ok": True,
        "action": "expand_template",
        "count": len(prompts),
        "items": prompts,
    }


def _normalize_prompt_output_file(output_file: str) -> str:
    path = str(
        output_file
        or "prompts/generated_prompts.txt"
    ).strip().replace(
        "\\",
        "/",
    )

    if path.startswith("assets/"):
        path = path[len("assets/"):]

    if not path.startswith(("prompts/", "outputs/")):
        path = f"prompts/{path}"

    return path


def generate_prompt_batch(payload: dict) -> dict:
    expanded = expand_template(
        payload
    )

    if not expanded.get("ok"):
        return {
            **expanded,
            "action": "generate_prompt_batch",
        }

    prompts = expanded.get(
        "items",
        [],
    )

    output_target = (
        payload.get("path", "")
        or payload.get("output_file", "")
    )
    output_file = _normalize_prompt_output_file(
        str(
            output_target
            or "prompts/generated_prompts.txt"
        )
    )

    path = assets_common._asset_path(
        assets_common.ASSETS_ROOT,
        output_file,
        default_suffix=".txt",
    )
    if not PROMPT_BATCH_OVERWRITE_EXISTING:
        path = assets_common._next_available_path(
            path
        )
    result = assets_common._write_text_file(
        path,
        prompts,
        overwrite=PROMPT_BATCH_OVERWRITE_EXISTING,
    )
    result["action"] = "generate_prompt_batch"
    result["examples"] = prompts[:5]
    return result


def check_duplicates(payload: dict) -> dict:
    category = str(
        payload.get("category", "")
        or payload.get("path", "")
        or ""
    ).strip()
    listed = list_wildcards(
        category
    )

    seen = {}
    duplicates = []

    for item in listed.get(
        "wildcards",
        [],
    ):
        path = assets_common.PROJECT_ROOT / item["path"]
        for index, line in enumerate(
            assets_common._read_lines(path),
            start=1,
        ):
            key = line.casefold()
            if key in seen:
                duplicates.append({
                    "text": line,
                    "first": seen[key],
                    "duplicate": {
                        "path": item["path"],
                        "line": index,
                    },
                })
                continue

            seen[key] = {
                "path": item["path"],
                "line": index,
            }

    return {
        "ok": True,
        "action": "check_duplicates",
        "duplicate_count": len(duplicates),
        "duplicates": duplicates[:50],
    }
