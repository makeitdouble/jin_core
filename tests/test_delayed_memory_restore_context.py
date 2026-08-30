import unittest

from rules.brain_context_builder import build_brain_context
from runtime.runtime_context import RuntimeContext


class DelayedMemoryRestoreContextTests(unittest.TestCase):

    def test_restore_priming_keeps_current_loaded_delayed_memory(self):
        context = RuntimeContext(
            websocket=None,
            emitter=None,
            logger=None,
            clients={},
        )
        context.runtime_session_restore_priming = True
        context.runtime_session_restore_pending_loaded_memory_ids = [
            "old123",
        ]
        context.runtime_loaded_delayed_memory = {
            "old123": {
                "title": "Archived report",
                "body": "ARCHIVED HEAVY BODY",
            },
            "new456": {
                "title": "Current tab report",
                "body": "CURRENT TAB DELAYED BODY",
                "pinned": True,
            },
        }
        context.runtime_loaded_delayed_memory_ids = [
            "old123",
            "new456",
        ]
        context.delayed_memory_reports = dict(
            context.runtime_loaded_delayed_memory
        )

        prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        self.assertNotIn(
            "ARCHIVED HEAVY BODY",
            prompt,
        )
        self.assertIn(
            "CURRENT TAB DELAYED BODY",
            prompt,
        )
        self.assertIn(
            "Current tab report",
            prompt,
        )


if __name__ == "__main__":
    unittest.main()
