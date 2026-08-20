import json
import re
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from runtime.runtime_context import RECENT_MESSAGES_MAX_PAIRS
from rules.runtime import (
    SESSION_RESTORE_REASONING_CHAR_LIMIT,
    SESSION_RESTORE_REASONING_COUNT,
)
from utils.chat_log import CHAT_LOG_ROOT, _clean_session_id
from utils.actions import normalize_jin_position_dict, normalize_jin_speed_value


BLOCK_RE_TEMPLATE = r"<{name}(?:\s+[^>]*)?>\s*(?P<body>[\s\S]*?)\s*</{name}>"
TOOL_RESULT_RE = re.compile(
    r'<TOOL_RESULT\s+name="(?P<name>[^"]+)"[^>]*>\s*(?P<body>[\s\S]*?)\s*</TOOL_RESULT>',
    re.IGNORECASE,
)
TRUSTED_VALUE_RE = re.compile(
    r"<(?P<name>CURRENT_[A-Z0-9_]+)>(?P<value>[\s\S]*?)</(?P=name)>",
    re.IGNORECASE,
)
ATTACHED_FILE_ID_RE = re.compile(
    r"\[\s*id\s*:\s*(?P<id>[a-zA-Z0-9_.-]+)\s*\]",
    re.IGNORECASE,
)
L4_FACT_ID_RE = re.compile(
    r"(?<![a-zA-Z0-9_])F(?P<number>\d+)(?![a-zA-Z0-9_])",
    re.IGNORECASE,
)


ACTION_LABELS = {
    "SAVE_DELAYED_MEMORY_CONTENT": "Saved delayed memory",
    "LOAD_DELAYED_MEMORY": "Loaded delayed memory",
    "UNLOAD_DELAYED_MEMORY": "Unloaded delayed memory",
    "SAVE_ACTIVE_MEMORY": "Saved active memory",
    "RESOLVE_ACTIVE_MEMORY": "Resolved active memory",
    "UPDATE_L4_FACTS": "Updated L4 facts",
    "ATTACH_FILE": "Attached file",
    "DETACH_FILE": "Detached file",
    "JIN_COLOR": "JIN color",
    "JIN_SIZE": "JIN size",
}


def _extract_block(text: str, name: str) -> str:
    match = re.search(
        BLOCK_RE_TEMPLATE.format(name=re.escape(name)),
        str(text or ""),
        re.IGNORECASE,
    )
    if match is None:
        return ""

    body = match.group("body").replace("\r\n", "\n")
    lines = body.splitlines()
    non_empty = [line for line in lines if line.strip()]
    if non_empty:
        indentation = min(
            len(line) - len(line.lstrip())
            for line in non_empty
        )
        if indentation:
            lines = [
                line[indentation:] if line.strip() else ""
                for line in lines
            ]
    return "\n".join(lines).strip()


def _parse_iso_timestamp(value) -> float:
    text = str(value or "").strip()
    if not text:
        return 0.0
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        return datetime.fromisoformat(normalized).timestamp()
    except ValueError:
        return 0.0


def _entry_timestamp(entry: dict) -> float:
    return _parse_iso_timestamp(entry.get("ts"))


def _find_session_directory(session_id: str, root: Path) -> Path | None:
    normalized = _clean_session_id(session_id)
    if not normalized or not root.is_dir():
        return None

    candidates = []
    for date_directory in root.iterdir():
        if not date_directory.is_dir():
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_directory.name):
            continue
        candidate = date_directory / normalized
        if candidate.is_dir():
            candidates.append(candidate)

    if not candidates:
        return None

    return sorted(candidates, key=lambda item: item.parent.name)[-1]


