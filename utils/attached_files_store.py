from __future__ import annotations

import base64
import hashlib
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Iterable

from utils.actions.active_memory_utils import generate_short_runtime_id

FILES_DIR = Path("assets/files")
INDEX_FILE = FILES_DIR / ".index.json"
GITKEEP_FILE = FILES_DIR / ".gitkeep"
MAX_FILE_RECORDS = 100
MAX_ATTACHED_FILES = 3
FILE_ID_RE = re.compile(r"^[a-z0-9]{6}$", re.IGNORECASE)
STORED_NAME_RE = re.compile(r"^([a-z0-9]{6})_(.+)$", re.IGNORECASE)

TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".py", ".js", ".jsx", ".ts", ".tsx",
    ".json", ".csv", ".css", ".html", ".htm", ".xml", ".yaml", ".yml",
    ".toml", ".log", ".ini", ".cfg", ".conf", ".sql", ".sh", ".ps1",
}


def ensure_files_dir() -> Path:
    FILES_DIR.mkdir(parents=True, exist_ok=True)
    if not GITKEEP_FILE.exists():
        GITKEEP_FILE.touch()
    return FILES_DIR


def _safe_name(name: str) -> str:
    value = Path(str(name or "attachment")).name.strip()
    value = value.replace("\x00", "")
    return value or "attachment"


def _kind_for(name: str, mime_type: str) -> str:
    mime = str(mime_type or "").lower()
    suffix = Path(name).suffix.lower()
    if mime.startswith("image/"):
        return "image"
    if mime.startswith("text/") or suffix in TEXT_EXTENSIONS or any(
        token in mime for token in ("json", "javascript", "xml", "yaml")
    ):
        return "text"
    return "binary"


def _load_index() -> list[dict]:
    ensure_files_dir()
    if not INDEX_FILE.exists():
        return []
    try:
        data = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [dict(item) for item in data if isinstance(item, dict)]


def _save_index(records: list[dict]) -> None:
    ensure_files_dir()
    INDEX_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _timestamp(value, fallback: float | None = None) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return fallback
    return parsed if parsed > 0 else fallback


def _record_sort_key(record: dict) -> tuple:
    """Keep pins first, newest pin first, and use id+title as a stable tie-break."""
    created_at = _timestamp(record.get("created_at"), 0.0) or 0.0
    if record.get("pinned"):
        pinned_at = _timestamp(record.get("pinned_at"), created_at) or created_at
        return (
            0,
            -pinned_at,
            -created_at,
            str(record.get("id") or ""),
            str(record.get("name") or "").casefold(),
        )
    return (
        1,
        -created_at,
        str(record.get("id") or ""),
        str(record.get("name") or "").casefold(),
    )


def _oldest_pinned_record(records: list[dict], *, exclude_id: str = "") -> dict | None:
    candidates = [
        record
        for record in records
        if record.get("pinned") and record.get("id") != exclude_id
    ]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda record: (
            _timestamp(record.get("pinned_at"), _timestamp(record.get("created_at"), 0.0)) or 0.0,
            _timestamp(record.get("created_at"), 0.0) or 0.0,
            str(record.get("id") or ""),
            str(record.get("name") or "").casefold(),
        ),
    )


def _normalize_record(record: dict) -> dict | None:
    file_id = str(record.get("id") or "").strip().lower()
    stored_name = str(record.get("stored_name") or "").strip()
    if not FILE_ID_RE.fullmatch(file_id) or not stored_name:
        return None
    path = FILES_DIR / stored_name
    if not path.is_file():
        return None
    name = _safe_name(record.get("name") or stored_name.split("_", 1)[-1])
    mime_type = str(record.get("type") or mimetypes.guess_type(name)[0] or "application/octet-stream")
    created_at = record.get("created_at")
    try:
        created_at = float(created_at)
    except (TypeError, ValueError):
        created_at = path.stat().st_mtime
    pinned = bool(record.get("pinned", False))
    pinned_at = _timestamp(record.get("pinned_at"), created_at) if pinned else None
    normalized = {
        "id": file_id,
        "name": name,
        "stored_name": stored_name,
        "context_path": f"/assets/files/{stored_name}",
        "url": f"/assets/files/{stored_name}",
        "type": mime_type,
        "kind": str(record.get("kind") or _kind_for(name, mime_type)),
        "size_bytes": int(record.get("size_bytes") or path.stat().st_size),
        "created_at": created_at,
        "sha256": str(record.get("sha256") or ""),
        "pinned": pinned,
        "pinned_at": pinned_at,
        "width": record.get("width"),
        "height": record.get("height"),
    }
    if not normalized["sha256"]:
        normalized["sha256"] = _file_sha256(path)
    return normalized


