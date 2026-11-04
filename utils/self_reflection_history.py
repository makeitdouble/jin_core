"""Compact evidence from raw JSONL, with one stable index space per archive.

The first successful analysis freezes this projection in the reflection store.
Snapshots provide action metadata only; they never supply dialogue or FRAME.
"""
import json
import re
from datetime import datetime, timezone

from runtime.anonymous_mode import is_anonymous_session_id


def clean_text(value, limit=None):
    text = str(value or "")
    text = re.sub(r"<(FILE_CONTENT|TOOLS_RESULTS|REASONING|FRAME_MEMORY\w*)\b[^>]*>.*?</\1>",
                  "[embedded context omitted]", text, flags=re.S | re.I)
    text = re.sub(r"```[^\n]*\n.{2000,}?```", "[long code/file body omitted]", text, flags=re.S)
    text = re.sub(r"data:[^\s;]+;base64,[A-Za-z0-9+/=\s]+", "[binary omitted]", text)
    text = re.sub(r"[A-Za-z0-9+/=]{200,}", "[binary omitted]", text)
    text = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", text, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", "", text)
    return text if limit is None or len(text) <= limit else text[:limit] + " [content omitted]"


_OMIT = {"context", "context_snapshot", "system_prompt", "reasoning", "html",
         "base64", "image", "images", "data", "content", "body", "file_content",
         "session_checkpoint", "bootstrap", "frame", "raw_response"}
_OUTCOME = {"ok", "success", "status", "error", "errors", "reason", "detail",
            "failure_reason", "message", "exit_code", "returncode", "isError"}


def outcome_summary(value):
    """Keep explicit receipts buried inside an otherwise omitted tool body."""
    if isinstance(value, dict):
        summary = {str(k): clean_text(v, 700) if isinstance(v, str) else v
                   for k, v in value.items() if k in _OUTCOME and not isinstance(v, (dict, list))}
        nested = [outcome_summary(v) for v in value.values() if isinstance(v, (dict, list))]
        nested = [v for v in nested if v]
        if nested:
            summary["nested_outcomes"] = nested
        return summary
    if isinstance(value, list):
        return [summary for v in value if (summary := outcome_summary(v))]
    return None


