from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from rules.runtime import (
    PROPOSAL_RULES,
    RUNTIME_ACTIONS_RULES,
    SKILL_ROUTING_RULES,
)


CONTRACTS_DIR = Path(__file__).resolve().parent
CONTRACT_VERSION = 1


ACTION_CONFIG_KEYS = (
    ("WEB_SEARCH", "CAN_WEB_SEARCH"),
    ("SAVE_SESSION", "CAN_SAVE_SESSION"),
    ("LIST_SKILLS", "CAN_USE_ASSETS"),
    ("HIDE_SKILLS", "CAN_USE_ASSETS"),
    ("CLEAN_TOOL_RESULTS", "CAN_CLEAN_TOOL_RESULTS"),
    ("IDLE", "CAN_IDLE"),
    ("APPEND_SKILL", "CAN_USE_ASSETS"),
    ("REMOVE_SKILL", "CAN_USE_ASSETS"),
    ("ASSET_ACTION", "CAN_USE_ASSETS"),
    ("CREATE_TODO_LIST", "CAN_RUNTIME_TODO"),
    ("RESOLVE_TODO", "CAN_RUNTIME_TODO"),
    ("CHECK_TODO", "CAN_RUNTIME_TODO"),
    ("SAVE_DELAYED_MEMORY_CONTENT", "CAN_SAVE_DELAYED_MEMORY"),
    ("LIST_DELAYED_MEMORY", "CAN_SAVE_DELAYED_MEMORY"),
    ("APPEND_DELAYED_MEMORY", "CAN_SAVE_DELAYED_MEMORY"),
    ("REMOVE_DELAYED_MEMORY", "CAN_SAVE_DELAYED_MEMORY"),
    ("CREATE_ACTIVE_MEMORY", "CAN_SAVE_ACTIVE_MEMORY"),
    ("RESOLVE_ACTIVE_MEMORY", "CAN_SAVE_ACTIVE_MEMORY"),
)


ACTIVE_MEMORY_ENTRY_RE = re.compile(
    r"^\s*-?\s*active_memory(?:_\d+)?\s*:",
    re.IGNORECASE | re.MULTILINE,
)


def _normalize_action_name(action_name: str) -> str:
    normalized = str(action_name or "").strip().upper()

    if normalized.startswith("CAN_"):
        normalized = normalized[4:]

    aliases = {
        "SAVE_DELAYED_MEMORY": "SAVE_DELAYED_MEMORY_CONTENT",
        "SAVE_ACTIVE_MEMORY": "CREATE_ACTIVE_MEMORY",
        "USE_ASSETS": "ASSET_ACTION",
        "TODO_LIST": "CREATE_TODO_LIST",
        "INTERNAL_ACTION_TODO_LIST": "CREATE_TODO_LIST",
        "INTERNAL_ACTION_CREATE_TODO_LIST": "CREATE_TODO_LIST",
    }

    return aliases.get(normalized, normalized)


def _as_list(value) -> list:
    if isinstance(value, list):
        return value

    if isinstance(value, str):
        return [value]

    return []


def _load_contract_file(path: Path) -> tuple[str, dict[str, Any]] | None:
    with path.open("r", encoding="utf-8") as contract_file:
        data = json.load(contract_file)

    if not isinstance(data, dict) or not data:
        return None

    if "runtime_action" in data:
        name = str(data.get("name") or path.stem).strip()
        contract = data
    else:
        name, contract = next(iter(data.items()))

    if not isinstance(contract, dict):
        return None

    normalized = {
        **contract,
        "name": str(contract.get("name") or name).strip() or path.stem,
    }

    return normalized["name"], normalized


@lru_cache(maxsize=1)
def get_action_contracts() -> dict[str, dict[str, Any]]:
    contracts: dict[str, dict[str, Any]] = {}

    for path in sorted(CONTRACTS_DIR.glob("*.json")):
        if path.name == "behavior_contract.json":
            continue

        loaded = _load_contract_file(path)
        if loaded is None:
            continue

        name, contract = loaded
        contracts[name] = contract

    return contracts


def get_behavior_contract() -> dict[str, Any]:
    return {
        "version": CONTRACT_VERSION,
        "action_guards": get_action_contracts(),
    }


