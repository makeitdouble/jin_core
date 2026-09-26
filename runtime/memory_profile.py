"""Disk-owned memory profiles. Browser snapshots are projections, never imports."""
import hashlib
import json
from copy import deepcopy
from pathlib import Path

MEMORY_ROOT = Path(__file__).resolve().parents[1] / "memory"
ANONYMOUS_CLOSE_GRACE_SECONDS = 2.0
ANONYMOUS_STARTUP_GRACE_SECONDS = 10.0


def enable_profile(context):
    app_state = context.websocket.app.state
    if not getattr(app_state, "memory_profiles_initialized", False):
        from runtime.frame_memory_pending import migrate_legacy_runtime_journal
        migrate_legacy_runtime_journal(root(context))
        app_state.memory_profiles_initialized = True

        # Do not erase _anon files synchronously on a backend restart: open
        # anonymous tabs reconnect through the normal WebSocket backoff. Give
        # them a short window to reclaim the shared anonymous profile; only
        # truly orphaned files are removed after that window.
        import asyncio
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            memory_root = root(context)

            def clear_startup_orphans():
                app_state.anonymous_memory_cleanup = None
                contexts = getattr(app_state, "websocket_runtime_contexts", {}).values()
                if not any(anonymous(item) for item in contexts):
                    clear_anonymous_files(memory_root)

            app_state.anonymous_memory_cleanup = loop.call_later(
                ANONYMOUS_STARTUP_GRACE_SECONDS,
                clear_startup_orphans,
            )

    cleanup = getattr(app_state, "anonymous_memory_cleanup", None)
    if anonymous(context) and cleanup is not None:
        cleanup.cancel()
        app_state.anonymous_memory_cleanup = None
    context.memory_profile_enabled = True
    context.delayed_memory_file_store_enabled = True
    context.runtime_lt_file_store_enabled = True


def enabled(context):
    return bool(getattr(context, "memory_profile_enabled", False))


def anonymous(context):
    return bool(getattr(context, "runtime_anonymous_mode", False))


def root(context):
    return Path(getattr(context, "memory_profile_root", MEMORY_ROOT))


def file_options(context, folder):
    return {"root": root(context) / folder, "anonymous": anonymous(context)}


