"""Bounded, read-only access to a user-linked local project."""
from __future__ import annotations

import json
import hashlib
import os
import re
from pathlib import Path, PureWindowsPath
from time import monotonic
from urllib.parse import unquote, urlsplit

from utils import attached_files_store as files

FOLDER_SUFFIX = ".jin-folder"
PROJECT_ACTIONS = {"project_tree", "project_search", "project_read"}
SKIP_DIRS = {".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv", "dist", "build"}
MAX_FILE_BYTES = 1024 * 1024
MAX_OUTPUT_CHARS = 24000
MAX_SCAN_ENTRIES = 10000
MAX_SCAN_BYTES = 32 * 1024 * 1024
MAX_SCAN_SECONDS = 3

# Read-only source root available even when the user has not linked a project.
# This is deliberately NOT an attached-files record: only a real UI folder link
# activates PROJECT_REVIEW / Project Mode.
DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROJECT_SELECTOR = "jin_core"


def default_project_name(root: Path | None = None) -> str:
    root = root or DEFAULT_PROJECT_ROOT
    return str(root.name or "jin_core")


def _default_project_record(root: Path) -> dict:
    name = default_project_name(root)
    return {
        "id": DEFAULT_PROJECT_SELECTOR,
        "name": name + FOLDER_SUFFIX,
        "display_name": name,
        "implicit_project": True,
    }


def link_project_folder(value: str) -> tuple[dict, bool, str | None]:
    """Only the user-facing endpoint creates links; model actions cannot."""
    value = str(value or "").strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        value = value[1:-1]
    if value.lower().startswith("file:"):
        url = urlsplit(value)
        if url.netloc not in {"", "localhost"} or url.query or url.fragment:
            raise ValueError("Use a local folder path or file:/// URL")
        value = unquote(url.path)
        if os.name == "nt" and re.match(r"^/[a-zA-Z]:/", value):
            value = value[1:]
    elif "://" in value:
        raise ValueError("Use a local folder path or file:/// URL; remote repositories are not supported")
    if not value:
        raise ValueError("Folder path is empty")
    root = Path(value).expanduser().resolve(strict=True)
    if not root.is_dir():
        raise ValueError("The selected path is not a folder")
    return files.store_uploaded_file(
        name=(root.name or "project") + FOLDER_SUFFIX,
        content=json.dumps({"path": str(root)}, ensure_ascii=False).encode("utf-8"),
        mime_type="text/plain",
        pin=True,
    )


def linked_projects(context, *, include_pending_restore: bool = False) -> list[dict]:
    records = []
    file_ids = list(getattr(context, "runtime_attached_file_ids", []) or [])

    # During the hidden archived-session restore tick the prompt intentionally
    # receives only resource metadata and the live attachment list is empty
    # until synthetic ATTACH_FILE_CONTENT replay runs after the first answer. Runtime
    # actions emitted by that first answer still need to resolve paths against
    # the staged project root, otherwise ATTACH_FILE_CONTENT/ASSET_ACTION can fail with
    # a false "No folder attached" even though the restored user turn visibly
    # carries the folder. Keep this opt-in so prompt/project-review builders do
    # not treat staged resources as already live.
    if (
        include_pending_restore
        and getattr(context, "runtime_session_restore_priming", False)
    ):
        file_ids.extend(
            getattr(
                context,
                "runtime_session_restore_pending_attached_file_ids",
                [],
            )
            or []
        )

    seen = set()
    for file_id in file_ids:
        file_id = str(file_id or "").strip().casefold()
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        record = files.get_file_record(file_id)
        if record and record["name"].lower().endswith(FOLDER_SUFFIX):
            records.append(record)
    return records


def project_review_active(context) -> bool:
    return bool(context is not None and linked_projects(context))


