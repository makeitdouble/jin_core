from __future__ import annotations

import json
import os
import re
from copy import deepcopy
from typing import Any

from utils.skills_asset_utils import normalize_skill_name


MCP_CONFIG_TAG_NAMES = (
    "MCP_SERVER",
    "JIN_MCP",
)


def _extract_tag_payload(content: str, tag_name: str) -> str:
    pattern = re.compile(
        rf"<{re.escape(tag_name)}\s*>([\s\S]*?)</{re.escape(tag_name)}\s*>",
        re.IGNORECASE,
    )
    match = pattern.search(str(content or ""))
    return str(match.group(1) or "").strip() if match else ""


def extract_mcp_config_payload(content: str) -> str:
    for tag_name in MCP_CONFIG_TAG_NAMES:
        payload = _extract_tag_payload(content, tag_name)
        if payload:
            return payload
    return ""


def parse_mcp_server_config(content: str) -> dict[str, Any] | None:
    payload = extract_mcp_config_payload(content)
    if not payload:
        return None

    try:
        raw = json.loads(payload)
    except (TypeError, ValueError):
        return {
            "_invalid": True,
            "error": "invalid_mcp_config_json",
            "detail": "MCP_SERVER must contain one JSON object",
        }

    if not isinstance(raw, dict):
        return {
            "_invalid": True,
            "error": "invalid_mcp_config",
            "detail": "MCP_SERVER must contain one JSON object",
        }

    transport = str(raw.get("transport") or "stdio").strip().casefold()
    aliases = {
        "http": "streamable_http",
        "streamable-http": "streamable_http",
        "streamable_http": "streamable_http",
        "stdio": "stdio",
        "sse": "sse",
    }
    transport = aliases.get(transport, transport)

    config: dict[str, Any] = {
        "transport": transport,
    }

    if transport == "stdio":
        command = str(raw.get("command") or "").strip()
        if not command:
            return {
                "_invalid": True,
                "error": "missing_mcp_command",
                "detail": "stdio MCP_SERVER requires command",
            }

        args = raw.get("args", [])
        if not isinstance(args, list) or any(not isinstance(value, str) for value in args):
            return {
                "_invalid": True,
                "error": "invalid_mcp_args",
                "detail": "stdio MCP_SERVER args must be a JSON string array",
            }

        config.update({
            "command": command,
            "args": list(args),
        })

        cwd = str(raw.get("cwd") or "").strip()
        if cwd:
            config["cwd"] = cwd

        static_env = raw.get("env", {})
        if static_env:
            if not isinstance(static_env, dict) or any(
                not isinstance(key, str) or not isinstance(value, (str, int, float, bool))
                for key, value in static_env.items()
            ):
                return {
                    "_invalid": True,
                    "error": "invalid_mcp_env",
                    "detail": "stdio MCP_SERVER env must be a JSON object of scalar values",
                }
            config["env"] = {
                str(key): str(value)
                for key, value in static_env.items()
            }

        env_from_host = raw.get("env_from_host", {})
        if env_from_host:
            if isinstance(env_from_host, list):
                if any(not isinstance(value, str) for value in env_from_host):
                    return {
                        "_invalid": True,
                        "error": "invalid_mcp_env_from_host",
                        "detail": "env_from_host list entries must be strings",
                    }
                env_from_host = {
                    value: value
                    for value in env_from_host
                }
            if not isinstance(env_from_host, dict) or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in env_from_host.items()
            ):
                return {
                    "_invalid": True,
                    "error": "invalid_mcp_env_from_host",
                    "detail": "env_from_host must be a JSON object or string array",
                }
            config["env_from_host"] = dict(env_from_host)

    elif transport in {"streamable_http", "sse"}:
        url = str(raw.get("url") or "").strip()
        if not url:
            return {
                "_invalid": True,
                "error": "missing_mcp_url",
                "detail": f"{transport} MCP_SERVER requires url",
            }
        if not url.lower().startswith(("http://", "https://")):
            return {
                "_invalid": True,
                "error": "invalid_mcp_url",
                "detail": "MCP_SERVER url must use http:// or https://",
            }
        config["url"] = url
    else:
        return {
            "_invalid": True,
            "error": "unsupported_mcp_transport",
            "detail": f"Unsupported MCP transport: {transport or 'unknown'}",
        }

    timeout = raw.get("read_timeout_seconds")
    if timeout is not None:
        try:
            timeout_value = float(timeout)
        except (TypeError, ValueError):
            return {
                "_invalid": True,
                "error": "invalid_mcp_timeout",
                "detail": "read_timeout_seconds must be a positive number",
            }
        if timeout_value <= 0:
            return {
                "_invalid": True,
                "error": "invalid_mcp_timeout",
                "detail": "read_timeout_seconds must be a positive number",
            }
        config["read_timeout_seconds"] = timeout_value

    return config


