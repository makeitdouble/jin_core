"""One structured JSON file per Active record; browser strings are a wire format."""
import json
import re
from pathlib import Path

from utils.long_term_facts_file_store import atomic_write_json

ACTIVE_MEMORY_ROOT = Path(__file__).resolve().parents[1] / "memory" / "active"
TAG = re.compile(r"\[\s*([^:\[\]]+):\s*(.*?)\s*\]", re.S)


def record_payload(record):
    key, value = str(record).split(":", 1)
    if not re.fullmatch(r"active_memory(?:_\d+)?", key.strip()):
        raise ValueError("Invalid Active key")
    tags = list(TAG.finditer(value))
    identity = next((m for m in tags if m[1].strip() == "id"), None)
    if identity is None or not re.fullmatch(r"AM-[a-z0-9]{6}", identity[2].strip()):
        raise ValueError("Invalid Active id")
    return {
        "key": key.strip(), "conditions": value[:identity.start()].strip(),
        **{m[1].strip(): m[2].strip() for m in tags if m.start() >= identity.start()},
    }


def payload_record(payload):
    key = payload["key"]
    tags = " ".join(f"[ {name}: {value} ]" for name, value in payload.items()
                    if name not in {"key", "conditions"})
    record = f"{key}: {payload['conditions']} {tags}"
    record_payload(record)  # Validate file identities before exposing them.
    return record


def load_active_records(*, root=ACTIVE_MEMORY_ROOT, anonymous=False):
    records = []
    for path in Path(root).glob("*.json"):
        if path.stem.endswith("_anon") != anonymous:
            continue
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
        records.append(payload_record(payload))
    return sorted(records, key=lambda row: int(re.search(r"\d+", row.split(":", 1)[0])[0]))


def persist_active_records(records, *, root=ACTIVE_MEMORY_ROOT, anonymous=False):
    root = Path(root)
    suffix = "_anon" if anonymous else ""
    payloads = [record_payload(row) for row in records]
    names = {f"{p['id']}{suffix}.json" for p in payloads}
    for payload in payloads:
        atomic_write_json(root / f"{payload['id']}{suffix}.json", payload)
    for path in root.glob("*.json"):
        if path.stem.endswith("_anon") == anonymous and path.name not in names:
            path.unlink()
