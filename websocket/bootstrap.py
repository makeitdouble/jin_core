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
    websocket_requests_anonymous_mode,
)
from utils.actions import (
    is_active_memory_key,
    is_delayed_memory_report_id,
    normalize_jin_speed_value,
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


def apply_metabolism_bootstrap_state(
    context,
    message_data: dict,
) -> None:

    from runtime.metabolism import (
        METABOLISM_DEFAULT_LEVELS,
        normalize_metabolism_associations,
        normalize_metabolism_levels,
    )

    raw_levels = message_data.get(
        "metabolism_levels",
        None,
    )

    if isinstance(raw_levels, dict):
        context.runtime_metabolism_levels = normalize_metabolism_levels(
            raw_levels
        )
    else:
        context.runtime_metabolism_levels = normalize_metabolism_levels(
            getattr(
                context,
                "runtime_metabolism_levels",
                METABOLISM_DEFAULT_LEVELS,
            )
        )

    try:
        updated_at = float(
            message_data.get(
                "metabolism_updated_at",
                0.0,
            )
            or 0.0
        )
    except (TypeError, ValueError):
        updated_at = 0.0

    context.runtime_metabolism_last_tick_at = max(0.0, updated_at)
    context.runtime_metabolism_instruction = str(
        message_data.get(
            "metabolism_instruction",
            getattr(context, "runtime_metabolism_instruction", ""),
        )
        or ""
    )[:900].strip()
    context.runtime_metabolism_associations = normalize_metabolism_associations(
        message_data.get(
            "metabolism_associations",
            getattr(context, "runtime_metabolism_associations", []),
        )
    )
    context.runtime_metabolism_last_committed_l1_id = str(
        message_data.get(
            "metabolism_last_committed_l1_id",
            getattr(context, "runtime_metabolism_last_committed_l1_id", ""),
        )
        or ""
    ).strip()


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

    restore_l4_fact_ids = []
    for fact_id in message_data.get(
        "restore_l4_fact_ids",
        [],
    ) if isinstance(message_data.get("restore_l4_fact_ids", []), list) else []:
        normalized = clean_bootstrap_memory(
            fact_id,
            limit=80,
        ).upper()
        if normalized and normalized not in restore_l4_fact_ids:
            restore_l4_fact_ids.append(normalized)
    context.runtime_session_restore_l4_fact_ids = restore_l4_fact_ids

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

    if bool(
        message_data.get("archived_session_restore")
        and source_session_id
    ):
        stage_session_restore_attached_file_ids(
            context,
            message_data,
        )
        stage_session_restore_visual_state(
            context,
            message_data,
        )
    else:
        context.runtime_session_restore_pending_attached_file_ids = []
        context.runtime_session_restore_pending_jin_color = ""
        context.runtime_session_restore_pending_jin_size = None
        context.runtime_session_restore_pending_jin_position = None
        context.runtime_session_restore_pending_jin_speed = None
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

    from runtime.L4_memory import (
        refresh_runtime_l4_archived_fact_ids,
    )

    refresh_runtime_l4_archived_fact_ids(
        context
    )

    return loaded_ids




def stage_session_restore_visual_state(
    context,
    message_data: dict,
) -> None:

    color = clean_bootstrap_memory(
        message_data.get("current_jin_color", ""),
        limit=32,
    ).strip()
    size = message_data.get("current_jin_size")
    position = message_data.get("current_jin_position")
    speed = normalize_jin_speed_value(
        message_data.get("current_jin_speed")
    )

    context.runtime_session_restore_pending_jin_color = color
    context.runtime_session_restore_pending_jin_size = (
        dict(size)
        if isinstance(size, dict)
        else None
    )
    context.runtime_session_restore_pending_jin_position = (
        dict(position)
        if isinstance(position, dict)
        else None
    )
    context.runtime_session_restore_pending_jin_speed = speed

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

    from runtime.L4_memory import (
        refresh_runtime_l4_archived_fact_ids,
    )

    refresh_runtime_l4_archived_fact_ids(
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

    from runtime.L4_memory import (
        refresh_runtime_l4_archived_fact_ids,
    )

    refresh_runtime_l4_archived_fact_ids(
        context
    )

    return deleted_report_ids


def hydrate_delayed_memory_reports_from_files(
    context,
) -> None:

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

    from runtime.L4_memory import (
        refresh_runtime_l4_archived_fact_ids,
    )

    refresh_runtime_l4_archived_fact_ids(
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

    for raw_item in value[-50:]:
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

    if not client_id:
        context = RuntimeContext(
            websocket=websocket,
            emitter=RuntimeEmitter(
                websocket
            ),
            logger=logger,
            clients=websocket.app.state.clients,
        )
        hydrate_delayed_memory_reports_from_files(
            context
        )
        hydrate_attached_files_from_store(
            context
        )
        configure_runtime_anonymous_mode(
            context,
            anonymous_mode_enabled,
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
        attach_websocket_to_context(
            existing_context,
            websocket,
            logger,
        )
        # A reconnect resumes the current runtime session, not the archived
        # parent that may have bootstrapped it.
        existing_context.session_id = client_id
        hydrate_delayed_memory_reports_from_files(
            existing_context
        )
        hydrate_attached_files_from_store(
            existing_context
        )
        configure_runtime_anonymous_mode(
            existing_context,
            anonymous_mode_enabled,
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
    resume_chat_log_session(
        context
    )
    hydrate_delayed_memory_reports_from_files(
        context
    )
    hydrate_attached_files_from_store(
        context
    )
    configure_runtime_anonymous_mode(
        context,
        anonymous_mode_enabled,
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
        "this session has just begun. "
        "you have no history with the user yet."
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
    apply_metabolism_bootstrap_state(
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

    context.runtime_memory_snapshots = [
        restored_snapshot
    ]
    context.runtime_memory_snapshot_index = 0

    return True


def enrich_session_bootstrap_from_archive(
    message_data: dict,
) -> dict:

    if not isinstance(message_data, dict):
        return {}

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

    try:
        from utils.session_restore import (
            build_archived_session_restore_payload,
        )

        archived = build_archived_session_restore_payload(
            source_session_id
        )
    except Exception:
        archived = None

    if not isinstance(archived, dict):
        return message_data

    enriched = dict(message_data)

    archive_reaches_saved_checkpoint = True
    saved_at = clean_bootstrap_memory(
        message_data.get("saved_at", ""),
        limit=80,
    )
    archive_messages = archived.get("messages", [])

    if saved_at and isinstance(archive_messages, list) and archive_messages:
        archive_tail_at = str(
            archive_messages[-1].get("ts", "")
            if isinstance(archive_messages[-1], dict)
            else ""
        ).strip()
        if archive_tail_at:
            try:
                checkpoint_at = datetime.fromisoformat(
                    saved_at.replace("Z", "+00:00")
                ).replace(microsecond=0)
                archive_tail_at = datetime.fromisoformat(
                    archive_tail_at.replace("Z", "+00:00")
                ).replace(microsecond=0)
                archive_reaches_saved_checkpoint = (
                    archive_tail_at >= checkpoint_at
                )
            except (TypeError, ValueError):
                pass

    # Never mix a newer browser save with an older raw log tail.
    if archive_reaches_saved_checkpoint:
        for field in (
            "dialog_context",
            "recent_turns",
            "previous_reasoning",
            "restore_reasoning_dump",
            "restore_l4_fact_ids",
            "restore_delayed_memory_metadata",
            "restore_attached_file_metadata",
            "session_actions",
            "runtime_turn_counter",
            "turn_number",
            "user_message_count",
            "assistant_message_count",
            "attached_file_ids",
        ):
            value = archived.get(field)
            if value not in (None, "", [], {}):
                enriched[field] = value

    # Browser persistence is the exact checkpoint when available. Fall back
    # to archived PREVIOUS_RUNTIME_STATE/resources only when the browser half
    # is absent.
    for field in (
        "runtime_memory",
        "runtime_memory_updates",
        "loaded_memory_ids",
        "active_memory_records",
        "tool_results",
    ):
        if enriched.get(field) in (None, "", [], {}):
            value = archived.get(field)
            if value not in (None, "", [], {}):
                enriched[field] = value

    enriched["source_session_id"] = source_session_id
    if archived.get("source_session_date"):
        enriched["source_session_date"] = archived["source_session_date"]
    # This is still an archived-session restore even when the raw log tail is
    # stale. The freshness guard above controls only which archived fields may
    # be mixed into the browser checkpoint; restore priming must remain active.
    enriched["archived_session_restore"] = True
    return enriched


def apply_session_bootstrap(
    context,
    message_data: dict,
) -> bool:

    message_data = enrich_session_bootstrap_from_archive(
        message_data
    )

    apply_active_memory_records(
        context,
        message_data,
    )
    apply_metabolism_bootstrap_state(
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

        context.runtime_memory_snapshots.append(
            restored_snapshot
        )
        context.runtime_memory_snapshot_index = 0

    return bool(
        runtime_memory
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

    from runtime.L4_memory import (
        emit_l4_memory_update,
    )

    await emit_l4_memory_update(
        context,
        change={
            "source": "file_bootstrap",
        },
    )

    # Chemistry is runtime state, not a page artifact. Re-emit it immediately
    # on connect/reconnect so the avatar never falls back to browser defaults.
    from runtime.metabolism import emit_metabolism_state

    await emit_metabolism_state(
        context
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
