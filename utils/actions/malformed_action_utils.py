"""Recognize three non-executable envelopes; never repair or run their payload."""
import re
from functools import lru_cache

from .regexp_utils import (
    RUNTIME_ACTION_EXECUTABLE_PREFIX,
    RuntimeActionRegexpMatch,
    is_quoted_runtime_marker,
)


MALFORMED_ACTION = "MALFORMED_ACTION"


@lru_cache(maxsize=None)
def _patterns(names, short_payload_names):
    name = "(?:" + "|".join(re.escape(n) for n in names) + ")"
    short = "(?:" + "|".join(re.escape(n) for n in short_payload_names) + ")"
    # Both spellings of the screenshot's wrapper are accepted as failures.
    wrapper = re.compile(
        RUNTIME_ACTION_EXECUTABLE_PREFIX
        + r"<\|?tool_call>\s*call\s*:\s*(?P<name>" + name + r")"
        + r"\s*(?P<payload>\{[^<>]*\})\s*(?:<\|?/tool_call>|<\|?tool_call\|?>)",
        re.I | re.S,
    )
    attributes = re.compile(
        RUNTIME_ACTION_EXECUTABLE_PREFIX
        + r"<(?P<name>" + name + r")\s+(?P<payload>[A-Za-z_]\w*\s*=[^<>]+)>"
        + r"\s*</(?P=name)\s*>", re.I | re.S,
    )
    body = re.compile(
        RUNTIME_ACTION_EXECUTABLE_PREFIX
        + r"<(?P<name>" + short + r")>\s*"
        + r"(?P<payload>\{\s*[A-Za-z_]\w*\s*=[^<>]*\})\s*</(?P=name)\s*>",
        re.I | re.S,
    )
    return wrapper, attributes, body


def find_malformed_action_matches(text, names, short_payload_names):
    if not names:
        return ()
    return tuple(
        RuntimeActionRegexpMatch(
            start=m.start(), end=m.end(), raw=m.group(),
            name=m.group("name").upper(), payload=m.group("payload").strip(),
            source="malformed",
        )
        for pattern in _patterns(tuple(names), tuple(short_payload_names))
        for m in pattern.finditer(text)
    )


def find_pending_malformed_action_start(text, names, short_payload_names):
    """Keep an envelope private until its close, also at arbitrary chunk splits."""
    if not names:
        return None
    complete = find_malformed_action_matches(text, names, short_payload_names)
    for opening in re.finditer(r"<", text):
        start = opening.start()
        if is_quoted_runtime_marker(text, start):
            continue
        if any(m.start <= start < m.end for m in complete):
            continue
        candidate = text[start:]
        upper = candidate.upper()
        wrappers = ("<TOOL_CALL>", "<|TOOL_CALL>")
        if any(upper.startswith(w) for w in wrappers):
            tail = candidate[candidate.index(">") + 1:].lstrip()
            if "CALL:".startswith(tail.upper()):
                return start
            call = re.match(r"call\s*:\s*([A-Z0-9_]*)", tail, re.I)
            if call and any(n.startswith(call.group(1).upper()) for n in names):
                payload = tail[call.end():].lstrip()
                if payload and not payload.startswith("{"):
                    continue
                # A completed unknown/other wrapper is plain text, not a guess.
                if not re.search(r"<\|?/?tool_call\|?>", tail, re.I):
                    return start
        for name in names:
            prefix = "<" + name
            if not upper.startswith(prefix):
                continue
            tail = candidate[len(prefix):]
            if tail and tail[0].isspace():
                if ">" not in tail:
                    return start
                if re.match(r"[^<>]*/\s*>", tail):
                    continue
                if re.match(r"\s+[A-Za-z_]\w*\s*=", tail):
                    if not re.search(r"</" + re.escape(name) + r"\s*>", tail, re.I):
                        return start
            if name in short_payload_names and tail.startswith(">"):
                body = tail[1:].lstrip()
                if not body or body.startswith("{"):
                    if not re.search(r"</" + re.escape(name) + r"\s*>", body, re.I):
                        return start
    return None


def build_malformed_notification(entry):
    from contracts.rules_assembler import get_runtime_action_schema
    from xml.sax.saxutils import escape

    result = entry["result"]
    name = result["malformed_action"]
    schema = "\n".join(get_runtime_action_schema(name))
    return (
        "<MALFORMED_ACTION_NOTIFICATION>\n"
        "In the previous message JIN used an incorrect schema when attempting an action.\n"
        f"tool_id: {escape(entry['tool_id'])}\n"
        f"Action: {escape(name)}\n"
        f"Payload: {escape(result['payload'])}\n"
        "If the action is still necessary to complete the request, use the correct schema:\n"
        f"{schema}\n"
        "</MALFORMED_ACTION_NOTIFICATION>"
    )


async def record_malformed_action(context, action, *, runtime_message_id="", context_snapshot=None):
    from utils.tool_results import record_runtime_tool_result, TOOL_RESULT_KIND_RUNTIME_ACTION
    from utils.session_actions_history import record_session_action_history, emit_session_actions_update
    from utils.context.runtime_action_result_text import format_runtime_action_result

    event = {
        "ok": False, "name": "malformed_action", "action": "malformed_action",
        "status": "failed", "error": "malformed_action",
        "malformed_action": action.marker_name, "payload": action.payload,
        "runtime_turn_id": str(getattr(context, "runtime_current_turn_id", "") or ""),
        "runtime_message_id": runtime_message_id,
    }
    if not hasattr(context, "runtime_action_events"):
        context.runtime_action_events = []
    context.runtime_action_events.append(event)
    record_runtime_tool_result(context, TOOL_RESULT_KIND_RUNTIME_ACTION, event)
    entry = context.runtime_tool_results[-1]
    event["tool_id"] = entry["tool_id"]
    text = f"MALFORMED_ACTION: {action.marker_name}"
    detail = format_runtime_action_result(event)
    record_session_action_history(
        context, text, preserve_separate=True,
        display_parts=[{"text": text, "detail": detail, "tool_ids": [entry["tool_id"]]}],
    )
    log_runtime = getattr(getattr(context, "logger", None), "log_runtime", None)
    if log_runtime is not None:
        await log_runtime(f"[RUNTIME ACTION] {text}")
    emit = getattr(getattr(context, "emitter", None), "emit", None)
    if emit is not None:
        await emit({
            **event, "type": "runtime_action", "id": entry["tool_id"],
            "display_name": MALFORMED_ACTION, "close_tag": False,
            "text": text, "detail": detail, "context": context_snapshot,
        })
    await emit_session_actions_update(context, current_sequence=True)
