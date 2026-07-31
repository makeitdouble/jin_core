from contracts.rules_assembler import (
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.actions import build_runtime_action_id
from utils.actions.todo_actions import attach_todo_result
from utils.session_actions_history import record_session_action_history
from utils.skills_asset_utils import (
    list_skills,
    load_skill,
    normalize_skill_name,
)


_RUNTIME_MARKER_NAME = "_runtime_marker_name"
_RUNTIME_MARKER_PAYLOAD = "_runtime_marker_payload"
_RUNTIME_MARKER_GROUP = "_runtime_marker_group"


def _attach_skill_marker_metadata(
    result: dict,
    action,
) -> dict:

    enriched_result = dict(
        result
    )
    marker_name = str(
        getattr(
            action,
            "marker_name",
            "",
        )
        or getattr(
            action,
            "name",
            "",
        )
        or ""
    ).strip().upper()
    marker_payload = str(
        getattr(
            action,
            "marker_payload",
            "",
        )
        or getattr(
            action,
            "payload",
            "",
        )
        or ""
    ).strip()
    marker_group = str(
        getattr(
            action,
            "marker_group",
            "",
        )
        or ""
    ).strip()

    if marker_name:
        enriched_result[_RUNTIME_MARKER_NAME] = marker_name

    if marker_payload:
        enriched_result[_RUNTIME_MARKER_PAYLOAD] = marker_payload

    if marker_group:
        enriched_result[_RUNTIME_MARKER_GROUP] = marker_group

    return enriched_result


def _public_skill_result(
    result: dict,
) -> dict:

    return {
        key: value
        for key, value in result.items()
        if not str(
            key
            or ""
        ).startswith(
            "_runtime_"
        )
    }


def _group_skill_state_results(
    skill_state_results,
) -> list[list[dict]]:

    groups = []
    plural_groups = {}

    for result in skill_state_results or ():
        if not isinstance(
            result,
            dict,
        ):
            continue

        marker_name = str(
            result.get(
                _RUNTIME_MARKER_NAME,
                "",
            )
            or ""
        ).strip().upper()
        marker_group = str(
            result.get(
                _RUNTIME_MARKER_GROUP,
                "",
            )
            or ""
        ).strip()
        is_plural = marker_name in {
            "APPEND_SKILLS",
            "REMOVE_SKILLS",
        }

        if not is_plural or not marker_group:
            groups.append([
                result,
            ])
            continue

        group = plural_groups.get(
            marker_group
        )

        if group is None:
            group = []
            plural_groups[marker_group] = group
            groups.append(
                group
            )

        group.append(
            result
        )

    return groups


def _build_skill_state_group_payload(
    results,
) -> tuple[str, str, str, str, dict, bool]:

    first_result = results[0]
    first_action = str(
        first_result.get(
            "action",
            "skill",
        )
        or "skill"
    ).strip().casefold()
    marker_name = str(
        first_result.get(
            _RUNTIME_MARKER_NAME,
            "",
        )
        or ""
    ).strip().upper()
    marker_payload = str(
        first_result.get(
            _RUNTIME_MARKER_PAYLOAD,
            "",
        )
        or ""
    ).strip()

    if not marker_name:
        marker_name = (
            "APPEND_SKILL"
            if first_action == "append_skill"
            else (
                "REMOVE_SKILL"
                if first_action == "remove_skill"
                else first_action.upper()
            )
        )

    is_plural = marker_name in {
        "APPEND_SKILLS",
        "REMOVE_SKILLS",
    }

    if marker_payload:
        requested_names = [
            part.strip()
            for part in marker_payload.split(",")
            if part.strip()
        ]
    else:
        requested_names = [
            str(
                result.get(
                    "requested",
                    "",
                )
                or ""
            ).strip()
            for result in results
        ]

    failures_by_name = {
        normalize_skill_name(
            result.get(
                "requested",
                "",
            )
        ): result
        for result in results
        if result.get("ok") is False
    }
    display_payloads = []

    for requested_name in requested_names:
        display_name = requested_name
        failed_result = failures_by_name.get(
            normalize_skill_name(
                requested_name
            )
        )

        if (
            failed_result is not None
            and failed_result.get("error") == "skill_not_found"
        ):
            display_name = (
                f"{display_name} "
                "( does not exist )"
            )

        if display_name:
            display_payloads.append(
                display_name
            )

    display_payload = ", ".join(
        display_payloads
    )
    text = (
        f"{marker_name}: {display_payload}"
        if display_payload
        else marker_name
    )
    event_action = marker_name.lower()
    all_ok = all(
        result.get("ok") is not False
        for result in results
    )

    if is_plural:
        skill_result = {
            "ok": all_ok,
            "action": event_action,
            "requested": requested_names,
            "results": [
                _public_skill_result(
                    result
                )
                for result in results
            ],
        }
    else:
        skill_result = _public_skill_result(
            first_result
        )

    return (
        marker_name,
        event_action,
        display_payload,
        text,
        skill_result,
        all_ok,
    )


async def apply_skill_actions(
    context,
    *,
    list_skill_actions,
    append_skill_actions,
    remove_skill_actions,
    runtime_todo_action_items,
    log_runtime,
):
    from utils.brain_client_utils import append_asset_runtime_result

    saved_asset_results = []

    if list_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] list_skills requested"
            )

        for action in list_skill_actions:
            result = list_skills(
                action.payload
            )
            result = attach_todo_result(
                context,
                runtime_todo_action_items,
                action,
                result,
            )
            append_asset_runtime_result(
                context,
                result,
            )
            saved_asset_results.append(
                result
            )

    appended_skill_results = []

    if append_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] append_skill requested"
            )

        current_skills = list(
            getattr(
                context,
                "runtime_appended_skills",
                [],
            )
            or []
        )

        for action in append_skill_actions:
            result = load_skill(
                action.payload
            )
            skill = result.get(
                "skill",
            )

            if result.get("ok") and isinstance(skill, dict):
                skill_name = normalize_skill_name(
                    skill.get(
                        "name",
                        "",
                    )
                )
                current_skills = [
                    existing
                    for existing in current_skills
                    if normalize_skill_name(
                        existing.get(
                            "name",
                            "",
                        )
                    ) != skill_name
                ]
                current_skills.append(
                    skill
                )
                context.runtime_appended_skills = current_skills

            result = attach_todo_result(
                context,
                runtime_todo_action_items,
                action,
                result,
            )
            if (
                result.get("ok") is False
                and result.get("error") == "skill_not_found"
            ):
                append_asset_runtime_result(
                    context,
                    dict(
                        result
                    ),
                )

            appended_skill_results.append(
                _attach_skill_marker_metadata(
                    result,
                    action,
                )
            )

    removed_skill_results = []

    if remove_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] remove_skill requested"
            )

        current_skills = list(
            getattr(
                context,
                "runtime_appended_skills",
                [],
            )
            or []
        )

        for action in remove_skill_actions:
            requested = normalize_skill_name(
                action.payload
            )
            before_count = len(
                current_skills
            )
            current_skills = [
                skill
                for skill in current_skills
                if normalize_skill_name(
                    skill.get(
                        "name",
                        "",
                    )
                ) != requested
            ]
            context.runtime_appended_skills = current_skills
            result = {
                "ok": True,
                "action": "remove_skill",
                "requested": requested,
                "removed": len(current_skills) < before_count,
            }
            removed_skill_results.append(
                _attach_skill_marker_metadata(
                    result,
                    action,
                )
            )

    if (
        appended_skill_results
        or removed_skill_results
    ):
        context.runtime_skill_state_barrier_active = True

    return {
        "saved_asset_results": saved_asset_results,
        "appended_skill_results": appended_skill_results,
        "removed_skill_results": removed_skill_results,
    }


