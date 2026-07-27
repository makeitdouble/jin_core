from contracts.rules_assembler import (
    RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_LIST_DELAYED_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_HIDE_SKILLS,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
    RUNTIME_ACTION_REMOVE_SKILL,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_WEB_SEARCH,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from rules.runtime import (
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
)
from utils.assets_utils import ensure_assets_tree
from utils.actions import (
    build_runtime_action_id,
    extract_active_memory_resolve_slot_id,
    extract_search_query,
    generate_active_memory_slot_key,
    normalize_jin_color_payload,
    parse_idle_seconds,
)
from utils.skills_asset_utils import (
    normalize_skill_name,
)
from utils.tool_results import (
    clear_runtime_tool_results,
)
from utils.runtime_action_abort import (
    mark_runtime_action_started,
    mark_runtime_actions_completed,
)
from utils.actions.active_memory_actions import (
    apply_save_active_memory_actions,
    apply_resolve_active_memory_actions,
    emit_rejected_active_memory_results,
)
from utils.actions.asset_actions import (
    apply_asset_actions,
    emit_saved_asset_results,
)
from utils.actions.delayed_memory_actions import (
    apply_delayed_memory_actions,
    apply_save_delayed_memory_actions,
    emit_delayed_memory_results,
)
from utils.actions.jin_color_actions import (
    apply_idle_actions,
    emit_jin_color_actions,
)
from utils.actions.skill_actions import (
    apply_skill_actions,
    emit_skill_state_results,
)
from utils.actions.todo_actions import (
    collect_runtime_todo_actions,
    emit_runtime_todo_results,
)

from utils.brain_client_utils import (
    build_action_missing_trigger_words_message,
    build_active_memory_resolve_failure_result,
    build_active_memory_runtime_line,
    build_delayed_memory_report,
    collect_context_active_memory_slot_ids,
    collect_context_active_memory_texts,
    normalize_active_memory_runtime_payload,
    resolve_runtime_action_user_message,
)


async def apply_runtime_action_calls(
    context,
    actions,
    user_message: str | None = None,
    context_snapshot: dict | None = None,
    assistant_message: str | None = None,
    confirmed_action_ids=None,
    rejected_action_ids=None,
    guard_confirmation_ids=None,
    action_display_ids=None,
) -> int:

    if (
        context is None
        or not actions
    ):
        return 0

    if not hasattr(
        context,
        "runtime_action_events",
    ):
        context.runtime_action_events = []

    if not hasattr(
        context,
        "runtime_search_calls",
    ):
        context.runtime_search_calls = []

    if not hasattr(
        context,
        "runtime_appended_skills",
    ):
        context.runtime_appended_skills = []

    if not hasattr(
        context,
        "runtime_visible_skills_result",
    ):
        context.runtime_visible_skills_result = {}

    action_context_snapshot = (
        dict(context_snapshot)
        if isinstance(context_snapshot, dict)
        else None
    )
    confirmed_action_ids = {
        int(action_id)
        for action_id in (confirmed_action_ids or ())
        if isinstance(
            action_id,
            int,
        )
    }
    rejected_action_ids = {
        int(action_id)
        for action_id in (rejected_action_ids or ())
        if isinstance(
            action_id,
            int,
        )
    }
    guard_confirmation_ids = (
        dict(guard_confirmation_ids)
        if isinstance(
            guard_confirmation_ids,
            dict,
        )
        else {}
    )
    action_display_ids = (
        dict(action_display_ids)
        if isinstance(
            action_display_ids,
            dict,
        )
        else {}
    )

    def with_action_context(payload: dict) -> dict:
        if not action_context_snapshot:
            return payload

        return {
            **payload,
            "context": action_context_snapshot,
        }

    ensure_assets_tree()

    search_action_count = sum(
        1
        for event in context.runtime_action_events
        if event.get("name") == RUNTIME_ACTION_WEB_SEARCH.lower()
    )

    accepted_action_names = set()

    search_calls = []
    filtered_actions = []
    rejected_action_events = {}
    rejected_active_memory_results = []
    search_query_seen = False
    save_session_seen = bool(
        getattr(
            context,
            "runtime_save_session_requested",
            False,
        )
    )
    save_session_action_emitted = bool(
        getattr(
            context,
            "runtime_save_session_action_emitted",
            False,
        )
    )
    resolve_active_memory_ids_seen = set()
    resolve_active_memory_failures_seen = set()
    save_delayed_memory_seen = set()
    list_delayed_memory_seen = False
    list_skills_seen = False
    hide_skills_seen = False
    resolved_user_message = resolve_runtime_action_user_message(
        context,
        user_message,
    )
    skill_state_action_names = {
        RUNTIME_ACTION_APPEND_SKILL,
        RUNTIME_ACTION_REMOVE_SKILL,
    }
    skill_workflow_action_names = {
        *skill_state_action_names,
        RUNTIME_ACTION_LIST_SKILLS,
        RUNTIME_ACTION_HIDE_SKILLS,
        RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
        RUNTIME_ACTION_IDLE,
    }
    todo_action_names = {
        RUNTIME_ACTION_CREATE_TODO_LIST,
        RUNTIME_ACTION_RESOLVE_TODO,
        RUNTIME_ACTION_CHECK_TODO,
    }
    appended_skill_names = {
        normalize_skill_name(
            skill.get(
                "name",
                "",
            )
        )
        for skill in (
            getattr(
                context,
                "runtime_appended_skills",
                [],
            )
            or []
        )
        if isinstance(
            skill,
            dict,
        )
        and normalize_skill_name(
            skill.get(
                "name",
                "",
            )
        )
    }
    has_skill_state_action = any(
        action.name in skill_state_action_names
        for action in actions
    )
    current_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()
    jin_color_dedup_state = getattr(
        context,
        "runtime_jin_color_apply_dedup_state",
        None,
    )

    if (
        not isinstance(
            jin_color_dedup_state,
            dict,
        )
        or jin_color_dedup_state.get("turn_id") != current_turn_id
    ):
        jin_color_dedup_state = {
            "turn_id": current_turn_id,
            "last_color": "",
        }
        context.runtime_jin_color_apply_dedup_state = (
            jin_color_dedup_state
        )

    current_jin_color = normalize_jin_color_payload(
        jin_color_dedup_state.get(
            "last_color",
            "",
        )
    )

    if (
        has_skill_state_action
        or getattr(
            context,
            "runtime_skill_state_barrier_active",
            False,
        )
    ):
        actions = [
            action
            for action in actions
            if action.name in skill_workflow_action_names
            or action.name in todo_action_names
        ]

    from runtime.behavior_contract import (
        get_action_guard_blocker_match,
        get_action_guard_name_for_runtime_action,
        should_pause_action_guard_for_confirmation,
    )

    for action in actions:

        jin_color = ""

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            jin_color = normalize_jin_color_payload(
                action.payload
            )

            if (
                not jin_color
                or jin_color == current_jin_color
            ):
                continue

        action_event_name = action.name.lower()
        action_guard_confirmed = id(action) in confirmed_action_ids

        if id(action) in rejected_action_ids:
            rejected_action_events[id(action)] = {
                "status": "failed",
                "error": "user_rejected_runtime_action",
                "title": f"{action.name} cancelled",
                "confirmation_id": guard_confirmation_ids.get(
                    id(action),
                    "",
                ),
            }
            continue

        guard_name = get_action_guard_name_for_runtime_action(
            action.name
        )
        blocker_match = (
            get_action_guard_blocker_match(
                guard_name,
                resolved_user_message,
            )
            if guard_name
            else ""
        )

        if blocker_match:
            from utils.context.runtime_state import (
                format_runtime_blocked_trigger_word_message,
            )

            failure_followup_message = (
                format_runtime_blocked_trigger_word_message(
                    blocker_match
                )
            )
            rejected_action_events[id(action)] = {
                "status": "failed",
                "error": "behavior_contract_blocker_matched",
                "blocker": blocker_match,
                "failure_followup_message": failure_followup_message,
                "confirmation_id": guard_confirmation_ids.get(
                    id(action),
                    "",
                ),
            }
            continue

        if (
            guard_name
            and not action_guard_confirmed
            and should_pause_action_guard_for_confirmation(
                guard_name,
                resolved_user_message,
            )
        ):
            rejection_event = {
                "status": "failed",
                "error": "user_did_not_confirm_runtime_action",
                "failure_followup_message": (
                    build_action_missing_trigger_words_message(
                        action.name,
                        ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
                    )
                ),
                "confirmation_id": guard_confirmation_ids.get(
                    id(action),
                    "",
                ),
            }

            if action.name == RUNTIME_ACTION_SAVE_SESSION:
                rejection_event["error"] = (
                    "user_did_not_explicitly_request_session_save"
                )

            elif (
                action.name
                == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
            ):
                rejected_report = build_delayed_memory_report(
                    context,
                    action.payload,
                )
                rejected_title = ""

                for report_value in rejected_report.values():
                    if isinstance(
                        report_value,
                        dict,
                    ):
                        rejected_title = str(
                            report_value.get(
                                "title",
                                "",
                            )
                            or ""
                        ).strip()

                    if rejected_title:
                        break

                context.runtime_delayed_memory_save_rejected_pending = True
                context.runtime_delayed_memory_save_rejected_title = (
                    rejected_title
                )
                rejection_event.update({
                    "error": (
                        "user_did_not_explicitly_request_report_save"
                    ),
                    "title": rejected_title,
                })
                save_delayed_memory_seen.add(
                    str(
                        action.payload
                        or ""
                    ).strip()
                )

            rejected_action_events[id(action)] = rejection_event
            continue

        if action.name == RUNTIME_ACTION_IDLE:
            seconds = parse_idle_seconds(
                action.payload
            )
            if seconds is None:
                continue

            # Every IDLE occurrence is an independent timer, including
            # repeated markers with the same payload in one model message.
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            current_jin_color = jin_color
            jin_color_dedup_state["last_color"] = jin_color
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_SAVE_SESSION:
            if getattr(
                context,
                "runtime_save_session_memory_committed_this_turn",
                False,
            ):
                # L3 already completed this turn. A SAVE_SESSION marker
                # repeated by the deferred follow-up must not start a second
                # memory pipeline.
                continue

            if save_session_seen:
                if not save_session_action_emitted:
                    save_session_action_emitted = True
                    accepted_action_names.add(
                        action_event_name
                    )
                    filtered_actions.append(
                        action
                    )

                continue

            save_session_seen = True
            save_session_action_emitted = True
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT:
            save_delayed_memory_key = str(
                action.payload
                or ""
            ).strip()

            if save_delayed_memory_key in save_delayed_memory_seen:
                continue

            if not build_delayed_memory_report(
                context,
                action.payload,
            ):
                continue

            save_delayed_memory_seen.add(
                save_delayed_memory_key
            )
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_LIST_DELAYED_MEMORY:
            if list_delayed_memory_seen:
                continue

            list_delayed_memory_seen = True
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_APPEND_DELAYED_MEMORY:
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_REMOVE_DELAYED_MEMORY:
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY:
            active_memory_line = build_active_memory_runtime_line(
                action.payload,
                slot_key=generate_active_memory_slot_key(
                    *collect_context_active_memory_texts(
                        context
                    )
                ),
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            )

            if not active_memory_line:
                continue

            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY:
            active_memory_id = extract_active_memory_resolve_slot_id(
                action.payload,
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            )

            if not active_memory_id:
                failure_result = build_active_memory_resolve_failure_result(
                    context,
                    action.payload,
                )
                failure_key = str(
                    failure_result.get(
                        "id",
                        "",
                    )
                    or failure_result.get(
                        "requested",
                        "",
                    )
                    or "unknown"
                ).strip().casefold()

                if failure_key in resolve_active_memory_failures_seen:
                    continue

                resolve_active_memory_failures_seen.add(
                    failure_key
                )
                rejected_active_memory_results.append(
                    failure_result
                )
                rejected_action_events[id(action)] = {
                    "status": "failed",
                    "error": failure_result["error"],
                    "id": failure_result.get(
                        "id",
                        "",
                    ),
                    "requested": failure_result.get(
                        "requested",
                        "",
                    ),
                }
                continue

            if active_memory_id in resolve_active_memory_ids_seen:
                continue

            resolve_active_memory_ids_seen.add(
                active_memory_id
            )
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name in todo_action_names:
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

            if (
                not query
                or search_query_seen
                or getattr(
                    context,
                    "runtime_search_queries",
                    [],
                )
            ):
                continue

            search_query_seen = True

        if action.name == RUNTIME_ACTION_LIST_SKILLS:
            if list_skills_seen:
                continue

            list_skills_seen = True

        if action.name == RUNTIME_ACTION_HIDE_SKILLS:
            if hide_skills_seen:
                continue

            hide_skills_seen = True

        if action.name == RUNTIME_ACTION_APPEND_SKILL:
            requested_skill = normalize_skill_name(
                action.payload
            )
            if not requested_skill:
                continue

            if requested_skill in appended_skill_names:
                continue

            appended_skill_names.add(
                requested_skill
            )

        if action.name == RUNTIME_ACTION_REMOVE_SKILL:
            requested_skill = normalize_skill_name(
                action.payload
            )
            if not requested_skill:
                continue

            appended_skill_names.discard(
                requested_skill
            )

        accepted_action_names.add(
            action_event_name
        )
        filtered_actions.append(
            action
        )

    if (
        not filtered_actions
        and not rejected_action_events
    ):
        return 0

    (
        runtime_todo_results,
        runtime_todo_action_items,
    ) = collect_runtime_todo_actions(
        context,
        filtered_actions,
        todo_action_names,
    )

    accepted_action_ids = {
        id(action)
        for action in filtered_actions
    }

    for action in actions:

        rejected_event = rejected_action_events.get(
            id(action)
        )

        if (
            id(action) not in accepted_action_ids
            and rejected_event is None
        ):
            continue

        action_event = {
            "name": action.name.lower(),
        }
        action_display_id = str(
            action_display_ids.get(
                id(action),
                "",
            )
            or ""
        ).strip()
        if action_display_id:
            action_event["id"] = action_display_id
        runtime_turn_id = str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        if runtime_turn_id:
            action_event["runtime_turn_id"] = runtime_turn_id

        query = ""

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY:
            active_memory_id = extract_active_memory_resolve_slot_id(
                action.payload,
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            )
            if active_memory_id:
                action_event["id"] = active_memory_id

        if query:
            search_action_count += 1
            tool_call_id = build_runtime_action_id(
                action.name,
                search_action_count,
            )
            action_event["id"] = tool_call_id
            action_event["query"] = query
            search_calls.append({
                "id": tool_call_id,
                "query": query,
                "context": action_context_snapshot,
            })

        elif action.name == RUNTIME_ACTION_IDLE:
            idle_seconds = parse_idle_seconds(
                action.payload
            )
            if idle_seconds is not None:
                action_event["seconds"] = idle_seconds
                action_event["payload"] = f"{idle_seconds}s"
                action_event["deferred_follow_up"] = True

        elif action.name == RUNTIME_ACTION_JIN_COLOR:
            color = normalize_jin_color_payload(
                action.payload
            )
            if color:
                action_event["color"] = color
                action_event["payload"] = color

        elif action.payload:
            action_event_payload = action.payload

            if action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY:
                action_event_payload = (
                    normalize_active_memory_runtime_payload(
                        action.payload
                    )
                )

            if action_event_payload:
                action_event["payload"] = (
                    action_event_payload
                )

        if rejected_event is not None:
            action_event.update({
                key: value
                for key, value in rejected_event.items()
                if value
            })
            failure_followup_message = str(
                rejected_event.get(
                    "failure_followup_message",
                    "",
                )
                or ""
            ).strip()
            if failure_followup_message:
                messages = getattr(
                    context,
                    "runtime_action_failure_followup_messages",
                    None,
                )
                if not isinstance(
                    messages,
                    list,
                ):
                    messages = []
                    context.runtime_action_failure_followup_messages = (
                        messages
                    )
                messages.append(
                    failure_followup_message
                )

        context.runtime_action_events.append(
            action_event
        )

        if rejected_event is None:
            mark_runtime_action_started(
                context,
                action=action_event.get(
                    "name",
                    action.name.lower(),
                ),
                action_id=action_event.get(
                    "id",
                    action_display_id,
                ),
                display_name=get_runtime_action_display_name(
                    action.name
                ),
                text=build_runtime_action_display_text(
                    action.name,
                    action.payload,
                ),
                payload=(
                    action_event.get(
                        "payload",
                        "",
                    )
                    or action_event.get(
                        "query",
                        "",
                    )
                    or action.payload
                ),
                close_tag=runtime_action_has_close_tag(
                    action.name
                ),
                context_snapshot=action_context_snapshot,
            )

    if rejected_action_events:
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
            for action in actions:
                rejected_event = rejected_action_events.get(
                    id(action)
                )
                if rejected_event is None:
                    continue
                if (
                    not rejected_event.get("confirmation_id")
                    and not rejected_event.get(
                        "failure_followup_message"
                    )
                    and rejected_event.get("error")
                    != "behavior_contract_blocker_matched"
                ):
                    continue

                payload = {
                    "type": "runtime_action",
                    "action": action.name.lower(),
                    "status": "failed",
                    "display_name": get_runtime_action_display_name(
                        action.name
                    ),
                    "close_tag": runtime_action_has_close_tag(
                        action.name
                    ),
                    "text": (
                        rejected_event.get("title")
                        or rejected_event.get("error")
                        or f"{action.name} blocked"
                    ),
                    "error": rejected_event.get(
                        "error",
                        "",
                    ),
                    "detail": rejected_event.get(
                        "failure_followup_message",
                        "",
                    ),
                }
                action_display_id = str(
                    action_display_ids.get(
                        id(action),
                        "",
                    )
                    or ""
                ).strip()
                if action_display_id:
                    payload["id"] = action_display_id

                if action.name == RUNTIME_ACTION_JIN_COLOR:
                    color = normalize_jin_color_payload(
                        action.payload
                    )
                    if color:
                        payload["color"] = color
                        payload["payload"] = color
                confirmation_id = str(
                    rejected_event.get(
                        "confirmation_id",
                        "",
                    )
                    or ""
                ).strip()
                if confirmation_id:
                    payload["confirmation_id"] = confirmation_id

                await emit(with_action_context(payload))

    if (
        not filtered_actions
        and not rejected_active_memory_results
        and not rejected_action_events
    ):
        return 0

    save_session_count = sum(
        1
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_SESSION
    )

    save_active_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
    ]
    save_active_memory_count = len(
        save_active_memory_actions
    )

    resolve_active_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
    ]
    resolve_active_memory_count = len(
        resolve_active_memory_actions
    )

    save_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
    ]

    list_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LIST_DELAYED_MEMORY
    ]

    append_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_APPEND_DELAYED_MEMORY
    ]

    remove_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_REMOVE_DELAYED_MEMORY
    ]

    list_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LIST_SKILLS
    ]

    hide_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_HIDE_SKILLS
    ]

    clean_tool_result_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_CLEAN_TOOL_RESULTS
    ]

    idle_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_IDLE
    ]

    jin_color_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_JIN_COLOR
    ]

    append_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_APPEND_SKILL
    ]

    remove_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_REMOVE_SKILL
    ]

    asset_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_ASSET_ACTION
    ]

    search_queries = [
        query
        for query in (
            extract_search_query(
                action.payload
            )
            for action in filtered_actions
            if action.name == RUNTIME_ACTION_WEB_SEARCH
        )
        if query
    ]

    if search_queries:
        if not hasattr(
            context,
            "runtime_search_queries",
        ):
            context.runtime_search_queries = []

        context.runtime_search_queries.extend(
            search_queries
        )

        context.runtime_search_calls.extend(
            search_calls
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

    idle_records = await apply_idle_actions(
        context,
        idle_actions,
        assistant_message=assistant_message,
        resolved_user_message=resolved_user_message,
        action_context_snapshot=action_context_snapshot,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    await emit_jin_color_actions(
        context,
        jin_color_actions,
        action_display_ids=action_display_ids,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    if (
        log_runtime is not None
        and search_queries
    ):
        await log_runtime(
            "[RUNTIME ACTION] "
            f"search x{len(search_queries)}"
        )

    await emit_runtime_todo_results(
        context,
        runtime_todo_results,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    if clean_tool_result_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] clean_tool_results requested"
            )

        clear_runtime_tool_results(
            context
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
            for _action in clean_tool_result_actions:
                await emit(with_action_context({
                    "type": "runtime_action",
                    "action": "clean_tool_results",
                    "status": "completed",
                    "display_name": get_runtime_action_display_name(
                        RUNTIME_ACTION_CLEAN_TOOL_RESULTS
                    ),
                    "close_tag": runtime_action_has_close_tag(
                        RUNTIME_ACTION_CLEAN_TOOL_RESULTS
                    ),
                    "text": "Tool results cleared",
                }))

    await emit_rejected_active_memory_results(
        context,
        rejected_active_memory_results,
        with_action_context=with_action_context,
    )

    skill_results = await apply_skill_actions(
        context,
        list_skill_actions=list_skill_actions,
        hide_skill_actions=hide_skill_actions,
        append_skill_actions=append_skill_actions,
        remove_skill_actions=remove_skill_actions,
        runtime_todo_action_items=runtime_todo_action_items,
        log_runtime=log_runtime,
    )
    saved_asset_results = list(
        skill_results["saved_asset_results"]
    )
    hidden_skill_results = skill_results["hidden_skill_results"]
    appended_skill_results = skill_results["appended_skill_results"]
    removed_skill_results = skill_results["removed_skill_results"]

    saved_asset_results.extend(
        await apply_asset_actions(
            context,
            asset_actions,
            runtime_todo_action_items=runtime_todo_action_items,
            log_runtime=log_runtime,
            with_action_context=with_action_context,
        )
    )

    delayed_memory_results = await apply_delayed_memory_actions(
        context,
        list_delayed_memory_actions=list_delayed_memory_actions,
        append_delayed_memory_actions=append_delayed_memory_actions,
        remove_delayed_memory_actions=remove_delayed_memory_actions,
        log_runtime=log_runtime,
    )

    await emit_delayed_memory_results(
        context,
        delayed_memory_results,
        with_action_context=with_action_context,
    )

    await emit_saved_asset_results(
        context,
        saved_asset_results,
        with_action_context=with_action_context,
    )

    skill_state_results = (
        appended_skill_results
        + removed_skill_results
        + hidden_skill_results
    )

    await emit_skill_state_results(
        context,
        skill_state_results,
        with_action_context=with_action_context,
    )

    if save_session_count:
        context.runtime_save_session_armed = False
        context.runtime_save_session_requested = True
        context.runtime_save_session_action_emitted = True
        save_session_confirmation_id = ""

        for action in filtered_actions:
            if action.name != RUNTIME_ACTION_SAVE_SESSION:
                continue

            save_session_confirmation_id = str(
                guard_confirmation_ids.get(
                    id(action),
                    "",
                )
                or ""
            ).strip()
            if save_session_confirmation_id:
                break

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] save_session requested"
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
            payload = {
                "type": "runtime_action",
                "action": "save_session",
                "status": "started",
                "text": "Saving session",
            }

            if save_session_confirmation_id:
                payload["confirmation_id"] = save_session_confirmation_id

            await emit(with_action_context(payload))

    saved_active_memory_texts = await apply_save_active_memory_actions(
        context,
        save_active_memory_actions,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    saved_delayed_memory_reports = await apply_save_delayed_memory_actions(
        context,
        save_delayed_memory_actions,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    resolved_active_memory_count = await apply_resolve_active_memory_actions(
        context,
        resolve_active_memory_actions,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    applied_count = (
        len(
            search_queries
        )
        + len(
            saved_asset_results
        )
        + len(
            appended_skill_results
        )
        + len(
            removed_skill_results
        )
        + len(
            hidden_skill_results
        )
        + len(
            clean_tool_result_actions
        )
        + len(
            idle_records
        )
        + len(
            jin_color_actions
        )
        + min(
            save_session_count,
            1,
        )
        + len(
            saved_active_memory_texts
        )
        + len(
            saved_delayed_memory_reports
        )
        + len(
            delayed_memory_results
        )
        + resolved_active_memory_count
    )

    mark_runtime_actions_completed(
        context,
        filtered_actions,
        keep_actions={
            RUNTIME_ACTION_WEB_SEARCH,
            RUNTIME_ACTION_SAVE_SESSION,
        },
    )

    return applied_count
