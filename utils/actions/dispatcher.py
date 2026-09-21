"""Source-ordered runtime action dispatcher."""

from itertools import groupby

from runtime.anonymous_mode import persistent_writes_restricted
from utils.assets_utils import ensure_assets_tree
from utils.runtime_action_abort import mark_runtime_actions_completed
from utils.tool_results import snapshot_runtime_tool_results_state

from .action_registry import KEEP_ACTIVE_ACTIONS, get_action
from .action_state import ActionState
from .active_memory_actions import emit_rejected_active_memory_results
from .action_context import ActionContext
from .action_events import record_action_event, snapshot_search_counts
from .malformed_action_utils import record_malformed_action


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
    if context is None or not actions:
        return 0

    applied = 0
    # Malformed notifications split batches but never reorder valid actions.
    for malformed, group in groupby(
        actions, key=lambda action: action.name == "MALFORMED_ACTION"
    ):
        if malformed:
            for action in group:
                await record_malformed_action(
                    context,
                    action,
                    runtime_message_id=runtime_message_id,
                    context_snapshot=context_snapshot,
                )
            continue

        applied += await _run_batch(
            context,
            tuple(group),
            user_message=user_message,
            context_snapshot=context_snapshot,
            confirmed_action_ids=confirmed_action_ids,
            rejected_action_ids=rejected_action_ids,
            guard_confirmation_ids=guard_confirmation_ids,
            action_display_ids=action_display_ids,
            runtime_message_id=runtime_message_id,
        )

    return applied


async def _run_batch(
    context,
    actions,
    *,
    user_message,
    context_snapshot,
    confirmed_action_ids,
    rejected_action_ids,
    guard_confirmation_ids,
    action_display_ids,
    runtime_message_id,
):
    batch = ActionContext.create(
        context,
        user_message,
        context_snapshot,
        confirmed_action_ids,
        rejected_action_ids,
        guard_confirmation_ids,
        action_display_ids,
        runtime_message_id,
    )
    if not persistent_writes_restricted(context):
        ensure_assets_tree()

    state = {
        # CLEAN_TOOL_RESULTS must only clear results that existed before this
        # emitted action stream, not results created by earlier calls in it.
        "tool_results_clean_state": snapshot_runtime_tool_results_state(context),
    }
    search_counts = snapshot_search_counts(context)
    action_state = ActionState(batch)
    applied = 0

    # This is the core invariant: prepare and run each call before touching the
    # next one. Runtime state therefore evolves in exactly the model's emitted
    # order: A.prepare -> A.run -> B.prepare -> B.run -> ...
    for action in actions:
        rejected_result_offset = len(action_state.rejected_active_memory_results)
        status = await action_state.prepare(action)

        if status == "reused":
            applied += 1
            continue

        if status == "rejected":
            await record_action_event(
                batch,
                action_state,
                action,
                search_counts,
                accepted=False,
            )
            new_rejected_results = action_state.rejected_active_memory_results[
                rejected_result_offset:
            ]
            if new_rejected_results:
                await emit_rejected_active_memory_results(
                    batch.context,
                    new_rejected_results,
                    with_action_context=batch.with_action_context_for(action),
                )
            continue

        if status != "ready":
            continue

        await record_action_event(
            batch,
            action_state,
            action,
            search_counts,
            accepted=True,
        )

        definition = get_action(action.name)
        if definition is None or definition.run is None:
            continue

        try:
            applied += await definition.run(batch, action, state)
        except Exception as exc:
            emit = getattr(getattr(batch.context, "emitter", None), "emit", None)
            if emit is not None:
                await emit(batch.with_action_context_for(action)({
                    "type": "runtime_action",
                    "action": action.name.lower(),
                    "id": str(batch.action_display_ids.get(id(action), "") or ""),
                    "status": "failed",
                    "error": type(exc).__name__,
                    "detail": str(exc),
                    "payload": action.payload,
                }))
            raise
        mark_runtime_actions_completed(
            batch.context,
            (action,),
            keep_actions=KEEP_ACTIVE_ACTIONS,
        )

    return applied
