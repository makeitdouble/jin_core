import asyncio
import contextlib
from collections import deque

from .logger import WebSocketLogger

from runtime.runtime_context import RuntimeContext
from runtime.L1_memory import schedule_interrupted_runtime_memory_update
from utils.runtime_action_abort import abort_active_runtime_actions


class PendingRequestQueue(asyncio.Queue):

    def _init(self, maxsize):
        self._idle_followups = deque()
        self._regular_requests = deque()

    @staticmethod
    def _is_idle_followup(item) -> bool:
        return (
            isinstance(item, dict)
            and item.get("type") == "idle_followup"
            and isinstance(
                item.get("idle_followup"),
                dict,
            )
        )

    def qsize(self) -> int:
        return (
            len(self._idle_followups)
            + len(self._regular_requests)
        )

    def empty(self) -> bool:
        return self.qsize() == 0

    def _put(self, item) -> None:
        target = (
            self._idle_followups
            if self._is_idle_followup(item)
            else self._regular_requests
        )
        target.append(item)

    def _get(self):
        if self._idle_followups:
            return self._idle_followups.popleft()

        return self._regular_requests.popleft()


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

    # -----------------------------------
    # FORCE CLOSE ACTIVE STREAMS
    # -----------------------------------

    if context:

        context.runtime_turn_interrupted = True
        context.runtime_turn_abort_requested = True
        context.runtime_turn_discard_requested = not update_memory

        await abort_active_runtime_actions(
            context,
            logger=logger,
            emit_to_client=emit_aborted_actions,
            remember_for_l1=update_memory,
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
        if not update_memory:
            return

        schedule_interrupted_runtime_memory_update(
            context=context,
        )

