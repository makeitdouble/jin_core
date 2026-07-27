import json
import re
import time

from utils.actions.action_counter_utils import (
    format_runtime_action_count,
)


MAX_SESSION_ACTION_HISTORY_ITEMS = 200


JIN_COLOR_HEX_RE = re.compile(
    r"#?(?P<hex>[0-9a-fA-F]{3}|[0-9a-fA-F]{6})"
)


def _normalize_session_action_display_colors(
    colors,
) -> list[str]:

    if isinstance(
        colors,
        (str, bytes),
    ):
        raw_colors = [
            colors,
        ]
    elif isinstance(
        colors,
        (list, tuple, set),
    ):
        raw_colors = list(
            colors
        )
    else:
        raw_colors = []

    normalized_colors = []

    for raw_color in raw_colors:
        match = JIN_COLOR_HEX_RE.fullmatch(
            str(raw_color or "")
        )

        if match is None:
            continue

        color = match.group("hex").lower()

        if len(color) == 3:
            color = "".join(
                char * 2
                for char in color
            )

        normalized_colors.append(
            f"#{color}"
        )

    return normalized_colors


def get_current_action_sequence_turn_id(
    context,
) -> str:

    if context is None:
        return ""

    return str(
        getattr(
            context,
            "runtime_current_sequence_turn_id",
            "",
        )
        or getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()


def get_current_action_sequence_started_at(
    context,
):

    if context is None:
        return None

    sequence_started_at = getattr(
        context,
        "runtime_current_sequence_started_at",
        None,
    )

    if isinstance(
        sequence_started_at,
        (int, float),
    ) and sequence_started_at > 0:
        return float(
            sequence_started_at
        )

    turn_started_at = getattr(
        context,
        "runtime_turn_started_at",
        None,
    )

    if isinstance(
        turn_started_at,
        (int, float),
    ) and turn_started_at > 0:
        return float(
            turn_started_at
        )

    return None


ACTION_DISPLAY_ALIASES = {
    "append_asset_file": "Appended asset file",
    "append_delayed_memory": "Appended delayed memory",
    "append_skill": "Appended skill",
    "append_wildcard_file": "Appended wildcard file",
    "asset_action": "Processed asset action",
    "check_duplicates": "Checked duplicates",
    "save_active_memory": "Saved active memory",
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
    "run_document_reader": "Read document iteratively",
    "run_python_skill": "Ran Python skill",
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
    "run": "Ran",
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

    if action.casefold() == "run_document_reader":
        mode = str(
            result.get(
                "mode",
                "",
            )
            or ""
        ).strip()
        modes = [
            str(item).strip()
            for item in result.get(
                "modes",
                [],
            )
            or []
            if str(item).strip()
        ]
        mode_label = mode or ", ".join(modes)

        if mode_label:
            text = f"{text} - {mode_label}"

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
            colors = _normalize_session_action_display_colors(
                part.get(
                    "colors",
                    [],
                )
            )
            try:
                count = max(
                    0,
                    int(
                        part.get(
                            "count",
                            0,
                        )
                        or 0
                    ),
                )
            except (
                TypeError,
                ValueError,
            ):
                count = 0
        else:
            part_text = str(
                part
                or ""
            ).strip()
            detail = ""
            colors = []
            count = 0

        if not part_text:
            continue

        normalized_part = {
            "text": part_text,
        }

        if detail:
            normalized_part["detail"] = detail

        if colors:
            normalized_part["colors"] = colors

        if count > 1:
            normalized_part["count"] = count

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


def _with_session_action_marker_count(
    part: dict,
    count: int,
) -> dict:

    counted_part = dict(
        part
    )
    normalized_count = max(
        0,
        int(
            count
            or 0
        ),
    )

    if normalized_count > 1:
        counted_part["count"] = normalized_count
    else:
        counted_part.pop(
            "count",
            None,
        )

    return counted_part


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
    count = int(
        normalized_part.get(
            "count",
            0,
        )
        or 0
    )

    if detail:
        text = f"{text} - {detail}"

    return format_runtime_action_count(
        text,
        count,
    )


def format_session_action_display_parts(
    parts,
    *,
    fallback_text: str = "",
) -> str:
    """Render history parts with the shared runtime-action count rules."""

    formatted_parts = [
        formatted_part
        for formatted_part in (
            _format_session_action_display_part(
                part
            )
            for part in (
                _normalize_session_action_display_parts(
                    parts
                )
            )
        )
        if formatted_part
    ]

    if formatted_parts:
        return ", ".join(
            formatted_parts
        )

    return str(
        fallback_text
        or ""
    ).strip()


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

    if normalized_display_parts:
        normalized_text = (
            format_session_action_display_parts(
                normalized_display_parts,
            )
        )

    if not normalized_text:
        return

    item = {
        "text": normalized_text,
        "created_at": time.time(),
    }

    if normalized_display_parts:
        item["parts"] = normalized_display_parts

    runtime_turn_id = get_current_action_sequence_turn_id(
        context
    )

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
        "SAVE_ACTIVE_MEMORY",
        "IDLE",
        "APPEND_DELAYED_MEMORY",
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


PAYLOAD_DISTINCT_SESSION_ACTIONS = {
    "SAVE_ACTIVE_MEMORY",
    "SAVE_DELAYED_MEMORY_CONTENT",
    "APPEND_DELAYED_MEMORY",
}


def _unique_session_action_values(
    values,
) -> list[str]:

    unique_values = []

    for value in values or []:
        normalized_value = str(
            value
            or ""
        ).strip()

        if (
            normalized_value
            and normalized_value not in unique_values
        ):
            unique_values.append(
                normalized_value
            )

    return unique_values


def _build_payload_distinct_session_action_parts(
    group: dict,
) -> list[dict]:

    action_name = group["action_name"]
    payload_groups = {}
    payload_entries = group.get(
        "payload_entries",
        [],
    )

    if not payload_entries:
        payload_entries = [
            {
                "key": payload,
                "display": payload,
            }
            for payload in group["payloads"]
        ]

    for payload_entry in payload_entries:
        payload_key = str(
            payload_entry.get(
                "key",
                "",
            )
            or ""
        ).strip()
        normalized_payload = str(
            payload_entry.get(
                "display",
                "",
            )
            or ""
        ).strip()

        if not payload_key:
            payload_key = normalized_payload

        if (
            not payload_key
            and not normalized_payload
        ):
            continue

        payload_group = payload_groups.setdefault(
            payload_key,
            {
                "count": 0,
                "details": [],
                "fallback": normalized_payload,
            },
        )
        payload_group["count"] += 1

        detail = _build_session_action_marker_detail(
            action_name,
            normalized_payload,
        )
        if detail:
            payload_group["details"].append(
                detail
            )

    if len(payload_groups) <= 1:
        return []

    parts = []

    for payload_key, payload_group in payload_groups.items():
        details = _unique_session_action_values(
            payload_group["details"]
        )
        part = {
            "text": action_name,
        }

        if details:
            part["detail"] = ", ".join(
                details
            )
        else:
            part["detail"] = (
                payload_group["fallback"]
                or payload_key
            )

        parts.append(
            _with_session_action_marker_count(
                part,
                payload_group["count"],
            )
        )

    return parts


def _build_formatted_session_action_marker_parts(
    marker_actions,
) -> list[dict]:

    action_groups = {}

    for marker_action in marker_actions or []:
        marker_count = 1
        marker_payloads = []
        marker_identity_payloads = []
        marker_colors = []

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
            raw_payloads = marker_action.get(
                "payloads",
                [],
            )
            raw_identity_payloads = marker_action.get(
                "raw_payloads",
                [],
            )
            marker_colors = _normalize_session_action_display_colors(
                marker_action.get(
                    "colors",
                    [],
                )
            )

            if isinstance(
                raw_payloads,
                (str, bytes),
            ):
                marker_payloads = [
                    str(raw_payloads),
                ]
            elif isinstance(
                raw_payloads,
                (list, tuple),
            ):
                marker_payloads = [
                    str(payload or "").strip()
                    for payload in raw_payloads
                    if str(payload or "").strip()
                ]

            if isinstance(
                raw_identity_payloads,
                (str, bytes),
            ):
                marker_identity_payloads = [
                    str(raw_identity_payloads),
                ]
            elif isinstance(
                raw_identity_payloads,
                (list, tuple),
            ):
                marker_identity_payloads = [
                    str(payload or "").strip()
                    for payload in raw_identity_payloads
                    if str(payload or "").strip()
                ]
            else:
                marker_identity_payloads = []

            if not marker_payloads:
                normalized_payload = str(
                    action_payload
                    or ""
                ).strip()
                if normalized_payload:
                    marker_payloads = [
                        normalized_payload,
                    ]

            if not marker_identity_payloads:
                marker_identity_payloads = list(
                    marker_payloads
                )

            raw_marker_count = marker_action.get(
                "marker_count",
                0,
            )

            try:
                marker_count = max(
                    1,
                    int(
                        raw_marker_count
                        or 1
                    ),
                )
            except (
                TypeError,
                ValueError,
            ):
                marker_count = 1
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
            normalized_payload = str(
                action_payload
                or ""
            ).strip()
            if normalized_payload:
                marker_payloads = [
                    normalized_payload,
                ]
        else:
            action_name = marker_action

        if not marker_identity_payloads:
            marker_identity_payloads = list(
                marker_payloads
            )

        normalized_name = str(
            action_name
            or ""
        ).strip().upper()

        if not normalized_name:
            continue

        group = action_groups.setdefault(
            normalized_name,
            {
                "action_name": normalized_name,
                "count": 0,
                "payloads": [],
                "payload_entries": [],
                "colors": [],
                "details": [],
            },
        )
        group["count"] += marker_count
        group["payloads"].extend(
            marker_payloads
        )
        group["payload_entries"].extend(
            {
                "key": marker_identity_payloads[index],
                "display": payload,
            }
            for index, payload in enumerate(
                marker_payloads
            )
            if index < len(
                marker_identity_payloads
            )
        )

        if (
            not marker_colors
            and normalized_name == "JIN_COLOR"
        ):
            marker_colors = (
                _normalize_session_action_display_colors(
                    marker_payloads
                )
            )

        if marker_colors:
            group["colors"].extend(
                marker_colors
            )

        for payload in marker_payloads:
            detail = _build_session_action_marker_detail(
                normalized_name,
                payload,
            )
            if detail:
                group["details"].append(
                    detail
                )

    formatted_parts = []

    for group in action_groups.values():
        action_name = group["action_name"]
        payload_distinct_parts = (
            _build_payload_distinct_session_action_parts(
                group
            )
            if action_name in PAYLOAD_DISTINCT_SESSION_ACTIONS
            else []
        )

        if payload_distinct_parts:
            formatted_parts.extend(
                payload_distinct_parts
            )
            continue

        count = group["count"]
        payloads = _unique_session_action_values(
            group["payloads"]
        )
        details = _unique_session_action_values(
            group["details"]
        )
        colors = _normalize_session_action_display_colors(
            group["colors"]
        )

        part = {
            "text": action_name,
        }

        if colors:
            part["colors"] = colors
        else:
            if details:
                part["detail"] = ", ".join(
                    details
                )
            elif (
                action_name in {
                    "APPEND_SKILL",
                    "REMOVE_SKILL",
                }
                and payloads
            ):
                part["text"] = (
                    f"{action_name}: "
                    f"{', '.join(payloads)}"
                )

        formatted_parts.append(
            _with_session_action_marker_count(
                part,
                count,
            )
        )

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


def upsert_session_action_marker_history_since(
    context,
    start_index: int,
    marker_actions,
) -> bool:

    if context is None:
        return False

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

    marker_index = None

    for index in range(
        safe_start_index,
        len(history),
    ):
        item = history[index]

        if not isinstance(
            item,
            dict,
        ):
            continue

        if item.get(
            "runtime_session_action_marker_item"
        ) is True:
            marker_index = index
            break

    previous_item = (
        history[marker_index]
        if marker_index is not None
        else {}
    )
    created_at = previous_item.get(
        "created_at",
        time.time(),
    ) if isinstance(
        previous_item,
        dict,
    ) else time.time()

    item = {
        "text": formatted_marker_names,
        "created_at": created_at,
        "parts": _normalize_session_action_display_parts(
            formatted_marker_parts
        ),
        "runtime_session_action_marker_item": True,
    }

    runtime_turn_id = get_current_action_sequence_turn_id(
        context
    )

    if runtime_turn_id:
        item["runtime_turn_id"] = runtime_turn_id

    if marker_index is None:
        history.append(
            item
        )
    else:
        history[marker_index] = item

    if len(history) > MAX_SESSION_ACTION_HISTORY_ITEMS:
        del history[:-MAX_SESSION_ACTION_HISTORY_ITEMS]

    return True


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

    runtime_turn_id = get_current_action_sequence_turn_id(
        context
    )

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
        "sequence_id": get_current_action_sequence_turn_id(
            context
        ),
        "items": items,
    })


def mark_current_action_sequence(
    context,
) -> str:

    if context is None:
        return ""

    runtime_turn_id = get_current_action_sequence_turn_id(
        context
    )

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
