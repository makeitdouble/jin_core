import json
import re
import secrets
import shutil
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
LEGACY_CHAT_LOG_DIR_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})-(?P<session>.+)$"
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


def _public_project_path(
    path: Path | str,
) -> str:

    resolved = Path(path).resolve()

    try:
        relative = resolved.relative_to(
            PROJECT_ROOT.resolve()
        )
    except ValueError:
        return resolved.as_posix()

    return "/" + relative.as_posix().lstrip("/")


def _ensure_reasoning_directory(
    session_directory: Path,
) -> Path:

    reasoning_directory = session_directory / "reasoning"
    reasoning_directory.mkdir(
        parents=True,
        exist_ok=True,
    )

    stale_gitkeep = reasoning_directory / ".gitkeep"

    try:
        stale_gitkeep.unlink()
    except FileNotFoundError:
        pass
    except OSError:
        pass

    return reasoning_directory


def _existing_session_chat_logs(
    context,
    *,
    root: Path | str | None = None,
) -> list[Path]:

    root_path = Path(
        root
        if root is not None
        else CHAT_LOG_ROOT
    )
    session_id = _context_session_id(
        context
    )

    if not root_path.is_dir():
        return []

    logs: list[Path] = []

    for date_directory in root_path.iterdir():
        if (
            not date_directory.is_dir()
            or not re.fullmatch(
                r"\d{4}-\d{2}-\d{2}",
                date_directory.name,
            )
        ):
            continue

        session_directory = (
            date_directory / session_id
        )

        if not session_directory.is_dir():
            continue

        logs.extend(
            path
            for path in session_directory.glob(
                "*.jsonl"
            )
            if path.is_file()
        )

    return sorted(
        logs,
        key=lambda path: (
            path.parent.parent.name,
            path.name,
        ),
    )


