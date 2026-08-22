import json
import re


ANONYMOUS_MODE_QUERY_PARAM = "anonymous_mode"
ANONYMOUS_MODE_TRUE_VALUES = {
    "1",
    "true",
    "yes",
    "on",
}

RESTRICTED_WRITE_ERROR = "restricted_write"
RESTRICTED_WRITE_REASON = "restricted write"
RESTRICTED_WRITE_FOLLOWUP_MESSAGE = (
    "Creating, saving, or changing persistent data is prohibited in this mode. "
    "Continue without creating, saving, updating, deleting, overwriting, or "
    "otherwise changing persistent data."
)

_ALWAYS_RESTRICTED_RUNTIME_ACTIONS = {
    "UPDATE_L4_FACTS",
    "SAVE_DELAYED_MEMORY",
}

_ASSET_WRITE_ACTIONS = {
    "create_asset_file",
    "append_asset_file",
    "create_wildcard_file",
    "append_wildcard_file",
    "create_wildcard_library",
    "generate_prompt_batch",
}

_ASSET_WRITE_PREFIXES = (
    "create_",
    "append_",
    "write_",
    "save_",
    "update_",
    "delete_",
    "remove_",
    "restore_",
    "overwrite_",
    "rename_",
    "move_",
)


def websocket_requests_anonymous_mode(websocket) -> bool:
    try:
        raw_value = websocket.query_params.get(
            ANONYMOUS_MODE_QUERY_PARAM,
            "",
        )
    except Exception:
        raw_value = ""

    return str(raw_value or "").strip().casefold() in ANONYMOUS_MODE_TRUE_VALUES


def configure_runtime_anonymous_mode(
    context,
    enabled: bool,
) -> None:
    enabled = bool(enabled)
    context.runtime_anonymous_mode = enabled
    context.runtime_persistent_writes_restricted = enabled

    # Delayed Memory is still hydrated/read from the global file store, but
    # anonymous sessions must never persist load counters, pruning, or reports.
    context.delayed_memory_file_store_enabled = not enabled


def persistent_writes_restricted(context) -> bool:
    return bool(
        getattr(
            context,
            "runtime_persistent_writes_restricted",
            False,
        )
    )


def _parse_asset_action_name(payload) -> str:
    if isinstance(payload, dict):
        return str(payload.get("action", "") or "").strip().casefold()

    text = str(payload or "").strip()
    if not text:
        return ""

    try:
        parsed = json.loads(text)
    except (TypeError, ValueError, json.JSONDecodeError):
        parsed = None

    if isinstance(parsed, dict):
        return str(parsed.get("action", "") or "").strip().casefold()

    match = re.search(
        r'["\']?action["\']?\s*[:=]\s*["\']([^"\']+)["\']',
        text,
        re.IGNORECASE,
    )
    return str(match.group(1) if match else "").strip().casefold()


def asset_action_writes_persistent_data(payload) -> bool:
    action_name = _parse_asset_action_name(payload)

    if not action_name:
        return False

    if action_name in _ASSET_WRITE_ACTIONS:
        return True

    return action_name.startswith(_ASSET_WRITE_PREFIXES)


def runtime_action_write_is_restricted(
    context,
    action_name: str,
    payload=None,
) -> bool:
    if not persistent_writes_restricted(context):
        return False

    normalized_name = str(action_name or "").strip().upper()

    if normalized_name in _ALWAYS_RESTRICTED_RUNTIME_ACTIONS:
        return True

    if normalized_name == "ASSET_ACTION":
        return asset_action_writes_persistent_data(payload)

    return False


def build_restricted_write_event(
    action_name: str,
    *,
    include_followup: bool = True,
) -> dict:
    normalized_name = str(action_name or "ACTION").strip().upper() or "ACTION"
    event = {
        "status": "failed",
        "error": RESTRICTED_WRITE_ERROR,
        "failure_reason": RESTRICTED_WRITE_REASON,
        "title": f"{normalized_name}: failed: {RESTRICTED_WRITE_REASON}",
    }
    if include_followup:
        event["failure_followup_message"] = (
            RESTRICTED_WRITE_FOLLOWUP_MESSAGE
        )
    return event
