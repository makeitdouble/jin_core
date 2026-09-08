import re

from utils.attached_files_store import file_display_name

TEXT_ATTACHMENT_CONTEXT_MAX_CHARS = 32000


def strip_attachment_source_text(value):
    text = str(value or "")
    # Local reader compatibility for old turns that embedded source in USER text.
    return re.sub(
        r"--- BEGIN ATTACHMENT TEXT: [^\r\n]+ ---[\s\S]*?--- END ATTACHMENT TEXT: [^\r\n]+ ---",
        "[file content managed by ATTACH_FILE_CONTENT]", text,
    )


def has_message_attachments(
    message_data: dict,
) -> bool:

    attachments = message_data.get(
        "attachments",
    )

    return isinstance(
        attachments,
        list,
    ) and bool(
        attachments,
    )


def _normalize_attachment_text(
    value,
) -> str:

    return str(
        value
        if value is not None
        else ""
    ).replace(
        "\r\n",
        "\n",
    ).replace(
        "\r",
        "\n",
    )


def _get_attachment_text_content(
    attachment: dict,
) -> str:

    if "text_content" in attachment:
        return _normalize_attachment_text(
            attachment.get(
                "text_content",
            )
        )

    # Backward compatibility for turns created by older clients that only
    # supplied the preview field.
    return _normalize_attachment_text(
        attachment.get(
            "text_preview",
            "",
        )
    )


def format_attachment_context(
    message_data: dict,
    *,
    max_text_chars: int = TEXT_ATTACHMENT_CONTEXT_MAX_CHARS,
    include_text: bool = True,
) -> str:

    attachments = message_data.get(
        "attachments",
    )

    if not isinstance(
        attachments,
        list,
    ):
        return ""

    lines = [
        "Attached context:",
    ]

    included = 0
    folder_name_counts = {}
    for item in attachments:
        if not isinstance(item, dict):
            continue
        item_name = str(item.get("name") or "")
        if item_name.lower().endswith(".jin-folder"):
            display = file_display_name(item_name)
            folder_name_counts[display] = folder_name_counts.get(display, 0) + 1

    for index, attachment in enumerate(
        attachments,
        start=1,
    ):

        if not isinstance(
            attachment,
            dict,
        ):
            continue

        included += 1

        name = str(
            attachment.get(
                "name",
                f"attachment-{index}",
            )
        )
        kind = str(
            attachment.get(
                "kind",
                "file",
            )
        )
        mime_type = str(
            attachment.get(
                "type",
                "application/octet-stream",
            )
        )
        size_label = str(
            attachment.get(
                "size_label",
                "",
            )
        )

        detail_parts = [
            kind,
            mime_type,
        ]

        if size_label:
            detail_parts.append(
                size_label
            )

        width = attachment.get(
            "width",
        )
        height = attachment.get(
            "height",
        )

        if width and height:
            detail_parts.append(
                f"{width}x{height}"
            )

        context_path = str(
            attachment.get(
                "context_path",
                name,
            )
            or name
        )
        file_id = str(
            attachment.get(
                "id",
                "",
            )
            or ""
        ).strip()
        id_suffix = (
            f" [ id: {file_id} ]"
            if file_id
            else ""
        )

        if name.lower().endswith(".jin-folder"):
            context_path = file_display_name(name)
            detail_parts = ["folder"]

        if name.lower().endswith(".jin-folder"):
            duplicate_suffix = (
                f" [ duplicate-name ASSET_ACTION id: {file_id} ]"
                if file_id and folder_name_counts.get(context_path, 0) > 1
                else ""
            )
            lines.append(f"- {context_path}/: folder{duplicate_suffix}")
            lines.append(
                f"Linked project (read only). File-path root is {context_path}/. "
                f"Use {context_path} as the ASSET_ACTION attachment (or omit it when this is the only folder). "
                "List/search with ASSET_ACTION; load files by copying folder-rooted paths into ATTACH_FILE_CONTENT."
            )
            continue

        lines.append(
            f"- {context_path}: {', '.join(detail_parts)}{id_suffix}"
        )

    if not included:
        return ""

    if include_text:
        from types import SimpleNamespace
        from utils.context.files import build_file_contents_context
        lines.append(build_file_contents_context(SimpleNamespace(
            runtime_turn_attachments=attachments,
            runtime_attached_file_ids=[item.get("id") for item in attachments if isinstance(item, dict)],
        ), max_text_chars=max_text_chars))

    return "\n".join(
        lines,
    ).strip()


