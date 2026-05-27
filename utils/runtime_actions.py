import json
import re
from dataclasses import dataclass

from contracts.context_contract import (
    DEEP_THOUGHT_ACTION,
    RUNTIME_ACTION_DEEP_THOUGHT,
    RUNTIME_ACTION_SEARCH,
    SEARCH_ACTION_CLOSE,
    SEARCH_ACTION_OPEN,
)


SELF_CLOSING_ACTION_MARKERS = {
    RUNTIME_ACTION_DEEP_THOUGHT: DEEP_THOUGHT_ACTION,
}

PAIRED_ACTION_MARKERS = {
    RUNTIME_ACTION_SEARCH: (
        SEARCH_ACTION_OPEN,
        SEARCH_ACTION_CLOSE,
    ),
}

KNOWN_RUNTIME_ACTIONS = tuple(
    sorted(
        (
            *SELF_CLOSING_ACTION_MARKERS.keys(),
            *PAIRED_ACTION_MARKERS.keys(),
        )
    )
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
    def deep_thought_count(self) -> int:

        return self.count(
            RUNTIME_ACTION_DEEP_THOUGHT
        )

    @property
    def search_queries(self) -> tuple[str, ...]:

        queries = []

        for action in self.actions:

            if action.name != RUNTIME_ACTION_SEARCH:
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

    return normalized_name


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
        return data.strip()

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


def extract_runtime_actions(
    text: str,
    enabled_actions=None,
) -> RuntimeActionResult:

    if not text:
        return RuntimeActionResult(
            text="",
        )

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )

    actions = []
    clean_text = text

    for action_name, marker in SELF_CLOSING_ACTION_MARKERS.items():

        if action_name not in enabled_action_names:
            continue

        call_count = clean_text.count(
            marker
        )

        if not call_count:
            continue

        clean_text = clean_text.replace(
            marker,
            "",
        )

        actions.extend(
            RuntimeActionCall(
                name=action_name,
            )
            for _ in range(
                call_count
            )
        )

    for action_name, markers in PAIRED_ACTION_MARKERS.items():

        if action_name not in enabled_action_names:
            continue

        open_marker, close_marker = markers

        pattern = re.compile(
            (
                re.escape(
                    open_marker
                )
                + r"(.*?)"
                + re.escape(
                    close_marker
                )
            ),
            re.DOTALL,
        )

        def replace_action(match):

            actions.append(
                RuntimeActionCall(
                    name=action_name,
                    payload=(
                        match.group(1)
                        .strip()
                    ),
                )
            )

            return ""

        clean_text = pattern.sub(
            replace_action,
            clean_text,
        )

    return RuntimeActionResult(
        text=clean_text,
        actions=tuple(
            actions
        ),
    )


def _enabled_action_start_markers(
    enabled_actions=None,
) -> tuple[str, ...]:

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )

    markers = []

    for action_name, marker in SELF_CLOSING_ACTION_MARKERS.items():

        if action_name in enabled_action_names:
            markers.append(
                marker
            )

    for action_name, paired_markers in PAIRED_ACTION_MARKERS.items():

        if action_name in enabled_action_names:
            markers.append(
                paired_markers[0]
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

    max_length = min(
        [len(text)]
        + [
            len(marker) - 1
            for marker in markers
        ]
    )

    for length in range(
        max_length,
        0,
        -1,
    ):

        for marker in markers:

            if text.endswith(
                marker[:length]
            ):
                return length

    return 0


def _unclosed_paired_action_start(
    text: str,
    enabled_actions=None,
) -> int | None:

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )

    latest_start: int = -1

    for action_name, markers in PAIRED_ACTION_MARKERS.items():

        if action_name not in enabled_action_names:
            continue

        open_marker, close_marker = markers

        start = text.rfind(
            open_marker
        )

        if start < 0:
            continue

        close = text.find(
            close_marker,
            start + len(open_marker),
        )

        if close >= 0:
            continue

        if start > latest_start:
            latest_start = start

    if latest_start < 0:
        return None

    return latest_start


class RuntimeActionStreamFilter:

    def __init__(
        self,
        enabled_actions=None,
    ):
        self.pending = ""
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

        self.pending = ""

        result = extract_runtime_actions(
            combined,
            enabled_actions=self.enabled_actions,
        )

        unclosed_start = _unclosed_paired_action_start(
            result.text,
            enabled_actions=self.enabled_actions,
        )

        if unclosed_start is not None:

            self.pending = result.text[
                unclosed_start:
            ]

            return RuntimeActionResult(
                text=result.text[
                    :unclosed_start
                ],
                actions=result.actions,
            )

        hold_length = (
            _trailing_marker_prefix_length(
                result.text,
                enabled_actions=self.enabled_actions,
            )
        )

        if not hold_length:
            return result

        self.pending = result.text[
            -hold_length:
        ]

        return RuntimeActionResult(
            text=result.text[
                :-hold_length
            ],
            actions=result.actions,
        )

    def flush(self) -> str:

        pending = self.pending
        self.pending = ""

        return pending