def compact(value, depth=0):
    """Retain outcome fields even when large sibling payloads are discarded."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if str(key).lower() in _OMIT:
                outcomes = outcome_summary(item)
                if outcomes:
                    result[str(key) + "_outcomes"] = outcomes
            elif depth < 5 or str(key) in _OUTCOME:
                result[str(key)] = compact(item, depth + 1)
        return result
    if isinstance(value, list):
        if depth > 5:
            return "[nested payload omitted]"
        result = [compact(v, depth + 1) for v in value[:12]]
        if len(value) > 12:
            result.append({"omitted_items": len(value) - 12, "outcomes": outcome_summary(value[12:])})
        return result
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return clean_text(value, 700)
        return compact(parsed, depth + 1) if isinstance(parsed, (dict, list)) else clean_text(value, 700)
    return value


def stamp(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt.replace(tzinfo=timezone.utc).timestamp() if dt.tzinfo is None else dt.timestamp()
    except (ValueError, TypeError, OverflowError):
        return 0.0


def archive_paths(root):
    grouped = {}
    for path in sorted(root.glob("????-??-??/*/*.jsonl")):
        if is_anonymous_session_id(path.parent.name) or not path.resolve().is_relative_to(root.resolve()):
            continue
        grouped.setdefault(path.parent.name, []).append(path)
    return grouped


def normalize_session(session_id, paths):
    rows, seen = [], {}
    for path in paths:
        with path.open(encoding="utf-8-sig") as stream:
            for line_no, line in enumerate(stream):
                if not line.strip():
                    continue
                # Do not silently mark a corrupt archive as fully processed.
                row = json.loads(line)
                if not isinstance(row, dict) or row.get("session_id", session_id) != session_id:
                    continue
                role = str(row.get("role", "")).lower()
                if role not in {"user", "jin", "assistant", "brain", "service"} and row.get("event") not in {
                    "runtime_tool_result", "runtime_action_request", "session_actions_snapshot"
                }:
                    continue
                identity_row = ({key: row.get(key) for key in ("session_id", "turn_id", "turn", "ts", "role", "text")}
                                if role in {"user", "jin", "assistant", "brain", "service"} else row)
                identity = json.dumps(identity_row, sort_keys=True, ensure_ascii=False)
                if identity in seen and seen[identity] != path:
                    continue
                seen[identity] = path
                rows.append((stamp(row.get("ts")), path.as_posix(), line_no, row))
    rows.sort(key=lambda item: item[:3])
    turns, records = {}, []
    snapshots = {}
    for order, (_, _, _, row) in enumerate(rows):
        turn = str(row.get("turn_id") or row.get("turn") or "unknown")
        group = turns.setdefault(turn, {"actions": [], "records": [], "order": order})
        role = str(row.get("role", "")).lower()
        if role in {"user", "jin", "assistant", "brain", "service"}:
            text = clean_text(row.get("text"))
            if not text.strip():
                # Keep the turn owner: its actions can still produce an ACTION record.
                continue
            record = {"turn_id": turn, "role": "USER" if role == "user" else "JIN",
                      "text": text, "ts": row.get("ts", ""), "order": order}
            group["records"].append(record)
            records.append(record)
            continue
        payload = row.get("payload")
        if not isinstance(payload, dict):
            continue
        if row["event"] == "session_actions_snapshot":
            for item in payload.get("items", []):
                if not isinstance(item, dict) or item.get("session_id", session_id) != session_id:
                    continue
                own_turn = str(item.get("runtime_turn_id") or item.get("turn_id") or turn)
                key = (own_turn, str(item.get("id") or item.get("created_at") or item.get("text")))
                snapshots[key] = (order, item)
        elif row["event"] == "runtime_tool_result":
            own_turn = str(payload.get("runtime_turn_id") or turn)
            target = turns.setdefault(own_turn, {"actions": [], "records": [], "order": order})
            result = payload.get("result")
            action_name = payload.get("action_name") or (result.get("action") if isinstance(result, dict) else None) or payload.get("kind", "tool")
            target["actions"].append({"tool_id": payload.get("tool_id", ""),
                "action": action_name,
                "arguments": compact(payload.get("action_payload", "")), "result": compact(payload.get("result"))})
        else:
            group["actions"].append({"id": payload.get("id", ""), "action": payload.get("action", ""),
                "arguments": compact(payload.get("payload", "")), "status": payload.get("status", "requested")})
    for (turn, _), (order, item) in snapshots.items():
        target = turns.setdefault(turn, {"actions": [], "records": [], "order": order})
        known_tools = {a.get("tool_id") for a in target["actions"] if a.get("tool_id")}
        parts = item.get("parts") or [item]
        for part in parts:
            if not isinstance(part, dict) or set(part.get("tool_ids") or []) & known_tools:
                continue
            action = {"summary": clean_text(part.get("text", ""), 700),
                      "status": part.get("status", item.get("status", "recorded"))}
            for field in ("detail", "context_detail"):
                detail = compact(part.get(field))
                if isinstance(detail, (dict, list)):
                    serialized = json.dumps(detail, ensure_ascii=False)
                    if len(serialized) > 700:
                        detail = clean_text(serialized, 700)
                if detail and (not isinstance(detail, str) or detail.strip()):
                    action[field] = detail
            target["actions"].append(action)
    for turn, group in turns.items():
        actions = list({json.dumps(a, sort_keys=True, ensure_ascii=False): a for a in group["actions"]}.values())
        if actions:
            if group["records"]:
                group["records"][0]["actions"] = actions
            else:
                records.append({"turn_id": turn, "role": "ACTION", "text": "", "actions": actions,
                                "ts": rows[group["order"]][3].get("ts", ""),
                                "order": group["order"]})
    records.sort(key=lambda record: record["order"])
    for index, record in enumerate(records, 1):
        record.pop("order")
        record["message_index"] = index
    return records


def serialize_history(session_id, records, cursor, characteristics=None):
    remaining = [record for record in records if record.get("message_index", 0) > cursor]
    return json.dumps({
        "session_id": session_id,
        "last_processed_index": cursor,
        "history": remaining,
        "characteristics": list(characteristics or []),
    }, ensure_ascii=False, indent=2)
