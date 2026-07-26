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


def format_attachment_context(
    message_data: dict,
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

        lines.append(
            f"- {name}: {', '.join(detail_parts)}"
        )

        if (
            attachment.get(
                "text_content"
            ) is not None
            or str(
                attachment.get(
                    "data_url",
                    "",
                )
                or ""
            ).startswith(
                "data:"
            )
        ):
            lines.append(
                "  runtime_attachment: full content is available to appended skills"
            )

        text_preview = attachment.get(
            "text_preview",
        )

        if text_preview is not None:
            preview = str(
                text_preview
            )
            preview_limit = int(
                attachment.get(
                    "preview_limit",
                    len(
                        preview
                    ),
                )
                or 0
            )
            truncated = bool(
                attachment.get(
                    "truncated",
                    False,
                )
            )
            status = (
                f"first {preview_limit} chars sent"
                if truncated
                else f"{len(preview)} chars sent"
            )

            lines.append(
                f"  text_preview ({status}):"
            )
            lines.append(
                preview
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
