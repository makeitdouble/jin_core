from __future__ import annotations

import json
import random
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = PROJECT_ROOT / "assets"
SKILLS_ROOT = ASSETS_ROOT / "skills"
WILDCARDS_ROOT = ASSETS_ROOT / "wildcards"
PROMPTS_ROOT = ASSETS_ROOT / "prompts"
TEMPLATES_ROOT = ASSETS_ROOT / "templates"
OUTPUTS_ROOT = ASSETS_ROOT / "outputs"

DEFAULT_WILDCARD_SKILL = """wildcards

Purpose:
Use project assets as external reusable resources for prompt generation. Assets are files, not memory and not identity.

When to use:
- When the user asks to create wildcard lists, prompt fragments, prompt batches, style libraries, clothing lists, pose lists, camera lists, lighting lists, templates, or reusable generation fragments.
- Use assets instead of pasting huge lists into chat.

Folder layout:
- assets/wildcards/ contains reusable prompt fragment lists.
- assets/prompts/ contains ready prompt batches.
- assets/templates/ contains prompt templates.
- assets/outputs/ contains generated or assembled outputs.

Wildcard files:
- Plain .txt only.
- One line equals one reusable prompt fragment.
- No markdown, numbering, JSON, comments, quotes, or decorative headings inside wildcard files.
- Read only the needed file or a small sample. Do not inline large wildcard libraries into chat context.

Wildcard syntax:
- __category/file__ means read one random line from assets/wildcards/category/file.txt.
- Example: __clothing/women_tops__ reads assets/wildcards/clothing/women_tops.txt.

Safe behavior:
- Create folders and .txt files inside assets when useful.
- Append existing wildcard files when the user asks to expand them.
- Do not delete or overwrite existing files unless the user explicitly asks.
- On name conflict, prefer a new numbered file or report the conflict.

Action workflow:
1. Use LIST_SKILLS to retrieve this skill before a wildcard workflow.
2. Use ASSET_ACTION with JSON payload for list_wildcards, create_wildcard_file, append_wildcard_file, sample_wildcard, expand_template, generate_prompt_batch, check_duplicates, or preview_file.
3. Emit ASSET_ACTION as a JSON block:
<INTERNAL_ACTION_ASSET_ACTION>
{"action":"list_wildcards"}
</INTERNAL_ACTION_ASSET_ACTION>
4. Payload fields may be top-level or nested under args, for example {"action":"create_wildcard_file","args":{"path":"clothing/test_tops","content":"line one\nline two"}}.
5. Use create_wildcard_library with files when creating several wildcard files at once.
6. Use create_wildcard_file only for files under assets/wildcards. Do not use it to save ready prompt batches.
7. Use generate_prompt_batch when the user asks to create N prompts from a template or wildcards and save them to assets/prompts or assets/outputs.
   Schema: {"action":"generate_prompt_batch","template":"...","count":20,"path":"assets/prompts/test_prompts.txt"}.
8. Prompt batch outputs must contain fully expanded prompts. Never write unresolved __category/file__ tokens as final prompt lines.
9. If a required wildcard file from the template is missing, stop and report the missing wildcard path, unless the user explicitly asked to create that wildcard first.
10. After ASSET_ACTION completes, report paths, counts, and 3-5 examples when useful. Do not paste huge generated lists into chat.
"""


DEFAULT_WILDCARD_CATEGORIES = (
    "clothing",
    "style",
    "scene",
    "character",
    "camera",
    "lighting",
)

WILDCARD_TOKEN_RE = re.compile(
    r"__([A-Za-z0-9_\-/]+)__"
)


def ensure_assets_tree() -> None:
    for path in (
        SKILLS_ROOT,
        PROMPTS_ROOT,
        TEMPLATES_ROOT,
        OUTPUTS_ROOT,
        *(WILDCARDS_ROOT / category for category in DEFAULT_WILDCARD_CATEGORIES),
    ):
        path.mkdir(
            parents=True,
            exist_ok=True,
        )

    skill_file = SKILLS_ROOT / "wildcards.txt"
    if not skill_file.exists():
        skill_file.write_text(
            DEFAULT_WILDCARD_SKILL,
            encoding="utf-8",
        )


