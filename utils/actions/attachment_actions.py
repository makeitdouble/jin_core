import asyncio
import re

from contracts.rules_assembler import (
    RUNTIME_ACTION_LIST_FILES,
    RUNTIME_ACTION_ATTACH_FILE,
    RUNTIME_ACTION_DETACH_FILE,
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
    from utils.context.files import unload_project_files
    for removed in set(getattr(context, "runtime_attached_file_ids", []) or []) - set(normalized):
        unload_project_files(context, removed)
    if attachments is None:
        attachments = hydrate_attachment_ids(normalized)
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


def parse_project_file_target(payload, context):
    from utils.project_reader import FOLDER_SUFFIX, linked_projects

    text = str(payload or "").strip().replace("\\", "/")
    match = re.fullmatch(r"(.+?)(?:#L([0-9]+)(?:-L?([0-9]+))?)?", text)
    if not match:
        return None
    path, start, end = match.groups()
    projects = linked_projects(context)
    prefix, separator, relative = path.partition("/")
    record = get_file_record(_clean_id(prefix)) if separator else None
    # Only a known folder ID is a prefix; six-character directory names are paths.
    if record and record["name"].lower().endswith(FOLDER_SUFFIX):
        folder, path = record["id"], relative
    elif len(projects) == 1:
        folder = projects[0]["id"]
    elif projects:
        raise ValueError("Multiple folders attached; use folder_id/relative/path")
    else:
        raise ValueError("No folder attached; attach a folder link or use a persistent file ID")
    target = {"action": "project_read", "attachment": folder, "path": path}
    if start is not None:
        target["start"] = int(start)
    if end is not None:
        target["end"] = int(end)
    return target


async def attach_project_file(context, payload):
    """Shared loader for ATTACH_FILE and the old ASSET_ACTION project_read alias."""
    from utils.project_reader import run_project_action
    return await asyncio.to_thread(run_project_action, context, payload)


async def apply_attachment_actions(
    context, *, list_actions, attach_actions, detach_actions,
    ordered_actions=None, log_runtime=None, with_action_context=lambda payload: payload,
) -> list[dict]:
    from utils.context.files import loaded_file_ref, unload_project_files
    results = []
    active_ids = _active_ids(context)
    restricted_writes = persistent_writes_restricted(context)

    if list_actions:
        records = list_file_records()
        result = {"action": "list_files", "ok": True, "files": records,
                  "lines": format_list_files_lines(records)}
        record_runtime_tool_result(context, TOOL_RESULT_KIND_FILES, result)
        results.append(result)

    # Preserve marker order, including detach -> attach of another range.
    actions = ordered_actions if ordered_actions is not None else [*detach_actions, *attach_actions]
    for action in actions:
        detaching = action.name == RUNTIME_ACTION_DETACH_FILE
        name = "detach_file" if detaching else "attach_file"
        file_id = _clean_id(action.payload)
        record = get_file_record(file_id)
        result = {"action": name, "ok": False, "id": str(action.payload or "").strip()}
        target, target_error = None, ""
        try:
            # Persistent IDs retain priority; everything else is a project path.
            if record is None:
                target = parse_project_file_target(action.payload, context)
        except ValueError as error:
            target_error = str(error)
        if target_error:
            result.update(error="invalid_file_reference", detail=target_error)
        elif target:
            if detaching:
                from pathlib import PurePosixPath
                path = str(PurePosixPath(target["path"].replace("\\", "/")))
                ref = f"{target['attachment']}/{path}"
                unloaded = unload_project_files(context, ref)
                result.update(id=ref, name=path, ok=unloaded, unloaded=unloaded)
                if not unloaded:
                    result.update(error="file_not_loaded", detail="File is not loaded; nothing to unload")
            else:
                result = await attach_project_file(context, target)
                result.update(action=name, id=result.get("file_ref") or str(action.payload),
                              name=result.get("path") or target["path"], source="project")
        elif not file_id or record is None:
            result["error"] = "file_not_found"
        elif detaching:
            was_loaded = file_id in active_ids
            active_ids = [value for value in active_ids if value != file_id]
            unload_project_files(context, file_id)
            if not restricted_writes:
                set_file_pinned(file_id, False)
            apply_attachment_context_ids(context, active_ids)
            result.update(ok=True, id=file_id, name=record["name"], unloaded=was_loaded)
        else:
            existing = loaded_file_ref(context, reference=file_id, sha256=record.get("sha256", ""))
            if existing:
                result.update(id=file_id, name=record["name"], error="file_already_loaded",
                              detail=f"File already loaded: {existing}. Use DETACH_FILE before loading it again.")
            else:
                previous_ids = list(active_ids)
                if restricted_writes:
                    error = None
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
        record_runtime_tool_result(context, TOOL_RESULT_KIND_FILES, result)
        results.append(result)

    if actions:
        if log_runtime is not None:
            await log_runtime(f"[RUNTIME ACTION] attachments active: {len(active_ids)}/{MAX_ATTACHED_FILES}")
        await _emit_snapshot(context)

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)
    if emit is not None:
        for result in results:
            action_name = {
                "list_files": RUNTIME_ACTION_LIST_FILES,
                "attach_file": RUNTIME_ACTION_ATTACH_FILE,
                "detach_file": RUNTIME_ACTION_DETACH_FILE,
            }.get(result.get("action"), result.get("action", ""))
            display_name = get_runtime_action_display_name(
                action_name
            )
            attachment_name = str(
                result.get("name")
                or ""
            ).strip()
            text = (
                f"{display_name}: {attachment_name}"
                if (
                    attachment_name
                    and result.get("action") in {
                        "attach_file",
                        "detach_file",
                    }
                )
                else (
                    result.get("error")
                    or (
                        f"{len(result.get('files', []))} files"
                        if result.get("action") == "list_files"
                        else "attachment updated"
                    )
                )
            )
            from utils.context.files import format_file_result
            detail = format_file_result(result) if result.get("action") != "list_files" else "\n".join(result.get("lines", []))
            await emit(with_action_context({
                "type": "runtime_action",
                "action": result.get("action"),
                "id": result.get("id") or result.get("action"),
                "status": "completed" if result.get("ok") is not False else "failed",
                "display_name": display_name,
                "close_tag": runtime_action_has_close_tag(action_name),
                "text": str(text),
                "detail": detail,
                "attachment_result": result,
            }))

    return results
