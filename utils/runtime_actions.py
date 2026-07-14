import json
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime

from rules import runtime as runtime_rules
from rules.runtime import (
    RUNTIME_ACTION_APPEND_SKILL,
    RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_CHECK_TODO,
    RUNTIME_ACTION_CREATE_TODO_LIST,
    RUNTIME_ACTION_LIST_DELAYED_MEMORY,
    RUNTIME_ACTION_LIST_SKILLS,
    RUNTIME_ACTION_HIDE_SKILLS,
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_REMOVE_SKILL,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)


KNOWN_RUNTIME_ACTIONS = tuple(
    sorted(
        (
            RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
            RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
            RUNTIME_ACTION_LIST_DELAYED_MEMORY,
            RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
            RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
            RUNTIME_ACTION_WEB_SEARCH,
            RUNTIME_ACTION_LIST_SKILLS,
            RUNTIME_ACTION_HIDE_SKILLS,
            RUNTIME_ACTION_IDLE,
            RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
            RUNTIME_ACTION_APPEND_SKILL,
            RUNTIME_ACTION_REMOVE_SKILL,
            RUNTIME_ACTION_ASSET_ACTION,
            RUNTIME_ACTION_CREATE_TODO_LIST,
            RUNTIME_ACTION_RESOLVE_TODO,
            RUNTIME_ACTION_CHECK_TODO,
            RUNTIME_ACTION_SAVE_SESSION,
        )
    )
)

BRACKETED_INTERNAL_ACTION_PATTERN = re.compile(
    (
        r"(?:"
        r"<\s*(?:INTERNAL_ACTION_)?"
        r"(?P<bracketed_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY|LIST_SKILLS|HIDE_SKILLS|CLEAN_TOOL_RESULTS|APPEND_SKILLS?|REMOVE_SKILLS?|RESOLVE_TODO|CHECK_TODO|IDLE)"
        r"(?:\s*:\s*(?P<bracketed_query>(?:(?!</\s*>)[^\r\n>])*?))?"
        r"(?:\s*</\s*>+|\s*/?\s*>+)"
        r"|"
        r"<\s*(?:INTERNAL_ACTION_)?"
        r"(?P<bracketed_attr_name>APPEND_SKILL)"
        r"\s+name\s*=\s*(?P<bracketed_attr_quote>['\"])"
        r"(?P<bracketed_attr_query>[^\r\n<>]*?)"
        r"(?P=bracketed_attr_quote)"
        r"\s*/?\s*>+"
        r"|"
        r"<\s*(?:INTERNAL_ACTION_)?"
        r"(?P<bracketed_line_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY|SAVE_DELAYED_MEMORY_CONTENT|LIST_SKILLS|HIDE_SKILLS|CLEAN_TOOL_RESULTS|APPEND_SKILLS?|REMOVE_SKILLS?|RESOLVE_TODO|CHECK_TODO|IDLE)"
        r"(?:\s*:\s*(?P<bracketed_line_query>[^\r\n>]*))?"
        r"[^\S\r\n]*(?=\r?\n)"
        r"|"
        r"(?m:^\s*(?:INTERNAL_ACTION_)?"
        r"(?P<bare_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY|SAVE_DELAYED_MEMORY_CONTENT|LIST_SKILLS|HIDE_SKILLS|CLEAN_TOOL_RESULTS|APPEND_SKILLS?|REMOVE_SKILLS?|RESOLVE_TODO|CHECK_TODO|IDLE)"
        r"(?:\s*:\s*(?P<bare_query>[^\r\n]*))?"
        r"\s*$)"
        r")"
    ),
    re.IGNORECASE,
)

DELAYED_MEMORY_ACTION_PATTERN = re.compile(
    (
        r"(?m:^[^\S\r\n]*"
        r"<?\s*(?:INTERNAL_ACTION_)?"
        r"(?P<name>LIST_DELAYED_MEMORY|APPEND_DELAYED_MEMORY|REMOVE_DELAYED_MEMORY)"
        r"(?:\s*:\s*(?P<query>[^\r\n>]*?))?"
        r"\s*/?\s*>?[^\S\r\n]*$)"
    ),
    re.IGNORECASE,
)

MALFORMED_CALL_INTERNAL_ACTION_PATTERN = re.compile(
    (
        r"(?:"
        r"<\|?tool_call\>\s*call\s*:\s*(?:INTERNAL_ACTION_)?"
        r"(?P<tool_call_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY|SAVE_DELAYED_MEMORY_CONTENT|LIST_DELAYED_MEMORY|APPEND_DELAYED_MEMORY|REMOVE_DELAYED_MEMORY|LIST_SKILLS|HIDE_SKILLS|CLEAN_TOOL_RESULTS|APPEND_SKILLS?|REMOVE_SKILLS?|RESOLVE_TODO|CHECK_TODO|IDLE)"
        r"(?:\s*:\s*(?P<tool_call_query>(?:(?!</\s*>)[^\r\n>])*?))?"
        r"(?:\s*</\s*>+|\s*/?\s*>+|[^\S\r\n]*(?=\r?\n|$))"
        r"|"
        r"(?m:^\s*call\s*:\s*(?:INTERNAL_ACTION_)?"
        r"(?P<bare_call_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY|SAVE_DELAYED_MEMORY_CONTENT|LIST_DELAYED_MEMORY|APPEND_DELAYED_MEMORY|REMOVE_DELAYED_MEMORY|LIST_SKILLS|HIDE_SKILLS|CLEAN_TOOL_RESULTS|APPEND_SKILLS?|REMOVE_SKILLS?|RESOLVE_TODO|CHECK_TODO|IDLE)"
        r"(?:\s*:\s*(?P<bare_call_query>[^\r\n]*))?"
        r"\s*$)"
        r")"
    ),
    re.IGNORECASE,
)

DELAYED_MEMORY_CONTENT_BLOCK_RE = re.compile(
    (
        r"<\s*(?:INTERNAL_ACTION_)?SAVE_DELAYED_MEMORY_CONTENT\s*>"
        r"[^\S\r\n]*(?:\r?\n)?"
        r"(?P<payload>.*?)"
        r"</\s*(?:INTERNAL_ACTION_)?SAVE_DELAYED_MEMORY_CONTENT\s*>+"
    ),
    re.IGNORECASE | re.DOTALL,
)

ASSET_ACTION_BLOCK_RE = re.compile(
    (
        r"<\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>"
        r"[^\S\r\n]*(?:\r?\n)?"
        r"(?P<payload>.*?)"
        r"(?:<\s*/\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>+|<\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>)"
    ),
    re.IGNORECASE | re.DOTALL,
)

CREATE_TODO_BLOCK_RE = re.compile(
    (
        r"<\s*(?:TODO_LIST|INTERNAL_ACTION_TODO_LIST|INTERNAL_ACTION_CREATE_TODO_LIST)\s*>"
        r"[^\S\r\n]*(?:\r?\n)?"
        r"(?P<payload>.*?)"
        r"</\s*(?:TODO_LIST|INTERNAL_ACTION_TODO_LIST|INTERNAL_ACTION_CREATE_TODO_LIST)\s*>+"
    ),
    re.IGNORECASE | re.DOTALL,
)

DELAYED_MEMORY_FIELD_RE = re.compile(
    r"(?im)^[^\S\r\n]*(title|summary|tags|body)[^\S\r\n]*:[^\S\r\n]*(.*)$",
)

DELAYED_MEMORY_BLOCK_START_RE = re.compile(
    r"<\s*(?:INTERNAL_ACTION_)?SAVE_DELAYED_MEMORY_CONTENT\s*>",
    re.IGNORECASE,
)

ASSET_ACTION_BLOCK_START_RE = re.compile(
    r"<\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>",
    re.IGNORECASE,
)

ASSET_ACTION_BLOCK_TAG_RE = re.compile(
    r"<\s*(?P<slash>/)?\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>+",
    re.IGNORECASE,
)

ASSET_ACTION_BLOCK_END_RE = re.compile(
    r"(?:<\s*/\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>+|<\s*(?:INTERNAL_ACTION_)?ASSET_ACTION\s*>)",
    re.IGNORECASE,
)

CREATE_TODO_BLOCK_START_RE = re.compile(
    r"<\s*(?:TODO_LIST|INTERNAL_ACTION_TODO_LIST|INTERNAL_ACTION_CREATE_TODO_LIST)\s*>",
    re.IGNORECASE,
)

