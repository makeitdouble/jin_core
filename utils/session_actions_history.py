import json
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


def _normalize_session_action_display_parts(
    parts,
) -> list[dict]:

    normalized_parts = []

    for part in parts or []:
        if isinstance(
            part,
            dict,
        ):
            part_text = str(
                part.get(
                    "text",
                    "",
                )
                or ""
            ).strip()
            detail = str(
                part.get(
                    "detail",
                    "",
                )
                or ""
            ).strip()
        else:
            part_text = str(
                part
                or ""
            ).strip()
            detail = ""

        if not part_text:
            continue

        normalized_part = {
            "text": part_text,
        }

        if detail:
            normalized_part["detail"] = detail

        normalized_parts.append(
            normalized_part
        )

    return normalized_parts


def _build_session_action_display_part(
    text: str,
) -> dict:

    normalized_text = str(
        text
        or ""
    ).strip()

    if not normalized_text:
        return {}

    detail_separator = " - "
    detail_separator_index = normalized_text.find(
        detail_separator
    )

    if detail_separator_index < 0:
        return {
            "text": normalized_text,
        }

    visible_text = normalized_text[
        :detail_separator_index
    ].strip()
    detail = normalized_text[
        detail_separator_index
        + len(detail_separator):
    ].strip()

    if not visible_text:
        visible_text = normalized_text
        detail = ""

    part = {
        "text": visible_text,
    }

    if detail:
        part["detail"] = detail

    return part


def _format_session_action_display_part(
    part: dict,
) -> str:

    normalized_parts = (
        _normalize_session_action_display_parts([
            part,
        ])
    )

    if not normalized_parts:
        return ""

    normalized_part = normalized_parts[0]
    text = normalized_part["text"]
    detail = normalized_part.get(
        "detail",
        "",
    )

    if detail:
        return f"{text} - {detail}"

    return text


