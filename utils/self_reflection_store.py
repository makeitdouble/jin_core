"""One atomic transaction owns evidence, cursor, counters and completion."""
import json
import re
import threading
from pathlib import Path
from xml.sax.saxutils import escape

from utils.long_term_facts_file_store import atomic_write_json

STORE_PATH = Path(__file__).resolve().parents[1] / "memory" / "self_reflection" / "state.json"
STORE_VERSION = 2
CHARACTERISTIC_ID_RE = re.compile(r"^IC-(\d{6})$")
# Nonblocking claim shared by all rooms; no waiting Service jobs or queued retries.
ANALYSIS_LOCK = threading.Lock()


def _extract_reflection_json(text):
    """Extract one JSON object from a model response without weakening its schema.

    Service models sometimes wrap an otherwise valid object in a Markdown JSON
    fence or add a short preamble/trailer despite the prompt. The response is
    still validated strictly by ``validate_result`` after extraction. We use
    JSONDecoder.raw_decode rather than brace slicing so braces inside quoted
    strings remain safe.
    """
    source = str(text or "").lstrip("\ufeff").strip()
    if not source:
        raise ValueError("Reflection response is empty")

    fenced = re.findall(
        r"```(?:json)?\s*(.*?)\s*```",
        source,
        flags=re.IGNORECASE | re.DOTALL,
    )
    candidates = fenced + [source]
    decoder = json.JSONDecoder()

    for candidate in candidates:
        candidate = candidate.strip()
        try:
            parsed, _end = decoder.raw_decode(candidate)
        except json.JSONDecodeError:
            parsed = None
        if isinstance(parsed, dict):
            return parsed

        # Allow a short natural-language preamble/trailer, but only recover a
        # real JSON object; malformed JSON is not repaired or guessed.
        for match in re.finditer(r"\{", candidate):
            try:
                parsed, _end = decoder.raw_decode(candidate, match.start())
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed

    raise ValueError("Reflection response does not contain a valid JSON object")


def _empty_state():
    return {"version": STORE_VERSION, "next_characteristic_id": 1,
            "sessions": {}, "events": [], "characteristics": {},
            "stats": {"processed_sessions": 0, "events": 0}}


def _normalized_description(value):
    return " ".join(str(value or "").split())


def _validated_count(value, field):
    if type(value) is not int or value < 0:
        raise ValueError(f"Invalid self-reflection {field}")
    return value


