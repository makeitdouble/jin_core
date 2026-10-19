import asyncio
import contextlib

from .logger import WebSocketLogger

from runtime.runtime_context import RuntimeContext
from runtime.frame_memory import schedule_interrupted_runtime_memory_update
from utils.runtime_action_abort import abort_active_runtime_actions

async def cancel_current_task(
    task: asyncio.Task | None,
    logger: WebSocketLogger,
    context: RuntimeContext | None = None,
    *,
    update_memory: bool = True,
    emit_aborted_actions: bool = True,
):

    task_is_running = (
        task is not None
        and not task.done()
    )
    interrupted_instance_group = None

    # -----------------------------------
    # FORCE CLOSE ACTIVE STREAMS
    # -----------------------------------

    if context:

        context.runtime_turn_interrupted = True
        context.runtime_turn_abort_requested = True
        from utils.actions.attachment_actions import clear_path_attachments
        clear_path_attachments(context)
        context.runtime_turn_discard_requested = not update_memory
        from utils.actions.jin_instance_actions import interrupt_instance_group, self_fork_phase
        if self_fork_phase(context) in {"child_pending", "child_running", "parent_pending"}:
            interrupted_instance_group = interrupt_instance_group(context, "stopped_by_user")

        from clients.brain_client import emit_active_memory_records_update_if_dirty
        await emit_active_memory_records_update_if_dirty(context)

        await abort_active_runtime_actions(
            context,
            logger=logger,
            emit_to_client=emit_aborted_actions,
            remember_for_frame=update_memory,
        )

        active_streams = (
            getattr(
                context,
                "active_streams",
                {},
            )
        )

        for stream_id, response in list(
                active_streams.items()
        ):

            with contextlib.suppress(Exception):

                await response.aclose()

        active_streams.clear()

    # -----------------------------------
    # CANCEL TASK
    # -----------------------------------

    if not task_is_running:
        if context and update_memory:
            schedule_interrupted_runtime_memory_update(
                context=context,
            )
        return

    task.cancel()

    try:

        await task

    except asyncio.CancelledError:

        await logger.log_runtime(
            "Generation cancelled."
        )

    if context:
        # A cancelled stream appends its last reasoning in its finally block.
        # Restore the parent after that append as well as at the Stop boundary.
        from utils.actions.jin_instance_actions import restore_parent_reasoning
        if interrupted_instance_group is not None and getattr(context, "runtime_jin_instance_group", None) is interrupted_instance_group:
            restore_parent_reasoning(context)
        if not update_memory:
            return

        schedule_interrupted_runtime_memory_update(
            context=context,
        )