def _load_dialog(path: Path) -> list[dict]:
    entries = []
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return entries

    decoder = json.JSONDecoder()

    for line in lines:
        source = str(line or "").lstrip("\ufeff")
        offset = 0

        # A log can survive an interrupted append without the final newline.
        # If the next process later appends another object, the physical line
        # becomes ``}{``. Decode every adjacent JSON value so one damaged
        # separator cannot make the last visible chat bubble disappear.
        while offset < len(source):
            while offset < len(source) and source[offset].isspace():
                offset += 1
            if offset >= len(source):
                break

            try:
                entry, end = decoder.raw_decode(source, offset)
            except (TypeError, ValueError, json.JSONDecodeError):
                break

            if isinstance(entry, dict):
                entries.append(entry)

            if end <= offset:
                break
            offset = end

    return entries


def _recent_restored_dialog_pairs(entries: list[dict]) -> list[tuple[dict, dict]]:
    """Return the newest complete USER/JIN pairs in chronological order."""
    turns: dict[object, dict[str, dict]] = {}
    ordered_keys: list[object] = []

    for index, entry in enumerate(entries):
        role = str(entry.get("role", "")).strip().lower()
        if role not in {"user", "jin", "assistant", "brain", "service"}:
            continue

        text = str(entry.get("text", "") or "").strip()
        if not text:
            continue

        try:
            turn_number = int(entry.get("turn", 0) or 0)
        except (TypeError, ValueError):
            turn_number = 0

        turn_id = str(entry.get("turn_id", "") or "").strip()
        if turn_number > 0:
            key: object = ("turn", turn_number)
        elif turn_id:
            key = ("turn_id", turn_id)
        else:
            # Legacy rows without a turn identity cannot be paired safely.
            # Keep them isolated rather than accidentally joining unrelated text.
            key = ("row", index)

        if key not in turns:
            turns[key] = {}
            ordered_keys.append(key)

        side = "user" if role == "user" else "jin"
        turns[key][side] = entry

    complete_pairs = [
        (turns[key]["user"], turns[key]["jin"])
        for key in ordered_keys
        if "user" in turns[key] and "jin" in turns[key]
    ]
    return complete_pairs[-RECENT_MESSAGES_MAX_PAIRS:]


def _append_restored_dialog_entry(lines: list[str], entry: dict) -> None:
    role = str(entry.get("role", "")).strip().lower()
    tag = "USER" if role == "user" else "JIN"
    text = str(entry.get("text", "") or "").strip()
    timestamp = str(entry.get("ts", "") or "").strip()
    timestamp_attr = f' ts="{escape(timestamp)}"' if timestamp else ""
    lines.append(f"<{tag}{timestamp_attr}>{escape(text)}</{tag}>")


def _build_restored_dialog_context(
    entries: list[dict],
    session_id: str,
) -> str:
    lines = [
        f'<RESTORED_SESSION_DIALOG session_id="{escape(session_id)}">',
        "This is the exact visible dialogue restored from the archived session. The three newest complete USER/JIN pairs are shown in chronological order, ending at the latest archived JIN response; continue from that interaction state and do not summarize or re-introduce it unless the user asks.",
    ]

    for user_entry, jin_entry in _recent_restored_dialog_pairs(entries):
        _append_restored_dialog_entry(lines, user_entry)
        _append_restored_dialog_entry(lines, jin_entry)

    lines.append("</RESTORED_SESSION_DIALOG>")
    return "\n".join(lines)


def _build_recent_turns(entries: list[dict]) -> list[dict]:
    turns: dict[int, dict] = {}
    ordered_turns = []

    for entry in entries:
        try:
            turn_number = int(entry.get("turn", 0) or 0)
        except (TypeError, ValueError):
            turn_number = 0
        if turn_number <= 0:
            continue

        if turn_number not in turns:
            turn = {
                "user": "",
                "jin": "",
            }
            turns[turn_number] = turn
            ordered_turns.append((turn_number, turn))
        else:
            turn = turns[turn_number]

        role = str(entry.get("role", "")).strip().lower()
        text = str(entry.get("text", "") or "").strip()
        timestamp = _entry_timestamp(entry)

        if role == "user":
            turn["user"] = text
            if timestamp:
                turn["user_created_at"] = timestamp
        elif role in {"jin", "assistant", "brain", "service"}:
            turn["jin"] = text
            if timestamp:
                turn["jin_created_at"] = timestamp

    ordered_turns.sort(key=lambda item: item[0])
    return [
        item
        for _, item in ordered_turns[-RECENT_MESSAGES_MAX_PAIRS:]
        if item.get("user") or item.get("jin")
    ]