def _root_for(context, attachment: str) -> tuple[Path, dict]:
    projects = linked_projects(context, include_pending_restore=True)

    # No linked folder: expose JIN's own source tree as an implicit read-only
    # project. This must stay separate from linked_projects(), otherwise merely
    # using a file action would silently activate Project Mode and its prompt/UI
    # behavior. As soon as the user links a real folder, this fallback disappears
    # and the existing linked-project selection rules take over unchanged.
    if not projects:
        root = DEFAULT_PROJECT_ROOT.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("Default JIN source folder is unavailable")
        name = default_project_name(root)
        selector = str(attachment or "").strip()
        allowed = {"", DEFAULT_PROJECT_SELECTOR.casefold(), name.casefold(), "jin_core"}
        if selector.casefold() not in allowed:
            raise ValueError(
                f"No project folder is attached; omit attachment or use {name} for JIN's default source root"
            )
        return root, _default_project_record(root)

    matches = [
        record for record in projects
        if attachment in {
            record["id"],
            record["name"],
            files.file_display_name(record["name"]),
        }
    ]
    if not attachment and len(projects) == 1:
        matches = projects
    if len(matches) != 1:
        raise ValueError("Select an attached project by its folder name or ASSET_ACTION attachment id")
    record = matches[0]
    descriptor = files.FILES_DIR / record["stored_name"]
    if descriptor.stat().st_size > 8192:
        raise ValueError("Folder descriptor is too large")
    data = json.loads(descriptor.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("path"), str):
        raise ValueError("Invalid folder descriptor")
    root = Path(data["path"])
    if not root.is_absolute():
        raise ValueError("Folder descriptor must contain an absolute path")
    root = root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Linked folder is unavailable")
    return root, record


def project_display_path(project_name: str, relative: str = ".", *, is_dir: bool = False) -> str:
    """Model-facing project path rooted at the visible attached-folder name."""
    root = str(project_name or "project").strip().rstrip("/") or "project"
    value = str(relative or ".").strip().replace("\\", "/")
    value = value.strip("/")
    if value in {"", "."}:
        rendered = root
    else:
        rendered = f"{root}/{value}"
    return rendered + "/" if is_dir and not rendered.endswith("/") else rendered


def _strip_project_display_root(relative: str, project_name: str, *root_aliases: str) -> str:
    """Accept folder-rooted paths and legacy plain relative paths as the same target."""
    value = str(relative or ".").strip().replace("\\", "/")
    # ``./jin_core/src`` is still a relative project path. Strip only explicit
    # current-directory prefixes; absolute/drive paths remain untouched and are
    # rejected by _inside below.
    while value.startswith("./"):
        value = value[2:]

    roots = []
    for candidate in (project_name, *root_aliases):
        root = str(candidate or "").strip().strip("/")
        if root and root not in roots:
            roots.append(root)

    for root in roots:
        if value.rstrip("/") == root:
            return "."
        prefix = root + "/"
        if value.startswith(prefix):
            return value[len(prefix):] or "."
    return value or "."


def _same_name_project_paths(root: Path, relative: str, *, limit: int = 3) -> list[str]:
    """Return bounded same-basename hints for a missing project path."""
    requested_name = Path(str(relative or "").replace("\\", "/")).name.casefold()
    if not requested_name:
        return []

    state = {
        "visited": 0,
        "skipped": 0,
        "limited": False,
        "deadline": monotonic() + min(MAX_SCAN_SECONDS, 0.2),
        "stop_reason": "",
    }
    matches = []
    for path, is_dir in _walk(root, root, 20, state):
        if is_dir or path.name.casefold() != requested_name:
            continue
        matches.append(path.relative_to(root).as_posix())
        if len(matches) >= limit:
            break
    return matches


