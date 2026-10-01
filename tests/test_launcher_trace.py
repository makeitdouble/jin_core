from types import SimpleNamespace

import utils.launcher_trace as trace


def test_launcher_trace_hides_static_status_and_model_catalog_noise():
    assert trace._inbound_visible("GET", "/static/css/base.css") is False
    assert trace._inbound_visible("GET", "/api/status") is False
    assert trace._inbound_visible("POST", "/api/runtime-model/switch") is True
    assert trace._outbound_visible("GET", "/v1/models") is False
    assert trace._outbound_visible("POST", "/v1/chat/completions") is True


def test_launcher_trace_labels_brain_when_service_is_fallback(monkeypatch):
    monkeypatch.setattr(
        trace,
        "settings",
        SimpleNamespace(
            BRAIN_API_BASE="http://127.0.0.1:1234",
            SERVICE_API_BASE="http://127.0.0.1:1234",
            SERVICE_CONFIGURED=False,
        ),
    )
    assert trace._target_for_url("http://127.0.0.1:1234/v1/chat/completions") == "BRAIN"


def test_launcher_trace_labels_dedicated_service(monkeypatch):
    monkeypatch.setattr(
        trace,
        "settings",
        SimpleNamespace(
            BRAIN_API_BASE="http://127.0.0.1:1234",
            SERVICE_API_BASE="http://192.168.1.25:1234",
            SERVICE_CONFIGURED=True,
        ),
    )
    assert trace._target_for_url("http://192.168.1.25:1234/v1/chat/completions") == "SERVICE"
