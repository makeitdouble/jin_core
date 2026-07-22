from dataclasses import dataclass
from functools import lru_cache

from contracts.rules_assembler import (
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
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_REMOVE_SKILL,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY,
    RUNTIME_ACTION_RESOLVE_TODO,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
    RUNTIME_ACTION_SAVE_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)
from contracts.rules_assembler import (
    get_close_tag_runtime_actions,
    get_runtime_action_private_marker,
    normalize_runtime_action_names as get_contract_runtime_action_names,
)

from .action_payload_utils import (
    _clean_internal_action_query,
    _get_internal_action_placeholder_payloads,
)
from .append_delayed_memory_utils import build_append_delayed_memory_payload
from .append_skill_utils import (
    build_append_skill_payload,
    plural_skill_marker_action_name as _plural_skill_marker_action_name,
    split_internal_skill_marker_list as _split_internal_skill_marker_list,
)
from .asset_action_utils import build_asset_action_payload
from .check_todo_utils import build_check_todo_payload
from .create_active_memory_utils import build_create_active_memory_payload
from .create_todo_list_utils import build_create_todo_list_payload
from .idle_utils import build_idle_payload
from .jin_color_utils import build_jin_color_payload
from .resolve_action_utils import build_resolve_action_payload
from .regexp_utils import (
    RuntimeActionRegexpMatch,
    compile_runtime_action_end_regexp,
    compile_runtime_action_start_regexp,
    extract_private_marker_parts,
    find_runtime_action_matches,
    find_unclosed_runtime_action_start,
    get_runtime_action_start_markers,
    select_non_overlapping_regexp_matches,
)
from .save_delayed_memory_utils import (
    DELAYED_MEMORY_FIELD_RE,
    build_save_delayed_memory_payload,
    parse_delayed_memory_content_payload,
)
from .web_search_utils import (
    build_web_search_payload,
    extract_search_query,
)


KNOWN_RUNTIME_ACTIONS = get_contract_runtime_action_names(
    None
)

CLOSE_TAG_RUNTIME_ACTIONS = frozenset(
    get_close_tag_runtime_actions()
)

REPEATABLE_RUNTIME_ACTIONS = frozenset({
    RUNTIME_ACTION_IDLE,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
})


def _runtime_action_marker_config(
    action_name: str,
) -> tuple[str, bool]:

    return (
        get_runtime_action_private_marker(
            action_name
        ),
        action_name in CLOSE_TAG_RUNTIME_ACTIONS,
    )


def _find_all_runtime_action_matches(
    text: str,
    action_names=None,
) -> tuple[RuntimeActionRegexpMatch, ...]:

    matches = []

    for action_name in normalize_runtime_action_names(
        action_names
    ):
        private_marker, close_tag = _runtime_action_marker_config(
            action_name
        )

        matches.extend(
            find_runtime_action_matches(
                text,
                private_marker,
                action_name,
                close_tag,
            )
        )

    return select_non_overlapping_regexp_matches(
        matches
    )


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


MAX_RUNTIME_ACTION_MARKERS_PER_MESSAGE = 5


