import asyncio
import json
from datetime import datetime
from xml.etree import ElementTree
from xml.sax.saxutils import escape

from config_loader import (
    config,
)
from runtime.context_contract import (
    ContextContract,
    RUNTIME_ACTION_DEEP_THOUGHT,
    RUNTIME_ACTION_REMEMBER_EVENT,
    RUNTIME_ACTION_REMEMBER_SESSION,
    RUNTIME_ACTION_WEB_SEARCH,
)
from runtime.memory_rules import (
    build_runtime_memory_context_text,
    build_runtime_session_event_snapshot,
    canonicalize_runtime_memory_text,
)

from bootstrap.brain_bootstrap import (
    ZERO_DIFF_STALL_ACTIVE_RULE,
    build_brain_runtime_interface_rules,
    build_brain_soft_success_rules,
    build_conversation_activity_instruction,
    build_identity_context,
    build_zero_diff_stall_instruction,
    get_image_input_rules,
    get_last_jin_response_rules,
    get_loop_rules,
    get_memory_rules,
    get_philosophy_mode,
    SAVE_SESSION_INTENT_MARKERS,
    META_TAG_REQUEST_MARKERS,
    MEMORY_REQUEST_MARKERS,
    PHILOSOPHY_MARKERS,
    MEDIA_CONTEXT_ATTRS,
)

from clients.errors import (
    format_client_error,
)

from clients.service_client import (
    ask_service_model,
    ask_service_model_stream,
)

from clients.response_extractor import (
    ResponseExtractor,
)

from utils.runtime_actions import (
    RuntimeActionStreamFilter,
    build_runtime_action_id,
    extract_search_query,
    extract_runtime_actions,
)


# ---------------------------------------------------------
# SYSTEM PROMPT
# ---------------------------------------------------------