def _chat_log_max_turn(
    paths: list[Path],
) -> int:

    max_turn = 0

    for path in paths:
        try:
            lines = path.read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            continue

        for line in lines:
            try:
                entry = json.loads(
                    line
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            if not isinstance(
                entry,
                dict,
            ):
                continue

            try:
                turn = int(
                    entry.get(
                        "turn",
                        0,
                    )
                    or 0
                )
            except (
                TypeError,
                ValueError,
            ):
                continue

            max_turn = max(
                max_turn,
                turn,
            )

    return max_turn


def resume_chat_log_session(
    context,
    *,
    root: Path | str | None = None,
) -> Path | None:

    if not chat_logging_enabled():
        return None

    existing_logs = _existing_session_chat_logs(
        context,
        root=root,
    )

    if not existing_logs:
        return None

    path = existing_logs[-1]
    context.runtime_chat_log_path = str(
        path
    )

    context_path = path.with_suffix(
        ".txt"
    )

    if context_path.exists():
        context.runtime_chat_context_path = str(
            context_path
        )

    max_turn = _chat_log_max_turn(
        existing_logs
    )
    current_turn = int(
        getattr(
            context,
            "runtime_turn_counter",
            0,
        )
        or 0
    )

    if max_turn > current_turn:
        context.runtime_turn_counter = max_turn

    _ensure_reasoning_directory(
        path.parent
    )

    return path


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
    date_directory = root_path / f"{timestamp:%Y-%m-%d}"
    directory = date_directory / session_id
    existing_logs = sorted(
        path
        for path in directory.glob(
            "*.jsonl"
        )
        if path.is_file()
    )
    path = (
        existing_logs[-1]
        if existing_logs
        else directory / f"{timestamp:%H%M%S}.jsonl"
    )
    context.runtime_chat_log_path = str(
        path
    )

    _ensure_reasoning_directory(
        directory
    )

    return path


def get_chat_context_path(
    context,
    *,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path:

    return get_chat_log_path(
        context,
        now=now,
        root=root,
    ).with_suffix(
        ".txt"
    )


def get_chat_bootstrap_context_path(
    context,
    *,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path:

    chat_log_path = get_chat_log_path(
        context,
        now=now,
        root=root,
    )

    return chat_log_path.with_name(
        chat_log_path.stem + ".bootstrap.txt"
    )


def _context_snapshot_text(
    context_snapshot: dict | None = None,
    *,
    system_prompt: str = "",
    user_prompt: str = "",
) -> str:

    snapshot = (
        context_snapshot
        if isinstance(
            context_snapshot,
            dict,
        )
        else {}
    )

    if snapshot:
        hidden = bool(
            snapshot.get(
                "hide_internal_action_rules"
            )
        )
        visible_system_prompt = str(
            snapshot.get(
                "visible_system_prompt",
                "",
            )
            or ""
        )
        raw_system_prompt = str(
            snapshot.get(
                "system_prompt",
                "",
            )
            or ""
        )
        system_prompt = (
            visible_system_prompt
            if hidden and visible_system_prompt
            else raw_system_prompt
        )
        user_prompt = str(
            snapshot.get(
                "user_prompt",
                "",
            )
            or ""
        )

    return "\n\n".join(
        str(part or "").strip()
        for part in (
            system_prompt,
            user_prompt,
        )
        if str(part or "").strip()
    ).strip()


def _write_context_snapshot(
    path: Path,
    text: str,
) -> Path:

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )
    path.write_text(
        text + "\n",
        encoding="utf-8",
        newline="\n",
    )

    return path


def save_chat_context_snapshot(
    context,
    *,
    context_snapshot: dict | None = None,
    system_prompt: str = "",
    user_prompt: str = "",
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path | None:

    if not chat_logging_enabled():
        return None

    text = _context_snapshot_text(
        context_snapshot,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    if not text:
        return None

    path = _write_context_snapshot(
        get_chat_context_path(
            context,
            now=now,
            root=root,
        ),
        text,
    )
    context.runtime_chat_context_path = str(
        path
    )

    return path


def save_chat_bootstrap_context_snapshot(
    context,
    *,
    context_snapshot: dict | None = None,
    system_prompt: str = "",
    user_prompt: str = "",
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path | None:

    if not chat_logging_enabled():
        return None

    text = _context_snapshot_text(
        context_snapshot,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
    )

    if not text:
        return None

    path = _write_context_snapshot(
        get_chat_bootstrap_context_path(
            context,
            now=now,
            root=root,
        ),
        text,
    )
    context.runtime_chat_bootstrap_context_path = str(
        path
    )

    return path


def save_current_runtime_context_snapshot(
    context,
    *,
    user_prompt: str = "",
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path | None:

    if not chat_logging_enabled():
        return None

    from rules.brain_context_builder import (
        build_brain_context,
    )
    from utils.brain_client_utils import (
        get_brain_runtime_config,
    )

    brain_runtime = get_brain_runtime_config()
    system_prompt = build_brain_context(
        context,
        brain_runtime.get(
            "runtime_actions",
            {},
        ),
        user_input=str(
            user_prompt
            or ""
        ),
    )

    return save_chat_context_snapshot(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        now=now,
        root=root,
    )


def save_current_runtime_bootstrap_context_snapshot(
    context,
    *,
    user_prompt: str = "",
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path | None:

    if not chat_logging_enabled():
        return None

    from rules.brain_context_builder import (
        build_brain_context,
    )
    from utils.brain_client_utils import (
        get_brain_runtime_config,
    )

    brain_runtime = get_brain_runtime_config()
    system_prompt = build_brain_context(
        context,
        brain_runtime.get(
            "runtime_actions",
            {},
        ),
        user_input=str(
            user_prompt
            or ""
        ),
    )

    return save_chat_bootstrap_context_snapshot(
        context,
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        now=now,
        root=root,
    )


def save_turn_reasoning(
    context,
    reasoning: str,
    *,
    now: datetime | None = None,
    root: Path | str | None = None,
) -> Path | None:

    if not chat_logging_enabled():
        return None

    cleaned_reasoning = str(
        reasoning
        or ""
    ).strip()

    if not cleaned_reasoning:
        return None

    timestamp = now or _now()
    chat_log_path = get_chat_log_path(
        context,
        now=timestamp,
        root=root,
    )
    reasoning_directory = _ensure_reasoning_directory(
        chat_log_path.parent
    )
    session_id = _context_session_id(
        context
    )
    turn_id = _clean_session_id(
        getattr(
            context,
            "runtime_current_turn_id",
            "",
        )
    ) or f"turn_{int(getattr(context, 'runtime_turn_counter', 0) or 0):06d}"
    reasoning_path = (
        reasoning_directory
        / f"{chat_log_path.stem}_{turn_id}.txt"
    )
    context_path = chat_log_path.with_suffix(
        ".txt"
    )
    reasoning_path.write_text(
        "\n".join([
            f"captured_at: {timestamp.isoformat(timespec='seconds')}",
            f"session_id: {session_id}",
            f"turn: {int(getattr(context, 'runtime_turn_counter', 0) or 0)}",
            f"turn_id: {getattr(context, 'runtime_current_turn_id', '') or ''}",
            f"dialog_path: {_public_project_path(chat_log_path)}",
            f"context_path: {_public_project_path(context_path)}",
            "",
            "--- REASONING ---",
            cleaned_reasoning,
            "",
        ]),
        encoding="utf-8",
        newline="\n",
    )
    context.runtime_turn_reasoning_log_path = str(
        reasoning_path
    )

    return reasoning_path


def _merge_directory_contents(
    source: Path,
    target: Path,
) -> None:

    target.mkdir(
        parents=True,
        exist_ok=True,
    )

    for source_item in sorted(
        source.iterdir(),
        key=lambda item: item.name,
    ):
        target_item = target / source_item.name

        if source_item.is_dir():
            _merge_directory_contents(
                source_item,
                target_item,
            )
            try:
                source_item.rmdir()
            except OSError:
                pass
            continue

        if not target_item.exists():
            shutil.move(
                str(source_item),
                str(target_item),
            )
            continue

        try:
            if source_item.read_bytes() == target_item.read_bytes():
                source_item.unlink()
                continue
        except OSError:
            pass

        suffix_index = 1

        while True:
            candidate = target / (
                f"{target_item.stem}.migrated-{suffix_index}"
                f"{target_item.suffix}"
            )

            if not candidate.exists():
                shutil.move(
                    str(source_item),
                    str(candidate),
                )
                break

            suffix_index += 1


def _move_file_without_overwrite(
    source: Path,
    target: Path,
) -> Path:

    target.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    if not target.exists():
        shutil.move(
            str(source),
            str(target),
        )
        return target

    try:
        if source.read_bytes() == target.read_bytes():
            source.unlink()
            return target
    except OSError:
        pass

    suffix_index = 1

    while True:
        candidate = target.with_name(
            f"{target.stem}.migrated-{suffix_index}{target.suffix}"
        )

        if not candidate.exists():
            shutil.move(
                str(source),
                str(candidate),
            )
            return candidate

        suffix_index += 1


def _reasoning_session_id(
    path: Path,
    date_directory: Path,
) -> str:

    try:
        head = path.read_text(
            encoding="utf-8",
            errors="replace",
        )[:4096]
    except OSError:
        head = ""

    match = re.search(
        r"(?m)^session_id:\s*(.+?)\s*$",
        head,
    )

    if match:
        session_id = _clean_session_id(
            match.group(1)
        )

        if session_id:
            return session_id

    session_directories = sorted(
        (
            item
            for item in date_directory.iterdir()
            if item.is_dir()
            and item.name != "reasoning"
        ),
        key=lambda item: len(item.name),
        reverse=True,
    )

    for session_directory in session_directories:
        if path.name.startswith(
            session_directory.name + "_"
        ):
            return session_directory.name

    return ""


def _migrate_date_reasoning_directory(
    date_directory: Path,
) -> list[tuple[Path, Path]]:

    source_directory = date_directory / "reasoning"

    if not source_directory.is_dir():
        return []

    moved: list[tuple[Path, Path]] = []

    for source in sorted(
        source_directory.iterdir(),
        key=lambda item: item.name,
    ):
        if not source.is_file():
            continue

        if source.name == ".gitkeep":
            try:
                source.unlink()
            except OSError:
                pass
            continue

        session_id = _reasoning_session_id(
            source,
            date_directory,
        )

        if not session_id:
            continue

        target_directory = _ensure_reasoning_directory(
            date_directory / session_id
        )
        prefix = session_id + "_"
        target_name = (
            source.name[len(prefix):]
            if source.name.startswith(prefix)
            else source.name
        )
        target = _move_file_without_overwrite(
            source,
            target_directory / target_name,
        )
        moved.append(
            (
                source,
                target,
            )
        )

    try:
        source_directory.rmdir()
    except OSError:
        pass

    return moved


def migrate_legacy_chat_logs(
    *,
    root: Path | str | None = None,
) -> list[tuple[Path, Path]]:

    if not chat_logging_enabled():
        return []

    root_path = Path(
        root
        if root is not None
        else CHAT_LOG_ROOT
    )
    root_path.mkdir(
        parents=True,
        exist_ok=True,
    )
    moved: list[tuple[Path, Path]] = []

    for source in sorted(
        root_path.iterdir(),
        key=lambda item: item.name,
    ):
        if not source.is_dir():
            continue

        match = LEGACY_CHAT_LOG_DIR_RE.fullmatch(
            source.name
        )

        if not match:
            continue

        session_id = _clean_session_id(
            match.group(
                "session"
            )
        )

        if not session_id:
            continue

        date_directory = root_path / match.group(
            "date"
        )
        target = date_directory / session_id

        if target.exists():
            _merge_directory_contents(
                source,
                target,
            )
            try:
                source.rmdir()
            except OSError:
                pass
        else:
            date_directory.mkdir(
                parents=True,
                exist_ok=True,
            )
            shutil.move(
                str(source),
                str(target),
            )

        _ensure_reasoning_directory(
            target
        )
        moved.append(
            (
                source,
                target,
            )
        )

    for date_directory in sorted(
        root_path.iterdir(),
        key=lambda item: item.name,
    ):
        if (
            date_directory.is_dir()
            and re.fullmatch(
                r"\d{4}-\d{2}-\d{2}",
                date_directory.name,
            )
        ):
            moved.extend(
                _migrate_date_reasoning_directory(
                    date_directory
                )
            )

    return moved


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
    entry["dialog_path"] = _public_project_path(
        path
    )
    context_path = get_chat_context_path(
        context,
        now=timestamp,
        root=root,
    )

    if context_path.exists():
        entry["context_path"] = _public_project_path(
            context_path
        )

    reasoning_path = str(
        getattr(
            context,
            "runtime_turn_reasoning_log_path",
            "",
        )
        or ""
    ).strip()

    if (
        str(role or "").casefold() == "jin"
        and reasoning_path
        and Path(reasoning_path).exists()
    ):
        entry["reasoning_path"] = _public_project_path(
            Path(reasoning_path)
        )

    path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    needs_separator = False
    try:
        if path.is_file() and path.stat().st_size > 0:
            with path.open("rb") as existing_log:
                existing_log.seek(-1, 2)
                needs_separator = existing_log.read(1) not in {b"\n", b"\r"}
    except OSError:
        needs_separator = False

    with path.open(
        "a",
        encoding="utf-8",
        newline="\n",
    ) as log_file:
        if needs_separator:
            log_file.write("\n")

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
