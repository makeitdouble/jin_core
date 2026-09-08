"""Small, index-free literal search over the canonical chat archive."""
from __future__ import annotations

import heapq
import json
import re
from datetime import date, datetime, time, timezone
from pathlib import Path

from utils.chat_log import chat_log_root_for_context, summarize_attachments

CHAT_LOG_SEARCH_DEFAULT_LIMIT = 10
CHAT_LOG_SEARCH_MAX_LIMIT = 50
REASONING_EXCERPT_RADIUS = 160
REASONING_EXCERPT_LIMIT = 3


def extract_chat_log_search_query(value) -> str:
    """Return the human-readable query without validating the whole request."""
    request = value
    if isinstance(value, str):
        try:
            request = json.loads(value)
        except (TypeError, ValueError):
            return ""

    if not isinstance(request, dict):
        return ""

    queries = request.get("query")
    if isinstance(queries, str):
        queries = [queries]
    if not isinstance(queries, list):
        return ""

    normalized = []
    for query in queries:
        if not isinstance(query, str):
            continue
        query = query.strip()
        if query and query not in normalized:
            normalized.append(query)

    return " | ".join(normalized)


def normalize_chat_log_search(payload: str) -> dict:
    try:
        request = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise ValueError("Payload must be a JSON object with search criteria.") from exc
    if not isinstance(request, dict):
        raise ValueError("Payload must be a JSON object with search criteria.")
    allowed = {"query", "has_attachments", "source", "start_date", "end_date", "start_time", "end_time", "max_limit"}
    if request.keys() - allowed:
        raise ValueError("Unknown fields: " + ", ".join(sorted(request.keys() - allowed)))
    queries = request.get("query")
    queries = [queries] if isinstance(queries, str) else queries
    if queries is None:
        queries = []
    elif not isinstance(queries, list) or not queries or any(not isinstance(q, str) or not q.strip() for q in queries):
        raise ValueError("query must be a non-empty string or array of non-empty strings when provided.")
    has_attachments = request.get("has_attachments", False)
    if type(has_attachments) is not bool:
        raise ValueError("has_attachments must be true or false.")
    if not queries and not has_attachments:
        raise ValueError("CHAT_LOG_SEARCH requires query or has_attachments=true.")
    sources = request.get("source", ["user", "jin"])
    sources = [sources] if isinstance(sources, str) else sources
    if not isinstance(sources, list) or not sources or any(s not in ("user", "jin") for s in sources):
        raise ValueError("source must contain only user and/or jin.")
    limit = request.get("max_limit", CHAT_LOG_SEARCH_DEFAULT_LIMIT)
    if type(limit) is not int or not 1 <= limit <= CHAT_LOG_SEARCH_MAX_LIMIT:
        raise ValueError(f"max_limit must be an integer from 1 to {CHAT_LOG_SEARCH_MAX_LIMIT}.")
    normalized = {"query": list(dict.fromkeys(queries)), "has_attachments": has_attachments,
                  "source": list(dict.fromkeys(sources))}
    for field in ("start_date", "end_date", "start_time", "end_time"):
        value = request.get(field)
        if value is not None:
            pattern = r"\d{4}-\d{2}-\d{2}" if field.endswith("date") else r"\d{2}:\d{2}(?::\d{2})?"
            if not isinstance(value, str) or not re.fullmatch(pattern, value):
                raise ValueError(f"Invalid {field} format.")
            try:
                (date.fromisoformat if field.endswith("date") else time.fromisoformat)(value)
            except ValueError as exc:
                raise ValueError(f"Invalid {field} value.") from exc
        normalized[field] = value
    for suffix in ("date", "time"):
        start, end = normalized[f"start_{suffix}"], normalized[f"end_{suffix}"]
        parser = date.fromisoformat if suffix == "date" else time.fromisoformat
        if suffix == "time" and end and len(end) == 5:
            end += ":59"
        if start and end and parser(start) > parser(end):
            raise ValueError(f"start_{suffix} must not exceed end_{suffix}.")
    normalized["max_limit"] = limit
    return normalized


def _timestamp(row: dict) -> datetime | None:
    try:
        return datetime.fromisoformat(str(row.get("ts") or "").replace("Z", "+00:00"))
    except ValueError:
        return None


def _in_range(stamp: datetime, request: dict) -> bool:
    day, clock = stamp.date().isoformat(), stamp.time().replace(microsecond=0).isoformat()
    for prefix, value in (("start", day), ("end", day)):
        bound = request[f"{prefix}_date"]
        if bound and (value < bound if prefix == "start" else value > bound):
            return False
    for prefix in ("start", "end"):
        bound = request[f"{prefix}_time"]
        if bound:
            # A minute-precision end includes that whole minute.
            bound = bound + (":59" if prefix == "end" else ":00") if len(bound) == 5 else bound
            if (clock < bound if prefix == "start" else clock > bound):
                return False
    return True


def _matches(text: str, queries: list[str]) -> bool:
    folded = text.casefold()
    return any(q.casefold() in folded for q in queries)


def _message_matches(row: dict, request: dict) -> bool:
    if request["query"] and not _matches(str(row.get("text") or ""), request["query"]):
        return False
    if request.get("has_attachments") and not bool(row.get("attachments") or []):
        return False
    return True


