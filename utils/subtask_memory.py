"""Ownership and lifetime of child Active records in the existing memory profile."""
import json

from utils.actions.active_memory_utils import _parse_active_memory_suffix, collect_active_memory_slot_ids

OWNER = "owner_subtask_agent_id"
LABEL = "subtask_memory_label"
SHARED_MEMORY_WRITES = {"UPDATE_LT_FACTS", "SAVE_DELAYED_MEMORY"}


def owner(record):
    # Only metadata after the canonical identity is authoritative.
    import re
    identity = re.search(r"\[\s*id\s*:\s*(?:SUB-)?AM-[a-z0-9]{6}\s*\]", str(record))
    return _parse_active_memory_suffix(str(record)[identity.end():], OWNER) if identity else ""


def running_child(context):
    from utils.actions.jin_instance_actions import active_child, self_fork_phase
    return active_child(context) if self_fork_phase(context) == "child_running" else None


def contexts(context):
    app = getattr(getattr(context, "websocket", None), "app", None)
    store = getattr(getattr(app, "state", None), "websocket_runtime_contexts", {})
    return [context, *(item for item in store.values() if item is not context)]


def live_owners(context):
    from runtime.memory_profile import anonymous, root
    from utils.actions.jin_instance_actions import instance_groups
    return {
        child["subtask_agent_id"]
        for target in contexts(context)
        if anonymous(target) == anonymous(context) and root(target) == root(context)
        for group in instance_groups(target)
        if group.get("phase") == "child_running"
        for child in group.get("tasks", []) if child.get("status") == "running"
    }


def can_mutate_record(context, record):
    if getattr(context, "runtime_instance_action_barrier", False):
        return False
    child = running_child(context)
    return not child or owner(record) == child["subtask_agent_id"]


def action_denial(context, name, payload):
    if getattr(context, "runtime_instance_action_barrier", False):
        return "This instance has transitioned; wait for the next runtime tick."
    child = running_child(context)
    if not child:
        return ""
    if name in SHARED_MEMORY_WRITES:
        return "Shared memory is read-only for child instances. Return useful findings in finish_reason."
    if name in {"SAVE_ACTIVE_MEMORY", "DELETE_ACTIVE_MEMORY"}:
        from utils.brain_client_utils import find_active_memory_slot_record
        from runtime.memory_profile import refresh_profile
        refresh_profile(context)
        if name == "SAVE_ACTIVE_MEMORY":
            try:
                data = json.loads(payload)
            except (ValueError, TypeError):
                data = {}
            identity = data.get("id", "") if isinstance(data, dict) else ""
        else:
            identity = str(payload).strip()
        if identity and not can_mutate_record(context, find_active_memory_slot_record(context, identity)):
            return "Child instances may change only their own temporary Active Memory."
    return ""


def discard_orphan_tool_results(context):
    from utils.tool_results import remove_runtime_tool_results
    owners = live_owners(context)
    remove_runtime_tool_results(context, lambda entry: bool(
        isinstance(entry, dict)
        and ((entry.get(OWNER) and entry[OWNER] not in owners)
             or (str(entry.get("tool_id", "")).startswith("SUB_T") and not entry.get(OWNER)))
    ))


def strip_records_and_results(context, removed, child_id="", known_ids=()):
    from utils.tool_results import remove_runtime_tool_results
    ids = collect_active_memory_slot_ids(*removed) | set(known_ids)
    if not ids and not child_id:
        return
    context.active_memory_records = [
        row for row in getattr(context, "active_memory_records", [])
        if not (collect_active_memory_slot_ids(row) & ids)
        and not (child_id and owner(row) == child_id)
    ]
    for attr in ("runtime_memory", "runtime_memory_stable"):
        text = str(getattr(context, attr, "") or "")
        setattr(context, attr, "\n".join(
            line for line in text.splitlines()
            if not (collect_active_memory_slot_ids(line) & ids)
        ))

    def matches(entry):
        if child_id and isinstance(entry, dict) and entry.get(OWNER) == child_id:
            return True
        result = entry.get("result", {}) if isinstance(entry, dict) else {}
        if not isinstance(result, dict) or result.get("action") not in {
            "save_active_memory", "update_active_memory", "delete_active_memory"
        }:
            return False
        return result.get("id") in ids or bool(collect_active_memory_slot_ids(result.get("record", "")) & ids)

    remove_runtime_tool_results(context, matches)
    context.runtime_failure_followup_entries = [
        entry for entry in getattr(context, "runtime_failure_followup_entries", []) if not matches(entry)
    ]
    context.runtime_active_memory_records_dirty = True


def cleanup_child_memory(context, child_id):
    from runtime.memory_profile import refresh_profile, commit_active, anonymous, root
    refresh_profile(context)
    records = list(getattr(context, "active_memory_records", []) or [])
    removed = [row for row in records if owner(row) == child_id]
    group = getattr(context, "runtime_jin_instance_group", {}) or {}
    known_ids = {
        identity for task in group.get("tasks", [])
        if task.get("subtask_agent_id") == child_id
        for identity in task.get("active_memory_ids", [])
    }
    # Commit before changing live projections or declaring the task complete.
    if removed:
        commit_active(context, [row for row in records if owner(row) != child_id])
    for target in contexts(context):
        if anonymous(target) == anonymous(context) and root(target) == root(context):
            strip_records_and_results(target, removed, child_id, known_ids)