def get_action_contract(name: str) -> dict[str, Any]:
    contract = get_action_contracts().get(str(name or "").strip(), {})
    return contract if isinstance(contract, dict) else {}


def get_action_contract_for_runtime_action(
    runtime_action: str,
) -> tuple[str, dict[str, Any]]:
    normalized_action = _normalize_action_name(runtime_action)

    if not normalized_action:
        return "", {}

    for name, contract in get_action_contracts().items():
        contract_action = _normalize_action_name(
            str(contract.get("runtime_action", "") or "")
        )

        if contract_action == normalized_action:
            return name, contract

    return "", {}


def get_action_contract_name_for_runtime_action(runtime_action: str) -> str:
    name, _ = get_action_contract_for_runtime_action(runtime_action)
    return name


def get_runtime_action_name(name_or_runtime_action: str) -> str:
    normalized = _normalize_action_name(name_or_runtime_action)

    if not normalized:
        return ""

    for contract in get_action_contracts().values():
        action = _normalize_action_name(contract.get("runtime_action", ""))
        if action == normalized:
            return action

    contract = get_action_contract(str(name_or_runtime_action or "").strip())
    action = _normalize_action_name(contract.get("runtime_action", ""))
    return action


def get_contract_strings(name: str, key: str) -> tuple[str, ...]:
    return tuple(
        value
        for value in _as_list(get_action_contract(name).get(key))
        if isinstance(value, str)
    )


def get_contract_effect(name: str, key: str, default=None):
    effects = get_action_contract(name).get("effects", {})
    if not isinstance(effects, dict):
        return default

    return effects.get(key, default)


def contract_emits_followup(name: str) -> bool:
    return bool(get_contract_effect(name, "emit_followup", True))


def runtime_action_emits_followup(runtime_action: str) -> bool:
    name, contract = get_action_contract_for_runtime_action(runtime_action)
    if not name or not contract:
        return True

    effects = contract.get("effects", {})
    if not isinstance(effects, dict):
        return True

    return bool(effects.get("emit_followup", True))


def get_enabled_runtime_actions(runtime_actions=None) -> tuple[str, ...]:
    enabled_actions = []
    action_flags = runtime_actions or {}

    for action_name, config_key in ACTION_CONFIG_KEYS:
        if bool(action_flags.get(config_key, False)):
            enabled_actions.append(action_name)

    return tuple(enabled_actions)


def normalize_runtime_action_names(enabled_actions=None) -> tuple[str, ...]:
    known_actions = {
        _normalize_action_name(contract.get("runtime_action", ""))
        for contract in get_action_contracts().values()
    }
    known_actions.discard("")

    if enabled_actions is None:
        return tuple(sorted(known_actions))

    if isinstance(enabled_actions, dict):
        candidates = (
            action_name
            for action_name, is_enabled in enabled_actions.items()
            if is_enabled
        )
    else:
        candidates = enabled_actions

    actions = []

    for action_name in candidates:
        normalized_name = _normalize_action_name(action_name)
        normalized_names = [normalized_name]

        if normalized_name == "CREATE_ACTIVE_MEMORY":
            normalized_names.append("RESOLVE_ACTIVE_MEMORY")

        if normalized_name == "SAVE_DELAYED_MEMORY_CONTENT":
            normalized_names.extend((
                "LIST_DELAYED_MEMORY",
                "APPEND_DELAYED_MEMORY",
                "REMOVE_DELAYED_MEMORY",
            ))

        if normalized_name == "ASSET_ACTION":
            normalized_names.extend((
                "LIST_SKILLS",
                "HIDE_SKILLS",
                "APPEND_SKILL",
                "REMOVE_SKILL",
            ))

        for normalized_name in normalized_names:
            if normalized_name in known_actions and normalized_name not in actions:
                actions.append(normalized_name)

    return tuple(actions)


def get_runtime_action_private_marker(runtime_action: str) -> str:
    _, contract = get_action_contract_for_runtime_action(runtime_action)
    return str(contract.get("private_marker", "") or "").strip()