CREATE_TODO_BLOCK_END_RE = re.compile(
    r"</\s*(?:TODO_LIST|INTERNAL_ACTION_TODO_LIST|INTERNAL_ACTION_CREATE_TODO_LIST)\s*>+",
    re.IGNORECASE,
)

DELAYED_MEMORY_BLOCK_END_RE = re.compile(
    r"</\s*(?:INTERNAL_ACTION_)?SAVE_DELAYED_MEMORY_CONTENT\s*>+",
    re.IGNORECASE,
)

CREATE_ACTIVE_MEMORY_MARKER_RE = re.compile(
    (
        r"^\s*<?\s*(?:INTERNAL_ACTION_)?CREATE_ACTIVE_MEMORY"
        r"\s*:\s*(?P<fields>(?:(?!</\s*>).)*?)\s*(?:</\s*>+|/?\s*>+)\s*$"
        r"|"
        r"^\s*(?:INTERNAL_ACTION_)?CREATE_ACTIVE_MEMORY"
        r"\s*:\s*(?P<bare_fields>[^\r\n]*)\s*$"
    ),
    re.IGNORECASE,
)

INTERNAL_ACTION_WITH_PAYLOAD_MARKER_RE = re.compile(
    (
        r"^\s*<?\s*(?:INTERNAL_ACTION_)?[A-Z_]+"
        r"\s*:\s*(?P<payload>(?:(?!</\s*>).)*?)\s*(?:</\s*>+|/?\s*>+)\s*$"
        r"|"
        r"^\s*(?:INTERNAL_ACTION_)?[A-Z_]+"
        r"\s*:\s*(?P<bare_payload>[^\r\n]*)\s*$"
    ),
    re.IGNORECASE,
)

ACTIVE_MEMORY_SLOT_ID_RE = re.compile(
    r"^[a-z0-9]{6}$",
)

SHORT_RUNTIME_ID_RE = ACTIVE_MEMORY_SLOT_ID_RE

ACTIVE_MEMORY_SLOT_ID_SUFFIX_RE = re.compile(
    r"\[\s*active_memory_id\s*:\s*([a-z0-9]{6})\s*\]",
    re.IGNORECASE,
)