def _inside(root: Path, relative: str) -> Path:
    relative = str(relative or ".").replace("\\", "/")
    if Path(relative).is_absolute() or PureWindowsPath(relative).drive or ".." in Path(relative).parts:
        raise ValueError("Use a relative path inside the linked folder")
    try:
        path = (root / relative).resolve(strict=True)
    except (FileNotFoundError, NotADirectoryError):
        # Keep host absolute paths out of model-facing errors. A missing file
        # should not look like an "absolute path" schema failure. If the model
        # guessed a stale directory but the basename exists elsewhere, include
        # a bounded exact-name hint so the follow-up can recover without any
        # unsafe fuzzy auto-attach.
        hints = _same_name_project_paths(root, relative)
        hint_text = (
            f" Same-name file found at: {', '.join(hints)}"
            if hints
            else ""
        )
        raise ValueError(
            f"Path not found inside linked folder: {relative}.{hint_text}"
        ) from None
    if not path.is_relative_to(root):
        raise ValueError("Path leaves the linked folder")
    return path


def _integer(payload, key, default, low, high):
    value = payload.get(key, default)
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
        raise ValueError(f"{key} must be an integer from {low} to {high}")
    value = int(value)
    if not low <= value <= high:
        raise ValueError(f"{key} must be from {low} to {high}")
    return value


def _text(path: Path, *, with_digest=False):
    if not path.is_file():
        raise ValueError("Path is not a regular file")
    with path.open("rb") as handle:
        data = handle.read(MAX_FILE_BYTES + 1)
    if len(data) > MAX_FILE_BYTES:
        raise ValueError("File exceeds the 1 MiB text limit")
    if b"\x00" in data:
        raise ValueError("Binary file; text reader only")
    try:
        text = data.decode("utf-8-sig")
        return (text, hashlib.sha256(data).hexdigest()) if with_digest else text
    except UnicodeDecodeError as error:
        raise ValueError("File is not UTF-8 text") from error


def _walk(root, start, depth, state):
    """No link traversal, stable pagination, bounded traversal even for huge folders."""
    def visit(directory, level):
        with os.scandir(directory) as entries:
            children = []
            for entry in entries:
                state["visited"] += 1
                if state["visited"] > MAX_SCAN_ENTRIES or monotonic() > state["deadline"]:
                    state["limited"] = True
                    state["stop_reason"] = (f"entry limit ({MAX_SCAN_ENTRIES})"
                                            if state["visited"] > MAX_SCAN_ENTRIES
                                            else f"time limit ({MAX_SCAN_SECONDS} seconds)")
                    break
                children.append(Path(entry.path))
        for path in sorted(children, key=lambda item: (item.name.casefold(), item.name)):
            if monotonic() > state["deadline"]:
                state["limited"] = True
                state["stop_reason"] = f"time limit ({MAX_SCAN_SECONDS} seconds)"
                return
            if path.is_symlink():
                state["skipped"] += 1
                continue
            try:
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    state["skipped"] += 1
                    continue
                is_dir = path.is_dir()
                if is_dir and path.name in SKIP_DIRS:
                    state["skipped"] += 1
                    continue
                yield path, is_dir
                if is_dir and level < depth and not state["limited"]:
                    yield from visit(path, level + 1)
            except OSError:
                state["skipped"] += 1
    yield from visit(start, 1)


