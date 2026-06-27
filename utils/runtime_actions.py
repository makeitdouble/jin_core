import json
import re
import secrets
import string
from dataclasses import dataclass
from datetime import datetime

from rules import runtime as runtime_rules
from rules.runtime import (
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)


KNOWN_RUNTIME_ACTIONS = tuple(
    sorted(
        (
            RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
            RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
            RUNTIME_ACTION_WEB_SEARCH,
            RUNTIME_ACTION_SAVE_SESSION,
        )
    )
)

BRACKETED_INTERNAL_ACTION_PATTERN = re.compile(
    (
        r"(?:"
        r"<\s*INTERNAL_ACTION_"
        r"(?P<bracketed_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY)"
        r"(?:\s*:\s*(?P<bracketed_query>[^\r\n>]*?))?"
        r"\s*>+"
        r"|"
        r"(?m:^\s*INTERNAL_ACTION_"
        r"(?P<bare_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY)"
        r"(?:\s*:\s*(?P<bare_query>[^\r\n]*))?"
        r"\s*$)"
        r")"
    ),
    re.IGNORECASE,
)

MALFORMED_CALL_INTERNAL_ACTION_PATTERN = re.compile(
    (
        r"(?:"
        r"<\|tool_call\>\s*call\s*:\s*INTERNAL_ACTION_"
        r"(?P<tool_call_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY)"
        r"(?:\s*:\s*(?P<tool_call_query>[^\r\n>]*?))?"
        r"\s*>+"
        r"|"
        r"(?m:^\s*call\s*:\s*INTERNAL_ACTION_"
        r"(?P<bare_call_name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY|RESOLVE_ACTIVE_MEMORY)"
        r"(?:\s*:\s*(?P<bare_call_query>[^\r\n]*))?"
        r"\s*$)"
        r")"
    ),
    re.IGNORECASE,
)

CREATE_ACTIVE_MEMORY_MARKER_RE = re.compile(
    (
        r"^\s*<?\s*INTERNAL_ACTION_CREATE_ACTIVE_MEMORY"
        r"\s*:\s*(?P<fields>.*?)\s*>+\s*$"
        r"|"
        r"^\s*INTERNAL_ACTION_CREATE_ACTIVE_MEMORY"
        r"\s*:\s*(?P<bare_fields>[^\r\n]*)\s*$"
    ),
    re.IGNORECASE,
)

INTERNAL_ACTION_WITH_PAYLOAD_MARKER_RE = re.compile(
    (
        r"^\s*<?\s*INTERNAL_ACTION_[A-Z_]+"
        r"\s*:\s*(?P<payload>.*?)\s*>+\s*$"
        r"|"
        r"^\s*INTERNAL_ACTION_[A-Z_]+"
        r"\s*:\s*(?P<bare_payload>[^\r\n]*)\s*$"
    ),
    re.IGNORECASE,
)

ACTIVE_MEMORY_SLOT_ID_RE = re.compile(
    r"^[a-z0-9]{6}$",
)

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
    "created_jin_message_number",
    "elapsed_time",
    "elapsed_jin_message_number",
)