def _migrate_state(state):
    """Normalize v1 text-keyed characteristics into stable v2 IDs in memory."""
    if not isinstance(state, dict) or state.get("version") not in {1, STORE_VERSION} or not all(
        isinstance(state.get(key), kind) for key, kind in
        (("sessions", dict), ("events", list), ("characteristics", dict), ("stats", dict))
    ):
        raise ValueError("Invalid self-reflection store")

    source_characteristics = state["characteristics"]
    normalized_characteristics = {}
    description_ids = {}
    used_ids = set()
    next_number = 1

    for key, raw in source_characteristics.items():
        if not isinstance(raw, dict):
            raise ValueError("Invalid self-reflection characteristic")
        candidate_id = str(raw.get("characteristic_id") or key or "").strip()
        match = CHARACTERISTIC_ID_RE.fullmatch(candidate_id)
        if match:
            if candidate_id in used_ids:
                raise ValueError("Duplicate self-reflection characteristic ID")
            used_ids.add(candidate_id)
            next_number = max(next_number, int(match.group(1)) + 1)

    migrated_rows = []
    for key, raw in source_characteristics.items():
        description = _normalized_description(raw.get("description"))
        if not description:
            raise ValueError("Invalid self-reflection characteristic description")
        candidate_id = str(raw.get("characteristic_id") or key or "").strip()
        if not CHARACTERISTIC_ID_RE.fullmatch(candidate_id):
            while f"IC-{next_number:06d}" in used_ids:
                next_number += 1
            candidate_id = f"IC-{next_number:06d}"
            used_ids.add(candidate_id)
            next_number += 1
        migrated_rows.append((candidate_id, description, raw))

    for characteristic_id, description, raw in migrated_rows:
        row = {"characteristic_id": characteristic_id, "description": description,
               "success_count": _validated_count(raw.get("success_count", 0), "success_count"),
               "failure_count": _validated_count(raw.get("failure_count", 0), "failure_count")}
        normalized_characteristics[characteristic_id] = row
        description_ids.setdefault(description.casefold(), characteristic_id)

    migrated_events = []
    seen_characteristics = set()
    for raw_event in state["events"]:
        if not isinstance(raw_event, dict):
            raise ValueError("Invalid self-reflection event")
        event = dict(raw_event)
        characteristic_id = str(event.get("characteristic_id") or "").strip()
        legacy_line = event.get("intuition_line")
        if not characteristic_id and isinstance(legacy_line, dict):
            characteristic_id = description_ids.get(
                _normalized_description(legacy_line.get("description")).casefold(), ""
            )
        if characteristic_id:
            if characteristic_id not in normalized_characteristics:
                raise ValueError("Self-reflection event references an unknown characteristic")
            event["characteristic_id"] = characteristic_id
            event.setdefault(
                "operation",
                "CREATE" if characteristic_id not in seen_characteristics else "UPDATE",
            )
            if "outcome" not in event and isinstance(legacy_line, dict) and type(legacy_line.get("success")) is bool:
                event["outcome"] = "success" if legacy_line["success"] else "failure"
            seen_characteristics.add(characteristic_id)
        migrated_events.append(event)

    configured_next = state.get("next_characteristic_id", 1)
    if type(configured_next) is not int or configured_next < 1:
        configured_next = 1
    next_number = max(next_number, configured_next)
    migrated = dict(state)
    migrated.update({
        "version": STORE_VERSION,
        "next_characteristic_id": next_number,
        "characteristics": normalized_characteristics,
        "events": migrated_events,
        "stats": {
            "processed_sessions": sum(
                bool(session.get("completed"))
                for session in state["sessions"].values()
                if isinstance(session, dict)
            ),
            "events": len(migrated_events),
        },
    })
    return migrated


def load_state(*, persist_migration=False):
    if not STORE_PATH.exists():
        return _empty_state()
    state = json.loads(STORE_PATH.read_text(encoding="utf-8-sig"))
    migrated = _migrate_state(state)
    if persist_migration and migrated != state:
        atomic_write_json(STORE_PATH, migrated)
    return migrated


def characteristics_for_service(state):
    normalized = _migrate_state(state)
    return [dict(normalized["characteristics"][characteristic_id])
            for characteristic_id in sorted(normalized["characteristics"])]


def validate_result(text, session_id, records, cursor, state=None):
    result = _extract_reflection_json(text)
    if not isinstance(result, dict) or result.get("session_id") != session_id:
        raise ValueError("Reflection session_id does not match supplied history")
    if result.get("status") == "no_event" and set(result) == {"status", "session_id"}:
        return result
    common_fields = {"status", "session_id", "start_message_index", "end_message_index",
                     "operation", "success"}
    if result.get("status") != "event_found" or result.get("operation") not in {"CREATE", "UPDATE"}:
        raise ValueError("Invalid reflection response schema")
    expected_fields = common_fields | (
        {"description"} if result["operation"] == "CREATE" else {"characteristic_id"}
    )
    if set(result) != expected_fields or type(result.get("success")) is not bool:
        raise ValueError("Invalid reflection response schema")
    start, end = result["start_message_index"], result["end_message_index"]
    indexes = {r["message_index"] for r in records}
    if type(start) is not int or type(end) is not int or not cursor < start <= end or not set(range(start, end + 1)) <= indexes:
        raise ValueError("Reflection range must be in the unprocessed supplied history")
    if result["operation"] == "CREATE":
        description = _normalized_description(result.get("description"))
        if not 1 <= len(description) <= 500:
            raise ValueError("Behavior description must be a short nonempty string")
        result["description"] = description
    else:
        characteristic_id = str(result.get("characteristic_id") or "").strip()
        characteristics = _migrate_state(state or _empty_state())["characteristics"]
        if characteristic_id not in characteristics:
            raise ValueError("UPDATE references an unknown characteristic_id")
        result["characteristic_id"] = characteristic_id
    return result


