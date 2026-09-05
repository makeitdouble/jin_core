import json
import re
from datetime import datetime

from fastapi import WebSocket

from .logger import WebSocketLogger

from runtime.runtime_context import (
    RECENT_MESSAGES_MAX_PAIRS,
    RuntimeContext,
    RuntimeEmitter,
)
from runtime.L1_memory import (
    build_runtime_memory_snapshot,
    parse_runtime_memory_lines,
)
from runtime.L1_memory_pending import (
    restore_pending_l1_update,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
    canonicalize_runtime_memory_key,
    emit_runtime_l1_diff_update,
    emit_runtime_memory_snapshot_refresh,
    rebuild_latest_runtime_memory_snapshot,
    remove_runtime_user_idle_lines,
    strip_runtime_memory_line_metadata,
)
from runtime.telemetry import send_telemetry
from runtime.anonymous_mode import (
    configure_runtime_anonymous_mode,
    ensure_anonymous_session_id,
    websocket_requests_anonymous_mode,
)
from utils.actions import (
    is_active_memory_key,
    is_delayed_memory_report_id,
    normalize_jin_color_payload,
    refresh_active_memory_runtime_metadata,
    remove_active_memory_entries,
)
from utils.chat_log import (
    resume_chat_log_session,
)
from utils.session_actions_history import (
    get_session_action_session_id,
    session_action_belongs_to_session,
)
from utils.attached_files_store import (
    hydrate_attachment_ids,
)
from utils.delayed_memory_file_store import (
    load_delayed_memory_reports_from_files,
    merge_delayed_memory_reports,
    normalize_delayed_memory_reports,
)


MAX_BOOTSTRAP_MEMORY_CHARS = 12000
MAX_BOOTSTRAP_TOOL_RESULT_CHARS = 32000
MAX_RESUME_CLIENT_ID_CHARS = 80
RESUME_CLIENT_ID_RE = re.compile(
    r"[^a-zA-Z0-9_.:-]"
)


RETIRED_RUNTIME_MEMORY_LINE_RE = re.compile(
    r"^\s*(?:-\s*)?l2_pattern_evidence_\d+\s*:",
    re.IGNORECASE,
)


BOOTSTRAP_TOOL_RESULT_KINDS = {
    "active_memory",
    "asset",
    "deep_search",
    "delayed_memory",
    "files",
    "lt",
    "runtime_action",
    "search",
}


ACTIVE_MEMORY_LINE_RE = re.compile(
    r"^\s*active_memory(?:_\d+)?\s*:",
    re.IGNORECASE,
)


def clean_active_memory_records(value) -> list[str]:

    records = []

    if isinstance(value, list):
        candidates = value
    else:
        candidates = str(value or "").splitlines()

    seen = set()

    for candidate in candidates:
        line = clean_bootstrap_memory(
            str(candidate or ""),
            limit=2000,
        )

        if not ACTIVE_MEMORY_LINE_RE.match(line):
            continue

        if line in seen:
            continue

        seen.add(line)
        records.append(line)

    return records


def apply_active_memory_records(
    context,
    message_data: dict,
) -> None:

    records = clean_active_memory_records(
        message_data.get(
            "active_memory_records",
            [],
        )
    )

    context.active_memory_records = records


def active_memory_records_text(context) -> str:

    return "\n".join(
        str(record or "").strip()
        for record in getattr(
            context,
            "active_memory_records",
            [],
        )
        if str(record or "").strip()
    )


def apply_archived_session_continuation_state(
    context,
    message_data: dict,
) -> None:

    source_session_id = clean_bootstrap_memory(
        message_data.get(
            "source_session_id",
            "",
        ),
        limit=80,
    )

    if (
        source_session_id
        and bool(
            message_data.get(
                "archived_session_restore",
                True,
            )
        )
    ):
        # A browser checkpoint with predecessor lineage is enough to resume
        # the conversation by default. Raw-log archive enrichment is optional:
        # later fresh tabs may only have the browser snapshot for their direct
        # predecessor, but they must still get the hidden continuation tick.
        # An explicit archived_session_restore=false remains an opt-out.
        context.runtime_archived_session_id = source_session_id
        context.runtime_session_restore_priming = True

    restore_reasoning_dump = clean_bootstrap_memory(
        message_data.get(
            "restore_reasoning_dump",
            "",
        ),
        limit=32000,
    )
    context.runtime_session_restore_reasoning_dump = (
        restore_reasoning_dump
    )

    restore_lt_fact_ids = []
    for fact_id in message_data.get(
        "restore_lt_fact_ids",
        [],
    ) if isinstance(message_data.get("restore_lt_fact_ids", []), list) else []:
        normalized = clean_bootstrap_memory(
            fact_id,
            limit=80,
        ).upper()
        if normalized and normalized not in restore_lt_fact_ids:
            restore_lt_fact_ids.append(normalized)
    context.runtime_session_restore_lt_fact_ids = restore_lt_fact_ids

    def _clean_restore_metadata(field_name: str) -> list[dict]:
        source = message_data.get(field_name, [])
        if not isinstance(source, list):
            return []
        items = []
        seen = set()
        for raw_item in source:
            if not isinstance(raw_item, dict):
                continue
            item_id = clean_bootstrap_memory(
                raw_item.get("id", ""),
                limit=200,
            )
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            items.append({
                "id": item_id,
                "title": clean_bootstrap_memory(
                    raw_item.get("title", ""),
                    limit=500,
                ) or item_id,
            })
        return items

    context.runtime_session_restore_delayed_memory_metadata = (
        _clean_restore_metadata(
            "restore_delayed_memory_metadata"
        )
    )
    context.runtime_session_restore_attached_file_metadata = (
        _clean_restore_metadata(
            "restore_attached_file_metadata"
        )
    )

    recent_turns = message_data.get(
        "recent_turns",
        [],
    )

    if isinstance(recent_turns, list):
        normalized_turns = []

        for turn in recent_turns:
            if not isinstance(turn, dict):
                continue

            user_text = clean_bootstrap_memory(
                turn.get("user", ""),
                limit=12000,
            )
            jin_text = clean_bootstrap_memory(
                turn.get("jin", ""),
                limit=12000,
            )

            if not user_text and not jin_text:
                continue

            normalized_turn = {
                "user": user_text,
                "jin": jin_text,
            }

            from utils.actions.jin_reaction_utils import normalize_jin_reaction_payload
            reaction = normalize_jin_reaction_payload(turn.get("jin_reaction", ""))
            if reaction:
                normalized_turn["jin_reaction"] = reaction

            reasoning = clean_bootstrap_memory(
                turn.get("reasoning", ""),
                limit=32000,
            )
            if reasoning:
                normalized_turn["reasoning"] = reasoning

            for source_key, target_key in (
                ("user_created_at", "user_created_at"),
                ("jin_created_at", "jin_created_at"),
            ):
                try:
                    timestamp = float(
                        turn.get(source_key, 0)
                        or 0
                    )
                except (TypeError, ValueError):
                    timestamp = 0.0

                if timestamp > 0:
                    normalized_turn[target_key] = timestamp

            normalized_turns.append(normalized_turn)

        context.runtime_recent_turns = normalized_turns[
            -RECENT_MESSAGES_MAX_PAIRS:
        ]

    restored_dialog = clean_bootstrap_memory(
        message_data.get(
            "dialog_context",
            "",
        ),
        limit=48000,
    )

    if restored_dialog:
        context.runtime_restored_session_dialog = restored_dialog
        context.runtime_restored_session_source_id = clean_bootstrap_memory(
            message_data.get(
                "source_session_id",
                "",
            ),
            limit=80,
        )

    previous_reasoning = clean_bootstrap_memory(
        message_data.get(
            "previous_reasoning",
            "",
        ),
        limit=48000,
    )

    if previous_reasoning:
        context.runtime_previous_reasoning_content = (
            previous_reasoning
        )
        context.runtime_previous_reasoning_loop_contents = []

        recent_turns = getattr(
            context,
            "runtime_recent_turns",
            [],
        )
        if (
            isinstance(recent_turns, list)
            and recent_turns
            and isinstance(recent_turns[-1], dict)
            and not str(recent_turns[-1].get("reasoning", "") or "").strip()
        ):
            recent_turns[-1]["reasoning"] = previous_reasoning

    session_actions = message_data.get(
        "session_actions",
        [],
    )

    if isinstance(session_actions, list):
        normalized_actions = []
        current_session_id = get_session_action_session_id(
            context
        )
        restored_previous_session = bool(
            source_session_id
            and current_session_id
            and source_session_id != current_session_id
        )

        for item in session_actions[-200:]:
            if not isinstance(item, dict):
                continue

            # Fresh continuation actions belong to the predecessor session.
            # Accept them here and rebind the final three to this runtime below.
            if (
                not restored_previous_session
                and not session_action_belongs_to_session(
                    item,
                    current_session_id,
                )
            ):
                continue

            text = clean_bootstrap_memory(
                item.get("text", ""),
                limit=2000,
            )

            if not text:
                continue

            normalized_item = {
                "text": text,
            }

            for identity_field, limit in (
                ("id", 200),
                ("event_id", 200),
                ("runtime_turn_id", 120),
            ):
                identity_value = clean_bootstrap_memory(
                    item.get(identity_field, ""),
                    limit=limit,
                )
                if identity_value:
                    normalized_item[identity_field] = identity_value

            item_session_id = clean_bootstrap_memory(
                item.get(
                    "session_id",
                    "",
                ),
                limit=80,
            )
            if item_session_id:
                normalized_item["session_id"] = item_session_id

            try:
                created_at = float(
                    item.get("created_at", 0)
                    or 0
                )
            except (TypeError, ValueError):
                created_at = 0.0

            if created_at > 0:
                normalized_item["created_at"] = created_at

            parts = item.get("parts", [])
            if isinstance(parts, list):
                normalized_parts = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    part_text = clean_bootstrap_memory(
                        part.get("text", ""),
                        limit=600,
                    )
                    if not part_text:
                        continue
                    normalized_part = {
                        "text": part_text,
                    }
                    detail = clean_bootstrap_memory(
                        part.get("detail", ""),
                        limit=1200,
                    )
                    message = clean_bootstrap_memory(
                        part.get("message", ""),
                        limit=2400,
                    )
                    part_id = clean_bootstrap_memory(
                        part.get("id", ""),
                        limit=200,
                    )
                    if detail:
                        normalized_part["detail"] = detail
                    if message:
                        normalized_part["message"] = message
                    if part_id:
                        normalized_part["id"] = part_id

                    raw_colors = part.get("colors", [])
                    if isinstance(raw_colors, (str, bytes)):
                        raw_colors = [raw_colors]
                    if isinstance(raw_colors, list):
                        colors = []
                        for raw_color in raw_colors:
                            color = clean_bootstrap_memory(
                                raw_color,
                                limit=16,
                            ).lower()
                            match = re.fullmatch(
                                r"#?([0-9a-f]{3}|[0-9a-f]{6})",
                                color,
                                re.IGNORECASE,
                            )
                            if match is None:
                                continue
                            color = match.group(1).lower()
                            if len(color) == 3:
                                color = "".join(
                                    char * 2
                                    for char in color
                                )
                            normalized_color = f"#{color}"
                            colors.append(normalized_color)
                        if colors:
                            normalized_part["colors"] = colors

                    normalized_parts.append(normalized_part)

                if normalized_parts:
                    normalized_item["parts"] = normalized_parts

            normalized_actions.append(normalized_item)

        if restored_previous_session:
            # Keep exactly the three latest actions from the direct predecessor.
            # Rebinding makes normal per-session pruning retain them, while new
            # actions from this tab append to the same history afterwards.
            normalized_actions = normalized_actions[-3:]
            for item in normalized_actions:
                item["runtime_session_action_previous_bootstrap"] = True
                if current_session_id:
                    item["session_id"] = current_session_id

        context.runtime_session_action_history = normalized_actions

    restored_jin_color = normalize_jin_color_payload(
        message_data.get("current_jin_color", "")
    )
    if restored_jin_color:
        # Normal next-tab bootstrap owns the live color too. Previously only
        # explicit archived restores staged it, leaving RuntimeContext on the
        # default #1f4f8f even after the action trail was recovered.
        context.jin_color = restored_jin_color

    if bool(
        message_data.get("archived_session_restore")
        and source_session_id
    ):
        stage_session_restore_attached_file_ids(
            context,
            message_data,
        )
    else:
        context.runtime_session_restore_pending_attached_file_ids = []
        attached_file_ids = [
            str(file_id or "").strip()
            for file_id in message_data.get(
                "attached_file_ids",
                [],
            )
            if str(file_id or "").strip()
        ]

        if attached_file_ids:
            attachments = hydrate_attachment_ids(
                attached_file_ids
            )
            context.runtime_attached_file_ids = [
                str(item.get("id", "") or "").strip()
                for item in attachments
                if isinstance(item, dict)
                and str(item.get("id", "") or "").strip()
            ]
            context.runtime_turn_attachments = list(attachments)
            context.runtime_current_sequence_attachments = list(attachments)


