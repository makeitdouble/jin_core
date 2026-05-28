from utils.tokens import (
    estimate_optional_tokens,
    estimate_stream_input_tokens,
    estimate_stream_live_tokens,
)


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


def record_token_usage(
    context,
    *,
    runtime_id: str,
    role: str,
    kind: str = "service",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    context_tokens: int = 0,
):

    usage_events = getattr(
        context,
        "runtime_usage_events",
        None,
    )

    if usage_events is None:
        usage_events = []
        context.runtime_usage_events = usage_events

    usage_events.append({
        "runtime_id": runtime_id,
        "role": role,
        "kind": kind,
        "prompt_tokens": _as_int(
            prompt_tokens
        ),
        "completion_tokens": _as_int(
            completion_tokens
        ),
        "total_tokens": _as_int(
            total_tokens
        ),
        "context_tokens": _as_int(
            context_tokens
        ),
    })


def record_stream_token_usage(
    context,
    *,
    runtime_id: str,
    role: str,
    kind: str = "service",
    stream,
    prompt_text: str = "",
):

    prompt_tokens = (
        _as_int(
            getattr(
                stream,
                "prompt_tokens",
                0,
            )
        )
        or estimate_stream_input_tokens(
            stream,
            prompt_text=prompt_text,
        )
    )

    completion_tokens = (
        _as_int(
            getattr(
                stream,
                "completion_tokens",
                0,
            )
        )
        or (
            estimate_optional_tokens(
                getattr(
                    stream,
                    "response",
                    "",
                )
            )
            + estimate_optional_tokens(
                getattr(
                    stream,
                    "reasoning",
                    "",
                )
            )
        )
    )

    total_tokens = (
        _as_int(
            getattr(
                stream,
                "total_tokens",
                0,
            )
        )
        or prompt_tokens
        + completion_tokens
    )
    context_tokens = estimate_stream_live_tokens(
        stream,
        prompt_text=prompt_text,
    )

    record_token_usage(
        context,
        runtime_id=runtime_id,
        role=role,
        kind=kind,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=total_tokens,
        context_tokens=context_tokens,
    )


def summarize_token_usage(
    context,
    *,
    kind: str | None = None,
) -> dict:

    summary = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
    }

    for event in getattr(
        context,
        "runtime_usage_events",
        [],
    ):
        if (
            kind is not None
            and event.get(
                "kind"
            )
            != kind
        ):
            continue

        summary["prompt_tokens"] += _as_int(
            event.get(
                "prompt_tokens",
                0,
            )
        )
        summary["completion_tokens"] += _as_int(
            event.get(
                "completion_tokens",
                0,
            )
        )
        summary["total_tokens"] += _as_int(
            event.get(
                "total_tokens",
                0,
            )
        )

    return summary


def summarize_token_usage_by_role(
    context,
    *,
    kind: str | None = None,
) -> list[dict]:

    grouped = {}

    for event in getattr(
        context,
        "runtime_usage_events",
        [],
    ):
        if (
            kind is not None
            and event.get(
                "kind"
            )
            != kind
        ):
            continue

        key = (
            event.get(
                "role",
                "unknown",
            ),
            event.get(
                "runtime_id",
                "unknown",
            ),
        )

        if key not in grouped:
            grouped[key] = {
                "role": key[0],
                "runtime_id": key[1],
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "context_tokens": 0,
            }

        grouped[key]["prompt_tokens"] += _as_int(
            event.get(
                "prompt_tokens",
                0,
            )
        )
        grouped[key]["completion_tokens"] += _as_int(
            event.get(
                "completion_tokens",
                0,
            )
        )
        grouped[key]["total_tokens"] += _as_int(
            event.get(
                "total_tokens",
                0,
            )
        )
        grouped[key]["context_tokens"] += _as_int(
            event.get(
                "context_tokens",
                0,
            )
        )

    return list(
        grouped.values()
    )


def format_token_usage_summary(
    context,
) -> str:

    summary = summarize_token_usage(
        context
    )
    breakdown = summarize_token_usage_by_role(
        context
    )

    lines = [
        "PROVIDER USAGE",
    ]

    for item in breakdown:
        lines.append(
            (
                f"{item['role']}: "
                f"{item['total_tokens']}"
                f" (prompt={item['prompt_tokens']}, "
                f"completion={item['completion_tokens']})"
            )
        )

    lines.append(
        f"total: {summary['total_tokens']}"
    )

    return "\n".join(
        lines
    )
