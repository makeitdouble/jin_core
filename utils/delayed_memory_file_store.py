from __future__ import annotations

import json
import os
import re
from pathlib import Path
from tempfile import NamedTemporaryFile

from utils.actions.delayed_memory_utils import (
    is_delayed_memory_report_id,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DELAYED_MEMORY_ROOT = PROJECT_ROOT / "memory" / "delayed"
MAX_DELAYED_MEMORY_TITLE_CHARS = 500
MAX_DELAYED_MEMORY_SUMMARY_CHARS = 2000
MAX_DELAYED_MEMORY_BODY_CHARS = 12000
MAX_DELAYED_MEMORY_TAGS = 30
MAX_DELAYED_MEMORY_TAG_CHARS = 80
MAX_DELAYED_MEMORY_SESSION_ID_CHARS = 200
MAX_DELAYED_MEMORY_TIME_CHARS = 100


def _clean_text(
    value,
    *,
    limit: int,
) -> str:

    if value is None:
        return ""

    cleaned = str(value).replace(
        "\x00",
        "",
    ).strip()

    if len(cleaned) <= limit:
        return cleaned

    return cleaned[-limit:].strip()


def _clean_counter(value) -> int:

    try:
        return max(
            int(value or 0),
            0,
        )
    except (TypeError, ValueError):
        return 0


def _clean_session_ids(value) -> list[str]:

    source = value if isinstance(value, list) else []
    cleaned = []
    seen = set()

    for item in source:
        session_id = _clean_text(
            item,
            limit=MAX_DELAYED_MEMORY_SESSION_ID_CHARS,
        )

        if not session_id or session_id in seen:
            continue

        seen.add(session_id)
        cleaned.append(session_id)

    return cleaned


def _clean_tags(value) -> list[str]:

    source = (
        value
        if isinstance(value, list)
        else str(value or "").split(",")
    )
    tags = []

    for item in source:
        tag = _clean_text(
            item,
            limit=MAX_DELAYED_MEMORY_TAG_CHARS,
        )

        if not tag:
            continue

        tags.append(tag)

        if len(tags) >= MAX_DELAYED_MEMORY_TAGS:
            break

    return tags


def normalize_delayed_memory_report(
    report_id: str,
    report,
) -> tuple[str, dict] | None:

    if not isinstance(report, dict):
        return None

    normalized_id = str(
        report.get("id", "")
        or report_id
        or ""
    ).strip().casefold()

    if not is_delayed_memory_report_id(normalized_id):
        return None

    title = _clean_text(
        report.get("title", ""),
        limit=MAX_DELAYED_MEMORY_TITLE_CHARS,
    )

    if not title:
        return None

    created_time = _clean_text(
        report.get("created_time", "")
        or report.get("time", ""),
        limit=MAX_DELAYED_MEMORY_TIME_CHARS,
    )
    created_date = _clean_text(
        report.get("created_date", "")
        or created_time,
        limit=MAX_DELAYED_MEMORY_TIME_CHARS,
    )

    return normalized_id, {
        "title": title,
        "summary": _clean_text(
            report.get("summary", ""),
            limit=MAX_DELAYED_MEMORY_SUMMARY_CHARS,
        ),
        "tags": _clean_tags(
            report.get("tags", []),
        ),
        "body": _clean_text(
            report.get("body", ""),
            limit=MAX_DELAYED_MEMORY_BODY_CHARS,
        ),
        "created_session_id": _clean_text(
            report.get("created_session_id", "")
            or report.get("session", ""),
            limit=MAX_DELAYED_MEMORY_SESSION_ID_CHARS,
        ),
        "created_time": created_time,
        "created_date": created_date,
        "appended_times": _clean_counter(
            report.get("appended_times", 0),
        ),
        "append_streak": _clean_counter(
            report.get("append_streak", 0),
        ),
        "last_appended_date": _clean_text(
            report.get("last_appended_date", ""),
            limit=MAX_DELAYED_MEMORY_TIME_CHARS,
        ),
        "last_appended_session_id": _clean_text(
            report.get("last_appended_session_id", ""),
            limit=MAX_DELAYED_MEMORY_SESSION_ID_CHARS,
        ),
        "all_appended_session_ids": _clean_session_ids(
            report.get("all_appended_session_ids", []),
        ),
    }


def normalize_delayed_memory_reports(value) -> dict[str, dict]:

    if not isinstance(value, dict):
        return {}

    if (
        "title" in value
        and (
            "id" in value
            or "body" in value
            or "summary" in value
        )
    ):
        candidates = [
            (
                str(value.get("id", "") or ""),
                value,
            )
        ]
    else:
        candidates = list(value.items())

    reports = {}

    for key, report in candidates:
        normalized = normalize_delayed_memory_report(
            str(key or ""),
            report,
        )

        if normalized is None:
            continue

        report_id, clean_report = normalized

        if report_id in reports:
            continue

        reports[report_id] = clean_report

    return reports


def merge_delayed_memory_reports(
    primary,
    fallback,
) -> dict[str, dict]:

    fallback_reports = normalize_delayed_memory_reports(
        fallback,
    )
    primary_reports = normalize_delayed_memory_reports(
        primary,
    )

    return {
        **fallback_reports,
        **primary_reports,
    }


def delayed_memory_filename(
    report_id: str,
    title: str,
) -> str:

    normalized_id = str(report_id or "").strip().casefold()

    if not is_delayed_memory_report_id(normalized_id):
        raise ValueError("invalid delayed memory id")

    clean_title = re.sub(
        r"[^\w]+",
        "_",
        str(title or "").strip(),
        flags=re.UNICODE,
    )
    clean_title = re.sub(
        r"_+",
        "_",
        clean_title,
    ).strip("_")

    if not clean_title:
        clean_title = "delayed_memory"

    return f"{normalized_id}_{clean_title}.json"


def build_delayed_memory_file_payload(
    report_id: str,
    report: dict,
) -> dict:

    normalized = normalize_delayed_memory_report(
        report_id,
        report,
    )

    if normalized is None:
        raise ValueError("invalid delayed memory report")

    normalized_id, clean_report = normalized

    return {
        "title": clean_report["title"],
        "summary": clean_report["summary"],
        "time": clean_report["created_time"],
        "tags": clean_report["tags"],
        "id": normalized_id,
        "session": clean_report["created_session_id"],
        "created_date": clean_report["created_date"],
        "all_appended_session_ids": clean_report[
            "all_appended_session_ids"
        ],
        "body": clean_report["body"],
        "appended_times": clean_report["appended_times"],
        "append_streak": clean_report["append_streak"],
        "last_appended_date": clean_report[
            "last_appended_date"
        ],
        "last_appended_session_id": clean_report[
            "last_appended_session_id"
        ],
    }


def persist_delayed_memory_report(
    report_id: str,
    report: dict,
    *,
    root: Path | str = DELAYED_MEMORY_ROOT,
) -> Path:

    root_path = Path(root)
    payload = build_delayed_memory_file_payload(
        report_id,
        report,
    )
    filename = delayed_memory_filename(
        payload["id"],
        payload["title"],
    )
    destination = root_path / filename

    root_path.mkdir(
        parents=True,
        exist_ok=True,
    )

    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        indent=2,
    ) + "\n"

    temporary_name = ""

    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="\n",
            prefix=f".{payload['id']}_",
            suffix=".tmp",
            dir=root_path,
            delete=False,
        ) as temporary_file:
            temporary_file.write(serialized)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
            temporary_name = temporary_file.name

        os.replace(
            temporary_name,
            destination,
        )
    finally:
        if temporary_name:
            temporary_path = Path(temporary_name)
            if temporary_path.exists():
                temporary_path.unlink()

    for candidate in root_path.glob(
        f"{payload['id']}_*.json"
    ):
        if candidate == destination:
            continue

        try:
            candidate.unlink()
        except OSError:
            pass

    legacy_candidate = root_path / f"{payload['id']}.json"

    if legacy_candidate != destination and legacy_candidate.exists():
        try:
            legacy_candidate.unlink()
        except OSError:
            pass

    return destination


