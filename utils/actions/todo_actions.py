from contracts.rules_assembler import (
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_RESOLVE_TODO,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.runtime_todo import (
    apply_runtime_todo_action_result,
    attach_runtime_todo_item_to_result,
    build_runtime_todo_history_text,
    check_runtime_todo_item,
    create_runtime_todo,
    has_active_runtime_todo,
    mark_next_runtime_todo_item_resolved,
    parse_runtime_todo_item_id,
    resolve_runtime_todo_item,
)
from utils.session_actions_history import (
    record_session_action_history,
)


def collect_runtime_todo_actions(
    context,
    filtered_actions,
    todo_action_names,
):
    runtime_todo_results = []
    runtime_todo_action_items = {}

    for action in filtered_actions:
        if action.name == RUNTIME_ACTION_CREATE_TODO_LIST:
            result = create_runtime_todo(
                context,
                action.payload,
            )
            runtime_todo_results.append(
                result
            )
            continue

        if action.name == RUNTIME_ACTION_RESOLVE_TODO:
            result = resolve_runtime_todo_item(
                context,
                parse_runtime_todo_item_id(
                    action.payload
                ),
            )
            runtime_todo_results.append(
                result
            )
            continue

        if action.name == RUNTIME_ACTION_CHECK_TODO:
            result = check_runtime_todo_item(
                context,
                parse_runtime_todo_item_id(
                    action.payload
                ),
            )
            runtime_todo_results.append(
                result
            )
            continue

        if has_active_runtime_todo(
            context
        ):
            todo_item = mark_next_runtime_todo_item_resolved(
                context
            )
            if todo_item is not None:
                runtime_todo_action_items[action] = dict(
                    todo_item
                )

    return (
        runtime_todo_results,
        runtime_todo_action_items,
    )


async def emit_runtime_todo_results(
    context,
    runtime_todo_results,
    *,
    log_runtime,
    with_action_context,
):
    if not runtime_todo_results:
        return

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] runtime_todo updated"
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

    for result in runtime_todo_results:
        text = build_runtime_todo_history_text(
            result
        )
        record_session_action_history(
            context,
            text,
        )
        if emit is not None:
            await emit(with_action_context({
                "type": "runtime_action",
                "action": str(
                    result.get(
                        "action",
                        "runtime_todo",
                    )
                    or "runtime_todo"
                ),
                "status": "completed" if result.get("ok") else "blocked",
                "display_name": get_runtime_action_display_name(
                    result.get(
                        "action",
                        "runtime_todo",
                    )
                ),
                "close_tag": runtime_action_has_close_tag(
                    result.get(
                        "action",
                        "runtime_todo",
                    )
                ),
                "text": text,
                "runtime_todo_result": result,
            }))


def attach_todo_result(
    context,
    runtime_todo_action_items,
    action,
    result,
):
    todo_item = apply_runtime_todo_action_result(
        context,
        runtime_todo_action_items.get(action),
        result,
    ) or runtime_todo_action_items.get(action)
    return attach_runtime_todo_item_to_result(
        result,
        todo_item,
    )
