import unittest
from pathlib import Path

from settings.config_loader import (
    load_config_module,
)


class ConfigLoaderTests(unittest.TestCase):

    def test_falls_back_to_example_config(self):

        root = Path(__file__).resolve().parents[1]

        config = load_config_module(
            config_path=(
                root / "missing.config.py"
            ),
            example_path=(
                root / "config.example.py"
            ),
        )

        self.assertEqual(
            config.CHAT_ENDPOINT,
            "/v1/chat/completions",
        )

        self.assertEqual(
            config.TRANSLATOR_MODEL_UID,
            "translator-model",
        )


if __name__ == "__main__":
    unittest.main()
