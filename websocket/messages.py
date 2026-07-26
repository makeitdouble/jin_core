import asyncio
import json
import time

import httpx

from agent import (
    AgentRuntime,
    AgentState,
)
from clients.brain_client import build_brain_payload
from config_loader import config
from rules.brain_context_builder import build_brain_context
from runtime.runtime_context import RECENT_MESSAGES_MAX_PAIRS
from runtime.L1_memory import (
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
)
from runtime.L1_memory_utils import record_runtime_memory_reasoning_quotes
from runtime.state_sync import refresh_runtime_state
from utils.brain_client_utils import (
    get_brain_runtime_config,
    should_prearm_save_session,
)
from utils.language import contains_cyrillic
from utils.session_actions_history import emit_session_actions_update
from utils.token_usage import format_token_usage_summary
from utils.tokens import estimate_runtime_tokens
from utils.urls import join_url
from utils.ws_errors import handle_fatal_runtime_error
from .attachments import build_user_text_with_attachments
from .bootstrap import (
    apply_active_memory_records,
    attach_user_idle_to_initial_runtime_snapshot,
)


RUNTIME_STATUS_CHECK_TIMEOUT = getattr(
    config,
    "STATUS_CHECK_TIMEOUT",
    0.5,
)


def get_status_http_client(
    context,
):

    clients = getattr(
        context,
        "clients",
        {},
    )

    for runtime_client in clients.values():
        http_client = getattr(
            runtime_client,
            "client",
            None,
        )

        if http_client is not None:
            return http_client

    return None


async def check_model_status(
    http_client,
    base_url: str,
) -> bool:

    try:
        response = await http_client.get(
            join_url(
                base_url,
                config.MODELS_ENDPOINT,
            ),
            timeout=RUNTIME_STATUS_CHECK_TIMEOUT,
        )

        return response.status_code == 200

    except (
        httpx.HTTPError,
        asyncio.TimeoutError,
    ):
        return False


async def has_available_model_runtime(
    context,
) -> bool:

    http_client = get_status_http_client(
        context
    )

    if http_client is None:
        return True

    brain_status, service_status = await asyncio.gather(
        check_model_status(
            http_client,
            config.BRAIN_API_BASE,
        ),
        check_model_status(
            http_client,
            config.SERVICE_API_BASE,
        ),
    )

    return (
        brain_status
        or service_status
    )


async def reject_when_all_models_offline(
    context,
) -> bool:

    if await has_available_model_runtime(
        context
    ):
        return False

    await context.logger.log_error(
        "[WS] all model runtimes are offline"
    )

    await context.websocket.send_json({
        "type": "error",
        "message": (
            "All model runtimes are offline."
        ),
        "details": (
            "Start BRAIN or SERVICE before sending a request."
        ),
        "component": "runtime_status",
    })

    return True


async def receive_message(
    context,
) -> dict | None:
    websocket = context.websocket
    logger = context.logger

    raw_data = (
        await websocket.receive_text()
    )

    try:

        message_data = json.loads(
            raw_data
        )

        if isinstance(
            message_data,
            dict,
        ):
            return message_data

        await logger.log_error(
            "Invalid JSON payload: expected object."
        )

        return None

    except json.JSONDecodeError as error:

        await logger.log_error(
            f"Invalid JSON payload: {error}"
        )

        return None


async def resolve_runtime_action_guard_confirmation(
    context,
    message_data: dict,
) -> bool:

    confirmation_id = str(
        message_data.get(
            "confirmation_id",
            "",
        )
        or ""
    ).strip()

    if not confirmation_id:
        return False

    pending = getattr(
        context,
        "runtime_action_guard_confirmations",
        {},
    )

    if not isinstance(
        pending,
        dict,
    ):
        return False

    future = pending.get(
        confirmation_id
    )

    if (
        future is None
        or not hasattr(
            future,
            "done",
        )
        or future.done()
    ):
        return False

    decision = str(
        message_data.get(
            "decision",
            "",
        )
        or ""
    ).strip().casefold()

    if decision not in {
        "continue",
        "reject",
    }:
        return False

    future.set_result(
        decision
    )

    return True


# ---------------------------------------------------------
# PROCESS MESSAGE
# ---------------------------------------------------------

async def arm_save_session_from_user_text(
    context,
    user_text: str,
) -> bool:

    if (
        getattr(
            context,
            "runtime_save_session_armed",
            False,
        )
        or getattr(
            context,
            "runtime_save_session_requested",
            False,
        )
    ):
        return False

    if not should_prearm_save_session(
        user_text,
    ):
        return False

    context.runtime_save_session_armed = True
    context.runtime_save_session_requested = False
    # This path is only a deterministic early trigger. It lets the brain see
    # the user's explicit save intent, but it does not confirm the save and
    # must not show the UI banner. The save becomes real only when JIN emits
    # the private SAVE_SESSION marker handled by apply_runtime_action_calls().
    context.runtime_save_session_action_emitted = False

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
            "[RUNTIME ACTION] save_session armed"
        )

    return True


