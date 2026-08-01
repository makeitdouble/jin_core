from __future__ import annotations

import json
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ASSETS_ROOT = PROJECT_ROOT / "assets"
SKILLS_ROOT = ASSETS_ROOT / "skills"
WILDCARDS_ROOT = ASSETS_ROOT / "wildcards"
PROMPTS_ROOT = ASSETS_ROOT / "prompts"
TEMPLATES_ROOT = ASSETS_ROOT / "templates"
OUTPUTS_ROOT = ASSETS_ROOT / "outputs"

DEFAULT_WILDCARD_CATEGORIES = (
    "clothing",
    "style",
    "scene",
    "character",
    "camera",
    "lighting",
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


def _normalize_text_content(value) -> str:
    content = str(
        value
        if value is not None
        else ""
    )

    return (
        content
        .replace("\\r\\n", "\n")
        .replace("\\n", "\n")
        .replace("\\r", "\n")
        .replace("\r\n", "\n")
        .replace("\r", "\n")
    )


def _with_terminal_newline(content: str) -> str:
    if (
        content
        and not content.endswith("\n")
    ):
        return f"{content}\n"

    return content


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


def _write_text_content(
    path: Path,
    content,
    *,
    overwrite: bool = False,
) -> dict:
    if path.exists() and not overwrite:
        return {
            "ok": False,
            "error": "file_exists",
            "path": _relative(path),
        }

    normalized_content = _normalize_text_content(
        content
    )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        _with_terminal_newline(
            normalized_content
        ),
        encoding="utf-8",
    )

    lines = normalized_content.splitlines()

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


def _asset_action_handlers() -> dict:
    from utils.file_manager_asset_utils import (
        append_asset_file,
        create_asset_file,
        preview_file,
    )
    from utils.wildcards_asset_utils import (
        append_wildcard_file,
        check_duplicates,
        create_wildcard_file,
        create_wildcard_library,
        expand_template,
        generate_prompt_batch,
        list_wildcards,
        sample_wildcard,
    )

    return {
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
        "create_asset_file": create_asset_file,
        "append_asset_file": append_asset_file,
    }


def _run_single_asset_action(payload: dict) -> dict:
    payload = _normalize_action_payload(
        payload
    )
    action = str(
        payload.get("action", "")
        or ""
    ).strip()

    handler = _asset_action_handlers().get(
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
