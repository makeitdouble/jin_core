import json
import re
import secrets
from datetime import datetime
from pathlib import Path

from config_loader import (
    config,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHAT_LOG_ROOT = PROJECT_ROOT / "logs"
CHAT_LOG_SESSION_ID_MAX_CHARS = 80
CHAT_LOG_SESSION_ID_RE = re.compile(
    r"[^a-zA-Z0-9_.-]"
)
ACTIVE_MEMORY_ID_SUFFIX_RE = re.compile(
    r"\[\s*active_memory_id\s*:\s*([^\]\s]+)\s*\]",
    re.IGNORECASE,
)
ACTIVE_MEMORY_KEY_RE = re.compile(
    r"^\s*(active_memory(?:_\d+)?)\s*:",
    re.IGNORECASE,
)


def chat_logging_enabled() -> bool:

    return bool(
        getattr(
            config,
            "LOG_CHAT",
            False,
        )
    )


def _now() -> datetime:

    return datetime.now().astimezone()


def _clean_session_id(
    value,
) -> str:

    cleaned = CHAT_LOG_SESSION_ID_RE.sub(
        "_",
        str(
            value
            or ""
        ).strip(),
    ).strip(
        "._-"
    )

    return cleaned[:CHAT_LOG_SESSION_ID_MAX_CHARS]


def _context_session_id(
    context,
) -> str:

    session_id = _clean_session_id(
        getattr(
            context,
            "session_id",
            "",
        )
    )

    if session_id:
        return session_id

    existing = _clean_session_id(
        getattr(
            context,
            "runtime_chat_log_session_id",
            "",
        )
    )

    if existing:
        return existing

    generated = f"session_{secrets.token_hex(4)}"
    context.runtime_chat_log_session_id = generated

    return generated


def get_chat_log_path(
    context,
    *,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path:

    existing_path = str(
        getattr(
            context,
            "runtime_chat_log_path",
            "",
        )
        or ""
    ).strip()

    if existing_path:
        return Path(
            existing_path
        )

    timestamp = now or _now()
    root_path = Path(
        root
        if root is not None
        else CHAT_LOG_ROOT
    )
    session_id = _context_session_id(
        context
    )
    directory = root_path / (
        f"{timestamp:%Y-%m-%d}-{session_id}"
    )
    path = directory / f"{timestamp:%H%M%S}.jsonl"
    context.runtime_chat_log_path = str(
        path
    )

    return path


def _clean_string_list(
    value,
) -> list[str]:

    source = value if isinstance(
        value,
        list,
    ) else []
    cleaned = []
    seen = set()

    for item in source:
        item_text = str(
            item
            or ""
        ).strip()

        if (
            not item_text
            or item_text in seen
        ):
            continue

        seen.add(
            item_text
        )
        cleaned.append(
            item_text
        )

    return cleaned


def extract_active_memory_ids(
    records,
) -> list[str]:

    source = records if isinstance(
        records,
        list,
    ) else []
    memory_ids = []
    seen = set()

    for record in source:
        text = str(
            record
            or ""
        ).strip()

        if not text:
            continue

        suffix_match = ACTIVE_MEMORY_ID_SUFFIX_RE.search(
            text
        )
        key_match = ACTIVE_MEMORY_KEY_RE.match(
            text
        )
        memory_id = (
            suffix_match.group(
                1
            )
            if suffix_match
            else (
                key_match.group(
                    1
                )
                if key_match
                else ""
            )
        ).strip().casefold()

        if (
            not memory_id
            or memory_id in seen
        ):
            continue

        seen.add(
            memory_id
        )
        memory_ids.append(
            memory_id
        )

    return memory_ids


def summarize_attachments(
    attachments,
) -> list[dict]:

    source = attachments if isinstance(
        attachments,
        list,
    ) else []
    summaries = []

    for index, attachment in enumerate(
        source,
        start=1,
    ):
        if not isinstance(
            attachment,
            dict,
        ):
            continue

        summary = {
            "name": str(
                attachment.get(
                    "name",
                    f"attachment-{index}",
                )
                or f"attachment-{index}"
            ),
        }

        for key in (
            "id",
            "kind",
            "type",
            "size_bytes",
            "size_label",
            "width",
            "height",
        ):
            if key not in attachment:
                continue

            value = attachment.get(
                key
            )

            if value is None or value == "":
                continue

            summary[key] = value

        width = summary.get(
            "width",
        )
        height = summary.get(
            "height",
        )

        if width and height:
            summary["resolution"] = f"{width}x{height}"

        summaries.append(
            summary
        )

    return summaries


def build_chat_log_entry(
    context,
    *,
    role: str,
    text: str,
    now: datetime | None = None,
) -> dict:

    timestamp = now or _now()

    return {
        "ts": timestamp.isoformat(
            timespec="seconds"
        ),
        "turn": int(
            getattr(
                context,
                "runtime_turn_counter",
                0,
            )
            or 0
        ),
        "turn_id": str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ),
        "session_id": str(
            getattr(
                context,
                "session_id",
                "",
            )
            or getattr(
                context,
                "runtime_chat_log_session_id",
                "",
            )
            or ""
        ),
        "role": str(
            role
            or ""
        ),
        "text": str(
            text
            or ""
        ),
        "attachments": summarize_attachments(
            getattr(
                context,
                "runtime_turn_attachments",
                [],
            )
        ),
        "active_memory_ids": extract_active_memory_ids(
            getattr(
                context,
                "active_memory_records",
                [],
            )
        ),
        "delayed_memory_ids": _clean_string_list(
            getattr(
                context,
                "runtime_loaded_delayed_memory_ids",
                [],
            )
        ),
    }


def append_chat_log_entry(
    context,
    *,
    role: str,
    text: str,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path | None:

    if not chat_logging_enabled():
        return None

    timestamp = now or _now()
    path = get_chat_log_path(
        context,
        now=timestamp,
        root=root,
    )
    entry = build_chat_log_entry(
        context,
        role=role,
        text=text,
        now=timestamp,
    )
    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with path.open(
        "a",
        encoding="utf-8",
        newline="\n",
    ) as log_file:
        log_file.write(
            json.dumps(
                entry,
                ensure_ascii=False,
                separators=(
                    ",",
                    ":",
                ),
            )
            + "\n"
        )

    return path
