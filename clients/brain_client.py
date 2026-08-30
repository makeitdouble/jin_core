import asyncio
import json
import re
import uuid

from config_loader import (
    config,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
    RUNTIME_ACTION_WEB_SEARCH,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    get_runtime_action_private_marker,
    runtime_action_has_close_tag,
)

from clients.errors import (
    format_client_error,
)

from rules.brain_context_builder import (
    build_brain_context,
    get_enabled_runtime_actions,
)

from utils.brain_client_utils import (
    apply_runtime_action_calls,
    build_pending_asset_action_preview,
    find_active_memory_slot_record,
    flush_pending_active_memory_delete_failure_history,
    log_runtime_action_marker_removals,
    should_execute_save_delayed_memory,
)
from runtime.action_guard import (
    confirm_runtime_action_guards,
    get_action_guard_display_id,
)
from utils.session_actions_history import (
    attach_session_action_jin_message_since,
    build_asset_action_marker_text,
    emit_session_actions_update,
    replace_session_action_history_since,
    upsert_session_action_marker_history_since,
)

from clients.response_extractor import (
    ResponseExtractor,
)

from runtime.client import (
    LMStudioAPIError,
)
from runtime.state import BRAIN_RUNTIME_ID


from utils.actions import (
    build_runtime_action_id,
    emit_runtime_action_counter_updates,
    RuntimeActionCounter,
    RuntimeActionRepetitionGuard,
    RuntimeActionResult,
    RuntimeActionStreamFilter,
    extract_active_memory_delete_slot_id,
    extract_runtime_actions,
    normalize_jin_color_payload,
    normalize_jin_size_payload,
)
from utils.runtime_todo import (
    has_active_runtime_todo,
)
from utils.current_context_window import (
    prepare_current_context_window_prompt,
)
from utils.skills_asset_utils import (
    normalize_skill_name,
)


def get_brain_runtime_id() -> str:
    return BRAIN_RUNTIME_ID


def get_response_enabled_runtime_actions(
    runtime_actions=None,
    user_message: str = "",
) -> tuple[str, ...]:

    enabled_actions = list(
        get_enabled_runtime_actions(
            runtime_actions
        )
    )

    if (
        RUNTIME_ACTION_SAVE_DELAYED_MEMORY
        in enabled_actions
        and not should_execute_save_delayed_memory(
            user_message
        )
    ):
        enabled_actions.remove(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY
        )

    return tuple(
        enabled_actions
    )


async def emit_active_memory_records_update_if_dirty(
    context,
) -> None:

    if context is None:
        return

    if not getattr(
        context,
        "runtime_active_memory_records_dirty",
        False,
    ):
        return

    context.runtime_active_memory_records_dirty = False

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
        "type": "active_memory_records_update",
        "active_memory_records": list(
            getattr(
                context,
                "active_memory_records",
                [],
            )
            or []
        ),
    })


# ---------------------------------------------------------
# PAYLOAD
# ---------------------------------------------------------

def build_brain_payload(
    text: str,
    context=None,
) -> str:

    return text


def build_brain_user_prompt_content(
    text: str,
    context=None,
):

    image_input_enabled = bool(
        getattr(
            config,
            "BRAIN_IMAGE_INPUT_ENABLED",
            False,
        )
    )

    if not image_input_enabled:
        return text

    content = [
        {
            "type": "text",
            "text": text,
        },
    ]

    for attachment in (
        getattr(
            context,
            "runtime_turn_attachments",
            [],
        )
        or []
    ):

        if not isinstance(
            attachment,
            dict,
        ):
            continue

        if (
            attachment.get(
                "kind",
            )
            != "image"
        ):
            continue

        data_url = str(
            attachment.get(
                "data_url",
                "",
            )
            or ""
        )

        if not data_url.startswith(
            "data:image/",
        ):
            continue

        content.append({
            "type": "image_url",
            "image_url": {
                "url": data_url,
            },
        })

    if len(content) == 1:
        return text

    return content


def build_brain_context_snapshot(
    *,
    context=None,
    system_prompt: str,
    user_prompt: str,
    runtime_actions=None,
    include_previous_reasoning: bool = True,
) -> dict:

    snapshot = {
        "context_role": "brain",
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }

    if not has_active_runtime_todo(
        context
    ):
        return snapshot

    snapshot["hide_internal_action_rules"] = True
    snapshot["visible_system_prompt"] = build_brain_context(
        context,
        runtime_actions,
        user_input=user_prompt,
        include_runtime_action_instructions=False,
        include_previous_reasoning=include_previous_reasoning,
    )

    return snapshot


# ---------------------------------------------------------
# NORMAL REQUEST
# ---------------------------------------------------------

