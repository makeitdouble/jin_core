from __future__ import annotations

import base64
import json
import mimetypes
from pathlib import Path

from contracts.rules_assembler import (
    RUNTIME_ACTION_CALL_MCP,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.actions import build_runtime_action_id
from utils.attached_files_store import (
    get_pinned_file_ids,
    hydrate_attachment_ids,
    store_uploaded_file,
)
from utils.mcp_client import call_mcp_tool
from utils.mcp_skill_utils import get_skill_mcp_config, resolve_loaded_mcp_skill
from utils.skills_asset_utils import normalize_skill_name
from utils.tool_results import TOOL_RESULT_KIND_RUNTIME_ACTION, record_runtime_tool_result


MAX_MCP_IMAGE_BYTES = 20 * 1024 * 1024


def _parse_call_mcp_payload(payload) -> tuple[dict | None, str, str]:
    if isinstance(payload, dict):
        data = payload
    else:
        raw = str(payload or "").strip()
        if not raw:
            return None, "invalid_json", "CALL_MCP payload is empty"
        try:
            # MCP code arguments are often multiline. Be tolerant of literal
            # control characters inside JSON strings instead of rejecting an
            # otherwise usable tool call.
            data = json.loads(raw, strict=False)
        except json.JSONDecodeError as exc:
            return (
                None,
                "invalid_json",
                f"CALL_MCP JSON parse failed at line {exc.lineno}, column {exc.colno}: {exc.msg}",
            )
        except (TypeError, ValueError) as exc:
            return None, "invalid_json", f"CALL_MCP JSON parse failed: {exc}"

    if not isinstance(data, dict):
        return None, "invalid_payload", "CALL_MCP payload must be a JSON object"

    skill = normalize_skill_name(data.get("skill", ""))
    if not skill:
        return None, "invalid_payload", "CALL_MCP field 'skill' must be a non-empty string"

    tool = str(data.get("tool") or "").strip()
    if not tool:
        return None, "invalid_payload", "CALL_MCP field 'tool' must be a non-empty string"

    arguments = data.get("arguments", {})
    if not isinstance(arguments, dict):
        return None, "invalid_payload", "CALL_MCP field 'arguments' must be a JSON object"

    return {
        "skill": skill,
        "tool": tool,
        "arguments": arguments,
    }, "", ""


def parse_call_mcp_payload(payload) -> dict | None:
    parsed, _error, _detail = _parse_call_mcp_payload(payload)
    return parsed


def canonical_call_mcp_payload(payload) -> str:
    parsed = parse_call_mcp_payload(payload)
    if not parsed:
        return str(payload or "").strip()
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def build_call_mcp_display_text(payload, *, failed: bool = False) -> str:
    parsed = parse_call_mcp_payload(payload)
    display_name = get_runtime_action_display_name(RUNTIME_ACTION_CALL_MCP)
    if not parsed:
        text = display_name
    else:
        text = f"{display_name}: {parsed['skill']} / {parsed['tool']}"
    return f"{text} (failed)" if failed else text


def _image_extension(mime_type: str) -> str:
    extension = mimetypes.guess_extension(str(mime_type or "").split(";", 1)[0].strip()) or ".png"
    if extension == ".jpe":
        extension = ".jpg"
    return extension


def _persist_mcp_images(context, result: dict) -> list[dict]:
    content = result.get("content")
    if not isinstance(content, list):
        return []

    stored = []
    skill_name = normalize_skill_name(result.get("skill", "")) or "mcp"
    tool_name = str(result.get("tool") or "tool").strip() or "tool"

    for index, block in enumerate(content, start=1):
        if not isinstance(block, dict) or str(block.get("type") or "").casefold() != "image":
            continue

        data = block.get("data")
        mime_type = str(block.get("mimeType") or block.get("mime_type") or "image/png").strip() or "image/png"
        if not isinstance(data, str) or not data:
            continue

        try:
            payload = base64.b64decode(data, validate=True)
        except (ValueError, TypeError):
            continue
        if not payload or len(payload) > MAX_MCP_IMAGE_BYTES:
            continue

        safe_tool = "".join(char if char.isalnum() or char in "-_" else "_" for char in tool_name)[:80]
        name = f"mcp_{skill_name}_{safe_tool}_{index}{_image_extension(mime_type)}"
        record, _created, error = store_uploaded_file(
            name=name,
            content=payload,
            mime_type=mime_type,
            pin=True,
        )
        if error or not record:
            continue

        file_id = str(record.get("id") or "").strip()
        hydrated = hydrate_attachment_ids([file_id])
        attachment = hydrated[0] if hydrated else dict(record)
        turn_attachments = getattr(context, "runtime_turn_attachments", None)
        if not isinstance(turn_attachments, list):
            turn_attachments = []
            context.runtime_turn_attachments = turn_attachments
        if file_id and not any(str(item.get("id") or "") == file_id for item in turn_attachments if isinstance(item, dict)):
            turn_attachments.append(attachment)

        sequence_attachments = getattr(context, "runtime_current_sequence_attachments", None)
        if isinstance(sequence_attachments, list) and file_id and not any(
            str(item.get("id") or "") == file_id
            for item in sequence_attachments
            if isinstance(item, dict)
        ):
            sequence_attachments.append(attachment)

        block.pop("data", None)
        block["mime_type"] = mime_type
        block["file_id"] = file_id
        block["name"] = str(record.get("name") or name)
        stored.append({
            "id": file_id,
            "name": str(record.get("name") or name),
            "mime_type": mime_type,
            "type": mime_type,
            "kind": "image",
            "url": str(record.get("url") or ""),
        })

    if stored:
        result["attachments"] = stored
    return stored


def _update_runtime_event(context, action_call, *, result: dict, action_id: str) -> None:
    payload = str(getattr(action_call, "payload", "") or "").strip()
    for event in reversed(getattr(context, "runtime_action_events", []) or []):
        if not isinstance(event, dict):
            continue
        if str(event.get("name") or "").casefold() != "call_mcp":
            continue
        if payload and str(event.get("payload") or "").strip() != payload:
            continue
        if action_id and event.get("id") and str(event.get("id")) != action_id:
            continue
        event["status"] = "completed" if result.get("ok") is not False else "failed"
        if result.get("ok") is False:
            event["failure_reason"] = str(result.get("detail") or result.get("error") or "failed")
            event["error"] = str(result.get("error") or "mcp_call_failed")
        return


async def apply_mcp_actions(
    context,
    actions,
    *,
    action_display_ids,
    log_runtime,
    with_action_context,
):
    results = []
    emitter = getattr(context, "emitter", None)
    emit = getattr(emitter, "emit", None)

    for action_call in actions or ():
        parsed, parse_error, parse_detail = _parse_call_mcp_payload(action_call.payload)
        action_id = str(action_display_ids.get(id(action_call), "") or "").strip()
        if not action_id:
            sequence = int(getattr(context, "runtime_mcp_action_sequence", 0) or 0) + 1
            context.runtime_mcp_action_sequence = sequence
            action_id = build_runtime_action_id(RUNTIME_ACTION_CALL_MCP, sequence)
            action_display_ids[id(action_call)] = action_id

        request_text = build_call_mcp_display_text(action_call.payload)
        if emit is not None:
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "call_mcp",
                "id": action_id,
                "status": "running",
                "display_name": get_runtime_action_display_name(RUNTIME_ACTION_CALL_MCP),
                "text": request_text,
                "payload": str(action_call.payload or "").strip(),
                "mcp_request": parsed,
                "close_tag": runtime_action_has_close_tag(RUNTIME_ACTION_CALL_MCP),
            }))

        if not parsed:
            result = {
                "ok": False,
                "runtime_action_name": "CALL_MCP",
                "error": parse_error or "invalid_payload",
                "detail": parse_detail or "Invalid CALL_MCP payload",
            }
        else:
            skill = resolve_loaded_mcp_skill(context, parsed["skill"])
            if skill is None:
                result = {
                    "ok": False,
                    "runtime_action_name": "CALL_MCP",
                    **parsed,
                    "error": "mcp_skill_not_loaded",
                    "detail": f"MCP skill is not loaded: {parsed['skill']}",
                }
            else:
                config = get_skill_mcp_config(skill)
                if not isinstance(config, dict) or config.get("_invalid"):
                    result = {
                        "ok": False,
                        "runtime_action_name": "CALL_MCP",
                        **parsed,
                        "error": str((config or {}).get("error") or "invalid_mcp_skill"),
                        "detail": str((config or {}).get("detail") or "Loaded skill has no valid MCP_SERVER config"),
                    }
                else:
                    try:
                        result = await call_mcp_tool(
                            context,
                            skill,
                            parsed["tool"],
                            parsed["arguments"],
                        )
                        result["runtime_action_name"] = "CALL_MCP"
                        if result.get("ok") is False and not result.get("detail"):
                            result["detail"] = "MCP tool returned is_error=true"
                        stored_images = _persist_mcp_images(context, result)
                        if stored_images:
                            # MCP images use the same canonical pinned-file state
                            # and snapshot event as user-attached files. This keeps
                            # the Console and composer chips in sync immediately.
                            from utils.actions.attachment_actions import (
                                _emit_snapshot,
                                apply_attachment_context_ids,
                            )

                            apply_attachment_context_ids(
                                context,
                                get_pinned_file_ids(),
                            )
                            await _emit_snapshot(context)
                    except Exception as exc:
                        result = {
                            "ok": False,
                            "runtime_action_name": "CALL_MCP",
                            **parsed,
                            "error": "mcp_call_failed",
                            "detail": str(exc),
                        }

        result["display_text"] = build_call_mcp_display_text(
            action_call.payload,
            failed=result.get("ok") is False,
        )
        result["id"] = action_id
        record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result)
        _update_runtime_event(context, action_call, result=result, action_id=action_id)

        if log_runtime is not None:
            status = "success" if result.get("ok") is not False else "failed"
            await log_runtime(f"[RUNTIME ACTION] {request_text} {status}")

        if emit is not None:
            await emit(with_action_context({
                "type": "runtime_action",
                "action": "call_mcp",
                "id": action_id,
                "status": "completed" if result.get("ok") is not False else "failed",
                "display_name": get_runtime_action_display_name(RUNTIME_ACTION_CALL_MCP),
                "text": result["display_text"],
                "payload": str(action_call.payload or "").strip(),
                "detail": str(result.get("detail") or "").strip(),
                "mcp_result": result,
                "close_tag": runtime_action_has_close_tag(RUNTIME_ACTION_CALL_MCP),
            }))

        results.append(result)

    return results
