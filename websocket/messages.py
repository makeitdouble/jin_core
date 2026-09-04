import asyncio
from copy import deepcopy
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
from runtime.behavior_contract import (
    get_action_guard_name_for_runtime_action,
)
from contracts.rules_assembler import (
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from runtime.L1_memory import (
    schedule_interrupted_runtime_memory_update,
    schedule_runtime_memory_update,
)
from runtime.L1_memory_utils import (
    build_runtime_session_checkpoint,
    record_runtime_memory_reasoning_quotes,
)
from runtime.LT_memory import (
    record_lt_reasoning_fact_mentions,
)
from runtime.state_sync import refresh_runtime_state
from utils.brain_client_utils import (
    get_brain_runtime_config,
)
from utils.chat_log import (
    append_chat_log_entry,
    replace_latest_chat_log_entry,
    save_turn_reasoning,
)
from utils.delayed_memory_triggers import (
    load_delayed_memory_by_tags,
)
from utils.session_actions_history import emit_session_actions_update
from utils.actions import (
    normalize_jin_position_dict,
    normalize_jin_speed_value,
    normalize_jin_size_dict,
)
from utils.token_usage import (
    format_token_usage_summary,
    get_runtime_token_estimate_scale,
)
from utils.tokens import estimate_stream_input_tokens
from utils.urls import join_url
from utils.ws_errors import handle_fatal_runtime_error
from .attachments import (
    attachment_ids_from_message_data,
    build_user_text_with_attachments,
    get_message_user_text,
    hydrate_message_attachments,
)
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

    brain_status = await check_model_status(
        http_client,
        config.BRAIN_API_BASE,
    )

    return brain_status


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
            "Brain runtime is offline."
        ),
        "details": (
            "Start BRAIN before sending a request."
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


def normalize_runtime_action_guard_retry(
    value,
) -> dict:

    if not isinstance(value, dict):
        return {}

    action = str(
        value.get("action", "")
        or ""
    ).strip().lower()
    guard = str(
        value.get("guard", "")
        or ""
    ).strip()
    confirmation_id = str(
        value.get("confirmation_id", "")
        or ""
    ).strip()
    action_id = str(
        value.get("id", "")
        or ""
    ).strip()
    context_snapshot = value.get(
        "context_snapshot",
        {},
    )
    if not isinstance(context_snapshot, dict):
        context_snapshot = {}

    try:
        attempt = int(
            value.get("attempt", 0)
            or 0
        )
    except (TypeError, ValueError):
        attempt = 0

    if (
        not action
        or not guard
        or not confirmation_id
        or attempt != 1
    ):
        return {}

    expected_guard = get_action_guard_name_for_runtime_action(
        action
    )

    if not expected_guard or expected_guard != guard:
        return {}

    retry = {
        "action": action,
        "guard": guard,
        "confirmation_id": confirmation_id,
        "id": action_id,
        "attempt": 1,
    }

    if context_snapshot:
        retry["context_snapshot"] = dict(
            context_snapshot
        )

    return retry


def build_runtime_action_guard_retry_request(
    message_data: dict,
) -> dict | None:

    if not isinstance(message_data, dict):
        return None

    decision = str(
        message_data.get("decision", "")
        or ""
    ).strip().casefold()

    if decision != "continue":
        return None

    retry = normalize_runtime_action_guard_retry({
        "action": message_data.get("action", ""),
        "guard": message_data.get("guard", ""),
        "confirmation_id": message_data.get(
            "confirmation_id",
            "",
        ),
        "id": message_data.get("id", ""),
        "attempt": message_data.get("retry_attempt", 0),
        "context_snapshot": message_data.get(
            "retry_context_snapshot",
            {},
        ),
    })

    user_text = str(
        message_data.get("retry_user_message", "")
        or ""
    ).strip()

    if not retry or not user_text:
        return None

    return {
        "type": "runtime_action_guard_retry",
        "text": user_text,
        "runtime_action_guard_retry": retry,
    }


async def emit_runtime_action_guard_confirmation_failure(
    context,
    message_data: dict,
    *,
    error: str = "runtime_action_confirmation_expired",
) -> None:

    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    if emit is None:
        return

    action = str(
        message_data.get("action", "")
        or ""
    ).strip().lower()
    confirmation_id = str(
        message_data.get("confirmation_id", "")
        or ""
    ).strip()
    action_id = str(
        message_data.get("id", "")
        or ""
    ).strip()

    if not action or not confirmation_id:
        return

    display_name = get_runtime_action_display_name(
        action
    )
    decision = str(
        message_data.get("decision", "")
        or ""
    ).strip().casefold()
    rejected = decision == "reject"

    payload = {
        "type": "runtime_action",
        "action": action,
        "status": "failed",
        "display_name": display_name,
        "close_tag": runtime_action_has_close_tag(action),
        "confirmation_id": confirmation_id,
        "error": (
            "user_rejected_runtime_action"
            if rejected
            else error
        ),
        "text": (
            f"{display_name} cancelled"
            if rejected
            else f"{display_name}: FAILED"
        ),
        "detail": (
            "The original confirmation no longer exists after reconnect."
            if not rejected
            else "The stale confirmation was cancelled by the user."
        ),
    }

    if action_id:
        payload["id"] = action_id

    await emit(payload)


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


async def refresh_pending_brain_usage(
    context,
    user_text: str,
):

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
            user_input=user_text,
        )
    )

    brain_payload = (
        build_brain_payload(
            user_text,
            context=context,
        )
    )

    pending_prompt = "\n".join(
        value
        for value in (
            brain_payload,
            system_prompt,
        )
        if value
    )

    used_tokens = (
        estimate_stream_input_tokens(
            None,
            prompt_text=pending_prompt,
            scale=get_runtime_token_estimate_scale(
                context,
                brain_runtime["runtime_id"],
            ),
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


def begin_user_waiting_for_jin_answer_turn(
    context,
    *,
    enabled: bool,
) -> None:

    current_session_id = str(
        getattr(
            context,
            "session_id",
            "",
        )
        or ""
    ).strip()
    tracked_session_id = str(
        getattr(
            context,
            "runtime_user_waiting_for_jin_answer_session_id",
            "",
        )
        or ""
    ).strip()

    if tracked_session_id != current_session_id:
        context.runtime_user_waiting_for_jin_answer_session_id = (
            current_session_id
        )
        context.runtime_user_waiting_for_jin_answer_last_seconds = None
        context.runtime_user_waiting_for_jin_answer_total_seconds = 0.0
        context.runtime_user_waiting_for_jin_answer_count = 0
        context.runtime_previous_answer_context_window = {}

    context.runtime_user_waiting_for_jin_answer_started_at = 0.0
    context.runtime_user_waiting_for_jin_answer_tracking_enabled = bool(
        enabled
    )


def remember_previous_answer_context_window(
    context,
) -> None:

    current_context_window = getattr(
        context,
        "runtime_current_context_window",
        {},
    )

    if not isinstance(
        current_context_window,
        dict,
    ):
        return

    try:
        used_tokens = int(
            current_context_window.get(
                "used_tokens",
                0,
            )
            or 0
        )
        context_window = int(
            current_context_window.get(
                "context_window",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        return

    if context_window <= 0 or used_tokens < 0:
        return

    context.runtime_previous_answer_context_window = {
        "runtime_id": str(
            current_context_window.get(
                "runtime_id",
                "",
            )
            or ""
        ),
        "used_tokens": used_tokens,
        "context_window": context_window,
        "value": str(
            current_context_window.get(
                "value",
                "",
            )
            or ""
        ),
    }


def finish_user_waiting_for_jin_answer_turn(
    context,
) -> float | None:

    # Context usage is independent from whether the answer exposed a visible
    # reasoning stream. Capture the completed request context on every finish.
    remember_previous_answer_context_window(
        context
    )

    if not bool(
        getattr(
            context,
            "runtime_user_waiting_for_jin_answer_tracking_enabled",
            False,
        )
    ):
        return None

    context.runtime_user_waiting_for_jin_answer_tracking_enabled = False
    started_at = float(
        getattr(
            context,
            "runtime_user_waiting_for_jin_answer_started_at",
            0.0,
        )
        or 0.0
    )
    context.runtime_user_waiting_for_jin_answer_started_at = 0.0

    if started_at <= 0:
        # No visible reasoning was emitted for this answer, so there is no
        # truthful wait duration under the "first reasoning symbol -> complete
        # answer" contract. Do not reuse an older answer as "previous".
        context.runtime_user_waiting_for_jin_answer_last_seconds = None
        return None

    waited_seconds = max(
        0.0,
        time.monotonic() - started_at,
    )
    context.runtime_user_waiting_for_jin_answer_last_seconds = (
        waited_seconds
    )
    context.runtime_user_waiting_for_jin_answer_total_seconds = (
        float(
            getattr(
                context,
                "runtime_user_waiting_for_jin_answer_total_seconds",
                0.0,
            )
            or 0.0
        )
        + waited_seconds
    )
    context.runtime_user_waiting_for_jin_answer_count = (
        int(
            getattr(
                context,
                "runtime_user_waiting_for_jin_answer_count",
                0,
            )
            or 0
        )
        + 1
    )

    return waited_seconds

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


def apply_runtime_avatar_context(
    context,
    message_data: dict,
):

    avatar_context = message_data.get(
        "runtime_avatar",
        {},
    )

    if not isinstance(
        avatar_context,
        dict,
    ):
        avatar_context = {}

    collapsed = bool(
        avatar_context.get(
            "collapsed",
            False,
        )
    )
    size = normalize_jin_size_dict({
        "width": avatar_context.get(
            "width",
        ),
        "height": avatar_context.get(
            "height",
        ),
    })

    position = normalize_jin_position_dict({
        "x": avatar_context.get("x"),
        "y": avatar_context.get("y"),
    })

    try:
        window_width = int(
            avatar_context.get("window_width")
            or avatar_context.get("windowWidth")
            or 0
        )
        window_height = int(
            avatar_context.get("window_height")
            or avatar_context.get("windowHeight")
            or 0
        )
    except (TypeError, ValueError):
        window_width = 0
        window_height = 0

    speed = normalize_jin_speed_value(
        avatar_context.get("speed")
        or avatar_context.get("speed_px_per_second")
        or avatar_context.get("speedPxPerSecond")
        or ""
    )

    context.runtime_avatar_panel_collapsed = collapsed
    context.runtime_avatar_current_size = (
        size
        if size
        else {}
    )
    context.runtime_avatar_current_position = (
        position
        if position
        else {}
    )
    context.runtime_avatar_window_size = (
        {
            "width": window_width,
            "height": window_height,
        }
        if window_width > 0 and window_height > 0
        else {}
    )
    if speed is not None:
        context.runtime_avatar_move_speed = speed


def build_user_retry_request(
    context,
    message_data: dict | None = None,
) -> dict | None:
    """Rebuild the latest real user request without creating a new user turn."""

    source = getattr(
        context,
        "runtime_last_retryable_request",
        {},
    )
    if not isinstance(source, dict) or not source:
        return None

    recent_turns = getattr(
        context,
        "runtime_recent_turns",
        [],
    )
    if (
        not isinstance(recent_turns, list)
        or not recent_turns
        or not str((recent_turns[-1] or {}).get("jin") or "").strip()
    ):
        return None

    text = str(source.get("text") or "")
    attachments = deepcopy(source.get("attachments") or [])
    if not text.strip() and not attachments:
        return None

    retry_request = {
        "type": "retry_last_response",
        "text": text,
    }
    if attachments:
        retry_request["attachments"] = attachments

    live_request = message_data if isinstance(message_data, dict) else {}
    # Runtime geometry and visible active-memory state are live UI state, not
    # part of the discarded answer. Refresh only those fields on retry.
    for field_name in (
        "runtime_avatar",
        "active_memory_records",
    ):
        if field_name in live_request:
            retry_request[field_name] = deepcopy(live_request[field_name])

    return retry_request


def discard_latest_visible_turn_for_user_retry(
    context,
) -> dict:
    """Remove the answer being replaced from rolling prompt-side history."""

    previous_turn = {}
    recent_turns = getattr(context, "runtime_recent_turns", None)
    if isinstance(recent_turns, list) and recent_turns:
        candidate = recent_turns.pop()
        if isinstance(candidate, dict):
            previous_turn = candidate

    # The previous reasoning belongs to the discarded answer and must not be
    # re-injected beside the explicit retry marker.
    context.runtime_previous_reasoning_content = ""
    context.runtime_previous_reasoning_loop_contents = []

    return previous_turn


def append_runtime_recent_turn(
    context,
    *,
    user_message: str,
    assistant_message: str,
    reasoning: str = "",
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
    reasoning = str(
        reasoning
        or ""
    ).strip()

    if not user_message and not assistant_message:
        return

    turn = {
        "user": user_message,
        "jin": assistant_message,
    }

    if reasoning:
        turn["reasoning"] = reasoning

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

    # An archived session checkout uses the full restored dialogue only to
    # prime the first continuation response. Once that response is committed,
    # normal rolling recent-turn memory takes over.
    if getattr(
        context,
        "runtime_restored_session_dialog",
        "",
    ):
        context.runtime_restored_session_dialog = ""
        context.runtime_restored_session_source_id = ""

    context.runtime_recent_turns = context.runtime_recent_turns[
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
        formatted = user_text
    else:
        formatted = (
            f"{json.dumps(user_text, ensure_ascii=False)} "
            f"[ repeated: {repeated} ]"
        )

    if getattr(
        context,
        "runtime_user_retry_active",
        False,
    ):
        return (
            f"{formatted} "
            "[ user_retry: true; previous_jin_answer_discarded: true; "
            "replace_previous_turn: true ]"
        ).strip()

    return formatted


async def process_message(
    context,
    message_data: dict,
):
    websocket = context.websocket
    logger = context.logger
    action_guard_retry = {}
    is_action_guard_retry = False
    is_user_retry = False
    user_retry_replaced_turn = {}
    retry_source_candidate = {}
    retry_terminal_emitted = False
    reasoning_save_pending = False

    try:

        is_session_restore_resume = bool(
            message_data.get("type") == "archived_session_resume"
            and getattr(
                context,
                "runtime_session_restore_priming",
                False,
            )
        )
        is_user_retry = bool(
            message_data.get("type") == "retry_last_response"
        )
        context.runtime_user_retry_active = is_user_retry
        if is_user_retry:
            context.runtime_user_retry_count = int(
                getattr(context, "runtime_user_retry_count", 0)
                or 0
            ) + 1
            retry_source_candidate = deepcopy(
                getattr(
                    context,
                    "runtime_last_retryable_request",
                    {},
                )
                or {}
            )
            # Retry consumes the previous completed-answer capability. It is
            # restored only if the replacement itself completes successfully.
            context.runtime_last_retryable_request = {}
            user_retry_replaced_turn = (
                discard_latest_visible_turn_for_user_retry(
                    context
                )
            )
        elif message_data.get("type", "message") == "message":
            context.runtime_user_retry_count = 0
            retry_source_candidate = {
                "text": get_message_user_text(message_data),
                "attachments": deepcopy(
                    message_data.get("attachments") or []
                ),
            }
            # The previous answer stops being retryable as soon as a new real
            # user turn starts. The current request is promoted only after its
            # JIN response completes successfully.
            context.runtime_last_retryable_request = {}
        action_guard_retry = normalize_runtime_action_guard_retry(
            message_data.get(
                "runtime_action_guard_retry",
                {},
            )
        )
        context.runtime_action_guard_retry = action_guard_retry
        context.runtime_action_guard_retry_consumed = False
        context.runtime_suppress_chat_content = bool(
            action_guard_retry
        )
        is_action_guard_retry = bool(
            action_guard_retry
        )
        if is_session_restore_resume:
            # The restore tick has no user message, so take the live browser
            # geometry from the resume request before building its context.
            apply_runtime_avatar_context(
                context,
                message_data,
            )
            # Keep restored file IDs pinned for subsequent turns, but do not
            # feed any file payload/image bytes into the hidden restore tick.
            active_attachment_ids = []
        elif is_action_guard_retry:
            active_attachment_ids = list(
                getattr(
                    context,
                    "runtime_attached_file_ids",
                    [],
                )
                or []
            )
        else:
            active_attachment_ids = attachment_ids_from_message_data(
                message_data
            )
            from utils.context.files import unload_project_files
            for removed in set(context.runtime_attached_file_ids or []) - set(active_attachment_ids):
                unload_project_files(context, removed)
            context.runtime_attached_file_ids = list(active_attachment_ids)

        hydrated_active_attachments = hydrate_message_attachments(
            message_data,
            active_attachment_ids,
        )

        user_text = (
            ""
            if is_session_restore_resume
            else build_user_text_with_attachments(
                message_data,
            )
        )

        context.runtime_turn_user_message = user_text
        context.runtime_turn_started_at = time.time()
        begin_user_waiting_for_jin_answer_turn(
            context,
            enabled=bool(
                not is_action_guard_retry
                and not is_session_restore_resume
                and (
                    is_user_retry
                    or message_data.get(
                        "type",
                        "message",
                    ) == "message"
                )
            ),
        )
        context.runtime_turn_counter = (
            getattr(
                context,
                "runtime_turn_counter",
                0,
            )
            + 1
        )
        context.runtime_current_turn_id = (
            f"retry_{context.runtime_turn_counter:06d}"
            if is_action_guard_retry
            else (
                f"user_retry_{context.runtime_turn_counter:06d}"
                if is_user_retry
                else f"turn_{context.runtime_turn_counter:06d}"
            )
        )
        context.runtime_current_sequence_turn_id = (
            context.runtime_current_turn_id
        )
        context.runtime_current_sequence_started_at = (
            context.runtime_turn_started_at
        )
        if is_action_guard_retry:
            context.runtime_turn_attachments = deepcopy(
                hydrated_active_attachments
            )
        else:
            context.runtime_turn_attachments = deepcopy(
                hydrated_active_attachments
            )
            context.runtime_current_sequence_attachments = deepcopy(
                hydrated_active_attachments
            )
            context.runtime_current_sequence_attachments_turn_id = (
                context.runtime_current_sequence_turn_id
            )
        context.runtime_turn_assistant_response = ""
        context.runtime_turn_reasoning_log_path = ""
        context.runtime_turn_reasoning_content = ""
        context.runtime_active_action_markers = []
        context.runtime_turn_aborted_actions = []
        context.runtime_turn_abort_requested = False
        context.runtime_turn_discard_requested = False
        context.runtime_turn_interrupted_memory_update_scheduled = False
        context.runtime_turn_interrupted = False
        context.runtime_turn_interruption_reason = ""
        context.runtime_turn_interruption_quote = ""
        context.runtime_turn_memory_user_message = ""
        context.runtime_avatar_panel_collapsed = False
        context.runtime_avatar_current_size = {}
        context.runtime_avatar_current_position = {}
        context.runtime_avatar_window_size = {}
        context.runtime_avatar_move_speed = 900
        context.runtime_reasoning_recovery_pending = False
        context.runtime_context_limit_recovery_pending = False
        context.runtime_context_limit_stage = ""
        context.runtime_context_limit_kind = ""
        context.runtime_context_limit_finish_reason = ""
        if (
            not is_action_guard_retry
            and not is_session_restore_resume
        ):
            if not is_user_retry:
                apply_user_idle_context(
                    context,
                    message_data,
                )

            apply_active_memory_records(
                context,
                message_data,
            )

            if not is_user_retry:
                apply_runtime_pattern_context(
                    context,
                    message_data,
                )

            apply_runtime_avatar_context(
                context,
                message_data,
            )

            context.runtime_turn_memory_user_message = (
                format_runtime_memory_user_message(
                    context,
                    user_text,
                )
            )

            if not is_user_retry:
                context.user_message_count += 1
                context.current_session_user_message_count += 1
                # Tag auto-load is driven only by the text the user typed.
                # Attachment text still stays in ``user_text`` and reaches JIN as
                # context, but it must never behave like a tag command.
                await load_delayed_memory_by_tags(
                    context,
                    get_message_user_text(
                        message_data
                    ),
                )

        if (
            not is_action_guard_retry
            and not is_session_restore_resume
            and not is_user_retry
        ):
            try:
                append_chat_log_entry(
                    context,
                    role="user",
                    text=user_text,
                )
            except Exception as error:
                await logger.log_system(
                    "[CHAT_LOG] local user message save failed: "
                    + str(error)
                )

        state = AgentState(
            user_input=user_text
        )
        if is_session_restore_resume:
            state.metadata["session_restore_resume"] = True
        if is_user_retry:
            state.metadata["user_retry"] = True

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
            # This is only candidate eligibility. The client waits for
            # agent_runtime_end before making the bubble long-tap retryable.
            "retryable_response": bool(
                not is_action_guard_retry
                and not is_session_restore_resume
                and (
                    is_user_retry
                    or message_data.get("type", "message") == "message"
                )
            ),
        })

        reasoning_save_pending = True
        await runtime.run(
            state,
            context,
        )
        finish_user_waiting_for_jin_answer_turn(
            context
        )

        try:
            save_turn_reasoning(
                context,
                getattr(
                    context,
                    "runtime_turn_reasoning_content",
                    "",
                ),
            )
            reasoning_save_pending = False
        except Exception as error:
            await logger.log_system(
                "[CHAT_LOG] reasoning save failed: "
                + str(error)
            )

        if (
            action_guard_retry
            and not getattr(
                context,
                "runtime_action_guard_retry_consumed",
                False,
            )
        ):
            await emit_runtime_action_guard_confirmation_failure(
                context,
                {
                    **action_guard_retry,
                    "decision": "continue",
                },
                error="runtime_action_confirmation_retry_not_emitted",
            )
            retry_terminal_emitted = True

        if getattr(
            context,
            "runtime_turn_discard_requested",
            False,
        ):
            return

        assistant_message = (
            state.brain_response
            or context.runtime_turn_assistant_response
        )

        # The last visible message_end already persisted a browser-side preview
        # of this turn. Commit the same completed turn to the raw archive and
        # runtime history before agent_runtime_end so both bootstrap sources
        # converge immediately.
        if not is_action_guard_retry:
            try:
                if is_user_retry:
                    replace_latest_chat_log_entry(
                        context,
                        role="jin",
                        text=assistant_message,
                    )
                else:
                    append_chat_log_entry(
                        context,
                        role="jin",
                        text=assistant_message,
                    )
            except Exception as error:
                await logger.log_system(
                    "[CHAT_LOG] local JIN message save failed: "
                    + str(error)
                )

        assistant_created_at = time.time()
        if not is_action_guard_retry:
            append_runtime_recent_turn(
                context,
                user_message=user_text,
                assistant_message=assistant_message,
                reasoning=getattr(
                    context,
                    "runtime_turn_reasoning_content",
                    "",
                ),
                user_created_at=(
                    user_retry_replaced_turn.get("user_created_at")
                    if is_user_retry
                    and isinstance(user_retry_replaced_turn, dict)
                    else getattr(
                        context,
                        "runtime_turn_started_at",
                        None,
                    )
                ),
                assistant_created_at=assistant_created_at,
            )
        if not is_action_guard_retry and not is_user_retry:
            context.assistant_message_count += 1
            if not is_session_restore_resume:
                context.current_session_assistant_message_count += 1
            context.turn_number += 1

        if not is_action_guard_retry:
            try:
                await record_lt_reasoning_fact_mentions(
                    context,
                    getattr(
                        context,
                        "runtime_turn_reasoning_content",
                        "",
                    ),
                    assistant_message,
                )
            except Exception as error:
                await logger.log_system(
                    "[MEMORY:L-T] turn mention tracking failed: "
                    + str(error)
                )

        completed_session_snapshot = (
            build_runtime_session_checkpoint(context)
        )

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

        retryable_response = bool(
            not is_action_guard_retry
            and not is_session_restore_resume
            and not getattr(
                context,
                "runtime_turn_interrupted",
                False,
            )
            and str(assistant_message or "").strip()
        )

        if retryable_response:
            context.runtime_last_retryable_request = deepcopy(
                retry_source_candidate
            )

        completed_turn_commit = bool(
            not is_action_guard_retry
            and not is_session_restore_resume
            and not getattr(
                context,
                "runtime_turn_interrupted",
                False,
            )
            and not getattr(
                context,
                "runtime_turn_discard_requested",
                False,
            )
            and str(user_text or "").strip()
        )

        await logger.log_system(
            "[WS] agent runtime end"
        )

        await websocket.send_json({
            "type": "agent_runtime_end",
            "retryable_response": retryable_response,
            "session_snapshot": completed_session_snapshot,
            "completed_turn_commit": completed_turn_commit,
        })

        if is_session_restore_resume:
            # The Brain node consumes restore priming immediately after the
            # first response and replays archived resources through the real
            # runtime-action dispatcher. Keep only a defensive cleanup here;
            # never mutate resource state or emit a second store snapshot from
            # the websocket tail, because that used to race the action/avatar
            # UI and make the load visible only after L1 completed.
            context.runtime_session_restore_pending_loaded_memory_ids = []
            context.runtime_session_restore_pending_attached_file_ids = []
            context.runtime_session_restore_priming = False
            context.runtime_session_restore_reasoning_dump = ""
            context.runtime_session_restore_lt_fact_ids = []
            context.runtime_session_restore_delayed_memory_metadata = []
            context.runtime_session_restore_attached_file_metadata = []

        if is_action_guard_retry:
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
            # Commit the interrupted turn through the ordinary L1 path.
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

    except asyncio.CancelledError:

        if (
            action_guard_retry
            and not retry_terminal_emitted
            and not getattr(
                context,
                "runtime_action_guard_retry_consumed",
                False,
            )
        ):
            await emit_runtime_action_guard_confirmation_failure(
                context,
                {
                    **action_guard_retry,
                    "decision": "continue",
                },
                error="runtime_action_confirmation_retry_cancelled",
            )

        await logger.log_runtime(
            "Agent runtime task cancelled."
        )

        raise

    except Exception as error:

        if (
            action_guard_retry
            and not retry_terminal_emitted
            and not getattr(
                context,
                "runtime_action_guard_retry_consumed",
                False,
            )
        ):
            await emit_runtime_action_guard_confirmation_failure(
                context,
                {
                    **action_guard_retry,
                    "decision": "continue",
                },
                error="runtime_action_confirmation_retry_failed",
            )

        await handle_fatal_runtime_error(
            context,
            component="agent_runtime",
            exception=error,
        )

    finally:

        if reasoning_save_pending:
            try:
                save_turn_reasoning(
                    context,
                    getattr(context, "runtime_turn_reasoning_content", ""),
                )
            except Exception as error:
                await logger.log_system(
                    "[CHAT_LOG] interrupted reasoning save failed: " + str(error)
                )

        # Normal turns finish immediately after AgentRuntime returns. This is
        # only the fallback for cancellation/error paths that leave a visible
        # reasoning stream without reaching that point.
        finish_user_waiting_for_jin_answer_turn(
            context
        )

        if is_user_retry:
            context.runtime_user_retry_active = False

        if is_action_guard_retry:
            context.runtime_suppress_chat_content = False
            context.runtime_action_guard_retry = {}


# ---------------------------------------------------------
# CANCEL CURRENT TASK
# ---------------------------------------------------------