class RuntimeActionRepetitionGuard:

    def __init__(
        self,
        *,
        max_consecutive: int | None = None,
        max_per_message: int = MAX_RUNTIME_ACTION_MARKERS_PER_MESSAGE,
    ):
        # ``max_consecutive`` remains accepted for compatibility with callers,
        # but the guard intentionally counts the same marker name across the
        # whole message. Payload changes and unrelated markers between repeats
        # must not let a marker loop escape validation.
        self.max_consecutive = max_consecutive
        self.max_per_message = max(
            1,
            int(max_per_message or MAX_RUNTIME_ACTION_MARKERS_PER_MESSAGE),
        )
        self.counts = {}
        self.triggered = False
        self.reason = ""

    def record(
        self,
        action: RuntimeActionCall,
    ) -> bool:

        if self.triggered:
            return True

        marker_name = normalize_runtime_action_name(
            action.name
        )
        count = self.counts.get(
            marker_name,
            0,
        ) + 1
        self.counts[marker_name] = count

        if count >= self.max_per_message:
            self.triggered = True
            self.reason = (
                f"runtime action marker {marker_name} reached "
                f"{count} occurrences in one message"
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


_ACTION_PAYLOAD_BUILDERS = {
    RUNTIME_ACTION_IDLE: build_idle_payload,
    RUNTIME_ACTION_JIN_COLOR: build_jin_color_payload,
    RUNTIME_ACTION_WEB_SEARCH: build_web_search_payload,
    RUNTIME_ACTION_CREATE_ACTIVE_MEMORY: build_create_active_memory_payload,
    RUNTIME_ACTION_RESOLVE_ACTIVE_MEMORY: build_resolve_action_payload,
    RUNTIME_ACTION_CREATE_TODO_LIST: build_create_todo_list_payload,
    RUNTIME_ACTION_RESOLVE_TODO: build_resolve_action_payload,
    RUNTIME_ACTION_CHECK_TODO: build_check_todo_payload,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT: build_save_delayed_memory_payload,
    RUNTIME_ACTION_APPEND_DELAYED_MEMORY: build_append_delayed_memory_payload,
    RUNTIME_ACTION_REMOVE_DELAYED_MEMORY: build_resolve_action_payload,
    RUNTIME_ACTION_APPEND_SKILL: build_append_skill_payload,
    RUNTIME_ACTION_REMOVE_SKILL: build_resolve_action_payload,
    RUNTIME_ACTION_ASSET_ACTION: build_asset_action_payload,
}


def _build_internal_action_call(
    action_name: str,
    query: str = "",
) -> RuntimeActionCall | None:

    normalized_name = normalize_runtime_action_name(
        action_name
    )

    if normalized_name not in KNOWN_RUNTIME_ACTIONS:
        return None

    if normalized_name in {
        RUNTIME_ACTION_LIST_DELAYED_MEMORY,
        RUNTIME_ACTION_HIDE_SKILLS,
    }:
        return RuntimeActionCall(
            name=normalized_name,
            payload="",
        )

    if normalized_name == RUNTIME_ACTION_LIST_SKILLS:
        return RuntimeActionCall(
            name=normalized_name,
            payload=_clean_internal_action_query(
                query
            ),
        )

    payload_builder = _ACTION_PAYLOAD_BUILDERS.get(
        normalized_name
    )

    if payload_builder is None:
        payload = ""
    else:
        payload = payload_builder(
            query,
            _get_internal_action_placeholder_payloads(),
        )

        if payload is None:
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

        while removal_start > 0:
            previous_line_end = removal_start - 1
            previous_line_start = text.rfind(
                "\n",
                0,
                previous_line_end,
            ) + 1
            previous_line = text[
                previous_line_start:previous_line_end
            ]

            if previous_line.strip():
                break

            removal_start = previous_line_start

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

        if removal_end >= len(
            text
        ):
            while (
                removal_start > 0
                and text[removal_start - 1].isspace()
            ):
                removal_start -= 1

        return (
            removal_start,
            removal_end,
        )

    removal_start = start
    removal_end = end

    if not line_prefix.strip():
        removal_start = line_start

    if (
        removal_end < line_end
        and text[removal_end] in " \t"
    ):
        while (
            removal_end < line_end
            and text[removal_end] in " \t"
        ):
            removal_end += 1

    elif (
        removal_start > line_start
        and text[removal_start - 1] in " \t"
    ):
        while (
            removal_start > line_start
            and text[removal_start - 1] in " \t"
        ):
            removal_start -= 1

    return (
        removal_start,
        removal_end,
    )


def _trailing_marker_spacing_start(
    text: str,
) -> int | None:

    if not text:
        return None

    index = len(
        text
    )

    while (
        index > 0
        and text[index - 1].isspace()
    ):
        index -= 1

    if index == len(
        text
    ):
        return None

    trailing = text[
        index:
    ]

    if (
        "\n" not in trailing
        and "\r" not in trailing
    ):
        return None

    return index


def _split_pending_marker_prefix(
    text: str,
    marker_start: int,
) -> tuple[int, str]:

    before_marker = text[
        :marker_start
    ]

    if not before_marker.strip():
        return (
            0,
            "",
        )

    spacing_start = _trailing_marker_spacing_start(
        before_marker
    )

    if spacing_start is not None:
        return (
            spacing_start,
            before_marker[
                :spacing_start
            ],
        )

    return (
        marker_start,
        before_marker,
    )


def _replace_runtime_action_matches(
    text: str,
    matches,
    replace_action,
) -> str:

    parts = []
    cursor = 0

    for match in matches:

        replacement = replace_action(
            match
        )

        start = match.start
        end = match.end

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
            # IDLE is intentionally numeric: ``IDLE: <digits>`` with an
            # optional ``s``/``ms`` suffix is a runtime marker. The suffix is
            # ignored and the number always means seconds. Plain prose and
            # malformed candidates such as ``<IDLE: test>`` stay visible.
            if normalized_action_name == RUNTIME_ACTION_IDLE:
                return raw_marker

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
            return ""

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
                action.name in REPEATABLE_RUNTIME_ACTIONS
                or action_key not in seen_action_keys
            ):
                if action.name not in REPEATABLE_RUNTIME_ACTIONS:
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
                return ""

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

    def replace_runtime_action_marker(
        match: RuntimeActionRegexpMatch,
    ) -> str:

        return handle_marker(
            match.raw,
            match.name,
            match.payload,
        )

    clean_text = _replace_runtime_action_matches(
        text,
        _find_all_runtime_action_matches(
            text,
            enabled_action_names,
        ),
        replace_runtime_action_marker,
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

def _enabled_action_start_markers(
    enabled_actions=None,
) -> tuple[str, ...]:

    markers = []

    for action_name in normalize_runtime_action_names(
        enabled_actions
    ):
        private_marker, _ = _runtime_action_marker_config(
            action_name
        )

        for marker in get_runtime_action_start_markers(
            private_marker,
            action_name,
        ):
            if marker not in markers:
                markers.append(
                    marker
                )

    return tuple(
        markers
    )


_MARKER_PREFIX_ANGLE = 1
_MARKER_PREFIX_BARE = 2


@lru_cache(maxsize=None)
def _enabled_action_marker_prefix_index(
    enabled_action_names: tuple[str, ...],
):
    """Build a reusable suffix lookup for streaming marker detection."""

    prefix_flags_by_length: dict[int, dict[str, int]] = {}
    max_length = 0

    for marker in _enabled_action_start_markers(
        enabled_action_names
    ):
        upper_marker = marker.upper()
        marker_flag = (
            _MARKER_PREFIX_ANGLE
            if marker.startswith("<")
            else _MARKER_PREFIX_BARE
        )
        max_length = max(
            max_length,
            len(upper_marker),
        )

        for length in range(
            1,
            len(upper_marker) + 1,
        ):
            # Closing tags are never stream starts. Kept for parity with the
            # previous matcher if aliases are extended later.
            if (
                length == len(upper_marker)
                and marker.startswith("</")
            ):
                continue

            prefix = upper_marker[:length]
            flags_for_length = prefix_flags_by_length.setdefault(
                length,
                {},
            )
            flags_for_length[prefix] = (
                flags_for_length.get(prefix, 0)
                | marker_flag
            )

    return (
        max_length,
        prefix_flags_by_length,
    )


def _trailing_marker_prefix_length(
    text: str,
    enabled_actions=None,
) -> int:

    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )
    max_marker_length, prefix_flags_by_length = (
        _enabled_action_marker_prefix_index(
            enabled_action_names
        )
    )

    if not text or not max_marker_length:
        return 0

    upper_text = text.upper()
    max_length = min(
        len(text),
        max_marker_length,
    )

    for length in range(
        max_length,
        0,
        -1,
    ):
        suffix = upper_text[-length:]
        marker_flags = prefix_flags_by_length.get(
            length,
            {},
        ).get(
            suffix,
            0,
        )

        if not marker_flags:
            continue

        # Angle markers can begin anywhere in a chunk. Bare legacy forms are
        # accepted only at the start of a line, matching the old behavior.
        if marker_flags & _MARKER_PREFIX_ANGLE:
            return length

        marker_start = len(text) - length
        line_start = max(
            text.rfind("\n", 0, marker_start),
            text.rfind("\r", 0, marker_start),
        ) + 1

        if not text[line_start:marker_start].strip():
            return length

    return 0


