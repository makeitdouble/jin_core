from contracts.rules_assembler import (
    RUNTIME_ACTION_LIST_FILES,
    RUNTIME_ACTION_LOAD_ATTACHMENT,
    RUNTIME_ACTION_UNLOAD_ATTACHMENT,
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


def _apply_context_ids(context, ids: list[str]) -> None:
    normalized = []
    for value in ids:
        file_id = _clean_id(value)
        if file_id and get_file_record(file_id) and file_id not in normalized:
            normalized.append(file_id)
        if len(normalized) >= MAX_ATTACHED_FILES:
            break
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
        await emit({
            "type": "attached_files_update",
            **public_file_snapshot(),
        })


async def apply_attachment_actions(
    context,
    *,
    list_actions,
    load_actions,
    unload_actions,
    log_runtime=None,
    with_action_context=lambda payload: payload,
) -> list[dict]:
    results = []
    active_ids = _active_ids(context)

    if list_actions:
        records = list_file_records()
        lines = format_list_files_lines(records)
        result = {
            "action": "list_files",
            "ok": True,
            "files": records,
            "lines": lines,
        }
        # one LIST_FILES result is enough even if the marker was repeated.
        record_runtime_tool_result(context, TOOL_RESULT_KIND_FILES, result)
        results.append(result)
        if log_runtime is not None:
            await log_runtime(f"[RUNTIME ACTION] list_files ({len(records)} files)")

    for action in unload_actions:
        file_id = _clean_id(action.payload)
        record = get_file_record(file_id)
        if not file_id or record is None:
            results.append({
                "action": "unload_attachment",
                "ok": False,
                "id": file_id or str(action.payload or "").strip(),
                "error": "file_not_found",
            })
            continue
        was_loaded = file_id in active_ids
        active_ids = [value for value in active_ids if value != file_id]
        set_file_pinned(file_id, False)
        results.append({
            "action": "unload_attachment",
            "ok": True,
            "id": file_id,
            "name": record["name"],
            "unloaded": was_loaded,
        })

    for action in load_actions:
        file_id = _clean_id(action.payload)
        record = get_file_record(file_id)
        if not file_id or record is None:
            results.append({
                "action": "load_attachment",
                "ok": False,
                "id": file_id or str(action.payload or "").strip(),
                "error": "file_not_found",
            })
            continue
        if file_id in active_ids:
            results.append({
                "action": "load_attachment",
                "ok": True,
                "id": file_id,
                "name": record["name"],
                "loaded": False,
                "already_loaded": True,
            })
            continue
        previous_active_ids = list(active_ids)
        updated, error = set_file_pinned(file_id, True)
        if error:
            results.append({
                "action": "load_attachment",
                "ok": False,
                "id": file_id,
                "name": record["name"],
                "error": error,
            })
            continue
        active_ids = get_pinned_file_ids()
        replaced_ids = [
            value
            for value in previous_active_ids
            if value not in active_ids
        ]
        result = {
            "action": "load_attachment",
            "ok": True,
            "id": file_id,
            "name": updated["name"],
            "loaded": True,
        }
        if replaced_ids:
            result["replaced_id"] = replaced_ids[0]
        results.append(result)

    if load_actions or unload_actions:
        _apply_context_ids(context, active_ids)
        if log_runtime is not None:
            await log_runtime(
                f"[RUNTIME ACTION] attachments active: {len(active_ids)}/{MAX_ATTACHED_FILES}"
            )
        await _emit_snapshot(context)

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)
    if emit is not None:
        for result in results:
            action_name = {
                "list_files": RUNTIME_ACTION_LIST_FILES,
                "load_attachment": RUNTIME_ACTION_LOAD_ATTACHMENT,
                "unload_attachment": RUNTIME_ACTION_UNLOAD_ATTACHMENT,
            }.get(result.get("action"), result.get("action", ""))
            text = result.get("name") or result.get("error") or (
                f"{len(result.get('files', []))} files"
                if result.get("action") == "list_files"
                else "attachment updated"
            )
            await emit(with_action_context({
                "type": "runtime_action",
                "action": result.get("action"),
                "id": result.get("id") or result.get("action"),
                "status": "completed" if result.get("ok") is not False else "failed",
                "display_name": get_runtime_action_display_name(action_name),
                "close_tag": runtime_action_has_close_tag(action_name),
                "text": str(text),
                "attachment_result": result,
            }))

    return results
