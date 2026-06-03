import unittest
from pathlib import Path
from unittest.mock import patch

from config_loader import (
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

    def test_env_overrides_fallback_config_values(self):

        root = Path(__file__).resolve().parents[1]

        with patch.dict(
            "os.environ",
            {
                "BRAIN_MODEL_UID": "env-brain",
                "USE_SERVICE_AS_BRAIN": "true",
                "BRAIN_CONTEXT_WINDOW": "12345",
                "SEARCH_TIMEOUT": "3.5",
            },
            clear=True,
        ):
            config = load_config_module(
                config_path=(
                    root / "missing.config.py"
                ),
                example_path=(
                    root / "config.example.py"
                ),
            )

        self.assertEqual(
            config.BRAIN_MODEL_UID,
            "env-brain",
        )

        self.assertIs(
            config.USE_SERVICE_AS_BRAIN,
            True,
        )

        self.assertEqual(
            config.BRAIN_CONTEXT_WINDOW,
            12345,
        )

        self.assertEqual(
            config.SEARCH_TIMEOUT,
            3.5,
        )

    def test_prefixed_env_overrides_are_supported(self):

        root = Path(__file__).resolve().parents[1]

        with patch.dict(
            "os.environ",
            {
                "JIN_SERVICE_MODEL_UID": "prefixed-service",
            },
            clear=True,
        ):
            config = load_config_module(
                config_path=(
                    root / "missing.config.py"
                ),
                example_path=(
                    root / "config.example.py"
                ),
            )

        self.assertEqual(
            config.SERVICE_MODEL_UID,
            "prefixed-service",
        )

    def test_unprefixed_env_has_priority_over_prefixed_env(self):

        root = Path(__file__).resolve().parents[1]

        with patch.dict(
            "os.environ",
            {
                "SERVICE_MODEL_UID": "plain-service",
                "JIN_SERVICE_MODEL_UID": "prefixed-service",
            },
            clear=True,
        ):
            config = load_config_module(
                config_path=(
                    root / "missing.config.py"
                ),
                example_path=(
                    root / "config.example.py"
                ),
            )

        self.assertEqual(
            config.SERVICE_MODEL_UID,
            "plain-service",
        )

    def test_invalid_bool_env_value_raises(self):

        root = Path(__file__).resolve().parents[1]

        with patch.dict(
            "os.environ",
            {
                "USE_SERVICE_AS_BRAIN": "maybe",
            },
            clear=True,
        ):
            with self.assertRaises(ValueError):
                load_config_module(
                    config_path=(
                        root / "missing.config.py"
                    ),
                    example_path=(
                        root / "config.example.py"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
