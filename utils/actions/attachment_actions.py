import asyncio
import re

from utils import attached_files_store as files
from contracts.rules_assembler import (
    RUNTIME_ACTION_LIST_FILES,
    RUNTIME_ACTION_ATTACH_FILE_CONTENT,
    RUNTIME_ACTION_ATTACH_FILE_BY_ID,
    RUNTIME_ACTION_ATTACH_FILE_BY_PATH,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.attached_files_store import (
    MAX_ATTACHED_FILES,
    FILE_ID_RE,
    format_list_files_lines,
    get_file_record,
    get_pinned_file_ids,
    hydrate_attachment_ids,
    list_file_records,
    set_file_pinned,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_FILES,
    record_runtime_tool_result,
)
from runtime.anonymous_mode import persistent_writes_restricted


def _clean_id(value: str) -> str:
    file_id = str(value or "").strip().lower()
    return file_id if FILE_ID_RE.fullmatch(file_id) else ""


def _active_ids(context) -> list[str]:
    raw = getattr(context, "runtime_attached_file_ids", [])
    ids = []
    for value in raw if isinstance(raw, list) else []:
        file_id = _clean_id(value)
        if file_id and get_file_record(file_id) and file_id not in ids:
            ids.append(file_id)
        if len(ids) >= MAX_ATTACHED_FILES:
            break
    return ids


def apply_attachment_context_ids(context, ids: list[str], *, attachments=None) -> None:
    normalized = []
    for value in ids:
        file_id = _clean_id(value)
        if file_id and get_file_record(file_id) and file_id not in normalized:
            normalized.append(file_id)
        if len(normalized) >= MAX_ATTACHED_FILES:
            break
    from utils.context.files import (
        unload_persistent_file_results,
        unload_project_files,
    )
    for removed in set(getattr(context, "runtime_attached_file_ids", []) or []) - set(normalized):
        unload_project_files(context, removed)
        unload_persistent_file_results(context, removed)
    if attachments is None:
        attachments = hydrate_attachment_ids(normalized)
    path_attachments = [a for a in getattr(context, "runtime_current_sequence_attachments", []) or []
                        if a.get("path_attachment") and a.get("attachment") in normalized]
    attachments = list(attachments) + path_attachments
    context.runtime_attached_file_ids = normalized
    context.runtime_turn_attachments = attachments
    context.runtime_current_sequence_attachments = list(attachments)
    current_sequence_turn_id = str(
        getattr(context, "runtime_current_sequence_turn_id", "") or ""
    ).strip()
    if current_sequence_turn_id:
        context.runtime_current_sequence_attachments_turn_id = current_sequence_turn_id


async def _emit_snapshot(context) -> None:
    from utils.attached_files_store import public_file_snapshot

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)
    if emit is not None:
        snapshot = public_file_snapshot()
        if persistent_writes_restricted(context):
            snapshot["pinned_ids"] = _active_ids(context)
        await emit({
            "type": "attached_files_update",
            **snapshot,
        })


