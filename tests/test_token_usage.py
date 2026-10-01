import unittest
from math import ceil
from types import SimpleNamespace

from utils.token_usage import (
    calibrate_runtime_token_estimate,
    get_runtime_token_estimate_scale,
    record_token_usage,
)
from utils.tokens import (
    estimate_stream_input_tokens,
    estimate_tokens,
)


class TokenUsageTests(unittest.TestCase):

    def test_general_estimate_uses_conservative_context_size(self):

        prompt = (
            "active_runtime_memory_entry "
            * 200
        )

        self.assertEqual(
            estimate_tokens(
                prompt
            ),
            estimate_stream_input_tokens(
                None,
                prompt_text=prompt,
            ),
        )
        self.assertEqual(
            estimate_tokens(
                prompt
            ),
            1400,
        )
        self.assertEqual(
            estimate_stream_input_tokens(
                None,
                prompt_text=prompt,
            ),
            1400,
        )

    def test_stream_estimate_keeps_symbol_heavy_prompt_word_based(self):

        prompt = "* " * 7000

        self.assertEqual(
            estimate_stream_input_tokens(
                None,
                prompt_text=prompt,
            ),
            7000,
        )

    def test_stream_estimate_uses_character_floor_for_normal_prompt(self):

        prompt = (
            "ordinary english prompt words "
            * 100
        )

        self.assertEqual(
            estimate_stream_input_tokens(
                None,
                prompt_text=prompt,
            ),
            ceil(
                len(prompt) / 4
            ),
        )
        self.assertGreater(
            estimate_stream_input_tokens(
                None,
                prompt_text=prompt,
            ),
            len(
                prompt.split()
            ),
        )

    def test_stream_estimate_counts_utf8_bytes_for_cyrillic(self):

        prompt = (
            "привет продолжай последовательность "
            * 100
        )

        self.assertEqual(
            estimate_stream_input_tokens(
                None,
                prompt_text=prompt,
            ),
            ceil(
                len(
                    prompt.encode(
                        "utf-8"
                    )
                ) / 4
            ),
        )

    def test_stream_estimate_applies_provider_calibration_scale(self):

        prompt = (
            "runtime system context "
            * 100
        )
        baseline = estimate_stream_input_tokens(
            None,
            prompt_text=prompt,
        )

        self.assertEqual(
            estimate_stream_input_tokens(
                None,
                prompt_text=prompt,
                scale=1.5,
            ),
            ceil(
                baseline * 1.5
            ),
        )

    def test_provider_prompt_usage_calibrates_next_estimate(self):

        context = SimpleNamespace()

        first_scale = calibrate_runtime_token_estimate(
            context,
            runtime_id="brain-model",
            estimated_prompt_tokens=100,
            provider_prompt_tokens=180,
        )

        self.assertAlmostEqual(
            first_scale,
            1.8,
        )
        self.assertAlmostEqual(
            get_runtime_token_estimate_scale(
                context,
                "brain-model",
            ),
            1.8,
        )

        second_scale = calibrate_runtime_token_estimate(
            context,
            runtime_id="brain-model",
            estimated_prompt_tokens=100,
            provider_prompt_tokens=150,
        )

        self.assertAlmostEqual(
            second_scale,
            1.695,
        )



if __name__ == "__main__":
    unittest.main()
