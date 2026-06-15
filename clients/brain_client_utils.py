import re
from xml.etree import ElementTree

from bootstrap.brain_bootstrap import (
    get_last_jin_response_rules,
    get_loop_rules,
    get_memory_rules,
    MEDIA_CONTEXT_ATTRS,
    MEMORY_REQUEST_MARKERS,
    PHILOSOPHY_MARKERS,
)
from runtime.behavior_contract import (
    should_execute_action_guard,
)
from runtime.context_contract import (
    RUNTIME_ACTION_REMEMBER_EVENT,
    RUNTIME_ACTION_REMEMBER_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)
from runtime.L3_memory_utils import (
    build_runtime_session_event_snapshot,
)
from utils.runtime_actions import (
    build_runtime_action_id,
    extract_search_query,
    extract_runtime_actions,
)


# ---------------------------------------------------------
# ACCUMULATE PREVIOUS THINK FIELDS
# ---------------------------------------------------------

MAX_PREVIOUS_THINK_CHARS = 9000
MAX_PREVIOUS_THINK_SECTION_CHARS = 3000

PREVIOUS_THINK_SECTION_TITLES = (
    [
        "Analyze User Input",
        "Analyze the User Input",
        "Analyze Intent",
        "Analyze the Intent",
        "Analyze Request",
        "Analyze the Request",
        "Determine Intent",
        "Determine the Intent",
        "Interpret User Input",
        "Interpret the User Input",
        "Identify Current Task",
        "Identify the Current Task",
        "Determine Goal",
        "Determine the Goal",
    ],
    [
        "Check Context/State",
        "Check State/Context",
        "Check Memory/Context",
        "Check Context/Memory",
        "Check State",
        "Check Memory",
        "Check Context",
        "Review Context/State",
        "Review State/Context",
        "Review Context/Memory",
        "Review Memory/Context",
        "Review State",
        "Review Memory",
        "Review Context",
        "Analyze Context/State",
        "Analyze State/Context",
        "Analyze Context/Memory",
        "Analyze Memory/Context",
        "Analyze State",
        "Analyze Memory",
        "Analyze Context",
    ],
    [
        "Check last_jin_response",
    ],
    [
        "Formulate Response",
        "Formulate the Response",
        "Final Output Generation",
        "Final Polish",
        "Formulate Response (JIN Persona)",
        "Execution"
    ],
)

PREVIOUS_THINK_SECTION_RE = re.compile(
    r"(?m)^\s*\d+\.\s+(?P<title>.+)$"
)


COUNTDOWN_CONTRACT_RULES = (
    "Runtime countdown_contract is active.\n"
    "Treat every countdown_contract line in RUNTIME_MEMORY as an active "
    "user-facing obligation from creation until it is completed or cancelled.\n"
    "Countdown contracts are turn-based or time-based obligations; use the "
    "contract fields in RUNTIME_MEMORY as trusted state.\n"
    "If countdown_contract status is active and remaining is greater than 0, "
    "do not execute the trigger early, but preserve the obligation in your "
    "response planning.\n"
    "If countdown_contract status is due or remaining is 0, execute its trigger "
    "in this answer as an actual direct user-facing action or question.\n"
    "For due recall triggers, ask the user for the remembered value without "
    "revealing, quoting, paraphrasing, or restating the stored value first.\n"
)


def normalize_previous_think_section_title(
    title: str,
) -> str:

    cleaned = (
        title
        .strip()
        .replace(
            "**",
            "",
        )
        .replace(
            "`",
            "",
        )
        .strip()
    )

    cleaned = re.sub(
        r"(?i)\b(Check\s+)[\"'](last_jin_response)[\"']",
        r"\1\2",
        cleaned,
    )

    return cleaned.strip()


