from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import json
import time
from uuid import uuid4

import config
from contracts.rules_assembler import (
    RUNTIME_ACTION_CREATE_JIN_INSTANCES,
    RUNTIME_ACTION_FINISH_SUBTASK,
    get_runtime_action_display_name,
    runtime_action_has_close_tag,
)
from utils.actions.common_action_utils import build_runtime_action_id
from utils.chat_log import append_chat_runtime_event
from utils.runtime_action_abort import mark_runtime_action_completed
from utils.tool_results import TOOL_RESULT_KIND_RUNTIME_ACTION, record_runtime_tool_result


CHILD_TOOL_RESULTS_INSTRUCTION = (
    "All TOOL_RESULTs created by you belong to your temporary instance and use "
    "SUB_T1, SUB_T2, ... IDs starting from SUB_T1 for each child. "
    "They are forcibly removed on FINISH_SUBTASK or interruption, including failures. "
    "Inherited parent TOOL_RESULTs use T* IDs and are read-only: do not clean them. "
    "CLEAN_TOOL_RESULTS accepts your SUB_T* IDs; an empty payload clears only your results. "
    "Return essential findings in finish_reason before finishing."
)


def _json_objects(payload) -> list[dict]:
    text = str(payload or "").strip()
    if not text:
        raise ValueError("CREATE_JIN_INSTANCES requires at least one assignment")
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = []
        for line_number, line in enumerate(text.splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON assignment on line {line_number}: {exc.msg}") from exc
            decoded.append(item)
    if isinstance(decoded, dict):
        decoded = [decoded]
    if not isinstance(decoded, list) or not decoded:
        raise ValueError("CREATE_JIN_INSTANCES payload must contain JSON objects")
    if not all(isinstance(item, dict) for item in decoded):
        raise ValueError("Every CREATE_JIN_INSTANCES assignment must be a JSON object")
    return decoded


def parse_instance_assignments(payload) -> list[dict]:
    items = _json_objects(payload)
    maximum = max(1, int(getattr(config, "JIN_MAX_INSTANCES", 32) or 32))
    if len(items) > maximum:
        raise ValueError(f"CREATE_JIN_INSTANCES accepts at most {maximum} assignments")
    assignments = []
    for expected_id, item in enumerate(items, start=1):
        supplied_id = item.get("id")
        if type(supplied_id) is not int or supplied_id != expected_id:
            raise ValueError("Assignment IDs must be consecutive integers starting at 1")
        if not isinstance(item.get("conditions"), str):
            raise ValueError(f"Assignment {expected_id} requires non-empty string conditions")
        conditions = item["conditions"].strip()
        if not conditions:
            raise ValueError(f"Assignment {expected_id} requires non-empty conditions")
        assignments.append({"ordinal": expected_id, "conditions": conditions})
    return assignments


def _parse_object(payload, action_name: str) -> dict:
    try:
        value = json.loads(str(payload or "").strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{action_name} requires one valid JSON object") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{action_name} requires one valid JSON object")
    return value


def _current_group(context) -> dict:
    group = getattr(context, "runtime_jin_instance_group", {})
    return group if isinstance(group, dict) else {}


def instance_groups(context) -> list[dict]:
    """Live execution frames, oldest first; the current group has one owner."""
    return [*(getattr(context, "runtime_jin_instance_stack", []) or []), _current_group(context)]


def _group_child(group) -> dict | None:
    index = group.get("active_index")
    tasks = group.get("tasks")
    if not isinstance(index, int) or not isinstance(tasks, list) or not 0 <= index < len(tasks):
        return None
    task = tasks[index]
    return task if isinstance(task, dict) else None


def active_child(context) -> dict | None:
    return _group_child(_current_group(context))


def self_fork_phase(context) -> str:
    return str(_current_group(context).get("phase") or "")


def _find_event(context, action_name: str, payload: str) -> dict | None:
    normalized = action_name.lower()
    for event in reversed(getattr(context, "runtime_action_events", []) or []):
        if not isinstance(event, dict) or event.get("name") != normalized:
            continue
        if str(event.get("payload") or "").strip() != str(payload or "").strip():
            continue
        if event.get("status") not in {"completed", "failed", "interrupted", "aborted"}:
            return event
    return None


async def _finish_event(batch, action, *, ok: bool, result: dict, text: str) -> None:
    event = _find_event(batch.context, action.name, action.payload)
    action_id = str(
        batch.action_display_ids.get(id(action), "")
        or (event or {}).get("id", "")
        or build_runtime_action_id(action.name, len(getattr(batch.context, "runtime_action_events", []) or []))
    )
    if event is not None:
        event.update(status="completed" if ok else "failed", result=deepcopy(result))
        if ok and action.name == RUNTIME_ACTION_FINISH_SUBTASK:
            event["payload"] = json.dumps(
                {
                    key: result.get(key, "")
                    for key in (
                        "subtask_agent_id",
                        "session_id",
                        "original_conditions",
                        "finish_reason",
                    )
                },
                ensure_ascii=False,
                separators=(",", ":"),
            )
        if not ok:
            event["failure_reason"] = text
        event["id"] = action_id
    payload = batch.with_action_context_for(action)({
        "type": "runtime_action",
        "action": action.name.lower(),
        "id": action_id,
        "status": "completed" if ok else "failed",
        "display_name": get_runtime_action_display_name(action.name),
        "close_tag": runtime_action_has_close_tag(action.name),
        "text": text,
        "payload": result,
        "detail": "" if ok else text,
    })
    emit = getattr(getattr(batch.context, "emitter", None), "emit", None)
    if emit is not None:
        await emit(payload)
    append_chat_runtime_event(batch.context, event="runtime_action", payload=payload)
    mark_runtime_action_completed(batch.context, action=action.name, action_id=action_id)


async def apply_create_jin_instances(batch, action, _state) -> int:
    context = batch.context
    previous_group = _current_group(context)
    parent = active_child(context) if self_fork_phase(context) == "child_running" else None
    if self_fork_phase(context) in {"child_pending", "parent_pending"}:
        error = "The registered instance group must advance before another CREATE"
        result = {"action": action.name.lower(), "ok": False, "error": "group_pending", "detail": error}
        record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result)
        await _finish_event(batch, action, ok=False, result=result, text=error)
        return 1
    try:
        assignments = parse_instance_assignments(action.payload)
    except ValueError as exc:
        result = {"action": action.name.lower(), "ok": False, "error": "invalid_payload", "detail": str(exc)}
        record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result)
        await _finish_event(batch, action, ok=False, result=result, text=str(exc))
        return 1

    group_id = f"jin_group_{uuid4().hex}"
    if not getattr(context, "runtime_jin_root_instance_id", ""):
        context.runtime_jin_root_instance_id = f"jin_{uuid4().hex}"
    parent_instance_id = parent["subtask_agent_id"] if parent else context.runtime_jin_root_instance_id
    parent_session_id = str(parent["session_id"] if parent else getattr(context, "session_id", "") or "")
    tasks = []
    for assignment in assignments:
        ordinal = assignment["ordinal"]
        tasks.append({
            **assignment,
            "subtask_agent_id": f"sub_jin_{ordinal}_{uuid4().hex[:12]}",
            "session_id": f"{group_id}_session_{ordinal}_{uuid4().hex[:8]}",
            "status": "pending",
            "finish_reason": "",
        })
    for task in tasks:
        task["instance_id"] = task["subtask_agent_id"]
        task["parent_instance_id"] = parent_instance_id
    group = {
        "group_id": group_id,
        "parent_instance_id": parent_instance_id,
        "parent_session_id": parent_session_id,
        "depth": len(getattr(context, "runtime_jin_instance_stack", []) or []) + (1 if parent else 0),
        "parent_user_message": str(getattr(context, "runtime_turn_user_message", "") or ""),
        "created_at": time.time(),
        "phase": "child_pending",
        "active_index": 0,
        "tasks": tasks,
    }
    result = {
        "action": action.name.lower(),
        "ok": True,
        "group_id": group_id,
        "instance_count": len(tasks),
        "instances": [
            {key: task[key] for key in ("ordinal", "subtask_agent_id", "session_id", "conditions")}
            for task in tasks
        ],
    }
    # CREATE is owned by its caller, before changing the active execution frame.
    record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result, result_id=group_id)
    if parent is not None:
        stack = list(getattr(context, "runtime_jin_instance_stack", []) or [])
        stack.append(previous_group)
        context.runtime_jin_instance_stack = stack
    context.runtime_jin_instance_group = group
    context.runtime_instance_action_barrier = True
    await _finish_event(
        batch, action, ok=True, result=result,
        text=f"Created {len(tasks)} sequential JIN instances",
    )
    return 1