def get_skill_mcp_config(skill: dict | None) -> dict[str, Any] | None:
    if not isinstance(skill, dict):
        return None
    content = str(skill.get("content") or "")
    return parse_mcp_server_config(content)


def is_mcp_skill(skill: dict | None) -> bool:
    config = get_skill_mcp_config(skill)
    return bool(config is not None and not config.get("_invalid"))


def get_loaded_mcp_skills(context=None) -> list[dict]:
    return [
        skill
        for skill in (getattr(context, "runtime_loaded_skills", []) or [])
        if isinstance(skill, dict) and is_mcp_skill(skill)
    ]


def has_loaded_mcp_skill(context=None) -> bool:
    return bool(get_loaded_mcp_skills(context))


def resolve_loaded_mcp_skill(context, skill_name: str) -> dict | None:
    requested = normalize_skill_name(skill_name)
    if not requested:
        return None

    for skill in getattr(context, "runtime_loaded_skills", []) or []:
        if not isinstance(skill, dict):
            continue
        if normalize_skill_name(skill.get("name", "")) == requested:
            return skill
    return None


def build_stdio_environment(config: dict[str, Any]) -> dict[str, str] | None:
    values = {
        str(key): str(value)
        for key, value in (config.get("env") or {}).items()
    }
    for child_name, host_name in (config.get("env_from_host") or {}).items():
        host_value = os.environ.get(str(host_name))
        if host_value is not None:
            values[str(child_name)] = host_value
    return values or None


def public_mcp_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(config, dict):
        return None

    result = {
        key: deepcopy(value)
        for key, value in config.items()
        if key not in {"env", "_invalid"}
    }
    if config.get("env"):
        result["env_keys"] = sorted(str(key) for key in config["env"])
    if config.get("env_from_host"):
        result["env_from_host"] = deepcopy(config["env_from_host"])
    return result


def append_mcp_runtime_catalog(skill: dict, discovery: dict) -> dict:
    """Return an in-memory skill copy with live MCP discovery appended.

    The asset on disk remains untouched. The generated block gives Brain the exact
    live tool names/schemas while JIN_SKILL.md remains the human-authored usage
    guide and connection declaration.
    """
    enriched = deepcopy(skill)
    content = str(enriched.get("content") or "").rstrip()
    skill_name = normalize_skill_name(enriched.get("name", "")) or "mcp"

    lines = [
        "<MCP_RUNTIME>",
        f"skill: {skill_name}",
    ]

    if discovery.get("ok") is False:
        lines.extend((
            "status: unavailable",
            f"error: {str(discovery.get('error') or 'mcp_discovery_failed')}",
            f"detail: {str(discovery.get('detail') or '').strip()}",
        ))
    else:
        server = discovery.get("server") if isinstance(discovery.get("server"), dict) else {}
        lines.extend((
            "status: connected",
            f"protocol_version: {str(server.get('protocol_version') or '').strip()}",
            f"server_name: {str(server.get('server_name') or '').strip()}",
            f"server_version: {str(server.get('server_version') or '').strip()}",
            "tools:",
        ))
        tools = discovery.get("tools") if isinstance(discovery.get("tools"), list) else []
        if not tools:
            lines.append("- none")
        for tool in tools[:200]:
            if not isinstance(tool, dict):
                continue
            name = str(tool.get("name") or "").strip()
            if not name:
                continue
            title = str(tool.get("title") or "").strip()
            description = str(tool.get("description") or "").strip().replace("\n", " ")
            schema = tool.get("input_schema") if isinstance(tool.get("input_schema"), dict) else {}
            lines.append(f"- name: {name}")
            if title:
                lines.append(f"  title: {title}")
            if description:
                lines.append(f"  description: {description}")
            lines.append(
                "  input_schema: "
                + json.dumps(schema, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            )

    lines.append("</MCP_RUNTIME>")
    runtime_block = "\n".join(lines)
    enriched["content"] = f"{content}\n\n{runtime_block}".strip()
    enriched["mcp_runtime"] = deepcopy(discovery)
    return enriched