def match_previous_think_section_title(
    title: str,
) -> str:

    normalized = normalize_previous_think_section_title(
        title
    )

    normalized_lower = normalized.lower()

    for configured_title in PREVIOUS_THINK_SECTION_TITLES:

        if isinstance(
            configured_title,
            str,
        ):
            aliases = [
                configured_title,
            ]
        elif isinstance(
            configured_title,
            (
                list,
                tuple,
            ),
        ):
            aliases = [
                alias
                for alias in configured_title
                if isinstance(
                    alias,
                    str,
                )
            ]
        else:
            aliases = []

        if not aliases:
            continue

        canonical_title = aliases[0]

        for alias in aliases:

            alias_lower = (
                normalize_previous_think_section_title(
                    alias
                )
                .lower()
            )

            if not alias_lower:
                continue

            if (
                normalized_lower == alias_lower
                or normalized_lower.startswith(
                    f"{alias_lower}:"
                )
            ):
                return canonical_title

    return ""


def clean_previous_think_section_text(
    section_text: str,
) -> str:

    lines = section_text.splitlines()

    if not lines:
        return ""

    heading_match = PREVIOUS_THINK_SECTION_RE.match(
        lines[0]
    )

    if not heading_match:
        cleaned_lines = lines
    else:
        heading = normalize_previous_think_section_title(
            heading_match.group(
                "title"
            )
        )

        cleaned_lines = [
            heading,
            *lines[1:],
        ]

    cleaned = "\n".join(
        cleaned_lines
    )

    cleaned = cleaned.replace(
        "**",
        "",
    )

    return cleaned.strip()


def trim_previous_think_section_text(
    section_text: str,
) -> tuple[str, bool]:

    trimmed = (
        len(
            section_text
        )
        > MAX_PREVIOUS_THINK_SECTION_CHARS
    )

    if not trimmed:
        return (
            section_text,
            False,
        )

    return (
        section_text[
            :MAX_PREVIOUS_THINK_SECTION_CHARS
        ].rstrip(),
        True,
    )


def extract_previous_think_tail(
    text: str,
) -> dict:

    if not isinstance(
        text,
        str,
    ):
        text = ""

    sections = []
    sections_found = []
    section_trimmed = False
    matches = list(
        PREVIOUS_THINK_SECTION_RE.finditer(
            text
        )
    )

    for index, match in enumerate(
        matches
    ):

        section_title = match_previous_think_section_title(
            match.group(
                "title"
            )
        )

        if not section_title:
            continue

        next_match = (
            matches[index + 1]
            if index + 1 < len(matches)
            else None
        )

        section_text = text[
            match.start(): (
                next_match.start()
                if next_match
                else len(text)
            )
        ].strip()

        section_text = clean_previous_think_section_text(
            section_text
        )

        if not section_text:
            continue

        section_text, was_section_trimmed = (
            trim_previous_think_section_text(
                section_text
            )
        )
        section_trimmed = (
            section_trimmed
            or was_section_trimmed
        )

        sections.append(
            section_text
        )
        sections_found.append(
            section_title
        )

    extracted = "\n\n".join(
        sections
    ).strip()

    total_trimmed = (
        len(
            extracted
        )
        > MAX_PREVIOUS_THINK_CHARS
    )

    if total_trimmed:
        extracted = extracted[
            :MAX_PREVIOUS_THINK_CHARS
        ].rstrip()

    trimmed = (
        section_trimmed
        or total_trimmed
    )

    return {
        "text": extracted,
        "sections_found": sections_found,
        "chars": len(
            extracted
        ),
        "trimmed": trimmed,
    }


def build_previous_think_block(
    text: str,
) -> tuple[str, dict]:

    extracted = extract_previous_think_tail(
        text
    )

    metadata = {
        "previous_think_appended": bool(
            extracted["text"]
        ),
        "previous_think_sections_found": (
            extracted["sections_found"]
        ),
        "previous_think_chars": extracted["chars"],
        "previous_think_trimmed": extracted["trimmed"],
    }

    if not extracted["text"]:
        return (
            "",
            metadata,
        )

    return (
        "\n".join([
            "<LOW_PRIORITY_PREVIOUS_THINK>",
            extracted["text"],
            "</LOW_PRIORITY_PREVIOUS_THINK>",
        ]),
        metadata,
    )


def get_previous_think_context_block(
    context=None,
) -> str:

    previous_think = getattr(
        context,
        "runtime_previous_think_raw",
        "",
    )

    block, metadata = build_previous_think_block(
        previous_think
    )

    if context is not None:
        context.runtime_previous_think_payload_log = metadata

    return block


