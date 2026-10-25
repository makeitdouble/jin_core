import json
import re

from .action_payload_utils import (
    _build_internal_action_payload,
)


_COMPACT_PROJECT_ACTION_FIELDS = {
    "project_tree": frozenset({"attachment", "path", "depth", "offset", "limit"}),
    "project_search": frozenset({"attachment", "path", "query", "offset", "limit"}),
}

_COMPACT_PROJECT_INTEGER_FIELDS = frozenset({
    "depth",
    "offset",
    "limit",
})


def build_compact_project_asset_action_payload(
    query: str,
) -> str | None:
    """Convert the narrow one-line project compatibility form to JSON.

    Accepted examples::

        project_search | . | query: build_context
        project_tree | . | depth: 1 | offset: 0 | limit: 100

    This intentionally does *not* become a generic ASSET_ACTION mini-language.
    Only the read-only project_tree/project_search actions and their existing
    fields are accepted; every other ASSET_ACTION keeps using the canonical
    JSON block form.
    """

    value = str(query or "").strip()
    if not value or "|" not in value:
        return None

    parts = [part.strip() for part in value.split("|")]
    if not parts or any(not part for part in parts):
        return None

    action = parts[0].casefold()
    allowed_fields = _COMPACT_PROJECT_ACTION_FIELDS.get(action)
    if allowed_fields is None:
        return None

    payload: dict[str, object] = {"action": action}
    positional_path_used = False

    for index, part in enumerate(parts[1:]):
        if ":" not in part:
            # The compact form permits exactly one positional value: the
            # project-relative path immediately after the action name.
            if index != 0 or positional_path_used or "path" in payload:
                return None
            payload["path"] = part
            positional_path_used = True
            continue

        key, raw_value = part.split(":", 1)
        key = key.strip().casefold()
        raw_value = raw_value.strip()

        if (
            key not in allowed_fields
            or key in payload
            or not raw_value
        ):
            return None

        if key in _COMPACT_PROJECT_INTEGER_FIELDS:
            if re.fullmatch(r"[0-9]+", raw_value) is None:
                return None
            payload[key] = int(raw_value)
        else:
            payload[key] = raw_value

    payload.setdefault("path", ".")

    if action == "project_search" and not str(payload.get("query") or "").strip():
        return None

    return json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def build_asset_action_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    return _build_internal_action_payload(
        query,
        placeholder_payloads,
    )


def project_listing_request_key(payload_text: str, result: dict) -> str:
    """Identify the *same request*, not just the same project tool name.

    In particular, different project_tree pages and project_search queries
    must keep their own results. Use the resolved folder/path from the result
    so display-name, ID and default-argument spellings compare equally.
    """
    if not isinstance(result, dict):
        return ""
    from utils.python_skill_asset_utils import _parse_payload

    payload = _parse_payload(payload_text)
    action = str(payload.get("action") or result.get("action") or "").strip().casefold()
    if action not in {"project_tree", "project_search"} or action != result.get("action"):
        return ""
    if result.get("ok") is False:
        return ""

    def number(field, default):
        # Old checkpoint records may lack the original action_payload. Page
        # metadata still records the exact offset and limit of that request.
        value = payload.get(field)
        if value is None and field in {"offset", "limit"}:
            match = re.search(rf"\b{field}\s+(\d+)", str(result.get("page") or ""))
            if match:
                value = match.group(1)
        if value is None and field == "depth":
            value = result.get("depth")
        try:
            return int(default if value is None else value)
        except (TypeError, ValueError):
            return default

    request = {
        "action": action,
        "attachment": str(result.get("attachment") or payload.get("attachment") or "").strip(),
        "path": str(result.get("path") or payload.get("path") or ".").replace("\\", "/").strip(),
        "offset": number("offset", 0),
        "limit": number("limit", 100),
    }
    if action == "project_tree":
        request["depth"] = number("depth", 1)
    else:
        request["query"] = str(payload.get("query") or result.get("query") or "").casefold()

    return json.dumps(request, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