def clean_delayed_memory_reports(value) -> dict:

    return normalize_delayed_memory_reports(
        value
    )


def clean_deleted_delayed_memory_report_ids(value) -> list[str]:

    source = value if isinstance(value, list) else [value]
    report_ids = []
    seen = set()

    for item in source:
        report_id = str(
            item
            or ""
        ).strip().casefold()

        if (
            not report_id
            or report_id in seen
            or not is_delayed_memory_report_id(
                report_id
            )
        ):
            continue

        seen.add(
            report_id
        )
        report_ids.append(
            report_id
        )

    return report_ids


def clean_loaded_delayed_memory_report_ids(value) -> list[str]:

    source = value if isinstance(value, list) else [value]
    report_ids = []
    seen = set()

    for item in source:
        report_id = str(
            item
            or ""
        ).strip().casefold()

        if (
            not report_id
            or report_id in seen
            or not is_delayed_memory_report_id(
                report_id
            )
        ):
            continue

        seen.add(report_id)
        report_ids.append(report_id)

    return report_ids


def apply_loaded_delayed_memory_ids(
    context,
    message_data: dict,
) -> list[str]:

    if "loaded_delayed_memory_ids" in message_data:
        raw_ids = message_data.get(
            "loaded_delayed_memory_ids",
            [],
        )
    elif "loaded_memory_ids" in message_data:
        raw_ids = message_data.get(
            "loaded_memory_ids",
            [],
        )
    else:
        return list(
            getattr(
                context,
                "runtime_loaded_delayed_memory_ids",
                [],
            )
            or []
        )

    requested_ids = clean_loaded_delayed_memory_report_ids(
        raw_ids
    )
    reports = getattr(
        context,
        "delayed_memory_reports",
        {},
    )
    reports = reports if isinstance(reports, dict) else {}
    loaded_reports = {}
    loaded_ids = []

    for report_id in requested_ids:
        report = reports.get(report_id)

        if not isinstance(report, dict):
            continue

        loaded_ids.append(report_id)
        loaded_reports[report_id] = {
            **report,
            "id": report_id,
        }

    context.runtime_loaded_delayed_memory = loaded_reports
    context.runtime_loaded_delayed_memory_ids = loaded_ids

    from runtime.LT_memory import (
        refresh_runtime_lt_archived_fact_ids,
    )

    refresh_runtime_lt_archived_fact_ids(
        context
    )

    return loaded_ids




def stage_session_restore_attached_file_ids(
    context,
    message_data: dict,
) -> list[str]:

    raw_ids = message_data.get(
        "attached_file_ids",
        [],
    )
    pending_ids = []
    seen = set()

    for raw_id in raw_ids if isinstance(raw_ids, list) else []:
        file_id = clean_bootstrap_memory(
            raw_id,
            limit=80,
        ).casefold()
        if not file_id or file_id in seen:
            continue
        seen.add(file_id)
        pending_ids.append(file_id)

    context.runtime_session_restore_pending_attached_file_ids = (
        pending_ids
    )

    # The hidden restore turn receives only RESTORED_SESSION_RESOURCES
    # metadata. Do not keep a browser/file-store sync active in the runtime
    # context, otherwise the restore answer can accidentally inherit the
    # archived file payload before the synthetic ATTACH_FILE replay below.
    context.runtime_attached_file_ids = []
    context.runtime_turn_attachments = []
    context.runtime_current_sequence_attachments = []
    context.runtime_current_sequence_attachments_turn_id = ""

    return pending_ids


def stage_session_restore_loaded_delayed_memory_ids(
    context,
    message_data: dict,
) -> list[str]:

    raw_loaded_ids = message_data.get(
        "loaded_delayed_memory_ids",
        message_data.get("loaded_memory_ids", []),
    )
    requested_ids = clean_loaded_delayed_memory_report_ids(
        raw_loaded_ids
    )
    # Keep the archived ids even if a report record has not reached this
    # connection yet. A delayed-memory store sync can arrive before the hidden
    # restore tick; activation after that tick will resolve only ids that exist.
    pending_ids = list(requested_ids)

    context.runtime_session_restore_pending_loaded_memory_ids = pending_ids
    context.runtime_loaded_delayed_memory = {}
    context.runtime_loaded_delayed_memory_ids = []

    from runtime.LT_memory import (
        refresh_runtime_lt_archived_fact_ids,
    )

    refresh_runtime_lt_archived_fact_ids(
        context
    )

    return pending_ids


def get_context_loaded_delayed_memory_ids(
    context,
) -> list[str]:

    loaded_reports = getattr(
        context,
        "runtime_loaded_delayed_memory",
        {},
    )

    if not isinstance(loaded_reports, dict):
        return []

    return clean_loaded_delayed_memory_report_ids(
        list(loaded_reports.keys())
    )