def record_session_action_history(
    context,
    text: str,
    *,
    display_parts=None,
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

    normalized_display_parts = (
        _normalize_session_action_display_parts(
            display_parts
        )
    )

    if not normalized_display_parts:
        fallback_part = (
            _build_session_action_display_part(
                normalized_text
            )
        )
        if fallback_part:
            normalized_display_parts = [
                fallback_part,
            ]

    item = {
        "text": normalized_text,
        "created_at": time.time(),
    }

    if normalized_display_parts:
        item["parts"] = normalized_display_parts

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


def build_reasoning_loop_history_text(
    quote: str,
) -> str:

    normalized_quote = str(
        quote
        or ""
    ).strip()

    if not normalized_quote:
        return "stuck in a reasoning loop"

    return (
        "stuck in a reasoning loop with "
        f'"{normalized_quote}"'
    )


def build_context_limit_history_text(
    stage: str,
    limit_kind: str = "context",
) -> str:

    normalized_stage = str(
        stage
        or "generation"
    ).strip().casefold()

    if normalized_stage not in {
        "reasoning",
        "answer",
        "generation",
    }:
        normalized_stage = "generation"

    normalized_limit_kind = str(
        limit_kind
        or "context"
    ).strip().casefold()

    limit_label = (
        "output token limit"
        if normalized_limit_kind == "output"
        else "context limit"
    )

    return (
        f"{limit_label} reached during "
        f"{normalized_stage}"
    )


def build_delayed_memory_save_rejected_history_text(
    title: str = "",
) -> str:

    normalized_title = str(
        title
        or ""
    ).strip()

    text = "SAVE_DELAYED_MEMORY_CONTENT - failed"

    if normalized_title:
        text = f"{text}: {normalized_title}"

    return (
        f"{text} "
        "(user did not provided system allowed trigger words for this action)"
    )


def build_active_memory_resolve_failed_history_text(
    result: dict,
) -> str:

    requested = str(
        result.get(
            "requested",
            "",
        )
        or result.get(
            "id",
            "",
        )
        or "unknown"
    ).strip()
    error = str(
        result.get(
            "error",
            "",
        )
        or "active_memory_not_resolved"
    ).strip()

    return (
        "RESOLVE_ACTIVE_MEMORY - failed: "
        f"{requested} ({error}; action was not executed)"
    )


def _find_saved_action_title(
    value,
) -> str:

    if not isinstance(
        value,
        dict,
    ):
        return ""

    title = str(
        value.get(
            "title",
            "",
        )
        or ""
    ).strip()

    if title:
        return title

    for nested_value in value.values():
        title = _find_saved_action_title(
            nested_value
        )

        if title:
            return title

    return ""


def _build_session_action_marker_detail(
    action_name: str,
    action_payload: str,
) -> str:

    normalized_name = str(
        action_name
        or ""
    ).strip().upper()
    normalized_payload = str(
        action_payload
        or ""
    ).strip()

    if not normalized_payload:
        return ""

    if normalized_name in {
        "CREATE_ACTIVE_MEMORY",
        "IDLE",
    }:
        return normalized_payload

    if not normalized_name.startswith(
        "SAVE_"
    ):
        return ""

    try:
        parsed_payload = json.loads(
            normalized_payload
        )
    except (
        TypeError,
        ValueError,
    ):
        return ""

    return _find_saved_action_title(
        parsed_payload
    )


def _build_formatted_session_action_marker_parts(
    marker_actions,
) -> list[dict]:

    action_groups = {}
    idle_group_index = 0

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

        group_key = normalized_name

        if normalized_name == "IDLE":
            idle_group_index += 1
            group_key = (
                normalized_name,
                idle_group_index,
            )

        group = action_groups.setdefault(
            group_key,
            {
                "action_name": normalized_name,
                "count": 0,
                "payload_counts": {},
                "detail_counts": {},
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

        detail = _build_session_action_marker_detail(
            normalized_name,
            normalized_payload,
        )

        if detail:
            detail_counts = group[
                "detail_counts"
            ]
            detail_counts[detail] = (
                detail_counts.get(
                    detail,
                    0,
                )
                + 1
            )

    formatted_parts = []

    for group in action_groups.values():
        action_name = group[
            "action_name"
        ]
        count = group[
            "count"
        ]
        payload_counts = group[
            "payload_counts"
        ]
        detail_counts = group[
            "detail_counts"
        ]

        if detail_counts:
            for detail, detail_count in detail_counts.items():
                formatted_detail = detail

                if detail_count > 1:
                    formatted_detail = (
                        f"{formatted_detail} "
                        f"( repeated_times: {detail_count} )"
                    )

                formatted_parts.append({
                    "text": action_name,
                    "detail": formatted_detail,
                })

            continue

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

            formatted_parts.append({
                "text": (
                    f"{action_name}: "
                    f"{', '.join(formatted_payloads)}"
                ),
            })
            continue

        if count > 1:
            formatted_parts.append({
                "text": (
                    f"{action_name} "
                    f"( repeated_times: {count} )"
                ),
            })
            continue

        formatted_parts.append({
            "text": action_name,
        })

    return formatted_parts


def format_session_action_marker_names(
    marker_actions,
) -> str:

    return ", ".join(
        formatted_part
        for formatted_part in (
            _format_session_action_display_part(
                part
            )
            for part in (
                _build_formatted_session_action_marker_parts(
                    marker_actions
                )
            )
        )
        if formatted_part
    )


def replace_session_action_history_since(
    context,
    start_index: int,
    marker_actions,
) -> None:

    if context is None:
        return

    formatted_marker_parts = (
        _build_formatted_session_action_marker_parts(
            marker_actions
        )
    )
    formatted_marker_names = ", ".join(
        formatted_part
        for formatted_part in (
            _format_session_action_display_part(
                part
            )
            for part in formatted_marker_parts
        )
        if formatted_part
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
        display_parts=formatted_marker_parts,
    )


def compact_session_action_history_since(
    context,
    start_index: int,
) -> bool:

    if context is None:
        return False

    history = getattr(
        context,
        "runtime_session_action_history",
        None,
    )

    if not isinstance(
        history,
        list,
    ):
        return False

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
    new_items = [
        item
        for item in history[safe_start_index:]
        if isinstance(
            item,
            dict,
        )
        and str(
            item.get(
                "text",
                "",
            )
            or ""
        ).strip()
    ]

    if len(new_items) < 2:
        return False

    merged_item = dict(
        new_items[0]
    )
    merged_item["text"] = ", ".join(
        str(
            item.get(
                "text",
                "",
            )
            or ""
        ).strip()
        for item in new_items
    )

    merged_parts = []

    for item in new_items:
        item_parts = (
            _normalize_session_action_display_parts(
                item.get(
                    "parts",
                    [],
                )
            )
        )

        if not item_parts:
            fallback_part = (
                _build_session_action_display_part(
                    item.get(
                        "text",
                        "",
                    )
                )
            )
            if fallback_part:
                item_parts = [
                    fallback_part,
                ]

        merged_parts.extend(
            item_parts
        )

    if merged_parts:
        merged_item["parts"] = merged_parts

    created_at_values = []

    for item in new_items:
        try:
            created_at_values.append(
                float(
                    item.get(
                        "created_at",
                        0,
                    )
                    or 0
                )
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

    if created_at_values:
        merged_item["created_at"] = min(
            created_at_values
        )

    del history[safe_start_index:]
    history.append(
        merged_item
    )

    return True


def build_session_actions_update_items(
    context,
    *,
    current_sequence: bool,
) -> list[dict]:

    if context is None:
        return []

    history = getattr(
        context,
        "runtime_session_action_history",
        [],
    )

    if not isinstance(
        history,
        list,
    ):
        return []

    runtime_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()

    if current_sequence and not runtime_turn_id:
        return []

    items = []

    for item in history:
        if not isinstance(
            item,
            dict,
        ):
            continue

        text = str(
            item.get(
                "text",
                "",
            )
            or ""
        ).strip()

        if not text:
            continue

        item_turn_id = str(
            item.get(
                "runtime_turn_id",
                "",
            )
            or ""
        ).strip()

        if (
            current_sequence
            and item_turn_id != runtime_turn_id
        ):
            continue

        try:
            created_at = float(
                item.get(
                    "created_at",
                    0,
                )
                or 0
            )
        except (
            TypeError,
            ValueError,
        ):
            created_at = 0.0

        parts = _normalize_session_action_display_parts(
            item.get(
                "parts",
                [],
            )
        )

        if not parts:
            fallback_part = (
                _build_session_action_display_part(
                    text
                )
            )
            if fallback_part:
                parts = [
                    fallback_part,
                ]

        update_item = {
            "text": text,
            "created_at": created_at,
        }

        if parts:
            update_item["parts"] = parts

        items.append(
            update_item
        )

    return items


async def emit_session_actions_update(
    context,
    *,
    current_sequence: bool,
) -> None:

    items = build_session_actions_update_items(
        context,
        current_sequence=current_sequence,
    )

    if not items:
        return

    emitter = getattr(
        context,
        "emitter",
        None,
    )
    emit = getattr(
        emitter,
        "emit",
        None,
    )

    if emit is None:
        return

    await emit({
        "type": "session_actions_update",
        "mode": (
            "sequence"
            if current_sequence
            else "session_actions"
        ),
        "sequence_id": str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ),
        "items": items,
    })


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
