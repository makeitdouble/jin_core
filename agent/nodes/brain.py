from copy import deepcopy

from agent.nodes.base import BaseNode

from runtime.stream import (
    RuntimeStream,
)

from clients.brain_client import (
    ask_brain_stream,
    build_brain_context_snapshot,
    build_brain_payload,
    emit_active_memory_records_update_if_dirty,
)
from rules.assembler import (
    build_brain_system_prompt,
)

from clients.search_client import (
    build_search_result_fallback_answer,
    run_search_service,
)

from clients.brain_client_utils import (
    get_brain_runtime_config,
)

from utils.language import (
    contains_cyrillic,
)

from config_loader import (
    config,
)


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


FOLLOWUP_SYSTEM_MESSAGE = (
    "This is runtime system message!\n"
    "Multi-step task in progress!\n"
    "This is not a start of a task sequence!\n"
    "This is not a new request!\n"
    "\n"
    "YOU MUST derive your next action from LATEST_USER_REQUEST and CURRENT_ACTIONS_HISTORY.\n"
    "You need to make all required actions and complete remaining steps!\n"
    "Continue without confirmation!\n"
    "\n"
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


def format_followup_action_from_event(
        event: dict,
) -> str:

    if not isinstance(
        event,
        dict,
    ):
        return ""

    return _compact_followup_value(
        event.get(
            "name",
            "",
        )
    )


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
        if count > 1:
            formatted_actions.append(
                f"{action_name} (repeated_times: {count} )"
            )
            continue

        formatted_actions.append(
            action_name
        )

    return ", ".join(
        formatted_actions
    )


def rename_runtime_memory_for_followup(
        system_prompt: str,
) -> str:

    prompt = str(
        system_prompt
        or ""
    )
    opening_tag = "<RUNTIME_MEMORY>"
    closing_tag = "</RUNTIME_MEMORY>"
    opening_index = prompt.find(
        opening_tag
    )

    if opening_index < 0:
        return prompt

    closing_index = prompt.find(
        closing_tag,
        opening_index + len(opening_tag),
    )

    if closing_index < 0:
        return prompt

    return (
        prompt[:opening_index]
        + "<LATEST_RUNTIME_MEMORY>"
        + prompt[opening_index + len(opening_tag):closing_index]
        + "</LATEST_RUNTIME_MEMORY>"
        + prompt[closing_index + len(closing_tag):]
    )


def build_followup_system_message(
        latest_action: str = "",
) -> str:

    latest_action = _compact_followup_value(
        latest_action
    )
    lines = [
        FOLLOWUP_SYSTEM_MESSAGE,
    ]

    if latest_action:
        lines.append(
            "This is follow-up tick for JIN latest action: "
            f"{latest_action}."
        )

    lines.append(
        "Requested and available information provided in tool results section."
    )

    return "\n".join(
        lines
    ).strip()


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

        from clients.brain_context_builder import (
            build_latest_user_request_context,
            build_session_actions_history_context,
            strip_actions_history_context,
        )
        from utils.session_actions_history import (
            mark_current_action_sequence,
        )

        if context is not None:
            latest_user_request_context = (
                build_latest_user_request_context(
                    initial_user_request,
                    created_at=getattr(
                        context,
                        "runtime_turn_started_at",
                        None,
                    ),
                )
            )
        else:
            latest_user_request_context = (
                build_latest_user_request_context(
                    initial_user_request
                )
            )

        sections = [
            build_followup_system_message(
                latest_action
            ),
            latest_user_request_context
        ]

        if context is not None:
            mark_current_action_sequence(
                context
            )
            current_actions_history_context = (
                build_session_actions_history_context(
                    context,
                    current_sequence=True,
                )
            )

            if current_actions_history_context:
                sections.append(
                    current_actions_history_context
                )

            from clients.brain_context_builder import (
                build_appended_delayed_memory_context,
                build_previous_chat_messages_context,
            )

            appended_delayed_memory_context = (
                build_appended_delayed_memory_context(
                    context
                )
            )

            if appended_delayed_memory_context:
                sections.append(
                    appended_delayed_memory_context
                )

            previous_chat_messages_context = (
                build_previous_chat_messages_context(
                    context,
                    extra_user_message=initial_user_request,
                )
            )

            if previous_chat_messages_context:
                sections.append(
                    previous_chat_messages_context
                )

        if instruction.strip():
            sections.append(
                instruction.strip()
            )

        sections.append(
            rename_runtime_memory_for_followup(
                strip_actions_history_context(
                    system_prompt
                )
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
    ) -> tuple[str, str]:

        logger = context.logger

        context_snapshot = build_brain_context_snapshot(
            context=context,
            system_prompt=system_prompt,
            user_prompt=brain_payload,
            runtime_actions=runtime_actions,
        )

        if preserve_runtime_action_markers:
            context_snapshot = {
                **context_snapshot,
                "preserve_runtime_action_markers": True,
            }

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
            enable_validator=True,
            emit_to_chat=True,
            emit_content_to_chat=emit_content_to_chat,
            context_snapshot=context_snapshot,
            runtime_actions=runtime_actions,
            filter_runtime_actions=filter_runtime_actions,
        )

        generator = ask_brain_stream(
            client=brain_client,
            text=state.translated_input,
            context=context,
            system_prompt=system_prompt,
            brain_payload=brain_payload,
            runtime_actions=runtime_actions,
            filter_runtime_actions=filter_runtime_actions,
        )

        text = await runtime.run(
            generator
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

        context.runtime_search_queries.clear()
        context.runtime_search_calls.clear()
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
        # needs to know whether CREATE_ACTIVE_MEMORY actually wrote a
        # record this turn even when the visible assistant text is empty
        # (e.g. the user explicitly asked JIN to emit only the marker).
        context.runtime_active_memory_created_this_turn = False

        system_prompt = (
            build_brain_system_prompt(
                context,
                runtime_actions=runtime_actions,
                commit_active_memory_refresh=True,
            )
        )

        await emit_active_memory_records_update_if_dirty(
            context
        )

        context.runtime_zero_diff_alert = None

        brain_payload = (
            build_brain_payload(
                state.translated_input,
                context=context,
            )
        )

        runtime_action_event_offset = len(
            getattr(
                context,
                "runtime_action_events",
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
            emit_content_to_chat=(
                not state.translate_response
            ),
        )

        asset_result_offset = 0
        delayed_memory_result_offset = 0
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
                or item_turn_id == current_turn_id
            )

        action_event_followup_offset = (
            runtime_action_event_offset
        )
        skill_state_followup_event_names = {
            "append_skill",
            "remove_skill",
            "append_delayed_memory",
        }

        def collect_pending_action_events():

            runtime_action_events = getattr(
                context,
                "runtime_action_events",
                [],
            )

            return [
                event
                for event in runtime_action_events[
                    action_event_followup_offset:
                ]
                if belongs_to_current_turn(
                    event
                )
            ]

        def consume_current_action_batch():

            nonlocal action_event_followup_offset
            nonlocal asset_result_offset
            nonlocal delayed_memory_result_offset

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

            return pending_action_events

        while followup_count < max_followups:

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

                await context.websocket.send_json({
                    "type": "runtime_action",
                    "action": "web_search",
                    "id": tool_call_id,
                    "text": (
                        f'Searching for "{query}"'
                    ),
                    "query": query,
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
                    "action": "web_search",
                    "id": tool_call_id,
                    "status": "completed",
                })

                context.runtime_search_result = search_result
                context.runtime_search_result_id = tool_call_id

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
                        "name": "web_search",
                        "query": query,
                        "id": tool_call_id,
                    })
                )

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_system_prompt(
                            context,
                            runtime_actions=followup_runtime_actions,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                        ),
                        state.translated_input,
                        context=context,
                        latest_action=latest_followup_action,
                        instruction=(
                            "Answer the latest user request using the "
                            "WEB_SEARCH tool result from trusted runtime "
                            "context. Mention the quoted source data when "
                            "it helps, then continue the workflow."
                        ),
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
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=(
                        not state.translate_response
                    ),
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
                        build_brain_system_prompt(
                            context,
                            runtime_actions=followup_runtime_actions,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                        ),
                        state.translated_input,
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
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=(
                        not state.translate_response
                    ),
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
                        build_brain_system_prompt(
                            context,
                            runtime_actions=followup_runtime_actions,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                        ),
                        state.translated_input,
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
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=(
                        not state.translate_response
                    ),
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

                if not pending_action_events:
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
                )

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_system_prompt(
                            context,
                            runtime_actions=followup_runtime_actions,
                            commit_active_memory_refresh=True,
                            include_previous_chat_messages=False,
                        ),
                        state.translated_input,
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
                    runtime_actions=followup_runtime_actions,
                    emit_content_to_chat=(
                        not state.translate_response
                    ),
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
                    build_brain_system_prompt(
                        context,
                        runtime_actions=followup_runtime_actions,
                        commit_active_memory_refresh=True,
                        include_previous_chat_messages=False,
                    ),
                    state.translated_input,
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
                runtime_actions=followup_runtime_actions,
                emit_content_to_chat=(
                    not state.translate_response
                ),
                filter_runtime_actions=True,
            )

            followup_count += 1
            continue

        if followup_count >= max_followups:
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

            final_system_prompt = (
                self.build_followup_system_prompt(
                    build_brain_system_prompt(
                        context,
                        runtime_actions=final_runtime_actions,
                        commit_active_memory_refresh=True,
                        include_previous_chat_messages=False,
                    ),
                    state.translated_input,
                    context=context,
                    latest_action="followup_limit_reached",
                )
            )
            final_system_prompt += (
                "\n\n<FOLLOWUP_LIMIT_REACHED>\n"
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
                runtime_actions=final_runtime_actions,
                emit_content_to_chat=(
                    not state.translate_response
                ),
                filter_runtime_actions=False,
                preserve_runtime_action_markers=True,
            )

        state.brain_response = text or ""
