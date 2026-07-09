import time


MAX_SESSION_ACTION_HISTORY_ITEMS = 200


ACTION_PAST_TENSE_VERBS = {
    "append": "Appended",
    "asset": "Processed",
    "check": "Checked",
    "create": "Created",
    "delete": "Deleted",
    "generate": "Generated",
    "list": "Readed",
    "read": "Readed",
    "remove": "Removed",
    "resolve": "Resolved",
    "save": "Saved",
    "update": "Updated",
    "write": "Wrote",
}


def _build_past_tense_action_text(
    action: str,
) -> str:

    parts = [
        part
        for part in str(
            action
            or ""
        ).strip().split("_")
        if part
    ]

    if not parts:
        return "Processed asset action"

    verb = ACTION_PAST_TENSE_VERBS.get(
        parts[0],
    )

    if verb is None:
        return "Processed " + " ".join(
            parts
        )

    subject_parts = parts[1:]

    if parts[0] == "asset":
        subject_parts = parts

    subject = " ".join(
        subject_parts
    )

    if not subject:
        subject = " ".join(
            parts
        )

    return f"{verb} {subject}".strip()


def build_asset_action_history_text(
    result: dict,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return _build_past_tense_action_text(
            "asset_action"
        )

    action = str(
        result.get(
            "action",
            "assets",
        )
        or "assets"
    )
    path = str(
        result.get(
            "path",
            "",
        )
        or ""
    ).strip()

    text = _build_past_tense_action_text(
        action
    )

    if path:
        text = f"{text} - {path}"

    if result.get("ok") is False:
        text = f"{text} - failed"

    return text


def record_session_action_history(
    context,
    text: str,
) -> None:

    if context is None:
        return

    normalized_text = str(
        text
        or ""
    ).strip()

    if not normalized_text:
        return

    history = getattr(
        context,
        "runtime_session_action_history",
        None,
    )

    if not isinstance(
        history,
        list,
    ):
        history = []
        setattr(
            context,
            "runtime_session_action_history",
            history,
        )

    history.append(
        {
            "text": normalized_text,
            "created_at": time.time(),
        }
    )

    if len(history) > MAX_SESSION_ACTION_HISTORY_ITEMS:
        del history[:-MAX_SESSION_ACTION_HISTORY_ITEMS]