def _scan_or_reconcile() -> list[dict]:
    ensure_files_dir()
    indexed = _load_index()
    by_stored = {
        str(item.get("stored_name") or ""): item
        for item in indexed
        if isinstance(item, dict)
    }
    records: list[dict] = []
    changed = False
    for path in FILES_DIR.iterdir():
        if not path.is_file() or path.name.startswith("."):
            continue
        match = STORED_NAME_RE.match(path.name)
        if not match:
            continue
        raw = by_stored.pop(path.name, None)
        if raw is None:
            file_id, name = match.groups()
            mime_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
            raw = {
                "id": file_id.lower(),
                "name": name,
                "stored_name": path.name,
                "type": mime_type,
                "kind": _kind_for(name, mime_type),
                "size_bytes": path.stat().st_size,
                "created_at": path.stat().st_mtime,
                "sha256": _file_sha256(path),
                "pinned": False,
                "pinned_at": None,
            }
            changed = True
        normalized = _normalize_record(raw)
        if normalized:
            records.append(normalized)
    if by_stored:
        changed = True
    records.sort(key=_record_sort_key)
    if changed or records != indexed:
        _save_index(records)
    return records


def list_file_records(limit: int = MAX_FILE_RECORDS) -> list[dict]:
    records = _scan_or_reconcile()
    try:
        limit = max(0, min(MAX_FILE_RECORDS, int(limit)))
    except (TypeError, ValueError):
        limit = MAX_FILE_RECORDS
    return [dict(record) for record in records[:limit]]


def get_file_record(file_id: str) -> dict | None:
    normalized_id = str(file_id or "").strip().lower()
    if not FILE_ID_RE.fullmatch(normalized_id):
        return None
    for record in _scan_or_reconcile():
        if record["id"] == normalized_id:
            return dict(record)
    return None


def get_pinned_file_ids() -> list[str]:
    return [record["id"] for record in _scan_or_reconcile() if record["pinned"]][:MAX_ATTACHED_FILES]


def set_file_pinned(file_id: str, pinned: bool) -> tuple[dict | None, str | None]:
    records = _scan_or_reconcile()
    target = None
    for record in records:
        if record["id"] == str(file_id or "").strip().lower():
            target = record
            break
    if target is None:
        return None, "not_found"
    if pinned and not target["pinned"]:
        pinned_count = sum(1 for record in records if record["pinned"])
        if pinned_count >= MAX_ATTACHED_FILES:
            oldest = _oldest_pinned_record(records, exclude_id=target["id"])
            if oldest is not None:
                oldest["pinned"] = False
                oldest["pinned_at"] = None
        target["pinned"] = True
        target["pinned_at"] = time.time()
    elif not pinned and target["pinned"]:
        target["pinned"] = False
        target["pinned_at"] = None
    records.sort(key=_record_sort_key)
    _save_index(records)
    return dict(target), None


def sync_pinned_file_ids(file_ids: Iterable[str]) -> list[str]:
    requested: list[str] = []
    for raw_id in file_ids or ():
        file_id = str(raw_id or "").strip().lower()
        if FILE_ID_RE.fullmatch(file_id) and file_id not in requested:
            requested.append(file_id)
        if len(requested) >= MAX_ATTACHED_FILES:
            break
    records = _scan_or_reconcile()
    existing = {record["id"] for record in records}
    requested = [file_id for file_id in requested if file_id in existing]
    requested_set = set(requested)
    now = time.time()
    requested_rank = {file_id: index for index, file_id in enumerate(requested)}
    for record in records:
        should_pin = record["id"] in requested_set
        if should_pin:
            if not record.get("pinned") or not _timestamp(record.get("pinned_at")):
                record["pinned_at"] = now - (requested_rank[record["id"]] * 0.000001)
            record["pinned"] = True
        else:
            record["pinned"] = False
            record["pinned_at"] = None
    records.sort(key=_record_sort_key)
    _save_index(records)
    return [record["id"] for record in records if record["pinned"]][:MAX_ATTACHED_FILES]