def _read_reasoning(session_directory: Path, entries: list[dict]) -> dict[str, str]:
    reasoning_directory = session_directory / "reasoning"
    if not reasoning_directory.is_dir():
        return {}

    by_turn_id = {}
    for entry in entries:
        role = str(entry.get("role", "")).strip().lower()
        if role not in {"jin", "assistant", "brain", "service"}:
            continue

        turn_id = str(entry.get("turn_id", "") or "").strip()
        reasoning_path = str(entry.get("reasoning_path", "") or "").strip()
        candidate = None

        if reasoning_path:
            candidate = reasoning_directory / Path(reasoning_path).name
        elif turn_id:
            matches = sorted(reasoning_directory.glob(f"*_{turn_id}.txt"))
            candidate = matches[-1] if matches else None

        if candidate is None or not candidate.is_file():
            continue

        try:
            text = candidate.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            by_turn_id[turn_id] = text

    return by_turn_id


def _crop_restore_reasoning(
    text: str,
    *,
    limit: int = SESSION_RESTORE_REASONING_CHAR_LIMIT,
) -> str:
    cleaned = str(text or "").strip()
    if not cleaned:
        return ""

    try:
        max_chars = max(int(limit), 0)
    except (TypeError, ValueError):
        max_chars = SESSION_RESTORE_REASONING_CHAR_LIMIT

    if not max_chars or len(cleaned) <= max_chars:
        return cleaned

    marker_template = "\n--- CUT {chars} MIDDLE CHARS ---\n"
    marker = marker_template.format(chars=0)
    edge_budget = max(max_chars - len(marker), 2)
    head_chars = edge_budget // 2
    tail_chars = edge_budget - head_chars
    cut_chars = len(cleaned) - head_chars - tail_chars
    marker = marker_template.format(chars=max(cut_chars, 0))

    # Recalculate once because the digit count inside the marker changes its size.
    edge_budget = max(max_chars - len(marker), 2)
    head_chars = edge_budget // 2
    tail_chars = edge_budget - head_chars
    cut_chars = len(cleaned) - head_chars - tail_chars
    marker = marker_template.format(chars=max(cut_chars, 0))

    return (
        cleaned[:head_chars]
        + marker
        + cleaned[-tail_chars:]
    )[:max_chars]


def _build_restore_reasoning_dump(
    entries: list[dict],
    reasoning_by_turn_id: dict[str, str],
) -> str:
    blocks = []

    for entry in reversed(entries):
        role = str(entry.get("role", "")).strip().lower()
        if role not in {"jin", "assistant", "brain", "service"}:
            continue

        turn_id = str(entry.get("turn_id", "") or "").strip()
        reasoning = _crop_restore_reasoning(
            reasoning_by_turn_id.get(turn_id, "")
        )
        if not reasoning:
            continue

        timestamp = str(entry.get("ts", "") or "").strip()
        attrs = []
        if turn_id:
            attrs.append(f'turn_id="{escape(turn_id)}"')
        if timestamp:
            attrs.append(f'ts="{escape(timestamp)}"')
        attr_text = (" " + " ".join(attrs)) if attrs else ""
        blocks.append(
            f"<REASONING{attr_text}>\n{reasoning}\n</REASONING>"
        )

        if len(blocks) >= SESSION_RESTORE_REASONING_COUNT:
            break

    if not blocks:
        return ""

    return (
        '<RESTORED_SESSION_REASONING_DUMP order="newest_first">\n'
        + "\n\n".join(blocks)
        + "\n</RESTORED_SESSION_REASONING_DUMP>"
    )


def _extract_l4_fact_ids(*texts: str) -> list[str]:
    ids = []
    seen = set()

    for text in texts:
        for match in L4_FACT_ID_RE.finditer(str(text or "")):
            fact_id = f"F{match.group('number')}".upper()
            if fact_id in seen:
                continue
            seen.add(fact_id)
            ids.append(fact_id)

    return ids


