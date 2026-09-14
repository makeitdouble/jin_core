import unittest
from pathlib import Path
from unittest.mock import patch

from config_loader import load_config_module


class ConfigLoaderTests(unittest.TestCase):
    def test_uses_default_example_when_config_is_missing(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config_module(config_path=root / "missing.config.py")
        self.assertEqual(config.BRAIN_MODEL_UID, "brain-model")

    def test_falls_back_to_example_config(self):
        root = Path(__file__).resolve().parents[1]
        config = load_config_module(
            config_path=root / "missing.config.py",
            example_path=root / "config.example.py",
        )
        self.assertEqual(config.BRAIN_MAX_FOLLOWUPS, 50)
        self.assertEqual(config.SEARCH_PROVIDER, "serper")
        self.assertFalse(hasattr(config, "CHAT_ENDPOINT"))
        self.assertFalse(hasattr(config, "STREAM_VALIDATOR_MAX_REPEAT_SENTENCES"))

    def test_config_and_example_expose_same_keys_in_same_order(self):
        root = Path(__file__).resolve().parents[1]

        def uppercase_assignments(path):
            import ast
            tree = ast.parse(path.read_text(encoding="utf-8"))
            return [
                node.targets[0].id
                for node in tree.body
                if isinstance(node, ast.Assign)
                and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id.isupper()
            ]

        self.assertEqual(
            uppercase_assignments(root / "config.py"),
            uppercase_assignments(root / "config.example.py"),
        )

    def test_stream_validator_thresholds_live_outside_user_config(self):
        root = Path(__file__).resolve().parents[1]
        source = (root / "utils" / "stream_validator.py").read_text(encoding="utf-8")
        self.assertIn("STREAM_VALIDATOR_MAX_REPEAT_SENTENCES = 7", source)
        self.assertIn("STREAM_VALIDATOR_MAX_REPEAT_SYMBOLIC_MOTIFS = 5", source)
        self.assertNotIn("configured_int(", source)


    def test_env_overrides_fallback_config_values(self):
        root = Path(__file__).resolve().parents[1]
        with patch.dict("os.environ", {
            "BRAIN_MODEL_UID": "env-brain",
            "ENABLE_RUNTIME_LOGS": "false",
        }, clear=True):
            config = load_config_module(
                config_path=root / "missing.config.py",
                example_path=root / "config.example.py",
            )
        self.assertEqual(config.BRAIN_MODEL_UID, "env-brain")
        self.assertIs(config.ENABLE_RUNTIME_LOGS, False)

    def test_prefixed_env_overrides_are_supported(self):
        root = Path(__file__).resolve().parents[1]
        with patch.dict("os.environ", {
            "JIN_SERVICE_MODEL_UID": "prefixed-service",
            "SERVICE_API_BASE": "http://service.invalid/v1",
        }, clear=True):
            config = load_config_module(
                config_path=root / "missing.config.py",
                example_path=root / "config.example.py",
            )
        self.assertEqual(config.SERVICE_MODEL_UID, "prefixed-service")

    def test_unprefixed_env_has_priority_over_prefixed_env(self):
        root = Path(__file__).resolve().parents[1]
        with patch.dict("os.environ", {
            "SERVICE_MODEL_UID": "plain-service",
            "JIN_SERVICE_MODEL_UID": "prefixed-service",
            "SERVICE_API_BASE": "http://service.invalid/v1",
        }, clear=True):
            config = load_config_module(
                config_path=root / "missing.config.py",
                example_path=root / "config.example.py",
            )
        self.assertEqual(config.SERVICE_MODEL_UID, "plain-service")

    def test_invalid_bool_env_value_raises(self):
        root = Path(__file__).resolve().parents[1]
        with patch.dict("os.environ", {"ENABLE_RUNTIME_LOGS": "maybe"}, clear=True):
            with self.assertRaises(ValueError):
                load_config_module(
                    config_path=root / "missing.config.py",
                    example_path=root / "config.example.py",
                )


if __name__ == "__main__":
    unittest.main()