async def ask_brain(
    *,
    client,
    text: str,
    context=None,
    runtime_actions=None,
) -> str:

    brain_payload = (
        build_brain_payload(
            text,
            context=context,
        )
    )

    system_prompt = (
        build_brain_context(
            context,
            runtime_actions,
            user_input=brain_payload,
            commit_active_memory_refresh=True,
        )
    )

    await emit_active_memory_records_update_if_dirty(
        context
    )

    model_user_prompt = build_brain_user_prompt_content(
        brain_payload,
        context=context,
    )

    prepared_context_window = await prepare_current_context_window_prompt(
        client=client,
        context=context,
        runtime_id=get_brain_runtime_id(),
        system_prompt=system_prompt,
        user_prompt=model_user_prompt,
        force_refresh=True,
    )
    system_prompt = prepared_context_window.system_prompt

    action_context_snapshot = build_brain_context_snapshot(
        context=context,
        system_prompt=system_prompt,
        user_prompt=brain_payload,
        runtime_actions=runtime_actions,
    )
    runtime_message_id = str(
        uuid.uuid4()
    )

    # -----------------------------------------------------
    # BRAIN
    # -----------------------------------------------------

    try:

        result = await client.ask(
            system_prompt=system_prompt,
            user_prompt=model_user_prompt,
            temperature=config.BRAIN_TEMPERATURE,
            max_tokens=None,
        )

        returned_model = (
            ResponseExtractor
            .extract_model(
                result
            )
        )

        if (
            returned_model
            != config.BRAIN_MODEL_UID
        ):

            raise RuntimeError(
                f"Wrong model loaded. "
                f"Expected "
                f"'{config.BRAIN_MODEL_UID}', "
                f"got "
                f"'{returned_model}'"
            )

        reasoning = (
            ResponseExtractor
            .extract_reasoning_text(
                result
            )
        )

        content = (
            ResponseExtractor
            .extract_content_text(
                result
            )
        )

        enabled_actions = get_response_enabled_runtime_actions(
            runtime_actions,
            text,
        )

        content_actions = extract_runtime_actions(
            content,
            enabled_actions=enabled_actions,
        )

        await log_runtime_action_marker_removals(
            context,
            content_actions,
            source="brain content",
        )

        (
            confirmed_action_ids,
            rejected_action_ids,
            guard_confirmation_ids,
            action_display_ids,
        ) = await confirm_runtime_action_guards(
            context,
            content_actions.actions,
            user_message=text,
            context_snapshot=action_context_snapshot,
        )

        await apply_runtime_action_calls(
            context,
            content_actions.actions,
            user_message=text,
            context_snapshot=action_context_snapshot,
            assistant_message=content,
            confirmed_action_ids=confirmed_action_ids,
            rejected_action_ids=rejected_action_ids,
            guard_confirmation_ids=guard_confirmation_ids,
            action_display_ids=action_display_ids,
            runtime_message_id=runtime_message_id,
        )

        if content_actions.text:
            return content_actions.text

        reasoning_actions = extract_runtime_actions(
            reasoning,
            enabled_actions=enabled_actions,
        )

        await log_runtime_action_marker_removals(
            context,
            reasoning_actions,
            source="brain reasoning fallback",
        )

        return reasoning_actions.text

    except LMStudioAPIError:

        raise

    except Exception as error:

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )


# ---------------------------------------------------------
# STREAM REQUEST
# ---------------------------------------------------------