def get_runtime_action_marker_prefixes(runtime_action: str) -> tuple[str, ...]:
    markers: list[str] = []
    marker = get_runtime_action_private_marker(runtime_action)

    if marker:
        markers.append(marker)

    for regexp in get_runtime_action_regexps(runtime_action):
        if regexp not in markers:
            markers.append(regexp)

    return tuple(markers)


def get_runtime_action_rules(runtime_action: str) -> tuple[str, ...]:
    _, contract = get_action_contract_for_runtime_action(runtime_action)
    return tuple(
        rule
        for rule in _as_list(contract.get("rules"))
        if isinstance(rule, str)
    )


def get_runtime_action_regexps(runtime_action: str) -> tuple[str, ...]:
    _, contract = get_action_contract_for_runtime_action(runtime_action)
    return tuple(
        pattern
        for pattern in _as_list(contract.get("regexp"))
        if isinstance(pattern, str) and pattern
    )


def get_runtime_action_failure_followup_message(
    runtime_action: str,
) -> tuple[str, ...]:
    _, contract = get_action_contract_for_runtime_action(runtime_action)
    return tuple(
        message
        for message in _as_list(contract.get("failure_followup_message"))
        if isinstance(message, str) and message.strip()
    )


def get_close_tag_runtime_actions() -> tuple[str, ...]:
    actions = []

    for contract in get_action_contracts().values():
        if not bool(contract.get("close_tag", False)):
            continue

        action = _normalize_action_name(contract.get("runtime_action", ""))
        if action:
            actions.append(action)

    return tuple(actions)


def get_stream_validator_excluded_markers() -> tuple[str, ...]:
    markers = []

    for contract in get_action_contracts().values():
        marker = str(contract.get("private_marker", "") or "").strip()
        if marker:
            markers.append(marker)

        if bool(contract.get("close_tag", False)) and marker.startswith("<"):
            marker_name = marker.lstrip("<").split(":", 1)[0].split(">", 1)[0]
            marker_name = marker_name.strip()
            if marker_name:
                markers.append(f"</{marker_name}>")

    return tuple(markers)


def get_internal_actions_with_payload() -> tuple[str, ...]:
    markers = []

    for contract in get_action_contracts().values():
        marker = str(contract.get("private_marker", "") or "").strip()
        if ":" in marker:
            markers.append(marker)

    return tuple(markers)


def get_no_follow_up_internal_actions() -> tuple[str, ...]:
    markers = []

    for contract in get_action_contracts().values():
        if bool(contract.get("effects", {}).get("emit_followup", True)):
            continue

        marker = str(contract.get("private_marker", "") or "").strip()
        if marker:
            markers.append(marker)

    return tuple(markers)


def get_enabled_action_start_markers(enabled_actions=None) -> tuple[str, ...]:
    enabled_action_names = normalize_runtime_action_names(enabled_actions)
    markers = []

    for action_name in enabled_action_names:
        markers.extend(get_runtime_action_regexps(action_name))

    return tuple(markers)


def _action_enabled(
    enabled_actions: tuple[str, ...],
    *names: str,
) -> bool:
    normalized_names = {
        _normalize_action_name(name)
        for name in names
        if str(name or "").strip()
    }

    return any(
        _normalize_action_name(action) in normalized_names
        for action in enabled_actions
    )


def _context_has_list_skills_tool_result(context=None) -> bool:
    visible_result = getattr(context, "runtime_visible_skills_result", {})

    if (
        isinstance(visible_result, dict)
        and visible_result.get("action") == "list_skills"
    ):
        return True

    for entry in list(getattr(context, "runtime_tool_results", []) or []):
        if not isinstance(entry, dict):
            continue

        result = entry.get("result")
        if isinstance(result, dict) and result.get("action") == "list_skills":
            return True

    for result in getattr(context, "runtime_asset_results", []) or []:
        if isinstance(result, dict) and result.get("action") == "list_skills":
            return True

    return False


def _context_has_delayed_memory_reports(context=None) -> bool:
    reports = getattr(context, "delayed_memory_reports", None)
    return bool(isinstance(reports, dict) and reports)


