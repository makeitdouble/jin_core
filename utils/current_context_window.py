import re
from dataclasses import dataclass, replace

from config_loader import config
from rules.runtime import CONTEXT_MAINTENANCE_WARNING_MESSAGE

from utils.token_usage import (
    get_runtime_token_estimate_scale,
)
from utils.tokens import (
    estimate_prompt_tokens,
)


CURRENT_CONTEXT_WINDOW_TAG = "CONTEXT_WINDOW"
CURRENT_CONTEXT_WINDOW_PLACEHOLDER = "__JIN_CURRENT_CONTEXT_WINDOW__"

CURRENT_CONTEXT_WINDOW_RE = re.compile(
    (
        r"(?P<indent>[ \t]*)"
        r"<CONTEXT_WINDOW>"
        r".*?"
        r"</CONTEXT_WINDOW>"
    ),
    re.DOTALL,
)

@dataclass(frozen=True)
class CurrentContextWindowPrompt:
    system_prompt: str
    used_tokens: int
    context_window: int
    value: str
    maintenance_state: dict | None = None


CONTEXT_MAINTENANCE_THRESHOLD_1 = 0.75
CONTEXT_MAINTENANCE_THRESHOLD_2 = 0.85
CONTEXT_MAINTENANCE_THRESHOLD_ALWAYS = 0.90
CONTEXT_MAINTENANCE_PREFIX_RE = re.compile(
    r"\A(?:<CONTEXT_MAINTENANCE>.*?</CONTEXT_MAINTENANCE>\s*)+", re.DOTALL,
)


def _maintenance_thresholds() -> tuple[float, float, float]:
    defaults = (CONTEXT_MAINTENANCE_THRESHOLD_1, CONTEXT_MAINTENANCE_THRESHOLD_2,
                CONTEXT_MAINTENANCE_THRESHOLD_ALWAYS)
    try:
        values = tuple(float(getattr(config, name, default)) for name, default in zip(
            ("CONTEXT_MAINTENANCE_THRESHOLD_1", "CONTEXT_MAINTENANCE_THRESHOLD_2",
             "CONTEXT_MAINTENANCE_THRESHOLD_ALWAYS"), defaults,
        ))
        if 0 < values[0] < values[1] < values[2] <= 1:
            return values
    except (TypeError, ValueError):
        pass
    return defaults


def _maintenance_decision(context, prepared, *, has_results: bool):
    """Plan state only. Submission, not preview/preparation, commits it."""
    thresholds = _maintenance_thresholds()
    session_id = str(getattr(context, "session_id", "") or "")
    old = getattr(context, "runtime_context_maintenance", {}) or {}
    if old.get("session_id") != session_id or old.get("thresholds") != thresholds:
        old = {}
    usage = prepared.used_tokens / prepared.context_window if prepared.context_window > 0 else 0
    previous = old.get("usage", 0)
    delivered = list(old.get("delivered", (False, False)))
    boundary_rearmed = list(old.get("boundary_rearmed", (False, False)))
    for index, threshold in enumerate(thresholds[:2]):
        falling_edge = usage == threshold and previous > threshold
        boundary_rearmed[index] = falling_edge or (usage == threshold and boundary_rearmed[index])
        if usage < threshold or falling_edge:
            delivered[index] = False
    if not has_results:
        delivered = [False, False]
    warn = has_results and prepared.context_window > 0 and (
        usage >= thresholds[2] or any(
            usage >= threshold and not delivered[index] and not boundary_rearmed[index]
            for index, threshold in enumerate(thresholds[:2])
        )
    )
    if warn:
        for index, threshold in enumerate(thresholds[:2]):
            if usage >= threshold and not boundary_rearmed[index]:
                delivered[index] = True
    return warn, {"session_id": session_id, "thresholds": thresholds,
                  "usage": usage, "delivered": tuple(delivered),
                  "boundary_rearmed": tuple(boundary_rearmed)}


def commit_context_maintenance(context, prepared: CurrentContextWindowPrompt) -> None:
    """Called at the Brain client submission boundary, including follow-ups."""
    if context is not None and prepared.maintenance_state is not None:
        context.runtime_context_maintenance = dict(prepared.maintenance_state)