async def apply_finish_subtask(batch, action, _state) -> int:
    context = batch.context
    group = _current_group(context)
    task = active_child(context)
    try:
        supplied = _parse_object(action.payload, RUNTIME_ACTION_FINISH_SUBTASK)
    except ValueError as exc:
        supplied = {}
        validation_error = str(exc)
    else:
        validation_error = ""
    if task is None or group.get("phase") != "child_running":
        validation_error = validation_error or "FINISH_SUBTASK is valid only for the active child JIN"
    if task is not None and not validation_error:
        if str(supplied.get("subtask_agent_id") or "") != task["subtask_agent_id"]:
            validation_error = "FINISH_SUBTASK subtask_agent_id does not match the active child"
        elif str(supplied.get("session_id") or "") != task["session_id"]:
            validation_error = "FINISH_SUBTASK session_id does not match the active child"
    finish_reason = supplied.get("finish_reason")
    finish_reason = finish_reason.strip() if isinstance(finish_reason, str) else ""
    if not validation_error and not finish_reason:
        validation_error = "FINISH_SUBTASK requires a non-empty finish_reason"
    authoritative = {
        "subtask_agent_id": str((task or {}).get("subtask_agent_id") or ""),
        "session_id": str((task or {}).get("session_id") or ""),
        "original_conditions": str((task or {}).get("conditions") or ""),
        "finish_reason": finish_reason,
    }
    if validation_error:
        result = {"action": action.name.lower(), "ok": False, "error": "invalid_finish", "detail": validation_error, **authoritative}
        record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result)
        await _finish_event(batch, action, ok=False, result=result, text=validation_error)
        return 1

    from utils.subtask_memory import cleanup_child_memory
    try:
        cleanup_child_memory(context, task["subtask_agent_id"])
    except (OSError, ValueError) as exc:
        result = {"action": action.name.lower(), "ok": False, "error": "subtask_memory_cleanup_failed", "detail": str(exc), **authoritative}
        record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result)
        await _finish_event(batch, action, ok=False, result=result, text=str(exc))
        return 1
    from clients.brain_client import emit_active_memory_records_update_if_dirty
    await emit_active_memory_records_update_if_dirty(context)
    context.runtime_instance_action_barrier = True
    task.update(status="completed", finish_reason=finish_reason, completed_at=time.time())
    result = {"action": action.name.lower(), "ok": True, **authoritative}
    next_index = int(group["active_index"]) + 1
    if next_index < len(group["tasks"]):
        group["active_index"] = next_index
        group["phase"] = "child_pending"
    else:
        group["active_index"] = None
        group["phase"] = "parent_pending"
    # Completion report belongs to the parent, not to the finished child's
    # ephemeral tool-result collection.
    if getattr(context, "runtime_jin_instance_stack", []):
        # Publish in the immediate parent's namespace when its frame resumes.
        # Until then, ordered task reports feed the next sibling's instruction.
        group.setdefault("completion_results", []).append(result)
    else:
        record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result, result_id=task["subtask_agent_id"])
    await _finish_event(
        batch, action, ok=True, result=result,
        text=f"JIN instance {task['ordinal']} finished: {finish_reason}",
    )
    return 1