def _allocate_characteristic_id(state):
    number = state["next_characteristic_id"]
    while f"IC-{number:06d}" in state["characteristics"]:
        number += 1
    state["next_characteristic_id"] = number + 1
    return f"IC-{number:06d}"


def commit_result(state, session_id, records, result):
    migrated = _migrate_state(state)
    state.clear()
    state.update(migrated)
    previous = state["sessions"].get(session_id, {})
    if previous.get("completed"):
        raise ValueError("Reflection session is already complete")
    cursor = previous.get("cursor", 0)
    no_event = result["status"] == "no_event"
    end = len(records) if no_event else result["end_message_index"]
    complete = no_event or end == len(records)
    transaction = {
        "operation": "SKIP" if no_event else result["operation"],
        "session_id": session_id,
        "sent_from": cursor + 1 if cursor < len(records) else None,
        "sent_through": len(records) if cursor < len(records) else None,
        "event_from": None if no_event else result["start_message_index"],
        "event_through": None if no_event else end,
        "characteristic_id": None,
        "description": None,
        "outcome": None,
        "cursor_before": cursor,
        "cursor_after": end,
    }
    if not no_event:
        if end <= cursor:
            raise ValueError("Reflection event was already processed")
        event_id = f"{session_id}:{result['start_message_index']}:{end}"
        if any(event.get("id") == event_id for event in state["events"]):
            raise ValueError("Reflection event was already counted")
        if result["operation"] == "CREATE":
            characteristic_id = _allocate_characteristic_id(state)
            characteristic = {
                "characteristic_id": characteristic_id,
                "description": result["description"],
                "success_count": 0,
                "failure_count": 0,
            }
            state["characteristics"][characteristic_id] = characteristic
        else:
            characteristic_id = result["characteristic_id"]
            characteristic = state["characteristics"].get(characteristic_id)
            if characteristic is None:
                raise ValueError("UPDATE references an unknown characteristic_id")
        outcome = "success" if result["success"] else "failure"
        characteristic[f"{outcome}_count"] += 1
        transaction.update({"characteristic_id": characteristic_id,
                            "description": characteristic["description"],
                            "outcome": outcome})
        state["events"].append({
            "id": event_id,
            "status": "event_found",
            "session_id": session_id,
            "start_message_index": result["start_message_index"],
            "end_message_index": end,
            "operation": result["operation"],
            "characteristic_id": characteristic_id,
            "outcome": outcome,
            "success": result["success"],
        })
    state["sessions"][session_id] = {"cursor": end, "completed": complete, "history": records}
    state["stats"] = {"processed_sessions": sum(bool(s["completed"]) for s in state["sessions"].values()),
                      "events": len(state["events"])}
    atomic_write_json(STORE_PATH, state)
    return transaction


def intuition_block():
    state = load_state()
    lines = []
    for characteristic_id in sorted(state["characteristics"]):
        row = state["characteristics"][characteristic_id]
        total = row["success_count"] + row["failure_count"]
        if total:
            description = escape(row["description"].replace("|", " / "))
            lines.append(f"{characteristic_id} | {description} | "
                         f"{row['success_count'] / total:.2f} | {row['failure_count'] / total:.2f}")
    return ("<JIN INTUITION BLOCK>\nID | Behavior | Success | Failure\n" +
            "\n".join(lines) + "\n</JIN INTUITION BLOCK>" if lines else "")