def _with_context_maintenance(*, context, runtime_id, prepared, user_prompt):
    from utils.context.tool_results import visible_removable_tool_result_hints
    from utils.tool_results_context import has_nonempty_tools_results_context

    warn, next_state = _maintenance_decision(
        context, prepared,
        has_results=has_nonempty_tools_results_context(prepared.system_prompt),
    )
    if not warn:
        return replace(prepared, maintenance_state=next_state)

    base = prepared.system_prompt
    hints = visible_removable_tool_result_hints(context, base)
    # Metadata and CONTEXT_WINDOW describe the same final prompt. Rebuild from
    # the unchanged base, never prepend recursively. Threshold decisions use
    # the pre-warning budget so the warning cannot trigger itself or a new band.
    for _ in range(16):
        available = max(0, prepared.context_window - prepared.used_tokens)
        block = (
            "<CONTEXT_MAINTENANCE>\n" + CONTEXT_MAINTENANCE_WARNING_MESSAGE + "\n\n"
            f"context_used_tokens: {prepared.used_tokens}\n"
            f"context_total_tokens: {prepared.context_window}\n"
            f"context_available_tokens: {available}\n"
            f"context_used_percent: {100 * prepared.used_tokens / prepared.context_window:.2f}%\n"
            f"context_available_percent: {100 * available / prepared.context_window:.2f}%\n"
            + hints + "</CONTEXT_MAINTENANCE>\n\n"
        )
        updated = annotate_current_context_window(
            context=context, runtime_id=runtime_id, system_prompt=block + base,
            user_prompt=user_prompt, context_window=prepared.context_window,
        )
        if updated.used_tokens == prepared.used_tokens:
            return replace(updated, maintenance_state=next_state)
        prepared = updated
    # The estimator depends on text length, so numeric widths normally settle
    # within a few passes. Never submit inaccurate self-referential metadata.
    raise ValueError("Context maintenance token metadata did not stabilize")


def _as_int(
    value,
) -> int:

    try:
        return int(
            value or 0
        )
    except (
        TypeError,
        ValueError,
    ):
        return 0


def text_from_user_prompt(
    user_prompt,
) -> str:

    if isinstance(
        user_prompt,
        str,
    ):
        return user_prompt

    if isinstance(
        user_prompt,
        list,
    ):
        text_parts = []

        for item in user_prompt:
            if not isinstance(
                item,
                dict,
            ):
                continue

            if item.get(
                "type",
            ) != "text":
                continue

            text_parts.append(
                str(
                    item.get(
                        "text",
                        "",
                    )
                )
            )

        return "\n".join(
            text_parts
        )

    return str(
        user_prompt
        or ""
    )


def provider_counted_user_prompt_text(
    context,
    user_prompt,
) -> str:

    text = text_from_user_prompt(
        user_prompt
    )

    if (
        text == ""
        and bool(
            getattr(
                context,
                "runtime_followup_tick_active",
                False,
            )
        )
    ):
        return " "

    return text


def format_current_context_window_value(
    *,
    used_tokens: int,
    context_window: int,
) -> str:

    used_tokens = max(
        0,
        _as_int(
            used_tokens
        ),
    )
    context_window = _as_int(
        context_window
    )

    if context_window > 0:
        return f"{used_tokens}/{context_window} occupied"

    return f"{used_tokens}/unknown occupied"


def _format_field(
    value: str,
    *,
    indent: str = "    ",
) -> str:

    return (
        f"{indent}<CONTEXT_WINDOW>"
        f"{value}"
        "</CONTEXT_WINDOW>"
    )


def ensure_current_context_window_field(
    system_prompt: str,
    value: str = CURRENT_CONTEXT_WINDOW_PLACEHOLDER,
) -> str:

    prompt = str(
        system_prompt
        or ""
    )

    if CURRENT_CONTEXT_WINDOW_RE.search(
        prompt
    ):
        return CURRENT_CONTEXT_WINDOW_RE.sub(
            lambda match: _format_field(
                value,
                indent=match.group(
                    "indent"
                ),
            ),
            prompt,
            count=1,
        )

    close_tag = "</TRUSTED_RUNTIME_VARIABLES>"
    if close_tag not in prompt:
        return prompt

    for tag in (
        "MODEL_UID",
        "BRAIN_MODEL_UID",
        "SERVICE_MODEL_UID",
        "SESSION_ID",
    ):
        match = re.search(
            (
                r"(?P<indent>[ \t]*)"
                rf"<{tag}>"
                r".*?"
                rf"</{tag}>"
            ),
            prompt,
            flags=re.DOTALL,
        )

        if not match:
            continue

        return (
            prompt[:match.end()]
            + "\n"
            + _format_field(
                value,
                indent=match.group(
                    "indent"
                ),
            )
            + prompt[match.end():]
        )

    return prompt.replace(
        close_tag,
        (
            _format_field(
                value,
            )
            + "\n"
            + close_tag
        ),
        1,
    )


def estimate_current_context_tokens(
    *,
    context,
    runtime_id: str,
    system_prompt: str,
    user_prompt,
) -> int:

    return estimate_prompt_tokens(
        system_prompt=str(system_prompt or ""),
        user_prompt=(user_prompt if isinstance(user_prompt, list) else
                     provider_counted_user_prompt_text(context, user_prompt)),
        scale=get_runtime_token_estimate_scale(
            context,
            runtime_id,
        ),
    )