def build_child_instruction(context) -> str:
    group = _current_group(context)
    task = active_child(context)
    if task is None:
        return ""
    completed = [item for item in group.get("tasks", []) if item.get("status") == "completed"]
    reports = "\n".join(
        f"- JIN #{item['ordinal']} ({item['subtask_agent_id']}): {item['finish_reason']}"
        for item in completed
    ) or "- none"
    return (
        "<JIN_SUBTASK_INSTANCE>\n"
        "You are JIN, a child instance of yourself created to execute one part of the original user intention.\n"
        f"Your ordinal number: {task['ordinal']}\n"
        f"Your authoritative subtask_agent_id: {task['subtask_agent_id']}\n"
        f"Your authoritative session_id: {task['session_id']}\n"
        f"Original user intention: {group.get('parent_user_message', '')}\n"
        f"Your assigned conditions: {task['conditions']}\n"
        "Use the context, memories, skills, attachments, tools, and tool results provided in this tick. "
        "Work autonomously through ordinary runtime actions and their ordinary follow-ups. You may create nested JIN instances with CREATE_JIN_INSTANCES.\n"
        "On your first tick, execute a runtime action if work is needed, or emit FINISH_SUBTASK if it is already done. "
        "Plain narration without an action immediately stops this child; nothing runs in the background.\n"
        "Shared Active Memory, L-T facts and Delayed Memory are read-only. "
        "Use SAVE_ACTIVE_MEMORY freely on any follow-up tick for your own temporary intentions, conclusions, "
        "conditions and working state. You may update or delete only your own Active records. "
        "They persist across all your follow-ups and runtime deletes them automatically when you finish or stop. "
        "Do not call DELETE_ACTIVE_MEMORY just to clean up before FINISH_SUBTASK. "
        "Your record IDs have the SUB-AM-xxxxxx prefix; use those exact IDs for updates and deletion. "
        "Ownership is assigned by runtime and cannot be supplied or changed. "
        "Return all findings that should survive in finish_reason; the parent decides what to retain.\n"
        f"{CHILD_TOOL_RESULTS_INSTRUCTION}\n"
        "When and only when the assigned subtask is complete, emit FINISH_SUBTASK using the authoritative IDs above, "
        "the original assigned conditions, and a precise finish_reason.\n"
        "Completed predecessor reports:\n"
        f"{reports}\n"
        "</JIN_SUBTASK_INSTANCE>"
    )


