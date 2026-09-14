from __future__ import annotations

import uuid
from typing import Any
from urllib.parse import quote

import httpx

from config_loader import get_env_override


POSTING_BOARD_BASE_URL = "https://getpostingboard.dev"
POSTING_BOARD_PROTOCOL = "getpostingboard/1"
POSTING_BOARD_API_KEY_ENV = "GETPOSTINGBOARD_API_KEY"
POSTING_BOARD_TIMEOUT_SECONDS = 30.0


def _clean_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.items()
        if item is not None and item != ""
    }


def _safe_response_body(response: httpx.Response):
    try:
        return response.json()
    except ValueError:
        return response.text


def _base_headers(api_key: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Agent-Protocol": POSTING_BOARD_PROTOCOL,
        "Authorization": f"Bearer {api_key}",
        "User-Agent": "JIN-Core/1.0",
    }


def _public_request_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() != "authorization"
    }


def _error_detail(body, fallback: str) -> str:
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "").strip()
            code = str(error.get("code") or "").strip()
            if message and code:
                return f"{code}: {message}"
            return message or code or fallback
        if error:
            return str(error)
    return fallback


async def execute_posting_board_request(
    payload: dict[str, Any],
    *,
    idempotency_key: str = "",
) -> dict[str, Any]:
    action = str(payload.get("action") or "").strip().casefold()
    override = get_env_override(POSTING_BOARD_API_KEY_ENV)
    api_key = str(override or "").strip()

    if not api_key:
        return {
            "ok": False,
            "runtime_action_name": "POSTING_BOARD",
            "action": action or "unknown",
            "error": "missing_api_key",
            "detail": f"{POSTING_BOARD_API_KEY_ENV} is not set in the JIN process environment",
            "request": {},
            "response": None,
        }

    method = "GET"
    path = ""
    params: dict[str, Any] = {}
    body: dict[str, Any] | None = None
    headers = _base_headers(api_key)

    if action == "feed":
        path = "/v1/feed"
        cursor = str(payload.get("cursor") or "").strip()
        if cursor:
            params = _clean_dict({
                "cursor": cursor,
                "limit": payload.get("limit"),
            })
        else:
            params = _clean_dict({
                "limit": payload.get("limit"),
            })

    elif action == "inbox":
        path = "/v1/inbox"
        if payload.get("after") not in (None, "") and payload.get("before") not in (None, ""):
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "inbox accepts either after or before, not both",
                "request": {},
                "response": None,
            }
        params = _clean_dict({
            "limit": payload.get("limit"),
            "after": payload.get("after"),
            "before": payload.get("before"),
        })

    elif action == "read":
        source = str(payload.get("source") or "").strip().casefold()
        root_id = str(payload.get("root_id") or "").strip()
        if source not in {"named", "b", "meatproxy"} or not root_id:
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "read requires source (named|b|meatproxy) and root_id",
                "request": {},
                "response": None,
            }
        path = f"/v1/discussions/{source}/{quote(root_id, safe='')}"
        params = _clean_dict({
            "article_revision_id": payload.get("article_revision_id"),
        })

    elif action == "search":
        query = str(payload.get("query") or "").strip()
        if not query:
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "search requires query",
                "request": {},
                "response": None,
            }
        path = "/v1/search"
        params = _clean_dict({
            "q": query,
            "limit": payload.get("limit"),
            "topic": payload.get("topic"),
        })

    elif action == "post":
        title = str(payload.get("title") or "").strip()
        body_text = str(payload.get("body") or "").strip()
        topic = str(payload.get("topic") or "general").strip() or "general"
        if not title or not body_text:
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "post requires title and body",
                "request": {},
                "response": None,
            }
        method = "POST"
        path = "/v1/posts"
        body = {
            "topic": topic,
            "title": title,
            "body": body_text,
        }
        headers["Content-Type"] = "application/json"
        headers["Idempotency-Key"] = str(idempotency_key or uuid.uuid4())

    elif action == "reply":
        thread_id = str(payload.get("thread_id") or "").strip()
        body_text = str(payload.get("body") or "").strip()
        if not thread_id or not body_text:
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "reply requires thread_id and body",
                "request": {},
                "response": None,
            }
        method = "POST"
        path = f"/v1/posts/{quote(thread_id, safe='')}/replies"
        body = {"body": body_text}
        headers["Content-Type"] = "application/json"
        headers["Idempotency-Key"] = str(idempotency_key or uuid.uuid4())

    elif action == "ack":
        try:
            through = int(payload.get("through"))
        except (TypeError, ValueError):
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "ack requires a non-negative integer through checkpoint",
                "request": {},
                "response": None,
            }
        if through < 0:
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "ack requires a non-negative integer through checkpoint",
                "request": {},
                "response": None,
            }
        method = "POST"
        path = "/v1/inbox/ack"
        body = {"through": through}
        headers["Content-Type"] = "application/json"

    elif action == "delete":
        post_id = str(payload.get("post_id") or "").strip()
        if not post_id:
            return {
                "ok": False,
                "runtime_action_name": "POSTING_BOARD",
                "action": action,
                "error": "invalid_payload",
                "detail": "delete requires post_id",
                "request": {},
                "response": None,
            }
        method = "DELETE"
        path = f"/v1/posts/{quote(post_id, safe='')}"

    else:
        return {
            "ok": False,
            "runtime_action_name": "POSTING_BOARD",
            "action": action or "unknown",
            "error": "unknown_posting_board_action",
            "detail": "supported actions: feed, inbox, read, search, post, reply, ack, delete",
            "request": {},
            "response": None,
        }

    request_preview = {
        "method": method,
        "path": path,
        "headers": _public_request_headers(headers),
    }
    if params:
        request_preview["query"] = params
    if body is not None:
        request_preview["body"] = body

    try:
        async with httpx.AsyncClient(
            base_url=POSTING_BOARD_BASE_URL,
            timeout=POSTING_BOARD_TIMEOUT_SECONDS,
            follow_redirects=False,
        ) as client:
            response = await client.request(
                method,
                path,
                headers=headers,
                params=params or None,
                json=body,
            )
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "runtime_action_name": "POSTING_BOARD",
            "action": action,
            "error": "network_error",
            "detail": str(exc),
            "request": request_preview,
            "response": None,
        }

    response_body = _safe_response_body(response)
    ok = 200 <= response.status_code < 300
    result = {
        "ok": ok,
        "runtime_action_name": "POSTING_BOARD",
        "action": action,
        "status_code": response.status_code,
        "request": request_preview,
        "response": response_body,
    }

    retry_after = str(response.headers.get("Retry-After") or "").strip()
    if retry_after:
        result["retry_after"] = retry_after

    if not ok:
        result["error"] = "posting_board_http_error"
        result["detail"] = _error_detail(
            response_body,
            f"HTTP {response.status_code}",
        )

    return result
