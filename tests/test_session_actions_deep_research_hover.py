from types import SimpleNamespace
import unittest

from runtime.deep_research import _record_sequence_line



class DeepResearchSessionActionHoverTests(unittest.IsolatedAsyncioTestCase):

    async def test_completion_history_keeps_full_deep_research_text_for_hover(self):
        context = SimpleNamespace(
            runtime_session_action_history=[],
            emitter=None,
        )

        await _record_sequence_line(
            context,
            "DEEP_RESEARCH complete: 8/10 searches",
            hover_text=(
                "DEEP_RESEARCH: Deep dive into Noir Jazz genres and "
                "essential albums."
            ),
        )

        self.assertEqual(
            context.runtime_session_action_history[-1]["parts"][0][
                "context_detail"
            ],
            (
                "DEEP_RESEARCH: Deep dive into Noir Jazz genres and "
                "essential albums."
            ),
        )



if __name__ == "__main__":
    unittest.main()