def redacted_attachment_for_log(
    attachment: dict,
) -> dict:

    redacted = dict(
        attachment
    )

    if redacted.get(
        "data_url",
    ):
        redacted["data_url"] = (
            f"<redacted image data url; "
            f"{len(str(redacted.get('data_url') or ''))} chars>"
        )

    if redacted.get(
        "text_content",
    ):
        redacted["text_content"] = (
            f"<redacted text attachment content; "
            f"{len(str(redacted.get('text_content') or ''))} chars>"
        )

    return redacted


def redacted_message_data_for_log(
    message_data: dict,
) -> dict:

    redacted = dict(
        message_data
    )

    attachments = redacted.get(
        "attachments",
    )

    if isinstance(
        attachments,
        list,
    ):
        redacted["attachments"] = [
            redacted_attachment_for_log(
                attachment
            )
            if isinstance(
                attachment,
                dict,
            )
            else attachment
            for attachment in attachments
        ]

    return redacted


def get_message_user_text(
    message_data: dict,
) -> str:

    if not isinstance(message_data, dict):
        return ""

    return str(
        message_data.get(
            "text",
            "",
        )
        or ""
    ).strip()


def build_user_text_with_attachments(
    message_data: dict,
) -> str:

    user_text = get_message_user_text(
        message_data
    )

    attachment_context = format_attachment_context(
        message_data,
        include_text=False,
    )

    if not attachment_context:
        return user_text

    if not user_text:
        return attachment_context

    return "\n\n".join([
        user_text,
        attachment_context,
    ])


def attachment_ids_from_message_data(message_data: dict) -> list[str]:
    from utils.attached_files_store import FILE_ID_RE, MAX_ATTACHED_FILES

    ids = []
    attachments = message_data.get("attachments", [])
    if not isinstance(attachments, list):
        return ids
    for attachment in attachments:
        if not isinstance(attachment, dict):
            continue
        file_id = str(attachment.get("id") or "").strip().lower()
        if FILE_ID_RE.fullmatch(file_id) and file_id not in ids:
            ids.append(file_id)
        if len(ids) >= MAX_ATTACHED_FILES:
            break
    return ids


def hydrate_message_attachments(message_data: dict, file_ids=None) -> list[dict]:
    from utils.attached_files_store import hydrate_attachment_ids

    ids = list(file_ids) if file_ids is not None else attachment_ids_from_message_data(message_data)
    attachments = hydrate_attachment_ids(ids)
    if attachments:
        message_data["attachments"] = attachments
    else:
        message_data.pop("attachments", None)
    return attachments


def build_attached_files_inventory_context(context=None) -> str:
    from utils.attached_files_store import get_file_record

    if context is None:
        return ""
    file_ids = getattr(context, "runtime_attached_file_ids", [])
    if not isinstance(file_ids, list) or not file_ids:
        return ""
    records = [get_file_record(file_id) for file_id in file_ids]
    records = [record for record in records if record]
    folder_names = [
        file_display_name(record["name"])
        for record in records
        if str(record.get("name") or "").lower().endswith(".jin-folder")
    ]
    folder_name_counts = {name: folder_names.count(name) for name in set(folder_names)}
    lines = []
    for record in records:
        display_name = file_display_name(record["name"])
        if str(record.get("name") or "").lower().endswith(".jin-folder"):
            suffix = (
                f" [ duplicate-name ASSET_ACTION id: {record['id']} ]"
                if folder_name_counts.get(display_name, 0) > 1
                else ""
            )
            lines.append(f"    {display_name}/{suffix}")
        else:
            lines.append(f"    {display_name} [ id: {record['id']} ]")
    from utils.context.files import loaded_project_files, project_file_display_ref
    for result in loaded_project_files(context):
        lines.append(f"    {project_file_display_ref(result)}; read: {result.get('range', '')}")
    if not lines:
        return ""
    return "<ATTACHED_FILES>\n" + "\n".join(lines) + "\n</ATTACHED_FILES>"
