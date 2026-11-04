"""One atomic transaction owns evidence, cursor, counters and completion."""
import json
import re
import threading
from pathlib import Path
from xml.sax.saxutils import escape

from utils.long_term_facts_file_store import atomic_write_json

STORE_PATH = Path(__file__).resolve().parents[1] / "memory" / "self_reflection" / "state.json"
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


def load_state():
    if not STORE_PATH.exists():
        return {"version": 1, "sessions": {}, "events": [], "characteristics": {},
                "stats": {"processed_sessions": 0, "events": 0}}
    state = json.loads(STORE_PATH.read_text(encoding="utf-8-sig"))
    if not isinstance(state, dict) or state.get("version") != 1 or not all(
        isinstance(state.get(key), kind) for key, kind in
        (("sessions", dict), ("events", list), ("characteristics", dict), ("stats", dict))
    ):
        raise ValueError("Invalid self-reflection store")
    return state


def validate_result(text, session_id, records, cursor):
    result = _extract_reflection_json(text)
    if not isinstance(result, dict) or result.get("session_id") != session_id:
        raise ValueError("Reflection session_id does not match supplied history")
    if result.get("status") == "no_event" and set(result) == {"status", "session_id"}:
        return result
    if result.get("status") != "event_found" or set(result) != {
        "status", "session_id", "start_message_index", "end_message_index", "intuition_line"
    }:
        raise ValueError("Invalid reflection response schema")
    start, end = result["start_message_index"], result["end_message_index"]
    indexes = {r["message_index"] for r in records}
    if type(start) is not int or type(end) is not int or not cursor < start <= end <= len(records) or not set(range(start, end + 1)) <= indexes:
        raise ValueError("Reflection range must be in the unprocessed supplied history")
    line = result["intuition_line"]
    if not isinstance(line, dict) or set(line) != {"description", "success"} or type(line["success"]) is not bool:
        raise ValueError("Invalid intuition_line")
    if not isinstance(line["description"], str) or not 1 <= len(line["description"].strip()) <= 500:
        raise ValueError("Behavior description must be a short nonempty string")
    line["description"] = " ".join(line["description"].split())
    return result


def commit_result(state, session_id, records, result):
    previous = state["sessions"].get(session_id, {})
    if previous.get("completed"):
        return
    cursor = previous.get("cursor", 0)
    no_event = result["status"] == "no_event"
    end = len(records) if no_event else result["end_message_index"]
    complete = no_event or end == len(records)
    if not no_event:
        if end <= cursor:
            return
        event_id = f"{session_id}:{result['start_message_index']}:{end}"
        if any(e["id"] == event_id for e in state["events"]):
            return
        line = result["intuition_line"]
        key = " ".join(line["description"].split()).casefold()
        counts = state["characteristics"].setdefault(key, {
            "description": line["description"], "success_count": 0, "failure_count": 0})
        counts["success_count" if line["success"] else "failure_count"] += 1
        state["events"].append({"id": event_id, **result})
    state["sessions"][session_id] = {"cursor": end, "completed": complete, "history": records}
    state["stats"] = {"processed_sessions": sum(bool(s["completed"]) for s in state["sessions"].values()),
                      "events": len(state["events"])}
    atomic_write_json(STORE_PATH, state)


def intuition_block():
    state = load_state()
    lines = []
    for row in state["characteristics"].values():
        total = row["success_count"] + row["failure_count"]
        if total:
            description = escape(row["description"].replace("|", " / "))
            lines.append(f"{description} | {row['success_count'] / total:.2f} | {row['failure_count'] / total:.2f}")
    return "<JIN INTUITION BLOCK>\nBehavior | Success | Failure\n" + "\n".join(lines) + "\n</JIN INTUITION BLOCK>" if lines else ""