def parse_project_file_target(payload, context, *, require_linked=False):
    from utils.project_reader import (
        DEFAULT_PROJECT_SELECTOR,
        FOLDER_SUFFIX,
        default_project_name,
        linked_projects,
    )

    text = str(payload or "").strip().replace("\\", "/")
    match = re.fullmatch(r"(.+?)(?:#L([0-9]+)(?:-L?([0-9]+))?)?", text)
    if not match:
        return None
    path, start, end = match.groups()
    # Normalize only explicit current-directory prefixes. ``../`` remains
    # untouched and is rejected later by the project path guard.
    while path.startswith("./"):
        path = path[2:]
    projects = linked_projects(context, include_pending_restore=not require_linked)
    if require_linked and not projects:
        raise ValueError("No folder attached")
    prefix, separator, relative = path.partition("/")
    record = get_file_record(_clean_id(prefix)) if separator else None
    # Canonical model-facing prefix is the visible folder name. Folder IDs are
    # still accepted for old sessions/outputs, but are not advertised as roots.
    named = [
        project for project in projects
        if separator and prefix == files.file_display_name(project["name"])
    ]
    if record and record["name"].lower().endswith(FOLDER_SUFFIX):
        folder, path = record["id"], relative
    elif len(named) == 1:
        folder, path = named[0]["id"], relative
    elif len(named) > 1:
        raise ValueError("Folder name is ambiguous; use the ASSET_ACTION attachment id for this exceptional case")
    elif len(projects) == 1:
        folder = projects[0]["id"]
    elif projects:
        raise ValueError("Multiple folders attached; prefix the path with the visible folder name, e.g. project_name/relative/path")
    else:
        # No UI-linked folder: resolve against JIN's built-in source root without
        # creating/pinning a fake attachment or enabling Project Mode.
        default_name = default_project_name()
        if separator and prefix.casefold() in {default_name.casefold(), "jin_core"}:
            path = relative
        folder = DEFAULT_PROJECT_SELECTOR
    if require_linked and (folder not in {project["id"] for project in projects} or start is not None):
        raise ValueError("Use a whole-file path in a currently attached folder")
    target = {"action": "project_read", "attachment": folder, "path": path}
    if start is not None:
        target["start"] = int(start)
    if end is not None:
        target["end"] = int(end)
    return target


async def attach_project_file_content(context, payload, *, next_unread_window=False):
    """Shared loader for ATTACH_FILE_CONTENT and the old ASSET_ACTION project_read alias."""
    from utils.project_reader import run_project_action

    project_payload = dict(payload or {})
    if (
        next_unread_window
        and "start" not in project_payload
        and "end" not in project_payload
    ):
        # Internal-only behavior for bare ATTACH_FILE_CONTENT. Explicit #L... reads
        # retain exact range identity, while legacy ASSET_ACTION project_read
        # keeps its old default-to-L1 behavior.
        project_payload["_next_unread_window"] = True

    return await asyncio.to_thread(
        run_project_action,
        context,
        project_payload,
    )


MAX_PATH_IMAGE_BYTES = 20 * 1024 * 1024
MAX_PATH_SET_BYTES = 40 * 1024 * 1024


def load_project_attachment(context, payload):
    """Resolve a user-authorized whole file; never import it into assets/files."""
    import hashlib
    import mimetypes
    from utils.project_reader import _root_for, _inside, MAX_FILE_BYTES
    from websocket.attachments import TEXT_ATTACHMENT_CONTEXT_MAX_CHARS

    target = parse_project_file_target(payload, context, require_linked=True)
    if not target:
        raise ValueError("Empty project path")
    if ":" in target["path"]:
        raise ValueError("Use a relative file path without drive or stream syntax")
    root, record = _root_for(context, target["attachment"])
    path = _inside(root, target["path"])
    if not path.is_file():
        raise ValueError("Path is not a regular file")
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    kind = files._kind_for(path.name, mime)
    if kind not in {"text", "image"} or path.suffix.lower() == ".jin-folder":
        raise ValueError("Unsupported file type; use UTF-8 text or PNG/JPEG/GIF/WebP images")
    limit = MAX_PATH_IMAGE_BYTES if kind == "image" else MAX_FILE_BYTES
    with path.open("rb") as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"File exceeds the {limit} byte attachment limit")
    if kind == "image":
        if data.startswith(b"\x89PNG\r\n\x1a\n"):
            mime = "image/png"
        elif data.startswith(b"\xff\xd8\xff"):
            mime = "image/jpeg"
        elif data[:6] in (b"GIF87a", b"GIF89a"):
            mime = "image/gif"
        elif data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            mime = "image/webp"
        else:
            raise ValueError("Unsupported image data; use PNG/JPEG/GIF/WebP")
    elif b"\x00" in data:
        raise ValueError("Binary file; UTF-8 text required")
    relative = path.relative_to(root).as_posix()
    display = f"{files.file_display_name(record['name'])}/{relative}"
    metadata = dict(source="project", path_attachment=True, attachment=record["id"],
                    path=relative, file_ref=f"{record['id']}/{relative}", display_ref=display,
                    context_path=display, name=path.name, kind=kind, type=mime,
                    size_bytes=len(data), sha256=hashlib.sha256(data).hexdigest())
    attachment = files.hydrate_file_bytes(metadata, data, strict_text=True)
    if kind == "text" and len(attachment["text_content"]) > TEXT_ATTACHMENT_CONTEXT_MAX_CHARS:
        raise ValueError(f"Text exceeds the {TEXT_ATTACHMENT_CONTEXT_MAX_CHARS} character whole-file limit")
    return attachment


