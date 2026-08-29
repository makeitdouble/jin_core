from contracts.rules_assembler import (
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_ATTACH_FILE,
    RUNTIME_ACTION_LIST_FILES,
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
    RUNTIME_ACTION_UPDATE_L4_FACTS,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_DETACH_FILE,
    RUNTIME_ACTION_UNLOAD_SKILL,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
    RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_WEB_SEARCH,
    build_runtime_action_display_text,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
    runtime_action_emits_followup,
    runtime_action_follows_up_on_fail,
)
from rules.runtime import (
    ACTION_REJECTED_MISSING_TRIGGER_WORDS_MESSAGE,
)
from runtime.anonymous_mode import (
    RESTRICTED_WRITE_REASON,
    build_restricted_write_event,
    persistent_writes_restricted,
    runtime_action_write_is_restricted,
)
from utils.assets_utils import ensure_assets_tree
from utils.actions import (
    build_runtime_action_id,
    extract_active_memory_delete_slot_id,
    extract_search_query,
    generate_active_memory_slot_key,
    normalize_jin_color_payload,
    normalize_jin_position_dict,
    normalize_jin_position_payload,
    normalize_jin_speed_payload,
    normalize_jin_speed_value,
    normalize_jin_size_dict,
    normalize_jin_size_payload,
    parse_update_active_memory_payload,
)
from utils.skills_asset_utils import (
    normalize_skill_name,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    clear_runtime_tool_results_before_state,
    record_runtime_tool_result,
    snapshot_runtime_tool_results_state,
)
from utils.runtime_action_abort import (
    mark_runtime_action_started,
    mark_runtime_actions_completed,
)
from utils.actions.active_memory_actions import (
    apply_save_active_memory_actions,
    apply_delete_active_memory_actions,
    apply_update_active_memory_actions,
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
from utils.actions.attachment_actions import (
    apply_attachment_actions,
)
from utils.actions.update_l4_facts_actions import schedule_update_l4_facts_actions
from utils.actions.jin_visual_sequence_actions import (
    emit_jin_visual_sequences,
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
    build_active_memory_delete_failure_result,
    build_active_memory_runtime_line,
    build_delayed_memory_report,
    collect_context_active_memory_slot_ids,
    collect_context_active_memory_texts,
    normalize_update_active_memory_payload_reference,
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
    runtime_message_id: str = "",
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
        "runtime_deep_search_calls",
    ):
        context.runtime_deep_search_calls = []

    if not hasattr(
        context,
        "runtime_loaded_skills",
    ):
        context.runtime_loaded_skills = []

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

    resolved_runtime_message_id = str(
        runtime_message_id
        or ""
    ).strip()
    resolved_runtime_turn_id = str(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
        or ""
    ).strip()

    def with_action_context(payload: dict) -> dict:
        enriched_payload = dict(payload)

        if resolved_runtime_turn_id:
            enriched_payload["runtime_turn_id"] = (
                resolved_runtime_turn_id
            )

        if resolved_runtime_message_id:
            enriched_payload["runtime_message_id"] = (
                resolved_runtime_message_id
            )

        if action_context_snapshot:
            enriched_payload["context"] = (
                action_context_snapshot
            )

        return enriched_payload

    if not persistent_writes_restricted(context):
        ensure_assets_tree()
    tool_results_clean_state = snapshot_runtime_tool_results_state(
        context
    )

    search_action_count = sum(
        1
        for event in context.runtime_action_events
        if event.get("name") == RUNTIME_ACTION_WEB_SEARCH.lower()
    )
    deep_search_action_count = sum(
        1
        for event in context.runtime_action_events
        if event.get("name") == RUNTIME_ACTION_DEEP_WEB_SEARCH.lower()
    )

    accepted_action_names = set()

    search_calls = []
    deep_search_calls = []
    filtered_actions = []
    rejected_action_events = {}
    rejected_active_memory_results = []
    delete_active_memory_ids_seen = set()
    delete_active_memory_failures_seen = set()
    save_delayed_memory_seen = set()
    resolved_user_message = resolve_runtime_action_user_message(
        context,
        user_message,
    )
    skill_state_action_names = {
        RUNTIME_ACTION_LOAD_SKILL,
        RUNTIME_ACTION_UNLOAD_SKILL,
    }
    skill_workflow_action_names = {
        *skill_state_action_names,
        RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
        RUNTIME_ACTION_DEEP_WEB_SEARCH,
        RUNTIME_ACTION_WEB_SEARCH,
        RUNTIME_ACTION_JIN_COLOR,
        RUNTIME_ACTION_JIN_SIZE,
        RUNTIME_ACTION_JIN_POSITION,
        RUNTIME_ACTION_JIN_SPEED,
        RUNTIME_ACTION_UPDATE_L4_FACTS,
    }
    todo_action_names = {
        RUNTIME_ACTION_CREATE_TODO_LIST,
        RUNTIME_ACTION_RESOLVE_TODO,
        RUNTIME_ACTION_CHECK_TODO,
    }
    loaded_skill_names = {
        normalize_skill_name(
            skill.get(
                "name",
                "",
            )
        )
        for skill in (
            getattr(
                context,
                "runtime_loaded_skills",
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
    runtime_action_dedup_scope = resolved_runtime_message_id
    runtime_action_seen_keys = set()

    if runtime_action_dedup_scope:
        runtime_action_dedup_state = getattr(
            context,
            "runtime_action_apply_dedup_state",
            None,
        )

        if (
            not isinstance(
                runtime_action_dedup_state,
                dict,
            )
            or runtime_action_dedup_state.get("turn_id")
            != current_turn_id
        ):
            runtime_action_dedup_state = {
                "turn_id": current_turn_id,
                "seen_by_message": {},
            }
            context.runtime_action_apply_dedup_state = (
                runtime_action_dedup_state
            )
        elif not isinstance(
            runtime_action_dedup_state.get("seen_by_message"),
            dict,
        ):
            runtime_action_dedup_state["seen_by_message"] = {}

        runtime_action_seen_by_message = runtime_action_dedup_state[
            "seen_by_message"
        ]
        runtime_action_seen_keys = set(
            runtime_action_seen_by_message.get(
                runtime_action_dedup_scope,
                [],
            )
            or []
        )

    def build_runtime_action_dedup_key(
        action,
        payload_identity: str | None = None,
    ) -> str:

        action_name = str(
            action.name
            or ""
        ).strip().upper()

        if payload_identity is None:
            if action_name == RUNTIME_ACTION_WEB_SEARCH:
                payload_identity = extract_search_query(
                    action.payload
                )
            elif action_name == RUNTIME_ACTION_JIN_COLOR:
                payload_identity = normalize_jin_color_payload(
                    action.payload
                )
            elif action_name == RUNTIME_ACTION_JIN_SIZE:
                payload_identity = normalize_jin_size_payload(
                    action.payload
                )
            elif action_name == RUNTIME_ACTION_JIN_POSITION:
                payload_identity = normalize_jin_position_payload(
                    action.payload
                )
            elif action_name == RUNTIME_ACTION_JIN_SPEED:
                payload_identity = normalize_jin_speed_payload(
                    action.payload
                )
            elif action_name in {
                RUNTIME_ACTION_LOAD_SKILL,
                RUNTIME_ACTION_UNLOAD_SKILL,
            }:
                payload_identity = normalize_skill_name(
                    action.payload
                )
            else:
                payload_identity = str(
                    action.payload
                    or ""
                )

        return (
            f"{action_name}\0"
            f"{str(payload_identity or '').strip()}"
        )

    def accept_runtime_action_once_per_message(
        action,
        payload_identity: str | None = None,
    ) -> bool:

        dedup_key = build_runtime_action_dedup_key(
            action,
            payload_identity,
        )

        if dedup_key in runtime_action_seen_keys:
            return False

        runtime_action_seen_keys.add(
            dedup_key
        )

        if runtime_action_dedup_scope:
            runtime_action_seen_by_message[
                runtime_action_dedup_scope
            ] = sorted(
                runtime_action_seen_keys
            )

        return True

    jin_color_message_scope = (
        resolved_runtime_message_id
        or "__unscoped__"
    )
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
            "last_color_by_message": {},
        }
        context.runtime_jin_color_apply_dedup_state = (
            jin_color_dedup_state
        )
    elif not isinstance(
        jin_color_dedup_state.get("last_color_by_message"),
        dict,
    ):
        legacy_last_color = normalize_jin_color_payload(
            jin_color_dedup_state.get(
                "last_color",
                "",
            )
        )
        jin_color_dedup_state["last_color_by_message"] = {}

        if legacy_last_color:
            jin_color_dedup_state["last_color_by_message"][
                "__unscoped__"
            ] = legacy_last_color

    jin_color_last_by_message = jin_color_dedup_state[
        "last_color_by_message"
    ]

    current_jin_color = normalize_jin_color_payload(
        jin_color_last_by_message.get(
            jin_color_message_scope,
            "",
        )
    )
    jin_size_message_scope = (
        resolved_runtime_message_id
        or "__unscoped__"
    )
    jin_size_dedup_state = getattr(
        context,
        "runtime_jin_size_apply_dedup_state",
        None,
    )

    if (
        not isinstance(
            jin_size_dedup_state,
            dict,
        )
        or jin_size_dedup_state.get("turn_id") != current_turn_id
    ):
        jin_size_dedup_state = {
            "turn_id": current_turn_id,
            "last_size_by_message": {},
        }
        context.runtime_jin_size_apply_dedup_state = (
            jin_size_dedup_state
        )
    elif not isinstance(
        jin_size_dedup_state.get("last_size_by_message"),
        dict,
    ):
        legacy_last_size = normalize_jin_size_payload(
            jin_size_dedup_state.get(
                "last_size",
                "",
            )
        )
        jin_size_dedup_state["last_size_by_message"] = {}

        if legacy_last_size:
            jin_size_dedup_state["last_size_by_message"][
                "__unscoped__"
            ] = legacy_last_size

    jin_size_last_by_message = jin_size_dedup_state[
        "last_size_by_message"
    ]

    current_jin_size = normalize_jin_size_payload(
        jin_size_last_by_message.get(
            jin_size_message_scope,
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

        if runtime_action_write_is_restricted(
            context,
            action.name,
            action.payload,
        ):
            rejected_action_events[id(action)] = (
                build_restricted_write_event(
                    action.name,
                    include_followup=runtime_action_emits_followup(
                        action.name
                    ),
                )
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
                    "[RUNTIME ACTION] "
                    f"{action.name.lower()} failed: "
                    f"{RESTRICTED_WRITE_REASON}"
                )
            continue

        jin_color = ""
        jin_size = ""
        jin_size_dict = None
        jin_position = ""
        jin_position_dict = None
        jin_speed = ""
        jin_speed_value = None

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            jin_color = normalize_jin_color_payload(
                action.payload
            )

            if (
                not jin_color
                or jin_color == current_jin_color
            ):
                continue

        if action.name == RUNTIME_ACTION_JIN_SIZE:
            jin_size = normalize_jin_size_payload(
                action.payload
            )
            jin_size_dict = normalize_jin_size_dict(
                action.payload
            )

            if (
                not jin_size
                or not jin_size_dict
                or jin_size == current_jin_size
            ):
                continue

        if action.name == RUNTIME_ACTION_JIN_POSITION:
            jin_position = normalize_jin_position_payload(
                action.payload
            )
            jin_position_dict = normalize_jin_position_dict(
                action.payload
            )

            if not jin_position or not jin_position_dict:
                continue

        if action.name == RUNTIME_ACTION_JIN_SPEED:
            jin_speed = normalize_jin_speed_payload(
                action.payload
            )
            jin_speed_value = normalize_jin_speed_value(
                action.payload
            )

            if not jin_speed or jin_speed_value is None:
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

            if (
                action.name
                == RUNTIME_ACTION_SAVE_DELAYED_MEMORY
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

        if action.name == RUNTIME_ACTION_JIN_COLOR:
            current_jin_color = jin_color
            context.jin_color = jin_color
            jin_color_last_by_message[
                jin_color_message_scope
            ] = jin_color
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_JIN_SIZE:
            current_jin_size = jin_size
            jin_size_last_by_message[
                jin_size_message_scope
            ] = jin_size
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name in {
            RUNTIME_ACTION_JIN_POSITION,
            RUNTIME_ACTION_JIN_SPEED,
        }:
            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY:
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

            if not accept_runtime_action_once_per_message(
                action,
                save_delayed_memory_key,
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

        if action.name == RUNTIME_ACTION_LOAD_DELAYED_MEMORY:
            if not accept_runtime_action_once_per_message(
                action
            ):
                continue

            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY:
            if not accept_runtime_action_once_per_message(
                action
            ):
                continue

            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name in {
            RUNTIME_ACTION_LIST_FILES,
            RUNTIME_ACTION_ATTACH_FILE,
            RUNTIME_ACTION_DETACH_FILE,
        }:
            if not accept_runtime_action_once_per_message(action):
                continue

            accepted_action_names.add(action_event_name)
            filtered_actions.append(action)
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
                failure_result = {
                    "ok": False,
                    "action": "save_active_memory",
                    "error": "invalid_active_memory_payload",
                    "detail": "invalid payload",
                    "payload": str(action.payload or "").strip(),
                }
                rejected_action_events[id(action)] = {
                    "status": "failed",
                    "error": failure_result["error"],
                    "failure_reason": failure_result["detail"],
                    "failed_marker_payload": failure_result["payload"],
                }
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_ACTIVE_MEMORY,
                    failure_result,
                )
                continue

            if not accept_runtime_action_once_per_message(
                action,
                active_memory_line,
            ):
                continue

            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY:
            (
                normalized_payload,
                requested_reference,
                resolved_reference_id,
            ) = normalize_update_active_memory_payload_reference(
                context,
                action.payload,
            )
            active_memory_id, update_fields = parse_update_active_memory_payload(
                normalized_payload
            )

            if not active_memory_id or not update_fields:
                failure_error = (
                    "active_memory_not_found"
                    if requested_reference and not resolved_reference_id
                    else "invalid_update_active_memory_payload"
                )
                failure_reason = (
                    "incorrect id"
                    if failure_error == "active_memory_not_found"
                    else "invalid payload"
                )
                failure_result = {
                    "ok": False,
                    "action": "update_active_memory",
                    "error": failure_error,
                    "detail": failure_reason,
                    "payload": str(action.payload or "").strip(),
                }
                rejected_action_events[id(action)] = {
                    "status": "failed",
                    "error": failure_error,
                    "failure_reason": failure_reason,
                    "failed_marker_payload": failure_result["payload"],
                }
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_ACTIVE_MEMORY,
                    failure_result,
                )
                continue

            update_key = (
                active_memory_id,
                tuple(update_fields),
            )
            if not accept_runtime_action_once_per_message(
                action,
                update_key,
            ):
                continue

            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_DELETE_ACTIVE_MEMORY:
            active_memory_id = extract_active_memory_delete_slot_id(
                action.payload,
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            )

            if not active_memory_id:
                failure_result = build_active_memory_delete_failure_result(
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

                if failure_key in delete_active_memory_failures_seen:
                    continue

                delete_active_memory_failures_seen.add(
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

            if active_memory_id in delete_active_memory_ids_seen:
                continue

            if not accept_runtime_action_once_per_message(
                action,
                active_memory_id,
            ):
                continue

            delete_active_memory_ids_seen.add(
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
            if not accept_runtime_action_once_per_message(
                action
            ):
                continue

            accepted_action_names.add(
                action_event_name
            )
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_DEEP_WEB_SEARCH:
            objective = extract_search_query(
                action.payload
            )

            if (
                not objective
                or getattr(
                    context,
                    "runtime_deep_search_calls",
                    [],
                )
            ):
                continue

            if not accept_runtime_action_once_per_message(
                action,
                objective,
            ):
                continue

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

            if (
                not query
                or getattr(
                    context,
                    "runtime_search_queries",
                    [],
                )
            ):
                continue

            if not accept_runtime_action_once_per_message(
                action,
                query,
            ):
                continue

        if action.name == RUNTIME_ACTION_LOAD_SKILL:
            requested_skill = normalize_skill_name(
                action.payload
            )
            if not requested_skill:
                continue

            if not accept_runtime_action_once_per_message(
                action,
                requested_skill,
            ):
                continue

            if requested_skill in loaded_skill_names:
                continue

            loaded_skill_names.add(
                requested_skill
            )

        if action.name == RUNTIME_ACTION_UNLOAD_SKILL:
            requested_skill = normalize_skill_name(
                action.payload
            )
            if not requested_skill:
                continue

            if not accept_runtime_action_once_per_message(
                action,
                requested_skill,
            ):
                continue

            loaded_skill_names.discard(
                requested_skill
            )

        if action.name not in {
            RUNTIME_ACTION_DEEP_WEB_SEARCH,
            RUNTIME_ACTION_WEB_SEARCH,
            RUNTIME_ACTION_LOAD_SKILL,
            RUNTIME_ACTION_UNLOAD_SKILL,
        }:
            if not accept_runtime_action_once_per_message(
                action
            ):
                continue

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
        if (
            not action_display_id
            and action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
        ):
            active_memory_action_sequence = int(
                getattr(
                    context,
                    "runtime_active_memory_action_sequence",
                    0,
                )
                or 0
            ) + 1
            context.runtime_active_memory_action_sequence = (
                active_memory_action_sequence
            )
            action_display_id = build_runtime_action_id(
                RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
                active_memory_action_sequence,
            )
            action_display_ids[id(action)] = action_display_id

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
        deep_search_objective = ""

        if action.name == RUNTIME_ACTION_DEEP_WEB_SEARCH:
            deep_search_objective = extract_search_query(
                action.payload
            )

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

        if action.name == RUNTIME_ACTION_DELETE_ACTIVE_MEMORY:
            active_memory_id = extract_active_memory_delete_slot_id(
                action.payload,
                existing_ids=collect_context_active_memory_slot_ids(
                    context
                ),
            )
            if active_memory_id:
                action_event["id"] = active_memory_id

        if deep_search_objective:
            deep_search_action_count += 1
            tool_call_id = (
                action_display_id
                or build_runtime_action_id(
                    action.name,
                    deep_search_action_count,
                )
            )
            action_event["id"] = tool_call_id
            action_event["query"] = deep_search_objective
            deep_search_calls.append({
                "id": tool_call_id,
                "query": deep_search_objective,
                "context": action_context_snapshot,
            })

        elif query:
            search_action_count += 1
            tool_call_id = (
                action_display_id
                or build_runtime_action_id(
                    action.name,
                    search_action_count,
                )
            )
            action_event["id"] = tool_call_id
            action_event["query"] = query
            search_calls.append({
                "id": tool_call_id,
                "query": query,
                "context": action_context_snapshot,
            })

        elif action.name == RUNTIME_ACTION_JIN_COLOR:
            color = normalize_jin_color_payload(
                action.payload
            )
            if color:
                action_event["color"] = color
                action_event["payload"] = color

        elif action.name == RUNTIME_ACTION_JIN_SIZE:
            size = normalize_jin_size_dict(
                action.payload
            )
            payload = normalize_jin_size_payload(
                action.payload
            )
            if size and payload:
                action_event["size"] = payload
                action_event["width"] = size["width"]
                action_event["height"] = size["height"]
                action_event["payload"] = payload

        elif action.name == RUNTIME_ACTION_JIN_POSITION:
            position = normalize_jin_position_dict(
                action.payload
            )
            payload = normalize_jin_position_payload(
                action.payload
            )
            if position and payload:
                action_event["position"] = payload
                action_event["x"] = position["x"]
                action_event["y"] = position["y"]
                action_event["payload"] = payload

        elif action.name == RUNTIME_ACTION_JIN_SPEED:
            speed = normalize_jin_speed_value(
                action.payload
            )
            payload = normalize_jin_speed_payload(
                action.payload
            )
            if speed is not None and payload:
                action_event["speed"] = speed
                action_event["payload"] = payload

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
            runtime_action_display_name = (
                get_runtime_action_display_name(
                    action.name
                )
            )
            runtime_action_display_text = (
                build_runtime_action_display_text(
                    action.name,
                    action.payload,
                )
            )
            runtime_action_id = str(
                action_event.get(
                    "id",
                    action_display_id,
                )
                or ""
            ).strip()

            if deep_search_objective:
                runtime_action_display_text = (
                    f"{runtime_action_display_name}: "
                    f"{deep_search_objective}"
                )

            mark_runtime_action_started(
                context,
                action=action_event.get(
                    "name",
                    action.name.lower(),
                ),
                action_id=runtime_action_id,
                display_name=runtime_action_display_name,
                text=runtime_action_display_text,
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

            if deep_search_objective:
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
                    await emit(with_action_context({
                        "type": "runtime_action",
                        "action": RUNTIME_ACTION_DEEP_WEB_SEARCH.lower(),
                        "id": runtime_action_id,
                        "status": "running",
                        "display_name": runtime_action_display_name,
                        "text": runtime_action_display_text,
                        "query": deep_search_objective,
                        "scene_effect": "search",
                        "deep_search_parent": True,
                        "deep_search_payload_ready": True,
                        "close_tag": runtime_action_has_close_tag(
                            action.name
                        ),
                    }))

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
                    and rejected_event.get("error") not in {
                        "behavior_contract_blocker_matched",
                        "restricted_write",
                    }
                    and not runtime_action_follows_up_on_fail(
                        action.name
                    )
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
                    "detail": (
                        rejected_event.get(
                            "failure_followup_message",
                            "",
                        )
                        or rejected_event.get(
                            "failure_reason",
                            "",
                        )
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
                if action.name == RUNTIME_ACTION_JIN_SIZE:
                    size = normalize_jin_size_dict(
                        action.payload
                    )
                    size_payload = normalize_jin_size_payload(
                        action.payload
                    )
                    if size and size_payload:
                        payload["size"] = size_payload
                        payload["width"] = size["width"]
                        payload["height"] = size["height"]
                        payload["payload"] = size_payload
                if action.name == RUNTIME_ACTION_JIN_POSITION:
                    position = normalize_jin_position_dict(
                        action.payload
                    )
                    position_payload = normalize_jin_position_payload(
                        action.payload
                    )
                    if position and position_payload:
                        payload["position"] = position_payload
                        payload["x"] = position["x"]
                        payload["y"] = position["y"]
                        payload["payload"] = position_payload
                if action.name == RUNTIME_ACTION_JIN_SPEED:
                    speed = normalize_jin_speed_value(
                        action.payload
                    )
                    speed_payload = normalize_jin_speed_payload(
                        action.payload
                    )
                    if speed is not None and speed_payload:
                        payload["speed"] = speed
                        payload["payload"] = speed_payload
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

    save_active_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY
    ]
    save_active_memory_count = len(
        save_active_memory_actions
    )

    update_active_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY
    ]

    delete_active_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
    ]
    delete_active_memory_count = len(
        delete_active_memory_actions
    )

    save_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY
    ]

    load_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LOAD_DELAYED_MEMORY
    ]

    unload_delayed_memory_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY
    ]

    list_file_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LIST_FILES
    ]
    attach_file_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_ATTACH_FILE
    ]
    detach_file_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_DETACH_FILE
    ]

    update_l4_facts_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_UPDATE_L4_FACTS
    ]

    clean_tool_result_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_CLEAN_TOOL_RESULTS
    ]

    jin_color_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_JIN_COLOR
    ]

    jin_size_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_JIN_SIZE
    ]

    jin_motion_actions = [
        action
        for action in filtered_actions
        if action.name in {
            RUNTIME_ACTION_JIN_POSITION,
            RUNTIME_ACTION_JIN_SPEED,
        }
    ]

    load_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_LOAD_SKILL
    ]

    unload_skill_actions = [
        action
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_UNLOAD_SKILL
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

    if deep_search_calls:
        context.runtime_deep_search_calls.extend(
            deep_search_calls
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

    # Explicit L4 edits start immediately on their own background lane.
    # Do not make them wait behind unrelated runtime action handlers.
    schedule_update_l4_facts_actions(
        context,
        update_l4_facts_actions,
        action_display_ids=action_display_ids,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    await emit_jin_visual_sequences(
        context,
        filtered_actions,
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

        clear_runtime_tool_results_before_state(
            context,
            tool_results_clean_state,
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
        load_skill_actions=load_skill_actions,
        unload_skill_actions=unload_skill_actions,
        runtime_todo_action_items=runtime_todo_action_items,
        log_runtime=log_runtime,
    )
    saved_asset_results = list(
        skill_results["saved_asset_results"]
    )
    loaded_skill_results = skill_results["loaded_skill_results"]
    unloaded_skill_results = skill_results["unloaded_skill_results"]

    saved_asset_results.extend(
        await apply_asset_actions(
            context,
            asset_actions,
            runtime_todo_action_items=runtime_todo_action_items,
            log_runtime=log_runtime,
            with_action_context=with_action_context,
        )
    )

    attachment_results = await apply_attachment_actions(
        context,
        list_actions=list_file_actions,
        attach_actions=attach_file_actions,
        detach_actions=detach_file_actions,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    delayed_memory_results = await apply_delayed_memory_actions(
        context,
        load_delayed_memory_actions=load_delayed_memory_actions,
        unload_delayed_memory_actions=unload_delayed_memory_actions,
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
        loaded_skill_results
        + unloaded_skill_results
    )

    await emit_skill_state_results(
        context,
        skill_state_results,
        with_action_context=with_action_context,
    )

    saved_active_memory_texts = await apply_save_active_memory_actions(
        context,
        save_active_memory_actions,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
        action_display_ids=action_display_ids,
    )

    saved_delayed_memory_reports = await apply_save_delayed_memory_actions(
        context,
        save_delayed_memory_actions,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    updated_active_memory_count = await apply_update_active_memory_actions(
        context,
        update_active_memory_actions,
        log_runtime=log_runtime,
        with_action_context=with_action_context,
    )

    deleted_active_memory_count = await apply_delete_active_memory_actions(
        context,
        delete_active_memory_actions,
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
            loaded_skill_results
        )
        + len(
            unloaded_skill_results
        )
        + len(
            clean_tool_result_actions
        )
        + len(
            jin_color_actions
        )
        + len(
            jin_size_actions
        )
        + len(
            jin_motion_actions
        )
        + len(
            update_l4_facts_actions
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
        + len(
            attachment_results
        )
        + updated_active_memory_count
        + deleted_active_memory_count
    )

    mark_runtime_actions_completed(
        context,
        filtered_actions,
        keep_actions={
            RUNTIME_ACTION_WEB_SEARCH,
                    RUNTIME_ACTION_UPDATE_L4_FACTS,
        },
    )

    return applied_count
