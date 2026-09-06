"""One file-content projection; existing tool records own project read snapshots."""
from xml.sax.saxutils import escape

from utils import attached_files_store as files


def project_file_ref(result):
    if not isinstance(result, dict):
        return ""
    if result.get("action") != "project_read" and result.get("source") != "project":
        return ""
    return str(result.get("file_ref") or f"{result.get('attachment', '')}/{result.get('path', '')}")


def _project_results(context, *, mirrors=False):
    recorded = getattr(context, "runtime_tool_results", []) or []
    for entry in recorded:
        result = entry.get("result") if isinstance(entry, dict) else None
        if project_file_ref(result):
            yield result
    # Legacy slots are a fallback, not an additional source of prompt content.
    if mirrors or (not recorded and not getattr(context, "runtime_tool_results_generation", 0)):
        for result in getattr(context, "runtime_asset_results", []) or []:
            if project_file_ref(result):
                yield result


def loaded_project_files(context):
    active = set(getattr(context, "runtime_attached_file_ids", []) or [])
    seen = set()
    for result in _project_results(context):
        ref = project_file_ref(result)
        if (result.get("ok") is False or result.get("loaded") is False
                or "content" not in result or ref.split("/", 1)[0] not in active or ref in seen):
            continue
        seen.add(ref)
        yield result


def loaded_file_ref(context, *, reference="", sha256=""):
    for file_id in getattr(context, "runtime_attached_file_ids", []) or []:
        record = files.get_file_record(file_id)
        if record and (reference == file_id or (sha256 and record.get("sha256") == sha256)):
            return file_id
    for result in loaded_project_files(context):
        ref = project_file_ref(result)
        if reference == ref or (sha256 and result.get("source_sha256") == sha256):
            return ref
    return ""


def _requested_line_range(result):
    if not isinstance(result, dict):
        return None
    try:
        start = int(result.get("requested_start"))
        end = int(result.get("requested_end"))
    except (TypeError, ValueError):
        return None
    if start <= 0 or end < start:
        return None
    return start, end


def _matches_requested_line_range(result, start=None, end=None):
    if start is None:
        return True
    try:
        requested = int(start), int(end)
    except (TypeError, ValueError):
        return False
    return _requested_line_range(result) == requested


def unload_project_files(
    context,
    reference,
    *,
    start=None,
    end=None,
    detached_at="",
):
    """Drop matching source bodies while preserving their action/result trail."""
    unloaded = False
    for result in _project_results(context, mirrors=True):
        ref = project_file_ref(result)
        if ref != reference and ref.split("/", 1)[0] != reference:
            continue
        if not _matches_requested_line_range(result, start, end):
            continue
        was_loaded = (
            "content" in result
            or result.get("loaded") is True
        )
        if not was_loaded:
            continue
        if "content" in result:
            unloaded = True
        result.pop("content", None)
        result["loaded"] = False
        if detached_at:
            result["detached_at"] = str(detached_at)
        unloaded = True
    return unloaded


def unload_persistent_file_results(
    context,
    file_id,
    *,
    detached_at="",
):
    """Mark recorded ATTACH_FILE snapshots unloaded without deleting the action."""
    normalized_id = str(file_id or "").strip().lower()
    if not normalized_id:
        return False

    unloaded = False
    for entry in getattr(context, "runtime_tool_results", []) or []:
        if not isinstance(entry, dict) or entry.get("kind") != "files":
            continue
        result = entry.get("result")
        if not isinstance(result, dict):
            continue
        if (
            result.get("action") != "attach_file"
            or result.get("source") == "project"
            or result.get("ok") is False
            or str(result.get("id") or "").strip().lower() != normalized_id
            or result.get("loaded") is False
        ):
            continue
        result["loaded"] = False
        if detached_at:
            result["detached_at"] = str(detached_at)
        unloaded = True
    return unloaded


def format_file_content(name, content):
    # Escape source delimiters so embedded tags cannot manufacture context blocks.
    label = escape(str(name)).replace("\n", " ").replace("\r", " ")
    return f"<FILE_CONTENT: {label} >\n{escape(str(content))}\n</FILE_CONTENT>"