ACTIVE_MEMORY_RESOLVE_SLOT_ID_TOKEN_RE = re.compile(
    r"(?<![a-zA-Z0-9_])([a-zA-Z0-9]{6})(?![a-zA-Z0-9_])",
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


def extract_active_memory_resolve_slot_id(
    payload: str,
    *,
    existing_ids=None,
) -> str:

    existing_id_set = {
        str(active_memory_id or "").strip().casefold()
        for active_memory_id in (existing_ids or ())
        if ACTIVE_MEMORY_SLOT_ID_RE.fullmatch(
            str(active_memory_id or "").strip().casefold()
        )
    }

    for match in ACTIVE_MEMORY_RESOLVE_SLOT_ID_TOKEN_RE.finditer(
        str(payload or "")
    ):
        active_memory_id = match.group(
            1
        ).casefold()

        if (
            existing_id_set
            and active_memory_id not in existing_id_set
        ):
            continue

        return active_memory_id

    return ""


def generate_active_memory_slot_id(
    existing_ids=None,
) -> str:

    return generate_short_runtime_id(
        existing_ids
    )


def _normalize_internal_action_placeholder(
    value: str,
) -> str:

    value = (
        value
        or ""
    ).strip()

    parts = [
        part.strip()
        for part in value.split("|")
        if part.strip()
    ]

    if parts:
        value = " | ".join(
            parts
        )

    return value.casefold().strip(
        "`'\"<>"
    ).strip()


def _get_internal_action_marker_payload(
    marker: str,
) -> str:

    match = INTERNAL_ACTION_WITH_PAYLOAD_MARKER_RE.match(
        str(marker or "")
    )

    if not match:
        return ""

    payload = (
        match.group("payload")
        or match.group("bare_payload")
        or ""
    )

    return " | ".join(
        part.strip()
        for part in payload.split("|")
        if part.strip()
    )


def _get_internal_action_placeholder_payloads(
    markers=None,
) -> tuple[str, ...]:

    markers = (
        markers
        if markers is not None
        else runtime_rules.INTERNAL_ACTIONS_WITH_PAYLOAD
    )

    payloads = []

    for marker in markers:
        payload = _get_internal_action_marker_payload(
            marker
        )

        if (
            payload
            and payload not in payloads
        ):
            payloads.append(
                payload
            )

    return tuple(
        payloads
    )


def normalize_active_memory_marker_field(
    field: str,
) -> str:

    normalized_field = re.sub(
        r"[^0-9a-zA-Z_]+",
        "_",
        str(field or "").strip().casefold(),
    ).strip("_")

    return normalized_field


def get_create_active_memory_marker_fields(
    marker: str | None = None,
) -> tuple[str, ...]:

    marker = (
        marker
        if marker is not None
        else runtime_rules.INTERNAL_ACTION_CREATE_ACTIVE_MEMORY_MARKER
    )

    match = CREATE_ACTIVE_MEMORY_MARKER_RE.match(
        str(marker or "")
    )

    if not match:
        return ()

    marker_fields = (
        match.group("fields")
        or match.group("bare_fields")
        or ""
    )

    fields = []

    for field in marker_fields.split("|"):
        normalized_field = normalize_active_memory_marker_field(
            field
        )

        if (
            normalized_field
            and normalized_field not in fields
        ):
            fields.append(
                normalized_field
            )

    return tuple(
        fields
    )


def get_create_active_memory_placeholder_payload(
    marker: str | None = None,
) -> str:

    marker = (
        marker
        if marker is not None
        else runtime_rules.INTERNAL_ACTION_CREATE_ACTIVE_MEMORY_MARKER
    )

    match = CREATE_ACTIVE_MEMORY_MARKER_RE.match(
        str(marker or "")
    )

    if not match:
        return ""

    marker_fields = (
        match.group("fields")
        or match.group("bare_fields")
        or ""
    )

    return " | ".join(
        field.strip()
        for field in marker_fields.split("|")
        if field.strip()
    )


def slugify_delayed_memory_title(
    title: str,
) -> str:

    return generate_short_runtime_id()


def generate_delayed_memory_report_id(
    existing_ids=None,
) -> str:

    return generate_short_runtime_id(
        existing_ids
    )


def is_delayed_memory_report_id(
    value: str,
) -> bool:

    return bool(
        SHORT_RUNTIME_ID_RE.fullmatch(
            str(value or "").strip().casefold()
        )
    )


def parse_delayed_memory_content_payload(
    payload: str,
    *,
    created_session_id: str = "",
    created_time: str = "",
) -> dict:

    text = str(
        payload
        or ""
    ).replace(
        "\r\n",
        "\n",
    ).strip()

    if not text:
        return {}

    field_matches = list(
        DELAYED_MEMORY_FIELD_RE.finditer(
            text
        )
    )

    if not field_matches:
        return {}

    fields = {}

    for index, match in enumerate(
        field_matches
    ):
        field_name = match.group(
            1
        ).casefold()
        inline_value = (
            match.group(
                2
            )
            or ""
        ).strip()
        next_start = (
            field_matches[index + 1].start()
            if index + 1 < len(field_matches)
            else len(text)
        )
        block_value = text[
            match.end():next_start
        ].strip(
            "\n"
        )

        if field_name == "body":
            value = "\n".join(
                part
                for part in (
                    inline_value,
                    block_value,
                )
                if part
            ).strip()
        else:
            value = inline_value

        fields[field_name] = value

    title = str(
        fields.get(
            "title",
            "",
        )
        or ""
    ).strip()

    if not title:
        return {}

    tags = [
        tag.strip()
        for tag in str(
            fields.get(
                "tags",
                "",
            )
            or ""
        ).split(",")
        if tag.strip()
    ]

    report_id = generate_delayed_memory_report_id(
        ()
    )

    return {
        report_id: {
            "title": title,
            "summary": str(
                fields.get(
                    "summary",
                    "",
                )
                or ""
            ).strip(),
            "tags": tags,
            "body": str(
                fields.get(
                    "body",
                    "",
                )
                or ""
            ).strip(),
            "created_session_id": str(
                created_session_id
                or ""
            ).strip(),
            "created_time": str(
                created_time
                or ""
            ).strip(),
        },
    }


@dataclass(frozen=True)
class RuntimeActionCall:
    name: str
    payload: str = ""


@dataclass(frozen=True)
class RuntimeActionResult:
    text: str
    started_actions: tuple[RuntimeActionCall, ...] = ()
    observed_actions: tuple[RuntimeActionCall, ...] = ()
    actions: tuple[RuntimeActionCall, ...] = ()
    removed_markers: tuple[str, ...] = ()
    marker_repetition_exceeded: bool = False
    marker_repetition_reason: str = ""

    @property
    def search_queries(self) -> tuple[str, ...]:

        queries = []

        for action in self.actions:

            if action.name != RUNTIME_ACTION_WEB_SEARCH:
                continue

            query = extract_search_query(
                action.payload
            )

            if query:
                queries.append(
                    query
                )

        return tuple(
            queries
        )

    def count(
        self,
        action_name: str,
    ) -> int:

        normalized_name = normalize_runtime_action_name(
            action_name
        )

        return sum(
            1
            for action in self.actions
            if action.name == normalized_name
        )


def build_runtime_action_id(
    action_name: str,
    index: int,
) -> str:

    return (
        f"{normalize_runtime_action_name(action_name).lower()}_"
        f"{index:03d}"
    )


class RuntimeActionRepetitionGuard:

    def __init__(
        self,
        *,
        max_consecutive: int = 3,
        max_per_message: int = 5,
    ):
        self.max_consecutive = max_consecutive
        self.max_per_message = max_per_message
        self.counts = {}
        self.last_key = None
        self.consecutive_count = 0
        self.triggered = False
        self.reason = ""

    @staticmethod
    def marker_key(
        action: RuntimeActionCall,
    ) -> tuple[str, str]:
        payload = " ".join(
            str(
                action.payload
                or ""
            ).split()
        ).strip().casefold()

        return (
            action.name,
            payload,
        )

    def record(
        self,
        action: RuntimeActionCall,
    ) -> bool:

        if self.triggered:
            return True

        # Repeated IDLE markers are a valid scheduling primitive: one model
        # message may intentionally arm several independent future ticks.
        # The sequence/runtime limits still bound the total amount of work,
        # so the generic loop guard must not collapse or reject them.
        if action.name == RUNTIME_ACTION_IDLE:
            return False

        key = self.marker_key(
            action
        )

        count = self.counts.get(
            key,
            0,
        ) + 1
        self.counts[key] = count

        if key == self.last_key:
            self.consecutive_count += 1
        else:
            self.last_key = key
            self.consecutive_count = 1

        if self.consecutive_count > self.max_consecutive:
            self.triggered = True
            self.reason = (
                "runtime action marker repeated "
                f"{self.consecutive_count} times in a row"
            )
            return True

        if count > self.max_per_message:
            self.triggered = True
            self.reason = (
                "runtime action marker repeated "
                f"{count} times in one message"
            )
            return True

        return False


def normalize_runtime_action_name(
    action_name: str,
) -> str:

    normalized_name = (
        str(action_name)
        .strip()
        .upper()
    )

    if normalized_name.startswith(
        "CAN_"
    ):
        normalized_name = normalized_name[4:]

    aliases = {
        "SAVE_SESSION": RUNTIME_ACTION_SAVE_SESSION,
        "SAVE_DELAYED_MEMORY": RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
        "SAVE_DELAYED_MEMORY_CONTENT": RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
        "LIST_DELAYED_MEMORY": RUNTIME_ACTION_LIST_DELAYED_MEMORY,
        "APPEND_DELAYED_MEMORY": RUNTIME_ACTION_APPEND_DELAYED_MEMORY,
        "REMOVE_DELAYED_MEMORY": RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
        "SAVE_ACTIVE_MEMORY": RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
        "RESOLVE_ACTIVE_MEMORY": RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
        "USE_ASSETS": RUNTIME_ACTION_ASSET_ACTION,
        "LIST_SKILLS": RUNTIME_ACTION_LIST_SKILLS,
        "HIDE_SKILLS": RUNTIME_ACTION_HIDE_SKILLS,
        "CLEAN_TOOL_RESULTS": RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
        "APPEND_SKILL": RUNTIME_ACTION_APPEND_SKILL,
        "REMOVE_SKILL": RUNTIME_ACTION_REMOVE_SKILL,
        "ASSET_ACTION": RUNTIME_ACTION_ASSET_ACTION,
        "TODO_LIST": RUNTIME_ACTION_CREATE_TODO_LIST,
        "INTERNAL_ACTION_TODO_LIST": RUNTIME_ACTION_CREATE_TODO_LIST,
        "CREATE_TODO_LIST": RUNTIME_ACTION_CREATE_TODO_LIST,
        "INTERNAL_ACTION_CREATE_TODO_LIST": RUNTIME_ACTION_CREATE_TODO_LIST,
        "RESOLVE_TODO": RUNTIME_ACTION_RESOLVE_TODO,
        "CHECK_TODO": RUNTIME_ACTION_CHECK_TODO,
        "IDLE": RUNTIME_ACTION_IDLE,
    }

    return aliases.get(
        normalized_name,
        normalized_name,
    )


def normalize_runtime_action_names(
    enabled_actions=None,
) -> tuple[str, ...]:

    if enabled_actions is None:
        return KNOWN_RUNTIME_ACTIONS

    if isinstance(
        enabled_actions,
        dict,
    ):
        candidates = (
            action_name
            for action_name, is_enabled
            in enabled_actions.items()
            if is_enabled
        )

    else:
        candidates = enabled_actions

    actions = []
    removed_markers = []

    for action_name in candidates:

        normalized_name = normalize_runtime_action_name(
            action_name
        )

        normalized_names = [
            normalized_name,
        ]

        if normalized_name == RUNTIME_ACTION_CREATE_ACTIVE_MEMORY:
            normalized_names.append(
                RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY
            )

        if normalized_name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT:
            normalized_names.append(
                RUNTIME_ACTION_LIST_DELAYED_MEMORY
            )
            normalized_names.append(
                RUNTIME_ACTION_APPEND_DELAYED_MEMORY
            )
            normalized_names.append(
                RUNTIME_ACTION_REMOVE_DELAYED_MEMORY
            )

        if normalized_name == RUNTIME_ACTION_ASSET_ACTION:
            normalized_names.append(
                RUNTIME_ACTION_LIST_SKILLS
            )
            normalized_names.append(
                RUNTIME_ACTION_HIDE_SKILLS
            )
            normalized_names.append(
                RUNTIME_ACTION_APPEND_SKILL
            )
            normalized_names.append(
                RUNTIME_ACTION_REMOVE_SKILL
            )

        if (
            normalized_name
            not in KNOWN_RUNTIME_ACTIONS
        ):
            continue

        for normalized_name in normalized_names:
            if normalized_name not in actions:
                actions.append(
                    normalized_name
                )

    return tuple(
        actions
    )


def _clean_internal_action_query(
    query: str,
) -> str:

    return (
        query
        or ""
    ).strip().strip(
        "*_`~"
    ).strip()


def _plural_skill_marker_action_name(
    action_name: str,
) -> str | None:

    normalized_name = (
        str(action_name)
        .strip()
        .upper()
    )

    if normalized_name == "APPEND_SKILLS":
        return RUNTIME_ACTION_APPEND_SKILL

    if normalized_name == "REMOVE_SKILLS":
        return RUNTIME_ACTION_REMOVE_SKILL

    return None


def _split_internal_skill_marker_list(
    query: str,
) -> tuple[str, ...]:

    return tuple(
        skill_name
        for skill_name in (
            part.strip()
            for part in _clean_internal_action_query(
                query
            ).split(",")
        )
        if skill_name
    )


def _is_placeholder_internal_query(
    query: str,
    placeholder_payloads=(),
) -> bool:

    normalized_query = _normalize_internal_action_placeholder(
        query
    )

    if normalized_query in {
        "",
        "...",
    }:
        return True

    placeholder_payloads = {
        _normalize_internal_action_placeholder(
            payload
        )
        for payload in placeholder_payloads
    }

    return normalized_query in placeholder_payloads


def _is_placeholder_create_active_memory_query(
    query: str,
    placeholder_payloads=(),
) -> bool:

    return _is_placeholder_internal_query(
        query,
        placeholder_payloads,
    )


IDLE_SECONDS_RE = re.compile(
    r"^\s*(?P<seconds>\d+)\s*s\s*$",
    re.IGNORECASE,
)


def parse_idle_seconds(
    payload: str,
) -> int | None:

    match = IDLE_SECONDS_RE.fullmatch(
        str(payload or "")
    )

    if match is None:
        return None

    try:
        return int(
            match.group("seconds")
        )
    except (
        TypeError,
        ValueError,
    ):
        return None


def _build_internal_action_call(
    action_name: str,
    query: str = "",
) -> RuntimeActionCall | None:

    normalized_name = normalize_runtime_action_name(
        action_name
    )

    if normalized_name not in KNOWN_RUNTIME_ACTIONS:
        return None

    payload = ""
    placeholder_payloads = _get_internal_action_placeholder_payloads()

    if normalized_name == RUNTIME_ACTION_IDLE:
        seconds = parse_idle_seconds(
            query
        )

        if seconds is None:
            return None

        payload = f"{seconds}s"

    elif normalized_name == RUNTIME_ACTION_WEB_SEARCH:
        query = _clean_internal_action_query(
            query
        )

        if _is_placeholder_internal_query(
            query,
            placeholder_payloads,
        ):
            return None

        payload = json.dumps(
            {
                "query": query,
            },
            ensure_ascii=False,
        )

    elif normalized_name == RUNTIME_ACTION_CREATE_ACTIVE_MEMORY:
        payload = _clean_internal_action_query(
            query
        )

        if _is_placeholder_create_active_memory_query(
            payload,
            placeholder_payloads,
        ):
            return None

    elif normalized_name == RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY:
        payload = _clean_internal_action_query(
            query
        )

        if _is_placeholder_internal_query(
            payload,
            placeholder_payloads,
        ):
            return None

    elif normalized_name == RUNTIME_ACTION_CREATE_TODO_LIST:
        payload = _clean_internal_action_query(
            query
        )

        if not payload:
            return None

    elif normalized_name in (
        RUNTIME_ACTION_RESOLVE_TODO,
        RUNTIME_ACTION_CHECK_TODO,
    ):
        payload = _clean_internal_action_query(
            query
        )

        if _is_placeholder_internal_query(
            payload,
            placeholder_payloads,
        ):
            return None

    elif normalized_name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT:
        report = parse_delayed_memory_content_payload(
            query
        )

        if not report:
            return None

        payload = json.dumps(
            report,
            ensure_ascii=False,
        )

    elif normalized_name == RUNTIME_ACTION_APPEND_DELAYED_MEMORY:
        payload = _clean_internal_action_query(
            query
        ).casefold()

        if (
            _is_placeholder_internal_query(
                payload,
                placeholder_payloads,
            )
            or not is_delayed_memory_report_id(
                payload
            )
        ):
            return None

    elif normalized_name == RUNTIME_ACTION_REMOVE_DELAYED_MEMORY:
        payload = _clean_internal_action_query(
            query
        )

        if _is_placeholder_internal_query(
            payload,
            placeholder_payloads,
        ):
            return None

    elif normalized_name in (
        RUNTIME_ACTION_LIST_DELAYED_MEMORY,
        RUNTIME_ACTION_HIDE_SKILLS,
    ):
        payload = ""

    elif normalized_name in (
        RUNTIME_ACTION_LIST_SKILLS,
        RUNTIME_ACTION_APPEND_SKILL,
        RUNTIME_ACTION_REMOVE_SKILL,
        RUNTIME_ACTION_ASSET_ACTION,
    ):
        payload = _clean_internal_action_query(
            query
        )

        if (
            normalized_name in (
                RUNTIME_ACTION_ASSET_ACTION,
                RUNTIME_ACTION_REMOVE_SKILL,
            )
            and _is_placeholder_internal_query(
                payload,
                placeholder_payloads,
            )
        ):
            return None

    return RuntimeActionCall(
        name=normalized_name,
        payload=payload,
    )


def _action_match_removal_span(
    text: str,
    start: int,
    end: int,
) -> tuple[int, int]:

    line_start = text.rfind(
        "\n",
        0,
        start,
    ) + 1

    line_prefix = text[
        line_start:start
    ]

    line_end = text.find(
        "\n",
        end,
    )

    if line_end < 0:
        line_end = len(
            text
        )
        after_line_end = line_end
    else:
        after_line_end = line_end + 1

    line_suffix = text[
        end:line_end
    ]

    if (
        not line_prefix.strip()
        and not line_suffix.strip()
    ):

        removal_start = line_start
        removal_end = after_line_end

        while removal_end < len(
            text
        ):

            next_line_end = text.find(
                "\n",
                removal_end,
            )

            if next_line_end < 0:
                candidate_end = len(
                    text
                )
                next_position = candidate_end
            else:
                candidate_end = next_line_end
                next_position = next_line_end + 1

            next_line = text[
                removal_end:candidate_end
            ]

            if next_line.strip():
                break

            removal_end = next_position

        return (
            removal_start,
            removal_end,
        )

    return (
        start,
        end,
    )


def _replace_runtime_action_matches(
    text: str,
    pattern,
    replace_action,
) -> str:

    parts = []
    cursor = 0

    for match in pattern.finditer(
        text
    ):

        replacement = replace_action(
            match
        )

        start = match.start()
        end = match.end()

        if replacement == "":
            start, end = _action_match_removal_span(
                text,
                start,
                end,
            )

        start = max(
            start,
            cursor,
        )

        if end < cursor:
            continue

        parts.append(
            text[
                cursor:start
            ]
        )
        parts.append(
            replacement
        )

        cursor = end

    parts.append(
        text[
            cursor:
        ]
    )

    return "".join(
        parts
    )


def extract_runtime_actions(
    text: str,
    enabled_actions=None,
    preserve_action_text: bool = False,
    seen_action_keys=None,
    preserve_action_marker=None,
    repetition_guard: RuntimeActionRepetitionGuard | None = None,
) -> RuntimeActionResult:

    if not text:
        return RuntimeActionResult(
            text="",
        )

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )
    actions = []
    observed_actions = []
    removed_markers = []
    marker_repetition_exceeded = False
    marker_repetition_reason = ""

    if seen_action_keys is None:
        seen_action_keys = set()

    def handle_marker(
        raw_marker: str,
        action_name: str,
        query: str = "",
    ) -> str:
        nonlocal marker_repetition_exceeded
        nonlocal marker_repetition_reason

        plural_skill_action_name = _plural_skill_marker_action_name(
            action_name
        )

        if plural_skill_action_name is not None:
            return handle_plural_skill_marker(
                raw_marker,
                plural_skill_action_name,
                query,
            )

        normalized_action_name = normalize_runtime_action_name(
            action_name
        )
        action_enabled = (
            normalized_action_name in enabled_action_names
        )

        if not action_enabled:
            return raw_marker

        action = _build_internal_action_call(
            action_name,
            query,
        )

        if action is None:
            if not preserve_action_text:
                removed_markers.append(
                    raw_marker
                )

            return (
                raw_marker
                if preserve_action_text
                else ""
            )

        observed_actions.append(
            action
        )

        if (
            repetition_guard is not None
            and repetition_guard.record(
                action
            )
        ):
            marker_repetition_exceeded = True
            marker_repetition_reason = repetition_guard.reason
            return raw_marker

        if (
            preserve_action_marker is not None
            and preserve_action_marker(
                raw_marker,
                action,
            )
        ):
            return raw_marker

        if not preserve_action_text:
            removed_markers.append(
                raw_marker
            )

        if action_enabled:
            action_key = (
                action.name,
                action.payload,
            )

            if (
                action.name == RUNTIME_ACTION_IDLE
                or action_key not in seen_action_keys
            ):
                if action.name != RUNTIME_ACTION_IDLE:
                    seen_action_keys.add(
                        action_key
                    )
                actions.append(
                    action
                )

        return (
            raw_marker
            if preserve_action_text
            else ""
        )

    def handle_plural_skill_marker(
        raw_marker: str,
        action_name: str,
        query: str = "",
    ) -> str:
        nonlocal marker_repetition_exceeded
        nonlocal marker_repetition_reason

        if action_name not in enabled_action_names:
            return raw_marker

        skill_names = _split_internal_skill_marker_list(
            query
        )
        plural_actions = []

        for skill_name in skill_names:
            action = _build_internal_action_call(
                action_name,
                skill_name,
            )

            if action is not None:
                plural_actions.append(
                    action
                )

        if not plural_actions:
            if not preserve_action_text:
                removed_markers.append(
                    raw_marker
                )

            return (
                raw_marker
                if preserve_action_text
                else ""
            )

        observed_actions.extend(
            plural_actions
        )

        for action in plural_actions:
            if (
                repetition_guard is not None
                and repetition_guard.record(
                    action
                )
            ):
                marker_repetition_exceeded = True
                marker_repetition_reason = repetition_guard.reason
                return raw_marker

        should_preserve_marker = False

        for action in plural_actions:
            if (
                preserve_action_marker is not None
                and preserve_action_marker(
                    raw_marker,
                    action,
                )
            ):
                should_preserve_marker = True
                continue

            action_key = (
                action.name,
                action.payload,
            )

            if action_key not in seen_action_keys:
                seen_action_keys.add(
                    action_key
                )
                actions.append(
                    action
                )

        if (
            not preserve_action_text
            and not should_preserve_marker
        ):
            removed_markers.append(
                raw_marker
            )

        return (
            raw_marker
            if (
                preserve_action_text
                or should_preserve_marker
            )
            else ""
        )

    def replace_private_marker(match):

        return handle_marker(
            match.group(0),
            match.group("bracketed_name")
            or match.group("bracketed_attr_name")
            or match.group("bracketed_line_name")
            or match.group("bare_name"),
            match.group("bracketed_query")
            or match.group("bracketed_attr_query")
            or match.group("bracketed_line_query")
            or match.group("bare_query")
            or "",
        )

    def replace_malformed_call_marker(match):

        return handle_marker(
            match.group(0),
            match.group("tool_call_name")
            or match.group("bare_call_name"),
            match.group("tool_call_query")
            or match.group("bare_call_query")
            or "",
        )

    def replace_delayed_memory_action_marker(match):

        return handle_marker(
            match.group(0),
            match.group("name"),
            match.group("query")
            or "",
        )

    def replace_delayed_memory_content_marker(match):

        return handle_marker(
            match.group(0),
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
            match.group("payload")
            or "",
        )

    def replace_asset_action_marker(match):

        return handle_marker(
            match.group(0),
            RUNTIME_ACTION_ASSET_ACTION,
            match.group("payload")
            or "",
        )

    def replace_create_todo_marker(match):

        return handle_marker(
            match.group(0),
            RUNTIME_ACTION_CREATE_TODO_LIST,
            match.group("payload")
            or "",
        )

    clean_text = _replace_runtime_action_matches(
        text,
        CREATE_TODO_BLOCK_RE,
        replace_create_todo_marker,
    )

    clean_text = _replace_runtime_action_matches(
        clean_text,
        ASSET_ACTION_BLOCK_RE,
        replace_asset_action_marker,
    )

    clean_text = _replace_runtime_action_matches(
        clean_text,
        DELAYED_MEMORY_CONTENT_BLOCK_RE,
        replace_delayed_memory_content_marker,
    )

    clean_text = _replace_runtime_action_matches(
        clean_text,
        DELAYED_MEMORY_ACTION_PATTERN,
        replace_delayed_memory_action_marker,
    )

    clean_text = _replace_runtime_action_matches(
        clean_text,
        MALFORMED_CALL_INTERNAL_ACTION_PATTERN,
        replace_malformed_call_marker,
    )

    clean_text = _replace_runtime_action_matches(
        clean_text,
        BRACKETED_INTERNAL_ACTION_PATTERN,
        replace_private_marker,
    )

    return RuntimeActionResult(
        text=clean_text,
        observed_actions=tuple(
            observed_actions
        ),
        actions=tuple(
            actions
        ),
        removed_markers=tuple(
            removed_markers
        ),
        marker_repetition_exceeded=marker_repetition_exceeded,
        marker_repetition_reason=marker_repetition_reason,
    )