def clear_path_attachments(context):
    """Release sequence bytes and mark the retained history as unloaded."""
    for attr in ("runtime_turn_attachments", "runtime_current_sequence_attachments"):
        setattr(context, attr, [a for a in getattr(context, attr, []) or [] if not a.get("path_attachment")])
    context.runtime_path_attachment_group = ()
    for entry in getattr(context, "runtime_tool_results", []) or []:
        result = entry.get("result", {})
        if isinstance(result, dict) and result.get("action") == "attach_file_by_path":
            result["loaded"] = False
            result.pop("content", None)


def prune_path_attachments(context):
    """No stale pixels after detach, deletion, Stop, or a new sequence."""
    from utils.project_reader import linked_projects, _root_for, _inside
    active = {p["id"] for p in linked_projects(context)}
    valid = set()
    for item in getattr(context, "runtime_current_sequence_attachments", []) or []:
        if not item.get("path_attachment"):
            continue
        try:
            if getattr(context, "runtime_turn_abort_requested", False) or item["attachment"] not in active:
                continue
            root, _ = _root_for(context, item["attachment"])
            if _inside(root, item["path"]).is_file():
                valid.add(item["file_ref"])
        except (OSError, ValueError, RuntimeError):
            pass
    for attr in ("runtime_turn_attachments", "runtime_current_sequence_attachments"):
        setattr(context, attr, [a for a in getattr(context, attr, []) or []
                               if not a.get("path_attachment") or a.get("file_ref") in valid])
    for entry in getattr(context, "runtime_tool_results", []) or []:
        result = entry.get("result", {})
        if isinstance(result, dict) and result.get("action") == "attach_file_by_path" and result.get("file_ref") not in valid:
            result["loaded"] = False


async def attach_project_path(context, action, group):
    from urllib.parse import urlencode
    payload = str(action.payload or "").strip()
    result = dict(action="attach_file_by_path", source="project", name=payload,
                  display_ref=payload, ok=False, loaded=False)
    if group != getattr(context, "runtime_path_attachment_group", ()):
        clear_path_attachments(context)
        context.runtime_path_attachment_group = group
    try:
        attachment = await asyncio.to_thread(load_project_attachment, context, payload)
        # Recheck user selection after the off-thread read before publishing bytes.
        from utils.project_reader import linked_projects
        if attachment["attachment"] not in {p["id"] for p in linked_projects(context)}:
            raise ValueError("Folder was detached")
        if getattr(context, "runtime_turn_abort_requested", False):
            raise ValueError("Turn was stopped")
        current = list(getattr(context, "runtime_current_sequence_attachments", []) or [])
        current = [a for a in current if a.get("file_ref") != attachment["file_ref"]]
        path_set = [a for a in current if a.get("path_attachment")]
        if len(path_set) >= MAX_ATTACHED_FILES or sum(a.get("size_bytes", 0) for a in path_set) + attachment["size_bytes"] > MAX_PATH_SET_BYTES:
            raise ValueError("Temporary attachment set limit exceeded")
        from websocket.attachments import TEXT_ATTACHMENT_CONTEXT_MAX_CHARS
        if sum(len(a.get("text_content", "")) for a in path_set) + len(attachment.get("text_content", "")) > TEXT_ATTACHMENT_CONTEXT_MAX_CHARS:
            raise ValueError("Temporary text attachment set limit exceeded")
        current.append(attachment)
        context.runtime_turn_attachments = list(current)
        context.runtime_current_sequence_attachments = current
        context.runtime_current_sequence_attachments_turn_id = getattr(context, "runtime_current_sequence_turn_id", "")
        result.update({k: v for k, v in attachment.items() if k not in {"data_url", "text_content"}})
        result.update(ok=True, loaded=True)
        result["preview_url"] = "/api/project-attachment/preview?" + urlencode({
            "session_id": getattr(context, "session_id", ""), "attachment": attachment["attachment"],
            "path": attachment["path"], "sha256": attachment["sha256"],
        })
    except (OSError, ValueError, RuntimeError) as error:
        detail = str(error) if isinstance(error, ValueError) else "File cannot be read"
        missing = "Path not found" in detail or isinstance(error, FileNotFoundError)
        result.update(error="file_not_found" if missing else "invalid_file_reference",
                      detail="file not exists" if missing else detail)
    return result


