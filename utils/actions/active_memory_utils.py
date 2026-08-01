import re
import secrets
import string
from datetime import datetime


ACTIVE_MEMORY_SLOT_ID_RE = re.compile(
    r"^[a-z0-9]{6}$",
)

SHORT_RUNTIME_ID_RE = ACTIVE_MEMORY_SLOT_ID_RE

ACTIVE_MEMORY_SLOT_ID_SUFFIX_RE = re.compile(
    r"\[\s*active_memory_id\s*:\s*([a-z0-9]{6})\s*\]",
    re.IGNORECASE,
)

ACTIVE_MEMORY_SLOT_ID_ALPHABET = (
    string.ascii_lowercase
    + string.digits
)

SHORT_RUNTIME_ID_ALPHABET = ACTIVE_MEMORY_SLOT_ID_ALPHABET

ACTIVE_MEMORY_KEY_RE = re.compile(
    r"^active_memory(?:_\d+)?$",
    re.IGNORECASE,
)

ACTIVE_MEMORY_RUNTIME_LINE_RE = re.compile(
    r"^\s*active_memory(?:_(\d+))?\s*:",
    re.IGNORECASE,
)

ACTIVE_MEMORY_LIFECYCLE_SUFFIX_NAMES = (
    "creation_time",
    "created_session_id",
    "created_jin_message_number",
    "elapsed_time",
    "elapsed_jin_message_number",
)

ACTIVE_MEMORY_RUNTIME_MANAGED_SUFFIX_NAMES = (
    "active_memory_id",
    *ACTIVE_MEMORY_LIFECYCLE_SUFFIX_NAMES,
    "status",
)

ACTIVE_MEMORY_LIFECYCLE_SUFFIX_RE = re.compile(
    (
        r"\s*\[\s*"
        r"(?:creation_time|created_session_id|created_jin_message_number|"
        r"elapsed_time|elapsed_jin_message_number)"
        r"\s*:\s*[^\]]*\]\s*"
    ),
    re.IGNORECASE,
)

ACTIVE_MEMORY_STATUS_FIELD_RE = re.compile(
    r"\s*\[\s*status\s*:\s*[^\]]*\]\s*",
    re.IGNORECASE,
)

ACTIVE_MEMORY_TRACE_FIELD_RE = re.compile(
    r"\s*(?:\[\s*trace\s*:\s*[^\]]*\]|\(\s*trace\s*:\s*[^)]*\))\s*",
    re.IGNORECASE,
)

def strip_active_memory_managed_suffixes(
    value: str,
    *,
    extra_suffix_names=(),
) -> str:

    suffix_names = []

    for suffix_name in (
        *ACTIVE_MEMORY_RUNTIME_MANAGED_SUFFIX_NAMES,
        *(extra_suffix_names or ()),
    ):
        normalized_name = str(
            suffix_name or ""
        ).strip().casefold()

        if (
            normalized_name
            and normalized_name not in suffix_names
        ):
            suffix_names.append(
                normalized_name
            )

    if not suffix_names:
        return str(value or "").strip()

    managed_suffix_re = re.compile(
        (
            r"\s*\[\s*(?:"
            + "|".join(
                re.escape(name)
                for name in suffix_names
            )
            + r")\s*:\s*[^\]]*\]\s*"
        ),
        re.IGNORECASE,
    )
    cleaned = managed_suffix_re.sub(
        " ",
        str(value or ""),
    )

    return re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()


def collect_active_memory_slot_ids(
    *texts,
) -> set[str]:

    ids = set()

    for text in texts:
        for match in ACTIVE_MEMORY_SLOT_ID_SUFFIX_RE.finditer(
            str(text or "")
        ):
            ids.add(
                match.group(
                    1
                ).casefold()
            )

    return ids


def is_active_memory_key(
    key: str,
) -> bool:

    return bool(
        ACTIVE_MEMORY_KEY_RE.match(
            str(key or "").strip()
        )
    )


def collect_active_memory_slot_indexes(
    *texts,
) -> set[int]:

    indexes = set()

    for text in texts:
        for line in str(
            text or ""
        ).splitlines():
            match = ACTIVE_MEMORY_RUNTIME_LINE_RE.match(
                line
            )

            if not match:
                continue

            suffix = match.group(
                1
            )
            indexes.add(
                int(
                    suffix
                    or 1
                )
            )

    return indexes


def generate_short_runtime_id(
    existing_ids=None,
    *,
    length: int = 6,
) -> str:

    used_ids = {
        str(runtime_id or "").strip().casefold()
        for runtime_id in (existing_ids or ())
        if SHORT_RUNTIME_ID_RE.fullmatch(
            str(runtime_id or "").strip().casefold()
        )
    }

    while True:
        runtime_id = "".join(
            secrets.choice(
                SHORT_RUNTIME_ID_ALPHABET
            )
            for _ in range(length)
        )

        if runtime_id not in used_ids:
            return runtime_id


def generate_active_memory_slot_key(
    *texts,
) -> str:

    used_indexes = collect_active_memory_slot_indexes(
        *texts
    )
    index = 1

    while index in used_indexes:
        index += 1

    return f"active_memory_{index}"