def run_project_action(context, payload: dict) -> dict:
    action = str(payload.get("action", ""))
    attachment = str(payload.get("attachment", "") or "")
    relative = str(payload.get("path", ".") or ".")
    result = {"action": action, "attachment": attachment, "path": relative}
    try:
        if action not in PROJECT_ACTIONS:
            raise ValueError("Unknown project action")
        root, record = _root_for(context, attachment)
        result["attachment"] = record["id"]
        result["project_name"] = files.file_display_name(record["name"])
        if record.get("implicit_project"):
            result["implicit_project"] = True
        relative = _strip_project_display_root(
            relative,
            result["project_name"],
            root.name,
        )
        path = _inside(root, relative)
        relative = path.relative_to(root).as_posix()
        result["path"] = relative
        if action == "project_read":
            result["file_ref"] = f"{record['id']}/{relative}"
            result["display_ref"] = project_display_path(result["project_name"], relative)
            result["source"] = "project"

            implicit_next_window = bool(
                payload.get("_next_unread_window")
                and "start" not in payload
                and "end" not in payload
            )
            if implicit_next_window:
                from utils.context.files import next_project_file_unread_start
                start = next_project_file_unread_start(
                    context,
                    result["file_ref"],
                )
                end = start + 199
            else:
                start = _integer(payload, "start", 1, 1, 10000000)
                end = _integer(payload, "end", start + 199, start, start + 399)

            # Keep the requested window as stable identity metadata. Explicit
            # ranges may be read again; the newest result owns the visible
            # FILE_CONTENT block for that window.
            result["requested_start"] = start
            result["requested_end"] = end
            source, result["source_sha256"] = _text(path, with_digest=True)
            lines = source.splitlines()
            if start > len(lines) and (lines or start != 1):
                raise ValueError(f"Start line exceeds file length: {len(lines)}")
            selected, used = [], 0
            for number in range(start, min(end, len(lines)) + 1):
                line = f"{number}: {lines[number - 1]}"
                if used + len(line) + 1 > MAX_OUTPUT_CHARS:
                    break
                selected.append(line)
                used += len(line) + 1
            last = start + len(selected) - 1
            result["range"] = f"{start}-{last} of {len(lines)} lines" if selected else f"No lines read; file has {len(lines)} lines"
            if selected:
                result["loaded_start"] = start
                result["loaded_end"] = last
            if lines and not selected:
                raise ValueError("Line exceeds the 24000 character limit; no content loaded")
            result["content"] = "\n".join(selected)
            result["loaded"] = True
            if last < min(end, len(lines)):
                result["notice"] = f"Output limit; next unread line: {last + 1}. A single line over 24000 characters cannot be displayed."
            elif last < len(lines):
                result["notice"] = f"Next unread line: {max(start, last + 1)}"
        else:
            if not path.is_dir():
                raise ValueError("Tree/search path must be a directory")
            offset = _integer(payload, "offset", 0, 0, 1000000)
            limit = _integer(payload, "limit", 100, 1, 200)
            depth = _integer(payload, "depth", 1, 1, 20) if action == "project_tree" else 100
            query = payload.get("query", "")
            if action == "project_search" and (not isinstance(query, str) or not query or len(query) > 500):
                raise ValueError("query must be nonempty literal text, up to 500 characters")
            state = {"visited": 0, "skipped": 0, "limited": False, "deadline": monotonic() + MAX_SCAN_SECONDS}
            found, output, used, scanned_bytes, more = 0, [], 0, 0, False
            for item, is_dir in _walk(root, path, depth, state):
                name = item.relative_to(root).as_posix()
                display_name = project_display_path(result["project_name"], name, is_dir=is_dir)
                if action == "project_tree":
                    matches = [display_name]
                elif is_dir:
                    continue
                else:
                    try:
                        # Count attempted bytes, including skipped large files.
                        scanned_bytes += min(item.stat().st_size, MAX_FILE_BYTES + 1)
                        if scanned_bytes > MAX_SCAN_BYTES:
                            state["limited"] = True
                            state["stop_reason"] = f"file byte budget ({MAX_SCAN_BYTES} bytes)"
                            break
                        text = _text(_inside(root, name))
                    except (OSError, ValueError):
                        state["skipped"] += 1
                        continue
                    display_name = project_display_path(result["project_name"], name)
                    matches = (f"{display_name}:{number}: {line}" for number, line in enumerate(text.splitlines(), 1) if query.casefold() in line.casefold())
                for line in matches:
                    found += 1
                    if found <= offset:
                        continue
                    if len(output) >= limit or used + len(line) + 1 > MAX_OUTPUT_CHARS:
                        more = True
                        break
                    output.append(line)
                    used += len(line) + 1
                if more:
                    break
            result["content"] = "\n".join(output) or "No entries in this page."
            unit = "matching lines" if action == "project_search" else "file/folder paths"
            result["page"] = f"offset {offset}; returned {len(output)} {unit} (limit {limit})"
            if action == "project_search":
                result["query"] = query
            else:
                result["depth"] = depth
            notices = []
            if more and output:
                notices.append(f"More results: repeat the same action with offset {offset + len(output)}; keep attachment, path, query/depth unchanged.")
            elif more:
                notices.append("Entry exceeds output limit; narrow the path/query. No entry was returned.")
            if state["limited"]:
                notices.append(f"Scan stopped: {state['stop_reason']}; coverage is incomplete. Search/list smaller subfolders with offset 0; increasing offset does not resume the scan.")
            if state["skipped"]:
                notices.append(f"Skipped files/folders: {state['skipped']} (excluded folders, links, unsupported files or read errors; not a count of matches).")
            if not more and not state["limited"]:
                notices.insert(0, "No more results within this path, depth and file filters.")
            if not output:
                result["content"] = ("No results returned on this page; this does not prove the project has no matches."
                                     if more or state["limited"] or offset else
                                     "No matching lines in the searched files." if action == "project_search" else
                                     "No file/folder paths within the requested depth.")
            if notices:
                result["notice"] = " ".join(notices)
        return {"ok": True, **result}
    except (OSError, ValueError, RuntimeError) as error:
        return {"ok": False, **result, "error": "project_read_failed", "detail": str(error), "payload": payload}


