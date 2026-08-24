from fastapi import (
    APIRouter,
    WebSocket,
)
from starlette.websockets import WebSocketDisconnect

import asyncio
import contextlib
import json

from .logger import WebSocketLogger

from runtime.L1_memory import (
    apply_runtime_response_feedback,
    discard_latest_runtime_memory_pending_turn,
    resume_runtime_memory_pending_update,
)
from runtime.L1_memory_utils import (
    emit_runtime_l1_diff_update,
)
from runtime.L4_memory import (
    apply_facts_memory_store_sync,
    apply_l4_memory_store_sync,
    cancel_l4_memory_idle_update,
    delete_l4_memory_fact,
    emit_facts_memory_store_update,
    restore_l4_memory_fact,
    emit_l4_memory_update,
    note_l4_foreground_state,
    note_l4_user_activity,
    register_l4_websocket_connection,
    runtime_l4_memory_update_running,
    schedule_l4_memory_idle_update,
    unregister_l4_websocket_connection,
)
from runtime.fact_check import run_fact_check_once
from runtime.anonymous_mode import (
    RESTRICTED_WRITE_REASON,
    persistent_writes_restricted,
)
from utils.ws_errors import handle_websocket_error
from .attachments import (
    build_user_text_with_attachments,
    format_attachment_context,
    has_message_attachments,
    redacted_attachment_for_log,
    redacted_message_data_for_log,
)
from .bootstrap import (
    apply_active_memory_records,
    apply_delayed_memory_reports,
    apply_suppressed_delayed_memory_auto_load_ids,
    apply_loaded_delayed_memory_ids,
    apply_runtime_memory_slot_delete,
    apply_runtime_resume,
    apply_session_bootstrap,
    build_session_bootstrap_chat_tail,
    emit_current_runtime_memory,
    emit_delayed_memory_store_snapshot,
    ensure_initial_runtime_snapshot,
    get_or_create_connection_context,
    initialize_connection,
    is_soft_resume_request,
)
from .messages import (
    build_runtime_action_guard_retry_request,
    build_user_retry_request,
    emit_runtime_action_guard_confirmation_failure,
    process_message,
    receive_message,
    refresh_pending_brain_usage,
    reject_when_all_models_offline,
    resolve_runtime_action_guard_confirmation,
    wait_for_runtime_memory_update,
)
from .tasks import (
    cancel_current_task,
)

from utils.delayed_memory_file_store import (
    delete_delayed_memory_report_files,
    persist_delayed_memory_reports,
)
from utils.attached_files_store import (
    hydrate_attachment_ids,
    public_file_snapshot,
    sync_pinned_file_ids,
)
from utils.chat_log import (
    save_current_runtime_bootstrap_context_snapshot,
)
from utils.session_actions_history import (
    emit_session_actions_update,
)


websocket_router = APIRouter()