def _runtime_memory_helpers():

    from runtime.L1_memory_utils import (
        durable_memory_line_text,
        normalize_memory_key,
        parse_runtime_memory_lines,
    )

    return (
        parse_runtime_memory_lines,
        durable_memory_line_text,
        normalize_memory_key,
    )


def _active_memory_line_text(
    line: dict,
) -> str:

    _, durable_memory_line_text, _ = _runtime_memory_helpers()

    return durable_memory_line_text(
        line
    )


def strip_active_memory_runtime_metadata(
    memory: str,
) -> str:

    parse_runtime_memory_lines, _, _ = _runtime_memory_helpers()
    parsed_lines = parse_runtime_memory_lines(
        memory
    )

    if not any(
        is_active_memory_key(
            (
                line.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
        )
        for line in parsed_lines
    ):
        return memory or ""

    updated_lines = []

    for line in parsed_lines:
        key = (
            line.get(
                "key",
                "",
            )
            or ""
        ).strip()
        value = (
            line.get(
                "value",
                "",
            )
            or ""
        ).strip()

        if is_active_memory_key(
            key
        ):
            value = ACTIVE_MEMORY_LIFECYCLE_SUFFIX_RE.sub(
                " ",
                value,
            )
            value = re.sub(
                r"\s+",
                " ",
                value,
            ).strip()

        updated_lines.append(
            _active_memory_line_text({
                "key": key,
                "value": value,
            })
        )

    return "\n".join(
        line
        for line in updated_lines
        if line.strip()
    ).strip()


def remove_active_memory_entries(
    memory: str,
) -> str:

    parse_runtime_memory_lines, _, _ = _runtime_memory_helpers()
    parsed_lines = parse_runtime_memory_lines(
        memory
    )

    if not parsed_lines:
        return memory or ""

    return "\n".join(
        _active_memory_line_text(
            line
        )
        for line in parsed_lines
        if not is_active_memory_key(
            (
                line.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
        )
    ).strip()


def _parse_active_memory_suffix(
    value: str,
    suffix_name: str,
) -> str:

    pattern = re.compile(
        r"\[\s*"
        + re.escape(
            suffix_name
        )
        + r"\s*:\s*([^\]]*)\]",
        re.IGNORECASE,
    )
    match = pattern.search(
        str(value or "")
    )

    if not match:
        return ""

    return match.group(
        1
    ).strip()


def is_active_memory_record_paused(
    value: str,
) -> bool:

    return (
        _parse_active_memory_suffix(
            value,
            "status",
        ).casefold()
        == "paused"
    )


def _parse_active_memory_created_jin_message_suffix(
    value: str,
) -> str:

    return _parse_active_memory_suffix(
        value,
        "created_jin_message_number",
    )


def _parse_runtime_datetime(
    value: str,
) -> datetime | None:

    text = str(value or "").strip()

    if not text:
        return None

    try:
        return datetime.fromisoformat(
            text.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError:
        return None


def _parse_runtime_int(
    value,
) -> int | None:

    try:
        return int(
            str(value).strip()
        )
    except (TypeError, ValueError):
        return None


def _runtime_datetime_delta_seconds(
    start: datetime | None,
    end: datetime | None,
) -> int:

    if start is None or end is None:
        return 0

    if start.tzinfo is None and end.tzinfo is not None:
        end = end.replace(
            tzinfo=None
        )

    if start.tzinfo is not None and end.tzinfo is None:
        start = start.replace(
            tzinfo=None
        )

    return max(
        0,
        int(
            (
                end
                - start
            ).total_seconds()
        ),
    )


def _format_runtime_elapsed_time(
    seconds: int,
) -> str:

    seconds = max(
        0,
        int(
            seconds
        ),
    )
    hours, remainder = divmod(
        seconds,
        3600,
    )
    minutes, seconds = divmod(
        remainder,
        60,
    )

    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _parse_runtime_elapsed_seconds(
    value: str | None,
) -> int | None:

    text = str(
        value
        or ""
    ).strip()

    if not text:
        return None

    match = re.fullmatch(
        r"(?P<hours>\d+):(?P<minutes>\d{1,2}):(?P<seconds>\d{1,2})",
        text,
    )

    if match:
        return (
            int(
                match.group(
                    "hours",
                )
            )
            * 3600
            + int(
                match.group(
                    "minutes",
                )
            )
            * 60
            + int(
                match.group(
                    "seconds",
                )
            )
        )

    if re.fullmatch(
        r"\d+",
        text,
    ):
        return int(
            text
        )

    return None


def _runtime_user_idle_seconds(
    context,
) -> int:

    try:
        seconds = int(
            getattr(
                context,
                "runtime_user_idle_seconds",
                0,
            )
            or 0
        )
    except (TypeError, ValueError):
        return 0

    return max(
        0,
        min(
            seconds,
            365 * 24 * 60 * 60,
        ),
    )


def _build_active_memory_lifecycle_suffixes(
    *,
    creation_time: str,
    created_session_id: str = "",
    created_jin_message_number: int,
    elapsed_time: str,
    elapsed_jin_message_number: int,
) -> str:

    values = {
        "creation_time": creation_time,
        "created_session_id": str(
            created_session_id
            or ""
        ).strip(),
        "created_jin_message_number": str(
            created_jin_message_number
        ),
        "elapsed_time": elapsed_time,
        "elapsed_jin_message_number": str(
            elapsed_jin_message_number
        ),
    }

    return " ".join(
        f"[ {name}: {values[name]} ]"
        for name in ACTIVE_MEMORY_LIFECYCLE_SUFFIX_NAMES
        if values[name]
    )


def _attach_active_memory_lifecycle_suffixes_to_value(
    value: str,
    suffixes: str,
) -> str:

    cleaned = ACTIVE_MEMORY_LIFECYCLE_SUFFIX_RE.sub(
        " ",
        str(value or ""),
    )
    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()

    status_match = ACTIVE_MEMORY_STATUS_FIELD_RE.search(
        cleaned
    )

    if not status_match:
        return f"{cleaned} {suffixes}".strip()

    before_status = cleaned[:status_match.start()].rstrip()
    status_and_tail = cleaned[status_match.start():].strip()

    return (
        f"{before_status} {suffixes} {status_and_tail}"
    ).strip()


def refresh_active_memory_runtime_metadata(
    memory: str,
    *,
    previous_memory: str = "",
    context=None,
    add_runtime_user_idle_to_elapsed: bool = False,
) -> str:

    parse_runtime_memory_lines, durable_memory_line_text, normalize_memory_key = (
        _runtime_memory_helpers()
    )
    parsed_lines = parse_runtime_memory_lines(
        memory
    )

    if not any(
        is_active_memory_key(
            (
                line.get(
                    "key",
                    "",
                )
                or ""
            ).strip()
        )
        for line in parsed_lines
    ):
        return memory or ""

    current_timestamp = str(
        getattr(
            context,
            "timestamp",
            "",
        )
        or datetime.now().isoformat()
    )
    current_datetime = (
        _parse_runtime_datetime(
            current_timestamp
        )
        or datetime.now()
    )
    current_turn_number = (
        _parse_runtime_int(
            getattr(
                context,
                "turn_number",
                None,
            )
        )
        or 0
    )
    previous_active_values = {}

    for previous_line in parse_runtime_memory_lines(
        previous_memory
    ):
        previous_key = (
            previous_line.get(
                "key",
                "",
            )
            or ""
        ).strip()

        if not is_active_memory_key(
            previous_key
        ):
            continue

        previous_active_values[
            normalize_memory_key(
                previous_key
            )
        ] = (
            previous_line.get(
                "value",
                "",
            )
            or ""
        ).strip()

    updated_lines = []

    for line in parsed_lines:
        key = (
            line.get(
                "key",
                "",
            )
            or ""
        ).strip()
        value = (
            line.get(
                "value",
                "",
            )
            or ""
        ).strip()

        if not is_active_memory_key(
            key
        ):
            updated_lines.append(
                durable_memory_line_text(
                    line
                )
            )
            continue

        previous_value = previous_active_values.get(
            normalize_memory_key(
                key
            ),
            "",
        )
        creation_time = (
            _parse_active_memory_suffix(
                previous_value,
                "creation_time",
            )
            or current_timestamp
        )
        created_session_id = (
            _parse_active_memory_suffix(
                previous_value,
                "created_session_id",
            )
            or str(
                getattr(
                    context,
                    "session_id",
                    "",
                )
                or ""
            ).strip()
        )
        created_jin_message_number = _parse_runtime_int(
            _parse_active_memory_created_jin_message_suffix(
                previous_value
            )
        )

        if created_jin_message_number is None:
            created_jin_message_number = current_turn_number

        elapsed_seconds = _runtime_datetime_delta_seconds(
            _parse_runtime_datetime(
                creation_time
            ),
            current_datetime,
        )
        previous_elapsed_seconds = (
            _parse_runtime_elapsed_seconds(
                _parse_active_memory_suffix(
                    previous_value,
                    "elapsed_time",
                )
            )
            or 0
        )
        elapsed_seconds = max(
            elapsed_seconds,
            previous_elapsed_seconds,
        )

        if add_runtime_user_idle_to_elapsed:
            elapsed_seconds = max(
                elapsed_seconds,
                previous_elapsed_seconds
                + _runtime_user_idle_seconds(
                    context
                ),
            )

        elapsed_jin_message_number = max(
            0,
            current_turn_number
            - created_jin_message_number,
        )
        value = _attach_active_memory_lifecycle_suffixes_to_value(
            value,
            _build_active_memory_lifecycle_suffixes(
                creation_time=creation_time,
                created_session_id=created_session_id,
                created_jin_message_number=created_jin_message_number,
                elapsed_time=_format_runtime_elapsed_time(
                    elapsed_seconds
                ),
                elapsed_jin_message_number=elapsed_jin_message_number,
            ),
        )
        updated_lines.append(
            f"{key}: {value}".strip()
        )

    return "\n".join(
        line
        for line in updated_lines
        if line.strip()
    ).strip()
