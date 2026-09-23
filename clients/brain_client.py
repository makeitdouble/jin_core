import asyncio


from utils.tokens import estimate_prompt_tokens

from config_loader import (
    config,
)
from contracts.rules_assembler import (
    RUNTIME_ACTION_POSTING_BOARD,
    RUNTIME_ACTION_CALL_MCP,
    RUNTIME_ACTION_SAVE_DELAYED_MEMORY,
)

from clients.errors import (
    format_client_error,
)

from rules.brain_context_builder import (
    build_brain_context,
    get_enabled_runtime_actions,
)

from utils.brain_client_utils import (
    apply_runtime_action_calls,
    should_execute_save_delayed_memory,
)

from runtime.client import (
    LMStudioAPIError,
)
from runtime.state import BRAIN_RUNTIME_ID


from utils.current_context_window import (
    prepare_current_context_window_prompt,
)
from utils.skills_asset_utils import (
    normalize_skill_name,
)


def get_brain_runtime_id() -> str:
    return BRAIN_RUNTIME_ID


def get_response_enabled_runtime_actions(
    runtime_actions=None,
    user_message: str = "",
    *,
    context=None,
) -> tuple[str, ...]:

    enabled_actions = list(
        get_enabled_runtime_actions(
            runtime_actions
        )
    )

    if (
        RUNTIME_ACTION_SAVE_DELAYED_MEMORY
        in enabled_actions
        and not should_execute_save_delayed_memory(
            user_message,
            context=context,
        )
    ):
        enabled_actions.remove(
            RUNTIME_ACTION_SAVE_DELAYED_MEMORY
        )

    if RUNTIME_ACTION_POSTING_BOARD in enabled_actions:
        loaded_skill_names = {
            normalize_skill_name(
                skill.get("name", "")
            )
            for skill in (
                getattr(
                    context,
                    "runtime_loaded_skills",
                    [],
                )
                or []
            )
            if isinstance(skill, dict)
        }
        if "posting_board" not in loaded_skill_names:
            enabled_actions.remove(
                RUNTIME_ACTION_POSTING_BOARD
            )

    if RUNTIME_ACTION_CALL_MCP in enabled_actions:
        from utils.mcp_skill_utils import has_loaded_mcp_skill

        if not has_loaded_mcp_skill(context):
            enabled_actions.remove(
                RUNTIME_ACTION_CALL_MCP
            )

    return tuple(
        enabled_actions
    )


async def emit_active_memory_records_update_if_dirty(
    context,
) -> None:

    if context is None:
        return

    if not getattr(
        context,
        "runtime_active_memory_records_dirty",
        False,
    ):
        return

    context.runtime_active_memory_records_dirty = False

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

    if emit is None:
        return

    await emit({
        "type": "active_memory_records_update",
        "active_memory_records": list(
            getattr(
                context,
                "active_memory_records",
                [],
            )
            or []
        ),
    })


# ---------------------------------------------------------
# PAYLOAD
# ---------------------------------------------------------

def build_brain_payload(
    text: str,
    context=None,
) -> str:

    return text


def build_brain_user_prompt_content(
    text: str,
    context=None,
):

    content = [
        {
            "type": "text",
            "text": text,
        },
    ]

    for attachment in (
        getattr(
            context,
            "runtime_turn_attachments",
            [],
        )
        or []
    ):

        if not isinstance(
            attachment,
            dict,
        ):
            continue

        if (
            attachment.get(
                "kind",
            )
            != "image"
        ):
            continue

        data_url = str(
            attachment.get(
                "data_url",
                "",
            )
            or ""
        )

        if not data_url.startswith(
            "data:image/",
        ):
            continue

        content.append({
            "type": "image_url",
            "image_url": {
                "url": data_url,
            },
        })

    if len(content) == 1:
        return text

    return content


def build_brain_context_snapshot(
    *,
    system_prompt: str,
    user_prompt: str,
    model_user_prompt=None,
) -> dict:

    snapshot = {
        "context_role": "brain",
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
    }

    if isinstance(model_user_prompt, list):
        snapshot["image_input_tokens"] = estimate_prompt_tokens(
            system_prompt="", user_prompt=[part for part in model_user_prompt
                if isinstance(part, dict) and part.get("type") == "image_url"],
        )
    return snapshot


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
    context_window_prepared: bool = False,
):

    resolved_brain_payload: str = (
        brain_payload
        if brain_payload is not None
        else build_brain_payload(
            text,
            context=context,
        )
    )

    resolved_system_prompt: str = (
        system_prompt
        or build_brain_context(
            context,
            runtime_actions,
            user_input=resolved_brain_payload,
            commit_active_memory_refresh=True,
        )
    )

    if system_prompt is None:
        await emit_active_memory_records_update_if_dirty(
            context
        )

    model_user_prompt = build_brain_user_prompt_content(
        resolved_brain_payload,
        context=context,
    )

    if not context_window_prepared:
        prepared_context_window = await prepare_current_context_window_prompt(
            client=client,
            context=context,
            runtime_id=get_brain_runtime_id(),
            system_prompt=resolved_system_prompt,
            user_prompt=model_user_prompt,
            force_refresh=True,
        )
        resolved_system_prompt = prepared_context_window.system_prompt

    # Provider transport only. RuntimeStream is the single owner of runtime
    # marker parsing, action lifecycle, counters, guards and session history.
    try:
        async for model_chunk in client.stream(
            context=context,
            system_prompt=resolved_system_prompt,
            user_prompt=model_user_prompt,
            temperature=config.BRAIN_TEMPERATURE,
            max_tokens=None,
        ):
            yield model_chunk

    except asyncio.CancelledError:
        raise

    except LMStudioAPIError:
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
