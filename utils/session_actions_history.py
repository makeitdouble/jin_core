import time


MAX_SESSION_ACTION_HISTORY_ITEMS = 200


ACTION_DISPLAY_ALIASES = {
    "append_asset_file": "Appended asset file",
    "append_delayed_memory": "Appended delayed memory",
    "append_skill": "Appended skill",
    "append_wildcard_file": "Appended wildcard file",
    "asset_action": "Processed asset action",
    "check_duplicates": "Checked duplicates",
    "create_active_memory": "Created active memory",
    "create_asset_file": "Created asset file",
    "create_wildcard_file": "Created wildcard file",
    "create_wildcard_library": "Created wildcard library",
    "expand_template": "Expanded template",
    "generate_prompt_batch": "Generated prompt batch",
    "hide_skills": "Hidden skills list",
    "list_delayed_memory": "Listed delayed memory",
    "list_skills": "Listed skills",
    "list_wildcards": "Listed wildcards",
    "preview_file": "Previewed file",
    "read_asset_file": "Read asset file",
    "read_asset_text": "Read asset text",
    "remove_delayed_memory": "Removed delayed memory",
    "remove_skill": "Removed skill",
    "resolve_active_memory": "Resolved active memory",
    "sample_wildcard": "Sampled wildcard",
    "save_delayed_memory_content": "Saved delayed memory",
    "save_session": "Saved session",
}


ACTION_PAST_TENSE_VERBS = {
    "append": "Appended",
    "asset": "Processed",
    "check": "Checked",
    "create": "Created",
    "delete": "Deleted",
    "expand": "Expanded",
    "generate": "Generated",
    "hide": "Hidden",
    "list": "Listed",
    "preview": "Previewed",
    "read": "Read",
    "remove": "Removed",
    "resolve": "Resolved",
    "sample": "Sampled",
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

    action_name = "_".join(
        parts
    ).lower()

    alias = ACTION_DISPLAY_ALIASES.get(
        action_name,
    )

    if alias:
        return alias

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

    item = {
        "text": normalized_text,
        "created_at": time.time(),
    }

    runtime_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()

    if runtime_turn_id:
        item["runtime_turn_id"] = runtime_turn_id

    history.append(
        item
    )

    if len(history) > MAX_SESSION_ACTION_HISTORY_ITEMS:
        del history[:-MAX_SESSION_ACTION_HISTORY_ITEMS]


def format_session_action_marker_names(
    marker_actions,
) -> str:

    action_groups = {}

    for marker_action in marker_actions or []:
        if isinstance(
            marker_action,
            dict,
        ):
            action_name = marker_action.get(
                "name",
                "",
            )
            action_payload = marker_action.get(
                "payload",
                "",
            )
        elif hasattr(
            marker_action,
            "name",
        ):
            action_name = getattr(
                marker_action,
                "name",
                "",
            )
            action_payload = getattr(
                marker_action,
                "payload",
                "",
            )
        else:
            action_name = marker_action
            action_payload = ""

        normalized_name = str(
            action_name
            or ""
        ).strip().upper()

        if not normalized_name:
            continue

        group = action_groups.setdefault(
            normalized_name,
            {
                "count": 0,
                "payload_counts": {},
            },
        )
        group["count"] += 1

        normalized_payload = str(
            action_payload
            or ""
        ).strip()

        if normalized_payload:
            payload_counts = group[
                "payload_counts"
            ]
            payload_counts[normalized_payload] = (
                payload_counts.get(
                    normalized_payload,
                    0,
                )
                + 1
            )

    formatted_names = []

    for action_name, group in action_groups.items():
        count = group[
            "count"
        ]
        payload_counts = group[
            "payload_counts"
        ]

        if (
            action_name in (
                "APPEND_SKILL",
                "REMOVE_SKILL",
            )
            and payload_counts
        ):
            formatted_payloads = []

            for payload, payload_count in payload_counts.items():
                if payload_count > 1:
                    formatted_payloads.append(
                        f"{payload} ( repeated_times: {payload_count} )"
                    )
                    continue

                formatted_payloads.append(
                    payload
                )

            formatted_names.append(
                f"{action_name}: {', '.join(formatted_payloads)}"
            )
            continue

        if count > 1:
            formatted_names.append(
                f"{action_name} ( repeated_times: {count} )"
            )
            continue

        formatted_names.append(
            action_name
        )

    return ", ".join(
        formatted_names
    )


def replace_session_action_history_since(
    context,
    start_index: int,
    marker_actions,
) -> None:

    if context is None:
        return

    formatted_marker_names = format_session_action_marker_names(
        marker_actions
    )

    if not formatted_marker_names:
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

    safe_start_index = max(
        0,
        min(
            int(
                start_index
                or 0
            ),
            len(history),
        ),
    )

    del history[safe_start_index:]

    record_session_action_history(
        context,
        formatted_marker_names,
    )


def mark_current_action_sequence(
    context,
) -> str:

    if context is None:
        return ""

    runtime_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()

    if not runtime_turn_id:
        return ""

    sequence_turn_ids = getattr(
        context,
        "runtime_action_sequence_turn_ids",
        None,
    )

    if not isinstance(
        sequence_turn_ids,
        list,
    ):
        sequence_turn_ids = []
        setattr(
            context,
            "runtime_action_sequence_turn_ids",
            sequence_turn_ids,
        )

    if runtime_turn_id not in sequence_turn_ids:
        sequence_turn_ids.append(
            runtime_turn_id
        )

    return runtime_turn_id