def apply_suppressed_delayed_memory_auto_load_ids(
    context,
    message_data: dict,
) -> list[str]:

    # Accept the old key only as a one-way migration path. Runtime state and
    # outgoing protocol use LOAD terminology exclusively.
    raw_ids = message_data.get(
        "suppressed_delayed_memory_auto_load_ids",
        message_data.get(
            "suppressed_delayed_memory_" + "append_ids",
            getattr(
                context,
                "runtime_suppressed_delayed_memory_auto_load_ids",
                [],
            ),
        ),
    )

    report_ids = clean_loaded_delayed_memory_report_ids(
        raw_ids
    )
    reports = getattr(
        context,
        "delayed_memory_reports",
        {},
    )
    reports = reports if isinstance(reports, dict) else {}
    report_ids = [
        report_id
        for report_id in report_ids
        if report_id in reports
    ]

    context.runtime_suppressed_delayed_memory_auto_load_ids = report_ids

    return report_ids


def apply_delayed_memory_reports(
    context,
    message_data: dict,
) -> list[str]:

    deleted_report_ids = clean_deleted_delayed_memory_report_ids(
        message_data.get(
            "deleted_delayed_memory_report_ids",
            [],
        )
    )

    if (
        "delayed_memory_reports" not in message_data
        and not deleted_report_ids
    ):
        return []

    incoming_reports = clean_delayed_memory_reports(
        message_data.get(
            "delayed_memory_reports",
            {},
        )
    )
    existing_reports = clean_delayed_memory_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
        )
    )

    for report_id in deleted_report_ids:
        existing_reports.pop(
            report_id,
            None,
        )

    context.delayed_memory_reports = {
        **existing_reports,
        **incoming_reports,
    }

    loaded_reports = getattr(
        context,
        "runtime_loaded_delayed_memory",
        None,
    )

    if isinstance(
        loaded_reports,
        dict,
    ):
        for report_id in deleted_report_ids:
            loaded_reports.pop(
                report_id,
                None,
            )

    loaded_ids = getattr(
        context,
        "runtime_loaded_delayed_memory_ids",
        None,
    )

    if isinstance(
        loaded_ids,
        list,
    ):
        deleted_report_id_set = set(
            deleted_report_ids
        )
        loaded_ids[:] = [
            report_id
            for report_id in loaded_ids
            if str(report_id or "").strip().casefold()
            not in deleted_report_id_set
        ]

    from runtime.LT_memory import (
        refresh_runtime_lt_archived_fact_ids,
    )

    refresh_runtime_lt_archived_fact_ids(
        context
    )

    return deleted_report_ids


def hydrate_delayed_memory_reports_from_files(
    context,
) -> None:

    if bool(
        getattr(
            context,
            "runtime_anonymous_mode",
            False,
        )
    ):
        # configure_runtime_anonymous_mode initializes a new room once.
        # A soft reconnect must keep its reports and loaded bodies intact.
        return

    file_reports, warnings = (
        load_delayed_memory_reports_from_files()
    )
    current_reports = clean_delayed_memory_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
        )
    )

    context.delayed_memory_reports = merge_delayed_memory_reports(
        current_reports,
        file_reports,
    )

    from runtime.LT_memory import (
        refresh_runtime_lt_archived_fact_ids,
    )

    refresh_runtime_lt_archived_fact_ids(
        context
    )

    if warnings:
        current_warnings = getattr(
            context,
            "runtime_delayed_memory_file_warnings",
            None,
        )

        if not isinstance(
            current_warnings,
            list,
        ):
            current_warnings = []
            context.runtime_delayed_memory_file_warnings = (
                current_warnings
            )

        current_warnings.extend(
            warning
            for warning in warnings
            if warning not in current_warnings
        )


def remove_runtime_memory_slot_by_key(
        memory: str,
        key: str,
) -> tuple[str, bool]:

    normalized_key = canonicalize_runtime_memory_key(
        str(key or "")
    )

    if not normalized_key:
        return str(memory or "").strip(), False

    kept_lines = []
    removed = False

    for raw_line in str(memory or "").splitlines():
        line = raw_line.strip().lstrip("-").strip()

        if not line:
            continue

        if ":" not in line:
            kept_lines.append(raw_line)
            continue

        line_key, _ = line.split(":", 1)

        if (
                canonicalize_runtime_memory_key(line_key)
                == normalized_key
        ):
            removed = True
            continue

        kept_lines.append(raw_line)

    return "\n".join(
        line.strip()
        for line in kept_lines
        if str(line).strip()
    ).strip(), removed


async def apply_runtime_memory_slot_delete(
        context,
        message_data: dict,
) -> bool:

    key = str(
        message_data.get("key", "")
    ).strip()

    normalized_key = canonicalize_runtime_memory_key(
        key
    )

    if (
            not normalized_key
            or normalized_key == "user_idle"
            or is_active_memory_key(normalized_key)
    ):
        return False

    current_memory = str(
        getattr(
            context,
            "runtime_memory",
            "",
        )
        or ""
    )

    next_memory, removed = remove_runtime_memory_slot_by_key(
        current_memory,
        key,
    )

    if not removed or next_memory == current_memory.strip():
        return False

    context.runtime_memory = next_memory
    context.runtime_memory_stable = next_memory
    context.runtime_memory_updates = int(
        getattr(
            context,
            "runtime_memory_updates",
            0,
        )
        or 0
    ) + 1

    snapshot = rebuild_latest_runtime_memory_snapshot(
        context
    )

    if snapshot is None:
        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )
        context.runtime_memory_snapshots = [snapshot]
        context.runtime_memory_snapshot_index = snapshot.get(
            "index",
            0,
        )

    snapshot["runtime_memory_updates"] = (
        context.runtime_memory_updates
    )
    snapshot["local_runtime_memory_delete"] = True
    snapshot["deleted_runtime_memory_key"] = normalized_key

    await emit_runtime_memory_snapshot_refresh(
        context,
        snapshot,
    )
    await emit_runtime_l1_diff_update(
        context
    )

    await context.logger.log_system(
        f"[RUNTIME MEMORY] slot deleted: {normalized_key}"
    )

    return True


def clean_bootstrap_memory(
    value,
    *,
    limit: int = MAX_BOOTSTRAP_MEMORY_CHARS,
) -> str:

    if not isinstance(
        value,
        str,
    ):
        return ""

    cleaned = value.replace(
        "\x00",
        "",
    ).strip()

    if len(cleaned) <= limit:
        return cleaned

    return cleaned[-limit:].strip()


def clean_bootstrap_runtime_memory(
    value,
    *,
    limit: int = MAX_BOOTSTRAP_MEMORY_CHARS,
) -> str:

    cleaned = remove_active_memory_entries(
        remove_runtime_user_idle_lines(
            clean_bootstrap_memory(
                value,
                limit=limit,
            )
        )
    ).strip()

    return "\n".join(
        line
        for line in cleaned.splitlines()
        if not RETIRED_RUNTIME_MEMORY_LINE_RE.match(line)
    ).strip()