def parse_asset_attachment_calls(payload):
    """Adapt the two explicit asset operations into the existing file loader."""
    from .common_action_utils import RuntimeActionCall

    name = str(payload.get("action", "")).strip().upper()
    by_id = name == RUNTIME_ACTION_ATTACH_FILE_BY_ID
    singular, plural = ("id", "ids") if by_id else ("path", "paths")
    values = payload.get(plural) if plural in payload else [payload.get(singular)]
    if (not isinstance(values, list) or not values
            or any(not isinstance(value, str) or not value.strip() for value in values)):
        raise ValueError(f"Supply {singular} as a string or {plural} as a non-empty list of strings")
    if len(values) > MAX_ATTACHED_FILES:
        raise ValueError(f"At most {MAX_ATTACHED_FILES} files per attachment action")
    values = list(dict.fromkeys(value.strip() for value in values))
    selector = payload.get("attachment", "")
    if selector and (by_id or not isinstance(selector, str)):
        raise ValueError("attachment is a folder selector for ATTACH_FILE_BY_PATH only")
    if selector:
        selector = selector.strip()
        values = [value if value.replace("\\", "/").startswith(selector + "/")
                  else selector + "/" + value for value in values]
    group = ", ".join(values)
    return tuple(RuntimeActionCall(name=name, payload=value, marker_group="asset_attachment",
                                   marker_payload=group) for value in values)


