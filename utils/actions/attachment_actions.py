import asyncio
import re

from utils import attached_files_store as files
from contracts.rules_assembler import (
    RUNTIME_ACTION_LIST_FILES,
    RUNTIME_ACTION_ATTACH_FILE_CONTENT,
    RUNTIME_ACTION_ATTACH_FILE_BY_ID,
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
    projects = linked_projects(context, include_pending_restore=True)
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


async def apply_attachment_actions(
    context, *, list_actions, attach_actions,
    log_runtime=None, with_action_context=lambda payload: payload,
) -> list[dict]:
    results = []
    active_ids = _active_ids(context)
    restricted_writes = persistent_writes_restricted(context)

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

        record_runtime_tool_result(context, TOOL_RESULT_KIND_FILES, result)
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
                "id": result.get("id") or result.get("action"),
                "status": "completed" if result.get("ok") is not False else "failed",
                "display_name": display_name,
                "close_tag": runtime_action_has_close_tag(action_name),
                "text": str(text),
                "detail": detail,
                "attachment_result": result,
            }))

    return results
