from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
from tempfile import NamedTemporaryFile

from runtime.anonymous_mode import is_anonymous_session_id
from runtime.LT_memory_utils import (
    clone_lt_store,
    collect_lt_reasoning_fact_ids,
    lt_timestamp_sort_value,
    normalize_lt_store,
    normalize_lt_text,
)
from utils.actions.save_delayed_memory_utils import normalize_long_term_fact_ids
from utils.chat_log import CHAT_LOG_ROOT
from utils.long_term_facts_file_store import LONG_TERM_FACTS_ROOT


LT_LOG_MENTION_BACKFILL_VERSION = 1
LT_LOG_MENTION_BACKFILL_WINDOW_DAYS = 7
LT_LOG_MENTION_BACKFILL_STATE_FILENAME = ".lt_mention_log_backfill_v1.json"


def _parse_datetime(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _iso_utc(value: datetime) -> str:
    return (
        value.astimezone(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name = ""
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=".lt_mention_backfill_",
            suffix=".tmp",
            dir=path.parent,
            delete=False,
        ) as temporary_file:
            json.dump(payload, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_name = temporary_file.name
        os.replace(temporary_name, path)
    finally:
        if temporary_name:
            temporary_path = Path(temporary_name)
            if temporary_path.exists():
                temporary_path.unlink()


def load_or_create_lt_log_mention_backfill_state(
    *,
    facts_root: Path | str = LONG_TERM_FACTS_ROOT,
    now: datetime | None = None,
) -> dict:
    """Freeze one historical seven-day window; live tracking owns newer turns."""

    path = Path(facts_root) / LT_LOG_MENTION_BACKFILL_STATE_FILENAME
    if path.is_file():
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raw = None
        if isinstance(raw, dict):
            activated = _parse_datetime(raw.get("activated_at"))
            fallback = _parse_datetime(raw.get("fallback_at"))
            if (
                int(raw.get("version") or 0) == LT_LOG_MENTION_BACKFILL_VERSION
                and activated is not None
                and fallback is not None
            ):
                return {
                    "version": LT_LOG_MENTION_BACKFILL_VERSION,
                    "activated_at": _iso_utc(activated),
                    "fallback_at": _iso_utc(fallback),
                }

    activated = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    activated = activated.replace(microsecond=0)
    state = {
        "version": LT_LOG_MENTION_BACKFILL_VERSION,
        "activated_at": _iso_utc(activated),
        "fallback_at": _iso_utc(
            activated - timedelta(days=LT_LOG_MENTION_BACKFILL_WINDOW_DAYS)
        ),
    }
    _write_json_atomic(path, state)
    return state


def _record_latest_mentions(
    latest_by_fact_id: dict[str, str],
    text: str,
    timestamp: datetime,
) -> None:
    timestamp_iso = _iso_utc(timestamp)
    for fact_id in collect_lt_reasoning_fact_ids(text):
        if lt_timestamp_sort_value(timestamp_iso) > lt_timestamp_sort_value(
            latest_by_fact_id.get(fact_id)
        ):
            latest_by_fact_id[fact_id] = timestamp_iso


def scan_lt_log_fact_mentions(
    *,
    log_root: Path | str = CHAT_LOG_ROOT,
    fallback_at: str,
    activated_at: str,
) -> dict:
    """Scan only JIN replies and reasoning; prompt/context dumps are false positives."""

    root = Path(log_root)
    start = _parse_datetime(fallback_at)
    end = _parse_datetime(activated_at)
    if start is None or end is None:
        raise ValueError("invalid L-T mention backfill time window")

    result = {
        "latest_by_fact_id": {},
        "jsonl_files_scanned": 0,
        "reasoning_files_scanned": 0,
        "jin_entries_scanned": 0,
    }
    if not root.is_dir():
        return result

    allowed_dates = {
        (start + timedelta(days=offset)).date().isoformat()
        for offset in range((end.date() - start.date()).days + 1)
    }

    for date_directory in sorted(root.iterdir(), key=lambda item: item.name):
        if not date_directory.is_dir() or date_directory.name not in allowed_dates:
            continue

        for session_directory in sorted(
            date_directory.iterdir(),
            key=lambda item: item.name,
        ):
            if (
                not session_directory.is_dir()
                or is_anonymous_session_id(session_directory.name)
            ):
                continue

            for jsonl_path in sorted(session_directory.glob("*.jsonl")):
                result["jsonl_files_scanned"] += 1
                try:
                    lines = jsonl_path.read_text(
                        encoding="utf-8", errors="replace"
                    ).splitlines()
                except OSError:
                    continue

                for line in lines:
                    try:
                        entry = json.loads(line)
                    except (TypeError, json.JSONDecodeError):
                        continue
                    if not isinstance(entry, dict):
                        continue
                    if str(entry.get("role") or "").strip().casefold() != "jin":
                        continue
                    timestamp = _parse_datetime(entry.get("ts"))
                    if timestamp is None or timestamp < start or timestamp > end:
                        continue
                    result["jin_entries_scanned"] += 1
                    _record_latest_mentions(
                        result["latest_by_fact_id"],
                        str(entry.get("text") or ""),
                        timestamp,
                    )

            # Reasoning has its own captured_at, so interrupted/empty visible
            # turns are recoverable without joining files back to the dialogue.
            for reasoning_path in sorted(
                session_directory.glob("reasoning/*.txt")
            ):
                try:
                    reasoning_text = reasoning_path.read_text(
                        encoding="utf-8", errors="replace"
                    )
                except OSError:
                    continue
                captured_at = next(
                    (
                        line.split(":", 1)[1].strip()
                        for line in reasoning_text.splitlines()[:8]
                        if line.casefold().startswith("captured_at:")
                    ),
                    "",
                )
                timestamp = _parse_datetime(captured_at)
                if timestamp is None or timestamp < start or timestamp > end:
                    continue
                result["reasoning_files_scanned"] += 1
                _record_latest_mentions(
                    result["latest_by_fact_id"], reasoning_text, timestamp
                )

    return result


def apply_lt_log_mention_backfill_to_store(
    store,
    *,
    latest_by_fact_id: dict[str, str],
    fallback_at: str,
    activated_at: str,
    now: str,
) -> tuple[dict, dict]:
    """Repair legacy dates while never rewinding a post-activation live mention."""

    current = clone_lt_store(normalize_lt_store(store, now=now))
    activation_sort = lt_timestamp_sort_value(activated_at)
    facts_by_reference: dict[str, dict] = {}

    for fact in current.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        fact_id = str(fact.get("id") or "").strip().upper()
        if not fact_id:
            continue
        for reference_id in normalize_long_term_fact_ids(
            [fact_id, *(fact.get("source_fact_ids") or [])]
        ):
            facts_by_reference[reference_id] = fact

    latest_by_current_fact_id: dict[str, str] = {}
    for reference_id, timestamp in (latest_by_fact_id or {}).items():
        fact = facts_by_reference.get(str(reference_id or "").strip().upper())
        if not fact:
            continue
        fact_id = str(fact.get("id") or "").strip().upper()
        if lt_timestamp_sort_value(timestamp) > lt_timestamp_sort_value(
            latest_by_current_fact_id.get(fact_id)
        ):
            latest_by_current_fact_id[fact_id] = normalize_lt_text(timestamp)

    change = {
        "changed": False,
        "kind": "log_mention_backfill",
        "changed_fact_ids": [],
        "mentioned_fact_ids": [],
        "fallback_fact_ids": [],
        "skipped_live_fact_ids": [],
    }

    for fact in current.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        fact_id = str(fact.get("id") or "").strip().upper()
        if not fact_id:
            continue
        if (
            activation_sort
            and (
                lt_timestamp_sort_value(fact.get("created_at")) >= activation_sort
                or lt_timestamp_sort_value(fact.get("last_mentioned_at"))
                >= activation_sort
            )
        ):
            change["skipped_live_fact_ids"].append(fact_id)
            continue

        target = latest_by_current_fact_id.get(fact_id) or normalize_lt_text(fallback_at)
        if not target or normalize_lt_text(fact.get("last_mentioned_at")) == target:
            continue

        fact["last_mentioned_at"] = target
        change["changed_fact_ids"].append(fact_id)
        bucket = (
            "mentioned_fact_ids"
            if fact_id in latest_by_current_fact_id
            else "fallback_fact_ids"
        )
        change[bucket].append(fact_id)

    if change["changed_fact_ids"]:
        change["changed"] = True
        current["revision"] = max(0, int(current.get("revision") or 0)) + 1
        current["updated_at"] = normalize_lt_text(now)
        current = normalize_lt_store(current, now=now)

    return current, change


async def run_lt_log_mention_backfill(context) -> dict:
    if bool(getattr(context, "runtime_persistent_writes_restricted", False)):
        return {"changed": False, "skipped": "restricted_writes"}

    # Keep the fallback module one-way: LT_memory does not import us back.
    from runtime.LT_memory import (
        emit_lt_memory_update,
        ensure_runtime_lt_state,
        get_runtime_lt_file_store_root,
        persist_runtime_lt_file_store,
    )

    facts_root = get_runtime_lt_file_store_root(context) or LONG_TERM_FACTS_ROOT
    state = await asyncio.to_thread(
        load_or_create_lt_log_mention_backfill_state, facts_root=facts_root
    )
    scan = await asyncio.to_thread(
        scan_lt_log_fact_mentions,
        log_root=CHAT_LOG_ROOT,
        fallback_at=state["fallback_at"],
        activated_at=state["activated_at"],
    )

    # Re-read only after disk scanning so a concurrent new live mention wins.
    current_store = clone_lt_store(ensure_runtime_lt_state(context))
    if not (current_store.get("facts") or []):
        return {"changed": False, "skipped": "no_facts", **scan}

    now = _iso_utc(datetime.now(timezone.utc))
    repaired_store, change = apply_lt_log_mention_backfill_to_store(
        current_store,
        latest_by_fact_id=scan["latest_by_fact_id"],
        fallback_at=state["fallback_at"],
        activated_at=state["activated_at"],
        now=now,
    )
    if change["changed"]:
        context.runtime_long_term_memory_store = repaired_store
        await asyncio.to_thread(
            persist_runtime_lt_file_store, context, repaired_store
        )
        await emit_lt_memory_update(
            context, change={**change, "source": "historical_logs"}
        )

    return {
        **change,
        "state": state,
        "jsonl_files_scanned": scan["jsonl_files_scanned"],
        "reasoning_files_scanned": scan["reasoning_files_scanned"],
        "jin_entries_scanned": scan["jin_entries_scanned"],
    }


def schedule_lt_log_mention_backfill(context):
    """Run once per websocket bootstrap and never hold up L-T store sync."""

    if bool(getattr(context, "runtime_persistent_writes_restricted", False)):
        return None
    existing = getattr(context, "runtime_lt_log_mention_backfill_task", None)
    if existing is not None:
        return existing

    async def _runner():
        try:
            return await run_lt_log_mention_backfill(context)
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log_runtime = getattr(getattr(context, "logger", None), "log_runtime", None)
            if callable(log_runtime):
                try:
                    await log_runtime(
                        "[MEMORY:L-T] historical mention backfill failed: " + str(error)
                    )
                except Exception:
                    pass
            return {"changed": False, "error": str(error)}

    task = asyncio.create_task(_runner())
    context.runtime_lt_log_mention_backfill_task = task
    return task
