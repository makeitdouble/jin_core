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

from clients.service_client import (
    ask_service_model,
)

from settings.config_loader import (
    config,
)

from utils.response_extractor import (
    ResponseExtractor,
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

        result = await ask_service_model(
            client=context.clients["service"],
            system_prompt=(
                "You are a runtime search agent.\n"
                "Use the query as a search task and return a concise structured result.\n"
                "Do not include chain-of-thought, plans, or markdown.\n"
                "Return only a useful answer for the main assistant to consume."
            ),
            user_prompt=(
                "SEARCH QUERY:\n"
                f"{query}\n\n"
                "Return:\n"
                "<SEARCH_RESULT>\n"
                f"  <QUERY>{query}</QUERY>\n"
                "  <SUMMARY>...</SUMMARY>\n"
                "  <FINDINGS>...</FINDINGS>\n"
                "</SEARCH_RESULT>"
            ),
            temperature=(
                config.SERVICE_TEMPERATURE
            ),
            max_tokens=(
                config.SERVICE_MAX_TOKENS
            ),
        )

        content = (
            ResponseExtractor
            .extract_content_text(
                result
            )
        )

        return content.strip()

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

        if (
            not text.strip()
            and context.runtime_search_queries
        ):

            query = context.runtime_search_queries.pop(0)

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
                "Original user request:\n"
                f"{state.translated_input}\n\n"
                "Runtime search result:\n"
                f"{search_result}\n\n"
                "Answer the original user request using the runtime search result. "
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