def extract_search_query(
    payload: str,
) -> str:

    payload = (
        payload
        or ""
    ).strip()

    if not payload:
        return ""

    data = payload

    for _ in range(2):

        if not isinstance(
            data,
            str,
        ):
            break

        stripped_data = data.strip()

        if not stripped_data:
            return ""

        if _is_ellipsis_placeholder(
            stripped_data
        ):
            return ""

        try:
            data = json.loads(
                stripped_data
            )

        except json.JSONDecodeError:
            return stripped_data

    if isinstance(
        data,
        str,
    ):
        stripped_data = data.strip()

        if _is_ellipsis_placeholder(
            stripped_data
        ):
            return ""

        return stripped_data

    if not isinstance(
        data,
        dict,
    ):
        return payload

    query = data.get(
        "query",
        "",
    )

    if not isinstance(
        query,
        str,
    ):
        return ""

    return extract_search_query(
        query
    )


def _is_ellipsis_placeholder(
    value: str,
) -> bool:

    token = (
        value
        or ""
    ).strip()

    token = token.strip(
        "`'\""
    ).strip()

    if (
        token.startswith("{")
        and token.endswith("}")
    ):
        token = token[
            1:-1
        ].strip()

    token = token.strip(
        "`'\""
    ).strip()

    return bool(
        token
        and re.fullmatch(
            r"(?:\.{3,}|\u2026)+",
            token,
        )
    )