def _parse_restore_attached_file_metadata(
    attached_files_block: str,
    entries: list[dict],
    attached_file_ids: list[str],
) -> list[dict]:
    metadata = {}

    for entry in reversed(entries):
        attachments = entry.get("attachments", [])
        if not isinstance(attachments, list):
            continue
        for attachment in attachments:
            if not isinstance(attachment, dict):
                continue
            file_id = str(attachment.get("id", "") or "").strip()
            if not file_id or file_id not in attached_file_ids:
                continue
            name = str(attachment.get("name", "") or "").strip()
            metadata.setdefault(file_id, {
                "id": file_id,
                "title": name or file_id,
            })

    for line in str(attached_files_block or "").splitlines():
        match = ATTACHED_FILE_ID_RE.search(line)
        if match is None:
            continue
        file_id = match.group("id").strip()
        if file_id not in attached_file_ids or file_id in metadata:
            continue
        title = line[:match.start()].strip().lstrip("-").strip()
        metadata[file_id] = {
            "id": file_id,
            "title": title or file_id,
        }

    return [
        metadata.get(file_id, {"id": file_id, "title": file_id})
        for file_id in attached_file_ids
    ]


def _parse_restore_delayed_memory_metadata(
    context_text: str,
    loaded_memory_ids: list[str],
) -> list[dict]:
    metadata = {}
    source = str(context_text or "")
    pattern = re.compile(
        BLOCK_RE_TEMPLATE.format(name=re.escape("LOADED_DELAYED_MEMORY")),
        re.IGNORECASE,
    )

    for match in pattern.finditer(source):
        body = match.group("body").strip()
        report = {}
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                report = parsed
        except (TypeError, ValueError):
            pass

        report_id = str(report.get("id", "") or "").strip()
        title = str(report.get("title", "") or "").strip()

        if not report_id:
            id_match = re.search(
                r'"id"\s*:\s*"(?P<value>[^"\n]+)"',
                body,
                re.IGNORECASE,
            )
            if id_match is not None:
                report_id = id_match.group("value").strip()

        if not title:
            title_match = re.search(
                r'"title"\s*:\s*"(?P<value>[^"\n]+)"',
                body,
                re.IGNORECASE,
            )
            if title_match is not None:
                title = title_match.group("value").strip()

        if report_id and report_id in loaded_memory_ids:
            metadata[report_id] = {
                "id": report_id,
                "title": title or report_id,
            }

    inventory = _extract_block(source, "DELAYED_MEMORY")
    for report_id in loaded_memory_ids:
        if report_id in metadata:
            continue
        title = ""
        inventory_match = re.search(
            rf"(?m)^\s*{re.escape(report_id)}_(?P<title>.+?)(?:\s+\([^\n)]*\))?\s*$",
            inventory,
            re.IGNORECASE,
        )
        if inventory_match is not None:
            title = inventory_match.group("title").strip().replace("_", " ")
        metadata[report_id] = {
            "id": report_id,
            "title": title or report_id,
        }

    return [metadata[report_id] for report_id in loaded_memory_ids]


def _tool_result_detail(name: str, payload: dict) -> tuple[str, str]:
    action_name = str(name or "").strip().upper()
    label = ACTION_LABELS.get(
        action_name,
        action_name.replace("_", " ").title(),
    )
    detail = ""

    for key in ("title", "message", "path", "id"):
        value = str(payload.get(key, "") or "").strip()
        if value:
            detail = value
            break

    report = payload.get("report")
    if not detail and isinstance(report, dict):
        detail = str(report.get("title", "") or report.get("id", "") or "").strip()

    return label, detail


