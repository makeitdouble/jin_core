"""Read-only historical evidence for long-term facts."""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

from runtime.fact_sources import normalize_sources, source_key
from runtime.LT_memory_utils import normalize_lt_id as normalize_fact_id
from utils.chat_log import chat_log_root_for_context


_LEGACY_FRAME_MAX_DELTA_SECONDS = 30 * 60
_LEGACY_FRAME_TIME_ONLY_MAX_DELTA_SECONDS = 2 * 60


def _read_session_entries(root: Path, session: str) -> list[dict]:
    entries = []
    seen = set()
    for path in sorted(root.glob(f"*/{session}/*.jsonl")):
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(entry, dict) or entry.get("session_id") != session:
                        continue
                    if entry.get("role") not in {"user", "jin"}:
                        continue
                    identity = (entry.get("turn_id"), entry.get("role"), entry.get("ts"), entry.get("text"))
                    if identity in seen:
                        continue
                    seen.add(identity)
                    entries.append(entry)
        except (OSError, UnicodeError):
            continue
    entries.sort(key=lambda row: str(row.get("ts") or ""))
    return entries


def _read_source(root: Path, source: dict) -> dict:
    episode = {**source, "source_id": source_key(source)}
    session = source["session_id"]
    matches = []
    # IDs have been validated before reaching path/glob operations.
    for path in sorted(root.glob(f"*/{session}/frames/*.txt")) if source.get("runtime_snapshot_id") else []:
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            continue
        header, separator, frame = text.partition("\n--- FRAME ---\n")
        metadata = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
        if (separator and metadata.get("session_id") == session
                and metadata.get("runtime_memory_id") == source["runtime_snapshot_id"]):
            matches.append((metadata, frame))
    if not matches and source.get("turn_id"):
        matches = [({"source_turn_ids": json.dumps([source["turn_id"]]),
                     "source_turns_complete": "true"}, None)]
    if not matches:
        return {**episode, "error": "source_unavailable"}
    # Conflicting archives are not resolved by picking the newest file.
    if any(match != matches[0] for match in matches[1:]):
        return {**episode, "error": "ambiguous_source_archive"}
    metadata, frame = matches[0]
    if frame is not None:
        episode["frame"] = frame
    else:
        episode["frame_status"] = "not_applicable_direct_turn_source"
    episode["captured_at"] = metadata.get("captured_at", "")
    try:
        turns = json.loads(metadata.get("source_turn_ids", "[]"))
        complete = json.loads(metadata.get("source_turns_complete", "false")) is True
    except (ValueError, TypeError):
        turns, complete = [], False
    turns = list(dict.fromkeys(str(t) for t in turns if t)) if isinstance(turns, list) else []

    entries = _read_session_entries(root, session)
    # Old FRAME archives predate source_turn_ids but still record the numeric
    # turn that produced the snapshot. Resolve that exact turn when possible.
    if (not complete or not turns) and frame is not None and str(metadata.get("turn") or "").strip():
        legacy_turn = str(metadata.get("turn") or "").strip()
        inferred = list(dict.fromkeys(
            str(row.get("turn_id") or "").strip()
            for row in entries
            if row.get("role") == "user"
            and str(row.get("turn") or "").strip() == legacy_turn
            and str(row.get("turn_id") or "").strip()
        ))
        if len(inferred) == 1:
            turns = inferred
            complete = True
            episode["legacy_turn_anchor_inferred"] = True

    episode["source_turn_ids"] = turns
    if not complete or not turns:
        episode["anchor_known"] = False
        episode["scope"] = "frame_episode"
        episode["dialog_status"] = "exact_turn_link_not_saved"
        episode["messages"] = []
        return episode

    anchors = [i for i, row in enumerate(entries)
               if row.get("turn_id") in turns and row.get("role") == "user"]
    episode["anchor_known"] = len(turns) == 1 and bool(anchors)
    episode["scope"] = "turn" if len(turns) == 1 else "frame_episode"

    # Explicit UPDATE_LT_FACTS actions emitted by the hidden session-restore
    # tick used to persist that synthetic turn id as provenance. Such a turn
    # can have a durable JIN row but no USER row. Do not report the whole source
    # as missing when exact same-turn dialogue still exists; expose only those
    # rows, with no false anchor. New writes are fixed at ingestion time to
    # point at the predecessor USER turn, while this keeps already-saved facts
    # recallable.
    if not anchors and frame is None and source.get("turn_id"):
        exact_turn_rows = [
            i for i, row in enumerate(entries)
            if row.get("turn_id") in turns
        ]
        if exact_turn_rows:
            episode["messages"] = [
                {"message_id": f"{session}/{i}", "turn_id": entries[i].get("turn_id"),
                 "role": entries[i]["role"], "timestamp": entries[i].get("ts"),
                 "text": entries[i].get("text", ""), "anchor": False}
                for i in exact_turn_rows
            ]
            found_turns = {entries[i].get("turn_id") for i in exact_turn_rows}
            episode["missing_turn_ids"] = [turn for turn in turns if turn not in found_turns]
            episode["dialog_status"] = (
                "available_without_user_anchor"
                if not episode["missing_turn_ids"]
                else "source_unavailable"
            )
            episode["user_anchor_missing"] = True
            return episode

    selected = sorted({j for i in anchors for j in range(max(0, i-1), min(len(entries), i+2))})
    episode["messages"] = [
        {"message_id": f"{session}/{i}", "turn_id": entries[i].get("turn_id"),
         "role": entries[i]["role"], "timestamp": entries[i].get("ts"),
         "text": entries[i].get("text", ""),
         "anchor": episode["anchor_known"] and i in anchors}
        for i in selected
    ]
    found_turns = {entries[i].get("turn_id") for i in anchors}
    episode["missing_turn_ids"] = [turn for turn in turns if turn not in found_turns]
    episode["dialog_status"] = "available" if not episode["missing_turn_ids"] else "source_unavailable"
    if not episode.get("frame") and not episode["messages"]:
        episode["error"] = "source_unavailable"
    return episode