def _reasoning_excerpts(folder: Path, row: dict, queries: list[str]) -> list[str]:
    directory = folder / "reasoning"
    name = str(row.get("reasoning_path") or "").replace("\\", "/").rsplit("/", 1)[-1]
    turn = str(row.get("turn_id") or "")
    if name:
        candidates = [directory / name]
    elif re.fullmatch(r"[A-Za-z0-9_-]+", turn):
        candidates = sorted(directory.glob(f"*_{turn}.txt"))[-1:]
    else:
        return []
    if not candidates or not candidates[0].is_file():
        return []
    candidate = candidates[0]
    if not candidate.resolve().is_relative_to(directory.resolve()):
        return []
    text = candidate.read_text(encoding="utf-8")
    _, marker, body = text.partition("--- REASONING ---")
    text = body.strip() if marker else text.strip()
    # Escaped alternatives are literal; original offsets preserve Unicode text.
    pattern = re.compile("|".join(re.escape(q) for q in queries), re.IGNORECASE)
    excerpts, previous_end = [], -1
    for match in pattern.finditer(text):
        start, end = max(0, match.start() - REASONING_EXCERPT_RADIUS), min(len(text), match.end() + REASONING_EXCERPT_RADIUS)
        if start < previous_end:
            continue
        excerpts.append(("…" if start else "") + text[start:end] + ("…" if end < len(text) else ""))
        previous_end = end
        if len(excerpts) == REASONING_EXCERPT_LIMIT:
            break
    return excerpts


def search_chat_logs(context, request: dict) -> dict:
    root = chat_log_root_for_context(context)
    newest, serial, matched, skipped = [], 0, 0, 0
    current_session = str(getattr(context, "session_id", "") or "")
    for path in sorted(root.glob("*/*/*.jsonl")):
        # Normal history does not expose other anonymous rooms.
        if path.parent.name.endswith("-anon") and path.parent.name != current_session:
            continue
        if not path.resolve().is_relative_to(root.resolve()):
            continue
        groups = {}
        with path.open(encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, 1):
                try:
                    row = json.loads(line)
                except ValueError:
                    skipped += 1
                    continue
                if not isinstance(row, dict):
                    skipped += 1
                    continue
                role = str(row.get("role") or "").strip().lower()
                role = "jin" if role in {"assistant", "brain", "service"} else role
                if role not in {"user", "jin"}:
                    continue
                if row.get("session_id") and row["session_id"] != path.parent.name:
                    skipped += 1
                    continue
                stamp = _timestamp(row)
                if stamp is None:
                    skipped += 1
                    continue
                turn = str(row.get("turn_id") or row.get("turn") or f"line:{line_number}")
                groups.setdefault(turn, []).append(({**row, "role": role}, stamp))
        for turn, rows in groups.items():
            eligible = [(row, stamp) for row, stamp in rows if _in_range(stamp, request)]
            users = [row for row, _ in eligible if row["role"] == "user" and _message_matches(row, request)]
            messages, excerpts, stamps = [], [], []
            for row, stamp in eligible:
                if row["role"] not in request["source"]:
                    continue
                visible_match = _message_matches(row, request)
                # has_attachments is a message filter: reasoning alone cannot satisfy it.
                thoughts = (_reasoning_excerpts(path.parent, row, request["query"])
                            if request["query"] and not request["has_attachments"] and row["role"] == "jin" and users else [])
                if not visible_match and not thoughts:
                    continue
                if visible_match:
                    messages.append(row)
                if thoughts:
                    excerpts.append({"timestamp": row["ts"], "excerpts": thoughts})
                    for user in users:
                        if user not in messages:
                            messages.append(user)
                stamps.append(stamp.replace(tzinfo=timezone.utc) if stamp.tzinfo is None else stamp.astimezone(timezone.utc))
            if not stamps:
                continue
            matched += 1
            serial += 1
            result = {"session_id": path.parent.name, "turn_id": turn, "archive": path.relative_to(root).as_posix(),
                      "messages": [{"role": r["role"], "timestamp": r["ts"], "text": str(r.get("text") or ""),
                                    "attachments": summarize_attachments(r.get("attachments", []))}
                                   for r in sorted(messages, key=lambda r: r["ts"])],
                      "reasoning": excerpts}
            heapq.heappush(newest, (max(stamps), serial, result))
            if len(newest) > request["max_limit"]:
                heapq.heappop(newest)
    return {"ok": True, "action": "CHAT_LOG_SEARCH", "request": request,
            "results": [item[2] for item in sorted(newest, reverse=True)],
            "matched_turns": matched, "has_more": matched > request["max_limit"], "skipped_records": skipped}


def format_chat_log_search(result: dict) -> str:
    lines = ["Status: success", "Request: " + json.dumps(result["request"], ensure_ascii=False),
             f"Returned: {len(result['results'])}; matching turns: {result['matched_turns']}; more: {str(result['has_more']).lower()}"]
    if result.get("skipped_records"):
        lines.append(f"Skipped malformed/missing-timestamp records: {result['skipped_records']}")
    if not result["results"]:
        lines.append("No matching messages found in saved logs.")
    for index, hit in enumerate(result["results"], 1):
        lines.extend(["", f"[{index}] Session: {hit['session_id']} | Turn: {hit['turn_id']} | Archive: {hit['archive']}"])
        for message in hit["messages"]:
            lines.append(f"{message['role'].upper()} [{message['timestamp']}]:")
            lines.extend("  " + line for line in message["text"].splitlines())
            if message["attachments"]:
                lines.append("Attachments: " + ", ".join(a["name"] + (f" [id: {a['id']}]" if a.get("id") else "") for a in message["attachments"]))
        for reasoning in hit["reasoning"]:
            lines.append(f"JIN reasoning excerpts [{reasoning['timestamp']}] (matching USER above):")
            for excerpt in reasoning["excerpts"]:
                lines.extend("  " + line for line in excerpt.splitlines())
    return "\n".join(lines)