def _build_session_actions(context_text: str, fallback_created_at: float) -> list[dict]:
    items = []
    offset = 0.0

    for match in TOOL_RESULT_RE.finditer(str(context_text or "")):
        raw_payload = match.group("body").strip()
        start = raw_payload.find("{")
        end = raw_payload.rfind("}")
        if start < 0 or end < start:
            continue
        try:
            payload = json.loads(raw_payload[start:end + 1])
        except (TypeError, ValueError):
            payload = {}

        if not isinstance(payload, dict):
            payload = {}

        label, detail = _tool_result_detail(match.group("name"), payload)

        if not detail:
            for key in ("title", "message", "path", "id"):
                detail_match = re.search(
                    rf'"{key}"\s*:\s*"(?P<value>[^"\n]+)"',
                    raw_payload,
                    re.IGNORECASE,
                )
                if detail_match is not None:
                    detail = detail_match.group("value").strip()
                    if detail:
                        break

        created_at = fallback_created_at + offset
        offset += 0.001

        report = payload.get("report")
        if isinstance(report, dict):
            report_timestamp = _parse_iso_timestamp(
                report.get("created_time") or report.get("created_date")
            )
            if report_timestamp:
                created_at = report_timestamp
        else:
            timestamp_match = re.search(
                r'"created_(?:time|date)"\s*:\s*"(?P<value>[^"\n]+)"',
                raw_payload,
                re.IGNORECASE,
            )
            if timestamp_match is not None:
                report_timestamp = _parse_iso_timestamp(
                    timestamp_match.group("value")
                )
                if report_timestamp:
                    created_at = report_timestamp

        part = {"text": label}
        if detail:
            part["detail"] = detail

        items.append({
            "text": label if not detail else f"{label} - {detail}",
            "created_at": created_at,
            "parts": [part],
        })

    return items


def _parse_trusted_values(context_text: str) -> dict:
    values = {}
    source = str(context_text or "")

    for name in (
        "RUNTIME_MODE",
        "SERVICE_MODEL_UID",
        "BRAIN_MODEL_UID",
        "CURRENT_CONTEXT_WINDOW",
        "CURRENT_JIN_COLOR",
        "CURRENT_JIN_SIZE",
        "CURRENT_JIN_POSITION",
        "CURRENT_JIN_SPEED",
        "CURRENT_WINDOW_SIZE",
        "CURRENT_USER_DATETIME",
    ):
        match = re.search(
            rf"<{name}>(?P<value>[\s\S]*?)</{name}>",
            source,
            re.IGNORECASE,
        )
        if match is not None:
            values[name] = match.group("value").strip()

    return values


def _parse_loaded_delayed_reports(context_text: str) -> dict:
    reports = {}
    source = str(context_text or "")
    pattern = re.compile(
        BLOCK_RE_TEMPLATE.format(name=re.escape("LOADED_DELAYED_MEMORY")),
        re.IGNORECASE,
    )

    for block_match in pattern.finditer(source):
        body = block_match.group("body").strip()
        if not body:
            continue

        try:
            report = json.loads(body)
        except (TypeError, ValueError):
            report = {}

            for key in (
                "id",
                "title",
                "summary",
            ):
                match = re.search(
                    rf'"{key}"\s*:\s*"(?P<value>[^"\n]*)"',
                    body,
                    re.IGNORECASE,
                )
                if match is not None:
                    report[key] = match.group("value").strip()

            tags_match = re.search(
                r'"tags"\s*:\s*\[(?P<value>[\s\S]*?)\]',
                body,
                re.IGNORECASE,
            )
            if tags_match is not None:
                report["tags"] = re.findall(
                    r'"([^"\n]+)"',
                    tags_match.group("value"),
                )

            body_match = re.search(
                r'"body"\s*:\s*"(?P<value>[\s\S]*?)"\s*(?:,\s*"(?:pinned|anchor_fact_ids|facts_ids|attachments_ids|created_session_id|created_time|created_date|loaded_times|load_streak|last_loaded_date|last_loaded_session_id|all_loaded_session_ids|id)"|\n\s*})',
                body,
                re.IGNORECASE,
            )
            if body_match is not None:
                report["body"] = body_match.group("value").strip()

        if not isinstance(report, dict) or not report:
            continue

        report_id = str(
            report.get("id", "")
            or report.get("_storage_key", "")
            or ""
        ).strip()
        if not report_id:
            continue

        clean_report = dict(report)
        clean_report.pop("id", None)
        clean_report.pop("_storage_key", None)
        reports[report_id] = clean_report

    return reports