def _enabled_action_start_markers(
    enabled_actions=None,
) -> tuple[str, ...]:

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )

    markers = []

    if RUNTIME_ACTION_IDLE in enabled_action_names:
        markers.extend((
            "<IDLE:",
            "<INTERNAL_ACTION_IDLE:",
            "<|tool_call>call:INTERNAL_ACTION_IDLE",
            "<tool_call>call:INTERNAL_ACTION_IDLE",
            "<|tool_call>call:IDLE",
            "<tool_call>call:IDLE",
            "call:INTERNAL_ACTION_IDLE",
            "call:IDLE",
        ))

    if RUNTIME_ACTION_SAVE_SESSION in enabled_action_names:
        markers.append(
            "<SAVE_SESSION>"
        )
        markers.append(
            "<INTERNAL_ACTION_SAVE_SESSION>"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_SAVE_SESSION"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_SAVE_SESSION"
        )
        markers.append(
            "<|tool_call>call:SAVE_SESSION"
        )
        markers.append(
            "<tool_call>call:SAVE_SESSION"
        )
        markers.append(
            "call:INTERNAL_ACTION_SAVE_SESSION"
        )
        markers.append(
            "call:SAVE_SESSION"
        )

    if RUNTIME_ACTION_CREATE_TODO_LIST in enabled_action_names:
        markers.append(
            "<TODO_LIST>"
        )
        markers.append(
            "</TODO_LIST>"
        )
        markers.append(
            "<INTERNAL_ACTION_TODO_LIST>"
        )
        markers.append(
            "</INTERNAL_ACTION_TODO_LIST>"
        )
        markers.append(
            "<INTERNAL_ACTION_CREATE_TODO_LIST>"
        )
        markers.append(
            "</INTERNAL_ACTION_CREATE_TODO_LIST>"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_TODO_LIST"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_TODO_LIST"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_CREATE_TODO_LIST"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_CREATE_TODO_LIST"
        )
        markers.append(
            "<|tool_call>call:CREATE_TODO_LIST"
        )
        markers.append(
            "<tool_call>call:CREATE_TODO_LIST"
        )
        markers.append(
            "call:INTERNAL_ACTION_TODO_LIST"
        )
        markers.append(
            "call:INTERNAL_ACTION_CREATE_TODO_LIST"
        )
        markers.append(
            "call:CREATE_TODO_LIST"
        )

    if RUNTIME_ACTION_RESOLVE_TODO in enabled_action_names:
        markers.append(
            "<RESOLVE_TODO:"
        )
        markers.append(
            "<INTERNAL_ACTION_RESOLVE_TODO:"
        )
        markers.append(
            "INTERNAL_ACTION_RESOLVE_TODO:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_RESOLVE_TODO:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_RESOLVE_TODO:"
        )
        markers.append(
            "<|tool_call>call:RESOLVE_TODO:"
        )
        markers.append(
            "<tool_call>call:RESOLVE_TODO:"
        )
        markers.append(
            "call:INTERNAL_ACTION_RESOLVE_TODO:"
        )
        markers.append(
            "call:RESOLVE_TODO:"
        )

    if RUNTIME_ACTION_CHECK_TODO in enabled_action_names:
        markers.append(
            "<CHECK_TODO:"
        )
        markers.append(
            "<INTERNAL_ACTION_CHECK_TODO:"
        )
        markers.append(
            "INTERNAL_ACTION_CHECK_TODO:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_CHECK_TODO:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_CHECK_TODO:"
        )
        markers.append(
            "<|tool_call>call:CHECK_TODO:"
        )
        markers.append(
            "<tool_call>call:CHECK_TODO:"
        )
        markers.append(
            "call:INTERNAL_ACTION_CHECK_TODO:"
        )
        markers.append(
            "call:CHECK_TODO:"
        )

    if RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT in enabled_action_names:
        markers.append(
            "<SAVE_DELAYED_MEMORY_CONTENT>"
        )
        markers.append(
            "</SAVE_DELAYED_MEMORY_CONTENT>"
        )
        markers.append(
            "<INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>"
        )
        markers.append(
            "</INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT>"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT"
        )
        markers.append(
            "<|tool_call>call:SAVE_DELAYED_MEMORY_CONTENT"
        )
        markers.append(
            "<tool_call>call:SAVE_DELAYED_MEMORY_CONTENT"
        )
        markers.append(
            "call:INTERNAL_ACTION_SAVE_DELAYED_MEMORY_CONTENT"
        )
        markers.append(
            "call:SAVE_DELAYED_MEMORY_CONTENT"
        )

    if RUNTIME_ACTION_LIST_DELAYED_MEMORY in enabled_action_names:
        markers.append(
            "<LIST_DELAYED_MEMORY>"
        )
        markers.append(
            "<INTERNAL_ACTION_LIST_DELAYED_MEMORY>"
        )
        markers.append(
            "<INTERNAL_ACTION_LIST_DELAYED_MEMORY"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_LIST_DELAYED_MEMORY"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_LIST_DELAYED_MEMORY"
        )
        markers.append(
            "<|tool_call>call:LIST_DELAYED_MEMORY"
        )
        markers.append(
            "<tool_call>call:LIST_DELAYED_MEMORY"
        )
        markers.append(
            "call:INTERNAL_ACTION_LIST_DELAYED_MEMORY"
        )
        markers.append(
            "call:LIST_DELAYED_MEMORY"
        )

    if RUNTIME_ACTION_APPEND_DELAYED_MEMORY in enabled_action_names:
        markers.append(
            "<APPEND_DELAYED_MEMORY:"
        )
        markers.append(
            "<INTERNAL_ACTION_APPEND_DELAYED_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_APPEND_DELAYED_MEMORY:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_APPEND_DELAYED_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:APPEND_DELAYED_MEMORY:"
        )
        markers.append(
            "<tool_call>call:APPEND_DELAYED_MEMORY:"
        )
        markers.append(
            "call:INTERNAL_ACTION_APPEND_DELAYED_MEMORY:"
        )
        markers.append(
            "call:APPEND_DELAYED_MEMORY:"
        )

    if RUNTIME_ACTION_REMOVE_DELAYED_MEMORY in enabled_action_names:
        markers.append(
            "<REMOVE_DELAYED_MEMORY:"
        )
        markers.append(
            "<INTERNAL_ACTION_REMOVE_DELAYED_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_REMOVE_DELAYED_MEMORY:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_REMOVE_DELAYED_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:REMOVE_DELAYED_MEMORY:"
        )
        markers.append(
            "<tool_call>call:REMOVE_DELAYED_MEMORY:"
        )
        markers.append(
            "call:INTERNAL_ACTION_REMOVE_DELAYED_MEMORY:"
        )
        markers.append(
            "call:REMOVE_DELAYED_MEMORY:"
        )

    if RUNTIME_ACTION_ASSET_ACTION in enabled_action_names:
        markers.append(
            "<ASSET_ACTION>"
        )
        markers.append(
            "< ASSET_ACTION"
        )
        markers.append(
            "</ASSET_ACTION>"
        )
        markers.append(
            "< /ASSET_ACTION"
        )
        markers.append(
            "< / ASSET_ACTION"
        )
        markers.append(
            "<INTERNAL_ACTION_ASSET_ACTION>"
        )
        markers.append(
            "< INTERNAL_ACTION_ASSET_ACTION"
        )
        markers.append(
            "</INTERNAL_ACTION_ASSET_ACTION>"
        )
        markers.append(
            "< /INTERNAL_ACTION_ASSET_ACTION"
        )
        markers.append(
            "< / INTERNAL_ACTION_ASSET_ACTION"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_ASSET_ACTION"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_ASSET_ACTION"
        )
        markers.append(
            "<|tool_call>call:ASSET_ACTION"
        )
        markers.append(
            "<tool_call>call:ASSET_ACTION"
        )
        markers.append(
            "call:INTERNAL_ACTION_ASSET_ACTION"
        )
        markers.append(
            "call:ASSET_ACTION"
        )

    if RUNTIME_ACTION_CREATE_ACTIVE_MEMORY in enabled_action_names:
        markers.append(
            "<CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<tool_call>call:CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "call:INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )
        markers.append(
            "call:CREATE_ACTIVE_MEMORY:"
        )

    if RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY in enabled_action_names:
        markers.append(
            "<RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<|tool_call>call:RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "<tool_call>call:RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "call:INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY:"
        )
        markers.append(
            "call:RESOLVE_ACTIVE_MEMORY:"
        )

    if RUNTIME_ACTION_WEB_SEARCH in enabled_action_names:
        markers.append(
            "<WEB_SEARCH:"
        )
        markers.append(
            "<INTERNAL_ACTION_WEB_SEARCH:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_WEB_SEARCH:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_WEB_SEARCH:"
        )
        markers.append(
            "<|tool_call>call:WEB_SEARCH:"
        )
        markers.append(
            "<tool_call>call:WEB_SEARCH:"
        )
        markers.append(
            "call:INTERNAL_ACTION_WEB_SEARCH:"
        )
        markers.append(
            "call:WEB_SEARCH:"
        )

    if RUNTIME_ACTION_LIST_SKILLS in enabled_action_names:
        markers.append(
            "<LIST_SKILLS:"
        )
        markers.append(
            "<LIST_SKILLS>"
        )
        markers.append(
            "<INTERNAL_ACTION_LIST_SKILLS:"
        )
        markers.append(
            "<INTERNAL_ACTION_LIST_SKILLS>"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_LIST_SKILLS:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_LIST_SKILLS:"
        )
        markers.append(
            "<|tool_call>call:LIST_SKILLS:"
        )
        markers.append(
            "<tool_call>call:LIST_SKILLS:"
        )
        markers.append(
            "call:INTERNAL_ACTION_LIST_SKILLS:"
        )
        markers.append(
            "call:LIST_SKILLS:"
        )

    if RUNTIME_ACTION_HIDE_SKILLS in enabled_action_names:
        markers.append(
            "<HIDE_SKILLS>"
        )
        markers.append(
            "<INTERNAL_ACTION_HIDE_SKILLS>"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_HIDE_SKILLS"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_HIDE_SKILLS"
        )
        markers.append(
            "<|tool_call>call:HIDE_SKILLS"
        )
        markers.append(
            "<tool_call>call:HIDE_SKILLS"
        )
        markers.append(
            "call:INTERNAL_ACTION_HIDE_SKILLS"
        )
        markers.append(
            "call:HIDE_SKILLS"
        )

    if RUNTIME_ACTION_CLEAN_TOOL_RESULTS in enabled_action_names:
        markers.append(
            "<CLEAN_TOOL_RESULTS>"
        )
        markers.append(
            "<INTERNAL_ACTION_CLEAN_TOOL_RESULTS>"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_CLEAN_TOOL_RESULTS"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_CLEAN_TOOL_RESULTS"
        )
        markers.append(
            "<|tool_call>call:CLEAN_TOOL_RESULTS"
        )
        markers.append(
            "<tool_call>call:CLEAN_TOOL_RESULTS"
        )
        markers.append(
            "call:INTERNAL_ACTION_CLEAN_TOOL_RESULTS"
        )
        markers.append(
            "call:CLEAN_TOOL_RESULTS"
        )

    if RUNTIME_ACTION_APPEND_SKILL in enabled_action_names:
        markers.append(
            "<APPEND_SKILL"
        )
        markers.append(
            "<APPEND_SKILL:"
        )
        markers.append(
            "<APPEND_SKILLS"
        )
        markers.append(
            "<APPEND_SKILLS:"
        )
        markers.append(
            "<INTERNAL_ACTION_APPEND_SKILL"
        )
        markers.append(
            "<INTERNAL_ACTION_APPEND_SKILL:"
        )
        markers.append(
            "<INTERNAL_ACTION_APPEND_SKILLS"
        )
        markers.append(
            "<INTERNAL_ACTION_APPEND_SKILLS:"
        )
        markers.append(
            "INTERNAL_ACTION_APPEND_SKILL:"
        )
        markers.append(
            "INTERNAL_ACTION_APPEND_SKILLS:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_APPEND_SKILL:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_APPEND_SKILL:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_APPEND_SKILLS:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_APPEND_SKILLS:"
        )
        markers.append(
            "<|tool_call>call:APPEND_SKILL:"
        )
        markers.append(
            "<tool_call>call:APPEND_SKILL:"
        )
        markers.append(
            "<|tool_call>call:APPEND_SKILLS:"
        )
        markers.append(
            "<tool_call>call:APPEND_SKILLS:"
        )
        markers.append(
            "call:INTERNAL_ACTION_APPEND_SKILL:"
        )
        markers.append(
            "call:APPEND_SKILL:"
        )
        markers.append(
            "call:INTERNAL_ACTION_APPEND_SKILLS:"
        )
        markers.append(
            "call:APPEND_SKILLS:"
        )

    if RUNTIME_ACTION_REMOVE_SKILL in enabled_action_names:
        markers.append(
            "<REMOVE_SKILL:"
        )
        markers.append(
            "<REMOVE_SKILLS:"
        )
        markers.append(
            "<INTERNAL_ACTION_REMOVE_SKILL:"
        )
        markers.append(
            "<INTERNAL_ACTION_REMOVE_SKILLS:"
        )
        markers.append(
            "INTERNAL_ACTION_REMOVE_SKILL:"
        )
        markers.append(
            "INTERNAL_ACTION_REMOVE_SKILLS:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_REMOVE_SKILL:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_REMOVE_SKILL:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_REMOVE_SKILLS:"
        )
        markers.append(
            "<tool_call>call:INTERNAL_ACTION_REMOVE_SKILLS:"
        )
        markers.append(
            "<|tool_call>call:REMOVE_SKILL:"
        )
        markers.append(
            "<tool_call>call:REMOVE_SKILL:"
        )
        markers.append(
            "<|tool_call>call:REMOVE_SKILLS:"
        )
        markers.append(
            "<tool_call>call:REMOVE_SKILLS:"
        )
        markers.append(
            "call:INTERNAL_ACTION_REMOVE_SKILL:"
        )
        markers.append(
            "call:REMOVE_SKILL:"
        )
        markers.append(
            "call:INTERNAL_ACTION_REMOVE_SKILLS:"
        )
        markers.append(
            "call:REMOVE_SKILLS:"
        )

    return tuple(
        markers
    )


