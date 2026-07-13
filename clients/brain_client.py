import asyncio

from config_loader import (
    config,
)
from rules.runtime import (
    RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_LIST_DELAYED_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_HIDE_SKILLS,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH, INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT_MARKER,
)

from clients.errors import (
    format_client_error,
)

from rules.assembler import (
    build_brain_system_prompt,
    get_enabled_runtime_actions,
)

from clients.brain_client_utils import (
    apply_runtime_action_calls,
    log_runtime_action_marker_removals,
    should_execute_save_delayed_memory,
    should_execute_save_session,
)
from utils.session_actions_history import (
    build_asset_action_history_text,
    emit_session_actions_update,
    replace_session_action_history_since,
)

from clients.service_client import (
    ask_service_model,
    ask_service_model_stream,
)

from clients.response_extractor import (
    ResponseExtractor,
)

from utils.runtime_actions import (
    build_runtime_action_id,
    RuntimeActionRepetitionGuard,
    RuntimeActionResult,
    RuntimeActionStreamFilter,
    extract_runtime_actions,
)
from utils.runtime_todo import (
    has_active_runtime_todo,
)
from utils.assets_service import (
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
    snapshot["visible_system_prompt"] = build_brain_system_prompt(
        context,
        runtime_actions,
        user_input=user_prompt,
        include_runtime_action_instructions=False,
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
        build_brain_system_prompt(
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

            await apply_runtime_action_calls(
                context,
                content_actions.actions,
                user_message=text,
                context_snapshot=action_context_snapshot,
            )

            return content_actions.text

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

        await apply_runtime_action_calls(
            context,
            content_actions.actions,
            user_message=text,
            context_snapshot=action_context_snapshot,
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
        or build_brain_system_prompt(
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
    runtime_action_boundary_seen = False
    delayed_memory_bubble_started = False
    asset_action_bubble_started = False
    action_context_snapshot = build_brain_context_snapshot(
        context=context,
        system_prompt=resolved_system_prompt,
        user_prompt=resolved_brain_payload,
        runtime_actions=runtime_actions,
    )
    session_action_history_start = len(
        getattr(
            context,
            "runtime_session_action_history",
            [],
        )
        or []
    )
    observed_action_markers = []
    session_action_history_finalized = False

    def capture_observed_action_markers(
        result,
    ) -> None:

        for action in getattr(
            result,
            "observed_actions",
            (),
        ):
            name = str(
                getattr(
                    action,
                    "name",
                    "",
                )
                or ""
            ).strip()

            if name:
                observed_action_markers.append(
                    action
                )

    async def finalize_session_action_history() -> None:

        nonlocal session_action_history_finalized

        if session_action_history_finalized:
            return

        session_action_history_finalized = True

        replace_session_action_history_since(
            context,
            session_action_history_start,
            observed_action_markers,
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

        if (
            INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT_MARKER not in pending
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
            "text": "Saving delayed memory report",
        }

        if action_context_snapshot:
            payload["context"] = action_context_snapshot

        await emit(
            payload
        )

    async def emit_asset_action_bubble_started():

        nonlocal asset_action_bubble_started

        if asset_action_bubble_started:
            return

        pending = str(
            getattr(
                content_filter,
                "pending",
                "",
            )
            or ""
        ).upper()

        if (
            "INTERNAL_ACTION_ASSET_ACTION" not in pending
            and "ASSET_ACTION" not in pending
        ):
            return

        asset_action_bubble_started = True

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

        action_id = build_runtime_action_id(
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
        pending_ids.append(
            action_id
        )

        payload = {
            "type": "runtime_action",
            "action": "asset_action",
            "id": action_id,
            "status": "started",
            "text": build_asset_action_history_text({
                "action": "asset_action",
            }),
        }

        if action_context_snapshot:
            payload["context"] = action_context_snapshot

        await emit(
            payload
        )

    async def filter_runtime_action_chunk(
        action_chunk,
    ):

        nonlocal stop_for_runtime_action
        nonlocal runtime_action_boundary_seen

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

        if not filter_runtime_actions:
            return action_chunk

        result = content_filter.filter(
            action_chunk.get(
                "content",
                "",
            )
        )
        capture_observed_action_markers(
            result
        )

        await emit_delayed_memory_bubble_started()
        await emit_asset_action_bubble_started()

        await log_runtime_action_marker_removals(
            context,
            result,
            source="brain stream content",
        )

        if await stop_on_marker_repetition(
            result
        ):
            return None

        action_applied = await apply_runtime_action_result(
            result
        )

        if runtime_action_boundary_seen:
            # A boundary action (for example WEB_SEARCH) used to stop the
            # model stream immediately. That dropped any action markers
            # emitted later in the same assistant message because they had
            # not arrived from the token stream yet. Keep draining adjacent
            # whitespace and action markers, but stop as soon as ordinary
            # visible text resumes. Everything after the boundary stays
            # hidden from chat.
            if (
                not action_applied
                and result.text
                and result.text.strip()
            ):
                stop_for_runtime_action = True

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

        nonlocal runtime_action_boundary_seen

        runtime_action_calls = tuple(
            result.actions
        )

        if not runtime_action_calls:
            return False

        await apply_runtime_action_calls(
            context,
            runtime_action_calls,
            user_message=text,
            context_snapshot=action_context_snapshot,
        )

        if any(
            action.name in (
                RUNTIME_ACTION_ASSET_ACTION,
                RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
                RUNTIME_ACTION_LIST_DELAYED_MEMORY,
                RUNTIME_ACTION_WEB_SEARCH,
                RUNTIME_ACTION_LIST_SKILLS,
                RUNTIME_ACTION_HIDE_SKILLS,
                RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
            )
            for action in runtime_action_calls
        ):
            runtime_action_boundary_seen = True

        return True

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
            capture_observed_action_markers(
                tail_result
            )

            await log_runtime_action_marker_removals(
                context,
                tail_result,
                source="brain stream tail",
            )

            if await stop_on_marker_repetition(
                tail_result
            ):
                await finalize_session_action_history()
                return

            await apply_runtime_action_result(
                tail_result
            )

            content_tail = tail_result.text
            if (
                content_tail
                and not stop_for_runtime_action
                and not runtime_action_boundary_seen
            ):
                yield {
                    "type": "content",
                    "content": content_tail,
                }

            await finalize_session_action_history()
            return

        except asyncio.CancelledError:
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
        capture_observed_action_markers(
            tail_result
        )

        await log_runtime_action_marker_removals(
            context,
            tail_result,
            source="brain stream tail",
        )

        if await stop_on_marker_repetition(
            tail_result
        ):
            await finalize_session_action_history()
            return

        await apply_runtime_action_result(
            tail_result
        )

        content_tail = tail_result.text
        if (
            content_tail
            and not stop_for_runtime_action
            and not runtime_action_boundary_seen
        ):
            yield {
                "type": "content",
                "content": content_tail,
            }

        await finalize_session_action_history()

    except asyncio.CancelledError:
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