def clean_bootstrap_tool_result_value(value):

    if isinstance(
        value,
        str,
    ):
        return clean_bootstrap_memory(
            value,
            limit=MAX_BOOTSTRAP_TOOL_RESULT_CHARS,
        )

    if isinstance(
        value,
        (dict, list),
    ):
        try:
            encoded = json.dumps(
                value,
                ensure_ascii=False,
                default=str,
            )
            from utils.context.files import project_file_ref
            if (isinstance(value, dict) and project_file_ref(value)
                    and isinstance(value.get("content"), str)
                    and len(value["content"]) <= 24000 and len(encoded) <= 160000):
                return json.loads(encoded)
            if len(encoded) > MAX_BOOTSTRAP_TOOL_RESULT_CHARS:
                encoded = encoded[
                    -MAX_BOOTSTRAP_TOOL_RESULT_CHARS:
                ]
            return json.loads(
                encoded
            )
        except (
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            return clean_bootstrap_memory(
                str(value),
                limit=MAX_BOOTSTRAP_TOOL_RESULT_CHARS,
            )

    if value is None:
        return ""

    return clean_bootstrap_memory(
        str(value),
        limit=MAX_BOOTSTRAP_TOOL_RESULT_CHARS,
    )


def clean_bootstrap_tool_results(value) -> tuple[list[dict], list]:

    if not isinstance(
        value,
        list,
    ):
        return [], []

    results = []
    created_ats = []

    from utils.context.files import select_file_tool_results
    for raw_item in select_file_tool_results(value, 50):
        if not isinstance(
            raw_item,
            dict,
        ):
            continue

        kind = clean_bootstrap_memory(
            raw_item.get("kind", ""),
            limit=80,
        ).casefold()
        if kind not in BOOTSTRAP_TOOL_RESULT_KINDS:
            continue

        result = clean_bootstrap_tool_result_value(
            raw_item.get("result")
        )
        if result is None or result == "":
            continue

        item = {
            "kind": kind,
            "result": result,
        }

        item_id = clean_bootstrap_memory(
            raw_item.get("id", ""),
            limit=200,
        )
        if item_id:
            item["id"] = item_id

        created_at = 0.0
        for key in (
            "created_at",
            "recorded_at",
        ):
            try:
                created_at = float(
                    raw_item.get(key, 0)
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                created_at = 0.0
            if created_at > 0:
                break

        if created_at > 0:
            item["created_at"] = created_at
            created_ats.append(created_at)
        else:
            created_ats.append(None)

        results.append(item)

    return results, created_ats


def apply_bootstrap_tool_results(
    context,
    message_data: dict,
) -> list[dict]:

    if "tool_results" not in message_data:
        return list(
            getattr(
                context,
                "runtime_tool_results",
                [],
            )
            or []
        )

    results, created_ats = clean_bootstrap_tool_results(
        message_data.get(
            "tool_results",
            [],
        )
    )

    context.runtime_tool_results = results
    context.runtime_tool_result_created_ats = created_ats
    context.runtime_tool_results_turn_count = 0
    context.runtime_tool_results_generation = (
        int(
            getattr(
                context,
                "runtime_tool_results_generation",
                0,
            )
            or 0
        )
        + 1
    )

    return results


def reset_archived_runtime_memory_lifecycle(
    memory: str,
) -> str:

    fresh_lines = []

    for raw_line in str(memory or "").splitlines():
        line = raw_line.strip()

        if not line:
            continue

        if ":" not in line:
            fresh_lines.append(
                strip_runtime_memory_line_metadata(line)
            )
            continue

        key, value = line.split(
            ":",
            1,
        )
        cleaned_value = strip_runtime_memory_line_metadata(
            value
        )
        fresh_lines.append(
            f"{key.strip()}: {cleaned_value}".rstrip()
        )

    return "\n".join(
        line for line in fresh_lines if line.strip()
    ).strip()




def normalize_resume_client_id(
    value,
) -> str:

    if not isinstance(
        value,
        str,
    ):
        return ""

    cleaned = RESUME_CLIENT_ID_RE.sub(
        "",
        value,
    ).strip()

    return cleaned[:MAX_RESUME_CLIENT_ID_CHARS]


def is_soft_resume_request(
    websocket: WebSocket,
) -> bool:

    return (
        websocket.query_params.get(
            "resume",
            "",
        ) == "soft"
    )


def get_resume_context_store(
    websocket: WebSocket,
) -> dict:

    store = getattr(
        websocket.app.state,
        "websocket_runtime_contexts",
        None,
    )

    if store is None:
        store = {}
        websocket.app.state.websocket_runtime_contexts = store

    return store


def attach_websocket_to_context(
    context: RuntimeContext,
    websocket: WebSocket,
    logger: WebSocketLogger,
):

    context.websocket = websocket
    context.emitter = RuntimeEmitter(
        websocket
    )
    context.logger = logger
    context.clients = websocket.app.state.clients


def hydrate_attached_files_from_store(context) -> None:
    from utils.attached_files_store import (
        get_pinned_file_ids,
        hydrate_attachment_ids,
    )

    file_ids = get_pinned_file_ids()
    attachments = hydrate_attachment_ids(file_ids)
    context.runtime_attached_file_ids = list(file_ids)
    context.runtime_turn_attachments = list(attachments)
    context.runtime_current_sequence_attachments = list(attachments)


def get_or_create_connection_context(
    websocket: WebSocket,
    logger: WebSocketLogger,
) -> tuple[RuntimeContext, bool]:

    client_id = normalize_resume_client_id(
        websocket.query_params.get(
            "client_id",
            "",
        )
    )

    anonymous_mode_enabled = websocket_requests_anonymous_mode(
        websocket
    )

    if anonymous_mode_enabled and client_id:
        client_id = normalize_resume_client_id(
            ensure_anonymous_session_id(client_id)
        )

    if not client_id:
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(
                websocket
            ),
            logger=logger,
            clients=websocket.app.state.clients,
        )
        configure_runtime_anonymous_mode(
            context,
            anonymous_mode_enabled,
        )
        hydrate_delayed_memory_reports_from_files(
            context
        )
        hydrate_attached_files_from_store(
            context
        )

        return context, False

    store = get_resume_context_store(
        websocket
    )

    existing_context = store.get(
        client_id
    )

    if isinstance(
        existing_context,
        RuntimeContext,
    ):
        # Anonymous rooms may reuse server RAM only for a websocket-level
        # soft reconnect inside the same loaded page. A full page reload
        # must start with a fresh FRAME; the tab-scoped browser stores are
        # synced back separately after the new connection is established.
        if (
            anonymous_mode_enabled
            and not is_soft_resume_request(websocket)
        ):
            store.pop(client_id, None)
            existing_context = None
        else:
            attach_websocket_to_context(
                existing_context,
                websocket,
                logger,
            )
            # A reconnect resumes the current runtime session, not the archived
            # parent that may have bootstrapped it.
            existing_context.session_id = client_id
            configure_runtime_anonymous_mode(
                existing_context,
                anonymous_mode_enabled,
            )
            hydrate_delayed_memory_reports_from_files(
                existing_context
            )
            hydrate_attached_files_from_store(
                existing_context
            )
            return existing_context, True

    context = RuntimeContext(
        websocket=websocket,
        emitter=RuntimeEmitter(
            websocket
        ),
        logger=logger,
        clients=websocket.app.state.clients,
        session_id=client_id,
    )
    configure_runtime_anonymous_mode(
        context,
        anonymous_mode_enabled,
    )
    resume_chat_log_session(
        context
    )
    hydrate_delayed_memory_reports_from_files(
        context
    )
    hydrate_attached_files_from_store(
        context
    )
    restore_pending_l1_update(
        context
    )

    store[client_id] = context

    return context, False


def ensure_initial_runtime_snapshot(
    context: RuntimeContext,
):

    if getattr(
        context,
        "runtime_memory_snapshots",
        [],
    ):
        return

    initial_snapshot = build_runtime_memory_snapshot(
        context,
        context.runtime_memory,
    )

    context.runtime_memory_snapshots.append(
        initial_snapshot
    )

    context.runtime_memory_snapshot_index = 0


def runtime_snapshot_has_user_idle(
    snapshot,
) -> bool:

    if not isinstance(
        snapshot,
        dict,
    ):
        return False

    for line in snapshot.get(
        "lines",
        [],
    ) or []:
        if not isinstance(
            line,
            dict,
        ):
            continue

        key = str(
            line.get(
                "key",
                "",
            )
            or ""
        ).strip().lower()

        if key == "user_idle":
            return True

    return any(
        raw_line.strip().lower().startswith(
            "user_idle:"
        )
        for raw_line in str(
            snapshot.get(
                "raw_memory",
                "",
            )
            or ""
        ).splitlines()
    )


def attach_user_idle_to_initial_runtime_snapshot(
    context,
):

    if getattr(
        context,
        "user_message_count",
        0,
    ) != 0:
        return

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    if not snapshots:
        return

    initial_snapshot = snapshots[0]

    if runtime_snapshot_has_user_idle(
        initial_snapshot
    ):
        return

    raw_memory = str(
        initial_snapshot.get(
            "raw_memory",
            "",
        )
        or ""
    )

    if not is_default_runtime_memory_text(
        raw_memory
    ):
        return

    display_memory = build_runtime_memory_context_text(
        getattr(
            context,
            "runtime_memory",
            "",
        ),
        context,
    )

    if "user_idle:" not in display_memory:
        return

    initial_snapshot["raw_memory"] = display_memory
    initial_snapshot["lines"] = parse_runtime_memory_lines(
        display_memory
    )




def parse_bootstrap_counter(
    value,
) -> int:

    try:
        return max(
            0,
            int(
                value
                or 0
            ),
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0


def runtime_snapshot_has_pheromone_strength(
    snapshot: dict,
) -> bool:

    if not isinstance(
        snapshot,
        dict,
    ):
        return False

    lines = snapshot.get(
        "lines",
        [],
    )

    if not isinstance(
        lines,
        list,
    ):
        return False

    return any(
        isinstance(line, dict)
        and line.get("strength") is not None
        for line in lines
    )


def build_restored_runtime_pheromone_snapshot(
    runtime_snapshot: dict,
    runtime_memory: str,
    *,
    index: int = 0,
) -> dict | None:

    if not isinstance(
        runtime_snapshot,
        dict,
    ):
        return None

    snapshot_memory = clean_bootstrap_runtime_memory(
        runtime_snapshot.get(
            "raw_memory",
            "",
        )
    )

    if snapshot_memory != runtime_memory:
        return None

    lines = [
        dict(line)
        for line in runtime_snapshot.get(
            "lines",
            [],
        )
        if isinstance(
            line,
            dict,
        )
    ]

    if not lines:
        return None

    restored_snapshot = {
        **runtime_snapshot,
        "index": index,
        "raw_memory": runtime_memory,
        "lines": lines,
        "display_source": "restored_runtime_snapshot",
    }

    if runtime_snapshot_has_pheromone_strength(
        runtime_snapshot
    ):
        restored_snapshot[
            "restored_pheromone_strength"
        ] = True

    return restored_snapshot


def resolve_restored_runtime_snapshot_session_id(
    runtime_snapshot: dict,
    source_session_id: str,
) -> str:

    snapshot_session_id = clean_bootstrap_memory(
        runtime_snapshot.get("session_id", "")
        if isinstance(runtime_snapshot, dict)
        else "",
        limit=80,
    )

    if snapshot_session_id:
        return snapshot_session_id

    return clean_bootstrap_memory(
        source_session_id,
        limit=80,
    )


async def emit_current_runtime_memory(
    context,
    *,
    replace_latest: bool = False,
):

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    if snapshots:
        snapshot_index = max(
            0,
            min(
                getattr(
                    context,
                    "runtime_memory_snapshot_index",
                    0,
                ),
                len(snapshots) - 1,
            ),
        )
        snapshot = snapshots[snapshot_index]
    else:
        snapshot = build_runtime_memory_snapshot(
            context,
            context.runtime_memory,
        )

    from runtime.L1_memory_utils import log_runtime_frame_snapshot

    await log_runtime_frame_snapshot(context, snapshot)
    await context.emitter.emit({
        "type": "runtime_memory_update",
        "memory": snapshot.get(
            "raw_memory",
            context.runtime_memory,
        ),
        "updates": getattr(
            context,
            "runtime_memory_updates",
            0,
        ),
        "snapshot": snapshot,
        "snapshots_count": len(
            snapshots
        ) or 1,
        "snapshot_index": snapshot.get(
            "index",
            0,
        ),
        "replace_latest": bool(
            replace_latest
        ),
    })



def is_default_runtime_memory_text(
    value: str,
) -> bool:

    text = str(
        value
        or ""
    ).strip()

    if ":" in text:
        key, candidate = text.split(
            ":",
            1,
        )

        if key.strip().lower() == "note":
            text = candidate.strip()

    normalized = " ".join(
        text.split()
    ).lower()

    return normalized == (
        "this session has just begun."
    ).lower()


ACTIVE_MEMORY_JIN_MESSAGE_COUNTER_RE = re.compile(
    (
        r"\[\s*"
        r"(?P<name>created_jin_message_number|elapsed_jin_message_number)"
        r"\s*:\s*(?P<value>-?\d+)"
        r"\s*\]"
    ),
    re.IGNORECASE,
)


def _parse_runtime_int_value(
    value,
) -> int | None:

    try:
        return int(
            str(value).strip()
        )
    except (TypeError, ValueError):
        return None


def _active_memory_jin_message_floor(
    runtime_memory: str,
) -> int:

    max_message_number = 0

    for line in parse_runtime_memory_lines(
        runtime_memory
    ):
        key = (
            line.get(
                "key",
                "",
            )
            or ""
        ).strip()

        if not is_active_memory_key(
            key
        ):
            continue

        suffix_values = {}

        for match in ACTIVE_MEMORY_JIN_MESSAGE_COUNTER_RE.finditer(
            str(
                line.get(
                    "value",
                    "",
                )
                or ""
            )
        ):
            parsed_value = _parse_runtime_int_value(
                match.group(
                    "value"
                )
            )

            if parsed_value is None:
                continue

            suffix_values[
                match.group(
                    "name"
                ).casefold()
            ] = max(
                0,
                parsed_value,
            )

        created_message_number = suffix_values.get(
            "created_jin_message_number"
        )
        elapsed_message_number = suffix_values.get(
            "elapsed_jin_message_number",
            0,
        )

        if created_message_number is None:
            continue

        max_message_number = max(
            max_message_number,
            created_message_number + elapsed_message_number,
        )

    return max_message_number


def _raise_runtime_counter_floor(
    context,
    field_name: str,
    floor: int,
):

    if floor <= 0:
        return

    current_value = _parse_runtime_int_value(
        getattr(
            context,
            field_name,
            0,
        )
    ) or 0

    if current_value >= floor:
        return

    setattr(
        context,
        field_name,
        floor,
    )


def hydrate_runtime_counters_from_bootstrap_metadata(
    context,
    message_data: dict,
):

    if not isinstance(
        message_data,
        dict,
    ):
        return

    runtime_snapshot = message_data.get(
        "runtime_snapshot",
        {},
    )

    snapshot_data = (
        runtime_snapshot
        if isinstance(
            runtime_snapshot,
            dict,
        )
        else {}
    )

    for field_name in (
        "turn_number",
        "runtime_turn_counter",
        "user_message_count",
        "assistant_message_count",
    ):
        floor = parse_bootstrap_counter(
            message_data.get(
                field_name,
                snapshot_data.get(
                    field_name,
                    0,
                ),
            )
        )

        _raise_runtime_counter_floor(
            context,
            field_name,
            floor,
        )


def hydrate_current_session_counters_from_resume_metadata(
    context,
    message_data: dict,
):

    if not isinstance(
        message_data,
        dict,
    ):
        return

    runtime_snapshot = message_data.get(
        "runtime_snapshot",
        {},
    )
    snapshot_data = (
        runtime_snapshot
        if isinstance(
            runtime_snapshot,
            dict,
        )
        else {}
    )

    for field_name in (
        "current_session_user_message_count",
        "current_session_assistant_message_count",
    ):
        floor = parse_bootstrap_counter(
            message_data.get(
                field_name,
                snapshot_data.get(
                    field_name,
                    0,
                ),
            )
        )
        _raise_runtime_counter_floor(
            context,
            field_name,
            floor,
        )


def hydrate_runtime_counters_from_active_memory(
    context,
    runtime_memory: str,
):

    message_floor = _active_memory_jin_message_floor(
        runtime_memory
    )

    if message_floor <= 0:
        return

    for field_name in (
        "turn_number",
        "assistant_message_count",
        "user_message_count",
    ):
        _raise_runtime_counter_floor(
            context,
            field_name,
            message_floor,
        )


def refresh_restored_active_memory_runtime_metadata(
    context,
    runtime_memory: str,
) -> str:

    runtime_memory = str(
        runtime_memory
        or ""
    ).strip()

    if not runtime_memory:
        return ""

    hydrate_runtime_counters_from_active_memory(
        context,
        runtime_memory,
    )

    return refresh_active_memory_runtime_metadata(
        runtime_memory,
        previous_memory=runtime_memory,
        context=context,
    )


def apply_runtime_resume(
    context,
    message_data: dict,
) -> bool:

    apply_active_memory_records(
        context,
        message_data,
    )
    apply_delayed_memory_reports(
        context,
        message_data,
    )
    apply_bootstrap_tool_results(
        context,
        message_data,
    )

    is_archived_restore = bool(
        message_data.get("archived_session_restore")
        and str(message_data.get("source_session_id", "") or "").strip()
    )

    if is_archived_restore:
        # Do not mark archived delayed reports as loaded before the hidden
        # restoration turn. Otherwise their full bodies can leak into the
        # bootstrap prompt through store sync/race paths. Keep only the ids
        # staged; metadata is injected separately by the restore context builder.
        stage_session_restore_loaded_delayed_memory_ids(
            context,
            message_data,
        )
    else:
        context.runtime_session_restore_pending_loaded_memory_ids = []
        apply_loaded_delayed_memory_ids(
            context,
            message_data,
        )

    apply_archived_session_continuation_state(
        context,
        message_data,
    )

    source_session_id = clean_bootstrap_memory(
        message_data.get(
            "source_session_id",
            message_data.get("previous_session_id", ""),
        ),
        limit=80,
    )
    if source_session_id:
        context.previous_session_id = source_session_id

    runtime_memory = clean_bootstrap_runtime_memory(
        message_data.get(
            "runtime_memory",
            "",
        )
    )

    runtime_snapshot = message_data.get(
        "runtime_snapshot",
        {},
    )

    runtime_memory_is_snapshot_fallback = False

    if (
        not runtime_memory
        and isinstance(
            runtime_snapshot,
            dict,
        )
    ):
        runtime_memory = clean_bootstrap_runtime_memory(
            runtime_snapshot.get(
                "raw_memory",
                "",
            )
        )
        runtime_memory_is_snapshot_fallback = True

    if (
        not runtime_memory
        or is_default_runtime_memory_text(
            runtime_memory
        )
    ):
        return False

    hydrate_runtime_counters_from_bootstrap_metadata(
        context,
        message_data,
    )

    runtime_memory_updates = parse_bootstrap_counter(
        message_data.get(
            "runtime_memory_updates",
            0,
        )
    )

    if runtime_memory_is_snapshot_fallback:
        runtime_memory_updates = 0

    active_memory_text = active_memory_records_text(
        context
    )

    if active_memory_text:
        hydrate_runtime_counters_from_active_memory(
            context,
            active_memory_text,
        )

    runtime_memory = refresh_restored_active_memory_runtime_metadata(
        context,
        runtime_memory,
    )

    # runtime_resume reconnects the same live session. A normal
    # session_bootstrap deliberately does not hydrate these counters, so each
    # fresh runtime session starts CURRENT_SESSION_STATE from zero.
    hydrate_current_session_counters_from_resume_metadata(
        context,
        message_data,
    )

    current_updates = parse_bootstrap_counter(
        getattr(
            context,
            "runtime_memory_updates",
            0,
        )
    )

    current_memory = clean_bootstrap_memory(
        getattr(
            context,
            "runtime_memory",
            "",
        )
    )

    if (
        current_memory
        and not is_default_runtime_memory_text(
            current_memory
        )
        and current_updates >= runtime_memory_updates
    ):
        return False

    restored_pheromone_snapshot = (
        build_restored_runtime_pheromone_snapshot(
            runtime_snapshot,
            runtime_memory,
        )
        if isinstance(
            runtime_snapshot,
            dict,
        )
        else None
    )

    context.runtime_memory = runtime_memory
    context.runtime_memory_stable = runtime_memory
    context.runtime_memory_updates = max(
        current_updates,
        runtime_memory_updates,
    )

    if restored_pheromone_snapshot:
        restored_snapshot = {
            **restored_pheromone_snapshot,
            "index": 0,
            "runtime_memory_updates": context.runtime_memory_updates,
        }
    else:
        restored_snapshot = build_runtime_memory_snapshot(
            context,
            runtime_memory,
        )

    restored_snapshot_session_id = (
        resolve_restored_runtime_snapshot_session_id(
            runtime_snapshot,
            source_session_id,
        )
    )
    if restored_snapshot_session_id:
        restored_snapshot["session_id"] = (
            restored_snapshot_session_id
        )

    restored_snapshot[
        "current_session_user_message_count"
    ] = int(
        getattr(
            context,
            "current_session_user_message_count",
            0,
        )
        or 0
    )
    restored_snapshot[
        "current_session_assistant_message_count"
    ] = int(
        getattr(
            context,
            "current_session_assistant_message_count",
            0,
        )
        or 0
    )

    context.runtime_memory_display_index_offset = parse_bootstrap_counter(
        message_data.get(
            "frame_memory_index",
            runtime_snapshot.get("index", 0)
            if isinstance(runtime_snapshot, dict)
            else 0,
        )
    )
    context.runtime_memory_snapshots = [
        restored_snapshot
    ]
    context.runtime_memory_snapshot_index = 0

    return True


def _bootstrap_iso_timestamp(value) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    try:
        return datetime.fromisoformat(
            text.replace("Z", "+00:00")
        ).timestamp()
    except (TypeError, ValueError):
        return 0.0


def _bootstrap_recent_turns_tail_timestamp(value) -> float:
    if not isinstance(value, list):
        return 0.0

    newest = 0.0
    for turn in value:
        if not isinstance(turn, dict):
            continue
        for field in (
            "jin_created_at",
            "user_created_at",
        ):
            raw = turn.get(field)
            try:
                timestamp = float(raw or 0)
            except (TypeError, ValueError):
                timestamp = _bootstrap_iso_timestamp(raw)
            newest = max(newest, timestamp)
    return newest


def _bootstrap_session_action_identity(item: dict) -> str:
    explicit_id = clean_bootstrap_memory(
        item.get("id", "")
        or item.get("event_id", ""),
        limit=200,
    )
    if explicit_id:
        return "id:" + explicit_id

    runtime_turn_id = clean_bootstrap_memory(
        item.get("runtime_turn_id", ""),
        limit=120,
    )
    part_names = [
        clean_bootstrap_memory(
            part.get("text", ""),
            limit=600,
        ).upper()
        for part in item.get("parts", [])
        if isinstance(part, dict)
        and clean_bootstrap_memory(
            part.get("text", ""),
            limit=600,
        )
    ] if isinstance(item.get("parts"), list) else []

    try:
        created_at = float(item.get("created_at", 0) or 0)
    except (TypeError, ValueError):
        created_at = 0
    text = clean_bootstrap_memory(
        item.get("text", ""),
        limit=2000,
    )
    normalized_parts = []
    for part in item.get("parts", []) if isinstance(item.get("parts"), list) else []:
        if not isinstance(part, dict):
            continue
        normalized_part = {
            "text": clean_bootstrap_memory(
                part.get("text", ""),
                limit=600,
            ).upper(),
            "detail": clean_bootstrap_memory(
                part.get("detail", ""),
                limit=1200,
            ),
            "message": clean_bootstrap_memory(
                part.get("message", ""),
                limit=2400,
            ),
            "id": clean_bootstrap_memory(
                part.get("id", ""),
                limit=200,
            ),
        }
        raw_colors = part.get("colors", [])
        if isinstance(raw_colors, (str, bytes)):
            raw_colors = [raw_colors]
        if isinstance(raw_colors, list):
            normalized_part["colors"] = [
                str(color or "").strip().lower()
                for color in raw_colors
                if str(color or "").strip()
            ]
        normalized_parts.append(normalized_part)

    return json.dumps(
        [created_at, runtime_turn_id, text, part_names, normalized_parts],
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _bootstrap_session_action_timestamp(item: dict) -> float:
    raw = item.get("created_at")
    try:
        return float(raw or 0)
    except (TypeError, ValueError):
        return _bootstrap_iso_timestamp(raw)


def _bootstrap_latest_session_action_color(value) -> str:
    if not isinstance(value, list):
        return ""

    for item in reversed(value):
        if not isinstance(item, dict):
            continue
        parts = item.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in reversed(parts):
            if (
                not isinstance(part, dict)
                or clean_bootstrap_memory(
                    part.get("text", ""),
                    limit=600,
                ).upper() != "JIN_COLOR"
            ):
                continue
            colors = part.get("colors", [])
            if isinstance(colors, (str, bytes)):
                colors = [colors]
            if not isinstance(colors, list):
                continue
            for raw_color in reversed(colors):
                color = normalize_jin_color_payload(raw_color)
                if color:
                    return color

    return ""


def _merge_bootstrap_session_actions(
    browser_actions,
    archive_actions,
) -> list[dict]:
    merged = []
    seen = set()

    for item in [
        *(browser_actions if isinstance(browser_actions, list) else []),
        *(archive_actions if isinstance(archive_actions, list) else []),
    ]:
        if not isinstance(item, dict):
            continue
        identity = _bootstrap_session_action_identity(item)
        if identity in seen:
            continue
        seen.add(identity)
        merged.append(dict(item))

    # Archive-derived actions can be older than the browser checkpoint even
    # when they are appended later during enrichment. Sort by their real
    # timestamp so a stale archive item cannot push the just-completed
    # JIN_COLOR action out of the restored three-item tail.
    merged.sort(key=_bootstrap_session_action_timestamp)
    return merged[-200:]


def enrich_session_bootstrap_from_archive(
    message_data: dict,
    *,
    anonymous_mode: bool | None = None,
) -> dict:

    if not isinstance(message_data, dict):
        return {}

    if bool(anonymous_mode):
        return message_data

    # A delayed-memory session link already carries the rich archived payload.
    # A normal browser bootstrap carries its predecessor session id, so enrich
    # that checkpoint from the server-side raw logs before hydrating JIN.
    if message_data.get("archived_session_restore") is True:
        return message_data

    source_session_id = clean_bootstrap_memory(
        message_data.get(
            "source_session_id",
            "",
        ),
        limit=80,
    )
    if not source_session_id:
        return message_data
    browser_source_session_id = source_session_id

    try:
        from utils.session_restore import (
            build_archived_session_restore_payload,
            find_latest_completed_session_restore_payload,
        )

        archived = build_archived_session_restore_payload(
            source_session_id,
            anonymous_mode=anonymous_mode,
        )
        latest_completed_archive = (
            find_latest_completed_session_restore_payload(
                anonymous_mode=anonymous_mode,
            )
        )
    except Exception:
        archived = None
        latest_completed_archive = None

    # source_session_id comes from browser persistence and can be stale. The
    # raw JSONL dialogue is authoritative: if another session has a strictly
    # newer real USER move, continue from that session immediately. A stopped
    # generation may therefore restore as USER-only; opening a blank tab still
    # does nothing because bootstrap-only sessions contain no real USER row.
    if isinstance(latest_completed_archive, dict):
        latest_source_session_id = clean_bootstrap_memory(
            latest_completed_archive.get(
                "source_session_id",
                "",
            ),
            limit=80,
        )
        latest_dialog_tail_timestamp = (
            _bootstrap_recent_turns_tail_timestamp(
                latest_completed_archive.get(
                    "recent_turns",
                    [],
                )
            )
        )
        requested_dialog_tail_timestamp = (
            _bootstrap_recent_turns_tail_timestamp(
                archived.get("recent_turns", [])
                if isinstance(archived, dict)
                else []
            )
        )
        browser_dialog_tail_timestamp = (
            _bootstrap_recent_turns_tail_timestamp(
                message_data.get("recent_turns", [])
            )
        )

        if (
            latest_source_session_id
            and latest_source_session_id != source_session_id
            and latest_dialog_tail_timestamp
            > max(
                requested_dialog_tail_timestamp,
                browser_dialog_tail_timestamp,
            )
        ):
            archived = latest_completed_archive
            source_session_id = latest_source_session_id

    if not isinstance(archived, dict):
        return message_data

    enriched = dict(message_data)

    archive_reaches_saved_checkpoint = True
    saved_at = clean_bootstrap_memory(
        message_data.get("saved_at", ""),
        limit=80,
    )
    archive_messages = archived.get("messages", [])
    archive_tail_at = clean_bootstrap_memory(
        archived.get("archive_tail_at", ""),
        limit=80,
    )
    if (
        not archive_tail_at
        and isinstance(archive_messages, list)
        and archive_messages
        and isinstance(archive_messages[-1], dict)
    ):
        archive_tail_at = clean_bootstrap_memory(
            archive_messages[-1].get("ts", ""),
            limit=80,
        )

    if saved_at and archive_tail_at:
        checkpoint_at = _bootstrap_iso_timestamp(saved_at)
        archive_tail_timestamp = _bootstrap_iso_timestamp(archive_tail_at)
        if checkpoint_at and archive_tail_timestamp:
            # Keep the pre-existing whole-second tolerance: browser checkpoints
            # often carry sub-second precision while JSONL rows are second-only.
            archive_reaches_saved_checkpoint = (
                int(archive_tail_timestamp) >= int(checkpoint_at)
            )

    # Dialogue freshness is independent from runtime-snapshot freshness. A fresh
    # tab clone advances saved_at even when it contains no newer conversation,
    # so comparing a chat-log tail to saved_at can pin bootstrap to an old turn
    # forever. Compare chat tail to chat tail instead.
    browser_recent_turns = message_data.get("recent_turns", [])
    archived_recent_turns = archived.get("recent_turns", [])
    browser_dialog_tail_timestamp = (
        _bootstrap_recent_turns_tail_timestamp(browser_recent_turns)
    )
    archive_dialog_tail_timestamp = (
        _bootstrap_recent_turns_tail_timestamp(archived_recent_turns)
    )

    if not archive_dialog_tail_timestamp and archive_tail_at:
        archive_dialog_tail_timestamp = _bootstrap_iso_timestamp(
            archive_tail_at
        )

    archive_reaches_dialog_checkpoint = False
    browser_has_recent_turns = bool(
        isinstance(browser_recent_turns, list)
        and browser_recent_turns
    )
    archive_has_recent_turns = bool(
        isinstance(archived_recent_turns, list)
        and archived_recent_turns
    )

    if (
        not browser_has_recent_turns
        and (
            archive_has_recent_turns
            or archive_dialog_tail_timestamp
            or clean_bootstrap_memory(
                archived.get("dialog_context", "")
            )
        )
    ):
        # Legacy browser checkpoints may have no per-turn timestamps at all.
        # If the browser has no dialogue tail, the source session's raw log is
        # the only authoritative dialogue source regardless of runtime saved_at.
        archive_reaches_dialog_checkpoint = True
    elif archive_dialog_tail_timestamp and browser_dialog_tail_timestamp:
        archive_reaches_dialog_checkpoint = (
            int(archive_dialog_tail_timestamp)
            >= int(browser_dialog_tail_timestamp)
        )

    if archive_reaches_dialog_checkpoint:
        for field in (
            "dialog_context",
            "recent_turns",
            "previous_reasoning",
            "restore_reasoning_dump",
            "restore_lt_fact_ids",
            "runtime_turn_counter",
            "turn_number",
            "user_message_count",
            "assistant_message_count",
        ):
            value = archived.get(field)
            if value not in (None, "", [], {}):
                enriched[field] = value

    # Runtime/resource checkpoint freshness still uses saved_at. Those fields
    # are not safe to replace from an older archive just because its dialogue
    # tail is newer than the browser's copied chat tail.
    if archive_reaches_saved_checkpoint:
        for field in (
            "restore_delayed_memory_metadata",
            "restore_attached_file_metadata",
            "attached_file_ids",
        ):
            value = archived.get(field)
            if value not in (None, "", [], {}):
                enriched[field] = value

    # The common checkpoint owns all actions committed before its saved_at.
    # Raw JSONL contributes only a newer tail (or the whole fallback when the
    # checkpoint has no actions), so the same marker cannot appear once from
    # localStorage and again from the file log.
    source_changed = source_session_id != browser_source_session_id
    browser_actions = (
        []
        if source_changed
        else enriched.get("session_actions", [])
    )
    archive_actions = archived.get("session_actions", [])
    if (
        browser_actions
        and isinstance(archive_actions, list)
        and not source_changed
    ):
        checkpoint_timestamp = _bootstrap_iso_timestamp(
            message_data.get("saved_at", "")
        )
        if checkpoint_timestamp:
            archive_actions = [
                item
                for item in archive_actions
                if isinstance(item, dict)
                and _bootstrap_session_action_timestamp(item)
                > checkpoint_timestamp
            ]
    if archive_actions not in (None, "", [], {}):
        enriched["session_actions"] = (
            _merge_bootstrap_session_actions(
                browser_actions,
                archive_actions,
            )
        )

    browser_color = (
        ""
        if source_changed
        else normalize_jin_color_payload(
            enriched.get("current_jin_color", "")
        )
    )
    if browser_color:
        # The browser checkpoint is updated in the same tick that JIN_COLOR is
        # applied. Session actions remain history; they only recover color for
        # checkpoints created before that field-local write existed.
        enriched["current_jin_color"] = browser_color
    else:
        archived_color = normalize_jin_color_payload(
            archived.get("current_jin_color", "")
        )
        action_color = _bootstrap_latest_session_action_color(
            enriched.get("session_actions", [])
        )

        if action_color:
            enriched["current_jin_color"] = action_color
        elif archived_color:
            enriched["current_jin_color"] = archived_color

    # Browser persistence is the exact checkpoint when available. Fall back
    # to archived PREVIOUS_RUNTIME_STATE/resources only when the browser half
    # is absent.
    exact_collection_fields = {
        "tool_results",
    }

    for field in (
        "runtime_memory",
        "runtime_memory_updates",
        "loaded_memory_ids",
        "active_memory_records",
        "tool_results",
    ):
        # CLEAN_TOOL_RESULTS deliberately persists tool_results=[]; that empty
        # collection is authoritative and must not be repopulated from an older
        # archived prompt on the next-tab boot. Other restore collections keep
        # their legacy fallback semantics.
        if field in exact_collection_fields:
            browser_has_value = (
                field in enriched
                and enriched.get(field) is not None
            )
        else:
            browser_has_value = (
                enriched.get(field) not in (None, "", [], {})
            )

        if browser_has_value:
            continue

        value = archived.get(field)
        if value not in (None, "", [], {}):
            enriched[field] = value

    # The browser checkpoint is authoritative for ordinary tool results, but
    # an UPDATE_LT_FACTS response can finish after that checkpoint was written.
    # Replay only those newer append-only L-T results. A CLEAN_TOOL_RESULTS
    # timestamp remains a hard lower bound so cleared results never resurrect.
    browser_tool_results = message_data.get("tool_results")
    if isinstance(browser_tool_results, list):
        saved_at_timestamp = _bootstrap_iso_timestamp(saved_at)
        cleared_at_timestamp = _bootstrap_iso_timestamp(
            message_data.get("tool_results_cleared_at", "")
        )
        tool_result_cutoff = max(
            saved_at_timestamp,
            cleared_at_timestamp,
        )
        archived_tool_results = archived.get("tool_results", [])
        if tool_result_cutoff > 0 and isinstance(archived_tool_results, list):
            late_lt_results = []
            for item in archived_tool_results:
                if not isinstance(item, dict):
                    continue
                if str(item.get("kind", "") or "").strip().casefold() != "lt":
                    continue
                try:
                    created_at = float(item.get("created_at", 0) or 0)
                except (TypeError, ValueError):
                    created_at = 0.0
                if created_at <= tool_result_cutoff:
                    continue
                late_lt_results.append(item)

            if late_lt_results:
                merged_tool_results = list(browser_tool_results)
                keyed_indexes = {}
                for index, item in enumerate(merged_tool_results):
                    if not isinstance(item, dict):
                        continue
                    kind = str(item.get("kind", "") or "").strip().casefold()
                    result_id = str(item.get("id", "") or "").strip()
                    if kind and result_id:
                        keyed_indexes[(kind, result_id)] = index

                for item in late_lt_results:
                    result_id = str(item.get("id", "") or "").strip()
                    key = ("lt", result_id) if result_id else None
                    if key is not None and key in keyed_indexes:
                        merged_tool_results[keyed_indexes[key]] = item
                    else:
                        if key is not None:
                            keyed_indexes[key] = len(merged_tool_results)
                        merged_tool_results.append(item)

                from utils.context.files import select_file_tool_results
                enriched["tool_results"] = select_file_tool_results(merged_tool_results, 50)

    enriched["source_session_id"] = source_session_id
    if archived.get("source_session_date"):
        enriched["source_session_date"] = archived["source_session_date"]
    # This is still an archived-session restore even when the raw log tail is
    # stale. The freshness guard above controls only which archived fields may
    # be mixed into the browser checkpoint; restore priming must remain active.
    enriched["archived_session_restore"] = True
    return enriched


def build_session_bootstrap_chat_tail(
    context,
) -> list[dict]:

    turns = getattr(
        context,
        "runtime_recent_turns",
        [],
    )
    if not isinstance(turns, list):
        return []

    committed_turns = []
    for turn in turns:
        if not isinstance(turn, dict):
            continue

        user_text = clean_bootstrap_memory(
            turn.get("user", ""),
            limit=12000,
        )
        attachment_context_marker = "\n\nAttached context:\n"
        if attachment_context_marker in user_text:
            user_text = user_text.split(
                attachment_context_marker,
                1,
            )[0].rstrip()

        jin_text = clean_bootstrap_memory(
            turn.get("jin", ""),
            limit=12000,
        )
        # runtime_recent_turns contains the latest real USER moves. A stopped
        # turn or action-only completion can legitimately have no visible JIN
        # text; its USER bubble still belongs to the predecessor chat tail.
        if not user_text:
            continue

        item = {
            "user": user_text,
            "jin": jin_text,
        }
        from utils.actions.jin_reaction_utils import normalize_jin_reaction_payload
        reaction = normalize_jin_reaction_payload(turn.get("jin_reaction", ""))
        if reaction:
            item["jin_reaction"] = reaction
        reasoning = clean_bootstrap_memory(
            turn.get("reasoning", ""),
            limit=32000,
        )
        reasoning_marker = "--- REASONING ---"
        if reasoning_marker in reasoning:
            reasoning = reasoning.split(
                reasoning_marker,
                1,
            )[1].strip()
        if reasoning:
            item["reasoning"] = reasoning

        for key in (
            "user_created_at",
            "jin_created_at",
        ):
            try:
                created_at = float(turn.get(key, 0) or 0)
            except (TypeError, ValueError):
                created_at = 0.0
            if created_at > 0:
                item[key] = created_at

        committed_turns.append(item)

    return committed_turns[-RECENT_MESSAGES_MAX_PAIRS:]


def apply_session_bootstrap(
    context,
    message_data: dict,
) -> bool:

    message_data = enrich_session_bootstrap_from_archive(
        message_data,
        anonymous_mode=bool(
            getattr(
                context,
                "runtime_anonymous_mode",
                False,
            )
        ),
    )

    apply_active_memory_records(
        context,
        message_data,
    )
    apply_delayed_memory_reports(
        context,
        message_data,
    )
    apply_bootstrap_tool_results(
        context,
        message_data,
    )

    is_archived_restore = bool(
        message_data.get("archived_session_restore")
        and str(message_data.get("source_session_id", "") or "").strip()
    )

    if is_archived_restore:
        # Do not mark archived delayed reports as loaded before the hidden
        # restoration turn. Otherwise their full bodies can leak into the
        # bootstrap prompt through store sync/race paths. Keep only the ids
        # staged; metadata is injected separately by the restore context builder.
        stage_session_restore_loaded_delayed_memory_ids(
            context,
            message_data,
        )
    else:
        context.runtime_session_restore_pending_loaded_memory_ids = []
        apply_loaded_delayed_memory_ids(
            context,
            message_data,
        )

    apply_archived_session_continuation_state(
        context,
        message_data,
    )

    source_session_id = clean_bootstrap_memory(
        message_data.get(
            "source_session_id",
            message_data.get("previous_session_id", ""),
        ),
        limit=80,
    )
    if source_session_id:
        context.previous_session_id = source_session_id

    runtime_memory = clean_bootstrap_runtime_memory(
        message_data.get(
            "runtime_memory",
            "",
        )
    )

    runtime_snapshot = message_data.get(
        "runtime_snapshot",
        {},
    )
    # Track whether runtime_memory was inferred from runtime_snapshot.raw_memory
    # rather than being sent explicitly by the client.
    runtime_memory_is_snapshot_fallback = False

    if (
        not runtime_memory
        and isinstance(
            runtime_snapshot,
            dict,
        )
    ):
        runtime_memory = clean_bootstrap_runtime_memory(
            runtime_snapshot.get(
                "raw_memory",
                "",
            )
        )
        runtime_memory_is_snapshot_fallback = True

    if is_archived_restore and runtime_memory:
        # The persisted runtime snapshot owns the historical L1 lifecycle.
        # Prefer its canonical raw_memory so snapshot timestamp + per-line
        # created_at/updated_at survive the restore instead of being rebased to
        # the current boot time.
        snapshot_memory = (
            clean_bootstrap_runtime_memory(
                runtime_snapshot.get(
                    "raw_memory",
                    "",
                )
            )
            if isinstance(runtime_snapshot, dict)
            else ""
        )

        if snapshot_memory:
            runtime_memory = snapshot_memory
        else:
            # Log-only legacy archives have relative presentation suffixes but
            # no absolute snapshot metadata. Keep the semantic values clean; in
            # that fallback case there is simply no exact lifecycle to restore.
            runtime_memory = reset_archived_runtime_memory_lifecycle(
                runtime_memory
            )

    has_bootstrap_content = bool(
        runtime_memory
    )

    if has_bootstrap_content:
        hydrate_runtime_counters_from_bootstrap_metadata(
            context,
            message_data,
        )

    runtime_memory_updates = parse_bootstrap_counter(
        message_data.get(
            "runtime_memory_updates",
            0,
        )
    )

    if runtime_memory_is_snapshot_fallback:
        runtime_memory_updates = 0

    active_memory_text = active_memory_records_text(
        context
    )

    if active_memory_text:
        hydrate_runtime_counters_from_active_memory(
            context,
            active_memory_text,
        )

    if runtime_memory:
        runtime_memory = refresh_restored_active_memory_runtime_metadata(
            context,
            runtime_memory,
        )

    if runtime_memory:
        restored_pheromone_snapshot = (
            build_restored_runtime_pheromone_snapshot(
                runtime_snapshot,
                runtime_memory,
            )
            if isinstance(runtime_snapshot, dict)
            else None
        )

        # Bootstrap should replace the initial/default runtime page, not append
        # extra pages. If the saved snapshot matches runtime_memory, keep that
        # exact snapshot as the restored baseline so lifecycle timestamps, diff
        # state, and pheromone strength all continue from the saved point.
        context.runtime_memory_snapshots = []
        context.runtime_memory_snapshot_index = 0

        context.runtime_memory = runtime_memory
        context.runtime_memory_stable = runtime_memory

        try:
            context.runtime_memory_updates = max(
                runtime_memory_updates,
                getattr(
                    context,
                    "runtime_memory_updates",
                    0,
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

        if restored_pheromone_snapshot:
            restored_snapshot = {
                **restored_pheromone_snapshot,
                "index": 0,
                "runtime_memory_updates": getattr(
                    context,
                    "runtime_memory_updates",
                    runtime_memory_updates,
                ),
            }
        else:
            restored_snapshot = build_runtime_memory_snapshot(
                context,
                context.runtime_memory,
            )

        restored_snapshot_session_id = (
            resolve_restored_runtime_snapshot_session_id(
                runtime_snapshot,
                source_session_id,
            )
        )
        if restored_snapshot_session_id:
            restored_snapshot["session_id"] = (
                restored_snapshot_session_id
            )

        # The FRAME may come from the predecessor, but visible message counts
        # belong to the new live session and must not inherit that history.
        restored_snapshot[
            "current_session_user_message_count"
        ] = int(
            getattr(
                context,
                "current_session_user_message_count",
                0,
            )
            or 0
        )
        restored_snapshot[
            "current_session_assistant_message_count"
        ] = int(
            getattr(
                context,
                "current_session_assistant_message_count",
                0,
            )
            or 0
        )

        context.runtime_memory_display_index_offset = parse_bootstrap_counter(
            message_data.get(
                "frame_memory_index",
                1,
            )
        )
        context.runtime_memory_snapshots.append(
            restored_snapshot
        )
        context.runtime_memory_snapshot_index = 0

    return bool(
        runtime_memory
        or source_session_id
        or getattr(context, "runtime_session_action_history", [])
        or getattr(context, "runtime_recent_turns", [])
    )


# ---------------------------------------------------------
# CONNECTION SETUP
# ---------------------------------------------------------

async def emit_delayed_memory_store_snapshot(
    context,
) -> None:

    reports = clean_delayed_memory_reports(
        getattr(
            context,
            "delayed_memory_reports",
            {},
        )
    )

    await context.emitter.emit({
        "type": "delayed_memory_store_snapshot",
        "delayed_memory_reports": reports,
        "loaded_delayed_memory_ids": (
            get_context_loaded_delayed_memory_ids(
                context
            )
        ),
    })


async def initialize_connection(
    context,
    *,
    skip_initial_runtime_state: bool = False,
):

    await context.websocket.accept()

    await send_telemetry(
        context
    )

    file_warnings = list(
        getattr(
            context,
            "runtime_delayed_memory_file_warnings",
            [],
        )
        or []
    )
    context.runtime_delayed_memory_file_warnings = []

    for warning in file_warnings:
        await context.logger.log_system(
            "[DELAYED MEMORY] " + str(warning)
        )

    await emit_delayed_memory_store_snapshot(
        context
    )

    from runtime.LT_memory import (
        emit_lt_memory_update,
    )

    await emit_lt_memory_update(
        context,
        change={
            "source": "file_bootstrap",
        },
    )

    if skip_initial_runtime_state:
        await context.logger.log_system(
            "[WS] soft reconnect: initial runtime state skipped"
        )
        return

    await emit_current_runtime_memory(
        context
    )

    await emit_runtime_l1_diff_update(
        context
    )


# ---------------------------------------------------------
# RECEIVE MESSAGE
# ---------------------------------------------------------
