from agents.base_node import BaseNode

from runtime.runtime_stream import (
    RuntimeStream,
)

from clients.brain_client import (
    ask_brain_stream,
    build_brain_payload,
    build_brain_system_prompt,
    record_deep_thought_calls,
)

from clients.search_client import (
    run_search_service,
)

from utils.brain import (
    get_brain_runtime_config,
)


class BrainNode(BaseNode):

    async def run_search_action(
            self,
            *,
            context,
            query: str,
    ) -> str:

        result = await run_search_service(
            context=context,
            query=query,
        )

        return result.strip()

    async def run_brain_stream(
            self,
            *,
            state,
            context,
            brain_runtime,
            brain_client,
            system_prompt: str,
            brain_payload: str,
            runtime_actions: dict,
    ) -> tuple[str, str]:

        logger = context.logger

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
            context_snapshot={
                "context_role": "brain",
                "system_prompt": system_prompt,
                "user_prompt": brain_payload,
            },
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
        context.runtime_search_result = ""

        system_prompt = (
            build_brain_system_prompt(
                context,
                runtime_actions=runtime_actions,
            )
        )

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
        )

        record_deep_thought_calls(
            context,
            reasoning,
        )

        if context.runtime_search_queries:

            query = context.runtime_search_queries.pop(0)
            context.runtime_search_queries.clear()

            await logger.log_runtime(
                "[RUNTIME ACTION] "
                f"executing search query={query!r}"
            )

            await context.websocket.send_json({
                "type": "runtime_action",
                "action": "search",
                "text": (
                    f'Searching for "{query}"'
                ),
                "query": query,
            })

            search_result = await self.run_search_action(
                context=context,
                query=query,
            )

            context.runtime_search_result = search_result

            followup_runtime_actions = {
                **runtime_actions,
                "CAN_SEARCH": False,
            }

            followup_system_prompt = (
                build_brain_system_prompt(
                    context,
                    runtime_actions=followup_runtime_actions,
                )
            )

            followup_payload = (
                "User request:\n"
                f"{state.translated_input}\n\n"
                "Answer the user request using the SEARCH tool result "
                "from trusted runtime context. "
                "Mention the quoted source data when it helps. "
                "Do not emit another SEARCH runtime action."
            )

            text, reasoning = await self.run_brain_stream(
                state=state,
                context=context,
                brain_runtime=brain_runtime,
                brain_client=brain_client,
                system_prompt=followup_system_prompt,
                brain_payload=followup_payload,
                runtime_actions=followup_runtime_actions,
            )

            record_deep_thought_calls(
                context,
                reasoning,
            )

            if not text.strip():
                text = search_result

        state.brain_response = text or ""
