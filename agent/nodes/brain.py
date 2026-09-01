from copy import deepcopy
import time
from xml.sax.saxutils import escape

from agent.nodes.base import BaseNode

from runtime.stream import (
    RuntimeStream,
)
from runtime.deep_web_search import (
    run_deep_web_search,
)

from clients.brain_client import (
    ask_brain_stream,
    build_brain_context_snapshot,
    build_brain_payload,
    emit_active_memory_records_update_if_dirty,
)
from rules.brain_context_builder import (
    build_brain_context,
)
from rules.runtime import (
    ACTION_FAILURE_FOLLOWUP_MESSAGE,
    ANSWERING_RECOVERY_MESSAGE,
    CONTEXT_LIMIT_RECOVERY_MESSAGE,
    REASONING_RECOVERY_MESSAGE,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_ATTACH_FILE,
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
    RUNTIME_ACTION_WEB_SEARCH,
)
from contracts.rules_assembler import (
    extract_private_marker_name,
    get_action_contract_name_for_runtime_action,
    get_runtime_action_display_name,
    get_runtime_action_private_marker,
    get_runtime_action_schema,
    get_runtime_action_rules,
    runtime_action_emits_followup,
    runtime_action_follows_up_on_fail,
    runtime_action_has_close_tag,
)

from clients.search_client import (
    build_search_result_fallback_answer,
    run_search_service,
)

from utils.brain_client_utils import (
    apply_runtime_action_calls,
    get_brain_runtime_config,
)
from utils.current_context_window import (
    prepare_current_context_window_prompt,
)
from utils.chat_log import (
    save_chat_bootstrap_context_snapshot,
    save_chat_context_snapshot,
)
from utils.runtime_action_abort import (
    mark_runtime_action_completed,
)

from utils.actions import (
    RuntimeActionCall,
)

from utils.actions.action_counter_utils import (
    format_runtime_action_count,
)

from utils.language import (
    contains_cyrillic,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_DEEP_SEARCH,
    TOOL_RESULT_KIND_SEARCH,
    begin_runtime_tool_results_turn,
    record_runtime_tool_result,
)
from utils.tool_results_context import (
    build_tools_results_context,
    split_tools_results_context,
)

from config_loader import (
    config,
)

def action_event_requires_follow_up(event) -> bool:

    if not isinstance(event, dict):
        return True

    status = str(event.get("status", "") or "").strip().casefold()

    if status == "aborted":
        return False

    name = str(event.get("name", "") or "").strip().casefold()

    if status == "failed":
        return runtime_action_follows_up_on_fail(
            name
        )

    return runtime_action_emits_followup(
        name
    )


def _build_failed_runtime_action_marker(event: dict) -> str:

    runtime_action = str(
        event.get("name", "")
        or ""
    ).strip()
    marker = get_runtime_action_private_marker(
        runtime_action
    )
    payload = str(
        event.get("failed_marker_payload")
        or event.get("payload")
        or ""
    ).strip()

    if not marker:
        return payload

    if not runtime_action_has_close_tag(
        runtime_action
    ):
        return " ".join(
            part
            for part in (marker, payload)
            if part
        ).strip()

    marker_name = extract_private_marker_name(
        marker
    )
    if not marker_name:
        return "\n".join(
            part
            for part in (marker, payload)
            if part
        ).strip()

    return "\n".join((
        marker,
        payload,
        f"</{marker_name}>",
    )).strip()


def build_failed_runtime_action_followup_context(
        event: dict,
) -> str:

    if not isinstance(event, dict):
        return ""

    runtime_action = str(
        event.get("name", "")
        or ""
    ).strip()
    if (
        str(event.get("status", "") or "").strip().casefold() != "failed"
        or not runtime_action_follows_up_on_fail(runtime_action)
    ):
        return ""

    failure_reason = str(
        event.get("failure_reason")
        or event.get("detail")
        or event.get("error")
        or "action failed"
    ).strip()
    display_name = get_runtime_action_display_name(
        runtime_action
    )
    mandatory_lines = []
    schema = get_runtime_action_schema(
        runtime_action
    )
    if schema:
        mandatory_lines.append(
            "Correct action schema:"
        )
        mandatory_lines.extend(schema)
    mandatory_lines.extend(
        get_runtime_action_rules(
            runtime_action
        )
    )
    mandatory_rules = "\n".join(
        mandatory_lines
    ).strip()
    failed_marker = _build_failed_runtime_action_marker(
        event
    )

    sections = [
        (
            "RUNTIME ACTION ERROR: "
            f"{display_name or runtime_action.upper()} failed: "
            f"{failure_reason}"
        ),
    ]

    if mandatory_rules:
        sections.append(
            "<MANDATORY_ACTION_RULES>\n"
            + mandatory_rules
            + "\n</MANDATORY_ACTION_RULES>"
        )

    if failed_marker:
        sections.append(
            "<FAILED_MARKER_CONTENT>\n"
            + failed_marker
            + "\n</FAILED_MARKER_CONTENT>"
        )

    return "\n\n".join(sections)


def build_failed_runtime_action_followup_contexts(
        context,
) -> str:

    if context is None:
        return ""

    current_turn_ids = {
        str(
            getattr(
                context,
                attribute,
                "",
            )
            or ""
        ).strip()
        for attribute in (
            "runtime_current_turn_id",
            "runtime_current_sequence_turn_id",
        )
    }
    current_turn_ids.discard("")
    latest_events = {}

    for index, event in enumerate(
        getattr(
            context,
            "runtime_action_events",
            [],
        )
        or []
    ):
        if not isinstance(event, dict):
            continue

        event_turn_id = str(
            event.get(
                "runtime_turn_id",
                "",
            )
            or ""
        ).strip()
        if (
            current_turn_ids
            and event_turn_id
            and event_turn_id not in current_turn_ids
        ):
            continue

        runtime_action = str(
            event.get(
                "name",
                "",
            )
            or ""
        ).strip().casefold()
        if not runtime_action_follows_up_on_fail(
            runtime_action
        ):
            continue

        latest_events[runtime_action] = (
            index,
            event,
        )

    contexts = []

    for _, event in sorted(
        latest_events.values(),
        key=lambda item: item[0],
    ):
        failure_context = (
            build_failed_runtime_action_followup_context(
                event
            )
        )
        if failure_context:
            contexts.append(
                failure_context
            )

    return "\n\n".join(
        contexts
    )


def action_event_defers_follow_up(event) -> bool:

    if not isinstance(event, dict):
        return False

    return bool(event.get("deferred_follow_up"))