def _parse_timestamp(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed


def _fact_timestamps(fact: dict) -> list[datetime]:
    result = []
    for field in ("updated_at", "created_at"):
        timestamp = _parse_timestamp(fact.get(field))
        if timestamp is not None and timestamp not in result:
            result.append(timestamp)
    return result


def _legacy_tokens(value) -> set[str]:
    return {
        token
        for token in re.findall(r"[\w-]+", str(value or "").casefold().replace("_", " "))
        if len(token) >= 4
    }


def _candidate_day_paths(root: Path, timestamp: datetime | None, pattern: str):
    if timestamp is None:
        yield from root.glob(f"*/{pattern}")
        return
    for offset in (-1, 0, 1):
        day = (timestamp + timedelta(days=offset)).date().isoformat()
        yield from root.glob(f"{day}/{pattern}")


def _infer_legacy_action_sources(root: Path, fact: dict) -> list[dict]:
    """Recover exact legacy UPDATE_LT_FACTS turns from persisted runtime results."""
    fact_id = normalize_fact_id(fact.get("id"))
    if not fact_id:
        return []
    fact_times = _fact_timestamps(fact)
    found = []
    seen = set()
    paths = set()
    if fact_times:
        for fact_time in fact_times:
            paths.update(_candidate_day_paths(root, fact_time, "*/*.jsonl"))
    else:
        paths.update(_candidate_day_paths(root, None, "*/*.jsonl"))
    for path in sorted(paths):
        try:
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if fact_id not in line:
                        continue
                    try:
                        entry = json.loads(line)
                    except ValueError:
                        continue
                    if not isinstance(entry, dict) or entry.get("event") != "runtime_tool_result":
                        continue
                    payload = entry.get("payload") if isinstance(entry.get("payload"), dict) else {}
                    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
                    if payload.get("kind") != "lt" or normalize_fact_id(result.get("fact_id")) != fact_id:
                        continue
                    session = str(entry.get("session_id") or "").strip()
                    turn = str(entry.get("turn_id") or "").strip()
                    source = normalize_sources([{"session_id": session, "turn_id": turn}])
                    if not source:
                        continue
                    identity = source_key(source[0])
                    if identity not in seen:
                        seen.add(identity)
                        found.append((str(entry.get("ts") or ""), source[0]))
        except (OSError, UnicodeError):
            continue
    found.sort(key=lambda item: item[0])
    return [source for _timestamp, source in found]


def _infer_legacy_frame_sources(root: Path, fact: dict) -> list[dict]:
    """Best-effort bridge for facts created before backend-owned provenance."""
    fact_times = _fact_timestamps(fact)
    if not fact_times:
        return []

    fact_tokens = _legacy_tokens(f"{fact.get('key', '')} {fact.get('value', '')}")
    inferred = []
    seen = set()
    for fact_time in fact_times:
        candidates = []
        for path in _candidate_day_paths(root, fact_time, "*/frames/*.txt"):
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            header, separator, frame = text.partition("\n--- FRAME ---\n")
            if not separator or not frame.strip() or frame.strip() == "This session has just begun.":
                continue
            metadata = dict(line.split(": ", 1) for line in header.splitlines() if ": " in line)
            session = str(metadata.get("session_id") or "").strip()
            snapshot = str(metadata.get("runtime_memory_id") or "").strip()
            frame_time = _parse_timestamp(metadata.get("created_at") or metadata.get("captured_at"))
            if not session or not snapshot or frame_time is None:
                continue
            delta = abs((frame_time - fact_time).total_seconds())
            if delta > _LEGACY_FRAME_MAX_DELTA_SECONDS:
                continue
            overlap = len(fact_tokens & _legacy_tokens(frame))
            if overlap < 2 and delta > _LEGACY_FRAME_TIME_ONLY_MAX_DELTA_SECONDS:
                continue
            captured_time = _parse_timestamp(metadata.get("captured_at")) or frame_time
            archive_lag = abs((captured_time - frame_time).total_seconds())
            candidates.append((overlap, delta, archive_lag, session, snapshot))

        if not candidates:
            continue
        candidates.sort(key=lambda item: (-item[0], item[1], item[2], item[3], item[4]))
        best = candidates[0]
        # Do not invent a source when two different snapshots are equally plausible.
        if len(candidates) > 1 and candidates[1][:3] == best[:3] and candidates[1][4] != best[4]:
            continue
        source = {"session_id": best[3], "runtime_snapshot_id": best[4]}
        identity = source_key(source)
        if identity not in seen:
            seen.add(identity)
            inferred.append(source)
    return inferred


def recall_fact_context(context, fact: dict, *, root: Path | None = None) -> dict:
    fact_id = normalize_fact_id(fact.get("id"))
    result = {"ok": False, "fact_id": fact_id, "value": str(fact.get("value") or "")}
    if not fact_id:
        return {**result, "error": "invalid_fact_id"}
    root = Path(root) if root is not None else chat_log_root_for_context(context)
    sources = normalize_sources(fact.get("sources"))
    legacy_inferred = False
    if not sources:
        sources = _infer_legacy_action_sources(root, fact)
        if not sources:
            sources = _infer_legacy_frame_sources(root, fact)
        legacy_inferred = bool(sources)
        if not sources:
            return {**result, "error": "source_not_saved"}
    episodes = [_read_source(root, source) for source in sources]
    return {**result, "ok": any("error" not in episode for episode in episodes),
            "sources": episodes,
            **({"legacy_source_inferred": True} if legacy_inferred else {}),
            **({"error": "source_unavailable"} if all("error" in e for e in episodes) else {})}
