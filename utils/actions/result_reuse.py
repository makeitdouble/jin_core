"""Move an existing tool result to a new action attempt without executing it."""
import json
from copy import deepcopy

from contracts.rules_assembler import get_runtime_action_display_name, runtime_action_has_close_tag
from utils.actions.common_action_utils import build_runtime_action_id
from utils.runtime_action_abort import mark_runtime_action_completed
from utils.tool_results import (
    RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES,
    TOOL_RESULT_KIND_RUNTIME_ACTION,
    get_runtime_tool_results, record_runtime_tool_result,
)
from utils.skills_asset_utils import normalize_skill_name


def canonical_payload(value):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (TypeError, ValueError):
            return value.strip()
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _materialize_loaded_skill_result(context, action):
    """Turn an already-loaded skill into a reusable tool-result source.

    Loaded skills predate the generic tool-result cache, so historically a
    repeated LOAD_SKILL in a later model message was silently dropped before
    it could become an action/follow-up. Materialize the currently loaded skill
    only when a repeat actually happens; the generic reuse path can then move
    the full result into the new TOOL_RESULT and leave the previous block as an
    absorbed identity record.
    """
    if action.name != "LOAD_SKILL":
        return None

    requested = normalize_skill_name(action.payload)
    if not requested:
        return None

    loaded_skill = next((
        skill
        for skill in (getattr(context, "runtime_loaded_skills", []) or [])
        if isinstance(skill, dict)
        and normalize_skill_name(skill.get("name", "")) == requested
    ), None)
    if loaded_skill is None:
        return None

    result = {
        "ok": True,
        "action": "load_skill",
        "requested": requested,
        "skill": deepcopy(loaded_skill),
    }
    record_runtime_tool_result(
        context,
        TOOL_RESULT_KIND_RUNTIME_ACTION,
        result,
    )
    source = get_runtime_tool_results(context)[-1]
    source.setdefault("action_name", "LOAD_SKILL")
    source.setdefault("action_payload", action.payload)

    # If the original load predates tool-result tracking/restoration, bind the
    # synthetic source to the latest matching action event when one is present.
    if not source.get("runtime_message_id"):
        for event in reversed(getattr(context, "runtime_action_events", []) or []):
            if not isinstance(event, dict):
                continue
            if str(event.get("name") or "").strip().casefold() != "load_skill":
                continue
            if normalize_skill_name(event.get("payload", "")) != requested:
                continue
            source["runtime_message_id"] = str(event.get("runtime_message_id") or "")
            source["runtime_turn_id"] = str(event.get("runtime_turn_id") or "")
            event.setdefault("tool_id", source["tool_id"])
            break

    return source


def find_reusable_result(context, action):
    # Cleanup operates on the store itself; its failures are never a cache.
    # Bare ATTACH_FILE_CONTENT is stateful: each call advances to the next
    # unread project-file window, so an identical payload is not equivalent
    # to the previous execution and must never be satisfied from reuse cache.
    if action.name in {"CLEAN_TOOL_RESULTS", "ATTACH_FILE_CONTENT", "CALL_MCP"}:
        return None

    # Posting Board reads/checkpoints are live server state, not reusable
    # results. Reusing inbox/feed/read/search would return stale data after an
    # intervening ack/write, while reusing ack/delete would suppress the state
    # transition itself. Only successful content-creating writes are safe to
    # move across model messages: their idempotency protection is intentional.
    if action.name == "POSTING_BOARD":
        from utils.posting_board_display import posting_board_action_name

        if posting_board_action_name(action.payload) not in {"post", "reply"}:
            return None
    for entry in reversed(get_runtime_tool_results(context)):
        if not isinstance(entry, dict) or not entry.get("tool_id") or entry.get("absorbed_by"):
            continue
        result = entry.get("result")
        # Failed operations remain retryable; do not turn a cached failure into success.
        if result in (None, "") or (isinstance(result, dict) and result.get("ok") is False):
            continue
        name = entry.get("action_name")
        if not name and isinstance(result, dict):
            name = result.get("runtime_action_name") or result.get("action")
        if str(name or "").upper() != action.name or "action_payload" not in entry:
            continue
        if action.name == "POSTING_BOARD":
            from utils.actions.posting_board_actions import (
                canonical_posting_board_payload,
            )

            source_payload = canonical_posting_board_payload(entry["action_payload"])
            action_payload = canonical_posting_board_payload(action.payload)
        elif action.name in {"LOAD_SKILL", "UNLOAD_SKILL"}:
            source_payload = normalize_skill_name(entry["action_payload"])
            action_payload = normalize_skill_name(action.payload)
        else:
            source_payload = canonical_payload(entry["action_payload"])
            action_payload = canonical_payload(action.payload)
        if source_payload == action_payload:
            return entry

    return _materialize_loaded_skill_result(context, action)


