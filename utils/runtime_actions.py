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

TOOL_CALL_MARKER = "<|tool_call>"


def build_runtime_action_id(
    action_name: str,
    index: int,
) -> str:

    return (
        f"{normalize_runtime_action_name(action_name).lower()}_"
        f"{index:03d}"
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
    clean_text = text

    for action_name, marker in SELF_CLOSING_ACTION_MARKERS.items():

        if action_name not in enabled_action_names:
            continue

        pattern = re.compile(
            _self_closing_action_open_pattern(
                action_name
            ),
            re.DOTALL,
        )

        matches = tuple(
            pattern.finditer(
                clean_text
            )
        )

        call_count = len(
            matches
        )

        if not call_count:
            continue

        clean_text = pattern.sub(
            (
                marker
                if preserve_action_text
                else ""
            ),
            clean_text,
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
                _paired_action_open_pattern(
                    action_name
                )
                + r"(\s*\{.*?\})\s*"
                + re.escape(
                    close_marker
                )
            ),
            re.DOTALL,
        )

        def replace_action(match):

            payload = (
                match.group(1)
                .strip()
            )

            actions.append(
                RuntimeActionCall(
                    name=action_name,
                    payload=payload,
                )
            )

            if preserve_action_text:
                return (
                    open_marker
                    + payload
                    + close_marker
                )

            return ""

        clean_text = pattern.sub(
            replace_action,
            clean_text,
        )

    clean_text = _strip_tool_call_markers(
        clean_text
    )

    return RuntimeActionResult(
        text=clean_text,
        actions=tuple(
            actions
        ),
    )


def _runtime_action_tag_name(
    action_name: str,
) -> str:

    return (
        "RUNTIME_ACTION:"
        + normalize_runtime_action_name(
            action_name
        )
    )


def _paired_action_open_pattern(
    action_name: str,
) -> str:

    return (
        r"<(?!/)[^<]*?"
        + re.escape(
            _runtime_action_tag_name(
                action_name
            )
        )
        + r"\s*>"
    )


def _self_closing_action_open_pattern(
    action_name: str,
) -> str:

    return (
        r"<(?!/)[^<]*?"
        + re.escape(
            _runtime_action_tag_name(
                action_name
            )
        )
        + r"\s*/?>"
    )


def _tool_call_action_open_marker(
    action_name: str,
) -> str:

    return (
        TOOL_CALL_MARKER
        + "call:"
        + _runtime_action_tag_name(
            action_name
        )
        + ">"
    )


def _runtime_action_open_marker(
    action_name: str,
) -> str:

    return (
        "<"
        + _runtime_action_tag_name(
            action_name
        )
        + ">"
    )


def _strip_tool_call_markers(
    text: str,
) -> str:

    return text.replace(
        TOOL_CALL_MARKER,
        "",
    )


def _complete_paired_action_open_at_end(
    text: str,
    enabled_actions=None,
) -> tuple[int, str] | None:

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )

    for action_name, markers in PAIRED_ACTION_MARKERS.items():

        if action_name not in enabled_action_names:
            continue

        open_marker, _ = markers

        pattern = re.compile(
            _paired_action_open_pattern(
                action_name
            ),
            re.DOTALL,
        )

        for match in pattern.finditer(
            text
        ):

            if match.end() != len(
                text
            ):
                continue

            return (
                match.start(),
                open_marker,
            )

    return None


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
                _runtime_action_open_marker(
                    action_name
                )
            )
            markers.append(
                marker
            )
            markers.append(
                _tool_call_action_open_marker(
                    action_name
                )
            )

    for action_name, paired_markers in PAIRED_ACTION_MARKERS.items():

        if action_name in enabled_action_names:
            markers.append(
                paired_markers[0]
            )
            markers.append(
                _tool_call_action_open_marker(
                    action_name
                )
            )

    markers.append(
        TOOL_CALL_MARKER
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

        _, close_marker = markers

        pattern = re.compile(
            _paired_action_open_pattern(
                action_name
            ),
            re.DOTALL,
        )

        for match in pattern.finditer(
            text
        ):

            start = match.start()

            close = text.find(
                close_marker,
                match.end(),
            )

            if close >= 0:
                continue

            tail = text[
                match.end():
            ]

            stripped_tail = tail.lstrip()

            if (
                stripped_tail
                and not stripped_tail.startswith(
                    "{"
                )
            ):
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
        preserve_action_text: bool = False,
    ):
        self.pending = ""
        self.pending_emitted_text = ""
        self.preserve_action_text = preserve_action_text
        self.enabled_actions = normalize_runtime_action_names(
            enabled_actions
        )

    def _finalize_result(
        self,
        result: RuntimeActionResult,
        fallback_text: str,
    ) -> RuntimeActionResult:

        emitted_text = self.pending_emitted_text
        self.pending_emitted_text = ""

        if not emitted_text:
            return result

        if result.text.startswith(
            emitted_text
        ):
            return RuntimeActionResult(
                text=result.text[
                    len(emitted_text):
                ],
                actions=result.actions,
            )

        if result.actions:
            return result

        return extract_runtime_actions(
            fallback_text,
            enabled_actions=self.enabled_actions,
            preserve_action_text=self.preserve_action_text,
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

        if self.preserve_action_text:

            open_at_end = _complete_paired_action_open_at_end(
                combined,
                enabled_actions=self.enabled_actions,
            )

            if open_at_end is not None:

                open_start, open_text = open_at_end
                self.pending = combined[
                    open_start:
                ]
                self.pending_emitted_text = open_text

                prefix_result = extract_runtime_actions(
                    combined[
                        :open_start
                    ],
                    enabled_actions=self.enabled_actions,
                    preserve_action_text=self.preserve_action_text,
                )

                return RuntimeActionResult(
                    text=(
                        prefix_result.text
                        + open_text
                    ),
                    actions=prefix_result.actions,
                )

        unclosed_start = _unclosed_paired_action_start(
            combined,
            enabled_actions=self.enabled_actions,
        )

        if unclosed_start is not None:

            self.pending = combined[
                unclosed_start:
            ]

            return extract_runtime_actions(
                combined[
                    :unclosed_start
                ],
                enabled_actions=self.enabled_actions,
                preserve_action_text=self.preserve_action_text,
            )

        hold_length = (
            _trailing_marker_prefix_length(
                combined,
                enabled_actions=self.enabled_actions,
            )
        )

        if hold_length:

            self.pending = combined[
                -hold_length:
            ]

            return extract_runtime_actions(
                combined[
                    :-hold_length
                ],
                enabled_actions=self.enabled_actions,
                preserve_action_text=self.preserve_action_text,
            )

        result = extract_runtime_actions(
            combined,
            enabled_actions=self.enabled_actions,
            preserve_action_text=self.preserve_action_text,
        )
        return self._finalize_result(
            result,
            chunk,
        )

    def flush(self) -> str:

        pending = self.pending
        self.pending = ""
        self.pending_emitted_text = ""

        return _strip_tool_call_markers(
            pending
        )