ACTIVE_MEMORY_LIFECYCLE_SUFFIX_RE = re.compile(
    (
        r"\s*\[\s*"
        r"(?:creation_time|created_jin_message_number|"
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
    created_jin_message_number: int,
    elapsed_time: str,
    elapsed_jin_message_number: int,
) -> str:

    values = {
        "creation_time": creation_time,
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

        if add_runtime_user_idle_to_elapsed:
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

    used_ids = {
        str(active_memory_id or "").strip().casefold()
        for active_memory_id in (existing_ids or ())
        if ACTIVE_MEMORY_SLOT_ID_RE.fullmatch(
            str(active_memory_id or "").strip().casefold()
        )
    }

    while True:
        active_memory_id = "".join(
            secrets.choice(
                ACTIVE_MEMORY_SLOT_ID_ALPHABET
            )
            for _ in range(6)
        )

        if active_memory_id not in used_ids:
            return active_memory_id


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


@dataclass(frozen=True)
class RuntimeActionCall:
    name: str
    payload: str = ""


@dataclass(frozen=True)
class RuntimeActionResult:
    text: str
    actions: tuple[RuntimeActionCall, ...] = ()
    removed_markers: tuple[str, ...] = ()

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
        "SAVE_ACTIVE_MEMORY": RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
        "RESOLVE_ACTIVE_MEMORY": RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY,
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

    if normalized_name == RUNTIME_ACTION_WEB_SEARCH:
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
) -> RuntimeActionResult:

    if not text:
        return RuntimeActionResult(
            text="",
        )

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )
    actions = []
    removed_markers = []

    if seen_action_keys is None:
        seen_action_keys = set()

    def handle_marker(
        raw_marker: str,
        action_name: str,
        query: str = "",
    ) -> str:

        if not preserve_action_text:
            removed_markers.append(
                raw_marker
            )

        action = _build_internal_action_call(
            action_name,
            query,
        )

        if (
            action is not None
            and action.name in enabled_action_names
        ):
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

        return (
            raw_marker
            if preserve_action_text
            else ""
        )

    def replace_private_marker(match):

        return handle_marker(
            match.group(0),
            match.group("bracketed_name")
            or match.group("bare_name"),
            match.group("bracketed_query")
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

    clean_text = _replace_runtime_action_matches(
        text,
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
        actions=tuple(
            actions
        ),
        removed_markers=tuple(
            removed_markers
        ),
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

    if RUNTIME_ACTION_SAVE_SESSION in enabled_action_names:
        markers.append(
            "<INTERNAL_ACTION_SAVE_SESSION>"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_SAVE_SESSION"
        )
        markers.append(
            "call:INTERNAL_ACTION_SAVE_SESSION"
        )

    if RUNTIME_ACTION_CREATE_ACTIVE_MEMORY in enabled_action_names:
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
            "call:INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )

    if RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY in enabled_action_names:
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
            "call:INTERNAL_ACTION_RESOLVE_ACTIVE_MEMORY:"
        )

    if RUNTIME_ACTION_WEB_SEARCH in enabled_action_names:
        markers.append(
            "<INTERNAL_ACTION_WEB_SEARCH:"
        )
        markers.append(
            "<|tool_call>call:INTERNAL_ACTION_WEB_SEARCH:"
        )
        markers.append(
            "call:INTERNAL_ACTION_WEB_SEARCH:"
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

            if upper_text.endswith(
                marker[:length]
            ):
                return length

    return 0


def _action_text_may_contain_marker(
    text: str,
) -> bool:

    if not text:
        return False

    return (
        "INTERNAL_ACTION_"
        in text.upper()
    )


def _extract_runtime_actions_if_needed(
    text: str,
    *,
    enabled_actions=None,
    preserve_action_text: bool = False,
    seen_action_keys=None,
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
    ):
        return None

    normalized = (
        candidate
        .lstrip()
        .upper()
    )

    if not normalized.startswith(
        "INTERNAL_ACTION_"
    ):
        return None

    action_name = normalized[
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
    marker_start = upper_text.rfind(
        "<|TOOL_CALL>"
    )

    if marker_start < 0:
        return None

    candidate = text[
        marker_start:
    ]

    after_prefix = candidate[
        len("<|tool_call>"):
    ]

    if ">" in after_prefix:
        return None

    normalized = (
        after_prefix
        .lstrip()
        .upper()
    )

    if not normalized.startswith(
        "CALL:INTERNAL_ACTION_"
    ):
        return None

    action_name = normalized[
        len("CALL:INTERNAL_ACTION_"):
    ]

    for known_action in KNOWN_RUNTIME_ACTIONS:
        if action_name.startswith(
            known_action
        ):
            return marker_start

    return None


def _unclosed_internal_action_request_start(
    text: str,
) -> int | None:

    for detector in (
        _unclosed_bracketed_internal_action_start,
        _unclosed_tool_call_internal_action_start,
    ):
        marker_start = detector(
            text
        )

        if marker_start is not None:
            return marker_start

    return None


class RuntimeActionStreamFilter:

    def __init__(
        self,
        enabled_actions=None,
        preserve_action_text: bool = False,
    ):
        self.pending = ""
        self.pending_is_action = False
        self.preserve_action_text = preserve_action_text
        self.seen_action_keys = set()
        self.enabled_actions = normalize_runtime_action_names(
            enabled_actions
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

                return _extract_runtime_actions_if_needed(
                    combined[
                        :-hold_length
                    ],
                    enabled_actions=self.enabled_actions,
                    preserve_action_text=self.preserve_action_text,
                    seen_action_keys=self.seen_action_keys,
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
            and "<" not in chunk
            and ">" not in chunk
        ):
            self.pending += chunk

            return RuntimeActionResult(
                text="",
            )

        self.pending = ""
        self.pending_is_action = False

        unclosed_start = _unclosed_internal_action_request_start(
            combined
        )

        if unclosed_start is not None:

            self.pending = combined[
                unclosed_start:
            ]
            self.pending_is_action = True

            return _extract_runtime_actions_if_needed(
                combined[
                    :unclosed_start
                ],
                enabled_actions=self.enabled_actions,
                preserve_action_text=self.preserve_action_text,
                seen_action_keys=self.seen_action_keys,
            )

        hold_length = _trailing_marker_prefix_length(
            combined,
            enabled_actions=self.enabled_actions,
        )

        if hold_length:

            self.pending = combined[
                -hold_length:
            ]

            return _extract_runtime_actions_if_needed(
                combined[
                    :-hold_length
                ],
                enabled_actions=self.enabled_actions,
                preserve_action_text=self.preserve_action_text,
                seen_action_keys=self.seen_action_keys,
            )

        return _extract_runtime_actions_if_needed(
            combined,
            enabled_actions=self.enabled_actions,
            preserve_action_text=self.preserve_action_text,
            seen_action_keys=self.seen_action_keys,
        )

    def flush_result(self) -> RuntimeActionResult:

        pending = self.pending
        self.pending = ""
        self.pending_is_action = False

        if self.preserve_action_text:
            return RuntimeActionResult(
                text=pending,
            )

        if _unclosed_internal_action_request_start(
            pending
        ) == 0:
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
        )

    def flush(self) -> str:

        return self.flush_result().text
