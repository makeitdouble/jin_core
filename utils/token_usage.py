from utils.tokens import (
    estimate_stream_input_tokens,
    estimate_stream_live_tokens,
    estimate_stream_text_tokens,
)


TOKEN_ESTIMATE_SCALE_MIN = 1.0
TOKEN_ESTIMATE_SCALE_MAX = 3.0
TOKEN_ESTIMATE_SCALE_PREVIOUS_WEIGHT = 0.65


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


def _as_float(
    value,
    default: float = 1.0,
) -> float:

    try:
        return float(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return default


def get_runtime_token_estimate_scale(
    context,
    runtime_id: str,
) -> float:

    scales = getattr(
        context,
        "runtime_token_estimate_scales",
        None,
    )

    if not isinstance(
        scales,
        dict,
    ):
        return TOKEN_ESTIMATE_SCALE_MIN

    return max(
        TOKEN_ESTIMATE_SCALE_MIN,
        min(
            TOKEN_ESTIMATE_SCALE_MAX,
            _as_float(
                scales.get(
                    runtime_id,
                    TOKEN_ESTIMATE_SCALE_MIN,
                )
            ),
        ),
    )


def calibrate_runtime_token_estimate(
    context,
    *,
    runtime_id: str,
    estimated_prompt_tokens: int,
    provider_prompt_tokens: int,
) -> float:

    estimated = _as_int(
        estimated_prompt_tokens
    )
    provider = _as_int(
        provider_prompt_tokens
    )

    if estimated <= 0 or provider <= 0:
        return get_runtime_token_estimate_scale(
            context,
            runtime_id,
        )

    observed_scale = max(
        TOKEN_ESTIMATE_SCALE_MIN,
        min(
            TOKEN_ESTIMATE_SCALE_MAX,
            provider / estimated,
        ),
    )

    scales = getattr(
        context,
        "runtime_token_estimate_scales",
        None,
    )

    if not isinstance(
        scales,
        dict,
    ):
        scales = {}
        context.runtime_token_estimate_scales = scales

    previous = scales.get(
        runtime_id
    )

    if previous is None:
        calibrated_scale = observed_scale
    else:
        previous_scale = max(
            TOKEN_ESTIMATE_SCALE_MIN,
            min(
                TOKEN_ESTIMATE_SCALE_MAX,
                _as_float(
                    previous
                ),
            ),
        )
        calibrated_scale = (
            previous_scale
            * TOKEN_ESTIMATE_SCALE_PREVIOUS_WEIGHT
            + observed_scale
            * (
                1.0
                - TOKEN_ESTIMATE_SCALE_PREVIOUS_WEIGHT
            )
        )

    calibrated_scale = max(
        TOKEN_ESTIMATE_SCALE_MIN,
        min(
            TOKEN_ESTIMATE_SCALE_MAX,
            calibrated_scale,
        ),
    )
    scales[runtime_id] = calibrated_scale

    return calibrated_scale


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
    estimate_scale: float = 1.0,
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
            scale=estimate_scale,
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
            estimate_stream_text_tokens(
                getattr(
                    stream,
                    "response",
                    "",
                ),
                scale=estimate_scale,
            )
            + estimate_stream_text_tokens(
                getattr(
                    stream,
                    "reasoning",
                    "",
                ),
                scale=estimate_scale,
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
        scale=estimate_scale,
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