def build_file_contents_context(context, *, max_text_chars=None):
    if context is None or getattr(context, "runtime_session_restore_priming", False):
        return ""
    from websocket.attachments import TEXT_ATTACHMENT_CONTEXT_MAX_CHARS, _get_attachment_text_content
    attachments = (getattr(context, "runtime_turn_attachments", [])
                   or getattr(context, "runtime_current_sequence_attachments", []) or [])
    active = set(getattr(context, "runtime_attached_file_ids", []) or [])
    blocks, seen, hashes = [], set(), set()
    try:
        remaining = max(0, int(TEXT_ATTACHMENT_CONTEXT_MAX_CHARS if max_text_chars is None else max_text_chars))
    except (TypeError, ValueError):
        remaining = TEXT_ATTACHMENT_CONTEXT_MAX_CHARS
    for attachment in attachments:
        if not isinstance(attachment, dict) or attachment.get("kind") != "text":
            continue
        ref = str(attachment.get("id") or attachment.get("context_path") or attachment.get("name"))
        name = str(attachment.get("name") or ref)
        digest = attachment.get("sha256")
        if (name.lower().endswith(".jin-folder") or ref in seen or (digest and digest in hashes)
                or (attachment.get("id") and ref not in active)):
            continue
        seen.add(ref)
        if digest:
            hashes.add(digest)
        content = _get_attachment_text_content(attachment)
        visible = content[:remaining]
        remaining -= len(visible)
        if len(visible) < len(content):
            visible += f"\n[attachment text truncated: {len(content) - len(visible)} chars omitted]"
        blocks.append(format_file_content(name, visible))
    for result in loaded_project_files(context):
        ref = project_file_ref(result)
        digest = result.get("source_sha256")
        if ref in seen or (digest and digest in hashes):
            continue
        seen.add(ref)
        if digest:
            hashes.add(digest)
        blocks.append(format_file_content(result.get("path") or ref, result["content"]))
    return "\n\n".join(blocks)


def format_file_result(result):
    from utils.project_reader import format_project_result
    if project_file_ref(result):
        return format_project_result(result)
    action = str(result.get("action") or "file")
    lines = [f"Action: {action}", f"File: {files.file_display_name(result.get('name') or result.get('id') or '')}"]
    if result.get("id") and result.get("name"):
        lines.append(f"ID: {result['id']}")
    if result.get("ok") is False:
        from contracts.rules_assembler import get_runtime_action_schema
        lines.extend(["Status: failed", f"Reason: {result.get('detail') or result.get('error')}",
                      "Correct action schema:", *get_runtime_action_schema(action.upper())])
    else:
        detached_at = str(result.get("detached_at") or "").strip()
        if action == "detach_file":
            lines.append(
                f"Status: detached at {detached_at}"
                if detached_at
                else "Status: unloaded"
            )
        elif result.get("loaded") is False:
            lines.append(
                f"Status: detached at {detached_at}"
                if detached_at
                else "Status: unloaded"
            )
        requested_range = _requested_line_range(result)
        if requested_range and action == "detach_file":
            lines.append(
                f"Lines: L{requested_range[0]}-L{requested_range[1]}"
            )
        if result.get("replaced_id"):
            lines.append(f"Unloaded: {result['replaced_id']}")
    return "\n".join(lines)


def select_file_tool_results(entries, limit):
    """Keep the normal history tail plus any still-loaded file-owning result."""
    entries = list(entries or [])
    boundary = max(0, len(entries) - limit)

    def owns_loaded_file(entry):
        if not isinstance(entry, dict):
            return False
        result = entry.get("result")
        if not isinstance(result, dict) or result.get("ok") is False or result.get("loaded") is False:
            return False
        if project_file_ref(result):
            return "content" in result
        return (
            entry.get("kind") == "files"
            and result.get("action") == "attach_file"
        )

    return [
        entry
        for index, entry in enumerate(entries)
        if index >= boundary or owns_loaded_file(entry)
    ]