@websocket_router.websocket(
    "/ws/chat"
)
async def websocket_endpoint(
    websocket: WebSocket,
):

    logger = WebSocketLogger(
        websocket
    )

    soft_resume = is_soft_resume_request(
        websocket
    )

    context, resumed_context = get_or_create_connection_context(
        websocket,
        logger,
    )

    # A client can request a soft reconnect while the backend process has
    # already restarted. Only skip bootstrap state when the server actually
    # recovered the in-memory RuntimeContext; a fresh context needs the normal
    # initial state so browser-side reconnect guards can reconcile it safely.
    skip_initial_runtime_state = (
        soft_resume
        and resumed_context
    )

    ensure_initial_runtime_snapshot(
        context
    )

    current_task = None
    pending_requests = asyncio.Queue()
    context.runtime_pending_requests_queue = pending_requests

    async def process_pending_requests():
        nonlocal current_task

        while True:

            message_data = await pending_requests.get()

            try:

                user_text = (
                    str(
                        message_data.get(
                            "text",
                            "",
                        )
                    ).strip()
                )

                if message_data.get("type") == "retry_last_response":
                    await discard_latest_runtime_memory_pending_turn(
                        context
                    )
                    # If an older batch remains after removing the discarded
                    # answer, let it settle before building the replacement.
                    await wait_for_runtime_memory_update(
                        context
                    )
                else:
                    await wait_for_runtime_memory_update(
                        context
                    )

                await apply_runtime_response_feedback(
                    context,
                    (
                        message_data.get(
                            "pending_last_response_rating",
                        )
                        or message_data.get(
                            "runtime_response_feedback",
                        )
                    ),
                )

                await refresh_pending_brain_usage(
                    context,
                    user_text,
                )

                active_task = asyncio.create_task(
                    process_message(
                        context,
                        message_data,
                    )
                )
                current_task = active_task
                note_l4_foreground_state(
                    context,
                    running=True,
                )

                try:
                    await active_task

                except asyncio.CancelledError:
                    if active_task.cancelled():
                        await logger.log_runtime(
                            "[WS] queued request interrupted"
                        )
                    else:
                        raise

                finally:
                    if current_task is active_task:
                        current_task = None
                    note_l4_foreground_state(
                        context,
                        running=False,
                    )

            finally:
                pending_requests.task_done()

    pending_processor = asyncio.create_task(
        process_pending_requests()
    )

    register_l4_websocket_connection(
        context,
        app_state=websocket.app.state,
        websocket=websocket,
    )

    try:

        await initialize_connection(
            context,
            skip_initial_runtime_state=skip_initial_runtime_state,
        )

        while True:

            message_data = (
                await receive_message(
                    context,
                )
            )

            if message_data is None:
                await logger.log_system(
                    "[WS] received: None"
                )
                continue

            message_type = (
                message_data.get(
                    "type",
                    "message",
                )
            )

            # -------------------------------------------------
            # SOFT RECONNECT RUNTIME RESUME
            # -------------------------------------------------

            if message_type == "runtime_resume":

                restored = apply_runtime_resume(
                    context,
                    message_data,
                )

                resumed_memory_task = (
                    resume_runtime_memory_pending_update(
                        context
                    )
                )

                if resumed_memory_task is not None:
                    await logger.log_runtime(
                        "[MEMORY:L1] pending update resumed after reconnect"
                    )

                if restored:
                    await logger.log_system(
                        "[WS] runtime resumed from browser memory"
                    )

                    try:
                        save_current_runtime_bootstrap_context_snapshot(
                            context
                        )
                    except Exception as error:
                        await logger.log_system(
                            "[CHAT_LOG] resumed context snapshot save failed: "
                            + str(error)
                        )

                    if message_data.get(
                        "emit_after_restore"
                    ):
                        await emit_current_runtime_memory(
                            context
                        )

                        await emit_runtime_l1_diff_update(
                            context
                        )

                continue

            # -------------------------------------------------
            # RESTORE BROWSER SESSION SNAPSHOT
            # -------------------------------------------------

            if message_type == "runtime_memory_delete_slot":
                await apply_runtime_memory_slot_delete(
                    context,
                    message_data,
                )
                continue

            if message_type == "active_memory_store_sync":
                apply_active_memory_records(
                    context,
                    message_data,
                )
                continue

            if message_type == "attachment_context_sync":
                requested_file_ids = message_data.get(
                    "ids",
                    [],
                )
                if persistent_writes_restricted(context):
                    attachments = hydrate_attachment_ids(
                        requested_file_ids
                    )
                    file_ids = [
                        str(attachment.get("id", "") or "").strip()
                        for attachment in attachments
                        if str(attachment.get("id", "") or "").strip()
                    ]
                else:
                    file_ids = sync_pinned_file_ids(
                        requested_file_ids
                    )
                    attachments = hydrate_attachment_ids(
                        file_ids
                    )
                context.runtime_attached_file_ids = list(
                    file_ids
                )
                context.runtime_turn_attachments = list(
                    attachments
                )
                context.runtime_current_sequence_attachments = list(
                    attachments
                )
                file_snapshot = public_file_snapshot()
                if persistent_writes_restricted(context):
                    file_snapshot["pinned_ids"] = list(file_ids)
                await websocket.send_json({
                    "type": "attached_files_update",
                    **file_snapshot,
                })
                continue

            if message_type == "delayed_memory_store_sync":
                if persistent_writes_restricted(context):
                    deleted_report_ids = []
                else:
                    deleted_report_ids = apply_delayed_memory_reports(
                        context,
                        message_data,
                    )
                apply_loaded_delayed_memory_ids(
                    context,
                    message_data,
                )
                apply_suppressed_delayed_memory_auto_load_ids(
                    context,
                    message_data,
                )
                if not persistent_writes_restricted(context):
                    for report_id in deleted_report_ids:
                        delete_errors = delete_delayed_memory_report_files(
                            report_id
                        )
                        for delete_error in delete_errors:
                            await logger.log_system(
                                "[DELAYED MEMORY] local file delete failed: "
                                + delete_error
                            )
                    reports = getattr(
                        context,
                        "delayed_memory_reports",
                        {},
                    ) or {}
                    file_errors = persist_delayed_memory_reports(
                        reports
                    )
                    for file_error in file_errors:
                        await logger.log_system(
                            "[DELAYED MEMORY] local file save failed: "
                            + file_error
                        )
                await emit_delayed_memory_store_snapshot(
                    context
                )
                continue

            if message_type == "facts_memory_store_sync":
                stats = apply_facts_memory_store_sync(
                    context,
                    message_data.get(
                        "records",
                        [],
                    ),
                )
                await logger.log_system(
                    (
                        "[WS] facts memory store synced "
                        f"({stats['records_count']} records, "
                        f"{stats['pending_count']} pending)"
                    )
                )
                await emit_facts_memory_store_update(
                    context
                )
                continue

            if message_type == "l4_memory_store_sync":
                applied = apply_l4_memory_store_sync(
                    context,
                    message_data.get(
                        "store",
                        {},
                    ),
                )
                if applied:
                    await logger.log_system(
                        "[WS] L4 memory store updated from browser profile"
                    )
                await emit_l4_memory_update(
                    context,
                    change={
                        "synced": bool(applied),
                    },
                )
                continue

            if message_type == "l4_memory_idle_tick":
                # Never begin background L4 work while a foreground turn is
                # running or already queued. Browser idle checks normally avoid
                # this too; the server guard keeps foreground priority strict.
                if (
                    (current_task is not None and not current_task.done())
                    or not pending_requests.empty()
                ):
                    continue

                if "records" in message_data:
                    apply_facts_memory_store_sync(
                        context,
                        message_data.get(
                            "records",
                            [],
                        ),
                    )

                if (
                    "store" in message_data
                    and not runtime_l4_memory_update_running(
                        context
                    )
                ):
                    apply_l4_memory_store_sync(
                        context,
                        message_data.get(
                            "store",
                            {},
                        ),
                    )

                schedule_l4_memory_idle_update(
                    context=context,
                    user_idle_seconds=message_data.get(
                        "user_idle_seconds",
                    ),
                )
                continue

            if message_type == "l4_memory_delete_fact":
                if persistent_writes_restricted(context):
                    await logger.log_runtime(
                        "[RUNTIME ACTION] l4_memory_delete_fact failed: "
                        + RESTRICTED_WRITE_REASON
                    )
                    await emit_l4_memory_update(
                        context,
                        change={
                            "deleted": False,
                            "error": "restricted_write",
                        },
                    )
                    continue
                await delete_l4_memory_fact(
                    context,
                    str(
                        message_data.get(
                            "fact_id",
                            "",
                        )
                        or ""
                    ),
                )
                continue

            if message_type == "l4_memory_restore_fact":
                fact = message_data.get(
                    "fact",
                    {},
                )
                if persistent_writes_restricted(context):
                    await logger.log_runtime(
                        "[RUNTIME ACTION] l4_memory_restore_fact failed: "
                        + RESTRICTED_WRITE_REASON
                    )
                    restored = False
                else:
                    restored = await restore_l4_memory_fact(
                        context,
                        fact,
                    )
                await websocket.send_json({
                    "type": "l4_memory_restore_result",
                    "fact_id": str(
                        fact.get("id", "")
                        if isinstance(fact, dict)
                        else ""
                    ),
                    "restored": bool(restored),
                    "error": (
                        "restricted_write"
                        if persistent_writes_restricted(context)
                        else ""
                    ),
                })
                if persistent_writes_restricted(context):
                    await emit_l4_memory_update(
                        context,
                        change={
                            "restored": False,
                            "error": "restricted_write",
                        },
                    )
                continue

            if message_type == "session_bootstrap":

                if persistent_writes_restricted(context):
                    await logger.log_system(
                        "[SESSION] browser session bootstrap ignored in anonymous mode"
                    )
                    continue

                await logger.log(
                    "[SESSION]",
                    "[BOOTSTRAP] browser session restore request",
                    details=json.dumps(
                        message_data,
                        ensure_ascii=False,
                        indent=2,
                    ),
                )

                restored = apply_session_bootstrap(
                    context,
                    message_data,
                )

                if restored:
                    await logger.log_system(
                        "[WS] browser session snapshot restored"
                    )

                    try:
                        save_current_runtime_bootstrap_context_snapshot(
                            context
                        )
                    except Exception as error:
                        await logger.log_system(
                            "[CHAT_LOG] bootstrap context snapshot save failed: "
                            + str(error)
                        )

                    # PREVIOUS_RUNTIME_STATE is already visible as page 1 in
                    # the browser before websocket bootstrap. This message is
                    # the authoritative echo of that same baseline, never a
                    # second page. Explicit replacement also survives harmless
                    # server-side normalization that can defeat text dedupe.
                    await emit_current_runtime_memory(
                        context,
                        replace_latest=True,
                    )

                    await emit_runtime_l1_diff_update(
                        context
                    )

                    await emit_delayed_memory_store_snapshot(
                        context
                    )

                    # Restore the same three-action trail in the visible
                    # [SESSION ACTIONS] logger. RuntimeContext already owns
                    # this list, so the hidden bootstrap tick sees it too.
                    await emit_session_actions_update(
                        context,
                        current_sequence=False,
                    )

                chat_tail = build_session_bootstrap_chat_tail(
                    context
                )
                if chat_tail:
                    await context.emitter.emit({
                        "type": "session_bootstrap_chat_tail",
                        "source_session_id": str(
                            getattr(
                                context,
                                "previous_session_id",
                                "",
                            )
                            or ""
                        ).strip(),
                        "turns": chat_tail,
                    })

                continue

            if message_type == "archived_session_resume":
                if not getattr(
                    context,
                    "runtime_session_restore_priming",
                    False,
                ):
                    await logger.log_system(
                        "[SESSION RESTORE] ignored stale resume tick"
                    )
                    continue

                if await reject_when_all_models_offline(
                    context
                ):
                    continue

                await pending_requests.put(
                    message_data
                )
                await logger.log_runtime(
                    "[SESSION RESTORE] queued hidden continuation tick"
                )
                continue

            if message_type == "runtime_action_guard_confirmation":

                handled = await resolve_runtime_action_guard_confirmation(
                    context,
                    message_data,
                )

                if handled:
                    await logger.log_runtime(
                        "[RUNTIME ACTION] guard confirmation received"
                    )
                    continue

                retry_request = build_runtime_action_guard_retry_request(
                    message_data
                )

                if retry_request is not None:
                    await pending_requests.put(
                        retry_request
                    )
                    await logger.log_runtime(
                        "[RUNTIME ACTION] stale guard confirmation "
                        "replayed once after reconnect"
                    )
                    continue

                await emit_runtime_action_guard_confirmation_failure(
                    context,
                    message_data,
                )
                await logger.log_runtime(
                    "[RUNTIME ACTION] stale guard confirmation failed"
                )
                continue

            if message_type == "retry_last_response":
                if (
                    current_task is not None
                    and not current_task.done()
                ):
                    await websocket.send_json({
                        "type": "retry_last_response_rejected",
                        "reason": "generation_running",
                    })
                    await logger.log_runtime(
                        "[USER RETRY] rejected: generation is running"
                    )
                    continue

                retry_request = build_user_retry_request(
                    context,
                    message_data,
                )
                if retry_request is None:
                    await websocket.send_json({
                        "type": "retry_last_response_rejected",
                        "reason": "no_retryable_response",
                    })
                    await logger.log_runtime(
                        "[USER RETRY] rejected: no live retry source"
                    )
                    continue

                note_l4_user_activity(context)
                await cancel_l4_memory_idle_update(
                    context,
                    reason="user_retry",
                )

                if await reject_when_all_models_offline(
                    context
                ):
                    await websocket.send_json({
                        "type": "retry_last_response_rejected",
                        "reason": "models_offline",
                    })
                    continue

                await pending_requests.put(
                    retry_request
                )
                await logger.log_runtime(
                    "[USER RETRY] queued replacement for latest JIN answer"
                )
                continue

            await logger.log_user(
                str(
                    message_data.get(
                        "text",
                        "",
                    )
                ),
                details=json.dumps(
                    redacted_message_data_for_log(
                        message_data
                    ),
                    ensure_ascii=False,
                    indent=2,
                ),
            )

            # -------------------------------------------------
            # ABORT GENERATION
            # -------------------------------------------------

            if message_type == "abort":

                await cancel_current_task(
                    current_task,
                    logger,
                    context,
                )

                current_task = None

                continue

            # -------------------------------------------------
            # MANUAL FACT CHECK
            # -------------------------------------------------

            if message_type == "fact_check":

                if (
                    current_task is not None
                    and not current_task.done()
                ):
                    await logger.log_runtime(
                        "[FACT_CHECK] skipped: generation is running"
                    )
                    continue

                await logger.log(
                    "[MEMORY:FACT_CHECK]",
                    "[FACT_CHECK] manual web check requested",
                    channel="memory",
                    memory_level="FACT_CHECK",
                    memory_event="fact_check_manual",
                )

                runtime_memory_task = getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )

                if runtime_memory_task is not None:
                    await logger.log_runtime(
                        "[FACT_CHECK] waiting for runtime memory update"
                    )
                    await runtime_memory_task

                await run_fact_check_once(
                    context
                )

                continue

            # -------------------------------------------------
            # IGNORE EMPTY MESSAGE
            # -------------------------------------------------

            user_text = (
                str(
                    message_data.get(
                        "text",
                        "",
                    )
                ).strip()
            )

            if (
                not user_text
                and not has_message_attachments(
                    message_data
                )
            ):

                await logger.log_error(
                    "Received empty message."
                )

                continue

            # Foreground conversation always wins over idle L4 maintenance.
            # Cancelling here aborts the in-flight background model request
            # before this user turn enters the generation queue; pending L4
            # facts remain in their stores for the next true idle window.
            note_l4_user_activity(context)
            await cancel_l4_memory_idle_update(
                context,
                reason="user_message",
            )

            if await reject_when_all_models_offline(
                context
            ):
                continue

            # -------------------------------------------------
            # QUEUE MESSAGE
            # -------------------------------------------------

            if (
                current_task is not None
                and not current_task.done()
            ):

                await logger.log_runtime(
                    "[WS] queued message while generation is running"
                )

            elif (
                getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )
                is not None
            ):

                await logger.log_runtime(
                    "[WS] queued message while memory update is running"
                )

            await pending_requests.put(
                message_data
            )

            await logger.log_runtime(
                f"[WS] pending requests: {pending_requests.qsize()}"
            )

    except WebSocketDisconnect:

        await cancel_current_task(
            current_task,
            logger,
            context,
            update_memory=False,
            emit_aborted_actions=False,
        )

        return

    except Exception as error:

        disconnect_like_error = (
            isinstance(error, RuntimeError)
            and "disconnect" in str(error).lower()
        )

        await cancel_current_task(
            current_task,
            logger,
            context,
            update_memory=not disconnect_like_error,
            emit_aborted_actions=not disconnect_like_error,
        )

        if disconnect_like_error:
            return

        await handle_websocket_error(
            websocket,
            logger,
            exception=error,
        )

    finally:
        unregister_l4_websocket_connection(
            context,
            app_state=websocket.app.state,
            websocket=websocket,
        )

        if getattr(
            context,
            "runtime_pending_requests_queue",
            None,
        ) is pending_requests:
            context.runtime_pending_requests_queue = None

        pending_processor.cancel()

        with contextlib.suppress(
            asyncio.CancelledError,
            Exception,
        ):
            await pending_processor

        while True:
            try:
                pending_requests.get_nowait()
            except asyncio.QueueEmpty:
                break
            pending_requests.task_done()