def persist_delayed_memory_reports(
    reports,
    *,
    root: Path | str = DELAYED_MEMORY_ROOT,
) -> list[str]:

    normalized_reports = normalize_delayed_memory_reports(
        reports,
    )
    errors = []

    for report_id, report in normalized_reports.items():
        try:
            persist_delayed_memory_report(
                report_id,
                report,
                root=root,
            )
        except (OSError, TypeError, ValueError) as error:
            errors.append(
                f"{report_id}: {error}"
            )

    return errors


def load_delayed_memory_reports_from_files(
    *,
    root: Path | str = DELAYED_MEMORY_ROOT,
) -> tuple[dict[str, dict], list[str]]:

    root_path = Path(root)

    if not root_path.exists():
        return {}, []

    reports = {}
    report_sources = {}
    warnings = []

    try:
        paths = sorted(
            (
                path
                for path in root_path.glob("*.json")
                if path.is_file()
                and not path.name.startswith(".")
            ),
            key=lambda path: (
                path.stat().st_mtime_ns,
                path.name.casefold(),
            ),
        )
    except OSError as error:
        return {}, [
            f"cannot scan {root_path}: {error}"
        ]

    for path in paths:
        try:
            raw_value = json.loads(
                path.read_text(
                    encoding="utf-8-sig",
                )
            )
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            warnings.append(
                f"skipped {path.name}: {error}"
            )
            continue

        normalized_reports = normalize_delayed_memory_reports(
            raw_value,
        )

        if not normalized_reports:
            warnings.append(
                f"skipped {path.name}: invalid delayed memory format"
            )
            continue

        for report_id, report in normalized_reports.items():
            previous_source = report_sources.get(
                report_id
            )

            if previous_source:
                warnings.append(
                    "duplicate delayed memory id "
                    f"{report_id}: {path.name} replaced "
                    f"{previous_source}"
                )

            reports[report_id] = report
            report_sources[report_id] = path.name

    return reports, warnings