def _context_has_active_memory(context=None) -> bool:
    memory_texts = [
        getattr(context, "runtime_memory", ""),
        getattr(context, "runtime_memory_stable", ""),
    ]
    active_records = getattr(context, "active_memory_records", None)

    if active_records:
        memory_texts.extend(str(record or "") for record in active_records)

    return any(
        ACTIVE_MEMORY_ENTRY_RE.search(str(memory_text or ""))
        for memory_text in memory_texts
    )


def build_allowed_markers(
    enabled_actions: tuple[str, ...],
    context=None,
) -> str:
    markers: list[str] = []
    has_list_skills_result = _context_has_list_skills_tool_result(context)

    for action in enabled_actions:
        action_name = _normalize_action_name(action)

        if action_name == "LIST_SKILLS" and has_list_skills_result:
            continue

        if action_name in {
            "HIDE_SKILLS",
            "APPEND_SKILL",
            "REMOVE_SKILL",
        } and not has_list_skills_result:
            continue

        marker = get_runtime_action_private_marker(action_name)
        if marker:
            markers.append(marker)

    if not markers:
        return ""

    return "\n".join(markers) + "."


def build_runtime_action_instructions(
    enabled_actions: tuple[str, ...],
    context=None,
) -> str:
    if not enabled_actions:
        return "No runtime actions are currently enabled."

    instructions: list[str] = [
        RUNTIME_ACTIONS_RULES,
        PROPOSAL_RULES,
    ]
    has_list_skills_result = _context_has_list_skills_tool_result(context)

    def append_rules(action_name: str) -> None:
        for rule in get_runtime_action_rules(action_name):
            if rule not in instructions:
                instructions.append(rule)

    for action_name in enabled_actions:
        normalized_name = _normalize_action_name(action_name)

        if normalized_name == "RESOLVE_ACTIVE_MEMORY" and not _context_has_active_memory(context):
            continue

        if normalized_name in {
            "LIST_DELAYED_MEMORY",
            "APPEND_DELAYED_MEMORY",
            "REMOVE_DELAYED_MEMORY",
        } and not _context_has_delayed_memory_reports(context):
            continue

        if normalized_name in {
            "HIDE_SKILLS",
            "APPEND_SKILL",
            "REMOVE_SKILL",
        } and not has_list_skills_result:
            continue

        append_rules(normalized_name)

    if _action_enabled(enabled_actions, "LIST_SKILLS"):
        instructions.append(SKILL_ROUTING_RULES)

    return "\n".join(instructions)


RUNTIME_ACTION_WEB_SEARCH = get_runtime_action_name("web_search")
RUNTIME_ACTION_SAVE_SESSION = get_runtime_action_name("save_session")
RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT = get_runtime_action_name(
    "save_delayed_memory"
)
RUNTIME_ACTION_LIST_DELAYED_MEMORY = get_runtime_action_name(
    "list_delayed_memory"
)
RUNTIME_ACTION_APPEND_DELAYED_MEMORY = get_runtime_action_name(
    "append_delayed_memory"
)
RUNTIME_ACTION_REMOVE_DELAYED_MEMORY = get_runtime_action_name(
    "remove_delayed_memory"
)
RUNTIME_ACTION_CREATE_ACTIVE_MEMORY = get_runtime_action_name(
    "create_active_memory"
)
RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY = get_runtime_action_name(
    "resolve_active_memory"
)
RUNTIME_ACTION_LIST_SKILLS = get_runtime_action_name("list_skills")
RUNTIME_ACTION_HIDE_SKILLS = get_runtime_action_name("hide_skills")
RUNTIME_ACTION_CLEAN_TOOL_RESULTS = get_runtime_action_name(
    "clean_tool_results"
)
RUNTIME_ACTION_APPEND_SKILL = get_runtime_action_name("append_skill")
RUNTIME_ACTION_REMOVE_SKILL = get_runtime_action_name("remove_skill")
RUNTIME_ACTION_ASSET_ACTION = get_runtime_action_name("asset_action")
RUNTIME_ACTION_CREATE_TODO_LIST = get_runtime_action_name("create_todo_list")
RUNTIME_ACTION_RESOLVE_TODO = get_runtime_action_name("resolve_todo")
RUNTIME_ACTION_CHECK_TODO = get_runtime_action_name("check_todo")
RUNTIME_ACTION_IDLE = get_runtime_action_name("idle")