def _asset_path(
    root: Path,
    relative_path: str,
    *,
    default_suffix: str = "",
) -> Path:
    ensure_assets_tree()

    raw_path = str(
        relative_path
        or ""
    ).strip().replace(
        "\\",
        "/",
    )

    if root == ASSETS_ROOT and raw_path.startswith("assets/"):
        raw_path = raw_path[len("assets/"):]

    if root == WILDCARDS_ROOT:
        if raw_path.startswith("assets/"):
            if raw_path.startswith("assets/wildcards/"):
                raw_path = raw_path[len("assets/wildcards/"):]
            else:
                raise ValueError("wildcard path must stay inside assets/wildcards")
        elif raw_path.startswith("wildcards/"):
            raw_path = raw_path[len("wildcards/"):]

    if not raw_path:
        raise ValueError("path is required")

    candidate = Path(raw_path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")

    if default_suffix and not candidate.suffix:
        candidate = candidate.with_suffix(default_suffix)

    resolved = (
        root / candidate
    ).resolve()
    resolved_root = root.resolve()

    if (
        resolved != resolved_root
        and resolved_root not in resolved.parents
    ):
        raise ValueError("path must stay inside assets")

    return resolved


def _read_lines(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(str(path.relative_to(PROJECT_ROOT)))

    return [
        line.strip()
        for line in path.read_text(
            encoding="utf-8",
        ).splitlines()
        if line.strip()
    ]


def _clean_lines(value) -> list[str]:
    if isinstance(
        value,
        str,
    ):
        normalized_value = (
            value
            .replace("\\r\\n", "\n")
            .replace("\\n", "\n")
            .replace("\\r", "\n")
            .replace("\\b", "\n")
            .replace("\\f", "\n")
            .replace("\\v", "\n")
        )
        normalized_value = re.sub(
            r"[\t\b\f\v]+",
            "\n",
            normalized_value,
        )
        normalized_value = re.sub(
            r"\\(?=[A-Za-zА-Яа-я])",
            "\n",
            normalized_value,
        )
        candidates = normalized_value.splitlines()
    elif isinstance(
        value,
        list,
    ):
        candidates = value
    else:
        candidates = []

    lines = []
    for candidate in candidates:
        line = str(
            candidate
            or ""
        ).strip()
        if line:
            lines.append(
                line
            )

    return lines


def _extract_json_string_field(
    text: str,
    field_name: str,
) -> str:
    match = re.search(
        rf'"{re.escape(field_name)}"\s*:\s*"(?P<value>[^"]*)"',
        text,
        re.IGNORECASE | re.DOTALL,
    )

    if not match:
        return ""

    return match.group(
        "value",
    ).strip()


def _parse_lenient_asset_payload(
    payload_text: str,
) -> dict:
    text = str(
        payload_text
        or ""
    ).strip()

    action = _extract_json_string_field(
        text,
        "action",
    )
    path = _extract_json_string_field(
        text,
        "path",
    )

    content_match = re.search(
        r'"content"\s*:\s*"(?P<content>.*)"\s*\}\s*\}?\s*$',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    content = (
        content_match.group("content").strip()
        if content_match
        else ""
    )

    if not (
        action
        and (
            path
            or content
        )
    ):
        return {}

    payload = {
        "action": action,
    }

    if path:
        payload["path"] = path

    if content:
        payload["content"] = content

    return payload


def _normalize_action_payload(payload: dict) -> dict:
    if not isinstance(
        payload,
        dict,
    ):
        return {}

    args = payload.get(
        "args",
        {},
    )

    if not isinstance(
        args,
        dict,
    ):
        args = {}

    normalized = {
        **args,
        **{
            key: value
            for key, value in payload.items()
            if key != "args"
        },
    }

    if (
        "lines" not in normalized
        and "content" in normalized
    ):
        normalized["lines"] = normalized["content"]

    return normalized


def _relative(path: Path) -> str:
    return str(
        path.relative_to(PROJECT_ROOT)
    ).replace(
        "\\",
        "/",
    )


def _write_text_file(
    path: Path,
    lines: list[str],
    *,
    overwrite: bool = False,
) -> dict:
    if path.exists() and not overwrite:
        return {
            "ok": False,
            "error": "file_exists",
            "path": _relative(path),
        }

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        "\n".join(lines).strip() + ("\n" if lines else ""),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "path": _relative(path),
        "line_count": len(lines),
        "examples": lines[:5],
    }


def _next_available_path(path: Path) -> Path:
    if not path.exists():
        return path

    suffix = path.suffix
    stem = path.stem
    parent = path.parent
    index = 2

    while True:
        candidate = parent / f"{stem}_{index:03d}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


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

    lines = _read_lines(
        path
    )
    item = {
        "name": normalize_skill_name(
            path.stem
        ),
        "path": _relative(
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
        SKILLS_ROOT.glob("*.txt")
    ):
        if normalize_skill_name(
            path.stem
        ) == requested:
            return path

    return None


def list_skills(skill: str = "") -> dict:
    ensure_assets_tree()

    requested = normalize_skill_name(
        skill
    )

    items = []
    for path in sorted(
        SKILLS_ROOT.glob("*.txt")
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

    ensure_assets_tree()

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


def list_wildcards(category: str = "") -> dict:
    ensure_assets_tree()

    root = WILDCARDS_ROOT
    if category:
        root = _asset_path(
            WILDCARDS_ROOT,
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

        lines = _read_lines(path)
        items.append({
            "path": _relative(path),
            "wildcard": str(
                path.relative_to(WILDCARDS_ROOT)
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
    path = _asset_path(
        WILDCARDS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    lines = _clean_lines(
        payload.get("lines")
        or payload.get("content")
    )

    result = _write_text_file(
        path,
        lines,
        overwrite=False,
    )
    result["action"] = "create_wildcard_file"
    return result


def append_wildcard_file(payload: dict) -> dict:
    path = _asset_path(
        WILDCARDS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    lines = _clean_lines(
        payload.get("lines")
        or payload.get("content")
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    existing_lines = _read_lines(path) if path.exists() else []
    merged_lines = existing_lines + lines
    path.write_text(
        "\n".join(merged_lines).strip() + ("\n" if merged_lines else ""),
        encoding="utf-8",
    )

    return {
        "ok": True,
        "action": "append_wildcard_file",
        "path": _relative(path),
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
    path = _asset_path(
        WILDCARDS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    count = int(
        payload.get("count", 5)
        or 5
    )
    lines = _read_lines(path)
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
        "path": _relative(path),
        "items": random.sample(
            lines,
            sample_count,
        ) if sample_count else [],
    }


def preview_file(payload: dict) -> dict:
    path = _asset_path(
        ASSETS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    count = int(
        payload.get("count", 10)
        or 10
    )
    lines = _read_lines(path)

    return {
        "ok": True,
        "action": "preview_file",
        "path": _relative(path),
        "line_count": len(lines),
        "items": lines[: max(0, count)],
    }


def _wildcard_path(name: str) -> Path:
    return _asset_path(
        WILDCARDS_ROOT,
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
                "path": _relative(path),
            })

    return missing


def _random_wildcard_line(name: str) -> str:
    path = _wildcard_path(
        name
    )
    lines = _read_lines(path)

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

    path = _asset_path(
        ASSETS_ROOT,
        output_file,
        default_suffix=".txt",
    )
    path = _next_available_path(
        path
    )
    result = _write_text_file(
        path,
        prompts,
        overwrite=False,
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
        path = PROJECT_ROOT / item["path"]
        for index, line in enumerate(
            _read_lines(path),
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


def _run_single_asset_action(payload: dict) -> dict:
    payload = _normalize_action_payload(
        payload
    )
    action = str(
        payload.get("action", "")
        or ""
    ).strip()

    handlers = {
        "list_wildcards": lambda data: list_wildcards(
            str(data.get("category", "") or "")
        ),
        "create_wildcard_file": create_wildcard_file,
        "append_wildcard_file": append_wildcard_file,
        "create_wildcard_library": create_wildcard_library,
        "sample_wildcard": sample_wildcard,
        "expand_template": expand_template,
        "generate_prompt_batch": generate_prompt_batch,
        "check_duplicates": check_duplicates,
        "preview_file": preview_file,
    }

    handler = handlers.get(
        action
    )

    if handler is None:
        return {
            "ok": False,
            "action": action or "unknown",
            "error": "unknown_asset_action",
        }

    return handler(
        payload
    )


def run_asset_action(payload_text: str) -> dict:
    ensure_assets_tree()

    try:
        payload = json.loads(
            str(
                payload_text
                or ""
            ).strip()
        )
    except json.JSONDecodeError as exc:
        payload = _parse_lenient_asset_payload(
            payload_text
        )

        if not payload:
            return {
                "ok": False,
                "action": "asset_action",
                "error": "invalid_json",
                "detail": str(exc),
            }

    try:
        if isinstance(
            payload,
            dict,
        ) and isinstance(
            payload.get("operations"),
            list,
        ):
            results = [
                _run_single_asset_action(operation)
                for operation in payload["operations"]
                if isinstance(operation, dict)
            ]
            return {
                "ok": all(
                    result.get("ok")
                    for result in results
                ),
                "action": "asset_action_batch",
                "results": results,
            }

        if not isinstance(
            payload,
            dict,
        ):
            return {
                "ok": False,
                "action": "asset_action",
                "error": "payload_must_be_object",
            }

        return _run_single_asset_action(
            payload
        )

    except Exception as exc:
        return {
            "ok": False,
            "action": "asset_action",
            "error": exc.__class__.__name__,
            "detail": str(exc),
        }


def format_asset_result(result: dict) -> str:
    return json.dumps(
        result,
        ensure_ascii=False,
        indent=2,
    )