async def emit_skill_state_results(
    context,
    skill_state_results,
    *,
    with_action_context,
):
    if not skill_state_results:
        return

    grouped_results = _group_skill_state_results(
        skill_state_results
    )
    skill_state_result_events = []

    for results in grouped_results:
        if not results:
            continue

        (
            marker_name,
            result_action,
            display_payload,
            text,
            skill_result,
            all_ok,
        ) = _build_skill_state_group_payload(
            results
        )
        skill_state_result_events.append({
            "marker_name": marker_name,
            "action": result_action,
            "display_payload": display_payload,
            "text": text,
            "skill_result": skill_result,
            "ok": all_ok,
        })
        record_session_action_history(
            context,
            text,
            preserve_separate=(
                marker_name
                not in {
                    "APPEND_SKILLS",
                    "REMOVE_SKILLS",
                }
            ),
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
        for result_index, result_event in enumerate(
            skill_state_result_events,
            start=1,
        ):
            result_action = str(
                result_event.get(
                    "action",
                    "skill",
                )
                or "skill"
            )
            text = str(
                result_event.get(
                    "text",
                    "",
                )
                or ""
            )
            action_id = build_runtime_action_id(
                result_action,
                len(context.runtime_action_events)
                + result_index,
            )
            status = (
                "completed"
                if result_event.get("ok") is not False
                else "failed"
            )
            payload = {
                "type": "runtime_action",
                "action": result_action,
                "id": action_id,
                "display_name": result_event.get(
                    "marker_name",
                    "",
                ) or get_runtime_action_display_name(
                    result_action
                ),
                "close_tag": runtime_action_has_close_tag(
                    result_action
                ),
                "text": text,
                "payload": result_event.get(
                    "display_payload",
                    "",
                ),
                "skill_result": result_event.get(
                    "skill_result",
                    {},
                ),
            }

            if status == "failed":
                await emit(with_action_context({
                    **payload,
                    "status": status,
                }))
                continue

            await emit(with_action_context(
                payload
            ))
            await emit(with_action_context({
                **payload,
                "status": status,
            }))