async def refresh_pending_brain_usage(
    context,
    user_text: str,
):

    if contains_cyrillic(
        user_text
    ):
        return

    brain_runtime = (
        get_brain_runtime_config()
    )

    runtime_actions = (
        brain_runtime.get(
            "runtime_actions",
            {},
        )
    )

    system_prompt = (
        build_brain_context(
            context,
            runtime_actions=runtime_actions,
        )
    )

    brain_payload = (
        build_brain_payload(
            user_text,
            context=context,
        )
    )

    used_tokens = (
        estimate_runtime_tokens(
            system_prompt=system_prompt,
            user_input=brain_payload,
        )
    )

    await refresh_runtime_state(
        context,
        runtime_id=(
            brain_runtime["runtime_id"]
        ),
        used_tokens=used_tokens,
        context_tokens=used_tokens,
        total_tokens=used_tokens,
        max_tokens=(
            brain_runtime["context_window"]
        ),
        last_error=None,
        status="online",
    )


async def wait_for_runtime_memory_update(
    context,
):

    while True:

        task = getattr(
            context,
            "runtime_memory_update_task",
            None,
        )

        if task is None:
            return

        if task.done():
            try:
                await task

            except asyncio.CancelledError:
                if task.cancelled():
                    await context.logger.log_runtime(
                        "[MEMORY] pending memory update cancelled"
                    )
                else:
                    raise

            except Exception as error:
                await context.logger.log_error(
                    "[MEMORY] pending memory update failed",
                    details=str(error),
                )

            finally:
                if (
                    getattr(
                        context,
                        "runtime_memory_update_task",
                        None,
                    )
                    is task
                ):
                    context.runtime_memory_update_task = None

            continue

        await context.logger.log_runtime(
            "[WS] waiting pending memory update"
        )

        try:
            await asyncio.shield(
                task
            )

        except asyncio.CancelledError:
            if task.cancelled():
                await context.logger.log_runtime(
                    "[MEMORY] pending memory update cancelled"
                )
            else:
                raise

        except Exception as error:
            await context.logger.log_error(
                "[MEMORY] pending memory update failed",
                details=str(error),
            )

        finally:
            if (
                getattr(
                    context,
                    "runtime_memory_update_task",
                    None,
                )
                is task
            ):
                context.runtime_memory_update_task = None


def parse_user_idle_seconds(
    value,
) -> int | None:

    try:
        seconds = int(
            float(
                value
            )
        )
    except (
        TypeError,
        ValueError,
    ):
        return None

    if seconds < 0:
        return None

    # Keep the value useful for conversational context, not as an
    # unbounded client-controlled payload. One year is more than enough
    # for a human re-entry signal.
    return min(
        seconds,
        365 * 24 * 60 * 60,
    )


def apply_user_idle_context(
    context,
    message_data: dict,
):

    seconds = parse_user_idle_seconds(
        message_data.get(
            "user_idle_seconds",
        )
    )

    if seconds is None:
        context.runtime_user_idle_seconds = None
        context.runtime_user_idle_text = ""
        context.runtime_user_idle_paused = False
        return

    context.runtime_user_idle_seconds = seconds
    context.runtime_user_idle_text = str(
        message_data.get(
            "user_idle",
            "",
        )
        or ""
    ).strip()[:32]
    context.runtime_user_idle_paused = bool(
        message_data.get(
            "user_idle_paused",
            False,
        )
    )
    attach_user_idle_to_initial_runtime_snapshot(
        context
    )