def revision(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read_profile(context):
    from utils.active_memory_file_store import load_active_records
    from utils.delayed_memory_file_store import load_delayed_memory_reports_from_files
    from utils.long_term_facts_file_store import load_long_term_facts_store, load_pending_facts
    delayed, warnings = load_delayed_memory_reports_from_files(**file_options(context, "delayed"))
    if warnings:
        raise ValueError("; ".join(warnings))
    lt, warnings = load_long_term_facts_store(**file_options(context, "facts"))
    if warnings:
        raise ValueError("; ".join(warnings))
    return {
        "active": load_active_records(**file_options(context, "active")),
        "delayed": delayed, "lt": lt,
        "pending": load_pending_facts(**file_options(context, "facts")).get("records", []),
    }


def apply_profile(context, profile):
    context.active_memory_records = deepcopy(profile["active"])
    context.delayed_memory_reports = deepcopy(profile["delayed"])
    context.runtime_long_term_memory_store = deepcopy(profile["lt"])
    context.runtime_facts_memory_records = deepcopy(profile["pending"])
    loaded = getattr(context, "runtime_loaded_delayed_memory", {}) or {}
    context.runtime_loaded_delayed_memory = {
        key: {**profile["delayed"][key], "id": key}
        for key in loaded if key in profile["delayed"]
    }
    context.runtime_loaded_delayed_memory_ids = [
        key for key in getattr(context, "runtime_loaded_delayed_memory_ids", [])
        if key in profile["delayed"]
    ]
    context.memory_profile_revisions = {key: revision(value) for key, value in profile.items()}


def refresh_profile(context):
    if enabled(context):
        apply_profile(context, read_profile(context))


def publish_profile(context):
    if not enabled(context):
        return
    profile = read_profile(context)
    app = getattr(getattr(context, "websocket", None), "app", None)
    store = getattr(getattr(app, "state", None), "websocket_runtime_contexts", {})
    targets = list(store.values())
    if not any(target is context for target in targets):
        targets.append(context)
    for target in targets:
        if not enabled(target) or anonymous(target) != anonymous(context):
            continue
        transport = getattr(target, "runtime_transport", None)
        if transport is not None and transport.stopping:
            continue
        apply_profile(target, profile)
        if transport is not None:
            transport.publish({
                "type": "memory_profile_snapshot", "profile": profile,
                "revisions": target.memory_profile_revisions,
            })


def commit_active(context, records):
    from utils.active_memory_file_store import persist_active_records
    if not enabled(context):
        context.active_memory_records = records
        return
    persist_active_records(records, **file_options(context, "active"))
    publish_profile(context)


def persist_delayed(context, reports):
    from utils.delayed_memory_file_store import persist_delayed_memory_reports
    options = file_options(context, "delayed") if enabled(context) else {}
    errors = persist_delayed_memory_reports(reports, **options)
    if errors:
        raise OSError("; ".join(errors))
    publish_profile(context)
    return errors


def handle_store_sync(context, message):
    """Only explicit browser edits based on this disk revision can write."""
    if not enabled(context):
        return False
    kind = {"active_memory_store_sync": "active", "delayed_memory_store_sync": "delayed",
            "lt_memory_store_sync": "lt", "facts_memory_store_sync": "pending"}.get(message.get("type"))
    from utils.delayed_memory_file_store import delete_delayed_memory_report_files
    if kind is None:
        return False
    refresh_profile(context)
    accepted = message.get("memory_revision") == context.memory_profile_revisions[kind]
    if accepted and kind == "active" and message.get("mutation") is True:
        from websocket.bootstrap import clean_active_memory_records
        commit_active(context, clean_active_memory_records(message.get("active_memory_records", [])))
    elif accepted and kind == "delayed":
        from websocket.bootstrap import (apply_delayed_memory_reports,
            apply_loaded_delayed_memory_ids, apply_suppressed_delayed_memory_auto_load_ids)
        # Passive sync may only update existing reports. Explicit delete/restore
        # comes from the panel, with the same revision guard.
        incoming = message.get("delayed_memory_reports", {})
        incoming = {key: value for key, value in incoming.items()
                    if key in context.delayed_memory_reports or message.get("mutation") is True}
        changed = {**message, "delayed_memory_reports": incoming, "_profile_edit": True}
        deleted = apply_delayed_memory_reports(context, changed)
        reports = deepcopy(context.delayed_memory_reports)
        for report_id in deleted:
            errors = delete_delayed_memory_report_files(report_id, **file_options(context, "delayed"))
            if errors:
                raise OSError("; ".join(errors))
        persist_delayed(context, reports)
        apply_loaded_delayed_memory_ids(context, message)
        apply_suppressed_delayed_memory_auto_load_ids(context, message)
    # L-T has explicit edit/delete/restore messages. FRAME produces pending
    # candidates on the server. Ordinary browser inventories cannot revive them.
    publish_profile(context)
    return True


def collect_frame_candidates(context, snapshot):
    if not enabled(context):
        return
    import re
    from utils.long_term_facts_file_store import load_pending_facts, persist_pending_records
    from runtime.LT_memory_utils import normalize_facts_memory_records
    from runtime.frame_memory_utils import strip_runtime_memory_line_metadata
    records = load_pending_facts(**file_options(context, "facts")).get("records", [])
    session_id = context.session_id
    record = next((item for item in records if item.get("session_id") == session_id), None)
    if record is None:
        record = {"session_id": session_id, "signals": {}}
        records.append(record)
    for line in snapshot.get("lines", []):
        key = str(line.get("key", "")).strip()
        if key in {"user_message", "user_idle"} or re.match(r"(?:active_memory|jin_response|l-?t_fact)", key, re.I):
            continue
        content = strip_runtime_memory_line_metadata(str(line.get("value", ""))).strip()
        if not key or not content:
            continue
        old = record["signals"].get(key, {})
        if old.get("content") == content:
            continue
        record["signals"][key] = {
            "content": content, "session_id": session_id,
            "runtime_snapshot_id": snapshot.get("runtime_memory_id", ""),
            "lt_status": "pending", "lt_analyzed_at": "",
        }
    persist_pending_records(normalize_facts_memory_records(records), **file_options(context, "facts"))
    publish_profile(context)


def clear_anonymous_files(memory_root=MEMORY_ROOT):
    for folder in ("active", "delayed", "facts"):
        for path in (Path(memory_root) / folder).glob("*_anon.json"):
            path.unlink()


def release_profile(context, app_state):
    if not enabled(context) or not anonymous(context):
        return
    others = getattr(app_state, "websocket_runtime_contexts", {}).values()
    if any(anonymous(other) and not getattr(getattr(other, "runtime_transport", None), "stopping", False)
           for other in others if other is not context):
        return
    import asyncio
    cleanup = getattr(app_state, "anonymous_memory_cleanup", None)
    if cleanup is not None:
        cleanup.cancel()

    def clean_if_last():
        app_state.anonymous_memory_cleanup = None
        contexts = getattr(app_state, "websocket_runtime_contexts", {}).values()
        if not any(anonymous(item) for item in contexts):
            clear_anonymous_files(root(context))

    # A page reload replaces its transport. Allow that replacement to join;
    # disconnected pages otherwise retain the existing ten-minute grace.
    app_state.anonymous_memory_cleanup = asyncio.get_running_loop().call_later(
        ANONYMOUS_CLOSE_GRACE_SECONDS, clean_if_last,
    )