async def apply_attachment_actions(
    context, *, list_actions, attach_actions,
    log_runtime=None, with_action_context=lambda payload: payload, runtime_message_id="", action_display_ids=None,
    owner_action_id="",
) -> list[dict]:
    results = []
    active_ids = _active_ids(context)
    restricted_writes = persistent_writes_restricted(context)

    def record_attachment_result(result):
        result["runtime_action_name"] = "ASSET_ACTION" if owner_action_id else action.name
        record_runtime_tool_result(context, TOOL_RESULT_KIND_FILES, result,
                                   result_id=owner_action_id)

    if list_actions:
        records = list_file_records()
        result = {"action": "list_files", "ok": True, "files": records,
                  "lines": format_list_files_lines(records)}
        file_count = len(records)
        result["result_count"] = file_count

        # LIST_FILES has no marker payload, so persist its actual outcome on the
        # runtime event. Session/current-request history uses this to show the
        # same compact result that the bubble and logger receive.
        runtime_events = getattr(context, "runtime_action_events", None)
        if isinstance(runtime_events, list):
            for event in reversed(runtime_events):
                if (
                    isinstance(event, dict)
                    and str(event.get("name") or "").strip().lower() == "list_files"
                    and str(event.get("status") or "").strip().lower()
                    not in {"completed", "failed"}
                ):
                    event.update(
                        status="completed",
                        result_count=file_count,
                        text=f"{RUNTIME_ACTION_LIST_FILES}: {file_count} files",
                    )
                    break

        record_runtime_tool_result(context, TOOL_RESULT_KIND_FILES, result)
        results.append(result)

    for action in attach_actions:
        image_path = (
            action.name == RUNTIME_ACTION_ATTACH_FILE_CONTENT
            and not get_file_record(_clean_id(action.payload))
            and str(action.payload).casefold().endswith((".png", ".jpg", ".jpeg", ".gif", ".webp"))
        )
        if action.name == RUNTIME_ACTION_ATTACH_FILE_BY_PATH or image_path:
            group = (runtime_message_id, getattr(action, "marker_group", ""), getattr(action, "marker_payload", "") or action.payload)
            display_id = (action_display_ids or {}).get(id(action)) or f"attach_path_{len(getattr(context, 'runtime_action_events', []) or []):06d}"
            emit = getattr(getattr(context, "emitter", None), "emit", None)
            if emit is not None:
                await emit(with_action_context({"type": "runtime_action", "action": "attach_file_by_path",
                                                "id": display_id, "status": "running", "text": action.name,
                                                "payload": action.payload}))
            result = await attach_project_path(context, action, group)
            result["runtime_action_id"] = display_id
            record_attachment_result(result)
            results.append(result)
            continue
        by_id = action.name == RUNTIME_ACTION_ATTACH_FILE_BY_ID
        name = "attach_file_by_id" if by_id else "attach_file_content"
        file_id = _clean_id(action.payload)
        record = get_file_record(file_id)
        result = {"action": name, "ok": False, "id": str(action.payload or "").strip()}
        target, target_error = None, ""
        try:
            # Persistent IDs retain priority; everything else is a project path.
            if record is None and not by_id:
                target = parse_project_file_target(action.payload, context)
        except ValueError as error:
            target_error = str(error)

        if target_error:
            result.update(error="invalid_file_reference", detail=target_error)
        elif target:
            result = await attach_project_file_content(
                context,
                target,
                next_unread_window=(
                    "start" not in target
                    and "end" not in target
                ),
            )
            result.update(
                action=name,
                id=result.get("file_ref") or str(action.payload),
                name=result.get("display_ref") or result.get("path") or target["path"],
                source="project",
            )
        elif not file_id or record is None:
            result["error"] = "file_not_found"
            if by_id:
                result["detail"] = "file not exists"
        else:
            previous_ids = list(active_ids)
            if restricted_writes:
                error = None
                active_ids = [
                    value for value in active_ids if value != file_id
                ]
                active_ids = [*active_ids, file_id][-MAX_ATTACHED_FILES:]
            else:
                _, error = set_file_pinned(file_id, True)
                active_ids = get_pinned_file_ids()

            if error:
                result["error"] = error
            else:
                apply_attachment_context_ids(context, active_ids)
                result.update(ok=True, id=file_id, name=record["name"], loaded=True)
                replaced = [value for value in previous_ids if value not in active_ids]
                if replaced:
                    result["replaced_id"] = replaced[0]

        record_attachment_result(result)
        results.append(result)

    if attach_actions:
        if log_runtime is not None:
            await log_runtime(f"[RUNTIME ACTION] attachments active: {len(active_ids)}/{MAX_ATTACHED_FILES}")
        await _emit_snapshot(context)

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)
    if emit is not None:
        for result in results:
            action_name = {
                "list_files": RUNTIME_ACTION_LIST_FILES,
                "attach_file_content": RUNTIME_ACTION_ATTACH_FILE_CONTENT,
                "attach_file_by_id": RUNTIME_ACTION_ATTACH_FILE_BY_ID,
                "attach_file_by_path": RUNTIME_ACTION_ATTACH_FILE_BY_PATH,
            }.get(result.get("action"), result.get("action", ""))
            display_name = get_runtime_action_display_name(action_name)
            from utils.context.files import format_file_result, file_result_summary
            text = (
                file_result_summary(result)
                if result.get("action") != "list_files"
                else f"{display_name}: {len(result.get('files', []))} files"
            )
            detail = (
                format_file_result(result)
                if result.get("action") != "list_files"
                else "\n".join(result.get("lines", []))
            )
            await emit(with_action_context({
                "type": "runtime_action",
                "action": result.get("action"),
                "id": result.get("runtime_action_id") or result.get("id") or result.get("action"),
                "status": "completed" if result.get("ok") is not False else "failed",
                "display_name": display_name,
                "close_tag": runtime_action_has_close_tag(action_name),
                "text": str(text),
                "detail": detail,
                "attachment_result": result,
            }))

    return results
