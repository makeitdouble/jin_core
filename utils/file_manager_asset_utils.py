from __future__ import annotations

from utils import assets_utils as assets_common


def preview_file(payload: dict) -> dict:
    path = assets_common._asset_path(
        assets_common.ASSETS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    count = int(
        payload.get("count", 10)
        or 10
    )
    lines = assets_common._read_lines(path)

    return {
        "ok": True,
        "action": "preview_file",
        "path": assets_common._relative(path),
        "line_count": len(lines),
        "items": lines[: max(0, count)],
    }


def read_asset_text_preview(
    payload: dict,
) -> dict:
    path = assets_common._asset_path(
        assets_common.ASSETS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    max_chars = int(
        payload.get("max_chars", 60000)
        or 60000
    )
    max_chars = max(
        1,
        min(
            max_chars,
            250000,
        ),
    )

    if not path.exists():
        raise FileNotFoundError(str(path.relative_to(assets_common.PROJECT_ROOT)))

    if not path.is_file():
        raise ValueError("path must point to a file")

    content = path.read_text(
        encoding="utf-8",
    )
    preview = content[:max_chars]

    return {
        "ok": True,
        "action": "asset_text_preview",
        "path": assets_common._relative(path),
        "name": assets_common._relative(path),
        "kind": "text",
        "type": "text/plain",
        "size_bytes": path.stat().st_size,
        "line_count": len(content.splitlines()),
        "preview_chars": len(preview),
        "preview_limit": max_chars,
        "truncated": len(content) > max_chars,
        "text_content": preview,
    }


def create_asset_file(payload: dict) -> dict:
    path = assets_common._asset_path(
        assets_common.ASSETS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )
    overwrite = bool(
        payload.get("overwrite", False)
    )

    if (
        "content" in payload
        and "lines" not in payload
    ):
        result = assets_common._write_text_content(
            path,
            payload.get("content"),
            overwrite=overwrite,
        )
    else:
        lines = assets_common._clean_lines(
            payload.get("lines")
            or payload.get("content")
        )
        result = assets_common._write_text_file(
            path,
            lines,
            overwrite=overwrite,
        )

    result["action"] = "create_asset_file"
    return result


def append_asset_file(payload: dict) -> dict:
    path = assets_common._asset_path(
        assets_common.ASSETS_ROOT,
        str(payload.get("path", "")),
        default_suffix=".txt",
    )

    if (
        "content" in payload
        and "lines" not in payload
    ):
        appended_content = assets_common._normalize_text_content(
            payload.get("content")
        )
        existing_content = (
            path.read_text(
                encoding="utf-8",
            )
            if path.exists()
            else ""
        )
        separator = (
            ""
            if (
                not existing_content
                or existing_content.endswith("\n")
                or not appended_content
            )
            else "\n"
        )
        merged_content = (
            existing_content
            + separator
            + appended_content
        )
        merged_content = assets_common._with_terminal_newline(
            merged_content
        )

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )
        path.write_text(
            merged_content,
            encoding="utf-8",
        )

        appended_lines = appended_content.splitlines()
        merged_lines = merged_content.splitlines()

        return {
            "ok": True,
            "action": "append_asset_file",
            "path": assets_common._relative(path),
            "appended_count": len(appended_lines),
            "line_count": len(merged_lines),
            "examples": merged_lines[:5],
        }

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
        "action": "append_asset_file",
        "path": assets_common._relative(path),
        "appended_count": len(lines),
        "line_count": len(merged_lines),
        "examples": merged_lines[:5],
    }