def build_parent_return_instruction(context) -> str:
    group = _current_group(context)
    lines = []
    for task in group.get("tasks", []):
        lines.append(
            f"- JIN #{task.get('ordinal')} | id={task.get('subtask_agent_id')} | "
            f"conditions={task.get('conditions')} | status={task.get('status')} | "
            f"finish_reason={task.get('finish_reason')}"
        )
    return (
        "<JIN_INSTANCES_RETURN_TO_PARENT>\n"
        "You are the immediate parent of this group. All its child instances have reached terminal states. "
        "Continue the original user intention using the ordered reports and the actual current tool results. "
        "A child report is not proof that a claimed file exists; verify real outputs when needed. "
        "Continue your own assignment. If you are a child yourself, use your own FINISH_SUBTASK only when your assignment is complete; otherwise you may answer normally. You may create another group if necessary.\n"
        + "\n".join(lines)
        + "\n</JIN_INSTANCES_RETURN_TO_PARENT>"
    )


def mark_child_started(context) -> None:
    context.runtime_instance_action_barrier = False
    group = _current_group(context)
    task = active_child(context)
    if task is not None:
        if "parent_reasoning_state" not in group:
            group["parent_reasoning_state"] = {
                name: deepcopy(getattr(context, name, default))
                for name, default in INSTANCE_REASONING_DEFAULTS.items()
            }
        # Suspend the parent's mutable tool projections as well as reasoning.
        # Relative inheritance of SUB results is introduced in part 3; until
        # then keep ancestor scratch results out of a descendant's SUB namespace.
        if getattr(context, "runtime_jin_instance_stack", []) and "parent_tool_state" not in group:
            group["parent_tool_state"] = {
                name: deepcopy(getattr(context, name, default))
                for name, default in INSTANCE_TOOL_DEFAULTS.items()
            }
            from utils.tool_results import remove_runtime_tool_results
            remove_runtime_tool_results(context, lambda entry: bool(entry.get("owner_subtask_agent_id")))
        for name, default in INSTANCE_REASONING_DEFAULTS.items():
            setattr(context, name, deepcopy(default))
        if "parent_jin_messages" not in group:
            group["parent_jin_messages"] = deepcopy(
                getattr(context, "runtime_current_sequence_jin_messages", [])
            )
        context.runtime_current_sequence_jin_messages = deepcopy(group["parent_jin_messages"])
        task["status"] = "running"
        task["started_at"] = time.time()
        group["phase"] = "child_running"


INSTANCE_TOOL_DEFAULTS = {
    "runtime_tool_results": [],
    "runtime_tool_result_created_ats": [],
    "runtime_tool_results_turn_count": 0,
    "runtime_tool_result_sequence": 0,
    "runtime_asset_results": [],
    "runtime_asset_retry_results": [],
    "runtime_asset_retry_context": [],
    "runtime_delayed_memory_results": [],
    "runtime_search_result": "",
    "runtime_search_result_id": "",
    "runtime_deep_research_result": "",
    "runtime_deep_research_result_id": "",
}


