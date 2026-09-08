"""One file-content projection; existing tool records own project read snapshots."""
import re
from xml.sax.saxutils import escape

from utils import attached_files_store as files


def project_file_ref(result):
    if not isinstance(result, dict):
        return ""
    if result.get("action") != "project_read" and result.get("source") != "project":
        return ""
    return str(result.get("file_ref") or f"{result.get('attachment', '')}/{result.get('path', '')}")


def project_file_result_active(context, result) -> bool:
    """Whether a project read still belongs to the currently selected source root."""
    if not isinstance(result, dict):
        return False
    if result.get("implicit_project"):
        # The built-in JIN root exists only while no real project folder is
        # linked. Linking a folder switches cleanly to normal Project Mode and
        # hides source blocks loaded from the implicit root.
        from utils.project_reader import linked_projects
        return not linked_projects(context, include_pending_restore=True)

    ref = project_file_ref(result)
    if not ref:
        return False
    active = {
        str(value or "").strip().casefold()
        for value in getattr(context, "runtime_attached_file_ids", []) or []
    }
    return ref.split("/", 1)[0].strip().casefold() in active


def project_file_load_key(result):
    """Identity of one loaded project source block, including its requested window."""
    ref = project_file_ref(result)
    if not ref:
        return None
    return ref, _requested_line_range(result)


def project_file_display_ref(result):
    """Visible folder-rooted path for prompt/UI text; internal file_ref stays id-based."""
    if not isinstance(result, dict):
        return ""
    value = str(result.get("display_ref") or "").strip()
    if value:
        return value
    relative = str(result.get("path") or "").strip().replace("\\", "/").lstrip("/")
    project_name = str(result.get("project_name") or "").strip().rstrip("/")
    if not project_name:
        record = files.get_file_record(result.get("attachment", ""))
        project_name = files.file_display_name(record["name"]) if record else ""
    if project_name:
        return f"{project_name}/{relative}" if relative and relative != "." else project_name
    return relative or project_file_ref(result)


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
    seen = set()
    for result in reversed(list(_project_results(context))):
        ref = project_file_ref(result)
        load_key = project_file_load_key(result)
        if (result.get("ok") is False or result.get("loaded") is False
                or "content" not in result or not project_file_result_active(context, result)
                or load_key in seen):
            continue
        seen.add(load_key)
        yield result


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


def _loaded_line_range(result):
    """Actual source lines owned by one loaded project result."""
    if not isinstance(result, dict):
        return None
    try:
        start = int(result.get("loaded_start"))
        end = int(result.get("loaded_end"))
    except (TypeError, ValueError):
        start = end = 0
    if start > 0 and end >= start:
        return start, end

    # Backward compatibility for already-persisted project reads created
    # before loaded_start/loaded_end existed. ``range`` records the actual
    # emitted window and is safer than requested_end when the 24K output
    # budget stopped a read before the requested line boundary.
    match = re.fullmatch(
        r"\s*(\d+)-(\d+)\s+of\s+\d+\s+lines\s*",
        str(result.get("range") or ""),
    )
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if start > 0 and end >= start:
            return start, end

    return _requested_line_range(result)


def project_file_content_label(result) -> str:
    """Compact FILE_CONTENT label: basename plus the actual loaded line window."""
    display_ref = project_file_display_ref(result) or project_file_ref(result)
    normalized = str(display_ref or "").strip().replace("\\", "/").rstrip("/")
    basename = normalized.rsplit("/", 1)[-1] if normalized else "file"
    loaded_range = _loaded_line_range(result)
    if loaded_range is None:
        return basename
    return f"{basename}#{loaded_range[0]}-{loaded_range[1]}"


def project_file_action_label(result) -> str:
    """Full folder-rooted path plus the actual loaded line window."""
    display_ref = project_file_display_ref(result) or project_file_ref(result)
    normalized = str(display_ref or "").strip().replace("\\", "/")
    loaded_range = _loaded_line_range(result)
    if loaded_range is None:
        return normalized
    return f"{normalized}#{loaded_range[0]}-{loaded_range[1]}"


def next_project_file_unread_start(context, reference) -> int:
    """Return the first unread line in the contiguous prefix of one file."""
    normalized_ref = str(reference or "").strip()
    next_line = 1
    ranges = []
    for result in loaded_project_files(context):
        if project_file_ref(result) != normalized_ref:
            continue
        loaded_range = _loaded_line_range(result)
        if loaded_range is not None:
            ranges.append(loaded_range)

    for start, end in sorted(ranges):
        if end < next_line:
            continue
        if start > next_line:
            break
        next_line = end + 1

    return next_line


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
        unloaded = True
    return unloaded


def unload_persistent_file_results(
    context,
    file_id,
):
    """Mark recorded ATTACH_FILE_CONTENT snapshots unloaded without deleting the action."""
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
            result.get("action") != "attach_file_content"
            or result.get("source") == "project"
            or result.get("ok") is False
            or str(result.get("id") or "").strip().lower() != normalized_id
            or result.get("loaded") is False
        ):
            continue
        result["loaded"] = False
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
        load_key = project_file_load_key(result)
        digest = result.get("source_sha256")
        # Different requested windows of the same project file are different
        # source blocks. Keep hash de-dupe only against persistent attachments;
        # project/project duplicates are handled by load_key instead.
        if load_key in seen or (digest and digest in hashes):
            continue
        seen.add(load_key)
        blocks.append(format_file_content(project_file_content_label(result), result["content"]))
    return "\n\n".join(blocks)


def file_result_summary(result):
    """One attachment outcome label for bubbles, history and context."""
    action = str(result.get("action") or "file").upper()
    reference = (project_file_action_label(result) if project_file_ref(result)
                 else files.file_display_name(result.get("name") or result.get("id") or ""))
    text = f"{action}: {reference}" if reference else action
    if result.get("ok") is False:
        reason = str(result.get("detail") or result.get("error") or "action failed").strip()
        text += f" - failed: {reason}"
    return text


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
        if result.get("loaded") is False:
            lines.append("Status: unloaded")
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
            and result.get("action") == "attach_file_content"
        )

    return [
        entry
        for index, entry in enumerate(entries)
        if index >= boundary or owns_loaded_file(entry)
    ]
