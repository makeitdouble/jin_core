import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from types import SimpleNamespace

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


class FakeStatusSequenceClient:

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.urls = []

    async def get(self, url, timeout):
        self.urls.append(url)
        index = min(len(self.urls) - 1, len(self.payloads) - 1)
        return FakeStatusResponse(self.payloads[index])


class RuntimeStatusConfigTests(unittest.IsolatedAsyncioTestCase):

    def test_runtime_config_uses_detected_context_as_panel_denominator(self):
        runtime_config = app_module.build_runtime_config(
            brain_status={
                "context_window": 16384,
            },
            service_status={
                "context_window": 4096,
            },
        )

        self.assertEqual(
            runtime_config["brain"]["max_tokens"],
            16384,
        )
        self.assertEqual(
            runtime_config["service"]["max_tokens"],
            (
                4096
                if app_module.settings.SERVICE_CONFIGURED
                else 16384
            ),
        )

    def test_write_runtime_config_values_rewrites_allowlisted_assignments(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.py"
            config_path.write_text(
                "\n".join([
                    "SERVICE_MODEL_UID = 'old-service'",
                    "BRAIN_MODEL_UID = 'old-brain'",
                ]) + "\n",
                encoding="utf-8",
            )

            with patch.object(app_module, "CONFIG_ROOT", root):
                app_module.write_runtime_config_values({
                    "SERVICE_MODEL_UID": "new-service",
                })

            text = config_path.read_text(encoding="utf-8")

        self.assertIn(
            "SERVICE_MODEL_UID = 'new-service'",
            text,
        )
        self.assertIn(
            "BRAIN_MODEL_UID = 'old-brain'",
            text,
        )

    async def test_switch_persists_launcher_utf8_bom_config(self):
        # Windows PowerShell Set-Content -Encoding UTF8 writes this BOM.
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            config_path = root / "config.py"
            config_path.write_text(
                "# Launcher config\nBRAIN_MODEL_UID = 'old-brain'\n",
                encoding="utf-8-sig",
            )
            request = SimpleNamespace(json=AsyncMock(return_value={
                "role": "brain",
                "model": "new-brain",
            }))
            with (
                patch.object(app_module, "CONFIG_ROOT", root),
                patch.object(app_module.app.state, "http_client", object(), create=True),
                patch.object(app_module, "initialize_runtime_model", AsyncMock(
                    return_value={"model": "new-brain"},
                )),
                patch.object(app_module, "apply_runtime_config_values") as apply,
                patch.object(app_module, "build_status_snapshot", AsyncMock(
                    return_value={"brain": True},
                )),
            ):
                result = await app_module.api_switch_runtime_model(request)
            self.assertEqual(result["model_switch"]["model"], "new-brain")
            apply.assert_called_once_with(
                {"BRAIN_MODEL_UID": "new-brain"}, app_module.app,
            )
            restored = {}
            exec(compile(config_path.read_bytes(), str(config_path), "exec"), restored)
            self.assertEqual(restored["BRAIN_MODEL_UID"], "new-brain")

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
        self.assertEqual(result["context_window"], 16384)

    async def test_fetch_runtime_model_status_keeps_probing_until_context_is_known(self):
        client = FakeStatusSequenceClient([
            {
                "models": [
                    {
                        "key": "model-b",
                        "loaded_instances": [
                            {
                                "id": "model-b",
                            }
                        ],
                    },
                ],
            },
            {
                "models": [
                    {
                        "key": "model-b",
                        "loaded_instances": [
                            {
                                "id": "model-b",
                                "loaded_context_length": 32768,
                            }
                        ],
                    },
                ],
            },
        ])

        result = await app_module.fetch_runtime_model_status(
            client,
            base_url="http://runtime.test",
            model_uid="model-b",
        )

        self.assertEqual(result["context_window"], 32768)
        self.assertEqual(
            client.urls[:2],
            [
                "http://runtime.test/api/v1/models",
                "http://runtime.test/api/v0/models",
            ],
        )

    async def test_fetch_runtime_model_status_does_not_use_theoretical_max_as_panel_context(self):
        client = FakeStatusSequenceClient([
            {
                "models": [
                    {
                        "key": "model-b",
                        "max_context_length": 131072,
                    },
                ],
            },
            {
                "models": [
                    {
                        "key": "model-b",
                        "max_context_length": 131072,
                    },
                ],
            },
            {
                "data": [
                    {
                        "id": "model-b",
                        "context_length": 32768,
                    },
                ],
            },
        ])

        result = await app_module.fetch_runtime_model_status(
            client,
            base_url="http://runtime.test",
            model_uid="model-b",
        )

        self.assertEqual(result["context_window"], 32768)
        self.assertEqual(
            client.urls,
            [
                "http://runtime.test/api/v1/models",
                "http://runtime.test/api/v0/models",
                "http://runtime.test/v1/models",
            ],
        )

if __name__ == "__main__":
    unittest.main()
