import json
import re
from dataclasses import dataclass

from rules import runtime as runtime_rules
from rules.runtime import (
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)


KNOWN_RUNTIME_ACTIONS = tuple(
    sorted(
        (
            RUNTIME_ACTION_CREATE_ACTIVE_MEMORY,
            RUNTIME_ACTION_WEB_SEARCH,
            RUNTIME_ACTION_SAVE_SESSION,
        )
    )
)

BRACKETED_INTERNAL_ACTION_PATTERN = re.compile(
    (
        r"<\s*INTERNAL_ACTION_"
        r"(?P<name>WEB_SEARCH|SAVE_SESSION|CREATE_ACTIVE_MEMORY)"
        r"(?:\s*:\s*(?P<query>[^>]*?))?"
        r"\s*>+"
    ),
    re.IGNORECASE,
)

CREATE_ACTIVE_MEMORY_MARKER_RE = re.compile(
    (
        r"^\s*<\s*INTERNAL_ACTION_CREATE_ACTIVE_MEMORY"
        r"\s*:\s*(?P<fields>.*?)\s*>+\s*$"
    ),
    re.IGNORECASE,
)

INTERNAL_ACTION_WITH_PAYLOAD_MARKER_RE = re.compile(
    (
        r"^\s*<\s*INTERNAL_ACTION_[A-Z_]+"
        r"\s*:\s*(?P<payload>.*?)\s*>+\s*$"
    ),
    re.IGNORECASE,
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

    return " | ".join(
        part.strip()
        for part in match.group("payload").split("|")
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

    fields = []

    for field in match.group("fields").split("|"):
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

    return " | ".join(
        field.strip()
        for field in match.group("fields").split("|")
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

    for action_name in candidates:

        normalized_name = normalize_runtime_action_name(
            action_name
        )

        if (
            normalized_name in KNOWN_RUNTIME_ACTIONS
            and normalized_name not in actions
        ):
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
) -> RuntimeActionResult:

    if not text:
        return RuntimeActionResult(
            text="",
        )

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )
    actions = []

    def replace_marker(match):

        action = _build_internal_action_call(
            match.group(
                "name"
            ),
            match.groupdict().get(
                "query",
                "",
            ),
        )

        if (
            action is not None
            and action.name in enabled_action_names
        ):
            actions.append(
                action
            )

        return (
            match.group(0)
            if preserve_action_text
            else ""
        )

    clean_text = _replace_runtime_action_matches(
        text,
        BRACKETED_INTERNAL_ACTION_PATTERN,
        replace_marker,
    )

    return RuntimeActionResult(
        text=clean_text,
        actions=tuple(
            actions
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

    if RUNTIME_ACTION_CREATE_ACTIVE_MEMORY in enabled_action_names:
        markers.append(
            "<INTERNAL_ACTION_CREATE_ACTIVE_MEMORY:"
        )

    if RUNTIME_ACTION_WEB_SEARCH in enabled_action_names:
        markers.append(
            "<INTERNAL_ACTION_WEB_SEARCH:"
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
                len(marker) - 1
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

    if (
        not text
        or "<" not in text
    ):
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


def _unclosed_internal_action_request_start(
    text: str,
) -> int | None:

    return _unclosed_bracketed_internal_action_start(
        text
    )


class RuntimeActionStreamFilter:

    def __init__(
        self,
        enabled_actions=None,
        preserve_action_text: bool = False,
    ):
        self.pending = ""
        self.pending_is_action = False
        self.preserve_action_text = preserve_action_text
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

        combined = (
            self.pending
            + chunk
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
            )

        return _extract_runtime_actions_if_needed(
            combined,
            enabled_actions=self.enabled_actions,
            preserve_action_text=self.preserve_action_text,
        )

    def flush(self) -> str:

        pending = self.pending
        self.pending = ""
        self.pending_is_action = False

        if self.preserve_action_text:
            return pending

        if _unclosed_internal_action_request_start(
            pending
        ) == 0:
            return ""

        return extract_runtime_actions(
            pending,
            enabled_actions=self.enabled_actions,
            preserve_action_text=False,
        ).text