def _parse_active_memory_records(runtime_memory: str) -> list[str]:
    records = []
    for line in str(runtime_memory or "").splitlines():
        if re.match(
            r"^\s*active_memory(?:_\d+)?\s*:",
            line,
            re.IGNORECASE,
        ):
            normalized = line.strip()
            if normalized and normalized not in records:
                records.append(normalized)
    return records


def _parse_jin_size(value: str):
    numbers = re.findall(
        r"(?<![a-zA-Z0-9])(?P<number>\d{2,4})(?:px)?",
        str(value or ""),
        re.IGNORECASE,
    )
    if not numbers:
        return ""
    width = int(numbers[0])
    height = int(numbers[1]) if len(numbers) > 1 else width
    if width <= 0 or height <= 0:
        return ""
    return {
        "width": width,
        "height": height,
    }


def build_archived_session_restore_payload(
    session_id: str,
    *,
    root: Path | str | None = None,
) -> dict | None:
    root_path = Path(root if root is not None else CHAT_LOG_ROOT)
    session_directory = _find_session_directory(session_id, root_path)
    if session_directory is None:
        return None

    dialog_paths = sorted(
        (path for path in session_directory.glob("*.jsonl") if path.is_file()),
        key=lambda path: path.name,
    )
    if not dialog_paths:
        return None

    dialog_path = dialog_paths[-1]
    entries = _load_dialog(dialog_path)
    if not entries:
        return None

    context_path = dialog_path.with_suffix(".txt")
    try:
        context_text = context_path.read_text(
            encoding="utf-8",
            errors="replace",
        ) if context_path.is_file() else ""
    except OSError:
        context_text = ""

    reasoning_by_turn_id = _read_reasoning(session_directory, entries)
    visible_entries = []
    for entry in entries:
        turn_id = str(entry.get("turn_id", "") or "").strip()
        has_text = bool(str(entry.get("text", "") or "").strip())
        has_attachments = bool(entry.get("attachments", []) or [])
        has_reasoning = bool(
            str(reasoning_by_turn_id.get(turn_id, "") or "").strip()
        )
        if has_text or has_attachments or has_reasoning:
            visible_entries.append(entry)

    if not visible_entries:
        return None

    trusted_values = _parse_trusted_values(context_text)
    previous_runtime_state = _extract_block(context_text, "PREVIOUS_RUNTIME_STATE")
    attached_files_block = _extract_block(context_text, "ATTACHED_FILES")

    last_entry = visible_entries[-1]
    loaded_memory_ids = [
        str(item or "").strip()
        for item in last_entry.get("delayed_memory_ids", []) or []
        if str(item or "").strip()
    ]
    attached_file_ids = list(dict.fromkeys(
        match.group("id").strip()
        for match in ATTACHED_FILE_ID_RE.finditer(attached_files_block)
        if match.group("id").strip()
    ))

    jin_entries = [
        entry for entry in visible_entries
        if str(entry.get("role", "")).strip().lower()
        in {"jin", "assistant", "brain", "service"}
    ]
    user_entries = [
        entry for entry in visible_entries
        if str(entry.get("role", "")).strip().lower() == "user"
    ]

    latest_reasoning = ""
    latest_jin_text = ""
    for entry in reversed(jin_entries):
        if not latest_jin_text:
            latest_jin_text = str(entry.get("text", "") or "").strip()
        turn_id = str(entry.get("turn_id", "") or "").strip()
        latest_reasoning = reasoning_by_turn_id.get(turn_id, "")
        if latest_reasoning:
            break

    restore_reasoning_dump = _build_restore_reasoning_dump(
        visible_entries,
        reasoning_by_turn_id,
    )
    restore_l4_fact_ids = _extract_l4_fact_ids(
        latest_reasoning,
        latest_jin_text,
    )
    restore_delayed_memory_metadata = (
        _parse_restore_delayed_memory_metadata(
            context_text,
            loaded_memory_ids,
        )
    )
    restore_attached_file_metadata = (
        _parse_restore_attached_file_metadata(
            attached_files_block,
            entries,
            attached_file_ids,
        )
    )

    max_turn = 0
    for entry in entries:
        try:
            max_turn = max(max_turn, int(entry.get("turn", 0) or 0))
        except (TypeError, ValueError):
            pass

    fallback_created_at = _entry_timestamp(visible_entries[0]) or dialog_path.stat().st_mtime
    session_actions = _build_session_actions(context_text, fallback_created_at)

    ui_messages = []
    for entry in visible_entries:
        role = str(entry.get("role", "")).strip().lower()
        if role not in {"user", "jin", "assistant", "brain", "service"}:
            continue
        turn_id = str(entry.get("turn_id", "") or "").strip()
        ui_messages.append({
            "role": role,
            "turn": entry.get("turn", 0),
            "turn_id": turn_id,
            "ts": entry.get("ts", ""),
            "text": str(entry.get("text", "") or ""),
            "attachments": entry.get("attachments", []) or [],
            "delayed_memory_ids": entry.get("delayed_memory_ids", []) or [],
            "active_memory_ids": entry.get("active_memory_ids", []) or [],
            "reasoning": reasoning_by_turn_id.get(turn_id, ""),
        })

    runtime_mode = trusted_values.get("RUNTIME_MODE", "BRAIN").strip().upper()
    if runtime_mode not in {"BRAIN", "SERVICE"}:
        runtime_mode = "BRAIN"

    return {
        "ok": True,
        "source_session_id": _clean_session_id(session_id),
        "source_session_date": session_directory.parent.name,
        "dialog_file": dialog_path.name,
        "context_file": context_path.name if context_path.is_file() else "",
        "messages": ui_messages,
        "dialog_context": _build_restored_dialog_context(
            visible_entries,
            _clean_session_id(session_id),
        ),
        "recent_turns": _build_recent_turns(visible_entries),
        "previous_reasoning": latest_reasoning,
        "restore_reasoning_dump": restore_reasoning_dump,
        "restore_l4_fact_ids": restore_l4_fact_ids,
        "restore_delayed_memory_metadata": restore_delayed_memory_metadata,
        "restore_attached_file_metadata": restore_attached_file_metadata,
        "runtime_memory": previous_runtime_state,
        "runtime_memory_updates": len(jin_entries),
        "loaded_memory_ids": loaded_memory_ids,
        "delayed_memory_reports": _parse_loaded_delayed_reports(context_text),
        "active_memory_records": _parse_active_memory_records(previous_runtime_state),
        "attached_file_ids": attached_file_ids,
        "session_actions": session_actions,
        "runtime_turn_counter": max_turn,
        "turn_number": max_turn,
        "user_message_count": len(user_entries),
        "assistant_message_count": len(jin_entries),
        "current_jin_color": trusted_values.get("CURRENT_JIN_COLOR", ""),
        "current_jin_size": _parse_jin_size(
            trusted_values.get("CURRENT_JIN_SIZE", "")
        ),
        "current_jin_position": normalize_jin_position_dict(
            trusted_values.get("CURRENT_JIN_POSITION", "")
        ),
        "current_jin_speed": (
            normalize_jin_speed_value(
                trusted_values.get("CURRENT_JIN_SPEED", "")
            )
            or 900
        ),
        "current_window_size": _parse_jin_size(
            trusted_values.get("CURRENT_WINDOW_SIZE", "")
        ),
        "current_jin_collapsed": bool(
            str(trusted_values.get("CURRENT_JIN_SIZE", "")).strip()
            or str(trusted_values.get("CURRENT_JIN_POSITION", "")).strip()
        ),
        "runtime_mode": runtime_mode,
        "archived_context": context_text,
    }
