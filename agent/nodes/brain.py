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


FOLLOWUP_USER_MESSAGE = "No new messages, multi-task in progress"


class BrainNode(BaseNode):

    @staticmethod
    def build_followup_system_prompt(
            system_prompt: str,
            initial_user_request: str,
            *,
            instruction: str = "",
    ) -> str:

        sections = [
            (
                "<INITIAL_USER_REQUEST>\n"
                f"{str(initial_user_request or '').strip()}\n"
                "</INITIAL_USER_REQUEST>"
            )
        ]

        if instruction.strip():
            sections.append(
                instruction.strip()
            )

        sections.append(
            system_prompt
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
    ) -> tuple[str, str]:

        logger = context.logger

        context_snapshot = build_brain_context_snapshot(
            context=context,
            system_prompt=system_prompt,
            user_prompt=brain_payload,
            runtime_actions=runtime_actions,
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
        if not hasattr(
            context,
            "runtime_asset_results",
        ):
            context.runtime_asset_results = []
        else:
            context.runtime_asset_results.clear()

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
        skill_state_event_offset = runtime_action_event_offset
        followup_count = 0
        max_followups = 12

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

                followup_runtime_actions = {
                    **runtime_actions,
                    "CAN_WEB_SEARCH": False,
                }

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_system_prompt(
                            context,
                            runtime_actions=followup_runtime_actions,
                            commit_active_memory_refresh=True,
                        ),
                        state.translated_input,
                        instruction=(
                            "Answer the initial user request using the "
                            "WEB_SEARCH tool result from trusted runtime "
                            "context. Mention the quoted source data when "
                            "it helps. Do not emit another WEB_SEARCH "
                            "runtime action."
                        ),
                    )
                )

                await emit_active_memory_records_update_if_dirty(
                    context
                )

                followup_payload = FOLLOWUP_USER_MESSAGE

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload=followup_payload,
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

            runtime_action_events = getattr(
                context,
                "runtime_action_events",
                [],
            )
            new_skill_state_events = [
                event
                for event in runtime_action_events[
                    skill_state_event_offset:
                ]
                if event.get("name") in {
                    "append_skill",
                    "remove_skill",
                }
            ]
            skill_state_event_offset = len(
                runtime_action_events
            )

            if new_skill_state_events:
                followup_runtime_actions = {
                    **runtime_actions,
                    "CAN_WEB_SEARCH": False,
                    "CAN_SAVE_SESSION": False,
                    "CAN_SAVE_DELAYED_MEMORY": False,
                    "CAN_SAVE_ACTIVE_MEMORY": False,
                }

                followup_system_prompt = (
                    self.build_followup_system_prompt(
                        build_brain_system_prompt(
                            context,
                            runtime_actions=followup_runtime_actions,
                            commit_active_memory_refresh=True,
                        ),
                        state.translated_input,
                    )
                )

                await emit_active_memory_records_update_if_dirty(
                    context
                )

                followup_payload = FOLLOWUP_USER_MESSAGE

                text, reasoning = await self.run_brain_stream(
                    state=state,
                    context=context,
                    brain_runtime=brain_runtime,
                    brain_client=brain_client,
                    system_prompt=followup_system_prompt,
                    brain_payload=followup_payload,
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

            if len(asset_results) <= asset_result_offset:
                break

            asset_result_offset = len(
                asset_results
            )
            followup_runtime_actions = {
                **runtime_actions,
                "CAN_WEB_SEARCH": False,
                "CAN_SAVE_SESSION": False,
                "CAN_SAVE_DELAYED_MEMORY": False,
                "CAN_SAVE_ACTIVE_MEMORY": False,
            }

            followup_system_prompt = (
                self.build_followup_system_prompt(
                    build_brain_system_prompt(
                        context,
                        runtime_actions=followup_runtime_actions,
                        commit_active_memory_refresh=True,
                    ),
                    state.translated_input,
                )
            )

            await emit_active_memory_records_update_if_dirty(
                context
            )

            followup_payload = FOLLOWUP_USER_MESSAGE

            text, reasoning = await self.run_brain_stream(
                state=state,
                context=context,
                brain_runtime=brain_runtime,
                brain_client=brain_client,
                system_prompt=followup_system_prompt,
                brain_payload=followup_payload,
                runtime_actions=followup_runtime_actions,
                emit_content_to_chat=(
                    not state.translate_response
                ),
                filter_runtime_actions=True,
            )

            followup_count += 1

            if (
                    len(asset_results) <= asset_result_offset
                    and text.strip()
            ):
                break

        state.brain_response = text or ""