async def replay_session_restore_resource_actions(
        context,
        *,
        assistant_message: str = "",
        context_snapshot=None,
) -> int:

    if not getattr(
        context,
        "runtime_session_restore_priming",
        False,
    ):
        return 0

    delayed_ids = []
    delayed_seen = set()
    for raw_id in getattr(
        context,
        "runtime_session_restore_pending_loaded_memory_ids",
        [],
    ) or []:
        report_id = str(raw_id or "").strip().casefold()
        if not report_id or report_id in delayed_seen:
            continue
        delayed_seen.add(report_id)
        delayed_ids.append(report_id)

    file_ids = []
    file_seen = set()
    for raw_id in getattr(
        context,
        "runtime_session_restore_pending_attached_file_ids",
        [],
    ) or []:
        file_id = str(raw_id or "").strip().casefold()
        if not file_id or file_id in file_seen:
            continue
        file_seen.add(file_id)
        file_ids.append(file_id)

    # Consume the restoration envelope before any possible contract-driven
    # follow-up. The initial answer was generated with metadata only; from
    # this point forward the normal runtime action pipeline owns the loaded
    # resources and any follow-up sees their real context.
    context.runtime_session_restore_pending_loaded_memory_ids = []
    context.runtime_session_restore_pending_attached_file_ids = []
    context.runtime_session_restore_priming = False
    context.runtime_session_restore_reasoning_dump = ""
    context.runtime_session_restore_lt_fact_ids = []
    context.runtime_session_restore_delayed_memory_metadata = []
    context.runtime_session_restore_attached_file_metadata = []

    actions = tuple(
        [
            RuntimeActionCall(
                name=RUNTIME_ACTION_LOAD_DELAYED_MEMORY,
                payload=report_id,
            )
            for report_id in delayed_ids
        ]
        + [
            RuntimeActionCall(
                name=RUNTIME_ACTION_ATTACH_FILE,
                payload=file_id,
            )
            for file_id in file_ids
        ]
    )

    if not actions:
        return 0

    return await apply_runtime_action_calls(
        context,
        actions,
        context_snapshot=(
            context_snapshot
            if isinstance(context_snapshot, dict)
            else None
        ),
        assistant_message=assistant_message,
    )


def action_batch_requires_follow_up(
        events,
        response_text: str,
) -> bool:

    if not events:
        return False

    events_requiring_follow_up = [
        event
        for event in events
        if action_event_requires_follow_up(event)
    ]

    if not events_requiring_follow_up:
        return False

    if all(
        action_event_defers_follow_up(event)
        for event in events_requiring_follow_up
    ):
        return False

    return True


def prepare_asset_results_for_turn(
        context,
) -> None:

    retry_results = getattr(
        context,
        "runtime_asset_retry_results",
        [],
    )

    if not isinstance(
        retry_results,
        list,
    ):
        retry_results = []

    context.runtime_asset_retry_context = [
        deepcopy(result)
        for result in retry_results
        if isinstance(
            result,
            dict,
        )
    ]
    context.runtime_asset_retry_results = []

    asset_results = getattr(
        context,
        "runtime_asset_results",
        None,
    )

    if not isinstance(
        asset_results,
        list,
    ):
        context.runtime_asset_results = []
        return

    asset_results.clear()


def build_reasoning_recovery_context(
        reason: str = "",
) -> str:

    if str(reason or "").strip() == "same answer output":
        return (
            "<ANSWERING_RECOVERY>\n"
            f"{ANSWERING_RECOVERY_MESSAGE}\n"
            "</ANSWERING_RECOVERY>"
        )

    return (
        "<REASONING_RECOVERY>\n"
        f"{REASONING_RECOVERY_MESSAGE}.\n"
        "</REASONING_RECOVERY>"
    )


def consume_action_failure_followup_context(
        context,
) -> str:

    if context is None or not bool(
        getattr(
            context,
            "runtime_followup_action_failure_pending",
            False,
        )
    ):
        return ""

    context.runtime_followup_action_failure_pending = False

    return (
        "<ACTION_FAILURE_FOLLOWUP>\n"
        f"{ACTION_FAILURE_FOLLOWUP_MESSAGE}\n"
        "</ACTION_FAILURE_FOLLOWUP>"
    )


def consume_confirm_result_context(
        context,
) -> str:

    messages = [
        str(message or "").strip()
        for message in getattr(
            context,
            "runtime_action_failure_followup_messages",
            [],
        )
        or []
        if str(message or "").strip()
    ]

    context.runtime_action_failure_followup_messages = []

    if not messages:
        return ""

    return (
        "<CONFIRM_RESULT>\n"
        + "\n".join(messages)
        + ".\n"
        "</CONFIRM_RESULT>"
    )


def build_context_limit_recovery_context(
        stage: str,
        limit_kind: str = "context",
) -> str:

    normalized_stage = str(
        stage
        or "generation"
    ).strip().casefold()

    if normalized_stage not in {
        "reasoning",
        "answer",
        "generation",
    }:
        normalized_stage = "generation"

    normalized_limit_kind = str(
        limit_kind
        or "context"
    ).strip().casefold()
    limit_label = (
        "output token limit"
        if normalized_limit_kind == "output"
        else "context limit"
    )

    return (
        "<CONTEXT_LIMIT_RECOVERY>\n"
        + CONTEXT_LIMIT_RECOVERY_MESSAGE.format(
            stage=normalized_stage,
            limit_label=limit_label,
        )
        + ".\n"
        "</CONTEXT_LIMIT_RECOVERY>"
    )


def _normalize_previous_reasoning_content(
        reasoning,
) -> str:

    return str(
        reasoning
        or ""
    ).strip()


def _recovery_reasoning_pending(
        context,
) -> bool:

    if context is None:
        return False

    if getattr(
        context,
        "runtime_reasoning_recovery_pending",
        False,
    ):
        return True

    if not getattr(
        context,
        "runtime_context_limit_recovery_pending",
        False,
    ):
        return False

    return (
        str(
            getattr(
                context,
                "runtime_context_limit_stage",
                "",
            )
            or ""
        ).strip().casefold()
        == "reasoning"
    )


def remember_recovery_reasoning_for_followup(
        context,
        reasoning,
) -> None:

    if not _recovery_reasoning_pending(
        context
    ):
        return

    normalized_reasoning = _normalize_previous_reasoning_content(
        reasoning
    )

    if not normalized_reasoning:
        return

    # Recovery follow-ups only need the immediately preceding failed
    # reasoning. Replacing the slot prevents repeated loop retries from
    # accumulating older reasoning blocks in the next prompt.
    context.runtime_previous_reasoning_loop_contents = [
        normalized_reasoning
    ]


def remember_successful_previous_reasoning(
        context,
        reasoning,
) -> None:

    if context is None:
        return

    if (
        getattr(
            context,
            "runtime_turn_interrupted",
            False,
        )
        or getattr(
            context,
            "runtime_reasoning_recovery_pending",
            False,
        )
        or getattr(
            context,
            "runtime_context_limit_recovery_pending",
            False,
        )
    ):
        return

    context.runtime_previous_reasoning_content = (
        _normalize_previous_reasoning_content(
            reasoning
        )
    )
    context.runtime_previous_reasoning_loop_contents = []


POTENTIAL_LOOP_FOLLOWUP_MESSAGE = (
    "!!!POTENTIAL LOOP DETECTED - STOP EXECUTING AND ANALYZE!!!"
)


def _compact_followup_value(
        value,
) -> str:

    return " ".join(
        str(
            value
            or ""
        ).split()
    ).strip()


def sanitize_sequence_user_request(
        value,
) -> str:

    # Attachment payload transport hints are useful to the runtime, but they
    # are not part of the user's request and must not leak into the visible
    # CURRENT_REQUEST_FLOW block on follow-up ticks.
    lines = []

    for line in str(value or "").splitlines():
        if line.strip().casefold().startswith(
            "runtime_attachment:"
        ):
            continue

        lines.append(line)

    return "\n".join(lines).strip()