def record_previous_think(
    context,
    reasoning: str,
):

    if context is None:
        return

    if not isinstance(
        reasoning,
        str,
    ):
        reasoning = ""

    context.runtime_previous_think_raw = reasoning


async def log_previous_think_payload(
    context,
):
    return

def get_enabled_runtime_actions(
    runtime_actions=None,
) -> tuple[str, ...]:

    enabled_actions = []

    action_flags = runtime_actions or {}

    for action_name, config_key in (
        (
            RUNTIME_ACTION_WEB_SEARCH,
            "CAN_WEB_SEARCH",
        ),
        (
            RUNTIME_ACTION_REMEMBER_SESSION,
            "CAN_REMEMBER_SESSION",
        ),
        (
            RUNTIME_ACTION_REMEMBER_EVENT,
            "CAN_REMEMBER_EVENT",
        ),
    ):

        if bool(
            action_flags.get(
                config_key,
                False,
            )
        ):
            enabled_actions.append(
                action_name
            )

    return tuple(
        enabled_actions
    )


def count_deep_thought_calls(
    text: str,
    runtime_actions=None,
) -> int:

    return 0


def record_deep_thought_calls(
    context,
    reasoning: str,
) -> int:

    return 0


def should_execute_remember_session(
    user_message: str,
) -> bool:
    return should_execute_action_guard(
        "remember_session",
        user_message
    )


def is_user_initiated_remember_event(
    user_message: str,
) -> bool:
    return should_execute_action_guard(
        "remember_event",
        user_message
    )


def resolve_runtime_action_user_message(
    context,
    user_message: str | None = None,
) -> str:

    if user_message:
        return user_message

    if context is None:
        return ""

    for attr_name in (
        "runtime_turn_user_message",
        "original_user_input",
        "user_input",
    ):

        value = getattr(
            context,
            attr_name,
            "",
        )

        if value:
            return value

    return ""


