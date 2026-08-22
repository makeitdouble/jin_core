import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import app as app_module


class FakeStatusResponse:

    def __init__(self, payload, status_code=200):
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


class FakeStatusClient:

    def __init__(self, payload):
        self.payload = payload
        self.urls = []

    async def get(self, url, timeout):
        self.urls.append(url)
        return FakeStatusResponse(self.payload)


class RuntimeStatusConfigTests(unittest.IsolatedAsyncioTestCase):

    def test_write_runtime_config_values_rewrites_allowlisted_assignments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.py"
            config_path.write_text(
                "\n".join([
                    "SERVICE_MODEL_UID = 'old-service'",
                    "SERVICE_CONTEXT_WINDOW = 4096",
                    "BRAIN_MODEL_UID = 'old-brain'",
                ]) + "\n",
                encoding="utf-8",
            )

            with patch.object(app_module, "CONFIG_ROOT", root):
                app_module.write_runtime_config_values({
                    "SERVICE_MODEL_UID": "new-service",
                    "SERVICE_CONTEXT_WINDOW": 8192,
                })

            text = config_path.read_text(encoding="utf-8")

        self.assertIn(
            "SERVICE_MODEL_UID = 'new-service'",
            text,
        )
        self.assertIn(
            "SERVICE_CONTEXT_WINDOW = 8192",
            text,
        )
        self.assertIn(
            "BRAIN_MODEL_UID = 'old-brain'",
            text,
        )

    async def test_fetch_runtime_model_status_returns_url_and_model_options(self):
        client = FakeStatusClient({
            "models": [
                {
                    "key": "model-a",
                    "display_name": "Model A",
                },
                {
                    "key": "model-b",
                    "display_name": "Model B",
                    "loaded_instances": [
                        {
                            "id": "model-b",
                            "loaded_context_length": 16384,
                        }
                    ],
                },
            ],
        })

        result = await app_module.fetch_runtime_model_status(
            client,
            base_url="http://runtime.test",
            model_uid="model-b",
            configured_context_window=4096,
        )

        self.assertTrue(result["online"])
        self.assertEqual(
            result["url"],
            "http://runtime.test/api/v1/models",
        )
        self.assertEqual(
            result["available_models"],
            [
                {
                    "id": "model-a",
                    "name": "Model A",
                },
                {
                    "id": "model-b",
                    "name": "Model B",
                },
            ],
        )
        self.assertTrue(result["loaded"])


if __name__ == "__main__":
    unittest.main()