def format_followup_action_from_event(
        event: dict,
) -> str:

    if not isinstance(
        event,
        dict,
    ):
        return ""

    runtime_action = str(
        event.get(
            "name",
            "",
        )
        or ""
    ).strip()
    normalized_runtime_action = runtime_action.upper()
    contract_name = get_action_contract_name_for_runtime_action(
        runtime_action
    ) or get_action_contract_name_for_runtime_action(
        normalized_runtime_action
    )
    display_name = get_runtime_action_display_name(
        contract_name
        or normalized_runtime_action
        or runtime_action
    )
    action_name = _compact_followup_value(
        normalized_runtime_action
        or contract_name
        or display_name
        or runtime_action
    )

    if action_name.upper() == "ASSET_ACTION":
        from utils.session_actions_history import (
            extract_asset_action_marker_name,
        )

        asset_action_name = extract_asset_action_marker_name(
            event.get("payload")
            or event.get("asset_result")
            or event.get("detail")
            or ""
        )

        if asset_action_name:
            return f"{action_name}: {asset_action_name}"

    return action_name


def format_followup_action_from_asset_result(
        result: dict,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return ""

    action = _compact_followup_value(
        result.get(
            "action",
            "",
        )
    )
    if not action:
        return ""

    return action


def format_followup_actions_from_events(
        events,
) -> str:

    action_counts = {}

    for event in events or []:
        action_name = format_followup_action_from_event(
            event
        )
        if not action_name:
            continue

        action_counts[action_name] = (
            action_counts.get(
                action_name,
                0,
            )
            + 1
        )

    formatted_actions = []

    for action_name, count in action_counts.items():
        formatted_actions.append(
            format_runtime_action_count(
                action_name,
                count,
            )
        )

    return ", ".join(
        formatted_actions
    )


def format_previous_runtime_memory_tag(
        *,
        sequence_started_at=None,
        now: float | None = None,
) -> str:

    if not isinstance(
        sequence_started_at,
        (int, float),
    ) or sequence_started_at <= 0:
        return "<PREVIOUS_RUNTIME_STATE>"

    if now is None:
        now = time.time()

    try:
        elapsed_seconds = max(
            0,
            float(now) - float(sequence_started_at),
        )
    except (
        TypeError,
        ValueError,
    ):
        return "<PREVIOUS_RUNTIME_STATE>"

    from runtime.L1_memory_utils import (
        format_user_idle_seconds,
    )

    elapsed_text = format_user_idle_seconds(
        elapsed_seconds
    )

    if not elapsed_text:
        return "<PREVIOUS_RUNTIME_STATE>"

    return (
        "<PREVIOUS_RUNTIME_STATE "
        f"( {elapsed_text} ago ) >"
    )


def strip_loaded_delayed_memory_context(
        system_prompt: str,
) -> str:

    lines = str(
        system_prompt
        or ""
    ).splitlines()
    opening_tag = "<LOADED_DELAYED_MEMORY>"
    closing_tag = "</LOADED_DELAYED_MEMORY>"
    kept_lines = []
    index = 0

    while index < len(lines):
        if lines[index].strip() != opening_tag:
            kept_lines.append(
                lines[index]
            )
            index += 1
            continue

        closing_index = index + 1
        while (
            closing_index < len(lines)
            and lines[closing_index].strip() != closing_tag
        ):
            closing_index += 1

        if closing_index >= len(lines):
            kept_lines.extend(
                lines[index:]
            )
            break

        index = closing_index + 1

    return "\n".join(kept_lines).strip()


def rename_runtime_memory_for_followup(
        system_prompt: str,
        *,
        sequence_started_at=None,
        now: float | None = None,
) -> str:

    prompt = str(
        system_prompt
        or ""
    )
    opening_tag_prefix = "<FRAME_MEMORY_"
    opening_index = prompt.find(
        opening_tag_prefix
    )

    # Keep old saved/follow-up contexts readable while current prompts use
    # the numbered FRAME_MEMORY_N contract.
    if opening_index < 0:
        opening_tag_prefix = "<RUNTIME_MEMORY"
        opening_index = prompt.find(
            opening_tag_prefix
        )

    if opening_index < 0:
        return prompt

    opening_end_index = prompt.find(
        ">",
        opening_index + len(opening_tag_prefix),
    )

    if opening_end_index < 0:
        return prompt

    opening_tag_name = (
        prompt[opening_index + 1:opening_end_index]
        .split(None, 1)[0]
        .strip()
    )
    if not opening_tag_name:
        return prompt

    closing_tag = f"</{opening_tag_name}>"
    closing_index = prompt.find(
        closing_tag,
        opening_end_index + 1,
    )

    if closing_index < 0:
        return prompt

    previous_opening_tag = format_previous_runtime_memory_tag(
        sequence_started_at=sequence_started_at,
        now=now,
    )

    return (
        prompt[:opening_index]
        + previous_opening_tag
        + prompt[opening_end_index + 1:closing_index]
        + "</PREVIOUS_RUNTIME_STATE>"
        + prompt[closing_index + len(closing_tag):]
    )


def restore_sequence_attachments_for_followup(
        context,
) -> None:

    current_attachments = getattr(
        context,
        "runtime_turn_attachments",
        [],
    )
    if current_attachments:
        return

    current_sequence_turn_id = str(
        getattr(
            context,
            "runtime_current_sequence_turn_id",
            "",
        )
        or ""
    ).strip()
    sequence_attachment_turn_id = str(
        getattr(
            context,
            "runtime_current_sequence_attachments_turn_id",
            "",
        )
        or ""
    ).strip()

    if (
        current_sequence_turn_id
        and current_sequence_turn_id == sequence_attachment_turn_id
    ):
        context.runtime_turn_attachments = deepcopy(
            getattr(
                context,
                "runtime_current_sequence_attachments",
                [],
            )
            or []
        )


def build_followup_attachment_payload(
        context,
) -> str:

    from websocket.attachments import (
        format_attachment_context,
    )

    attachments = getattr(
        context,
        "runtime_turn_attachments",
        [],
    )

    if not attachments:
        return ""

    return format_attachment_context({
        "attachments": attachments,
    })


class BrainNode(BaseNode):

    @staticmethod
    def build_followup_system_prompt(
            system_prompt: str,
            initial_user_request: str,
            *,
            context=None,
            instruction: str = "",
            latest_action: str = "",
    ) -> str:

        from utils.context.context_exports import (
            build_session_actions_history_context,
            strip_actions_history_context,
        )
        from utils.context.current_concerns import (
            build_current_concerns_context,
        )
        from utils.session_actions_history import (
            get_current_action_sequence_started_at,
            mark_current_action_sequence,
        )

        sequence_started_at = (
            get_current_action_sequence_started_at(
                context
            )
            if context is not None
            else None
        )

        tool_result_blocks, system_prompt = (
            split_tools_results_context(
                system_prompt
            )
        )

        confirm_result_context = (
            consume_confirm_result_context(
                context
            )
            if context is not None
            else ""
        )

        if confirm_result_context:
            tool_result_blocks.append(
                confirm_result_context
            )

        reasoning_recovery_pending = (
            context is not None
            and getattr(
                context,
                "runtime_reasoning_recovery_pending",
                False,
            )
        )
        context_limit_recovery_pending = (
            context is not None
            and getattr(
                context,
                "runtime_context_limit_recovery_pending",
                False,
            )
        )

        session_actions_history_context = ""
        current_request_flow_context = ""

        if context is not None:
            mark_current_action_sequence(
                context
            )

        session_actions_history_context = (
            build_session_actions_history_context(
                context,
                current_sequence=False,
            )
        )
        current_request_flow_context = (
            build_session_actions_history_context(
                context,
                current_sequence=True,
                sequence_user_message=initial_user_request,
                sequence_user_created_at=sequence_started_at,
                latest_action=latest_action,
            )
        )

        potential_loop_detected = bool(
            context is not None
            and getattr(
                context,
                "runtime_potential_loop_detected_pending",
                False,
            )
        )

        sections = []

        if potential_loop_detected:
            sections.append(
                POTENTIAL_LOOP_FOLLOWUP_MESSAGE
            )
            context.runtime_potential_loop_detected_pending = False

        action_failure_followup_context = (
            consume_action_failure_followup_context(
                context
            )
            if context is not None
            else ""
        )
        if action_failure_followup_context:
            sections.append(
                action_failure_followup_context
            )

        failed_action_context = (
            build_failed_runtime_action_followup_contexts(
                context
            )
            if context is not None
            else ""
        )
        if failed_action_context:
            sections.append(
                failed_action_context
            )

        if instruction.strip():
            sections.append(
                instruction.strip()
            )

        if (
            context is not None
            and reasoning_recovery_pending
        ):
            interruption_reason = str(
                getattr(
                    context,
                    "runtime_turn_interruption_reason",
                    "",
                )
                or ""
            ).strip()

            sections.append(
                build_reasoning_recovery_context(
                    interruption_reason
                )
            )

            if interruption_reason:
                recovery_reason_tag = (
                    "ANSWERING_RECOVERY_REASON"
                    if interruption_reason == "same answer output"
                    else "REASONING_RECOVERY_REASON"
                )
                sections.append(
                    f"<{recovery_reason_tag}>\n"
                    f'{interruption_reason}\n'
                    f"</{recovery_reason_tag}>"
                )

            context.runtime_reasoning_recovery_pending = False
            context.runtime_turn_interrupted = False
            context.runtime_turn_interruption_reason = ""
            context.runtime_turn_interruption_quote = ""

        if (
            context is not None
            and context_limit_recovery_pending
        ):
            sections.append(
                build_context_limit_recovery_context(
                    getattr(
                        context,
                        "runtime_context_limit_stage",
                        "generation",
                    ),
                    getattr(
                        context,
                        "runtime_context_limit_kind",
                        "context",
                    ),
                )
            )
            context.runtime_context_limit_recovery_pending = False
            context.runtime_context_limit_stage = ""
            context.runtime_context_limit_kind = ""
            context.runtime_context_limit_finish_reason = ""
            context.runtime_turn_interrupted = False
            context.runtime_turn_interruption_reason = ""
            context.runtime_turn_interruption_quote = ""

        if session_actions_history_context:
            sections.append(
                session_actions_history_context
            )

        if current_request_flow_context:
            sections.append(
                current_request_flow_context
            )

        # Rebuild this live block on every internal follow-up instead of
        # inheriting the stale snapshot from the initial prompt.
        sections.append(
            build_current_concerns_context(
                context
            )
        )

        sections.append(
            build_tools_results_context(
                tool_result_blocks
            )
        )

        if (
            context is not None
            and getattr(
                context,
                "runtime_delayed_memory_save_rejected_pending",
                False,
            )
        ):
            context.runtime_delayed_memory_save_rejected_pending = False
            context.runtime_delayed_memory_save_rejected_title = ""

        if context is not None:
            from rules.brain_context_builder import (
                build_loaded_delayed_memory_context,
            )

            loaded_delayed_memory_context = (
                build_loaded_delayed_memory_context(
                    context
                )
            )

            if loaded_delayed_memory_context:
                sections.append(
                    loaded_delayed_memory_context
                )

        sections.append(
            rename_runtime_memory_for_followup(
                strip_loaded_delayed_memory_context(
                    strip_actions_history_context(
                        system_prompt
                    )
                ),
                sequence_started_at=sequence_started_at,
            )
        )

        return "\n\n".join(
            sections
        )

    @staticmethod
    async def run_search_action(
            *,
            context,
            query: str,
    ) -> str:

        result = await run_search_service(
            context=context,
            query=query,
        )

        return result.strip()

    @staticmethod
    def build_asset_result_report(
            result: dict,
            *,
            user_text: str = "",
    ) -> str:

        if not isinstance(
            result,
            dict,
        ):
            return "Asset operation completed."

        use_russian = contains_cyrillic(
            user_text
        )

        action = str(
            result.get(
                "action",
                "asset_action",
            )
            or "asset_action"
        )
        ok = bool(
            result.get(
                "ok",
                False,
            )
        )
        path = str(
            result.get(
                "path",
                "",
            )
            or ""
        )
        error = str(
            result.get(
                "error",
                "",
            )
            or ""
        )
        detail = str(
            result.get(
                "detail",
                "",
            )
            or ""
        )

        if not ok:
            reason = " — ".join(
                part
                for part in (
                    error,
                    detail,
                )
                if part
            )
            if use_russian:
                return (
                    f"Не удалось выполнить asset-операцию `{action}`"
                    f" для `{path}`: {reason or 'unknown error'}."
                )
            return (
                f"Could not complete asset operation `{action}`"
                f" for `{path}`: {reason or 'unknown error'}."
            )

        line_count = result.get(
            "line_count",
            None,
        )
        appended_count = result.get(
            "appended_count",
            None,
        )
        examples = (
            result.get("examples")
            or result.get("items")
            or []
        )

        if not isinstance(
            examples,
            list,
        ):
            examples = []

        def format_ru_line_count(value) -> str:
            try:
                count = int(value)
            except (TypeError, ValueError):
                return str(value)

            last_two = count % 100
            last = count % 10

            if 11 <= last_two <= 14:
                word = "строк"
            elif last == 1:
                word = "строку"
            elif 2 <= last <= 4:
                word = "строки"
            else:
                word = "строк"

            return f"{count} {word}"

        if use_russian:
            if action == "create_wildcard_file":
                lines = [
                    (
                        f"Создал файл `{path}`"
                        + (
                            f" на {format_ru_line_count(line_count)}."
                            if line_count is not None
                            else "."
                        )
                    )
                ]
            elif action == "append_wildcard_file":
                lines = [
                    (
                        f"Обновил файл `{path}`"
                        + (
                            f": добавлено {format_ru_line_count(appended_count)}, всего {format_ru_line_count(line_count)}."
                            if appended_count is not None and line_count is not None
                            else "."
                        )
                    )
                ]
            elif action == "generate_prompt_batch":
                lines = [
                    (
                        f"Создал prompt batch `{path}`"
                        + (
                            f" на {format_ru_line_count(line_count)}."
                            if line_count is not None
                            else "."
                        )
                    )
                ]
            elif action in {"sample_wildcard", "preview_file", "expand_template"}:
                lines = [
                    (
                        f"Готово: `{action}`"
                        + (f" для `{path}`." if path else ".")
                    )
                ]
            else:
                lines = [
                    (
                        f"Готово: `{action}`"
                        + (f" для `{path}`." if path else ".")
                    )
                ]

            if examples:
                lines.append("")
                lines.append("Примеры:")
                lines.extend(
                    f"- {item}"
                    for item in examples[:5]
                )

            return "\n".join(lines).strip()

        if action == "create_wildcard_file":
            lines = [
                (
                    f"Created `{path}`"
                    + (
                        f" with {line_count} lines."
                        if line_count is not None
                        else "."
                    )
                )
            ]
        elif action == "append_wildcard_file":
            lines = [
                (
                    f"Updated `{path}`"
                    + (
                        f": appended {appended_count} lines, {line_count} total."
                        if appended_count is not None and line_count is not None
                        else "."
                    )
                )
            ]
        elif action == "generate_prompt_batch":
            lines = [
                (
                    f"Created prompt batch `{path}`"
                    + (
                        f" with {line_count} lines."
                        if line_count is not None
                        else "."
                    )
                )
            ]
        else:
            lines = [
                (
                    f"Completed `{action}`"
                    + (f" for `{path}`." if path else ".")
                )
            ]

        if examples:
            lines.append("")
            lines.append("Examples:")
            lines.extend(
                f"- {item}"
                for item in examples[:5]
            )

        return "\n".join(lines).strip()

    @staticmethod
    async def emit_brain_text(
            *,
            state,
            context,
            brain_runtime,
            text: str,
            emit_content_to_chat: bool = True,
            context_snapshot: dict | None = None,
    ) -> tuple[str, str]:

        async def generator():
            yield {
                "type": "content",
                "content": text,
            }

        runtime = RuntimeStream(
            context=context,
            runtime_id=(
                brain_runtime[
                    "runtime_id"
                ]
            ),
            role=(
                brain_runtime["label"]
            ),
            context_window=(
                brain_runtime[
                    "context_window"
                ]
            ),
            log_method=getattr(
                context.logger,
                brain_runtime[
                    "log_method"
                ],
            ),
            model_output_log_method=getattr(
                context.logger,
                brain_runtime.get(
                    "model_output_log_method",
                    "",
                ),
                None,
            ),
            enable_validator=True,
            emit_to_chat=True,
            emit_content_to_chat=emit_content_to_chat,
            context_snapshot=(
                context_snapshot
                or getattr(
                    state,
                    "visible_response_context",
                    None,
                )
            ),
            runtime_actions={},
        )

        response = await runtime.run(
            generator()
        )

        return (
            response or text,
            runtime.stream.reasoning,
        )

    @staticmethod
    async def run_brain_stream(
            *,
            state,
            context,
            brain_runtime,
            brain_client,
            system_prompt: str,
            brain_payload: str,
            runtime_actions: dict,
            emit_content_to_chat: bool = True,
            filter_runtime_actions: bool = True,
            preserve_runtime_action_markers: bool = False,
            followup_tick: bool = False,
    ) -> tuple[str, str]:

        logger = context.logger

        is_followup_tick = bool(
            followup_tick
        )
        previous_followup_tick = getattr(
            context,
            "runtime_followup_tick_active",
            False,
        )

        effective_brain_payload = brain_payload

        if is_followup_tick:
            restore_sequence_attachments_for_followup(
                context
            )
            effective_brain_payload = (
                build_followup_attachment_payload(
                    context
                )
                or brain_payload
            )
            context.runtime_followup_tick_active = True

        prepared_context_window = await prepare_current_context_window_prompt(
            client=brain_client,
            context=context,
            runtime_id=brain_runtime["runtime_id"],
            system_prompt=system_prompt,
            user_prompt=effective_brain_payload,
            fallback_context_window=brain_runtime["context_window"],
            force_refresh=True,
        )
        system_prompt = prepared_context_window.system_prompt
        brain_runtime["context_window"] = (
            prepared_context_window.context_window
        )

        context_snapshot = build_brain_context_snapshot(
            system_prompt=system_prompt,
            user_prompt=effective_brain_payload,
        )

        if preserve_runtime_action_markers:
            context_snapshot = {
                **context_snapshot,
                "preserve_runtime_action_markers": True,
            }

        try:
            context_snapshot_saver = (
                save_chat_bootstrap_context_snapshot
                if bool(
                    getattr(
                        context,
                        "runtime_session_restore_priming",
                        False,
                    )
                )
                else save_chat_context_snapshot
            )
            context_snapshot_saver(
                context,
                context_snapshot=context_snapshot,
            )
        except Exception as error:
            await logger.log_system(
                "[CHAT_LOG] context snapshot save failed: "
                + str(error)
            )

        state.visible_response_context = (
            context_snapshot
        )

        runtime = RuntimeStream(
            context=context,
            runtime_id=(
                brain_runtime[
                    "runtime_id"
                ]
            ),
            role=(
                brain_runtime["label"]
            ),
            context_window=(
                brain_runtime[
                    "context_window"
                ]
            ),
            log_method=getattr(
                logger,
                brain_runtime[
                    "log_method"
                ],
            ),
            model_output_log_method=getattr(
                logger,
                brain_runtime.get(
                    "model_output_log_method",
                    "",
                ),
                None,
            ),
            enable_validator=True,
            emit_to_chat=True,
            emit_content_to_chat=emit_content_to_chat,
            context_snapshot=context_snapshot,
            runtime_actions=runtime_actions,
            filter_runtime_actions=filter_runtime_actions,
        )

        try:
            generator = ask_brain_stream(
                client=brain_client,
                text=state.user_input,
                context=context,
                system_prompt=system_prompt,
                brain_payload=effective_brain_payload,
                runtime_actions=runtime_actions,
                filter_runtime_actions=filter_runtime_actions,
            )

            text = await runtime.run(
                generator
            )
        finally:
            if is_followup_tick:
                context.runtime_followup_tick_active = (
                    previous_followup_tick
                )

        if runtime.stream.reasoning:
            context.runtime_turn_reasoning_content = "\n".join(
                part
                for part in (
                    getattr(
                        context,
                        "runtime_turn_reasoning_content",
                        "",
                    ),
                    runtime.stream.reasoning,
                )
                if str(part or "").strip()
            )

        return (
            text or "",
            runtime.stream.reasoning,
        )

    async def run(
            self,
            state,
            context,
    ):

        logger = context.logger

        brain_runtime = (
            get_brain_runtime_config()
        )

        state.visible_response_role = (
            brain_runtime["label"]
        )

        brain_client = (
            context.clients[
                brain_runtime["label"]
            ]
        )

        runtime_actions = (
            brain_runtime.get(
                "runtime_actions",
                {},
            )
        )

        begin_runtime_tool_results_turn(
            context
        )
        context.runtime_turn_reasoning_content = ""

        def ensure_runtime_list(
                name: str,
        ) -> list:

            value = getattr(
                context,
                name,
                None,
            )

            if not isinstance(
                value,
                list,
            ):
                value = []
                setattr(
                    context,
                    name,
                    value,
                )

            return value

        ensure_runtime_list(
            "runtime_deep_search_calls"
        ).clear()
        context.runtime_deep_search_result = ""
        context.runtime_deep_search_result_id = ""
        ensure_runtime_list(
            "runtime_search_queries"
        ).clear()
        ensure_runtime_list(
            "runtime_search_calls"
        ).clear()
        context.runtime_search_result = ""
        context.runtime_search_result_id = ""
        prepare_asset_results_for_turn(
            context
        )
        if not hasattr(
            context,
            "runtime_delayed_memory_results",
        ):
            context.runtime_delayed_memory_results = []
        else:
            context.runtime_delayed_memory_results.clear()

        # Reset per-turn signal for schedule_runtime_memory_update(): it
        # needs to know whether SAVE_ACTIVE_MEMORY actually wrote a
        # record this turn even when the visible assistant text is empty
        # (e.g. the user explicitly asked JIN to emit only the marker).
        context.runtime_active_memory_saved_this_turn = False
        context.runtime_active_memory_refresh_tick = 0
        action_guard_retry = getattr(
            context,
            "runtime_action_guard_retry",
            {},
        )
        retry_context_snapshot = (
            action_guard_retry.get(
                "context_snapshot",
                {},
            )
            if isinstance(action_guard_retry, dict)
            else {}
        )
        if not isinstance(retry_context_snapshot, dict):
            retry_context_snapshot = {}

        retry_system_prompt = str(
            retry_context_snapshot.get(
                "system_prompt",
                "",
            )
            or ""
        )
        retry_user_prompt = str(
            retry_context_snapshot.get(
                "user_prompt",
                "",
            )
            or ""
        )

        if retry_system_prompt:
            system_prompt = retry_system_prompt
            brain_payload = retry_user_prompt
        else:
            system_prompt = (
                build_brain_context(
                    context,
                    runtime_actions=runtime_actions,
                    user_input=state.user_input,
                    commit_active_memory_refresh=True,
                    # Ordinary user turns must carry the previous completed
                    # reasoning block. Follow-up builders disable it explicitly
                    # where they need the current turn reasoning instead.
                    include_previous_reasoning=True,
                )
            )
            brain_payload = (
                build_brain_payload(
                    state.user_input,
                    context=context,
                )
            )

        sequence_user_request = str(
            getattr(
                context,
                "runtime_turn_user_message",
                "",
            )
            or state.user_input
            or ""
        )
        sequence_user_request = sanitize_sequence_user_request(
            sequence_user_request
        )

        await emit_active_memory_records_update_if_dirty(
            context
        )

        context.runtime_zero_diff_alert = None

        runtime_action_event_offset = len(
            getattr(
                context,
                "runtime_action_events",
                [],
            )
            or []
        )
        runtime_tool_result_followup_offset = len(
            getattr(
                context,
                "runtime_tool_results",
                [],
            )
            or []
        )

        text, reasoning = await self.run_brain_stream(
            state=state,
            context=context,
            brain_runtime=brain_runtime,
            brain_client=brain_client,
            system_prompt=system_prompt,
            brain_payload=brain_payload,
            runtime_actions=runtime_actions,
            emit_content_to_chat=True,
        )

        if getattr(
            context,
            "runtime_turn_abort_requested",
            False,
        ):
            state.brain_response = text or ""
            return

        restore_replay_asset_result_offset = 0
        restore_replay_delayed_memory_result_offset = 0

        if state.metadata.get(
            "session_restore_resume",
            False,
        ):
            replayed_restore_actions = await replay_session_restore_resource_actions(
                context,
                assistant_message=text or "",
                context_snapshot=getattr(
                    state,
                    "visible_response_context",
                    None,
                ),
            )

            if replayed_restore_actions:
                # ATTACH_FILE / LOAD_DELAYED_MEMORY replay after the very first
                # restored JIN message is state reconstruction, not a new model
                # decision. Run the real action dispatcher (bubbles,
                # tool results, pinning, etc.) but consume its action/results as
                # already handled so the follow-up scheduler cannot fire even
                # when the normal runtime contract says emit_followup=true.
                # The next user/model turn takes fresh offsets and goes back to
                # ordinary contract-driven behavior automatically.
                runtime_action_event_offset = len(
                    getattr(
                        context,
                        "runtime_action_events",
                        [],
                    )
                    or []
                )
                runtime_tool_result_followup_offset = len(
                    getattr(
                        context,
                        "runtime_tool_results",
                        [],
                    )
                    or []
                )
                restore_replay_asset_result_offset = len(
                    getattr(
                        context,
                        "runtime_asset_results",
                        [],
                    )
                    or []
                )
                restore_replay_delayed_memory_result_offset = len(
                    getattr(
                        context,
                        "runtime_delayed_memory_results",
                        [],
                    )
                    or []
                )

        asset_result_offset = restore_replay_asset_result_offset
        delayed_memory_result_offset = restore_replay_delayed_memory_result_offset
        followup_count = 0
        max_followups = max(
            1,
            int(
                config.BRAIN_MAX_FOLLOWUPS
            ),
        )
        current_turn_id = str(
            getattr(
                context,
                "runtime_current_turn_id",
                "",
            )
            or ""
        ).strip()
        current_sequence_turn_id = str(
            getattr(
                context,
                "runtime_current_sequence_turn_id",
                "",
            )
            or ""
        ).strip()

        def abort_requested():
            return bool(
                getattr(
                    context,
                    "runtime_turn_abort_requested",
                    False,
                )
            )

        if abort_requested():
            state.brain_response = text or ""
            return

        def belongs_to_current_turn(
                item,
        ) -> bool:

            if (
                not current_turn_id
                or not isinstance(
                    item,
                    dict,
                )
            ):
                return True

            item_turn_id = str(
                item.get(
                    "runtime_turn_id",
                    "",
                )
                or ""
            ).strip()

            return (
                not item_turn_id
                or item_turn_id
                in {
                    current_turn_id,
                    current_sequence_turn_id,
                }
            )

        def collect_pending_asset_tool_results():

            tool_results = getattr(
                context,
                "runtime_tool_results",
                [],
            )
            pending_results = []

            for entry in tool_results[
                runtime_tool_result_followup_offset:
            ]:
                if (
                    not isinstance(entry, dict)
                    or entry.get("kind") != TOOL_RESULT_KIND_ASSET
                ):
                    continue

                result = entry.get("result")
                if (
                    not isinstance(result, dict)
                    or not belongs_to_current_turn(result)
                ):
                    continue

                runtime_action = str(
                    result.get("runtime_action_name")
                    or result.get("action")
                    or "asset_action"
                ).strip()

                if not runtime_action_emits_followup(
                    runtime_action
                ):
                    continue

                pending_results.append(result)

            return pending_results

        action_event_followup_offset = (
            runtime_action_event_offset
        )
        skill_state_followup_event_names = {
            "load_skill",
            "unload_skill",
            "load_delayed_memory",
        }

        def collect_pending_action_events():

            runtime_action_events = getattr(
                context,
                "runtime_action_events",
                [],
            )
            pending_action_events = [
                event
                for event in runtime_action_events[
                    action_event_followup_offset:
                ]
                if belongs_to_current_turn(
                    event
                )
            ]

            if not action_batch_requires_follow_up(
                    pending_action_events,
                    text,
            ):
                return []

            return pending_action_events

        def consume_current_action_batch():

            nonlocal action_event_followup_offset
            nonlocal asset_result_offset
            nonlocal delayed_memory_result_offset
            nonlocal runtime_tool_result_followup_offset

            pending_action_events = (
                collect_pending_action_events()
            )
            action_event_followup_offset = len(
                getattr(
                    context,
                    "runtime_action_events",
                    [],
                )
            )

            current_asset_results = [
                result
                for result in getattr(
                    context,
                    "runtime_asset_results",
                    [],
                )
                if belongs_to_current_turn(
                    result
                )
            ]
            asset_result_offset = len(
                current_asset_results
            )

            current_delayed_memory_results = [
                result
                for result in getattr(
                    context,
                    "runtime_delayed_memory_results",
                    [],
                )
                if belongs_to_current_turn(
                    result
                )
            ]
            delayed_memory_result_offset = len(
                current_delayed_memory_results
            )
            runtime_tool_result_followup_offset = len(
                getattr(
                    context,
                    "runtime_tool_results",
                    [],
                )
                or []
            )

            return pending_action_events

        while followup_count < max_followups:

            if abort_requested():
                break

            remember_recovery_reasoning_for_followup(
                context,
                reasoning,
            )

            context.runtime_active_memory_refresh_tick = (
                followup_count + 1
            )

            if getattr(
                context,
                "runtime_context_limit_recovery_pending",
                False,
            ):
                from utils.session_actions_history import (
                    build_context_limit_history_text,
                )

                limit_stage = getattr(
                    context,
                    "runtime_context_limit_stage",
                    "generation",
                )
                limit_kind = getattr(
                    context,
                    "runtime_context_limit_kind",
                    "context",
                )
                followup_action_events = (
                    consume_current_action_batch()
                )
                followup_runtime_actions = {
                    **runtime_actions,
                }
                latest_followup_action = (
                    format_followup_actions_from_events(
                        followup_action_events
                    )
                    or build_context_limit_history_text(
                        limit_stage,
                        limit_kind,
                    )
                )

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_context(
                            context,
                            runtime_actions=followup_runtime_actions,
                            user_input=sequence_user_request,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                            include_previous_reasoning=False,
                        ),
                        sequence_user_request,
                        context=context,
                        latest_action=latest_followup_action,
                    )
                )

                await emit_active_memory_records_update_if_dirty(
                    context
                )

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload="",
                    followup_tick=True,
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=True,
                    filter_runtime_actions=True,
                )

                followup_count += 1
                continue

            if context.runtime_deep_search_calls:

                deep_search_call = context.runtime_deep_search_calls.pop(0)
                objective = str(
                    deep_search_call.get("query")
                    or ""
                ).strip()
                tool_call_id = str(
                    deep_search_call.get("id")
                    or ""
                ).strip()
                context.runtime_deep_search_calls.clear()

                # DEEP_WEB_SEARCH owns the web-search budget for this sequence.
                # Ignore a stray direct WEB_SEARCH emitted alongside it.
                context.runtime_search_queries.clear()
                context.runtime_search_calls.clear()

                await logger.log_runtime(
                    "[RUNTIME ACTION] executing deep web search "
                    f"id={tool_call_id!r} objective={objective!r}"
                )

                deep_search_result = await run_deep_web_search(
                    context=context,
                    objective=objective,
                    context_snapshot=deep_search_call.get("context"),
                    parent_action_id=tool_call_id,
                )

                deep_search_display_name = (
                    get_runtime_action_display_name(
                        RUNTIME_ACTION_DEEP_WEB_SEARCH
                    )
                )
                await context.websocket.send_json({
                    "type": "runtime_action",
                    "action": RUNTIME_ACTION_DEEP_WEB_SEARCH.lower(),
                    "display_name": deep_search_display_name,
                    "id": tool_call_id,
                    "status": "completed",
                    "text": (
                        f"{deep_search_display_name}: {objective}"
                    ),
                    "query": objective,
                    "scene_effect": "search",
                    "context": deep_search_call.get("context"),
                    "deep_search_parent": True,
                    "deep_search_payload_ready": True,
                })
                mark_runtime_action_completed(
                    context,
                    action=RUNTIME_ACTION_DEEP_WEB_SEARCH,
                    action_id=tool_call_id,
                )
                context.runtime_deep_search_result = deep_search_result
                context.runtime_deep_search_result_id = tool_call_id
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_DEEP_SEARCH,
                    deep_search_result,
                    result_id=tool_call_id,
                )

                followup_action_events = consume_current_action_batch()
                followup_runtime_actions = {
                    **runtime_actions,
                }
                latest_followup_action = (
                    format_followup_actions_from_events(
                        followup_action_events
                    )
                    or format_followup_action_from_event({
                        "name": RUNTIME_ACTION_DEEP_WEB_SEARCH.lower(),
                        "id": tool_call_id,
                    })
                )

                followup_system_prompt = self.build_followup_system_prompt(
                    build_brain_context(
                        context,
                        runtime_actions=followup_runtime_actions,
                        user_input=sequence_user_request,
                        commit_active_memory_refresh=True,
                        include_previous_chat_messages=False,
                        include_previous_reasoning=False,
                        include_turn_reasoning=True,
                        crop_previous_reasoning=False,
                    ),
                    sequence_user_request,
                    context=context,
                    latest_action=latest_followup_action,
                )

                await emit_active_memory_records_update_if_dirty(context)

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload="",
                    followup_tick=True,
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=True,
                    filter_runtime_actions=True,
                )

                followup_count += 1
                continue

            if context.runtime_search_queries:

                search_call = (
                    context.runtime_search_calls.pop(0)
                    if context.runtime_search_calls
                    else {}
                )
                query = (
                    search_call.get("query")
                    or context.runtime_search_queries.pop(0)
                )
                tool_call_id = search_call.get(
                    "id",
                    "",
                )
                context.runtime_search_queries.clear()
                context.runtime_search_calls.clear()

                await logger.log_runtime(
                    "[RUNTIME ACTION] "
                    f"executing search id={tool_call_id!r} "
                    f"query={query!r}"
                )
                search_display_name = (
                    get_runtime_action_display_name(
                        RUNTIME_ACTION_WEB_SEARCH
                    )
                )

                await context.websocket.send_json({
                    "type": "runtime_action",
                    "action": RUNTIME_ACTION_WEB_SEARCH.lower(),
                    "display_name": search_display_name,
                    "id": tool_call_id,
                    "text": (
                        f"{search_display_name}: {query}"
                    ),
                    "query": query,
                    "scene_effect": "search",
                    "context": search_call.get(
                        "context",
                    ),
                })

                search_result = await self.run_search_action(
                    context=context,
                    query=query,
                )

                await context.websocket.send_json({
                    "type": "runtime_action",
                    "action": RUNTIME_ACTION_WEB_SEARCH.lower(),
                    "display_name": search_display_name,
                    "id": tool_call_id,
                    "status": "completed",
                    "scene_effect": "search",
                })
                mark_runtime_action_completed(
                    context,
                    action=RUNTIME_ACTION_WEB_SEARCH,
                    action_id=tool_call_id,
                )

                context.runtime_search_result = search_result
                context.runtime_search_result_id = tool_call_id
                record_runtime_tool_result(
                    context,
                    TOOL_RESULT_KIND_SEARCH,
                    search_result,
                    result_id=tool_call_id,
                )

                followup_action_events = (
                    consume_current_action_batch()
                )
                followup_runtime_actions = {
                    **runtime_actions,
                }

                latest_followup_action = (
                    format_followup_actions_from_events(
                        followup_action_events
                    )
                    or format_followup_action_from_event({
                        "name": RUNTIME_ACTION_WEB_SEARCH.lower(),
                        "query": query,
                        "id": tool_call_id,
                    })
                )

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_context(
                            context,
                            runtime_actions=followup_runtime_actions,
                            user_input=sequence_user_request,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                            include_previous_reasoning=False,
                            include_turn_reasoning=True,
                            crop_previous_reasoning=False,
                        ),
                        sequence_user_request,
                        context=context,
                        latest_action=latest_followup_action,
                    )
                )

                await emit_active_memory_records_update_if_dirty(
                    context
                )

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload="",
                    followup_tick=True,
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=True,
                )

                if not text.strip():
                    text = build_search_result_fallback_answer(
                        search_result
                    )

                followup_count += 1
                continue

            pending_action_events = (
                collect_pending_action_events()
            )
            new_skill_state_events = [
                event
                for event in pending_action_events
                if event.get("name")
                in skill_state_followup_event_names
            ]

            if new_skill_state_events:
                followup_action_events = (
                    consume_current_action_batch()
                )
                followup_runtime_actions = {
                    **runtime_actions,
                }

                latest_followup_action = (
                    format_followup_actions_from_events(
                        followup_action_events
                    )
                )

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_context(
                            context,
                            runtime_actions=followup_runtime_actions,
                            user_input=sequence_user_request,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                            include_previous_reasoning=False,
                            include_turn_reasoning=True,
                            crop_previous_reasoning=False,
                        ),
                        sequence_user_request,
                        context=context,
                        latest_action=latest_followup_action,
                    )
                )

                await emit_active_memory_records_update_if_dirty(
                    context
                )

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload="",
                    followup_tick=True,
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=True,
                    filter_runtime_actions=True,
                )

                followup_count += 1
                continue

            delayed_memory_results = getattr(
                context,
                "runtime_delayed_memory_results",
                [],
            )
            current_delayed_memory_results = [
                result
                for result in delayed_memory_results
                if belongs_to_current_turn(
                    result
                )
            ]

            if (
                    len(current_delayed_memory_results)
                    > delayed_memory_result_offset
            ):
                followup_action_events = (
                    consume_current_action_batch()
                )
                followup_runtime_actions = {
                    **runtime_actions,
                }

                latest_followup_action = (
                    format_followup_actions_from_events(
                        followup_action_events
                    )
                    or format_followup_action_from_asset_result(
                        current_delayed_memory_results[-1]
                    )
                )

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_context(
                            context,
                            runtime_actions=followup_runtime_actions,
                            user_input=sequence_user_request,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                            include_previous_reasoning=False,
                            include_turn_reasoning=True,
                            crop_previous_reasoning=False,
                        ),
                        sequence_user_request,
                        context=context,
                        latest_action=latest_followup_action,
                    )
                )

                await emit_active_memory_records_update_if_dirty(
                    context
                )

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload="",
                    followup_tick=True,
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=True,
                    filter_runtime_actions=True,
                )

                followup_count += 1
                continue

            asset_results = getattr(
                context,
                "runtime_asset_results",
                [],
            )
            current_asset_results = [
                result
                for result in asset_results
                if belongs_to_current_turn(
                    result
                )
            ]

            if len(current_asset_results) <= asset_result_offset:
                pending_action_events = (
                    collect_pending_action_events()
                )
                pending_asset_tool_results = (
                    collect_pending_asset_tool_results()
                )

                if (
                    not pending_action_events
                    and not pending_asset_tool_results
                    and not getattr(
                        context,
                        "runtime_reasoning_recovery_pending",
                        False,
                    )
                    and not getattr(
                        context,
                        "runtime_context_limit_recovery_pending",
                        False,
                    )
                ):
                    break

                followup_action_events = (
                    consume_current_action_batch()
                )
                followup_runtime_actions = {
                    **runtime_actions,
                }

                latest_followup_action = (
                    format_followup_actions_from_events(
                        followup_action_events
                    )
                    or format_followup_action_from_asset_result(
                        pending_asset_tool_results[-1]
                        if pending_asset_tool_results
                        else {}
                    )
                )

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_context(
                            context,
                            runtime_actions=followup_runtime_actions,
                            user_input=sequence_user_request,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                            include_previous_reasoning=False,
                            include_turn_reasoning=True,
                            crop_previous_reasoning=False,
                        ),
                        sequence_user_request,
                        context=context,
                        latest_action=latest_followup_action,
                    )
                )

                await emit_active_memory_records_update_if_dirty(
                    context
                )

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload="",
                    followup_tick=True,
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=True,
                    filter_runtime_actions=True,
                )

                followup_count += 1
                continue

            followup_action_events = (
                consume_current_action_batch()
            )
            followup_runtime_actions = {
                **runtime_actions,
            }

            latest_followup_action = (
                format_followup_actions_from_events(
                    followup_action_events
                )
                or format_followup_action_from_asset_result(
                    current_asset_results[-1]
                )
            )

            followup_system_prompt = (
                self.build_followup_system_prompt(
                    build_brain_context(
                        context,
                        runtime_actions=followup_runtime_actions,
                        user_input=sequence_user_request,
                        commit_active_memory_refresh=True,
                        include_previous_chat_messages=False,
                        include_previous_reasoning=False,
                        include_turn_reasoning=True,
                        crop_previous_reasoning=False,
                    ),
                    sequence_user_request,
                    context=context,
                    latest_action=latest_followup_action,
                )
            )

            await emit_active_memory_records_update_if_dirty(
                context
            )

            text, reasoning = await self.run_brain_stream(
                state=state,
                context=context,
                brain_runtime=brain_runtime,
                brain_client=brain_client,
                system_prompt=followup_system_prompt,
                brain_payload="",
                followup_tick=True,
                runtime_actions=followup_runtime_actions,
                emit_content_to_chat=True,
                filter_runtime_actions=True,
            )

            followup_count += 1
            continue

        remember_recovery_reasoning_for_followup(
            context,
            reasoning,
        )

        if followup_count >= max_followups:
            context.runtime_active_memory_refresh_tick = (
                followup_count + 1
            )
            stop_reason = (
                "Brain workflow stopped after reaching the configured "
                f"follow-up limit ({max_followups}). "
                "One final non-executable response tick will run."
            )

            await logger.log_runtime(
                "[BRAIN FOLLOW-UP LIMIT] "
                + stop_reason
            )

            await context.websocket.send_json({
                "type": "runtime_action",
                "action": "followup_limit_reached",
                "id": (
                    current_turn_id
                    or "current_turn"
                ),
                "status": "stopped",
                "text": (
                    f"Follow-up limit reached ({max_followups}). "
                    "Running one final response tick with runtime "
                    "actions disabled."
                ),
            })

            final_runtime_actions = {
                key: False
                for key in runtime_actions
            }

            followup_limit_instruction = (
                "<FOLLOWUP_LIMIT_REACHED>\n"
                f"The runtime stopped this workflow after {max_followups} "
                "internal follow-up ticks. This is the final response "
                "tick. No runtime action emitted in this response will "
                "execute, and no further follow-up tick will run. Any "
                "runtime action marker you output will be shown to the "
                "user as plain model text. If work remains and your next "
                "step would normally be a runtime action, output that exact "
                "marker so the user can see where execution stopped. State "
                "clearly that the workflow stopped because the follow-up "
                "limit was reached. Briefly "
                "summarize what was completed and what remains. Do not "
                "claim unfinished work is complete.\n"
                "</FOLLOWUP_LIMIT_REACHED>"
            )

            final_system_prompt = (
                self.build_followup_system_prompt(
                    build_brain_context(
                        context,
                        runtime_actions=final_runtime_actions,
                        user_input=sequence_user_request,
                        commit_active_memory_refresh=True,
                        include_previous_chat_messages=False,
                        include_previous_reasoning=False,
                        include_turn_reasoning=True,
                        crop_previous_reasoning=False,
                    ),
                    sequence_user_request,
                    context=context,
                    instruction=followup_limit_instruction,
                    latest_action="followup_limit_reached",
                )
            )

            await emit_active_memory_records_update_if_dirty(
                context
            )

            text, reasoning = await self.run_brain_stream(
                state=state,
                context=context,
                brain_runtime=brain_runtime,
                brain_client=brain_client,
                system_prompt=final_system_prompt,
                brain_payload="",
                followup_tick=True,
                runtime_actions=final_runtime_actions,
                emit_content_to_chat=True,
                filter_runtime_actions=False,
                preserve_runtime_action_markers=True,
            )

        state.brain_response = text or ""
        if context is not None:
            remember_successful_previous_reasoning(
                context,
                reasoning,
            )



