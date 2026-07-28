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
from utils.tool_results import (
    TOOL_RESULT_KIND_ASSET,
    remove_runtime_tool_results,
)


async def apply_skill_actions(
    context,
    *,
    list_skill_actions,
    hide_skill_actions,
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
            context.runtime_visible_skills_result = result
            saved_asset_results.append(
                result
            )

    hidden_skill_results = []

    if hide_skill_actions:
        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] hide_skills requested"
            )

        for action in hide_skill_actions:
            was_visible = bool(
                getattr(
                    context,
                    "runtime_visible_skills_result",
                    {},
                )
            )
            context.runtime_visible_skills_result = {}
            remove_runtime_tool_results(
                context,
                lambda entry: (
                    entry.get("kind") == TOOL_RESULT_KIND_ASSET
                    and isinstance(entry.get("result"), dict)
                    and entry["result"].get("action") == "list_skills"
                ),
            )

            for attribute_name in (
                "runtime_asset_results",
                "runtime_asset_retry_context",
                "runtime_asset_retry_results",
            ):
                results = getattr(
                    context,
                    attribute_name,
                    None,
                )
                if not isinstance(
                    results,
                    list,
                ):
                    continue

                results[:] = [
                    result
                    for result in results
                    if not (
                        isinstance(
                            result,
                            dict,
                        )
                        and result.get(
                            "action"
                        ) == "list_skills"
                    )
                ]

            result = {
                "ok": True,
                "action": "hide_skills",
                "hidden": was_visible,
            }
            result = attach_todo_result(
                context,
                runtime_todo_action_items,
                action,
                result,
            )
            hidden_skill_results.append(
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
            appended_skill_results.append(
                result
            )
            if (
                result.get("ok") is False
                and result.get("error") == "skill_not_found"
            ):
                append_asset_runtime_result(
                    context,
                    result,
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
            removed_skill_results.append({
                "ok": True,
                "action": "remove_skill",
                "requested": requested,
                "removed": len(current_skills) < before_count,
            })

    if (
        appended_skill_results
        or removed_skill_results
    ):
        context.runtime_skill_state_barrier_active = True

    return {
        "saved_asset_results": saved_asset_results,
        "hidden_skill_results": hidden_skill_results,
        "appended_skill_results": appended_skill_results,
        "removed_skill_results": removed_skill_results,
    }


async def emit_skill_state_results(
    context,
    skill_state_results,
    *,
    with_action_context,
):
    skill_state_result_texts = []

    for result in skill_state_results:
        result_action = str(
            result.get(
                "action",
                "skill",
            )
            or "skill"
        )
        requested_skill = str(
            result.get(
                "requested",
                "",
            )
            or ""
        )
        if result_action == "append_skill":
            text = f"Appended skill: {requested_skill}"
        elif result_action == "remove_skill":
            text = f"Removed skill: {requested_skill}"
        else:
            text = "Hidden skills list"
        if (
            result_action == "append_skill"
            and result.get("ok") is False
            and result.get("error") == "skill_not_found"
        ):
            text = f"{text} ( does not exist )"

        skill_state_result_texts.append(
            (
                result,
                text,
            )
        )
        record_session_action_history(
            context,
            text,
        )

    if not skill_state_results:
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

    if emit is not None:
        for result_index, (result, text) in enumerate(
            skill_state_result_texts,
            start=1,
        ):
            result_action = str(
                result.get(
                    "action",
                    "skill",
                )
                or "skill"
            )
            action_id = build_runtime_action_id(
                result_action,
                len(context.runtime_action_events)
                + result_index,
            )
            status = (
                "completed"
                if result.get("ok") is not False
                else "failed"
            )
            payload = {
                "type": "runtime_action",
                "action": result_action,
                "id": action_id,
                "display_name": get_runtime_action_display_name(
                    result_action
                ),
                "close_tag": runtime_action_has_close_tag(
                    result_action
                ),
                "text": text,
                "skill_result": result,
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