@lru_cache(maxsize=None)
def _enabled_action_stream_candidates(
    enabled_action_names: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    signal_names = []
    bare_markers = []

    for action_name in enabled_action_names:
        private_marker, _ = _runtime_action_marker_config(
            action_name
        )
        marker_name, _ = extract_private_marker_parts(
            private_marker
        )

        for signal_name in (
            action_name,
            marker_name,
        ):
            normalized_signal = signal_name.strip().upper()

            if (
                normalized_signal
                and normalized_signal not in signal_names
            ):
                signal_names.append(
                    normalized_signal
                )

        for marker in get_runtime_action_start_markers(
            private_marker,
            action_name,
        ):
            upper_marker = marker.upper()

            if (
                upper_marker.startswith("<")
                or upper_marker.startswith("CALL:")
            ):
                continue

            if upper_marker not in bare_markers:
                bare_markers.append(
                    upper_marker
                )

    return (
        tuple(signal_names),
        tuple(bare_markers),
    )


def _action_text_may_contain_marker(
    text: str,
    enabled_actions=None,
) -> bool:

    if not text:
        return False

    upper_text = text.upper()
    enabled_action_names = normalize_runtime_action_names(
        enabled_actions
    )
    signal_names, bare_markers = (
        _enabled_action_stream_candidates(
            enabled_action_names
        )
    )

    # Expensive generic regexps are useful only after a real marker envelope.
    # Mentioning INTERNAL_ACTION_* in prose must not stall every stream chunk.
    if (
        "<" in upper_text
        or "CALL:" in upper_text
    ):
        if any(
            signal_name in upper_text
            for signal_name in signal_names
        ):
            return True

    if bare_markers:
        normalized_lines = upper_text.replace(
            "\r",
            "\n",
        ).split(
            "\n"
        )

        for line in normalized_lines:
            if line.lstrip().startswith(
                bare_markers
            ):
                return True

    return False


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
        text,
        enabled_actions=enabled_actions,
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


def _unclosed_internal_action_request_start(
    text: str,
    enabled_actions=None,
) -> int | None:

    marker_starts = []

    for action_name in normalize_runtime_action_names(
        enabled_actions
    ):
        private_marker, close_tag = _runtime_action_marker_config(
            action_name
        )
        marker_start = find_unclosed_runtime_action_start(
            text,
            private_marker,
            action_name,
            close_tag,
        )

        if marker_start is not None:
            marker_starts.append(
                marker_start
            )

    if not marker_starts:
        return None

    return max(
        marker_starts
    )


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

        for action_name in self.enabled_actions:
            if action_name not in CLOSE_TAG_RUNTIME_ACTIONS:
                continue

            private_marker, _ = _runtime_action_marker_config(
                action_name
            )
            start_pattern = compile_runtime_action_start_regexp(
                private_marker,
                action_name,
            )

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

        for action_name in self.enabled_actions:
            if action_name not in CLOSE_TAG_RUNTIME_ACTIONS:
                continue

            private_marker, _ = _runtime_action_marker_config(
                action_name
            )
            start_pattern = compile_runtime_action_start_regexp(
                private_marker,
                action_name,
            )

            for match in start_pattern.finditer(
                text
            ):
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
        pending_was_spacing = (
            bool(self.pending)
            and not self.pending.strip()
            and not self.pending_is_action
        )

        if not self.pending:
            hold_length = _trailing_marker_prefix_length(
                combined,
                enabled_actions=self.enabled_actions,
            )

            if hold_length:

                prefix_start = len(
                    combined
                ) - hold_length
                pending_start, ready_text = _split_pending_marker_prefix(
                    combined,
                    prefix_start,
                )

                self.pending = combined[
                    pending_start:
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

            spacing_start = _trailing_marker_spacing_start(
                combined
            )

            if (
                spacing_start is not None
                and not _action_text_may_contain_marker(
                    combined,
                    enabled_actions=self.enabled_actions,
                )
            ):
                self.pending = combined[
                    spacing_start:
                ]
                self.pending_is_action = False

                ready_text = combined[
                    :spacing_start
                ]

                return RuntimeActionResult(
                    text=ready_text,
                )

        if (
            not self.pending
            and not _action_text_may_contain_marker(
                chunk,
                enabled_actions=self.enabled_actions,
            )
        ):
            return RuntimeActionResult(
                text=chunk,
            )

        if (
            self.pending
            and self.pending_is_action
        ):
            pending_starts_with_angle = (
                self.pending.lstrip().startswith("<")
            )
            action_may_be_complete = (
                ">" in chunk
                or (
                    (
                        not pending_starts_with_angle
                        or ">" not in self.pending
                    )
                    and (
                        "\n" in chunk
                        or "\r" in chunk
                    )
                )
            )

            if not action_may_be_complete:
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

            pending_start, ready_text = _split_pending_marker_prefix(
                combined,
                unclosed_start,
            )

            self.pending = combined[
                pending_start:
            ]
            self.pending_is_action = True

            result = _extract_runtime_actions_if_needed(
                ready_text,
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

            prefix_start = len(
                combined
            ) - hold_length
            pending_start, ready_text = _split_pending_marker_prefix(
                combined,
                prefix_start,
            )

            if (
                pending_was_spacing
                and not ready_text.strip()
            ):
                self.pending = combined
                self.pending_is_action = True

                return RuntimeActionResult(
                    text="",
                )

            self.pending = combined[
                pending_start:
            ]

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

        delayed_memory_marker, _ = _runtime_action_marker_config(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT
        )
        delayed_memory_start_re = compile_runtime_action_start_regexp(
            delayed_memory_marker,
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
        )
        delayed_memory_end_re = compile_runtime_action_end_regexp(
            delayed_memory_marker,
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY_CONTENT,
        )
        delayed_memory_start = delayed_memory_start_re.match(
            pending
        )

        if (
            delayed_memory_start is not None
            and not delayed_memory_end_re.search(
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