async def apply_runtime_action_calls(
    context,
    actions,
    user_message: str | None = None,
) -> int:

    if (
        context is None
        or not actions
    ):
        return 0

    if not hasattr(
        context,
        "runtime_action_events",
    ):
        context.runtime_action_events = []

    if not hasattr(
        context,
        "runtime_search_calls",
    ):
        context.runtime_search_calls = []

    search_action_count = sum(
        1
        for event in context.runtime_action_events
        if event.get("name") == "web_search"
    )

    search_calls = []
    filtered_actions = []
    search_query_seen = False
    remember_session_seen = bool(
        getattr(
            context,
            "runtime_remember_session_requested",
            False,
        )
    )
    remember_session_action_emitted = bool(
        getattr(
            context,
            "runtime_remember_session_action_emitted",
            False,
        )
    )
    remember_event_seen = False
    resolved_user_message = resolve_runtime_action_user_message(
        context,
        user_message,
    )

    for action in actions:

        if action.name == RUNTIME_ACTION_REMEMBER_SESSION:
            if not should_execute_remember_session(
                resolved_user_message
            ):
                continue

            if remember_session_seen:
                if not remember_session_action_emitted:
                    remember_session_action_emitted = True
                    filtered_actions.append(
                        action
                    )

                continue

            remember_session_seen = True
            remember_session_action_emitted = True
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_REMEMBER_EVENT:
            if remember_event_seen:
                continue

            remember_event_seen = True
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

            if (
                not query
                or search_query_seen
                or getattr(
                    context,
                    "runtime_search_queries",
                    [],
                )
            ):
                continue

            search_query_seen = True

        filtered_actions.append(
            action
        )

    if not filtered_actions:
        return 0

    for action in filtered_actions:

        action_event = {
            "name": action.name.lower(),
        }

        query = ""

        if action.name == RUNTIME_ACTION_WEB_SEARCH:
            query = extract_search_query(
                action.payload
            )

        if query:
            search_action_count += 1
            tool_call_id = build_runtime_action_id(
                action.name,
                search_action_count,
            )
            action_event["id"] = tool_call_id
            action_event["query"] = query
            search_calls.append({
                "id": tool_call_id,
                "query": query,
            })

        elif action.payload:
            action_event["payload"] = (
                action.payload
            )

        context.runtime_action_events.append(
            action_event
        )

    remember_session_count = sum(
        1
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_REMEMBER_SESSION
    )

    remember_event_count = sum(
        1
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_REMEMBER_EVENT
    )

    search_queries = [
        query
        for query in (
            extract_search_query(
                action.payload
            )
            for action in filtered_actions
            if action.name == RUNTIME_ACTION_WEB_SEARCH
        )
        if query
    ]

    if search_queries:
        if not hasattr(
            context,
            "runtime_search_queries",
        ):
            context.runtime_search_queries = []

        context.runtime_search_queries.extend(
            search_queries
        )

        context.runtime_search_calls.extend(
            search_calls
        )

    logger = getattr(
        context,
        "logger",
        None,
    )
    log_runtime = getattr(
        logger,
        "log_runtime",
        None,
    )

    if (
        log_runtime is not None
        and search_queries
    ):
        await log_runtime(
            "[RUNTIME ACTION] "
            f"search x{len(search_queries)}"
        )

    if remember_session_count:
        context.runtime_remember_session_armed = False
        context.runtime_remember_session_requested = True
        context.runtime_remember_session_action_emitted = True

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] remember_session requested"
            )

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            await emit({
                "type": "runtime_action",
                "action": "remember_session",
                "text": "Remembering this session",
            })

    if remember_event_count:
        initiated_by = (
            "user"
            if is_user_initiated_remember_event(
                resolved_user_message
            )
            else "jin"
        )

        if not hasattr(
            context,
            "runtime_session_event_snapshots",
        ):
            context.runtime_session_event_snapshots = []

        context.runtime_session_event_snapshots.append(
            build_runtime_session_event_snapshot(
                context,
                source="runtime_action",
                initiated_by=initiated_by,
            )
        )

        if log_runtime is not None:
            await log_runtime(
                "[RUNTIME ACTION] remember_event saved"
            )

        emitter = getattr(
            context,
            "emitter",
            None,
        )
        emit = getattr(
            emitter,
            "emit",
            None,
        )

        if emit is not None:
            session_memory = (
                getattr(
                    context,
                    "runtime_l3_session_memory",
                    "",
                )
                or getattr(
                    context,
                    "session_memory",
                    "",
                )
            )
            await emit({
                "type": "runtime_action",
                "action": "remember_event",
                "text": "Remembering this event",
            })
            await emit({
                "type": "runtime_session_memory_update",
                "memory": session_memory,
                "event_snapshots": list(
                    context.runtime_session_event_snapshots
                ),
                "updates": getattr(
                    context,
                    "runtime_session_memory_updates",
                    0,
                ),
                "source": getattr(
                    context,
                    "session_memory_source",
                    "",
                ),
                "persist": True,
            })

    return len(
        search_queries
    ) + min(
        remember_session_count,
        1,
    ) + min(
        remember_event_count,
        1,
    )



def indent_xml(
    value: str,
    *,
    spaces: int = 8,
) -> str:

    prefix = " " * spaces
    lines = (
        value
        or ""
    ).strip().splitlines()

    return "\n".join(
        f"{prefix}{line}"
        for line in lines
    )


def strip_empty_results_xml(
    value: str,
) -> str:

    source = (
        value
        or ""
    ).strip()

    if not source:
        return ""

    try:
        root = ElementTree.fromstring(
            source
        )

    except ElementTree.ParseError:
        return source

    def prune_empty_results(
        element,
    ) -> None:

        for child in list(
            element
        ):
            prune_empty_results(
                child
            )

            if child.tag != "RESULTS":
                continue

            if list(
                child
            ):
                continue

            if (
                child.text
                and child.text.strip()
            ):
                continue

            element.remove(
                child
            )

    prune_empty_results(
        root
    )

    return ElementTree.tostring(
        root,
        encoding="unicode",
        short_empty_elements=False,
    )