INSTANCE_REASONING_DEFAULTS = {
    "runtime_failure_followup_entries": [],
    "runtime_failure_followup_tool_ids": [],
    "runtime_followup_action_failure_pending": False,
    "runtime_action_failure_followup_messages": [],
    "runtime_turn_reasoning_content": "",
    "runtime_previous_reasoning_loop_contents": [],
    "runtime_reasoning_recovery_pending": False,
    "runtime_context_limit_recovery_pending": False,
    "runtime_context_limit_stage": "",
    "runtime_context_limit_kind": "",
    "runtime_context_limit_finish_reason": "",
}


def restore_parent_reasoning(context) -> None:
    context.runtime_instance_action_barrier = False
    group = _current_group(context)
    for name, value in group.get("parent_tool_state", {}).items():
        setattr(context, name, deepcopy(value))
    snapshot = group.get("parent_reasoning_state", {})
    for name, value in snapshot.items():
        setattr(context, name, deepcopy(value))
    group = _current_group(context)
    if "parent_jin_messages" in group:
        context.runtime_current_sequence_jin_messages = deepcopy(group["parent_jin_messages"])


def mark_parent_returned(context, expected_group: dict) -> None:
    # Detach the finished frame before the caller's return tick can act again.
    if expected_group.get("phase") == "parent_pending":
        expected_group["phase"] = "completed"
        expected_group["completed_at"] = time.time()
    stack = getattr(context, "runtime_jin_instance_stack", [])
    if _current_group(context) is expected_group and stack:
        context.runtime_jin_instance_group = stack.pop()
        for result in expected_group.pop("completion_results", []):
            record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, result,
                                       result_id=result["subtask_agent_id"])
        # Retain reports on the parent task, never a second live group owner.
        parent = active_child(context)
        if parent is not None:
            parent.setdefault("child_group_reports", []).append(_group_report(expected_group))
        expected_group.pop("parent_tool_state", None)
        expected_group.pop("parent_reasoning_state", None)
        expected_group.pop("parent_jin_messages", None)


def _group_report(group) -> dict:
    # Keep terminal diagnostics flat. Copying nested frame/report trees while
    # unwinding would reintroduce a Python recursion limit into the stack loop.
    keys = ("ordinal", "subtask_agent_id", "session_id", "parent_instance_id",
            "conditions", "status", "finish_reason", "memory_cleanup_error")
    return {"group_id": group.get("group_id", ""), "tasks": [
        {key: task[key] for key in keys if key in task}
        for task in group.get("tasks", [])
    ]}


def interrupt_instance_group(context, reason: str = "stopped") -> dict:
    """Unwind the whole suspended tree without recursing through Python calls."""
    while True:
        group = _interrupt_current_group(context, reason)
        stack = getattr(context, "runtime_jin_instance_stack", [])
        if not stack:
            return group
        context.runtime_jin_instance_group = stack.pop()
        parent = active_child(context)
        if parent is not None:
            parent.setdefault("child_group_reports", []).append(_group_report(group))
        group.pop("parent_tool_state", None)
        group.pop("parent_reasoning_state", None)
        group.pop("parent_jin_messages", None)


def _interrupt_current_group(context, reason: str = "stopped") -> dict:
    group = _current_group(context)
    if group.get("phase") not in {"child_pending", "child_running", "parent_pending"}:
        return group
    task = active_child(context)
    if task is not None and task.get("status") == "running":
        from utils.subtask_memory import cleanup_child_memory
        try:
            cleanup_child_memory(context, task["subtask_agent_id"])
        except (OSError, ValueError) as exc:
            # Stop must still cancel generation. Disk-owned bootstrap retries orphan cleanup.
            task["memory_cleanup_error"] = str(exc)
        task["status"] = "interrupted"
        task["finish_reason"] = reason
    for item in group.get("tasks", []):
        if item.get("status") == "pending":
            item["status"] = "cancelled"
            item["finish_reason"] = reason
    group["phase"] = "interrupted"
    group["active_index"] = None
    group["interrupted_at"] = time.time()
    restore_parent_reasoning(context)
    context.runtime_instance_action_barrier = True
    return group


def _timestamp(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return 0.0
    return 0.0


def recent_lt_fact_ids(context, *, now: float | None = None) -> list[str]:
    store = getattr(context, "runtime_long_term_memory_store", {})
    cutoff = (time.time() if now is None else float(now)) - 24 * 60 * 60
    return [
        str(fact.get("id", "")).strip().upper()
        for fact in (store.get("facts", []) if isinstance(store, dict) else [])
        if isinstance(fact, dict)
        and max(_timestamp(fact.get("created_at")), _timestamp(fact.get("updated_at"))) >= cutoff
    ]