async def ask_brain_stream(
    *,
    client,
    text: str,
    context,
    system_prompt: str | None = None,
    brain_payload: str | None = None,
    runtime_actions=None,
    filter_runtime_actions: bool = True,
):

    resolved_brain_payload: str = (
        brain_payload
        if brain_payload is not None
        else build_brain_payload(
            text,
            context=context,
        )
    )

    resolved_system_prompt: str = (
        system_prompt
        or build_brain_context(
            context,
            runtime_actions,
            user_input=resolved_brain_payload,
            commit_active_memory_refresh=True,
        )
    )

    if system_prompt is None:
        await emit_active_memory_records_update_if_dirty(
            context
        )

    enabled_actions = get_response_enabled_runtime_actions(
        runtime_actions,
        text,
    )

    model_user_prompt = build_brain_user_prompt_content(
        resolved_brain_payload,
        context=context,
    )

    prepared_context_window = await prepare_current_context_window_prompt(
        client=client,
        context=context,
        runtime_id=get_brain_runtime_id(),
        system_prompt=resolved_system_prompt,
        user_prompt=model_user_prompt,
        force_refresh=True,
    )
    resolved_system_prompt = prepared_context_window.system_prompt

    loaded_skill_marker_names = {
        normalize_skill_name(
            skill.get(
                "name",
                "",
            )
            if isinstance(
                skill,
                dict,
            )
            else skill
        )
        for skill in (
            getattr(
                context,
                "runtime_loaded_skills",
                [],
            )
            or []
        )
    }
    loaded_skill_marker_names.discard(
        ""
    )

    def preserve_duplicate_load_skill_marker(
        _raw_marker,
        action,
    ) -> bool:

        if action.name != RUNTIME_ACTION_LOAD_SKILL:
            return False

        requested_skill = normalize_skill_name(
            action.payload
        )

        if not requested_skill:
            return False

        if requested_skill in loaded_skill_marker_names:
            return True

        loaded_skill_marker_names.add(
            requested_skill
        )

        return False

    content_filter = RuntimeActionStreamFilter(
        enabled_actions=enabled_actions,
        preserve_action_marker=preserve_duplicate_load_skill_marker,
        repetition_guard=RuntimeActionRepetitionGuard(),
        #preserve_action_text=True
    )
    stop_for_runtime_action = False
    delayed_memory_bubble_started = False
    active_memory_pending_bubble_ids = []
    deep_web_search_pending_bubble_ids = []
    update_lt_facts_pending_bubble_ids = []
    asset_action_bubble_started = False
    asset_action_bubble_id = ""
    asset_action_bubble_text = ""
    action_context_snapshot = build_brain_context_snapshot(
        context=context,
        system_prompt=resolved_system_prompt,
        user_prompt=resolved_brain_payload,
        runtime_actions=runtime_actions,
    )
    runtime_message_id = str(
        uuid.uuid4()
    )
    session_action_history_start = len(
        getattr(
            context,
            "runtime_session_action_history",
            [],
        )
        or []
    )
    runtime_action_event_start = len(
        getattr(
            context,
            "runtime_action_events",
            [],
        )
        or []
    )
    action_counter = RuntimeActionCounter()
    deleted_active_memory_display_payloads = {}
    raw_content_parts = []
    raw_model_output_parts = []
    session_action_message_parts = []
    session_action_message_content = ""
    session_action_marker_seen = False
    confirmed_action_guard_names = set()
    rejected_action_guard_names = set()
    action_guard_display_state = {}
    session_action_history_finalized = False

    def capture_observed_action_markers(
        result,
    ):

        return action_counter.record(
            getattr(
                result,
                "observed_actions",
                (),
            )
        )

    def capture_session_action_message_preview(
        result,
        counter_entries,
    ) -> None:

        nonlocal session_action_message_content
        nonlocal session_action_marker_seen

        if session_action_marker_seen:
            return

        visible_text = str(
            getattr(
                result,
                "text",
                "",
            )
            or ""
        )

        if visible_text:
            session_action_message_parts.append(
                visible_text
            )

        if not counter_entries:
            return

        session_action_marker_seen = True
        session_action_message_content = "".join(
            session_action_message_parts
        ).strip()

    def build_pending_asset_action_stream_preview(
        pending_text: str,
    ) -> dict:

        matches = tuple(
            re.finditer(
                r"<\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>",
                str(
                    pending_text
                    or ""
                ),
                re.IGNORECASE,
            )
        )

        if not matches:
            return {}

        body = str(
            pending_text
            or ""
        )[matches[-1].end():]

        def extract_string_field(
            field: str,
        ) -> str:
            match = re.search(
                rf'"{re.escape(field)}"\s*:\s*"(?P<value>[^"]*)"',
                body,
                re.IGNORECASE | re.DOTALL,
            )

            return (
                match.group("value").strip()
                if match
                else ""
            )

        action = extract_string_field(
            "action"
        )
        if not action:
            return {}

        preview_payload = {
            "action": action,
        }

        for field in (
            "path",
            "output_file",
            "attachment",
            "mode",
        ):
            value = extract_string_field(
                field
            )
            if value:
                preview_payload[field] = value

        return build_pending_asset_action_preview(
            json.dumps(
                preview_payload
            )
        )

    def get_applied_jin_colors() -> list[str]:

        current_turn_id = str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        colors = []
        events = getattr(
            context,
            "runtime_action_events",
            [],
        ) or []

        for event in events[
            runtime_action_event_start:
        ]:
            if not isinstance(
                event,
                dict,
            ):
                continue

            if str(
                event.get("name")
                or event.get("action")
                or ""
            ).strip().casefold() != "jin_color":
                continue

            if (
                str(
                    event.get("status")
                    or ""
                ).strip().casefold()
                == "failed"
                or event.get("error")
            ):
                continue

            event_turn_id = str(
                event.get("runtime_turn_id")
                or ""
            ).strip()

            if (
                current_turn_id
                and event_turn_id
                and event_turn_id != current_turn_id
            ):
                continue

            color = normalize_jin_color_payload(
                event.get("color")
                or event.get("payload")
                or ""
            )

            if color:
                colors.append(
                    color
                )

        return colors

    def get_applied_jin_sizes() -> list[str]:

        current_turn_id = str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        sizes = []
        events = getattr(
            context,
            "runtime_action_events",
            [],
        ) or []

        for event in events[
            runtime_action_event_start:
        ]:
            if not isinstance(
                event,
                dict,
            ):
                continue

            if str(
                event.get("name")
                or event.get("action")
                or ""
            ).strip().casefold() != "jin_size":
                continue

            if (
                str(
                    event.get("status")
                    or ""
                ).strip().casefold()
                == "failed"
                or event.get("error")
            ):
                continue

            event_turn_id = str(
                event.get("runtime_turn_id")
                or ""
            ).strip()

            if (
                current_turn_id
                and event_turn_id
                and event_turn_id != current_turn_id
            ):
                continue

            size = normalize_jin_size_payload(
                event.get("size")
                or event.get("payload")
                or ""
            )

            if size:
                sizes.append(
                    size
                )

        return sizes

    def get_delete_active_memory_display_payload(
        payload,
    ) -> str:

        normalized_payload = str(
            payload
            or ""
        ).strip()
        active_memory_id = extract_active_memory_delete_slot_id(
            normalized_payload
        )

        if not active_memory_id:
            return normalized_payload

        cached_content = deleted_active_memory_display_payloads.get(
            active_memory_id,
            "",
        )

        if cached_content:
            return cached_content

        record = find_active_memory_slot_record(
            context,
            active_memory_id,
        )
        content = re.sub(
            r"^\s*active_memory(?:_\d+)?\s*:\s*",
            "",
            str(record or ""),
            flags=re.IGNORECASE,
        )
        content = re.sub(
            r"\s*\[[^\]]+\]\s*",
            " ",
            content,
        )
        content = re.sub(
            r"\s+",
            " ",
            content,
        ).strip()

        if content:
            deleted_active_memory_display_payloads[
                active_memory_id
            ] = content
            return content

        return normalized_payload

    def get_action_counter_display_payloads() -> dict:

        display_payloads = {}
        applied_colors = get_applied_jin_colors()

        if applied_colors:
            display_payloads[
                RUNTIME_ACTION_JIN_COLOR
            ] = applied_colors

        applied_sizes = get_applied_jin_sizes()

        if applied_sizes:
            display_payloads[
                RUNTIME_ACTION_JIN_SIZE
            ] = applied_sizes

        for delete_entry in action_counter.entries():
            if (
                delete_entry is None
                or delete_entry.name != RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
                or not delete_entry.payloads
            ):
                continue

            display_payloads[(
                delete_entry.name,
                delete_entry.identity,
            )] = [
                get_delete_active_memory_display_payload(
                    payload
                )
                for payload in delete_entry.payloads
            ]

        delayed_memory_display_actions = (
            RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
            RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
        )

        delayed_memory_entries = [
            (
                action_name,
                action_counter.get(
                    action_name
                ),
            )
            for action_name in delayed_memory_display_actions
        ]

        if any(
            entry is not None
            and entry.payloads
            for _, entry in delayed_memory_entries
        ):
            from utils.brain_client_utils import (
                get_delayed_memory_reports,
                normalize_delayed_memory_action_id,
            )

            reports = get_delayed_memory_reports(
                context
            )

            for action_name, entry in delayed_memory_entries:
                if (
                    entry is None
                    or not entry.payloads
                ):
                    continue

                display_values = []

                for payload in entry.payloads:
                    normalized_payload = str(
                        payload
                        or ""
                    ).strip()
                    report_id = normalize_delayed_memory_action_id(
                        normalized_payload
                    )
                    report = reports.get(
                        report_id,
                    )
                    title = (
                        str(
                            report.get(
                                "title",
                                "",
                            )
                            or ""
                        ).strip()
                        if isinstance(
                            report,
                            dict,
                        )
                        else ""
                    )
                    display_values.append(
                        title
                        or normalized_payload
                        or report_id
                    )

                display_payloads[
                    action_name
                ] = display_values

        return display_payloads

    async def emit_action_counter_updates(
        entries,
        *,
        status: str = "counted",
        detail: str = "",
    ) -> None:

        await emit_runtime_action_counter_updates(
            context,
            entries,
            context_snapshot=(
                action_context_snapshot
            ),
            display_payloads=(
                get_action_counter_display_payloads()
            ),
            status=status,
            detail=detail,
            runtime_message_id=runtime_message_id,
        )

    async def sync_session_action_marker_history() -> None:

        marker_actions = action_counter.marker_actions(
            display_payloads=(
                get_action_counter_display_payloads()
            ),
        )

        if not marker_actions:
            return

        updated = upsert_session_action_marker_history_since(
            context,
            session_action_history_start,
            marker_actions,
        )
        message_attached = (
            attach_session_action_jin_message_since(
                context,
                session_action_history_start,
                session_action_message_content,
            )
            if session_action_message_content
            else False
        )

        if not updated and not message_attached:
            return

        await emit_session_actions_update(
            context,
            current_sequence=True,
        )

    async def finalize_session_action_history() -> None:

        nonlocal session_action_history_finalized

        if session_action_history_finalized:
            return

        session_action_history_finalized = True

        await emit_action_counter_updates(
            action_counter.entries(),
            status="counter_final",
        )

        marker_actions = action_counter.marker_actions(
            display_payloads=(
                get_action_counter_display_payloads()
            ),
        )

        history = getattr(
            context,
            "runtime_session_action_history",
            None,
        )
        saved_delayed_memory_items = []
        safe_start_index = 0

        if isinstance(history, list):
            safe_start_index = max(
                0,
                min(
                    int(
                        session_action_history_start
                        or 0
                    ),
                    len(history),
                ),
            )
            saved_delayed_memory_items = [
                dict(item)
                for item in history[
                    safe_start_index:
                ]
                if isinstance(item, dict)
                and item.get(
                    "runtime_session_action_marker_item"
                ) is not True
                and str(
                    item.get("text", "")
                    or ""
                ).strip().startswith(
                    "Delayed memory saved:"
                )
            ]

        if saved_delayed_memory_items:
            remaining_marker_actions = [
                action
                for action in marker_actions
                if str(
                    action.get("name", "")
                    or ""
                ).strip().upper()
                != RUNTIME_ACTION_SAVE_DELAYED_MEMORY
            ]

            if remaining_marker_actions:
                replace_session_action_history_since(
                    context,
                    session_action_history_start,
                    remaining_marker_actions,
                )
            else:
                del history[safe_start_index:]

            history.extend(
                saved_delayed_memory_items
            )
        else:
            replace_session_action_history_since(
                context,
                session_action_history_start,
                marker_actions,
            )

        if marker_actions and session_action_message_content:
            attach_session_action_jin_message_since(
                context,
                session_action_history_start,
                session_action_message_content,
            )

        flush_pending_active_memory_delete_failure_history(
            context
        )

        await emit_session_actions_update(
            context,
            current_sequence=True,
        )

    async def emit_delayed_memory_bubble_started():

        nonlocal delayed_memory_bubble_started

        if delayed_memory_bubble_started:
            return

        pending = str(
            getattr(
                content_filter,
                "pending",
                "",
            )
            or ""
        ).upper()

        delayed_memory_marker = get_runtime_action_private_marker(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY
        ).upper()

        if (
            not delayed_memory_marker
            or delayed_memory_marker not in pending
        ):
            return

        delayed_memory_bubble_started = True

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

        pending_ids = getattr(
            context,
            "runtime_pending_delayed_memory_action_ids",
            None,
        )

        if not isinstance(
            pending_ids,
            list,
        ):
            pending_ids = []
            context.runtime_pending_delayed_memory_action_ids = (
                pending_ids
            )

        current_sequence = max(
            int(
                getattr(
                    context,
                    "runtime_delayed_memory_action_sequence",
                    0,
                )
                or 0
            ),
            len(
                getattr(
                    context,
                    "delayed_memory_reports",
                    {},
                )
                or {}
            ),
            len([
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
                ) == "save_delayed_memory"
            ]),
        )
        next_sequence = current_sequence + 1
        context.runtime_delayed_memory_action_sequence = (
            next_sequence
        )
        action_id = build_runtime_action_id(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
            next_sequence,
        )
        pending_ids.append(
            action_id
        )

        payload = {
            "type": "runtime_action",
            "action": "save_delayed_memory",
            "id": action_id,
            "status": "started",
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY
            ),
            "text": build_runtime_action_display_text(
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY
            ),
        }

        if action_context_snapshot:
            payload["context"] = action_context_snapshot

        await emit(
            payload
        )

    async def emit_active_memory_bubble_started(
        result,
    ):

        started_actions = tuple(
            getattr(
                result,
                "started_actions",
                (),
            )
            or ()
        )

        started_count = sum(
            1
            for action in started_actions
            if action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
        )

        if not started_count:
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

        for _ in range(started_count):
            sequence = int(
                getattr(
                    context,
                    "runtime_active_memory_action_sequence",
                    0,
                )
                or 0
            ) + 1
            context.runtime_active_memory_action_sequence = sequence

            action_id = build_runtime_action_id(
                RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
                sequence,
            )
            active_memory_pending_bubble_ids.append(
                action_id
            )

            payload = {
                "type": "runtime_action",
                "action": "save_active_memory",
                "id": action_id,
                "status": "started",
                "runtime_message_id": runtime_message_id,
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
                ),
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
                ),
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
                ),
            }

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

            await emit(
                payload
            )

    def assign_active_memory_bubble_ids(
        actions,
        action_display_ids,
    ):

        for action in actions:
            if action.name != RUNTIME_ACTION_SAVE_ACTIVE_MEMORY:
                continue

            action_id = (
                active_memory_pending_bubble_ids.pop(0)
                if active_memory_pending_bubble_ids
                else ""
            )

            if action_id:
                action_display_ids[id(action)] = action_id

    async def emit_deep_web_search_bubble_started(
        result,
    ):

        started_actions = tuple(
            getattr(
                result,
                "started_actions",
                (),
            )
            or ()
        )

        started_count = sum(
            1
            for action in started_actions
            if action.name == RUNTIME_ACTION_DEEP_WEB_SEARCH
        )

        if not started_count:
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

        existing_count = sum(
            1
            for event in getattr(
                context,
                "runtime_action_events",
                [],
            )
            or []
            if isinstance(event, dict)
            and event.get("name")
            == RUNTIME_ACTION_DEEP_WEB_SEARCH.lower()
        )

        for _ in range(started_count):
            sequence = max(
                int(
                    getattr(
                        context,
                        "runtime_deep_web_search_action_sequence",
                        0,
                    )
                    or 0
                ),
                existing_count,
            ) + 1
            context.runtime_deep_web_search_action_sequence = sequence
            existing_count = sequence

            action_id = build_runtime_action_id(
                RUNTIME_ACTION_DEEP_WEB_SEARCH,
                sequence,
            )
            deep_web_search_pending_bubble_ids.append(
                action_id
            )

            payload = {
                "type": "runtime_action",
                "action": RUNTIME_ACTION_DEEP_WEB_SEARCH.lower(),
                "id": action_id,
                "status": "started",
                "runtime_message_id": runtime_message_id,
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_DEEP_WEB_SEARCH
                ),
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_DEEP_WEB_SEARCH
                ),
                "scene_effect": "search",
                "deep_search_parent": True,
                "deep_search_payload_ready": False,
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_DEEP_WEB_SEARCH
                ),
            }

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

            await emit(
                payload
            )

    def assign_deep_web_search_bubble_ids(
        actions,
        action_display_ids,
    ):

        for action in actions:
            if action.name != RUNTIME_ACTION_DEEP_WEB_SEARCH:
                continue

            action_id = (
                deep_web_search_pending_bubble_ids.pop(0)
                if deep_web_search_pending_bubble_ids
                else ""
            )

            if action_id:
                action_display_ids[id(action)] = action_id

    async def emit_update_lt_facts_bubble_started(
        result,
    ):

        started_actions = tuple(
            getattr(
                result,
                "started_actions",
                (),
            )
            or ()
        )

        started_count = sum(
            1
            for action in started_actions
            if action.name == RUNTIME_ACTION_UPDATE_LT_FACTS
        )

        if not started_count:
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

        for _ in range(started_count):
            sequence = int(
                getattr(
                    context,
                    "runtime_update_lt_facts_action_sequence",
                    0,
                )
                or 0
            ) + 1
            context.runtime_update_lt_facts_action_sequence = sequence

            action_id = build_runtime_action_id(
                RUNTIME_ACTION_UPDATE_LT_FACTS,
                sequence,
            )
            update_lt_facts_pending_bubble_ids.append(
                action_id
            )

            payload = {
                "type": "runtime_action",
                "action": "update_lt_facts",
                "id": action_id,
                "status": "started",
                "runtime_message_id": runtime_message_id,
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_UPDATE_LT_FACTS
                ),
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_UPDATE_LT_FACTS
                ),
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_UPDATE_LT_FACTS
                ),
            }

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

            await emit(
                payload
            )

    def assign_update_lt_facts_bubble_ids(
        actions,
        action_display_ids,
    ):

        for action in actions:
            if action.name != RUNTIME_ACTION_UPDATE_LT_FACTS:
                continue

            action_id = (
                update_lt_facts_pending_bubble_ids.pop(0)
                if update_lt_facts_pending_bubble_ids
                else ""
            )

            if action_id:
                action_display_ids[id(action)] = action_id


    async def emit_rejected_update_lt_facts_bubble_finished(
        result,
    ):

        removed_update_markers = sum(
            1
            for marker in (
                getattr(result, "removed_markers", ())
                or ()
            )
            if re.search(
                r"<\s*UPDATE_LT_FACTS(?:\s|>)",
                str(marker or ""),
                flags=re.IGNORECASE,
            )
        )
        parsed_update_actions = sum(
            1
            for action in (
                getattr(result, "observed_actions", ())
                or ()
            )
            if action.name == RUNTIME_ACTION_UPDATE_LT_FACTS
        )
        rejected_count = max(
            0,
            removed_update_markers - parsed_update_actions,
        )

        if not rejected_count:
            return

        emitter = getattr(context, "emitter", None)
        emit = getattr(emitter, "emit", None)

        for _ in range(rejected_count):
            action_id = (
                update_lt_facts_pending_bubble_ids.pop(0)
                if update_lt_facts_pending_bubble_ids
                else ""
            )

            if not action_id or emit is None:
                continue

            payload = {
                "type": "runtime_action",
                "action": "update_lt_facts",
                "id": action_id,
                "status": "failed",
                "runtime_message_id": runtime_message_id,
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_UPDATE_LT_FACTS
                ),
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_UPDATE_LT_FACTS
                ),
                "detail": "Invalid L-T update note was ignored.",
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_UPDATE_LT_FACTS
                ),
            }

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

            await emit(payload)


    async def emit_asset_action_bubble_started(
        result=None,
    ):

        nonlocal asset_action_bubble_started
        nonlocal asset_action_bubble_id
        nonlocal asset_action_bubble_text

        asset_action_call = next(
            (
                action
                for action in getattr(
                    result,
                    "actions",
                    (),
                )
                or ()
                if action.name == RUNTIME_ACTION_ASSET_ACTION
            ),
            None,
        )

        asset_action_started = any(
            action.name == RUNTIME_ACTION_ASSET_ACTION
            for action in getattr(
                result,
                "started_actions",
                (),
            )
            or ()
        )

        if (
            asset_action_call is None
            and not asset_action_started
        ):
            return

        if (
            asset_action_call is not None
            and asset_action_bubble_started
        ):
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

        pending_ids = getattr(
            context,
            "runtime_pending_asset_action_ids",
            None,
        )

        if not isinstance(
            pending_ids,
            list,
        ):
            pending_ids = []
            context.runtime_pending_asset_action_ids = (
                pending_ids
            )

        if not asset_action_bubble_id:
            asset_action_bubble_id = build_runtime_action_id(
                RUNTIME_ACTION_ASSET_ACTION,
                len(
                    getattr(
                        context,
                        "runtime_asset_results",
                        [],
                    )
                    or []
                )
                + len(pending_ids)
                + 1,
            )

        if not asset_action_bubble_started:
            pending_ids.append(
                asset_action_bubble_id
            )

        asset_result = None
        detail = ""

        if asset_action_call is not None:
            detail = str(
                asset_action_call.payload
                or ""
            ).strip()
            asset_result = build_pending_asset_action_preview(
                detail
            )
            next_text = build_asset_action_marker_text(
                asset_result
            )
        else:
            next_text = build_runtime_action_display_text(
                RUNTIME_ACTION_ASSET_ACTION
            )

        if (
            asset_action_bubble_started
            and next_text == asset_action_bubble_text
        ):
            return

        asset_action_bubble_started = True
        asset_action_bubble_text = next_text

        payload = {
            "type": "runtime_action",
            "action": "asset_action",
            "id": asset_action_bubble_id,
            "status": "started",
            "runtime_message_id": runtime_message_id,
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_ASSET_ACTION
            ),
            "text": next_text,
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_ASSET_ACTION
            ),
        }

        if detail:
            payload["detail"] = detail

        if asset_result is not None:
            payload["asset_result"] = asset_result

        if action_context_snapshot:
            payload["context"] = action_context_snapshot

        await emit(
            payload
        )

    async def filter_runtime_action_chunk(
        action_chunk,
    ):

        nonlocal stop_for_runtime_action

        chunk_type = action_chunk.get(
            "type"
        )

        if chunk_type not in (
            "thinking",
            "content",
        ):
            return action_chunk

        if chunk_type == "thinking":
            return action_chunk

        content_text = str(
            action_chunk.get(
                "content",
                "",
            )
            or ""
        )
        raw_model_output_parts.append(
            content_text
        )
        raw_content_parts.append(
            content_text
        )

        if not filter_runtime_actions:
            return action_chunk

        result = content_filter.filter(
            action_chunk.get(
                "content",
                "",
            )
        )
        counter_entries = (
            capture_observed_action_markers(
                result
            )
        )
        capture_session_action_message_preview(
            result,
            counter_entries,
        )

        await emit_action_counter_updates(
            counter_entries
        )

        await emit_delayed_memory_bubble_started()
        await emit_active_memory_bubble_started(
            result
        )
        await emit_deep_web_search_bubble_started(
            result
        )
        await emit_update_lt_facts_bubble_started(
            result
        )
        # The opening tag lights the bubble before its body is validated. If
        # the completed marker is rejected, retire that exact pending bubble
        # now; otherwise its queued id gets stolen by the next valid update.
        await emit_rejected_update_lt_facts_bubble_finished(
            result
        )
        await emit_asset_action_bubble_started(
            result
        )

        await log_runtime_action_marker_removals(
            context,
            result,
            source="brain stream content",
        )

        action_applied = await apply_runtime_action_result(
            result
        )

        if counter_entries:
            await sync_session_action_marker_history()

        if await stop_on_marker_repetition(
            result
        ):
            return None

        if action_applied:
            if not result.text:
                return None

            return {
                **action_chunk,
                "content": result.text,
            }

        if not result.text:
            return None

        return {
            **action_chunk,
            "content": result.text,
        }

    def build_raw_model_output_chunk() -> dict:

        return {
            "type": "raw_model_output",
            "content": "".join(
                raw_model_output_parts
            ),
        }

    async def stop_on_marker_repetition(
        result,
    ) -> bool:

        nonlocal stop_for_runtime_action

        if not getattr(
            result,
            "marker_repetition_exceeded",
            False,
        ):
            return False

        stop_for_runtime_action = True
        reason = (
            getattr(
                result,
                "marker_repetition_reason",
                "",
            )
            or "runtime action marker repetition limit exceeded"
        )
        triggered_action = getattr(
            content_filter.repetition_guard,
            "triggered_action",
            None,
        )
        triggered_entry = (
            action_counter.get(
                getattr(
                    triggered_action,
                    "name",
                    "",
                ),
                getattr(
                    triggered_action,
                    "payload",
                    "",
                ),
            )
            if triggered_action is not None
            else None
        )

        if triggered_entry is not None:
            await emit_action_counter_updates(
                (triggered_entry,),
                status="interrupted",
                detail=reason,
            )
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
                "[RUNTIME ACTION] marker repetition guard interrupted stream: "
                f"{reason}"
            )

        return True

    async def apply_runtime_action_result(
        result,
    ) -> bool:

        runtime_action_calls = tuple(
            result.actions
        )

        if not runtime_action_calls:
            return False

        immediate_action_calls = runtime_action_calls

        if immediate_action_calls:
            (
                confirmed_action_ids,
                rejected_action_ids,
                guard_confirmation_ids,
                action_display_ids,
            ) = await confirm_runtime_action_guards(
                context,
                immediate_action_calls,
                user_message=text,
                context_snapshot=action_context_snapshot,
                confirmed_guard_names=confirmed_action_guard_names,
                rejected_guard_names=rejected_action_guard_names,
                display_state=action_guard_display_state,
            )

            assign_active_memory_bubble_ids(
                immediate_action_calls,
                action_display_ids,
            )
            assign_deep_web_search_bubble_ids(
                immediate_action_calls,
                action_display_ids,
            )
            assign_update_lt_facts_bubble_ids(
                immediate_action_calls,
                action_display_ids,
            )

            await apply_runtime_action_calls(
                context,
                immediate_action_calls,
                user_message=text,
                context_snapshot=action_context_snapshot,
                confirmed_action_ids=confirmed_action_ids,
                rejected_action_ids=rejected_action_ids,
                guard_confirmation_ids=guard_confirmation_ids,
                action_display_ids=action_display_ids,
                runtime_message_id=runtime_message_id,
            )

        return True

    # -----------------------------------------------------
    # BRAIN
    # -----------------------------------------------------

    try:

        async for model_chunk in (
            client.stream(
                context=context,
                system_prompt=(
                    resolved_system_prompt
                ),
                user_prompt=model_user_prompt,
                temperature=config.BRAIN_TEMPERATURE,
                max_tokens=None,
            )
        ):

            filtered_chunk = (
                await filter_runtime_action_chunk(
                    model_chunk
                )
            )

            if filtered_chunk:
                yield filtered_chunk

            if stop_for_runtime_action:
                break

        tail_result = (
            content_filter.flush_result()
            if filter_runtime_actions
            else RuntimeActionResult(text="")
        )
        tail_counter_entries = (
            capture_observed_action_markers(
                tail_result
            )
        )
        capture_session_action_message_preview(
            tail_result,
            tail_counter_entries,
        )
        await emit_action_counter_updates(
            tail_counter_entries
        )

        await log_runtime_action_marker_removals(
            context,
            tail_result,
            source="brain stream tail",
        )

        await apply_runtime_action_result(
            tail_result
        )

        if tail_counter_entries:
            await sync_session_action_marker_history()

        if await stop_on_marker_repetition(
            tail_result
        ):
            await finalize_session_action_history()
            yield build_raw_model_output_chunk()
            return
        content_tail = tail_result.text
        if (
            content_tail
            and not stop_for_runtime_action
        ):
            yield {
                "type": "content",
                "content": content_tail,
            }

        await finalize_session_action_history()
        yield build_raw_model_output_chunk()

    except asyncio.CancelledError:
        await finalize_session_action_history()
        raise

    except LMStudioAPIError:
        await finalize_session_action_history()
        raise

    except Exception as error:

        await finalize_session_action_history()

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )


