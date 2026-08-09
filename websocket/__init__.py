from fastapi import (
    APIRouter,
    WebSocket,
)
from starlette.websockets import WebSocketDisconnect

import asyncio
import contextlib
import json

from .logger import WebSocketLogger

from runtime.L1_memory import apply_runtime_response_feedback
from runtime.L1_memory_utils import (
    emit_runtime_l1_diff_update,
    emit_runtime_session_memory_update,
)
from runtime.L4_memory import (
    apply_facts_memory_store_sync,
    apply_l4_memory_store_sync,
    delete_l4_memory_fact,
    emit_facts_memory_store_update,
    restore_l4_memory_fact,
    emit_l4_memory_update,
    runtime_l4_memory_update_running,
    schedule_l4_memory_idle_update,
)
from runtime.fact_check import run_fact_check_once
from utils.ws_errors import handle_websocket_error
from .attachments import (
    build_user_text_with_attachments,
    format_attachment_context,
    has_message_attachments,
    redacted_attachment_for_log,
    redacted_message_data_for_log,
)
from .bootstrap import (
    apply_delayed_memory_reports,
    apply_runtime_memory_slot_delete,
    apply_runtime_resume,
    apply_session_bootstrap,
    emit_current_runtime_memory,
    emit_delayed_memory_store_snapshot,
    ensure_initial_runtime_snapshot,
    get_or_create_connection_context,
    initialize_connection,
    is_soft_resume_request,
)
from .messages import (
    arm_save_session_from_user_text,
    merge_runtime_idle_followup_turn,
    process_message,
    receive_message,
    refresh_pending_brain_usage,
    reject_when_all_models_offline,
    resolve_runtime_action_guard_confirmation,
    wait_for_runtime_memory_update,
)
from .tasks import (
    PendingRequestQueue,
    cancel_current_task,
)

from utils.delayed_memory_file_store import (
    persist_delayed_memory_reports,
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

    skip_initial_runtime_state = soft_resume

    ensure_initial_runtime_snapshot(
        context
    )

    current_task = None
    pending_requests = PendingRequestQueue()
    context.runtime_pending_requests_queue = pending_requests

    pending_idle_followups = list(
        getattr(
            context,
            "runtime_pending_idle_followups",
            [],
        )
        or []
    )
    context.runtime_pending_idle_followups = []

    async def process_pending_requests():
        nonlocal current_task

        while True:

            message_data = await pending_requests.get()

            try:

                is_idle_followup = (
                    message_data.get("type") == "idle_followup"
                    and isinstance(
                        message_data.get("idle_followup"),
                        dict,
                    )
                )
                user_text = (
                    str(
                        (
                            message_data.get("idle_followup", {}).get(
                                "origin_user_request",
                                "",
                            )
                            if is_idle_followup
                            else message_data.get(
                                "text",
                                "",
                            )
                        )
                    ).strip()
                )

                await wait_for_runtime_memory_update(
                    context
                )
                if not is_idle_followup:
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

            finally:
                pending_requests.task_done()

    pending_processor = asyncio.create_task(
        process_pending_requests()
    )

    try:

        await initialize_connection(
            context,
            skip_initial_runtime_state=skip_initial_runtime_state,
        )

        for idle_followup in pending_idle_followups:
            await pending_requests.put({
                "type": "idle_followup",
                "idle_followup": idle_followup,
            })

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

                if restored:
                    await logger.log_system(
                        "[WS] runtime resumed from browser memory"
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
            # RESTORE BROWSER SESSION MEMORY
            # -------------------------------------------------

            if message_type == "runtime_memory_delete_slot":
                await apply_runtime_memory_slot_delete(
                    context,
                    message_data,
                )
                continue

            if message_type == "delayed_memory_store_sync":
                apply_delayed_memory_reports(
                    context,
                    message_data,
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
                })
                continue

            if message_type == "session_bootstrap":

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
                        "[WS] browser session memory restored"
                    )

                    await emit_current_runtime_memory(
                        context
                    )

                    await emit_runtime_l1_diff_update(
                        context
                    )

                    await emit_runtime_session_memory_update(
                        context
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

        pending_idle_records = getattr(
            context,
            "runtime_pending_idle_followups",
            None,
        )
        if not isinstance(pending_idle_records, list):
            pending_idle_records = []
            context.runtime_pending_idle_followups = (
                pending_idle_records
            )

        pending_idle_ids = {
            str(record.get("id", "") or "")
            for record in pending_idle_records
            if isinstance(record, dict)
        }

        while True:
            try:
                queued_message = pending_requests.get_nowait()
            except asyncio.QueueEmpty:
                break

            try:
                idle_record = queued_message.get(
                    "idle_followup",
                )
                if not isinstance(idle_record, dict):
                    continue

                idle_id = str(
                    idle_record.get(
                        "id",
                        "",
                    )
                    or ""
                )
                if idle_id and idle_id in pending_idle_ids:
                    continue

                pending_idle_records.append(
                    idle_record
                )
                if idle_id:
                    pending_idle_ids.add(
                        idle_id
                    )
            finally:
                pending_requests.task_done()


