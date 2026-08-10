from copy import deepcopy

from contracts.rules_assembler import (
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.actions import build_runtime_action_id
from utils.session_actions_history import record_session_action_history
from utils.tool_results import (
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    record_runtime_tool_result,
)


async def apply_delayed_memory_actions(
    context,
    *,
    load_delayed_memory_actions,
    unload_delayed_memory_actions,
    update_delayed_memory_actions,
    log_runtime,
):
    from utils.brain_client_utils import (
        load_delayed_memory_report,
        record_delayed_memory_runtime_result,
        build_delayed_memory_failure_result,
        build_delayed_memory_history_text,
        clear_loaded_delayed_memory_report,
        clear_delayed_memory_runtime_results,
        get_delayed_memory_reports,
        unload_delayed_memory_report,
        set_loaded_delayed_memory_report,
        update_delayed_memory_report,
    )

    delayed_memory_results = []

    if load_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] load_delayed_memory requested"
            )

        clear_delayed_memory_runtime_results(
            context
        )

        for action in load_delayed_memory_actions:
            result = load_delayed_memory_report(
                context,
                action.payload,
            )
            did_load_delayed_memory = set_loaded_delayed_memory_report(
                context,
                result,
            )
            if result.get("ok") is False:
                record_delayed_memory_runtime_result(
                    context,
                    result,
                )
            if did_load_delayed_memory:
                history_text = build_delayed_memory_history_text(
                    result
                )
                if history_text:
                    record_session_action_history(
                        context,
                        history_text,
                    )
            delayed_memory_results.append(
                result
            )

    if update_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] update_delayed_memory requested"
            )

        clear_delayed_memory_runtime_results(
            context
        )

        for action in update_delayed_memory_actions:
            result = update_delayed_memory_report(
                context,
                action.payload,
            )
            record_delayed_memory_runtime_result(
                context,
                result,
            )

            if result.get("ok") is not False:
                from runtime.L4_memory import (
                    refresh_runtime_l4_archived_fact_ids,
                )

                refresh_runtime_l4_archived_fact_ids(
                    context
                )
                history_text = build_delayed_memory_history_text(
                    result
                )
                if history_text:
                    record_session_action_history(
                        context,
                        history_text,
                    )

            delayed_memory_results.append(
                result
            )

    if unload_delayed_memory_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] unload_delayed_memory requested"
            )

        clear_delayed_memory_runtime_results(
            context
        )

        saved_reports_before_remove = deepcopy(
            get_delayed_memory_reports(
                context
            )
        )

        for action in unload_delayed_memory_actions:
            result = unload_delayed_memory_report(
                context,
                action.payload,
            )
            did_unload_delayed_memory = clear_loaded_delayed_memory_report(
                context,
                result.get(
                    "id",
                    "",
                ),
            )
            result["unloaded"] = did_unload_delayed_memory
            if (
                result.get("ok") is not False
                and not did_unload_delayed_memory
            ):
                result = build_delayed_memory_failure_result(
                    action="unload_delayed_memory",
                    requested=result.get(
                        "id",
                        "",
                    ),
                    error="delayed_memory_not_loaded",
                )
                result["unloaded"] = False
            record_delayed_memory_runtime_result(
                context,
                result,
            )
            if did_unload_delayed_memory:
                history_text = build_delayed_memory_history_text(
                    result
                )
                if history_text:
                    record_session_action_history(
                        context,
                        history_text,
                    )
            delayed_memory_results.append(
                result
            )

        if get_delayed_memory_reports(
            context
        ) != saved_reports_before_remove:
            setattr(
                context,
                "delayed_memory_reports",
                saved_reports_before_remove,
            )

    return delayed_memory_results


async def emit_delayed_memory_results(
    context,
    delayed_memory_results,
    *,
    with_action_context,
):
    if not delayed_memory_results:
        return

    from utils.brain_client_utils import build_delayed_memory_action_text

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

    first_delayed_result_index = max(
        len(
            getattr(
                context,
                "runtime_delayed_memory_results",
                [],
            )
        )
        - len(
            delayed_memory_results
        ),
        0,
    )

    for result_index, result in enumerate(
        delayed_memory_results,
        start=1,
    ):
        result_action = str(
            result.get(
                "action",
                "delayed_memory",
            )
            or "delayed_memory"
        )
        report_id = str(
            result.get(
                "id",
                "",
            )
            or ""
        ).strip().casefold()
        report = result.get(
            "report",
        )
        action_id = (
            report_id
            or build_runtime_action_id(
                result_action,
                first_delayed_result_index
                + result_index,
            )
        )
        event = {
            "type": "runtime_action",
            "action": result_action,
            "id": action_id,
            "status": (
                "completed"
                if result.get("ok") is not False
                else "failed"
            ),
            "display_name": get_runtime_action_display_name(
                result_action
            ),
            "close_tag": runtime_action_has_close_tag(
                result_action
            ),
            "text": build_delayed_memory_action_text(
                result
            ),
            "delayed_memory_result": result,
        }

        if report_id:
            event["delayed_memory_report_id"] = (
                report_id
            )

        if isinstance(
            report,
            dict,
        ):
            event["delayed_memory_report"] = {
                **report,
                "id": report_id
                or str(
                    report.get(
                        "id",
                        "",
                    )
                    or ""
                ).strip().casefold(),
            }

        await emit(with_action_context({
            **event,
        }))