def get_enabled_runtime_actions(
    runtime_actions=None,
) -> tuple[str, ...]:

    enabled_actions = []

    action_flags = runtime_actions or {}

    for action_name, config_key in (
        (
            RUNTIME_ACTION_DEEP_THOUGHT,
            "CAN_DEEP_THOUGHT",
        ),
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


def get_enabled_thinking_runtime_actions(
    runtime_actions=None,
) -> tuple[str, ...]:

    return get_enabled_runtime_actions(
        runtime_actions
    )


def count_deep_thought_calls(
    text: str,
    runtime_actions=None,
) -> int:

    return (
        extract_runtime_actions(
            text,
            enabled_actions=(
                get_enabled_runtime_actions(
                    runtime_actions
                )
            ),
        )
        .deep_thought_count
    )


async def apply_deep_thought_calls(
    context,
    call_count: int,
) -> int:

    if (
        context is None
        or not call_count
    ):
        return 0

    current_count = getattr(
        context,
        "deep_thought_count",
        0,
    )

    context.deep_thought_count = (
        current_count
        + call_count
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

    if log_runtime is not None:
        await log_runtime(
            "[RUNTIME ACTION] "
            f"deep_thought x{call_count}; "
            f"counter={context.deep_thought_count}"
        )

    return call_count


def _normalize_action_guard_text(
    text: str,
) -> str:

    return (
        text
        or ""
    ).casefold().replace(
        "ё",
        "е",
    )


def should_execute_remember_session(
    user_message: str,
) -> bool:

    normalized_message = _normalize_action_guard_text(
        user_message
    )

    if not normalized_message:
        return False

    has_meta_request = any(
        _normalize_action_guard_text(
            marker
        ) in normalized_message
        for marker in META_TAG_REQUEST_MARKERS
    )

    if has_meta_request:
        return False

    return any(
        _normalize_action_guard_text(
            marker
        ) in normalized_message
        for marker in SAVE_SESSION_INTENT_MARKERS
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
    remember_event_seen = False
    deep_thought_seen = False
    resolved_user_message = resolve_runtime_action_user_message(
        context,
        user_message,
    )

    for action in actions:

        if action.name == RUNTIME_ACTION_DEEP_THOUGHT:
            if deep_thought_seen:
                continue

            deep_thought_seen = True
            filtered_actions.append(
                action
            )
            continue

        if action.name == RUNTIME_ACTION_REMEMBER_SESSION:
            if not should_execute_remember_session(
                resolved_user_message
            ):
                continue

            if remember_session_seen:
                continue

            remember_session_seen = True
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

    deep_thought_count = sum(
        1
        for action in filtered_actions
        if action.name == RUNTIME_ACTION_DEEP_THOUGHT
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

    applied_count = await apply_deep_thought_calls(
        context,
        min(
            deep_thought_count,
            1,
        ),
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
        context.runtime_remember_session_requested = True

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
        if not hasattr(
            context,
            "runtime_session_event_snapshots",
        ):
            context.runtime_session_event_snapshots = []

        context.runtime_session_event_snapshots.append(
            build_runtime_session_event_snapshot(
                context,
                source="runtime_action",
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

    return applied_count + len(
        search_queries
    ) + min(
        remember_session_count,
        1,
    ) + min(
        remember_event_count,
        1,
    )


def record_deep_thought_calls(
    context,
    reasoning: str,
) -> int:

    call_count = count_deep_thought_calls(
        reasoning
    )

    if not call_count:
        return 0

    call_count = min(
        call_count,
        1,
    )

    current_count = getattr(
        context,
        "deep_thought_count",
        0,
    )

    context.deep_thought_count = (
        current_count
        + call_count
    )

    return call_count


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


def build_brain_runtime_context(
    context=None,
    runtime_actions=None,
) -> str:

    deep_thought_count = 0
    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )

    if context is not None:

        deep_thought_count = getattr(
            context,
            "deep_thought_count",
            0,
        )

    now = datetime.now()

    context_contract = ContextContract(
        user_input="",
        compressed_history="",
        system_state="ACTIVE",
        deep_thought_count=deep_thought_count,
        can_deep_thought=(
            RUNTIME_ACTION_DEEP_THOUGHT
            in enabled_actions
        ),
        can_web_search=(
            RUNTIME_ACTION_WEB_SEARCH
            in enabled_actions
        ),
        can_remember_session=(
            RUNTIME_ACTION_REMEMBER_SESSION
            in enabled_actions
        ),
        can_remember_event=(
            RUNTIME_ACTION_REMEMBER_EVENT
            in enabled_actions
        ),
        timestamp=now.isoformat(),
        current_date=now.date().isoformat(),
        current_time=now.strftime("%H:%M:%S"),
        weekday=now.strftime("%A"),
        year=now.year,
    )

    runtime_xml = (
        context_contract
        .to_runtime_xml()
    )

    session_state_xml = ""

    if context is not None:
        session_state_xml = (
            "<SESSION_STATE>\n"
            f"    <TURN_NUMBER>{getattr(context, 'turn_number', 0)}</TURN_NUMBER>\n"
            f"    <USER_MESSAGE_COUNT>{getattr(context, 'user_message_count', 0)}</USER_MESSAGE_COUNT>\n"
            f"    <ASSISTANT_MESSAGE_COUNT>{getattr(context, 'assistant_message_count', 0)}</ASSISTANT_MESSAGE_COUNT>\n"
            "</SESSION_STATE>"
        )

    runtime_memory = ""
    session_memory = ""
    session_event_snapshots = []
    runtime_l2_memory = ""
    zero_diff_alert = None
    conversation_activity_diff = get_conversation_activity_diff(
        context
    )
    search_result = ""
    search_result_id = ""

    if context is not None:
        runtime_memory = getattr(
            context,
            "runtime_memory",
            "",
        )
        runtime_memory = build_runtime_memory_context_text(
            runtime_memory,
            context,
        )
        session_memory = getattr(
            context,
            "runtime_l3_session_memory",
            "",
        ) or getattr(
            context,
            "session_memory",
            "",
        )
        session_event_snapshots = list(
            getattr(
                context,
                "runtime_session_event_snapshots",
                [],
            )
            or []
        )
        runtime_l2_memory = getattr(
            context,
            "runtime_l2_memory",
            "",
        )
        zero_diff_alert = getattr(
            context,
            "runtime_zero_diff_alert",
            None,
        )
        search_result = getattr(
            context,
            "runtime_search_result",
            "",
        )
        search_result_id = getattr(
            context,
            "runtime_search_result_id",
            "",
        )

    runtime_context_parts = [
        runtime_xml
    ]

    if session_state_xml:
        runtime_context_parts.append(
            session_state_xml
        )

    if session_memory.strip():
        runtime_context_parts.append(
            "<SESSION_MEMORY priority=\"higher_than_runtime_memory\">\n"
            f"{indent_xml(escape(session_memory))}\n"
            "</SESSION_MEMORY>"
        )

    runtime_context_parts.append(
        "<SESSION_EVENT_SNAPSHOTS priority=\"session_context\">\n"
        f"{indent_xml(escape(json.dumps(session_event_snapshots, ensure_ascii=False, indent=2)))}\n"
        "</SESSION_EVENT_SNAPSHOTS>"
    )

    if runtime_memory.strip():
        runtime_context_parts.append(
            "<RUNTIME_MEMORY>\n"
            f"{indent_xml(escape(canonicalize_runtime_memory_text(runtime_memory)))}\n"
            "</RUNTIME_MEMORY>"
        )

    if runtime_l2_memory.strip():
        runtime_context_parts.append(
            "<RUNTIME_PATTERN_MEMORY>\n"
            f"{indent_xml(escape(runtime_l2_memory))}\n"
            "</RUNTIME_PATTERN_MEMORY>"
        )

    if conversation_activity_diff is not None:
        activity_percent = get_conversation_activity_percent(
            conversation_activity_diff
        )
        activity_instruction = build_conversation_activity_instruction(
            activity_percent
        )

        runtime_context_parts.append(
            "<CONVERSATION_ACTIVITY>\n"
            f"    <PERCENT>{activity_percent}</PERCENT>\n"
            "    <INSTRUCTION>\n"
            f"{indent_xml(escape(activity_instruction))}\n"
            "    </INSTRUCTION>\n"
            "</CONVERSATION_ACTIVITY>"
        )

    if zero_diff_alert:
        alert_user_message = (
            zero_diff_alert.get(
                "user_message",
                "",
            )
            if isinstance(
                zero_diff_alert,
                dict,
            )
            else ""
        )
        alert_assistant_message = (
            zero_diff_alert.get(
                "assistant_message",
                "",
            )
            if isinstance(
                zero_diff_alert,
                dict,
            )
            else ""
        )
        alert_turn_number = (
            zero_diff_alert.get(
                "turn_number",
                0,
            )
            if isinstance(
                zero_diff_alert,
                dict,
            )
            else 0
        )

        runtime_context_parts.append(
            "<ZERO_DIFF_STALL_ALERT>\n"
            "    <INSTRUCTION>\n"
            f"        {build_zero_diff_stall_instruction()}\n"
            "    </INSTRUCTION>\n"
            f"    <TRIGGER_TURN>{alert_turn_number}</TRIGGER_TURN>\n"
            "    <TRIGGER_USER_MESSAGE>\n"
            f"{indent_xml(escape(alert_user_message))}\n"
            "    </TRIGGER_USER_MESSAGE>\n"
            "    <TRIGGER_JIN_RESPONSE>\n"
            f"{indent_xml(escape(alert_assistant_message))}\n"
            "    </TRIGGER_JIN_RESPONSE>\n"
            "</ZERO_DIFF_STALL_ALERT>"
        )

    if not search_result:
        return "\n".join(
            runtime_context_parts
        )

    search_result = strip_empty_results_xml(
        search_result
    )

    tool_result_attrs = (
        'name="WEB_SEARCH"'
    )

    if search_result_id:
        tool_result_attrs = (
            f'{tool_result_attrs} '
            f'id="{escape(search_result_id)}"'
        )

    tool_results_xml = (
        '<TOOL_RESULTS type=\'external_untrusted_evidence\'>\n'
        f"    <TOOL_RESULT {tool_result_attrs}>\n"
        f"{indent_xml(search_result)}\n"
        "    </TOOL_RESULT>\n"
        "</TOOL_RESULTS>"
    )

    return (
        "\n".join(
            runtime_context_parts
            + [
                tool_results_xml
            ]
        )
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
        None,
    )

    if pattern_counter is not None:
        try:
            return int(
                pattern_counter
            ) > 0
        except (
            TypeError,
            ValueError,
        ):
            return False

    runtime_l2_memory = getattr(
        context,
        "runtime_l2_memory",
        "",
    )

    return bool(
        str(
            runtime_l2_memory
            or ""
        ).strip()
    )


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
        get_last_jin_response_rules(),
    ]

    if has_memory_rule_request(
        context
    ):
        rules.append(
            get_memory_rules()
        )

    if has_loop_rule_signal(
        context
    ):
        rules.append(
            get_loop_rules()
        )

    if has_media_context(
        context
    ):
        rules.append(
            get_image_input_rules()
        )

    if is_philosophy_mode_active(
        context
    ):
        rules.append(
            get_philosophy_mode()
        )

    return "".join(
        rules
    )


def build_brain_system_prompt(
    context=None,
    runtime_actions=None,
) -> str:

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )

    zero_diff_stall_active = has_zero_diff_stall_alert(
        context
    )

    soft_rules = ""

    if zero_diff_stall_active:
        soft_rules = (
            ZERO_DIFF_STALL_ACTIVE_RULE
        )
    else:
        soft_rules = build_brain_soft_success_rules()

    return (
        f"{build_identity_context(context)}"
        f"{soft_rules}"
        f"{build_conditional_prompt_rules(context)}"
        f"{build_brain_runtime_interface_rules(enabled_actions)}"
        "\n"
        f"{build_brain_runtime_context(context, runtime_actions)}"
    )


# ---------------------------------------------------------
# PAYLOAD
# ---------------------------------------------------------

def build_brain_payload(
    text: str,
    context=None,
) -> str:

    return text


# ---------------------------------------------------------
# NORMAL REQUEST
# ---------------------------------------------------------

async def ask_brain(
    *,
    client,
    text: str,
    context=None,
    runtime_actions=None,
) -> str:

    brain_payload = (
        build_brain_payload(
            text,
            context=context,
        )
    )

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            result = await ask_service_model(
                client=client,
                user_prompt=brain_payload,
                system_prompt=(
                    build_brain_system_prompt(
                        context,
                        runtime_actions,
                    )
                ),
                temperature=(
                    config.BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config.BRAIN_MAX_TOKENS
                ),
            )

            reasoning = (
                ResponseExtractor.extract_reasoning_text(
                    result
                )
            )

            content = (
                ResponseExtractor
                .extract_content_text(
                    result
                )
            )

            enabled_actions = get_enabled_runtime_actions(
                runtime_actions
            )
            thinking_actions = get_enabled_thinking_runtime_actions(
                runtime_actions
            )

            reasoning_actions = (
                extract_runtime_actions(
                    reasoning,
                    enabled_actions=thinking_actions,
                    preserve_action_text=True,
                )
            )

            content_actions = (
                extract_runtime_actions(
                    content,
                    enabled_actions=enabled_actions,
                )
            )

            await apply_runtime_action_calls(
                context,
                (
                    reasoning_actions.actions
                    + content_actions.actions
                ),
                user_message=text,
            )

            return content_actions.text

        except Exception as error:

            formatted_error = (
                format_client_error(
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        result = await client.ask(
            system_prompt=(
                build_brain_system_prompt(
                    context,
                    runtime_actions,
                )
            ),
            user_prompt=brain_payload,
            temperature=(
                config
                .BRAIN_TEMPERATURE
            ),
            max_tokens=(
                config
                .BRAIN_MAX_TOKENS
            ),
        )

        returned_model = (
            ResponseExtractor
            .extract_model(
                result
            )
        )

        if (
            returned_model
            != config.BRAIN_MODEL_UID
        ):

            raise RuntimeError(
                f"Wrong model loaded. "
                f"Expected "
                f"'{config.BRAIN_MODEL_UID}', "
                f"got "
                f"'{returned_model}'"
            )

        reasoning = (
            ResponseExtractor
            .extract_reasoning_text(
                result
            )
        )

        content = (
            ResponseExtractor
            .extract_content_text(
                result
            )
        )

        enabled_actions = get_enabled_runtime_actions(
            runtime_actions
        )
        thinking_actions = get_enabled_thinking_runtime_actions(
            runtime_actions
        )

        reasoning_actions = extract_runtime_actions(
            reasoning,
            enabled_actions=thinking_actions,
            preserve_action_text=True,
        )

        content_actions = extract_runtime_actions(
            content,
            enabled_actions=enabled_actions,
        )

        await apply_runtime_action_calls(
            context,
            (
                reasoning_actions.actions
                + content_actions.actions
            ),
            user_message=text,
        )

        if content_actions.text:
            return content_actions.text

        return extract_runtime_actions(
            reasoning,
            enabled_actions=thinking_actions,
        ).text

    except Exception as error:

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )


# ---------------------------------------------------------
# STREAM REQUEST
# ---------------------------------------------------------

async def ask_brain_stream(
    *,
    client,
    text: str,
    context,
    system_prompt: str | None = None,
    brain_payload: str | None = None,
    runtime_actions=None,
):

    resolved_brain_payload: str = (
        brain_payload
        or build_brain_payload(
            text,
            context=context,
        )
    )

    resolved_system_prompt: str = (
        system_prompt
        or build_brain_system_prompt(
            context,
            runtime_actions,
        )
    )

    enabled_actions = get_enabled_runtime_actions(
        runtime_actions
    )
    thinking_actions = get_enabled_thinking_runtime_actions(
        runtime_actions
    )

    thinking_filter = RuntimeActionStreamFilter(
        enabled_actions=thinking_actions,
        preserve_action_text=True,
    )
    content_filter = RuntimeActionStreamFilter(
        enabled_actions=enabled_actions
    )
    deep_thought_action_executed = False
    stop_for_runtime_action = False

    async def filter_runtime_action_chunk(
        action_chunk,
    ):

        nonlocal deep_thought_action_executed
        nonlocal stop_for_runtime_action

        chunk_type = action_chunk.get(
            "type"
        )

        if chunk_type not in (
            "thinking",
            "content",
        ):
            return action_chunk

        stream_filter = (
            thinking_filter
            if chunk_type == "thinking"
            else content_filter
        )

        result = stream_filter.filter(
            action_chunk.get(
                "content",
                "",
            )
        )

        if (
            result.deep_thought_count
            and not deep_thought_action_executed
        ):

            deep_thought_action_executed = True

            await apply_deep_thought_calls(
                context,
                1,
            )

        non_deep_actions = tuple(
            action
            for action in result.actions
            if action.name != RUNTIME_ACTION_DEEP_THOUGHT
        )

        if non_deep_actions:
            await apply_runtime_action_calls(
                context,
                non_deep_actions,
                user_message=text,
            )

            stop_for_runtime_action = any(
                action.name == RUNTIME_ACTION_WEB_SEARCH
                for action in non_deep_actions
            )

            if not stop_for_runtime_action:
                if not result.text:
                    return None

                return {
                    **action_chunk,
                    "content": result.text,
                }

            if (
                chunk_type == "thinking"
                and result.text
            ):
                return {
                    **action_chunk,
                    "content": result.text,
                }

            return None

        if not result.text:
            return None

        return {
            **action_chunk,
            "content": result.text,
        }

    # -----------------------------------------------------
    # SERVICE AS BRAIN
    # -----------------------------------------------------

    if config.USE_SERVICE_AS_BRAIN:

        try:

            async for model_chunk in (
                ask_service_model_stream(
                    context=context,
                    client=client,
                    user_prompt=(
                        resolved_brain_payload
                    ),
                    system_prompt=(
                        resolved_system_prompt
                    ),
                    temperature=(
                        config
                        .BRAIN_TEMPERATURE
                    ),
                    max_tokens=(
                        config
                        .BRAIN_MAX_TOKENS
                    ),
                )
            ):

                filtered_chunk = (
                    await filter_runtime_action_chunk(
                        model_chunk
                    )
                )

                if filtered_chunk:
                    yield filtered_chunk

                if stop_for_runtime_action:
                    break

            thinking_tail = thinking_filter.flush()
            if (
                thinking_tail
                and not stop_for_runtime_action
            ):
                yield {
                    "type": "thinking",
                    "content": thinking_tail,
                }

            content_tail = content_filter.flush()
            if (
                content_tail
                and not stop_for_runtime_action
            ):
                yield {
                    "type": "content",
                    "content": content_tail,
                }

            return

        except asyncio.CancelledError:
            raise

        except Exception as error:

            formatted_error = (
                format_client_error(
                    "service_as_brain",
                    config.SERVICE_API_BASE,
                    config.SERVICE_MODEL_UID,
                    error,
                )
            )

            raise RuntimeError(
                formatted_error
            )

    # -----------------------------------------------------
    # REAL BRAIN
    # -----------------------------------------------------

    try:

        async for model_chunk in (
            client.stream(
                context=context,
                system_prompt=(
                    resolved_system_prompt
                ),
                user_prompt=resolved_brain_payload,
                temperature=(
                    config
                    .BRAIN_TEMPERATURE
                ),
                max_tokens=(
                    config
                    .BRAIN_MAX_TOKENS
                ),
            )
        ):

            filtered_chunk = (
                await filter_runtime_action_chunk(
                    model_chunk
                )
            )

            if filtered_chunk:
                yield filtered_chunk

            if stop_for_runtime_action:
                break

        thinking_tail = thinking_filter.flush()
        if (
            thinking_tail
            and not stop_for_runtime_action
        ):
            yield {
                "type": "thinking",
                "content": thinking_tail,
            }

        content_tail = content_filter.flush()
        if (
            content_tail
            and not stop_for_runtime_action
        ):
            yield {
                "type": "content",
                "content": content_tail,
            }

    except asyncio.CancelledError:
        raise

    except Exception as error:

        formatted_error = (
            format_client_error(
                "brain",
                config.BRAIN_API_BASE,
                config.BRAIN_MODEL_UID,
                error,
            )
        )

        raise RuntimeError(
            formatted_error
        )
