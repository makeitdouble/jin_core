"""Compact launcher-only runtime I/O tracing.

The normal application stays quiet unless ``JIN_LAUNCHER_TRACE=1`` is present.
The Windows launcher consumes these single-line records and renders a small
request console instead of exposing Uvicorn's static-file/access-log spam.
"""

from __future__ import annotations

import os
import time
from urllib.parse import urlsplit

from app_settings import settings


TRACE_ENV = "JIN_LAUNCHER_TRACE"
_TRACE_START_KEY = "jin_launcher_trace_started_at"

_QUIET_INBOUND_PREFIXES = (
    "/static/",
    "/assets/",
)
_QUIET_INBOUND_PATHS = {
    "/",
    "/favicon.ico",
    "/api/status",
}
_QUIET_OUTBOUND_GET_PATHS = {
    "/v1/models",
    "/api/v0/models",
    "/api/v1/models",
    "/props",
}


def launcher_trace_enabled() -> bool:
    value = str(os.environ.get(TRACE_ENV, "") or "").strip().casefold()
    return value in {"1", "true", "yes", "on"}


def _emit(*parts: object) -> None:
    if not launcher_trace_enabled():
        return
    timestamp = time.strftime("%H:%M:%S")
    safe = [str(part).replace("|", "/").replace("\r", " ").replace("\n", " ") for part in parts]
    print("JIN_TRACE|" + timestamp + "|" + "|".join(safe), flush=True)


def _inbound_visible(method: str, path: str) -> bool:
    if path in _QUIET_INBOUND_PATHS:
        return False
    if any(path.startswith(prefix) for prefix in _QUIET_INBOUND_PREFIXES):
        return False
    return True


def _outbound_visible(method: str, path: str) -> bool:
    if method.upper() == "GET" and path in _QUIET_OUTBOUND_GET_PATHS:
        return False
    if path == "/models/sse":
        return False
    return True


def _normalize_base(value: str) -> str:
    return str(value or "").strip().rstrip("/").casefold()


def _target_for_url(url: str) -> str:
    normalized = str(url or "").strip().casefold()
    brain = _normalize_base(settings.BRAIN_API_BASE)
    service = _normalize_base(settings.SERVICE_API_BASE)

    if settings.SERVICE_CONFIGURED and service and normalized.startswith(service):
        return "SERVICE"
    if brain and normalized.startswith(brain):
        return "BRAIN"

    try:
        host = urlsplit(url).netloc
    except Exception:
        host = ""
    return host.upper() or "EXT"


async def trace_outgoing_request(request) -> None:
    if not launcher_trace_enabled():
        return

    method = str(getattr(request, "method", "") or "").upper()
    url = str(getattr(request, "url", "") or "")
    try:
        path = request.url.path
    except Exception:
        path = "/"

    if not _outbound_visible(method, path):
        return

    request.extensions[_TRACE_START_KEY] = time.monotonic()
    _emit("OUT", ">", _target_for_url(url), method, path)


async def trace_outgoing_response(response) -> None:
    if not launcher_trace_enabled():
        return

    request = getattr(response, "request", None)
    if request is None:
        return

    method = str(getattr(request, "method", "") or "").upper()
    try:
        path = request.url.path
    except Exception:
        path = "/"

    if not _outbound_visible(method, path):
        return

    started = request.extensions.get(_TRACE_START_KEY)
    elapsed_ms = 0
    if isinstance(started, (int, float)):
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))

    _emit(
        "OUT",
        "<",
        _target_for_url(str(getattr(request, "url", "") or "")),
        int(getattr(response, "status_code", 0) or 0),
        method,
        path,
        f"{elapsed_ms}ms",
    )


async def trace_inbound_http(request, call_next):
    if not launcher_trace_enabled():
        return await call_next(request)

    method = str(request.method or "").upper()
    path = str(request.url.path or "/")
    visible = _inbound_visible(method, path)
    started = time.monotonic()

    if visible:
        _emit("IN", ">", "JIN", method, path)

    try:
        response = await call_next(request)
    except Exception:
        if visible:
            elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
            _emit("IN", "!", "JIN", "ERR", method, path, f"{elapsed_ms}ms")
        raise

    if visible:
        elapsed_ms = max(0, int((time.monotonic() - started) * 1000))
        _emit(
            "IN",
            "<",
            "JIN",
            int(getattr(response, "status_code", 0) or 0),
            method,
            path,
            f"{elapsed_ms}ms",
        )

    return response
