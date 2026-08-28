import re
import unittest
from types import SimpleNamespace

from config_loader import config
from rules.brain_context_builder import build_brain_context
from utils.current_context_window import (
    CURRENT_CONTEXT_WINDOW_PLACEHOLDER,
    estimate_current_context_tokens,
    prepare_current_context_window_prompt,
)


class FakeRuntimeClient:

    def __init__(
        self,
        context_window: int,
    ):

        self.context_window = context_window
        self.force_refresh_values = []

    async def resolve_request_context_window(
        self,
        *,
        force_refresh=False,
    ):

        self.force_refresh_values.append(
            force_refresh
        )

        return self.context_window


class CurrentContextWindowTests(
    unittest.IsolatedAsyncioTestCase
):

    async def test_prepare_inserts_detected_context_window_under_current_model(self):

        context = SimpleNamespace(
            runtime_action_events=[],
            runtime_token_estimate_scales={},
        )
        system_prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )
        user_prompt = "hello"

        prepared = await prepare_current_context_window_prompt(
            client=FakeRuntimeClient(
                32728
            ),
            context=context,
            runtime_id=config.BRAIN_MODEL_UID,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            fallback_context_window=8192,
            force_refresh=True,
        )

        self.assertNotIn(
            CURRENT_CONTEXT_WINDOW_PLACEHOLDER,
            prepared.system_prompt,
        )
        self.assertIn(
            "/32728 occupied</CURRENT_CONTEXT_WINDOW>",
            prepared.system_prompt,
        )
        self.assertLess(
            prepared.system_prompt.index(
                "<CURRENT_MODEL_UID>"
            ),
            prepared.system_prompt.index(
                "<CURRENT_CONTEXT_WINDOW>"
            ),
        )
        self.assertLess(
            prepared.system_prompt.index(
                "<CURRENT_CONTEXT_WINDOW>"
            ),
            prepared.system_prompt.index(
                "<CURRENT_JIN_COLOR>"
            ),
        )

        match = re.search(
            r"<CURRENT_CONTEXT_WINDOW>(\d+)/32728 occupied</CURRENT_CONTEXT_WINDOW>",
            prepared.system_prompt,
        )
        self.assertIsNotNone(
            match
        )
        self.assertEqual(
            int(
                match.group(1)
            ),
            estimate_current_context_tokens(
                context=context,
                runtime_id=config.BRAIN_MODEL_UID,
                system_prompt=prepared.system_prompt,
                user_prompt=user_prompt,
            ),
        )

    async def test_prepare_replaces_stale_context_window_value(self):

        context = SimpleNamespace(
            runtime_action_events=[],
            runtime_token_estimate_scales={},
            runtime_current_context_window_text="1/8192 occupied",
        )
        system_prompt = build_brain_context(
            context=context,
            runtime_actions={
                "CAN_WEB_SEARCH": False,
            },
        )

        prepared = await prepare_current_context_window_prompt(
            client=FakeRuntimeClient(
                32728
            ),
            context=context,
            runtime_id=config.BRAIN_MODEL_UID,
            system_prompt=system_prompt,
            user_prompt="follow up",
            fallback_context_window=8192,
        )

        self.assertNotIn(
            "1/8192 occupied",
            prepared.system_prompt,
        )
        self.assertIn(
            prepared.value,
            prepared.system_prompt,
        )
        self.assertEqual(
            context.runtime_current_context_window_text,
            prepared.value,
        )


if __name__ == "__main__":
    unittest.main()