async def apply_save_delayed_memory_actions(
    context,
    save_delayed_memory_actions,
    *,
    log_runtime,
    with_action_context,
):
    from utils.brain_client_utils import (
        build_delayed_memory_history_text,
        build_delayed_memory_report,
        deduplicate_delayed_memory_report_keys,
    )

    saved_delayed_memory_reports = []

    if not save_delayed_memory_actions:
        return saved_delayed_memory_reports

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] save_delayed_memory requested"
        )

    for action in save_delayed_memory_actions:
        delayed_memory_reports = getattr(
            context,
            "delayed_memory_reports",
            None,
        )

        if not isinstance(
            delayed_memory_reports,
            dict,
        ):
            delayed_memory_reports = {}
            setattr(
                context,
                "delayed_memory_reports",
                delayed_memory_reports,
            )

        report = build_delayed_memory_report(
            context,
            action.payload,
            existing_ids=delayed_memory_reports,
        )

        if not report:
            continue

        report = deduplicate_delayed_memory_report_keys(
            delayed_memory_reports,
            report,
        )

        delayed_memory_reports.update(
            report
        )

        from runtime.L4_memory import (
            refresh_runtime_l4_archived_fact_ids,
        )

        refresh_runtime_l4_archived_fact_ids(
            context
        )

        file_errors = []

        if bool(
            getattr(
                context,
                "delayed_memory_file_store_enabled",
                False,
            )
        ):
            from utils.delayed_memory_file_store import (
                persist_delayed_memory_reports,
            )

            file_errors = persist_delayed_memory_reports(
                report
            )

            if file_errors and log_runtime is not None:
                for file_error in file_errors:
                    await log_runtime(
                        "[DELAYED MEMORY] local file save failed: "
                        + file_error
                    )

        saved_delayed_memory_reports.append(
            report
        )

        for report_id, report_value in report.items():
            if not isinstance(
                report_value,
                dict,
            ):
                continue

            history_text = build_delayed_memory_history_text({
                "ok": True,
                "action": "save_delayed_memory_content",
                "id": report_id,
                "title": str(
                    report_value.get(
                        "title",
                        "",
                    )
                    or ""
                ).strip(),
                "report": {
                    **report_value,
                    "id": report_id,
                },
            })
            if history_text:
                record_session_action_history(
                    context,
                    history_text,
                )

            saved_result = {
                "ok": True,
                "action": "save_delayed_memory_content",
                "destination": (
                    "delayed_memory_reports (Delayed Memory storage)"
                ),
                "id": report_id,
                "title": str(
                    report_value.get(
                        "title",
                        "",
                    )
                    or ""
                ).strip(),
                "report": {
                    **report_value,
                    "id": report_id,
                },
                "file_saved": not file_errors,
                "file_errors": list(file_errors),
            }
            record_runtime_tool_result(
                context,
                TOOL_RESULT_KIND_DELAYED_MEMORY,
                saved_result,
            )

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
        for report in saved_delayed_memory_reports:
            report_items = [
                (
                    report_id,
                    report_value,
                )
                for report_id, report_value in report.items()
                if isinstance(
                    report_value,
                    dict,
                )
            ]
            report_id = (
                report_items[0][0]
                if report_items
                else ""
            )
            report_title = (
                str(
                    report_items[0][1].get(
                        "title",
                        "",
                    )
                    or ""
                ).strip()
                if report_items
                else ""
            )
            pending_ids = getattr(
                context,
                "runtime_pending_delayed_memory_action_ids",
                None,
            )
            action_id = (
                pending_ids.pop(0)
                if isinstance(
                    pending_ids,
                    list,
                )
                and pending_ids
                else ""
            )

            if not action_id:
                current_action_sequence = int(
                    getattr(
                        context,
                        "runtime_delayed_memory_action_sequence",
                        0,
                    )
                    or 0
                )
                save_action_event_count = len([
                    event
                    for event in getattr(
                        context,
                        "runtime_action_events",
                        [],
                    )
                    if isinstance(
                        event,
                        dict,
                    )
                    and event.get(
                        "name"
                    ) == "save_delayed_memory_content"
                ])
                action_sequence = max(
                    current_action_sequence + 1,
                    len(
                        getattr(
                            context,
                            "delayed_memory_reports",
                            {},
                        )
                        or {}
                    ),
                    save_action_event_count,
                )
                setattr(
                    context,
                    "runtime_delayed_memory_action_sequence",
                    action_sequence,
                )
                action_id = build_runtime_action_id(
                    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
                    action_sequence,
                )
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "save_delayed_memory_content",
                "id": action_id,
                "status": "completed",
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
                ),
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
                ),
                "text": (
                    f"Saved delayed memory: {report_title}"
                    if report_title
                    else "Delayed memory saved"
                ),
                "delayed_memory_report_id": report_id,
                "delayed_memory_report": report,
            }))

    return saved_delayed_memory_reports
