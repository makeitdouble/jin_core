TEXT_ATTACHMENT_CONTEXT_MAX_CHARS = 32000


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
) -> str:

    attachments = message_data.get(
        "attachments",
    )

    if not isinstance(
        attachments,
        list,
    ):
        return ""

    try:
        remaining_text_chars = max(
            0,
            int(
                max_text_chars
            ),
        )
    except (
        TypeError,
        ValueError,
    ):
        remaining_text_chars = (
            TEXT_ATTACHMENT_CONTEXT_MAX_CHARS
        )

    lines = [
        "Attached context:",
    ]

    included = 0

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

        lines.append(
            f"- {context_path}: {', '.join(detail_parts)}{id_suffix}"
        )

        if kind.strip().lower() != "text":
            continue

        text_content = _get_attachment_text_content(
            attachment
        )

        if not text_content.strip():
            continue

        if remaining_text_chars <= 0:
            lines.append(
                "[attachment text omitted: text context budget exhausted]"
            )
            continue

        visible_text = text_content[
            :remaining_text_chars
        ]
        omitted_chars = (
            len(text_content)
            - len(visible_text)
        )
        remaining_text_chars -= len(
            visible_text
        )

        lines.append(
            f"--- BEGIN ATTACHMENT TEXT: {name} ---"
        )
        lines.append(
            visible_text
        )

        if omitted_chars > 0:
            lines.append(
                f"[attachment text truncated: {omitted_chars} chars omitted]"
            )

        lines.append(
            f"--- END ATTACHMENT TEXT: {name} ---"
        )

    if not included:
        return ""

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


def build_user_text_with_attachments(
    message_data: dict,
) -> str:

    user_text = str(
        message_data.get(
            "text",
            "",
        )
    ).strip()

    attachment_context = format_attachment_context(
        message_data,
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
    lines = []
    for file_id in file_ids:
        record = get_file_record(file_id)
        if not record:
            continue
        lines.append(f"    {record['name']} [ id: {record['id']} ]")
    if not lines:
        return ""
    return "<ATTACHED_FILES>\n" + "\n".join(lines) + "\n</ATTACHED_FILES>"
