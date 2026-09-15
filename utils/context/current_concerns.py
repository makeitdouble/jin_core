# Builds the compact live concerns block shown before tool results.
from utils.actions import (
    is_active_memory_record_paused,
)
from utils.attached_files_store import (
    get_file_record,
)
from utils.brain_client_utils import (
    include_pinned_delayed_memory_reports,
)


def _count_pending_active_memory(
    context=None,
) -> int:

    if context is None:
        return 0

    records = getattr(
        context,
        "active_memory_records",
        [],
    )

    if not isinstance(
        records,
        (list, tuple),
    ):
        return 0

    return sum(
        1
        for record in records
        if str(
            record
            or ""
        ).strip()
        and not is_active_memory_record_paused(
            str(
                record
                or ""
            )
        )
    )


def _count_loaded_files(
    context=None,
) -> int:

    if context is None:
        return 0

    file_ids = getattr(
        context,
        "runtime_attached_file_ids",
        [],
    )

    if not isinstance(
        file_ids,
        list,
    ):
        return 0

    loaded_count = 0
    seen_ids = set()

    for raw_file_id in file_ids:
        file_id = str(
            raw_file_id
            or ""
        ).strip().casefold()

        if (
            not file_id
            or file_id in seen_ids
        ):
            continue

        record = get_file_record(
            file_id
        )

        if not record:
            continue

        seen_ids.add(
            file_id
        )
        loaded_count += 1

    from utils.context.files import loaded_project_files
    return loaded_count + sum(1 for _ in loaded_project_files(context))


def _count_loaded_delayed_memory(
    context=None,
) -> int:

    if context is None:
        return 0

    loaded_reports = include_pinned_delayed_memory_reports(
        context
    )

    if not isinstance(
        loaded_reports,
        dict,
    ):
        return 0

    from utils.project_context import pinned_project_reports, project_review_active
    if project_review_active(context):
        allowed_ids = pinned_project_reports(context)
        loaded_reports = {key: report for key, report in loaded_reports.items() if key.casefold() in allowed_ids}

    return sum(
        1
        for report in loaded_reports.values()
        if isinstance(
            report,
            dict,
        )
    )


def _get_previous_context_usage_percent(
    context=None,
) -> float | None:

    if context is None:
        return None

    previous_context_window = getattr(
        context,
        "runtime_previous_answer_context_window",
        {},
    )

    if not isinstance(
        previous_context_window,
        dict,
    ):
        return None

    try:
        used_tokens = int(
            previous_context_window.get(
                "used_tokens",
                0,
            )
            or 0
        )
        context_window = int(
            previous_context_window.get(
                "context_window",
                0,
            )
            or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if context_window <= 0 or used_tokens < 0:
        return None

    return min(
        100.0,
        max(
            0.0,
            (used_tokens / context_window) * 100.0,
        ),
    )


def _format_context_usage_percent(
    usage_percent: float,
) -> str:

    return (
        f"{usage_percent:.1f}"
        .rstrip("0")
        .rstrip(".")
        + "%"
    )

def build_current_concerns_context(
    context=None,
    *,
    has_tool_results: bool = False,
) -> str:

    pending_active_memory_count = (
        _count_pending_active_memory(
            context
        )
    )
    loaded_file_count = _count_loaded_files(
        context
    )
    loaded_delayed_memory_count = (
        _count_loaded_delayed_memory(
            context
        )
    )

    lines = []

    previous_usage_percent = (
        _get_previous_context_usage_percent(
            context
        )
    )

    if (
        previous_usage_percent is not None
        and previous_usage_percent >= 50.0
    ):
        context_usage_line = (
            "Current context window usage is above normal: "
            + _format_context_usage_percent(
                previous_usage_percent
            )
        )
        if has_tool_results:
            context_usage_line += (
                " - check and clean redundant tool results"
            )
        lines.append(
            context_usage_line
        )

    if pending_active_memory_count:
        active_memory_label = (
            "active memory"
            if pending_active_memory_count == 1
            else "active memories"
        )
        lines.append(
            "You have "
            f"{pending_active_memory_count} pending "
            f"{active_memory_label} to resolve."
        )

    loaded_parts = []

    if loaded_file_count:
        file_label = (
            "file"
            if loaded_file_count == 1
            else "files"
        )
        loaded_parts.append(
            f"{loaded_file_count} {file_label}"
        )

    if loaded_delayed_memory_count:
        loaded_parts.append(
            f"{loaded_delayed_memory_count} delayed memory"
        )

    if loaded_parts:
        lines.append(
            "Loaded: "
            + ", ".join(
                loaded_parts
            )
        )

    if not lines:
        return (
            "<CURRENT_CONCERNS>\n"
            "</CURRENT_CONCERNS>"
        )

    return (
        "<CURRENT_CONCERNS>\n"
        + "\n".join(
            lines
        )
        + "\n</CURRENT_CONCERNS>"
    )
