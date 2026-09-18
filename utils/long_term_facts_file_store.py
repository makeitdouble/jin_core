from __future__ import annotations

import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from runtime.LT_memory_utils import (
    normalize_facts_memory_records,
    normalize_lt_store,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LONG_TERM_FACTS_ROOT = PROJECT_ROOT / "memory" / "facts"
LONG_TERM_FACTS_FILENAME = "long_term_facts.json"


def atomic_write_json(path, payload):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    name = ""
    try:
        with NamedTemporaryFile(mode="w", encoding="utf-8", newline="\n",
                                dir=path.parent, prefix="." + path.stem,
                                suffix=".tmp", delete=False) as stream:
            name = stream.name
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()
    return path


def get_long_term_facts_path(*, root=LONG_TERM_FACTS_ROOT, anonymous=False):
    return Path(root) / ("long_term_facts_anon.json" if anonymous else LONG_TERM_FACTS_FILENAME)


def pending_facts_path(*, root=LONG_TERM_FACTS_ROOT, anonymous=False):
    return Path(root) / ("pending_facts_anon.json" if anonymous else "pending_facts.json")


def load_pending_facts(*, root=LONG_TERM_FACTS_ROOT, anonymous=False):
    path = pending_facts_path(root=root, anonymous=anonymous)
    if not path.exists():
        return {"pending_facts": [], "records": []}
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"Invalid pending facts file: {path}")
    return payload


def persist_pending_records(records, *, root=LONG_TERM_FACTS_ROOT, anonymous=False):
    payload = load_pending_facts(root=root, anonymous=anonymous)
    payload["records"] = normalize_facts_memory_records(records)
    atomic_write_json(pending_facts_path(root=root, anonymous=anonymous), payload)


def _merge_pending_records(existing, incoming):
    """Import only browser fields that do not already exist on disk."""
    merged = {}
    order = []

    def absorb(records, *, overwrite):
        for record in normalize_facts_memory_records(records):
            identity = record.get("session_id") or record.get("storage_key")
            if identity not in merged:
                merged[identity] = {
                    **record,
                    "signals": dict(record.get("signals") or {}),
                }
                order.append(identity)
                continue
            target = merged[identity]
            if record.get("storage_key") and not target.get("storage_key"):
                target["storage_key"] = record["storage_key"]
            for key, field in (record.get("signals") or {}).items():
                if overwrite or key not in target["signals"]:
                    target["signals"][key] = field
            target["signal_count"] = len(target["signals"])

    # Legacy browser records are only a migration source. Existing disk fields
    # always win if both sides contain the same session/key.
    absorb(incoming, overwrite=False)
    absorb(existing, overwrite=True)
    return normalize_facts_memory_records([merged[key] for key in order])


def import_legacy_pending_records(records, *, root=LONG_TERM_FACTS_ROOT, anonymous=False):
    path = pending_facts_path(root=root, anonymous=anonymous)
    payload = load_pending_facts(root=root, anonymous=anonymous)
    if payload.get("legacy_browser_import_pending") is not True:
        return False

    payload["records"] = _merge_pending_records(
        payload.get("records", []),
        records,
    )
    payload.pop("legacy_browser_import_pending", None)
    atomic_write_json(path, payload)
    return True


def load_long_term_facts_store(*, root=LONG_TERM_FACTS_ROOT, anonymous=False):
    path = get_long_term_facts_path(root=root, anonymous=anonymous)
    raw = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
    pending_path = pending_facts_path(root=root, anonymous=anonymous)

    if not pending_path.exists():
        # Old builds embedded the extraction queue in long_term_facts.json and
        # kept raw Facts Memory candidates only in browser storage. The presence
        # of that legacy key is a durable one-time migration signal. Once it is
        # stripped below, deleting pending_facts.json later means "empty" and
        # stale browser storage can never become authoritative again.
        pending_payload = {
            "pending_facts": raw.get("pending_facts", [])
                if isinstance(raw.get("pending_facts"), list) else [],
            "records": [],
        }
        if "pending_facts" in raw:
            pending_payload["legacy_browser_import_pending"] = True
        atomic_write_json(pending_path, pending_payload)

    pending = load_pending_facts(root=root, anonymous=anonymous)
    store = normalize_lt_store({**raw, "pending_facts": pending.get("pending_facts", [])})
    disk = {key: value for key, value in store.items() if key != "pending_facts"}
    if path.exists() and raw != disk:
        atomic_write_json(path, disk)
    return store, []


def persist_long_term_facts_store(store, *, root=LONG_TERM_FACTS_ROOT, anonymous=False):
    payload = normalize_lt_store(store)
    pending = load_pending_facts(root=root, anonymous=anonymous)
    pending["pending_facts"] = payload.pop("pending_facts", [])
    atomic_write_json(pending_facts_path(root=root, anonymous=anonymous), pending)
    return atomic_write_json(get_long_term_facts_path(root=root, anonymous=anonymous), payload)
