import re

from dataclasses import dataclass
from functools import lru_cache

from contracts.rules_assembler import (
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_LOAD_SKILL,
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_ATTACH_FILE,
    RUNTIME_ACTION_LIST_FILES,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
    RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
    RUNTIME_ACTION_ASSET_ACTION,
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_REACTION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    RUNTIME_ACTION_UNLOAD_SKILL,
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_DETACH_FILE,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
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
from .load_delayed_memory_utils import build_load_delayed_memory_payload
from .skill_load_utils import (
    build_load_skill_payload,
    plural_skill_marker_action_name as _plural_skill_marker_action_name,
    split_internal_skill_marker_list as _split_internal_skill_marker_list,
)
from .asset_action_utils import build_asset_action_payload
from .save_active_memory_utils import build_save_active_memory_payload
from .jin_color_utils import build_jin_color_payload
from .jin_reaction_utils import build_jin_reaction_payload
from .jin_size_utils import build_jin_size_payload
from .jin_position_utils import build_jin_position_payload
from .jin_speed_utils import build_jin_speed_payload
from .update_lt_facts_utils import build_update_lt_facts_payload
from .update_active_memory_utils import build_update_active_memory_payload
from .resolve_action_utils import build_resolve_action_payload
from .regexp_utils import (
    RuntimeActionRegexpMatch,
    RUNTIME_ACTION_EXECUTABLE_PREFIX,
    RUNTIME_ACTION_QUOTE_OPENERS,
    is_quoted_runtime_marker,
    compile_runtime_action_end_regexp,
    compile_runtime_action_start_regexp,
    compile_runtime_action_tag_regexp,
    extract_private_marker_parts,
    find_runtime_action_matches,
    find_unclosed_runtime_action_start,
    get_runtime_action_start_markers,
    select_non_overlapping_regexp_matches,
)
from .save_delayed_memory_utils import (
    build_save_delayed_memory_payload,
)
from .web_search_utils import (
    build_web_search_payload,
    extract_search_query,
)


KNOWN_RUNTIME_ACTIONS = get_contract_runtime_action_names(
    None
)


def format_runtime_trigger_words_message(
    template: str,
    trigger_words,
) -> str:

    return template.format(
        trigger_words=", ".join(
            str(
                trigger_word
                or ""
            ).strip()
            for trigger_word in trigger_words
            if str(
                trigger_word
                or ""
            ).strip()
        )
    )

CLOSE_TAG_RUNTIME_ACTIONS = frozenset(
    get_close_tag_runtime_actions()
)

REPEATABLE_RUNTIME_ACTIONS = frozenset({
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
})

JIN_INLINE_PAYLOAD_ACTIONS = frozenset({
    RUNTIME_ACTION_JIN_COLOR,
    RUNTIME_ACTION_JIN_REACTION,
    RUNTIME_ACTION_JIN_SIZE,
    RUNTIME_ACTION_JIN_POSITION,
    RUNTIME_ACTION_JIN_SPEED,
})

UPDATE_ACTIVE_MEMORY_START_RE = re.compile(
    RUNTIME_ACTION_EXECUTABLE_PREFIX
    + r"<\s*UPDATE_ACTIVE_MEMORY(?=\s|>)",
    re.IGNORECASE,
)

UPDATE_ACTIVE_MEMORY_SELF_CLOSING_ATTRIBUTE_RE = re.compile(
    RUNTIME_ACTION_EXECUTABLE_PREFIX + (
        r"<\s*(?P<name>UPDATE_ACTIVE_MEMORY)"
        r"\s+"
        r"(?P<payload>(?:[^<>\"']+|\"[^\"]*\"|'[^']*')*?)"
        r"\s*/\s*>"
    ),
    re.IGNORECASE | re.DOTALL,
)


def _runtime_action_allows_inline_payload(
    action_name: str,
) -> bool:
    return action_name in JIN_INLINE_PAYLOAD_ACTIONS


@lru_cache(maxsize=None)
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

        action_matches = find_runtime_action_matches(
            text,
            private_marker,
            action_name,
            close_tag,
            allow_inline_payload=(
                _runtime_action_allows_inline_payload(
                    action_name
                )
            ),
        )

        if action_name == RUNTIME_ACTION_DEEP_WEB_SEARCH:
            action_matches = (
                *_find_deep_web_search_block_matches(
                    text,
                    private_marker,
                    action_name,
                ),
                *find_runtime_action_matches(
                    text,
                    private_marker,
                    action_name,
                    False,
                ),
                *action_matches,
            )

        if action_name == RUNTIME_ACTION_ASSET_ACTION:
            action_matches = tuple(
                match
                for match in action_matches
                if match.payload.strip()
            )

        if action_name == RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY:
            action_matches = (
                *_find_update_active_memory_attribute_matches(
                    text
                ),
                *action_matches,
            )

        if action_name == RUNTIME_ACTION_CLEAN_TOOL_RESULTS:
            action_matches = (
                *action_matches,
                *_find_clean_tool_results_closing_matches(
                    text,
                    private_marker,
                ),
            )

        matches.extend(
            action_matches
        )

    return select_non_overlapping_regexp_matches(
        matches
    )


def _find_clean_tool_results_closing_matches(
    text: str,
    private_marker: str,
) -> tuple[RuntimeActionRegexpMatch, ...]:
    """Treat a redundant CLEAN_TOOL_RESULTS close tag as parser-only noise."""

    matches = []
    end_pattern = compile_runtime_action_end_regexp(
        private_marker,
        RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
    )

    for match in end_pattern.finditer(
        str(
            text
            or ""
        )
    ):
        matches.append(
            RuntimeActionRegexpMatch(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                name=RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
                source="compat_closing",
            )
        )

    return tuple(
        matches
    )


def _find_update_active_memory_attribute_matches(
    text: str,
) -> tuple[RuntimeActionRegexpMatch, ...]:

    matches = []

    for match in UPDATE_ACTIVE_MEMORY_SELF_CLOSING_ATTRIBUTE_RE.finditer(
        str(
            text
            or ""
        )
    ):
        matches.append(
            RuntimeActionRegexpMatch(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                name=str(
                    match.group("name")
                    or ""
                ).strip().upper(),
                payload=str(
                    match.group("payload")
                    or ""
                ).strip(),
            )
        )

    return tuple(
        matches
    )


def _find_deep_web_search_block_matches(
    text: str,
    private_marker: str,
    action_name: str,
) -> tuple[RuntimeActionRegexpMatch, ...]:

    marker_name, placeholder_payload = extract_private_marker_parts(
        private_marker
    )
    names = [
        name
        for name in (
            marker_name,
            action_name,
        )
        if str(name or "").strip()
    ]
    name_pattern = "|".join(
        re.escape(name)
        for name in dict.fromkeys(names)
    )

    if not name_pattern:
        return ()

    placeholder_key = (
        placeholder_payload
        or "research objective"
    ).casefold().strip(
        "`'\"<>"
    ).strip()
    regexp = re.compile(
        RUNTIME_ACTION_EXECUTABLE_PREFIX + (
            r"<\s*(?P<name>"
            + name_pattern
            + r")"
            r"(?:\s*:\s*(?P<attribute_payload>[^>\r\n]*?))?"
            r"\s*>"
            r"(?P<body>.*?)"
            + RUNTIME_ACTION_EXECUTABLE_PREFIX
            + r"<\s*/\s*(?:"
            + name_pattern
            + r")\s*>+"
        ),
        re.IGNORECASE | re.DOTALL,
    )
    matches = []

    for match in regexp.finditer(str(text or "")):
        attribute_payload = str(
            match.group("attribute_payload")
            or ""
        ).strip()
        body_payload = str(
            match.group("body")
            or ""
        ).strip()
        attribute_key = attribute_payload.casefold().strip(
            "`'\"<>"
        ).strip()
        payload = (
            body_payload
            if (
                body_payload
                and (
                    not attribute_payload
                    or attribute_key == placeholder_key
                )
            )
            else attribute_payload
        )

        matches.append(
            RuntimeActionRegexpMatch(
                start=match.start(),
                end=match.end(),
                raw=match.group(0),
                name=str(
                    match.group("name")
                    or action_name
                ).strip().upper(),
                payload=payload,
                source="regexp",
            )
        )

    return tuple(matches)


def _is_payloadless_jin_color_marker(
    raw_marker: str,
    payload: str,
) -> bool:

    if str(payload or "").strip():
        return False

    return bool(
        re.fullmatch(
            r"<\s*JIN_COLOR(?:\s*:\s*)?\s*/?>",
            str(raw_marker or "").strip(),
            re.IGNORECASE,
        )
    )


@dataclass(frozen=True)
class RuntimeActionCall:
    name: str
    payload: str = ""
    marker_name: str = ""
    marker_payload: str = ""
    marker_group: str = ""


@dataclass(frozen=True)
class RuntimeActionResult:
    text: str
    started_actions: tuple[RuntimeActionCall, ...] = ()
    observed_actions: tuple[RuntimeActionCall, ...] = ()
    actions: tuple[RuntimeActionCall, ...] = ()
    failed_actions: tuple[RuntimeActionCall, ...] = ()
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
        # ``max_consecutive`` remains accepted for compatibility with callers.
        # Repetition is counted by the normalized action + payload pair across
        # the whole message, so interleaved different payloads do not collide.
        self.max_consecutive = max_consecutive
        self.max_per_message = max(
            1,
            int(max_per_message or MAX_RUNTIME_ACTION_MARKERS_PER_MESSAGE),
        )
        self.counts = {}
        self.triggered = False
        self.triggered_action = None
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
        marker_payload = str(
            getattr(
                action,
                "payload",
                "",
            )
            or ""
        ).strip()
        marker_key = (
            marker_name,
            marker_payload,
        )
        count = self.counts.get(
            marker_key,
            0,
        ) + 1
        self.counts[marker_key] = count

        if count >= self.max_per_message:
            self.triggered = True
            self.triggered_action = action
            self.reason = (
                f"runtime action marker {marker_name} reached "
                f"{count} identical occurrences in one message"
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
        "SAVE_DELAYED_MEMORY": RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
        "SAVE_ACTIVE_MEMORY": RUNTIME_ACTION_SAVE_ACTIVE_MEMORY,
        "DELETE_ACTIVE_MEMORY": RUNTIME_ACTION_DELETE_ACTIVE_MEMORY,
        "USE_ASSETS": RUNTIME_ACTION_ASSET_ACTION,
        "CLEAN_TOOL_RESULTS": RUNTIME_ACTION_CLEAN_TOOL_RESULTS,
        "LOAD_SKILL": RUNTIME_ACTION_LOAD_SKILL,
        "UNLOAD_SKILL": RUNTIME_ACTION_UNLOAD_SKILL,
        "ASSET_ACTION": RUNTIME_ACTION_ASSET_ACTION,
        "JIN_SIZE": RUNTIME_ACTION_JIN_SIZE,
        "JIN_POSITION": RUNTIME_ACTION_JIN_POSITION,
        "JIN_SPEED": RUNTIME_ACTION_JIN_SPEED,
        "UPDATE_LT_FACTS": RUNTIME_ACTION_UPDATE_LT_FACTS,
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

        if normalized_name == RUNTIME_ACTION_SAVE_ACTIVE_MEMORY:
            normalized_names.append(
                RUNTIME_ACTION_DELETE_ACTIVE_MEMORY
            )
            normalized_names.append(
                RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY
            )

        if normalized_name == RUNTIME_ACTION_SAVE_DELAYED_MEMORY:
            normalized_names.append(
                RUNTIME_ACTION_LOAD_DELAYED_MEMORY
            )
            normalized_names.append(
                RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY
            )

        if normalized_name == RUNTIME_ACTION_ASSET_ACTION:
            normalized_names.append(
                RUNTIME_ACTION_LOAD_SKILL
            )
            normalized_names.append(
                RUNTIME_ACTION_UNLOAD_SKILL
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


def build_deep_web_search_payload(
    query: str,
    placeholder_payloads=(),
) -> str | None:

    return build_web_search_payload(
        query,
        (
            *placeholder_payloads,
            "research objective",
        ),
    )


_ACTION_PAYLOAD_BUILDERS = {
    RUNTIME_ACTION_JIN_COLOR: build_jin_color_payload,
    RUNTIME_ACTION_JIN_REACTION: build_jin_reaction_payload,
    RUNTIME_ACTION_JIN_SIZE: build_jin_size_payload,
    RUNTIME_ACTION_JIN_POSITION: build_jin_position_payload,
    RUNTIME_ACTION_JIN_SPEED: build_jin_speed_payload,
    RUNTIME_ACTION_UPDATE_LT_FACTS: build_update_lt_facts_payload,
    RUNTIME_ACTION_DEEP_WEB_SEARCH: build_deep_web_search_payload,
    RUNTIME_ACTION_WEB_SEARCH: build_web_search_payload,
    RUNTIME_ACTION_SAVE_ACTIVE_MEMORY: build_save_active_memory_payload,
    RUNTIME_ACTION_DELETE_ACTIVE_MEMORY: build_resolve_action_payload,
    RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY: build_update_active_memory_payload,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY: build_save_delayed_memory_payload,
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY: build_load_delayed_memory_payload,
    RUNTIME_ACTION_UNLOAD_DELAYED_MEMORY: build_resolve_action_payload,
    RUNTIME_ACTION_ATTACH_FILE: build_resolve_action_payload,
    RUNTIME_ACTION_DETACH_FILE: build_resolve_action_payload,
    RUNTIME_ACTION_LOAD_SKILL: build_load_skill_payload,
    RUNTIME_ACTION_UNLOAD_SKILL: build_resolve_action_payload,
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
    plural_skill_marker_index = 0

    if seen_action_keys is None:
        seen_action_keys = set()

    def handle_marker(
        raw_marker: str,
        action_name: str,
        query: str = "",
    ) -> str:
        nonlocal marker_repetition_exceeded
        nonlocal marker_repetition_reason

        if marker_repetition_exceeded:
            if not preserve_action_text:
                removed_markers.append(
                    raw_marker
                )

            return (
                raw_marker
                if preserve_action_text
                else ""
            )

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
            if _is_payloadless_jin_color_marker(
                raw_marker,
                query,
            ):
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

        preserve_marker = (
            preserve_action_marker is not None
            and preserve_action_marker(
                raw_marker,
                action,
            )
        )

        if (
            preserve_marker
            and action.name != RUNTIME_ACTION_JIN_REACTION
        ):
            return raw_marker

        if (
            not preserve_action_text
            and not preserve_marker
        ):
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
            if preserve_action_text or preserve_marker
            else ""
        )

    def handle_plural_skill_marker(
        raw_marker: str,
        action_name: str,
        query: str = "",
    ) -> str:
        nonlocal marker_repetition_exceeded
        nonlocal marker_repetition_reason
        nonlocal plural_skill_marker_index

        if marker_repetition_exceeded:
            if not preserve_action_text:
                removed_markers.append(
                    raw_marker
                )

            return (
                raw_marker
                if preserve_action_text
                else ""
            )

        if action_name not in enabled_action_names:
            return raw_marker

        skill_names = _split_internal_skill_marker_list(
            query
        )
        plural_marker_name = (
            "LOAD_SKILLS"
            if action_name == RUNTIME_ACTION_LOAD_SKILL
            else "UNLOAD_SKILLS"
        )
        plural_marker_payload = ", ".join(
            skill_names
        )
        plural_skill_marker_index += 1
        plural_marker_group = (
            f"{plural_marker_name.lower()}_"
            f"{plural_skill_marker_index:03d}"
        )
        plural_actions = []

        for skill_name in skill_names:
            action = _build_internal_action_call(
                action_name,
                skill_name,
            )

            if action is not None:
                plural_actions.append(
                    RuntimeActionCall(
                        name=action.name,
                        payload=action.payload,
                        marker_name=plural_marker_name,
                        marker_payload=plural_marker_payload,
                        marker_group=plural_marker_group,
                    )
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

        plural_marker_action = RuntimeActionCall(
            name=plural_marker_name,
            payload=plural_marker_payload,
            marker_name=plural_marker_name,
            marker_payload=plural_marker_payload,
            marker_group=plural_marker_group,
        )
        observed_actions.append(
            plural_marker_action
        )

        if (
            repetition_guard is not None
            and repetition_guard.record(
                plural_marker_action
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

        if match.source == "compat_closing":
            if not preserve_action_text:
                removed_markers.append(
                    match.raw
                )

            return (
                match.raw
                if preserve_action_text
                else ""
            )

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
        private_marker, close_tag = _runtime_action_marker_config(
            action_name
        )

        for marker in get_runtime_action_start_markers(
            private_marker,
            action_name,
            close_tag,
        ):
            if marker not in markers:
                markers.append(
                    marker
                )

        if action_name == RUNTIME_ACTION_CLEAN_TOOL_RESULTS:
            marker_name, _ = extract_private_marker_parts(
                private_marker
            )
            closing_marker = f"</{marker_name}>"

            if closing_marker not in markers:
                markers.append(
                    closing_marker
                )

    return tuple(
        markers
    )


_MARKER_PREFIX_ANGLE = 1


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
        # ``get_runtime_action_start_markers`` exposes only canonical
        # angle-bracket action tags.
        marker_flag = _MARKER_PREFIX_ANGLE
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


def _trailing_inline_jin_marker_length(
    text: str,
    enabled_action_names: tuple[str, ...],
) -> int:
    """Hold partial/inline JIN tags across streamed chunks, whitespace included."""
    if not text:
        return 0

    marker_start = text.rfind("<")
    if marker_start < 0 or is_quoted_runtime_marker(text, marker_start):
        return 0

    candidate = text[marker_start:]
    if ">" in candidate or "\n" in candidate or "\r" in candidate:
        return 0

    name_match = re.match(
        r"<\s*([A-Z0-9_]*)",
        candidate,
        re.IGNORECASE,
    )
    if name_match is None:
        return 0

    typed_name = str(name_match.group(1) or "").upper()
    allowed_names = []
    for action_name in enabled_action_names:
        if not _runtime_action_allows_inline_payload(action_name):
            continue
        private_marker, _ = _runtime_action_marker_config(action_name)
        marker_name, _ = extract_private_marker_parts(private_marker)
        for name in (marker_name, action_name):
            normalized = str(name or "").strip().upper()
            if normalized and normalized not in allowed_names:
                allowed_names.append(normalized)

    if not allowed_names:
        return 0

    if not typed_name:
        return len(candidate) if candidate[1:].strip() == "" else 0

    if any(
        name.startswith(typed_name)
        for name in allowed_names
    ):
        return len(candidate)

    return 0


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

    # Retain a possible literal opener even when '<' arrives in the next chunk.
    if text[-1] in RUNTIME_ACTION_QUOTE_OPENERS:
        return 1

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

        if marker_flags & _MARKER_PREFIX_ANGLE:
            if not is_quoted_runtime_marker(text, len(text) - length):
                return length

    return _trailing_inline_jin_marker_length(
        text,
        enabled_action_names,
    )


@lru_cache(maxsize=None)
def _enabled_action_stream_candidates(
    enabled_action_names: tuple[str, ...],
) -> tuple[str, ...]:
    signal_names = []

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

    return tuple(signal_names)


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
    signal_names = _enabled_action_stream_candidates(
        enabled_action_names
    )

    # No opening angle bracket means no runtime action. Names such as
    # Runtime action names in prose, Markdown/code spans, or
    # standalone lines must pass through unchanged.
    if "<" not in upper_text:
        return False

    return any(
        signal_name in upper_text
        for signal_name in signal_names
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
        if action_name == RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY:
            marker_start = (
                _unclosed_update_active_memory_attribute_start(
                    text
                )
            )

            if marker_start is not None:
                marker_starts.append(
                    marker_start
                )

        private_marker, close_tag = _runtime_action_marker_config(
            action_name
        )
        marker_start = find_unclosed_runtime_action_start(
            text,
            private_marker,
            action_name,
            close_tag,
            allow_inline_payload=(
                _runtime_action_allows_inline_payload(
                    action_name
                )
            ),
        )

        if marker_start is not None:
            marker_starts.append(
                marker_start
            )

    if not marker_starts:
        return None

    return min(
        marker_starts
    )


def _unclosed_update_active_memory_attribute_start(
    text: str,
) -> int | None:

    value = str(
        text
        or ""
    )

    if not value:
        return None

    marker_start = value.rfind(
        "<"
    )

    if marker_start < 0 or is_quoted_runtime_marker(text, marker_start):
        return None

    candidate = value[
        marker_start:
    ]

    if ">" in candidate:
        return None

    if re.fullmatch(
        r"<\s*UPDATE_ACTIVE_MEMORY(?:\s+[^<>]*)?",
        candidate,
        re.IGNORECASE | re.DOTALL,
    ) is None:
        return None

    return marker_start


def _asset_action_stream_payload_has_action(
    candidate: str,
) -> bool:

    value = str(candidate or "").lstrip()

    if not value.startswith("{"):
        return False

    return bool(
        re.search(
            r'"action"\s*:\s*"[^"\r\n]+"',
            value,
            re.IGNORECASE,
        )
    )


def _asset_action_block_has_payload(
    text: str,
    opening_match,
    private_marker: str,
) -> bool:

    tail = text[
        opening_match.end():
    ]
    next_tag = compile_runtime_action_tag_regexp(
        private_marker,
        RUNTIME_ACTION_ASSET_ACTION,
    ).search(
        tail,
    )

    if next_tag is not None:
        return bool(
            tail[:next_tag.start()].strip()
        )

    candidate = tail.strip()

    if not candidate:
        return False

    # An unclosed ASSET_ACTION is not valid yet. While its JSON body is being
    # streamed, start the pending bubble only after a real action field appears.
    # Ordinary prose after a stray opening tag must not be mistaken for payload.
    return _asset_action_stream_payload_has_action(
        candidate
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

            opening_match = start_pattern.match(
                text,
                marker_start,
            )

            update_attribute_start = (
                action_name == RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY
                and UPDATE_ACTIVE_MEMORY_START_RE.match(
                    text,
                    marker_start,
                )
                is not None
            )

            if opening_match is None and not update_attribute_start:
                continue

            if (
                action_name == RUNTIME_ACTION_ASSET_ACTION
                and not _asset_action_block_has_payload(
                    text,
                    opening_match,
                    private_marker,
                )
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
        action_names=None,
    ) -> tuple[RuntimeActionCall, ...]:

        marker_starts = []
        candidate_action_names = (
            tuple(action_names)
            if action_names is not None
            else self.enabled_actions
        )

        for action_name in candidate_action_names:
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

            # UPDATE_ACTIVE_MEMORY also supports the compact self-closing
            # attribute form, e.g.
            # <UPDATE_ACTIVE_MEMORY active_memory_id="abc123" field="x" />.
            # Detect the opening name itself, before the attribute payload
            # is complete, so its pending bubble lights up while streaming.
            if action_name == RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY:
                for match in UPDATE_ACTIVE_MEMORY_START_RE.finditer(
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
            failed_actions=result.failed_actions,
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
            # Block actions must win over a trailing ``<`` prefix. When a
            # chunk ends at the first character of a closing tag, the generic
            # prefix detector would otherwise emit the still-open block body
            # as visible text and keep only ``<`` pending.
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
                started_actions = (
                    self._find_started_actions(ready_text)
                    + self._build_started_actions(combined, unclosed_start)
                )
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
                # The pending buffer begins at the outer opening marker
                # (possibly after whitespace). Don't rescan its private body
                # for nested actions on every content chunk.
                started_actions = (
                    () if self.pending_started_actions else self._build_started_actions(
                        self.pending, len(self.pending) - len(self.pending.lstrip()),
                    )
                )

                return RuntimeActionResult(
                    text="",
                    started_actions=started_actions,
                )

        self.pending = ""
        self.pending_is_action = False
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
            started_actions = (
                self._find_started_actions(ready_text)
                + self._build_started_actions(combined, unclosed_start)
            )

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

        started_actions = self._find_started_actions(combined)
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

        marker_start = _unclosed_internal_action_request_start(
            pending,
            enabled_actions=self.enabled_actions,
        )
        if marker_start is not None:
            failed_actions = []
            for action_name in self.enabled_actions:
                if action_name not in CLOSE_TAG_RUNTIME_ACTIONS:
                    continue
                private_marker, close_tag = _runtime_action_marker_config(action_name)
                action_start = find_unclosed_runtime_action_start(
                    pending, private_marker, action_name, close_tag,
                    allow_inline_payload=_runtime_action_allows_inline_payload(action_name),
                )
                if action_name == RUNTIME_ACTION_UPDATE_ACTIVE_MEMORY:
                    attribute_start = _unclosed_update_active_memory_attribute_start(pending)
                    if attribute_start is not None:
                        action_start = attribute_start
                if action_start != marker_start:
                    continue
                opening = compile_runtime_action_start_regexp(
                    private_marker, action_name,
                ).match(pending, marker_start)
                failed_actions.append(RuntimeActionCall(
                    name=action_name,
                    payload=pending[opening.end():] if opening else pending[marker_start:],
                ))
                break

            # Never reconstruct a missing close tag or parse actions inside
            # the unfinished private body. It stays hidden and unexecuted.
            return RuntimeActionResult(
                text=pending[:marker_start] if pending[:marker_start].strip() else "",
                failed_actions=tuple(failed_actions),
                removed_markers=(pending[marker_start:],),
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