def _trailing_marker_prefix_length(
    text: str,
    enabled_actions=None,
) -> int:

    markers = _enabled_action_start_markers(
        enabled_actions
    )
    upper_text = text.upper()
    upper_markers = tuple(
        marker.upper()
        for marker in markers
    )

    max_length = min(
        len(text),
        max(
            [
                len(marker)
                for marker in markers
            ],
            default=0,
        ),
    )

    for length in range(
        max_length,
        0,
        -1,
    ):

        for marker in upper_markers:

            if length > len(marker):
                continue

            if (
                length == len(marker)
                and marker.startswith("</")
            ):
                continue

            if not upper_text.endswith(
                marker[:length]
            ):
                continue

            marker_start = len(text) - length

            if not marker.startswith("<"):
                line_start = max(
                    text.rfind("\n", 0, marker_start),
                    text.rfind("\r", 0, marker_start),
                ) + 1

                if text[line_start:marker_start].strip():
                    continue

            return length

    return 0


def _action_text_may_contain_marker(
    text: str,
) -> bool:

    if not text:
        return False

    upper_text = text.upper()

    return (
        "INTERNAL_ACTION_" in upper_text
        or "CALL:" in upper_text
        or "TODO_LIST" in upper_text
        or "DELAYED_MEMORY" in upper_text
        or any(
            action_name in upper_text
            for action_name in KNOWN_RUNTIME_ACTIONS
        )
    )


