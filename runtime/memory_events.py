from runtime.memory_common import (
    safe_call,
)
from runtime.L1_memory_utils import (
    build_runtime_memory_context_text,
)


def _build_runtime_memory_snapshot(context, memory: str) -> dict:
    from runtime.L1_memory import (
        build_runtime_memory_snapshot,
    )

    return build_runtime_memory_snapshot(
        context,
        memory,
    )


def _parse_runtime_memory_lines(memory: str) -> list[dict]:
    from runtime.L1_memory import (
        parse_runtime_memory_lines,
    )

    return parse_runtime_memory_lines(
        memory
    )


def _apply_runtime_memory_diff(
        lines: list[dict],
        previous_snapshot: dict | None,
) -> list[dict]:
    from runtime.L1_memory import (
        apply_runtime_memory_diff,
    )

    return apply_runtime_memory_diff(
        lines,
        previous_snapshot,
    )


def _build_runtime_memory_patch(
        lines: list[dict],
        previous_snapshot: dict | None,
) -> dict:
    from runtime.L1_memory import (
        build_runtime_memory_patch,
    )

    return build_runtime_memory_patch(
        lines,
        previous_snapshot,
    )


def _build_strength_map(lines: list[dict]) -> dict[str, float]:
    from runtime.L1_memory import (
        build_strength_map,
    )

    return build_strength_map(
        lines
    )


def _get_strength_zones(lines: list[dict]) -> dict:
    from runtime.L1_memory import (
        get_strength_zones,
    )

    return get_strength_zones(
        lines
    )


def _average_diff(values: list[float]) -> float:
    from runtime.L2_memory import (
        average_diff,
    )

    return average_diff(
        values
    )


def _diff_value_range(values: list[float]) -> float:
    from runtime.L2_memory import (
        diff_value_range,
    )

    return diff_value_range(
        values
    )


async def emit_runtime_memory_update(
        context,
) -> dict:

    emitter = getattr(
        context,
        "emitter",
        None,
    )

    memory = getattr(context, "runtime_memory", "")
    display_memory = build_runtime_memory_context_text(
        memory,
        context,
    )

    if not hasattr(
        context,
        "runtime_memory_snapshots",
    ):
        context.runtime_memory_snapshots = []

    snapshot = _build_runtime_memory_snapshot(context, memory)

    context.runtime_memory_snapshots.append(snapshot)
    context.runtime_memory_snapshot_index = snapshot["index"]

    emit = getattr(
        emitter,
        "emit",
        None,
    )

    await safe_call(
        emit,
        {
            "type": "runtime_memory_update",
            "memory": display_memory,
            "updates": getattr(context, "runtime_memory_updates", 0),
            "snapshot": snapshot,
            "snapshots_count": len(context.runtime_memory_snapshots),
            "snapshot_index": context.runtime_memory_snapshot_index,
        },
    )

    return snapshot


def build_runtime_l1_diff_stats(
        diff_history: list[dict],
) -> dict:

    values = [
        item.get(
            "total_diff",
            0,
        )
        for item in diff_history
    ]

    return {
        "count": len(values),
        "average": _average_diff(values),
        "range": _diff_value_range(values),
        "min": min(values) if values else 0,
        "max": max(values) if values else 0,
    }




def rebuild_latest_runtime_memory_snapshot(
        context,
) -> dict | None:

    snapshots = getattr(
        context,
        "runtime_memory_snapshots",
        [],
    )

    if not snapshots:
        return None

    latest_snapshot = snapshots[-1]
    previous_snapshot = (
        snapshots[-2]
        if len(snapshots) > 1
        else None
    )

    display_memory = build_runtime_memory_context_text(
        getattr(
            context,
            "runtime_memory",
            "",
        ),
        context,
    )

    lines = _parse_runtime_memory_lines(
        display_memory
    )

    lines = _apply_runtime_memory_diff(
        lines,
        previous_snapshot,
    )

    patch_details = _build_runtime_memory_patch(
        lines,
        previous_snapshot,
    )

    refreshed_snapshot = {
        **latest_snapshot,
        "raw_memory": display_memory,
        "lines": lines,
        "patch": patch_details["patch"],
        "total_diff": patch_details["total_diff"],
    }

    snapshots[-1] = refreshed_snapshot
    context.runtime_memory_snapshots = snapshots
    context.runtime_memory_snapshot_index = refreshed_snapshot["index"]

    return refreshed_snapshot


async def emit_runtime_memory_snapshot_refresh(
        context,
        snapshot: dict | None,
) -> None:

    if snapshot is None:
        return

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

    await safe_call(
        emit,
        {
            "type": "runtime_memory_update",
            "memory": snapshot.get(
                "raw_memory",
                "",
            ),
            "updates": getattr(
                context,
                "runtime_memory_updates",
                0,
            ),
            "snapshot": snapshot,
            "snapshots_count": len(
                getattr(
                    context,
                    "runtime_memory_snapshots",
                    [],
                )
                or []
            ),
            "snapshot_index": getattr(
                context,
                "runtime_memory_snapshot_index",
                snapshot.get(
                    "index",
                    0,
                ),
            ),
            "replace_latest": True,
        },
    )

async def emit_runtime_l1_diff_update(
        context,
) -> None:

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

    history = list(
        getattr(
            context,
            "runtime_l1_diff_history",
            [],
        )
        or []
    )

    snapshots = list(
        getattr(
            context,
            "runtime_memory_snapshots",
            [],
        )
        or []
    )
    latest_lines = (
        snapshots[-1].get("lines", [])
        if snapshots
        else []
    )

    await safe_call(
        emit,
        {
            "type": "runtime_l1_diff_update",
            "diffs": history,
            "stats": build_runtime_l1_diff_stats(
                history
            ),
            "strength_map": _build_strength_map(
                latest_lines
            ),
            "strength_zones": _get_strength_zones(
                latest_lines
            ),
        },
    )


async def emit_runtime_session_memory_update(
        context,
        *,
        persist_browser: bool = False,
) -> None:

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

    memory = getattr(
        context,
        "runtime_l3_session_memory",
        "",
    ) or getattr(
        context,
        "session_memory",
        "",
    )
    event_snapshots = list(
        getattr(
            context,
            "runtime_session_event_snapshots",
            [],
        )
        or []
    )

    await safe_call(
        emit,
        {
            "type": "runtime_session_memory_update",
            "memory": memory,
            "event_snapshots": event_snapshots,
            "updates": getattr(
                context,
                "runtime_session_memory_updates",
                0,
            ),
            "source": getattr(
                context,
                "session_memory_source",
                "",
            ),
            "persist": persist_browser,
        },
    )


async def emit_runtime_action_completed(
        context,
        *,
        action: str,
) -> None:

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

    await safe_call(
        emit,
        {
            "type": "runtime_action",
            "action": action,
            "status": "completed",
        },
    )
