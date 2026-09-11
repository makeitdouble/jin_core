import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from runtime.L1_memory_utils import build_runtime_memory_snapshot
from runtime.runtime_context import RuntimeContext
from websocket.bootstrap import apply_runtime_memory_slot_delete



class Emitter:
    def __init__(self):
        self.events = []

    async def emit(self, data):
        self.events.append(data)


class Logger:
    def __init__(self):
        self.system_logs = []

    async def log_system(self, message):
        self.system_logs.append(message)


class RuntimeMemoryDeleteGuardTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.context = RuntimeContext(None, Emitter(), Logger(), {})
        self.context.runtime_memory = (
            "discussion_focus: keep me\n"
            "user_state: unchanged"
        )
        self.context.runtime_memory_stable = self.context.runtime_memory
        self.context.runtime_memory_updates = 4
        self.context.runtime_memory_snapshots = [
            build_runtime_memory_snapshot(
                self.context,
                self.context.runtime_memory,
            )
        ]
        self.context.runtime_memory_snapshot_index = 0

    async def test_foreground_busy_blocks_delete_and_reconciles_optimistic_client(self):
        original = self.context.runtime_memory
        original_updates = self.context.runtime_memory_updates

        with patch(
            "websocket.bootstrap.emit_runtime_memory_snapshot_refresh",
            new_callable=AsyncMock,
        ) as refresh, patch(
            "websocket.bootstrap.emit_runtime_l1_diff_update",
            new_callable=AsyncMock,
        ) as diff:
            deleted = await apply_runtime_memory_slot_delete(
                self.context,
                {"key": "discussion_focus"},
                foreground_busy=True,
            )

        self.assertFalse(deleted)
        self.assertEqual(self.context.runtime_memory, original)
        self.assertEqual(self.context.runtime_memory_stable, original)
        self.assertEqual(self.context.runtime_memory_updates, original_updates)
        refresh.assert_awaited_once()
        diff.assert_not_awaited()
        self.assertIn("slot delete blocked: memory busy", self.context.logger.system_logs[-1])

    async def test_pending_frame_update_blocks_delete(self):
        original = self.context.runtime_memory
        pending = asyncio.get_running_loop().create_future()
        self.context.runtime_memory_update_task = pending

        try:
            with patch(
                "websocket.bootstrap.emit_runtime_memory_snapshot_refresh",
                new_callable=AsyncMock,
            ) as refresh:
                deleted = await apply_runtime_memory_slot_delete(
                    self.context,
                    {"key": "discussion_focus"},
                )
        finally:
            pending.cancel()
            self.context.runtime_memory_update_task = None

        self.assertFalse(deleted)
        self.assertEqual(self.context.runtime_memory, original)
        refresh.assert_awaited_once()

    async def test_completed_frame_update_does_not_block_delete(self):
        done = asyncio.get_running_loop().create_future()
        done.set_result(None)
        self.context.runtime_memory_update_task = done

        with patch(
            "websocket.bootstrap.emit_runtime_memory_snapshot_refresh",
            new_callable=AsyncMock,
        ) as refresh, patch(
            "websocket.bootstrap.emit_runtime_l1_diff_update",
            new_callable=AsyncMock,
        ) as diff:
            deleted = await apply_runtime_memory_slot_delete(
                self.context,
                {"key": "discussion_focus"},
            )

        self.assertTrue(deleted)
        self.assertNotIn("discussion_focus:", self.context.runtime_memory)
        self.assertEqual(self.context.runtime_memory_updates, 5)
        refresh.assert_awaited_once()
        diff.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
