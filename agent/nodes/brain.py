from agent.nodes.base import BaseNode

from runtime.stream import (
    RuntimeStream,
)

from clients.brain_client import (
    ask_brain_stream,
    build_brain_payload,
    build_brain_system_prompt,
    emit_active_memory_records_update_if_dirty,
)

from clients.search_client import (
    build_search_result_fallback_answer,
    run_search_service,
)

from clients.brain_client_utils import (
    get_brain_runtime_config,
)


class BrainNode(BaseNode):

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
    ) -> tuple[str, str]:

        logger = context.logger

        context_snapshot = {
            "context_role": "brain",
            "system_prompt": system_prompt,
            "user_prompt": brain_payload,
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
        )

        generator = ask_brain_stream(
            client=brain_client,
            text=state.translated_input,
            context=context,
            system_prompt=system_prompt,
            brain_payload=brain_payload,
            runtime_actions=runtime_actions,
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
                build_brain_system_prompt(
                    context,
                    runtime_actions=followup_runtime_actions,
                    commit_active_memory_refresh=True,
                )
            )

            await emit_active_memory_records_update_if_dirty(
                context
            )

            followup_payload = (
                "User request:\n"
                f"{state.translated_input}\n\n"
                "Answer the user request using the WEB_SEARCH tool result "
                "from trusted runtime context. "
                "Mention the quoted source data when it helps. "
                "Do not emit another WEB_SEARCH runtime action."
            )

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

        state.brain_response = text or ""