async def reuse_action_result(context, action, *, runtime_message_id,
                              action_display_ids, with_action_context):
    source = find_reusable_result(context, action)
    if source is None:
        return False
    if runtime_message_id and source.get("runtime_message_id") == runtime_message_id:
        # A second parser pass over this same message is not a new model tick.
        return False
    action_id = action_display_ids.get(id(action), "")
    generated_action_id = not bool(action_id)
    if not action_id:
        sequence = int(getattr(context, "runtime_reused_action_sequence", 0) or 0) + 1
        context.runtime_reused_action_sequence = sequence
        action_id = build_runtime_action_id(action.name, sequence) + "_reused"
        action_display_ids[id(action)] = action_id
    event = with_action_context({
        "name": action.name.lower(), "id": action_id, "status": "completed",
        "payload": action.payload, "reused_from": source["tool_id"],
    })
    context.runtime_action_events.append(event)
    result = deepcopy(source["result"])
    if isinstance(result, dict):
        result["id"] = action_id
        for key in ("runtime_turn_id", "runtime_message_id"):
            if key in event:
                result[key] = event[key]
    record_runtime_tool_result(context, source["kind"], result, result_id=action_id)
    target = get_runtime_tool_results(context)[-1]
    target.update(action_name=action.name, action_payload=action.payload,
                  reused_from=source["tool_id"], runtime_message_id=runtime_message_id)
    event["tool_id"] = target["tool_id"]
    # Leave an identity-only record, never a second full response in the prompt.
    source["action_name"] = action.name
    source["absorbed_by"] = target["tool_id"]
    for attribute in RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES:
        values = getattr(context, attribute, None)
        if isinstance(values, list):
            values[:] = [deepcopy(result) if value == source["result"] else value
                         for value in values]
    source["result"] = {}
    detail = f'Result reused from {source["tool_id"]}; now stored in {target["tool_id"]}.'
    text = get_runtime_action_display_name(action.name)
    if action.name == "POSTING_BOARD":
        from utils.actions.posting_board_actions import build_posting_board_display_text
        text = build_posting_board_display_text(action.payload)
    payload = with_action_context({
        "type": "runtime_action", "action": action.name.lower(), "id": action_id,
        "status": "completed", "text": text, "detail": detail,
        "payload": action.payload, "tool_id": target["tool_id"],
        "reused_from": target["reused_from"],
        "display_name": get_runtime_action_display_name(action.name),
        "close_tag": runtime_action_has_close_tag(action.name),
    })
    if action.name == "POSTING_BOARD":
        payload["posting_board_result"] = result
    elif source["kind"] == "asset":
        payload["asset_result"] = result
    emit = getattr(getattr(context, "emitter", None), "emit", None)
    if emit is not None:
        await emit(payload)
    log = getattr(getattr(context, "logger", None), "log_runtime", None)
    if log is not None:
        await log(f"[RUNTIME ACTION] {action.name.lower()} completed: {detail}")
    mark_runtime_action_completed(context, action=action.name, action_id=action_id)
    if generated_action_id:
        # Stream-start events for actions without dedicated display ids are
        # tracked as idless active markers. Retire that lifecycle record too.
        mark_runtime_action_completed(context, action=action.name)
    return True