def store_uploaded_file(
    *,
    name: str,
    content: bytes,
    mime_type: str = "",
    width=None,
    height=None,
    pin: bool = True,
) -> tuple[dict, bool, str | None]:
    ensure_files_dir()
    original_name = _safe_name(name)
    payload = bytes(content or b"")
    sha256 = hashlib.sha256(payload).hexdigest()
    records = _scan_or_reconcile()
    for record in records:
        if record.get("sha256") == sha256:
            error = None
            if pin and not record.get("pinned"):
                record, error = set_file_pinned(record["id"], True)
            return dict(record), False, error

    used_ids = [record["id"] for record in records]
    file_id = generate_short_runtime_id(existing_ids=used_ids)
    stored_name = f"{file_id}_{original_name}"
    path = FILES_DIR / stored_name
    path.write_bytes(payload)
    resolved_mime = str(mime_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream")
    record = {
        "id": file_id,
        "name": original_name,
        "stored_name": stored_name,
        "context_path": f"/assets/files/{stored_name}",
        "url": f"/assets/files/{stored_name}",
        "type": resolved_mime,
        "kind": _kind_for(original_name, resolved_mime),
        "size_bytes": len(payload),
        "created_at": time.time(),
        "sha256": sha256,
        "pinned": False,
        "pinned_at": None,
        "width": width,
        "height": height,
    }
    records.append(record)
    _save_index(records)
    error = None
    if pin:
        record, error = set_file_pinned(file_id, True)
    return dict(record), True, error


def delete_file_record(file_id: str) -> bool:
    records = _scan_or_reconcile()
    normalized_id = str(file_id or "").strip().lower()
    remaining = []
    target = None
    for record in records:
        if record["id"] == normalized_id:
            target = record
        else:
            remaining.append(record)
    if target is None:
        return False
    path = FILES_DIR / target["stored_name"]
    try:
        path.unlink(missing_ok=True)
    finally:
        _save_index(remaining)
    return True


def _size_label(size: int) -> str:
    value = max(0, int(size or 0))
    if value < 1024:
        return f"{value} B"
    if value < 1024 * 1024:
        return f"{value / 1024:.1f} KB"
    return f"{value / (1024 * 1024):.1f} MB"


def hydrate_attachment_ids(file_ids: Iterable[str]) -> list[dict]:
    hydrated = []
    for file_id in list(file_ids or ())[:MAX_ATTACHED_FILES]:
        record = get_file_record(file_id)
        if not record:
            continue
        path = FILES_DIR / record["stored_name"]
        attachment = dict(record)
        attachment["size_label"] = _size_label(record["size_bytes"])
        if record["kind"] == "text":
            try:
                attachment["text_content"] = path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                attachment["text_content"] = ""
        elif record["kind"] == "image" or record["type"] == "application/pdf":
            try:
                encoded = base64.b64encode(path.read_bytes()).decode("ascii")
                attachment["data_url"] = f"data:{record['type']};base64,{encoded}"
            except OSError:
                pass
        hydrated.append(attachment)
    return hydrated


def public_file_snapshot(limit: int = MAX_FILE_RECORDS) -> dict:
    return {
        "files": list_file_records(limit),
        "pinned_ids": get_pinned_file_ids(),
        "max_attached_files": MAX_ATTACHED_FILES,
    }


def format_age(created_at: float, *, now: float | None = None) -> str:
    now = time.time() if now is None else float(now)
    seconds = max(1, int(now - float(created_at or now)))
    if seconds < 60:
        return f"{seconds}s"
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    if hours < 24:
        return f"{hours}h"
    return f"{hours // 24}d"


def format_list_files_lines(records: list[dict] | None = None) -> list[str]:
    records = records if records is not None else list_file_records()
    lines = []
    for index, record in enumerate(records[:MAX_FILE_RECORDS], start=1):
        size = _size_label(record.get("size_bytes", 0))
        dims = ""
        if record.get("width") and record.get("height"):
            dims = f" {record['width']}x{record['height']}"
        age = format_age(record.get("created_at") or time.time())
        lines.append(
            f"{index}. {record['name']} {size}{dims} [ id: {record['id']} ] ( {age} ago )"
        )
    return lines