def _extract_runtime_actions_if_needed(
    text: str,
    *,
    enabled_actions=None,
    preserve_action_text: bool = False,
    seen_action_keys=None,
    preserve_action_marker=None,
    repetition_guard: RuntimeActionRepetitionGuard | None = None,
) -> RuntimeActionResult:

    if not text:
        return RuntimeActionResult(
            text="",
        )

    if not _action_text_may_contain_marker(
        text
    ):
        return RuntimeActionResult(
            text=text,
        )

    return extract_runtime_actions(
        text,
        enabled_actions=enabled_actions,
        preserve_action_text=preserve_action_text,
        seen_action_keys=seen_action_keys,
        preserve_action_marker=preserve_action_marker,
        repetition_guard=repetition_guard,
    )


def _unclosed_bracketed_internal_action_start(
    text: str,
) -> int | None:

    marker_start = text.rfind(
        "<"
    )

    if marker_start < 0:
        return None

    candidate = text[
        marker_start + 1:
    ]

    if (
        "<" in candidate
        or ">" in candidate
        or "\n" in candidate
        or "\r" in candidate
    ):
        return None

    normalized = (
        candidate
        .lstrip()
        .upper()
    )

    action_name = normalized

    if action_name.startswith(
        "INTERNAL_ACTION_"
    ):
        action_name = action_name[
            len("INTERNAL_ACTION_"):
        ]

    for known_action in KNOWN_RUNTIME_ACTIONS:
        if action_name.startswith(
            known_action
        ):
            return marker_start

    return None


def _unclosed_tool_call_internal_action_start(
    text: str,
) -> int | None:

    upper_text = text.upper()
    marker_candidates = (
        (
            upper_text.rfind(
                "<|TOOL_CALL>"
            ),
            len("<|tool_call>"),
        ),
        (
            upper_text.rfind(
                "<TOOL_CALL>"
            ),
            len("<tool_call>"),
        ),
    )
    marker_start, marker_length = max(
        marker_candidates,
        key=lambda item: item[0],
    )

    if marker_start < 0:
        return None

    candidate = text[
        marker_start:
    ]

    after_prefix = candidate[
        marker_length:
    ]

    if ">" in after_prefix:
        return None

    normalized = (
        after_prefix
        .lstrip()
        .upper()
    )

    if not normalized.startswith(
        "CALL:"
    ):
        return None

    action_name = normalized[
        len("CALL:"):
    ]

    if action_name.startswith(
        "INTERNAL_ACTION_"
    ):
        action_name = action_name[
            len("INTERNAL_ACTION_"):
        ]

    for known_action in KNOWN_RUNTIME_ACTIONS:
        if action_name.startswith(
            known_action
        ):
            return marker_start

    return None


def _unclosed_delayed_memory_action_start(
    text: str,
) -> int | None:

    upper_text = text.upper()
    marker_starts = [
        upper_text.rfind(
            marker
        )
        for marker in (
            "<LIST_DELAYED_MEMORY",
            "<INTERNAL_ACTION_LIST_DELAYED_MEMORY",
            "<APPEND_DELAYED_MEMORY:",
            "<INTERNAL_ACTION_APPEND_DELAYED_MEMORY:",
            "<REMOVE_DELAYED_MEMORY:",
            "<INTERNAL_ACTION_REMOVE_DELAYED_MEMORY:",
        )
    ]
    marker_start = max(
        marker_starts
    )

    if marker_start < 0:
        return None

    candidate = text[
        marker_start:
    ]

    if (
        ">" in candidate
        or "\n" in candidate
        or "\r" in candidate
    ):
        return None

    if "<" in candidate[1:]:
        return None

    return marker_start


def _unclosed_delayed_memory_content_block_start(
    text: str,
) -> int | None:

    opening_match = None

    for match in DELAYED_MEMORY_BLOCK_START_RE.finditer(
        text
    ):
        opening_match = match

    if opening_match is None:
        return None

    closing_match = None

    for match in DELAYED_MEMORY_BLOCK_END_RE.finditer(
        text,
        opening_match.end(),
    ):
        closing_match = match
        break

    if closing_match is not None:
        return None

    return opening_match.start()


def _unclosed_asset_action_block_start(
    text: str,
) -> int | None:

    opening_match = None
    opening_end = 0

    for match in ASSET_ACTION_BLOCK_TAG_RE.finditer(
        text
    ):
        if match.group(
            "slash"
        ):
            opening_match = None
            opening_end = 0
            continue

        if opening_match is None:
            opening_match = match
            opening_end = match.end()
            continue

        payload = text[
            opening_end:match.start()
        ].strip()

        if payload:
            opening_match = None
            opening_end = 0
            continue

        opening_match = match
        opening_end = match.end()

    if opening_match is None:
        return None

    return opening_match.start()


def _unclosed_create_todo_block_start(
    text: str,
) -> int | None:

    opening_match = None

    for match in CREATE_TODO_BLOCK_START_RE.finditer(
        text
    ):
        opening_match = match

    if opening_match is None:
        return None

    closing_match = None

    for match in CREATE_TODO_BLOCK_END_RE.finditer(
        text,
        opening_match.end(),
    ):
        closing_match = match
        break

    if closing_match is not None:
        return None

    return opening_match.start()


