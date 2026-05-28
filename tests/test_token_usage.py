import unittest
from types import SimpleNamespace

from utils.token_usage import (
    format_token_usage_summary,
    record_token_usage,
)


class TokenUsageTests(unittest.TestCase):

    def test_format_token_usage_summary_sums_flow_events(self):

        context = SimpleNamespace()

        record_token_usage(
            context,
            runtime_id="brain-model",
            role="brain",
            kind="brain",
            prompt_tokens=10,
            completion_tokens=5,
            total_tokens=15,
            context_tokens=12,
        )
        record_token_usage(
            context,
            runtime_id="service-model",
            role="service",
            kind="service",
            prompt_tokens=20,
            completion_tokens=7,
            total_tokens=27,
        )

        self.assertEqual(
            format_token_usage_summary(
                context
            ),
            (
                "PROVIDER USAGE\n"
                "brain: 15 (prompt=10, completion=5)\n"
                "service: 27 (prompt=20, completion=7)\n"
                "total: 42"
            ),
        )


if __name__ == "__main__":
    unittest.main()