def format_project_result(result: dict, *, include_content=False) -> str:
    """Compact action text; callers may nest the source body beside it."""
    from utils.context.files import (
        format_file_content,
        project_file_action_label,
        project_file_content_label,
        project_file_ref,
    )
    action = str(result.get("action") or "project_read")
    ref = project_file_ref(result)
    project_name = result.get("project_name")
    if not project_name:
        record = files.get_file_record(result.get("attachment", ""))
        project_name = files.file_display_name(record["name"]) if record else ""
    display_ref = str(result.get("display_ref") or (project_display_path(project_name, result.get("path", ".")) if project_name else ref))
    lines = [f"Action: {action}"]
    if ref:
        lines.append(f"File: {project_file_action_label(result) or display_ref}")
        if project_name:
            lines.append(f"Folder root: {project_name}/")
    else:
        if project_name:
            lines.append(f"Project root: {project_name}/")
            lines.append(f"ASSET_ACTION attachment: {project_name} (project selector; file paths still start with {project_name}/)")
            lines.append(f"Path: {project_display_path(project_name, result.get('path', '.'), is_dir=True)}")
        else:
            lines.append(f"Project: {result.get('attachment', '')}; path: {result.get('path', '.')}")
    failed = result.get("ok") is False
    if failed:
        lines.append("Status: failed")
    elif result.get("loaded") is False:
        lines.append("Status: unloaded")
    for key, label in (("query", "Query (literal text, case-insensitive)"), ("depth", "Directory depth"), ("range", "File lines"), ("page", "Page"), ("detail", "Reason")):
        if result.get(key) is not None:
            lines.append(f"{label}: {result[key]}")
    # Old saved results may carry the former boilerplate. Keep only actionable limits.
    notice = str(result.get("notice") or "")
    if notice and notice != "End of file":
        notice = notice.replace("Skipped generated folders and symlinks; search reads UTF-8 text files up to 1 MiB.", "")
        notice = notice.replace("End of this scan (within selected depth and exclusions).", "")
        notice = notice.replace("Skipped/unreadable entries: 0.", "").strip()
        if notice:
            lines.append(f"Notes: {notice}")
    if failed:
        from contracts.rules_assembler import get_runtime_action_schema
        name = "ATTACH_FILE_CONTENT" if ref else "ASSET_ACTION"
        lines.extend(["Correct action schema:", *get_runtime_action_schema(name)])
    elif "content" in result:
        if ref:
            if include_content:
                lines.append(format_file_content(project_file_content_label(result), result["content"]))
        else:
            if action == "project_search":
                lines.append("Matching lines (folder-rooted path:line number: source text):")
            elif action == "project_tree":
                lines.append("Paths rooted at the attached folder name (trailing / means folder):")
            lines.append(result["content"])
    return "\n".join(lines)