def _unclosed_internal_action_request_start(
    text: str,
    enabled_actions=None,
) -> int | None:

    for detector in (
        _unclosed_create_todo_block_start,
        _unclosed_asset_action_block_start,
        _unclosed_delayed_memory_content_block_start,
        _unclosed_delayed_memory_action_start,
        _unclosed_bracketed_internal_action_start,
        _unclosed_tool_call_internal_action_start,
    ):
        marker_start = detector(
            text
        )

        if marker_start is not None:
            candidate = text[
                marker_start:
            ].upper()

            for marker in _enabled_action_start_markers(
                enabled_actions
            ):
                normalized_marker = marker.upper()

                if (
                    candidate.startswith(
                        normalized_marker
                    )
                    or normalized_marker.startswith(
                        candidate
                    )
                ):
                    return marker_start

    return None


class RuntimeActionStreamFilter:

    def __init__(
        self,
        enabled_actions=None,
        preserve_action_text: bool = False,
        preserve_action_marker=None,
        repetition_guard: RuntimeActionRepetitionGuard | None = None,
    ):
        self.pending = ""
        self.pending_is_action = False
        self.preserve_action_text = preserve_action_text
        self.preserve_action_marker = preserve_action_marker
        self.repetition_guard = repetition_guard
        self.seen_action_keys = set()
        self.pending_started_actions = set()
        self.enabled_actions = normalize_runtime_action_names(
            enabled_actions
        )

    def _build_started_actions(
        self,
        text: str,
        marker_start: int,
    ) -> tuple[RuntimeActionCall, ...]:

        block_actions = (
            (
                RUNTIME_ACTION_ASSET_ACTION,
                ASSET_ACTION_BLOCK_START_RE,
            ),
            (
                RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
                DELAYED_MEMORY_BLOCK_START_RE,
            ),
        )

        for action_name, start_pattern in block_actions:
            if action_name not in self.enabled_actions:
                continue

            if not start_pattern.match(
                text,
                marker_start,
            ):
                continue

            if action_name in self.pending_started_actions:
                return ()

            self.pending_started_actions.add(
                action_name
            )

            return (
                RuntimeActionCall(
                    name=action_name,
                ),
            )

        return ()

    def _find_started_actions(
        self,
        text: str,
    ) -> tuple[RuntimeActionCall, ...]:

        marker_starts = []

        for start_pattern in (
            ASSET_ACTION_BLOCK_START_RE,
            DELAYED_MEMORY_BLOCK_START_RE,
        ):
            match = start_pattern.search(
                text
            )

            if match is not None:
                marker_starts.append(
                    match.start()
                )

        started_actions = []

        for marker_start in sorted(
            set(marker_starts)
        ):
            started_actions.extend(
                self._build_started_actions(
                    text,
                    marker_start,
                )
            )

        return tuple(
            started_actions
        )

    @staticmethod
    def _attach_started_actions(
        result: RuntimeActionResult,
        started_actions,
    ) -> RuntimeActionResult:

        if not started_actions:
            return result

        return RuntimeActionResult(
            text=result.text,
            started_actions=tuple(
                started_actions
            ),
            observed_actions=result.observed_actions,
            actions=result.actions,
            removed_markers=result.removed_markers,
            marker_repetition_exceeded=(
                result.marker_repetition_exceeded
            ),
            marker_repetition_reason=(
                result.marker_repetition_reason
            ),
        )

    def filter(
        self,
        chunk: str,
    ) -> RuntimeActionResult:

        if not chunk:
            return RuntimeActionResult(
                text="",
            )

        combined = (
            self.pending
            + chunk
        )

        if not self.pending:
            hold_length = _trailing_marker_prefix_length(
                combined,
                enabled_actions=self.enabled_actions,
            )

            if hold_length:

                self.pending = combined[
                    -hold_length:
                ]

                ready_text = combined[
                    :-hold_length
                ]
                started_actions = self._find_started_actions(
                    ready_text
                )
                result = _extract_runtime_actions_if_needed(
                    ready_text,
                    enabled_actions=self.enabled_actions,
                    preserve_action_text=self.preserve_action_text,
                    seen_action_keys=self.seen_action_keys,
                    preserve_action_marker=self.preserve_action_marker,
                    repetition_guard=self.repetition_guard,
                )

                self.pending_started_actions.clear()

                return self._attach_started_actions(
                    result,
                    started_actions,
                )

        if (
            not self.pending
            and not _action_text_may_contain_marker(
                chunk
            )
            and "<" not in chunk
        ):
            return RuntimeActionResult(
                text=chunk,
            )

        if (
            self.pending
            and self.pending_is_action
            and ">" not in chunk
            and "\n" not in chunk
            and "\r" not in chunk
        ):
            self.pending += chunk

            return RuntimeActionResult(
                text="",
            )

        self.pending = ""
        self.pending_is_action = False
        started_actions = self._find_started_actions(
            combined
        )

        unclosed_start = _unclosed_internal_action_request_start(
            combined,
            enabled_actions=self.enabled_actions,
        )

        if unclosed_start is not None:

            self.pending = combined[
                unclosed_start:
            ]
            self.pending_is_action = True

            result = _extract_runtime_actions_if_needed(
                combined[
                    :unclosed_start
                ],
                enabled_actions=self.enabled_actions,
                preserve_action_text=self.preserve_action_text,
                seen_action_keys=self.seen_action_keys,
                preserve_action_marker=self.preserve_action_marker,
                repetition_guard=self.repetition_guard,
            )

            return self._attach_started_actions(
                result,
                started_actions,
            )

        hold_length = _trailing_marker_prefix_length(
            combined,
            enabled_actions=self.enabled_actions,
        )

        if hold_length:

            self.pending = combined[
                -hold_length:
            ]

            result = _extract_runtime_actions_if_needed(
                combined[
                    :-hold_length
                ],
                enabled_actions=self.enabled_actions,
                preserve_action_text=self.preserve_action_text,
                seen_action_keys=self.seen_action_keys,
                preserve_action_marker=self.preserve_action_marker,
                repetition_guard=self.repetition_guard,
            )

            self.pending_started_actions.clear()

            return self._attach_started_actions(
                result,
                started_actions,
            )

        result = _extract_runtime_actions_if_needed(
            combined,
            enabled_actions=self.enabled_actions,
            preserve_action_text=self.preserve_action_text,
            seen_action_keys=self.seen_action_keys,
            preserve_action_marker=self.preserve_action_marker,
            repetition_guard=self.repetition_guard,
        )

        self.pending_started_actions.clear()

        return self._attach_started_actions(
            result,
            started_actions,
        )

    def flush_result(self) -> RuntimeActionResult:

        pending = self.pending
        self.pending = ""
        self.pending_is_action = False
        self.pending_started_actions.clear()

        if self.preserve_action_text:
            return RuntimeActionResult(
                text=pending,
            )

        delayed_memory_start = DELAYED_MEMORY_BLOCK_START_RE.match(
            pending
        )

        if (
            delayed_memory_start is not None
            and not DELAYED_MEMORY_BLOCK_END_RE.search(
                pending,
                delayed_memory_start.end(),
            )
        ):
            payload = pending[
                delayed_memory_start.end():
            ].strip()

            present_fields = {
                str(
                    match.group(1)
                    or ""
                ).strip().casefold()
                for match in DELAYED_MEMORY_FIELD_RE.finditer(
                    payload
                )
            }

            if (
                {
                    "title",
                    "summary",
                    "tags",
                    "body",
                }.issubset(
                    present_fields
                )
                and parse_delayed_memory_content_payload(
                    payload
                )
            ):
                pending = (
                    pending.rstrip()
                    + "\n</SAVE_DELAYED_MEMORY_CONTENT>"
                )

        if _unclosed_internal_action_request_start(
            pending,
            enabled_actions=self.enabled_actions,
        ) == 0:
            result = extract_runtime_actions(
                pending,
                enabled_actions=self.enabled_actions,
                preserve_action_text=False,
                preserve_action_marker=self.preserve_action_marker,
                repetition_guard=self.repetition_guard,
            )

            if result.actions:
                return result

            return RuntimeActionResult(
                text="",
                removed_markers=(
                    pending,
                ) if pending else (),
            )

        return extract_runtime_actions(
            pending,
            enabled_actions=self.enabled_actions,
            preserve_action_text=False,
            preserve_action_marker=self.preserve_action_marker,
            repetition_guard=self.repetition_guard,
        )

    def flush(self) -> str:

        return self.flush_result().text
