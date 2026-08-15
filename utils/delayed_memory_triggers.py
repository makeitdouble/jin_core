from __future__ import annotations

import re
import unicodedata


RUNTIME_ACTION_LOAD_DELAYED_MEMORY = "load_delayed_memory"
MIN_DELAYED_MEMORY_TRIGGER_CHARS = 2


def normalize_delayed_memory_trigger_text(value) -> str:
    return unicodedata.normalize(
        "NFKC",
        str(value or ""),
    ).casefold().strip()


def delayed_memory_trigger_matches(
    user_text: str,
    tag: str,
) -> bool:
    source = normalize_delayed_memory_trigger_text(
        user_text
    )
    trigger = normalize_delayed_memory_trigger_text(
        tag
    )

    if (
        not source
        or not trigger
        or len(trigger) < MIN_DELAYED_MEMORY_TRIGGER_CHARS
    ):
        return False

    return bool(
        re.search(
            rf"(?<!\w){re.escape(trigger)}(?!\w)",
            source,
            flags=re.UNICODE,
        )
    )


def find_delayed_memory_trigger_tag(
    user_text: str,
    report: dict,
) -> str:
    if not isinstance(report, dict):
        return ""

    tags = report.get(
        "tags",
        [],
    )

    if not isinstance(tags, list):
        tags = [tags]

    for tag in tags:
        cleaned_tag = str(
            tag or ""
        ).strip()

        if delayed_memory_trigger_matches(
            user_text,
            cleaned_tag,
        ):
            return cleaned_tag

    return ""


async def load_delayed_memory_by_tags(
    context,
    user_text: str,
) -> list[dict]:
    """Load matching delayed reports before Brain sees the turn.

    Delayed memory has one tag list: ``tags``. Each tag is both an index tag
    and a lexical trigger hook. Tag-triggered reports use the exact same loaded
    memory state as LOAD_DELAYED_MEMORY, so Brain may later unload them with
    the normal UNLOAD_DELAYED_MEMORY action.
    """

    if not str(user_text or "").strip():
        return []

    from utils.brain_client_utils import (
        get_delayed_memory_reports,
        get_loaded_delayed_memory_reports,
        load_delayed_memory_report,
        set_loaded_delayed_memory_report,
    )

    reports = get_delayed_memory_reports(
        context
    )
    loaded_reports = get_loaded_delayed_memory_reports(
        context
    )
    suppressed_ids = {
        str(item or "").strip().casefold()
        for item in (
            getattr(
                context,
                "runtime_suppressed_delayed_memory_auto_load_ids",
                [],
            )
            or []
        )
        if str(item or "").strip()
    }
    context.runtime_suppressed_delayed_memory_auto_load_ids = []
    loaded_results = []

    for report_id, report in reports.items():
        normalized_report_id = str(
            report_id or ""
        ).strip().casefold()

        if (
            normalized_report_id in loaded_reports
            or normalized_report_id in suppressed_ids
            or not isinstance(report, dict)
        ):
            continue

        trigger_tag = find_delayed_memory_trigger_tag(
            user_text,
            report,
        )

        if not trigger_tag:
            continue

        result = load_delayed_memory_report(
            context,
            normalized_report_id,
        )

        if result.get("ok") is False:
            continue

        if not set_loaded_delayed_memory_report(
            context,
            result,
        ):
            continue

        result = {
            **result,
            "action": RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
            "triggered_by_tag": trigger_tag,
        }
        loaded_results.append(result)

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

        if emit is not None:
            title = str(
                result.get("title", "")
                or normalized_report_id
            ).strip()
            report_payload = result.get(
                "report",
                {},
            )
            event = {
                "type": "runtime_action",
                "action": RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
                "id": normalized_report_id,
                "status": "completed",
                "display_name": "LOADED DELAYED MEMORY",
                "close_tag": False,
                "text": (
                    f"LOADED DELAYED MEMORY: {title} - "
                    f'triggered_by_tag: "{trigger_tag}"'
                ),
                "detail": (
                    f'triggered_by_tag: "{trigger_tag}"'
                ),
                "triggered_by_tag": trigger_tag,
                "delayed_memory_result": result,
                "delayed_memory_report_id": normalized_report_id,
            }

            if isinstance(report_payload, dict):
                event["delayed_memory_report"] = {
                    **report_payload,
                    "id": normalized_report_id,
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
                event["runtime_turn_id"] = runtime_turn_id

            await emit(event)

        logger = getattr(
            context,
            "logger",
            None,
        )
        log_runtime = getattr(
            logger,
            "log_runtime",
            None,
        )
        if log_runtime is not None:
            await log_runtime(
                "[DELAYED MEMORY] loaded by tag: "
                f"{normalized_report_id} <- {trigger_tag}"
            )

    return loaded_results
