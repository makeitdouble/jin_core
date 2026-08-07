import asyncio
import json
import re
import uuid

from config_loader import (
    config,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_UPDATE_L4_FACTS,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
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
    flush_pending_active_memory_resolve_failure_history,
    log_runtime_action_marker_removals,
    should_execute_save_delayed_memory,
    should_execute_save_session,
)
from runtime.action_guard import (
    confirm_runtime_action_guards,
    get_action_guard_display_id,
)
from utils.session_actions_history import (
    build_asset_action_marker_text,
    emit_session_actions_update,
    replace_session_action_history_since,
    upsert_session_action_marker_history_since,
)

from clients.service_client import (
    ask_service_model,
    ask_service_model_stream,
)

from clients.response_extractor import (
    ResponseExtractor,
)

from runtime.client import (
    LMStudioAPIError,
)


from utils.actions import (
    build_runtime_action_id,
    emit_runtime_action_counter_updates,
    RuntimeActionCounter,
    RuntimeActionRepetitionGuard,
    RuntimeActionResult,
    RuntimeActionStreamFilter,
    extract_runtime_actions,
    normalize_jin_color_payload,
)
from utils.runtime_todo import (
    has_active_runtime_todo,
)
from utils.skills_asset_utils import (
    normalize_skill_name,
)


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
        RUNTIME_ACTION_SAVE_SESSION
        in enabled_actions
        and not should_execute_save_session(
            user_message
        )
    ):
        enabled_actions.remove(
            RUNTIME_ACTION_SAVE_SESSION
        )

    if (
        RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
        in enabled_actions
        and not should_execute_save_delayed_memory(
            user_message
        )
    ):
        enabled_actions.remove(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
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

    image_input_enabled = (
        bool(
            getattr(
                config,
                "SERVICE_IMAGE_INPUT_ENABLED",
                False,
            )
        )
        if config.USE_SERVICE_AS_BRAIN
        else bool(
            getattr(
                config,
                "BRAIN_IMAGE_INPUT_ENABLED",
                False,
            )
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
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            result = await ask_service_model(
                client=client,
                user_prompt=model_user_prompt,
                system_prompt=system_prompt,
                temperature=(
                    config.BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config.BRAIN_MAX_TOKENS
                ),
            )

            reasoning = (
                ResponseExtractor.extract_reasoning_text(
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

            content_actions = (
                extract_runtime_actions(
                    content,
                    enabled_actions=enabled_actions,
                )
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

            return content_actions.text

        except LMStudioAPIError:

            raise

        except Exception as error:

            formatted_error = (
                format_client_error(
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        result = await client.ask(
            system_prompt=system_prompt,
            user_prompt=model_user_prompt,
            temperature=(
                config
                .BRAIN_TEMPERATURE
            ),
            max_tokens=(
                config
                .BRAIN_MAX_TOKENS
            ),
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

    appended_skill_marker_names = {
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
                "runtime_appended_skills",
                [],
            )
            or []
        )
    }
    appended_skill_marker_names.discard(
        ""
    )

    def preserve_duplicate_append_skill_marker(
        _raw_marker,
        action,
    ) -> bool:

        if action.name != RUNTIME_ACTION_APPEND_SKILL:
            return False

        requested_skill = normalize_skill_name(
            action.payload
        )

        if not requested_skill:
            return False

        if requested_skill in appended_skill_marker_names:
            return True

        appended_skill_marker_names.add(
            requested_skill
        )

        return False

    content_filter = RuntimeActionStreamFilter(
        enabled_actions=enabled_actions,
        preserve_action_marker=preserve_duplicate_append_skill_marker,
        repetition_guard=RuntimeActionRepetitionGuard(),
        #preserve_action_text=True
    )
    stop_for_runtime_action = False
    delayed_memory_bubble_started = False
    update_l4_facts_pending_bubble_ids = []
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
    raw_content_parts = []
    raw_model_output_parts = []
    pending_idle_action_calls = []
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

    def get_action_counter_display_payloads() -> dict:

        display_payloads = {}
        applied_colors = get_applied_jin_colors()

        if applied_colors:
            display_payloads[
                RUNTIME_ACTION_JIN_COLOR
            ] = applied_colors

        delayed_memory_display_actions = (
            RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
            RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
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

        if not updated:
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

        replace_session_action_history_since(
            context,
            session_action_history_start,
            action_counter.marker_actions(
                display_payloads=(
                    get_action_counter_display_payloads()
                ),
            ),
        )
        flush_pending_active_memory_resolve_failure_history(
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
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
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
                ) == "save_delayed_memory_content"
            ]),
        )
        next_sequence = current_sequence + 1
        context.runtime_delayed_memory_action_sequence = (
            next_sequence
        )
        action_id = build_runtime_action_id(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
            next_sequence,
        )
        pending_ids.append(
            action_id
        )

        payload = {
            "type": "runtime_action",
            "action": "save_delayed_memory_content",
            "id": action_id,
            "status": "started",
            "display_name": get_runtime_action_display_name(
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
            ),
            "text": build_runtime_action_display_text(
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
            ),
            "close_tag": runtime_action_has_close_tag(
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
            ),
        }

        if action_context_snapshot:
            payload["context"] = action_context_snapshot

        await emit(
            payload
        )

    async def emit_update_l4_facts_bubble_started(
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
            if action.name == RUNTIME_ACTION_UPDATE_L4_FACTS
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
                    "runtime_update_l4_facts_action_sequence",
                    0,
                )
                or 0
            ) + 1
            context.runtime_update_l4_facts_action_sequence = sequence

            action_id = build_runtime_action_id(
                RUNTIME_ACTION_UPDATE_L4_FACTS,
                sequence,
            )
            update_l4_facts_pending_bubble_ids.append(
                action_id
            )

            payload = {
                "type": "runtime_action",
                "action": "update_l4_facts",
                "id": action_id,
                "status": "started",
                "runtime_message_id": runtime_message_id,
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_UPDATE_L4_FACTS
                ),
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_UPDATE_L4_FACTS
                ),
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_UPDATE_L4_FACTS
                ),
            }

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

            await emit(
                payload
            )

    async def complete_update_l4_facts_bubbles(
        actions,
        action_display_ids,
    ):

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

        for action in actions:
            if action.name != RUNTIME_ACTION_UPDATE_L4_FACTS:
                continue

            action_id = (
                update_l4_facts_pending_bubble_ids.pop(0)
                if update_l4_facts_pending_bubble_ids
                else ""
            )

            if action_id:
                action_display_ids[id(action)] = action_id

            if emit is None or not action_id:
                continue

            payload = {
                "type": "runtime_action",
                "action": "update_l4_facts",
                "id": action_id,
                "status": "completed",
                "runtime_message_id": runtime_message_id,
                "display_name": get_runtime_action_display_name(
                    RUNTIME_ACTION_UPDATE_L4_FACTS
                ),
                "text": build_runtime_action_display_text(
                    RUNTIME_ACTION_UPDATE_L4_FACTS
                ),
                "close_tag": runtime_action_has_close_tag(
                    RUNTIME_ACTION_UPDATE_L4_FACTS
                ),
            }

            if action_context_snapshot:
                payload["context"] = action_context_snapshot

            await emit(
                payload
            )

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

        await emit_action_counter_updates(
            counter_entries
        )

        await emit_delayed_memory_bubble_started()
        await emit_update_l4_facts_bubble_started(
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

        idle_action_calls = tuple(
            action
            for action in runtime_action_calls
            if action.name == RUNTIME_ACTION_IDLE
        )
        immediate_action_calls = tuple(
            action
            for action in runtime_action_calls
            if action.name != RUNTIME_ACTION_IDLE
        )

        pending_idle_action_calls.extend(
            idle_action_calls
        )

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

            await complete_update_l4_facts_bubbles(
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

    async def flush_pending_idle_actions() -> None:

        if not pending_idle_action_calls:
            return

        idle_actions = tuple(
            pending_idle_action_calls
        )
        pending_idle_action_calls.clear()

        (
            confirmed_action_ids,
            rejected_action_ids,
            guard_confirmation_ids,
            action_display_ids,
        ) = await confirm_runtime_action_guards(
            context,
            idle_actions,
            user_message=text,
            context_snapshot=action_context_snapshot,
            confirmed_guard_names=confirmed_action_guard_names,
            rejected_guard_names=rejected_action_guard_names,
            display_state=action_guard_display_state,
        )

        await apply_runtime_action_calls(
            context,
            idle_actions,
            user_message=text,
            context_snapshot=action_context_snapshot,
            assistant_message="".join(
                raw_content_parts
            ),
            confirmed_action_ids=confirmed_action_ids,
            rejected_action_ids=rejected_action_ids,
            guard_confirmation_ids=guard_confirmation_ids,
            action_display_ids=action_display_ids,
            runtime_message_id=runtime_message_id,
        )

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            async for model_chunk in (
                ask_service_model_stream(
                    context=context,
                    client=client,
                    user_prompt=(
                        model_user_prompt
                    ),
                    system_prompt=(
                        resolved_system_prompt
                    ),
                    temperature=(
                        config
                        .BRAIN_TEMPERATURE
                    ),
                    max_tokens=(
                        config
                        .BRAIN_MAX_TOKENS
                    ),
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

            if await stop_on_marker_repetition(
                tail_result
            ):
                await finalize_session_action_history()
                yield build_raw_model_output_chunk()
                return
            await flush_pending_idle_actions()

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
            return

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
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        async for model_chunk in (
            client.stream(
                context=context,
                system_prompt=(
                    resolved_system_prompt
                ),
                user_prompt=model_user_prompt,
                temperature=(
                    config
                    .BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config
                    .BRAIN_MAX_TOKENS
                ),
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
        await flush_pending_idle_actions()

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