def get_conversation_activity_diff(
    context=None,
) -> float | None:

    if context is None:
        return None

    recorded_diff = getattr(
        context,
        "runtime_conversation_activity_diff",
        None,
    )

    if recorded_diff is not None:
        try:
            return float(
                recorded_diff
            )
        except (
            TypeError,
            ValueError,
        ):
            pass

    patch_sources = (
        getattr(
            context,
            "runtime_l2_pending_patches",
            None,
        )
        or getattr(
            context,
            "runtime_memory_snapshots",
            None,
        )
        or []
    )

    for patch in reversed(
        patch_sources
    ):

        if not isinstance(
            patch,
            dict,
        ):
            continue

        total_diff = patch.get(
            "total_diff",
        )

        if total_diff is None:
            continue

        try:
            return float(
                total_diff
            )
        except (
            TypeError,
            ValueError,
        ):
            continue

    return None


def get_conversation_activity_percent(
    diff: float,
) -> int:

    return max(
        0,
        min(
            100,
            int(
                round(
                    diff
                )
            ),
        ),
    )


def has_zero_diff_stall_alert(
    context=None,
) -> bool:

    if context is None:
        return False

    return bool(
        getattr(
            context,
            "runtime_zero_diff_alert",
            None,
        )
    )

def _get_current_user_message(
    context=None,
) -> str:

    if context is None:
        return ""

    for attr_name in (
        "runtime_turn_user_message",
        "original_user_input",
        "user_input",
        "last_user_message",
    ):

        value = getattr(
            context,
            attr_name,
            "",
        )

        if value:
            return str(
                value
            )

    return ""


def _normalized_text(
    value: str,
) -> str:

    return (
        value
        or ""
    ).casefold().replace(
        "ё",
        "е",
    )


def _contains_any_marker(
    text: str,
    markers: tuple[str, ...],
) -> bool:

    normalized = _normalized_text(
        text
    )

    return any(
        _normalized_text(
            marker
        ) in normalized
        for marker in markers
    )

def has_countdown_contract(
    context=None,
) -> bool:

    if context is None:
        return False

    runtime_memory = str(
        getattr(
            context,
            "runtime_memory",
            "",
        )
        or ""
    )

    for raw_line in runtime_memory.splitlines():
        line = raw_line.strip()

        while line.startswith("-"):
            line = line[1:].strip()

        key = line.split(
            ":",
            1,
        )[0].strip().casefold()

        if key == "countdown_contract":
            return True

    return False


def has_memory_rule_request(
    context=None,
) -> bool:

    if context is None:
        return False

    explicit_flag = getattr(
        context,
        "has_memory_request",
        None,
    )

    if explicit_flag is not None:
        return bool(
            explicit_flag
        )

    user_message = _get_current_user_message(
        context
    )

    return _contains_any_marker(
        user_message,
        MEMORY_REQUEST_MARKERS,
    )


def has_loop_rule_signal(
    context=None,
) -> bool:

    if context is None:
        return False

    pattern_counter = getattr(
        context,
        "runtime_pattern_counter",
        0,
    )

    try:
        return int(
            pattern_counter
        ) > 1
    except (
        TypeError,
        ValueError,
    ):
        return False


def has_media_context(
    context=None,
) -> bool:

    if context is None:
        return False

    explicit_flag = getattr(
        context,
        "has_media",
        None,
    )

    if explicit_flag is not None:
        return bool(
            explicit_flag
        )

    for attr_name in MEDIA_CONTEXT_ATTRS:
        value = getattr(
            context,
            attr_name,
            None,
        )

        if value:
            return True

    return False


def is_philosophy_mode_active(
    context=None,
) -> bool:

    if context is None:
        return False

    explicit_flag = getattr(
        context,
        "philosophy_active",
        None,
    )

    if explicit_flag is not None:
        return bool(
            explicit_flag
        )

    user_message = _get_current_user_message(
        context
    )

    return _contains_any_marker(
        user_message,
        PHILOSOPHY_MARKERS,
    )


def build_conditional_prompt_rules(
    context=None,
) -> str:

    rules = [
        ""
    ]

    if has_countdown_contract(
        context
    ):
        rules.append(
            COUNTDOWN_CONTRACT_RULES
        )

    if has_loop_rule_signal(
        context
    ):
        rules.append(
            get_loop_rules()
        )

    return "".join(
        rules
    )
