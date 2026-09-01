"""Explicit value-only edits from the memory inspector (no model action)."""

import re

from runtime.L1_memory_utils import (
    build_runtime_memory_snapshot,
    emit_runtime_memory_snapshot_refresh,
    rebuild_latest_runtime_memory_snapshot,
)
from runtime.LT_memory import (
    emit_lt_memory_update,
    ensure_runtime_lt_state,
    mark_runtime_lt_explicit_edit,
    persist_runtime_lt_file_store,
)
from runtime.LT_memory_utils import clone_lt_store
from utils.time_utils import utc_now_iso
from runtime.anonymous_mode import persistent_writes_restricted
from utils.actions.active_memory_utils import (
    collect_active_memory_slot_ids,
    is_active_memory_key,
)


def split_editable_memory_value(value):
    """Match the browser's balanced, trailing [key: value] metadata parser."""
    text = str(value or "").rstrip()
    tags = []
    while text.endswith("]"):
        depth = 0
        start = None
        for index in range(len(text) - 1, -1, -1):
            depth += (text[index] == "]") - (text[index] == "[")
            if depth == 0:
                start = index
                break
        if start is None:
            break
        match = re.fullmatch(r"\s*([\w.-]+)\s*:\s*([\s\S]*)", text[start + 1:-1])
        if match is None:
            break
        tags.insert(0, (match[1], text[start:]))
        text = text[:start].rstrip()
    return text.strip(), tags


def replace_memory_value(raw_value, value, *, active=False):
    _, tags = split_editable_memory_value(raw_value)
    suffixes = []
    for key, raw in tags:
        if active and key.casefold() == "conditions":
            raw = f"[ {key}: {value} ]"
        if active and key.casefold() == "updated_at":
            continue
        suffixes.append(raw)
    if active:
        suffixes.append(f"[ updated_at: {utc_now_iso()} ]")
    return " ".join([value, *suffixes])


async def apply_memory_value_edit(context, data, *, foreground_busy=False):
    kind = data.get("kind")
    target = data.get("target")
    value = data.get("value")
    expected = data.get("expected_value")
    result = {
        "type": "memory_value_edit_result",
        "request_id": data.get("request_id"),
        "ok": False,
    }

    def reject(error):
        return {**result, "error": error}

    if (kind not in {"frame", "active", "lt"}
            or not isinstance(target, str) or not target
            or not isinstance(value, str) or not value.strip()
            or not isinstance(expected, str) or "\x00" in value):
        return reject("invalid_value")
    # FRAME/ACTIVE records are single physical lines; preserve entered line breaks.
    value = value.strip().replace("\r\n", "\n").replace("\r", "\n")
    if kind != "lt":
        value = value.replace("\n", r"\n")
    if kind == "lt" and persistent_writes_restricted(context):
        return reject("restricted_write")
    pending = getattr(context, "runtime_memory_update_task", None)
    if kind in {"frame", "active"} and (
        foreground_busy or (pending is not None and not pending.done())
    ):
        return reject("memory_busy")

    if kind == "lt":
        store = clone_lt_store(ensure_runtime_lt_state(context))
        fact = next((item for item in store["facts"] if item["id"] == target), None)
        if fact is None:
            return reject("not_found")
        current = str(fact.get("value") or "")
        if current != expected and current != value:
            return reject("value_changed")
        if current != value:
            fact["value"] = value
            fact["updated_at"] = utc_now_iso()
            store["revision"] = int(store.get("revision") or 0) + 1
            store["updated_at"] = fact["updated_at"]
            # Publish only after the durable write succeeds.
            persist_runtime_lt_file_store(context, store)
            context.runtime_long_term_memory_store = store
            mark_runtime_lt_explicit_edit(context, [target])
        result["updated_at"] = fact.get("updated_at", "")
        await emit_lt_memory_update(context, change={"updated_ids": [target], "changed": current != value})
    else:
        snapshots = getattr(context, "runtime_memory_snapshots", []) or []
        if kind == "frame":
            if is_active_memory_key(target) or target == "user_idle":
                return reject("invalid_target")
            latest = snapshots[-1] if snapshots else {}
            # IDs survive client history reindexing and in-place snapshot refreshes.
            if not data.get("frame_id") or data["frame_id"] != latest.get("runtime_memory_id"):
                return reject("stale_frame")
            records = str(getattr(context, "runtime_memory", "") or "").splitlines()
            matches = [i for i, row in enumerate(records)
                       if ":" in row and row.split(":", 1)[0].strip().lstrip("-").strip() == target]
        else:
            records = list(getattr(context, "active_memory_records", []) or [])
            matches = [i for i, row in enumerate(records)
                       if target in collect_active_memory_slot_ids(row)]
        if len(matches) != 1:
            return reject("not_found")
        index = matches[0]
        key, raw = records[index].split(":", 1)
        current, _ = split_editable_memory_value(raw)
        if current != expected and current != value:
            return reject("value_changed")
        if current != value:
            records[index] = f"{key}: {replace_memory_value(raw, value, active=kind == 'active')}"
            if kind == "frame":
                context.runtime_memory = "\n".join(records)
                context.runtime_memory_stable = context.runtime_memory
                context.runtime_memory_updates = int(getattr(context, "runtime_memory_updates", 0) or 0) + 1
            else:
                context.active_memory_records = records
                context.runtime_active_memory_records_dirty = True
                # Keep legacy inline Active projections consistent; never touch historical snapshots.
                for attr in ("runtime_memory", "runtime_memory_stable"):
                    lines = str(getattr(context, attr, "") or "").splitlines()
                    setattr(context, attr, "\n".join(
                        records[index] if target in collect_active_memory_slot_ids(row) else row
                        for row in lines
                    ))
        if kind == "active":
            _, tags = split_editable_memory_value(records[index].split(":", 1)[1])
            result["updated_at"] = next((raw.split(":", 1)[1][:-1].strip()
                                         for name, raw in tags if name.casefold() == "updated_at"), "")
            await context.emitter.emit({
                "type": "active_memory_records_update",
                "active_memory_records": records,
            })
        snapshot = rebuild_latest_runtime_memory_snapshot(context)
        if snapshot is None:
            snapshot = build_runtime_memory_snapshot(context, getattr(context, "runtime_memory", ""))
            context.runtime_memory_snapshots = [snapshot]
            context.runtime_memory_snapshot_index = snapshot["index"]
        snapshot["runtime_memory_updates"] = getattr(context, "runtime_memory_updates", 0)
        await emit_runtime_memory_snapshot_refresh(context, snapshot)

    return {**result, "ok": True, "value": value}