def parse_runtime_pattern_counter(
    value,
) -> int:

    try:
        counter = int(
            value
            or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0

    return max(
        0,
        min(
            counter,
            100,
        ),
    )


def apply_runtime_pattern_context(
    context,
    message_data: dict,
):

    context.runtime_pattern_counter = parse_runtime_pattern_counter(
        message_data.get(
            "runtime_pattern_counter",
            0,
        )
    )
    context.runtime_repeated_input_count = parse_runtime_pattern_counter(
        message_data.get(
            "runtime_repeated_input_count",
            0,
        )
    )


def append_runtime_recent_turn(
    context,
    *,
    user_message: str,
    assistant_message: str,
    user_created_at: float | None = None,
    assistant_created_at: float | None = None,
) -> None:

    if context is None:
        return

    if not hasattr(
        context,
        "runtime_recent_turns",
    ):
        context.runtime_recent_turns = []

    user_message = str(
        user_message
        or ""
    ).strip()
    assistant_message = str(
        assistant_message
        or ""
    ).strip()

    if not user_message and not assistant_message:
        return

    turn = {
        "user": user_message,
        "jin": assistant_message,
    }

    if isinstance(
        user_created_at,
        (int, float),
    ):
        turn["user_created_at"] = float(
            user_created_at
        )

    if isinstance(
        assistant_created_at,
        (int, float),
    ):
        turn["jin_created_at"] = float(
            assistant_created_at
        )

    context.runtime_recent_turns.append(
        turn
    )

    context.runtime_recent_turns = context.runtime_recent_turns[
        -RECENT_MESSAGES_MAX_PAIRS:
    ]


def merge_runtime_idle_followup_turn(
    context,
    *,
    origin_user_request: str,
    assistant_message: str,
    assistant_created_at: float | None = None,
    idle_followup_id: str = "",
) -> None:

    if context is None:
        return

    origin_user_request = str(
        origin_user_request
        or ""
    ).strip()
    assistant_message = str(
        assistant_message
        or ""
    ).strip()

    if not assistant_message:
        return

    recent_turns = getattr(
        context,
        "runtime_recent_turns",
        None,
    )
    if not isinstance(
        recent_turns,
        list,
    ):
        recent_turns = []
        context.runtime_recent_turns = recent_turns

    target_turn = None
    for turn in reversed(
        recent_turns
    ):
        if not isinstance(
            turn,
            dict,
        ):
            continue

        turn_user = str(
            turn.get(
                "user",
                "",
            )
            or ""
        ).strip()
        turn_origin = str(
            turn.get(
                "idle_origin_user_request",
                "",
            )
            or ""
        ).strip()

        if origin_user_request and (
            turn_user == origin_user_request
            or turn_origin == origin_user_request
        ):
            target_turn = turn
            break

    if target_turn is None:
        target_turn = {
            "user": origin_user_request,
            "jin": "",
            "idle_origin_user_request": origin_user_request,
        }
        recent_turns.append(
            target_turn
        )

    target_turn["jin"] = assistant_message
    target_turn["idle_origin_user_request"] = origin_user_request

    normalized_idle_followup_id = str(
        idle_followup_id
        or ""
    ).strip()
    if normalized_idle_followup_id:
        target_turn["idle_followup_id"] = normalized_idle_followup_id

    if isinstance(
        assistant_created_at,
        (int, float),
    ):
        target_turn["jin_created_at"] = float(
            assistant_created_at
        )

    context.runtime_recent_turns = recent_turns[
        -RECENT_MESSAGES_MAX_PAIRS:
    ]


def format_runtime_memory_user_message(
    context,
    user_text: str,
) -> str:

    repeated = parse_runtime_pattern_counter(
        getattr(
            context,
            "runtime_repeated_input_count",
            0,
        )
    )

    if repeated < 2:
        return user_text

    return f"{json.dumps(user_text, ensure_ascii=False)} [ repeated: {repeated} ]"


async def process_message(
    context,
    message_data: dict,
):
    websocket = context.websocket
    logger = context.logger

    try:

        idle_followup = message_data.get(
            "idle_followup",
            {},
        )
        if not isinstance(idle_followup, dict):
            idle_followup = {}
        is_idle_followup = bool(idle_followup)

        user_text = (
            str(
                idle_followup.get(
                    "origin_user_request",
                    "",
                )
                or ""
            )
            if is_idle_followup
            else build_user_text_with_attachments(
                message_data,
            )
        )

        context.runtime_turn_user_message = user_text
        context.runtime_turn_started_at = time.time()
        context.runtime_turn_counter = (
            getattr(
                context,
                "runtime_turn_counter",
                0,
            )
            + 1
        )
        context.runtime_current_turn_id = (
            f"idle_{context.runtime_turn_counter:06d}"
            if is_idle_followup
            else f"turn_{context.runtime_turn_counter:06d}"
        )

        if is_idle_followup:
            context.runtime_current_sequence_turn_id = str(
                idle_followup.get(
                    "sequence_turn_id",
                    "",
                )
                or context.runtime_current_turn_id
            ).strip()
            sequence_started_at = idle_followup.get(
                "sequence_started_at"
            )
            if not isinstance(
                sequence_started_at,
                (int, float),
            ) or sequence_started_at <= 0:
                sequence_started_at = context.runtime_turn_started_at
            context.runtime_current_sequence_started_at = float(
                sequence_started_at
            )
        else:
            context.runtime_current_sequence_turn_id = (
                context.runtime_current_turn_id
            )
            context.runtime_current_sequence_started_at = (
                context.runtime_turn_started_at
            )
        context.runtime_turn_attachments = (
            idle_followup.get(
                "attachments",
                [],
            )
            if (
                is_idle_followup
                and isinstance(
                    idle_followup.get(
                        "attachments",
                    ),
                    list,
                )
            )
            else (
                message_data.get(
                    "attachments",
                    [],
                )
                if (
                    not is_idle_followup
                    and isinstance(
                        message_data.get(
                            "attachments",
                        ),
                        list,
                    )
                )
                else []
            )
        )
        context.runtime_turn_assistant_response = ""
        context.runtime_active_action_markers = []
        context.runtime_turn_aborted_actions = []
        context.runtime_turn_abort_requested = False
        context.runtime_turn_discard_requested = False
        context.runtime_turn_interrupted_memory_update_scheduled = False
        context.runtime_turn_interrupted = False
        context.runtime_turn_interruption_reason = ""
        context.runtime_turn_interruption_quote = ""
        context.runtime_save_session_memory_committed_this_turn = False
        context.runtime_turn_memory_user_message = ""
        context.runtime_reasoning_recovery_pending = False
        context.runtime_context_limit_recovery_pending = False
        context.runtime_context_limit_stage = ""
        context.runtime_context_limit_kind = ""
        context.runtime_context_limit_finish_reason = ""
        if not is_idle_followup:
            await arm_save_session_from_user_text(
                context,
                user_text,
            )
            apply_user_idle_context(
                context,
                message_data,
            )
            apply_active_memory_records(
                context,
                message_data,
            )
            apply_runtime_pattern_context(
                context,
                message_data,
            )
            context.runtime_turn_memory_user_message = (
                format_runtime_memory_user_message(
                    context,
                    user_text,
                )
            )
            context.user_message_count += 1

        state = AgentState(
            user_input=user_text
        )
        if is_idle_followup:
            state.metadata["idle_followup"] = idle_followup

        if hasattr(
            context,
            "runtime_usage_events",
        ):
            context.runtime_usage_events.clear()

        else:
            context.runtime_usage_events = []

        runtime = AgentRuntime()

        await websocket.send_json({
            "type": "agent_runtime_start",
        })

        await runtime.run(
            state,
            context,
        )

        if getattr(
            context,
            "runtime_turn_discard_requested",
            False,
        ):
            return

        await emit_session_actions_update(
            context,
            current_sequence=False,
        )

        await logger.log(
            "[FLOW TELEMETRY]",
            format_token_usage_summary(
                context
            ),
        )

        await logger.log_system(
            "[WS] agent runtime end"
        )

        await websocket.send_json({
            "type": "agent_runtime_end",
        })

        assistant_message = (
                state.final_answer
                or state.brain_response
                or context.runtime_turn_assistant_response
        )

        assistant_created_at = time.time()
        if is_idle_followup:
            merge_runtime_idle_followup_turn(
                context,
                origin_user_request=user_text,
                assistant_message=assistant_message,
                assistant_created_at=assistant_created_at,
                idle_followup_id=str(
                    idle_followup.get(
                        "id",
                        "",
                    )
                    or ""
                ),
            )
        else:
            append_runtime_recent_turn(
                context,
                user_message=user_text,
                assistant_message=assistant_message,
                user_created_at=getattr(
                    context,
                    "runtime_turn_started_at",
                    None,
                ),
                assistant_created_at=assistant_created_at,
            )

        if is_idle_followup:
            memory_update_task = None
        elif getattr(
            context,
            "runtime_turn_interrupted",
            False,
        ):
            record_runtime_memory_reasoning_quotes(
                context,
                getattr(
                    context,
                    "runtime_turn_reasoning_content",
                    "",
                ),
            )
            memory_update_task = schedule_interrupted_runtime_memory_update(
                context=context,
            )
        else:
            # SAVE_SESSION now completes before its follow-up using the
            # snapshots that already existed. The user's save request and
            # JIN's final confirmation are therefore committed here through
            # the ordinary post-response L1/L2 path.
            record_runtime_memory_reasoning_quotes(
                context,
                getattr(
                    context,
                    "runtime_turn_reasoning_content",
                    "",
                ),
            )
            memory_update_task = schedule_runtime_memory_update(
                context=context,
                user_message=getattr(
                    context,
                    "runtime_turn_memory_user_message",
                    "",
                ) or format_runtime_memory_user_message(
                    context,
                    user_text,
                ),
                assistant_message=assistant_message,
            )

        if getattr(
            context,
            "runtime_save_session_requested",
            False,
        ):
            await wait_for_runtime_memory_update(
                context
            )

        context.assistant_message_count += 1
        if not is_idle_followup:
            context.turn_number += 1

        # Background fact-checking is intentionally not armed here.
        # Fact-checking runs only from the explicit UI request path.

    except asyncio.CancelledError:

        await logger.log_runtime(
            "Agent runtime task cancelled."
        )

        raise

    except Exception as error:

        await handle_fatal_runtime_error(
            context,
            component="agent_runtime",
            exception=error,
        )


# ---------------------------------------------------------
# CANCEL CURRENT TASK
# ---------------------------------------------------------