def annotate_current_context_window(
    *,
    context,
    runtime_id: str,
    system_prompt: str,
    user_prompt,
    context_window: int,
) -> CurrentContextWindowPrompt:

    prompt = ensure_current_context_window_field(
        system_prompt,
        CURRENT_CONTEXT_WINDOW_PLACEHOLDER,
    )

    used_tokens = 0
    value = CURRENT_CONTEXT_WINDOW_PLACEHOLDER

    for _ in range(12):
        used_tokens = estimate_current_context_tokens(
            context=context,
            runtime_id=runtime_id,
            system_prompt=prompt,
            user_prompt=user_prompt,
        )
        value = format_current_context_window_value(
            used_tokens=used_tokens,
            context_window=context_window,
        )
        next_prompt = ensure_current_context_window_field(
            prompt,
            value,
        )

        if next_prompt == prompt:
            break

        prompt = next_prompt

    used_tokens = estimate_current_context_tokens(
        context=context,
        runtime_id=runtime_id,
        system_prompt=prompt,
        user_prompt=user_prompt,
    )
    value = format_current_context_window_value(
        used_tokens=used_tokens,
        context_window=context_window,
    )
    prompt = ensure_current_context_window_field(
        prompt,
        value,
    )

    return CurrentContextWindowPrompt(
        system_prompt=prompt,
        used_tokens=used_tokens,
        context_window=_as_int(
            context_window
        ),
        value=value,
    )


def remember_current_context_window(
    context,
    *,
    runtime_id: str,
    prepared: CurrentContextWindowPrompt,
) -> None:

    if context is None:
        return

    value = {
        "runtime_id": runtime_id,
        "used_tokens": prepared.used_tokens,
        "context_window": prepared.context_window,
        "value": prepared.value,
    }

    context.runtime_current_context_window = value
    context.runtime_current_context_window_text = prepared.value

    if prepared.context_window > 0:
        from runtime.registry import runtime_state

        try:
            runtime_state.update_runtime_state(
                runtime_id,
                max_tokens=prepared.context_window,
            )
        except KeyError:
            # Lightweight/custom runtime IDs can use the prompt helper without
            # becoming one of the two UI telemetry owners.
            pass


async def resolve_current_context_window(
    client,
    *,
    fallback_context_window: int = 0,
    force_refresh: bool = False,
) -> int:

    resolver = getattr(
        client,
        "resolve_request_context_window",
        None,
    )

    if resolver is not None:
        try:
            resolved = await resolver(
                force_refresh=force_refresh
            )
        except TypeError:
            resolved = await resolver()
        except Exception:
            resolved = None

        resolved_context_window = _as_int(
            resolved
        )
        if resolved_context_window > 0:
            return resolved_context_window

    return max(
        0,
        _as_int(
            fallback_context_window
        ),
    )


async def prepare_current_context_window_prompt(
    *,
    client,
    context,
    runtime_id: str,
    system_prompt: str,
    user_prompt,
    fallback_context_window: int = 0,
    force_refresh: bool = False,
) -> CurrentContextWindowPrompt:

    context_window = await resolve_current_context_window(
        client,
        fallback_context_window=fallback_context_window,
        force_refresh=force_refresh,
    )

    prompt = str(
        system_prompt
        or ""
    )

    if str(runtime_id or "").strip().casefold() == "brain":
        prompt = CONTEXT_MAINTENANCE_PREFIX_RE.sub("", prompt)
        # L-T is the one large memory inventory whose prompt projection can shrink
        # safely. Measure the CURRENT prompt without L-T first, then keep a simple
        # 50% -> all / 90% -> one linear budget between those points. Selection is
        # by last_mentioned_at, while the surviving lines stay in their existing
        # prompt order. Storage, panel order and memory-attention ordering are not
        # touched.
        try:
            from runtime.LT_context_budget import (
                calculate_lt_context_fact_limit,
                get_lt_context_fact_ids,
                limit_long_term_memory_context,
                split_long_term_memory_context,
            )

            prompt_without_lt, lt_block, _lt_match = (
                split_long_term_memory_context(
                    prompt
                )
            )
            lt_fact_ids = get_lt_context_fact_ids(
                lt_block
            )

            if lt_fact_ids and context_window > 0:
                base_prepared = annotate_current_context_window(
                    context=context,
                    runtime_id=runtime_id,
                    system_prompt=prompt_without_lt,
                    user_prompt=user_prompt,
                    context_window=context_window,
                )
                fact_limit = calculate_lt_context_fact_limit(
                    total_facts=len(lt_fact_ids),
                    used_tokens_without_lt=base_prepared.used_tokens,
                    context_window=context_window,
                )
                prompt = limit_long_term_memory_context(
                    context=context,
                    system_prompt=prompt,
                    fact_limit=fact_limit,
                )
                context.runtime_lt_context_budget = {
                    "used_tokens_without_lt": base_prepared.used_tokens,
                    "context_window": context_window,
                    "usage_without_lt": round(
                        base_prepared.used_tokens / context_window,
                        4,
                    ),
                    "available_facts": len(lt_fact_ids),
                    "loaded_facts": fact_limit,
                }
        except Exception:
            # Prompt budgeting must be fail-open: if anything about the optional
            # projection fails, keep the historical all-facts prompt intact.
            pass

    prepared = annotate_current_context_window(
        context=context,
        runtime_id=runtime_id,
        system_prompt=prompt,
        user_prompt=user_prompt,
        context_window=context_window,
    )
    if str(runtime_id or "").strip().casefold() == "brain":
        prepared = _with_context_maintenance(
            context=context, runtime_id=runtime_id, prepared=prepared, user_prompt=user_prompt,
        )
    remember_current_context_window(
        context,
        runtime_id=runtime_id,
        prepared=prepared,
    )

    return prepared
