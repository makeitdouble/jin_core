import re
import time
from copy import deepcopy


TOOL_RESULT_KIND_SEARCH = "search"
TOOL_RESULT_KIND_DEEP_SEARCH = "deep_search"
TOOL_RESULT_KIND_ASSET = "asset"
TOOL_RESULT_KIND_ACTIVE_MEMORY = "active_memory"
TOOL_RESULT_KIND_DELAYED_MEMORY = "delayed_memory"
TOOL_RESULT_KIND_FILES = "files"
TOOL_RESULT_KIND_LT = "lt"
TOOL_RESULT_KIND_FACT_CONTEXT = "fact_context"
TOOL_RESULT_KIND_RUNTIME_ACTION = "runtime_action"

RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES = (
    "runtime_asset_results",
    "runtime_asset_retry_results",
    "runtime_asset_retry_context",
    "runtime_delayed_memory_results",
)
RUNTIME_TOOL_RESULT_CREATED_AT_ATTRIBUTE = (
    "runtime_tool_result_created_ats"
)


def _parse_tool_result_timestamp(
    value,
) -> float | None:

    if isinstance(
        value,
        (int, float),
    ):
        timestamp = float(
            value
        )
    else:
        try:
            timestamp = float(
                str(
                    value
                    or ""
                ).strip()
            )
        except (
            TypeError,
            ValueError,
        ):
            return None

    if timestamp <= 0:
        return None

    return timestamp


def get_runtime_tool_result_created_ats(
    context,
) -> list:

    created_ats = getattr(
        context,
        RUNTIME_TOOL_RESULT_CREATED_AT_ATTRIBUTE,
        None,
    )

    if not isinstance(
        created_ats,
        list,
    ):
        created_ats = []
        setattr(
            context,
            RUNTIME_TOOL_RESULT_CREATED_AT_ATTRIBUTE,
            created_ats,
        )

    return created_ats


def align_runtime_tool_result_created_ats(
    context,
) -> list:

    tool_results = get_runtime_tool_results(
        context
    )
    created_ats = get_runtime_tool_result_created_ats(
        context
    )

    if len(created_ats) < len(tool_results):
        created_ats.extend(
            [None] * (
                len(tool_results)
                - len(created_ats)
            )
        )
    elif len(created_ats) > len(tool_results):
        del created_ats[
            len(tool_results):
        ]

    return created_ats


def get_runtime_tool_result_created_at(
    context,
    index: int,
    entry: dict | None = None,
) -> float | None:

    if isinstance(
        entry,
        dict,
    ):
        for key in (
            "created_at",
            "recorded_at",
        ):
            timestamp = _parse_tool_result_timestamp(
                entry.get(
                    key
                )
            )
            if timestamp is not None:
                return timestamp

    created_ats = getattr(
        context,
        RUNTIME_TOOL_RESULT_CREATED_AT_ATTRIBUTE,
        None,
    )
    if not isinstance(
        created_ats,
        list,
    ):
        return None

    try:
        created_at = created_ats[
            index
        ]
    except (
        TypeError,
        IndexError,
    ):
        return None

    return _parse_tool_result_timestamp(
        created_at
    )


def _trim_runtime_tool_result_created_ats_prefix(
    context,
    count: int,
) -> None:

    created_ats = getattr(
        context,
        RUNTIME_TOOL_RESULT_CREATED_AT_ATTRIBUTE,
        None,
    )

    if not isinstance(
        created_ats,
        list,
    ):
        return

    if count <= 0:
        return

    del created_ats[
        :min(
            count,
            len(created_ats),
        )
    ]


def _failed_tool_result_requires_followup(
    kind: str,
    result,
) -> bool:

    if (
        not isinstance(
            result,
            dict,
        )
        or result.get("ok") is not False
    ):
        return False

    normalized_kind = str(
        kind
        or ""
    ).strip().casefold()

    if normalized_kind in {
        TOOL_RESULT_KIND_RUNTIME_ACTION,
        TOOL_RESULT_KIND_SEARCH,
        TOOL_RESULT_KIND_DEEP_SEARCH,
        TOOL_RESULT_KIND_ASSET,
        TOOL_RESULT_KIND_DELAYED_MEMORY,
        TOOL_RESULT_KIND_FILES,
        TOOL_RESULT_KIND_FACT_CONTEXT,
    }:
        return True

    if normalized_kind != TOOL_RESULT_KIND_ACTIVE_MEMORY:
        return False

    runtime_action = str(
        result.get("runtime_action_name")
        or result.get("action")
        or ""
    ).strip()

    if not runtime_action:
        return False

    from contracts.rules_assembler import (
        runtime_action_follows_up_on_fail,
    )

    return runtime_action_follows_up_on_fail(
        runtime_action
    )


def _queue_failed_tool_result_followup(
    context,
    kind: str,
    result,
) -> None:

    if not _failed_tool_result_requires_followup(
        kind,
        result,
    ):
        return

    setattr(
        context,
        "runtime_followup_action_failure_pending",
        True,
    )


def begin_runtime_tool_results_turn(
    context,
) -> None:

    context.runtime_failure_followup_tool_ids = []
    context.runtime_failure_followup_entries = []
    setattr(
        context,
        "runtime_tool_results_turn_count",
        0,
    )
    setattr(
        context,
        "runtime_followup_action_failure_pending",
        False,
    )


def get_runtime_tool_results(
    context,
) -> list[dict]:

    tool_results = getattr(
        context,
        "runtime_tool_results",
        None,
    )

    if not isinstance(
        tool_results,
        list,
    ):
        tool_results = []
        setattr(
            context,
            "runtime_tool_results",
            tool_results,
        )

    return tool_results


def record_runtime_tool_result(
    context,
    kind: str,
    result,
    *,
    result_id: str = "",
    created_at: float | None = None,
) -> bool:

    tool_results = get_runtime_tool_results(
        context
    )
    created_ats = align_runtime_tool_result_created_ats(
        context
    )
    turn_count = int(
        getattr(
            context,
            "runtime_tool_results_turn_count",
            0,
        )
        or 0
    )

    entry = {
        "kind": str(
            kind
            or ""
        ).strip(),
        "result": deepcopy(
            result
        ),
    }

    normalized_result_id = str(
        result_id
        or ""
    ).strip()
    if normalized_result_id:
        entry["id"] = normalized_result_id

    recorded_at = (
        _parse_tool_result_timestamp(
            created_at
        )
        if created_at is not None
        else None
    )

    entry["tool_id"] = allocate_runtime_tool_id(context)
    bind_tool_result_to_action(context, entry)
    tool_results.append(
        entry
    )
    _queue_failed_tool_result_followup(context, entry["kind"], result)
    if _failed_tool_result_requires_followup(entry["kind"], result):
        pending = list(getattr(context, "runtime_failure_followup_tool_ids", []) or [])
        pending.append(entry["tool_id"])
        context.runtime_failure_followup_tool_ids = pending
        pending_entries = list(
            getattr(
                context,
                "runtime_failure_followup_entries",
                [],
            )
            or []
        )
        pending_entries.append(
            deepcopy(entry)
        )
        context.runtime_failure_followup_entries = pending_entries
    created_ats.append(
        (
            time.time()
            if recorded_at is None
            else recorded_at
        )
    )
    setattr(
        context,
        "runtime_tool_results_turn_count",
        turn_count + 1,
    )
    return True


def remove_runtime_tool_results(
    context,
    predicate,
) -> None:

    tool_results = get_runtime_tool_results(
        context
    )
    created_ats = getattr(
        context,
        RUNTIME_TOOL_RESULT_CREATED_AT_ATTRIBUTE,
        None,
    )
    next_tool_results = []
    next_created_ats = []

    for index, entry in enumerate(
        tool_results
    ):
        if predicate(
            entry
        ):
            continue

        next_tool_results.append(
            entry
        )
        if (
            isinstance(
                created_ats,
                list,
            )
            and index < len(
                created_ats
            )
        ):
            next_created_ats.append(
                created_ats[index]
            )

    tool_results[:] = next_tool_results
    if isinstance(
        created_ats,
        list,
    ):
        created_ats[:] = next_created_ats


def _runtime_result_list_count(
    context,
    attribute_name: str,
) -> int:

    results = getattr(
        context,
        attribute_name,
        None,
    )

    if not isinstance(
        results,
        list,
    ):
        return 0

    return len(
        results
    )


def snapshot_runtime_tool_results_state(
    context,
) -> dict:

    return {
        "tool_result_count": len(
            get_runtime_tool_results(
                context
            )
        ),
        "runtime_search_result": getattr(
            context,
            "runtime_search_result",
            "",
        ),
        "runtime_search_result_id": getattr(
            context,
            "runtime_search_result_id",
            "",
        ),
        "runtime_deep_search_result": getattr(
            context,
            "runtime_deep_search_result",
            "",
        ),
        "runtime_deep_search_result_id": getattr(
            context,
            "runtime_deep_search_result_id",
            "",
        ),
        "list_counts": {
            attribute_name: _runtime_result_list_count(
                context,
                attribute_name,
            )
            for attribute_name in RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES
        },
    }


def _trim_runtime_result_list_prefix(
    context,
    attribute_name: str,
    count: int,
) -> None:

    results = getattr(
        context,
        attribute_name,
        None,
    )

    if not isinstance(
        results,
        list,
    ):
        setattr(
            context,
            attribute_name,
            [],
        )
        return

    if count <= 0:
        return

    del results[
        :min(
            count,
            len(results),
        )
    ]


def clear_runtime_tool_results_before_state(
    context,
    state: dict,
) -> None:

    if not isinstance(
        state,
        dict,
    ):
        clear_runtime_tool_results(
            context
        )
        return

    tool_results = get_runtime_tool_results(
        context
    )
    try:
        tool_result_count = max(
            0,
            int(
                state.get(
                    "tool_result_count",
                    0,
                )
                or 0
            ),
        )
    except (
        TypeError,
        ValueError,
    ):
        tool_result_count = 0

    if tool_result_count:
        del tool_results[
            :min(
                tool_result_count,
                len(tool_results),
            )
        ]
        _trim_runtime_tool_result_created_ats_prefix(
            context,
            tool_result_count,
        )

    generation = int(
        getattr(
            context,
            "runtime_tool_results_generation",
            0,
        )
        or 0
    )
    setattr(
        context,
        "runtime_tool_results_generation",
        generation + 1,
    )
    setattr(
        context,
        "runtime_tool_results_turn_count",
        len(tool_results),
    )

    if (
        state.get("runtime_search_result")
        or state.get("runtime_search_result_id")
    ):
        setattr(
            context,
            "runtime_search_result",
            "",
        )
        setattr(
            context,
            "runtime_search_result_id",
            "",
        )

    if (
        state.get("runtime_deep_search_result")
        or state.get("runtime_deep_search_result_id")
    ):
        setattr(
            context,
            "runtime_deep_search_result",
            "",
        )
        setattr(
            context,
            "runtime_deep_search_result_id",
            "",
        )

    list_counts = state.get(
        "list_counts",
        {},
    )
    if not isinstance(
        list_counts,
        dict,
    ):
        list_counts = {}

    for attribute_name in RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES:
        try:
            list_count = max(
                0,
                int(
                    list_counts.get(
                        attribute_name,
                        0,
                    )
                    or 0
                ),
            )
        except (
            TypeError,
            ValueError,
        ):
            list_count = 0

        _trim_runtime_result_list_prefix(
            context,
            attribute_name,
            list_count,
        )


def clear_runtime_tool_results(
    context,
) -> None:

    get_runtime_tool_results(
        context
    ).clear()
    get_runtime_tool_result_created_ats(
        context
    ).clear()
    generation = int(
        getattr(
            context,
            "runtime_tool_results_generation",
            0,
        )
        or 0
    )
    setattr(
        context,
        "runtime_tool_results_generation",
        generation + 1,
    )
    setattr(
        context,
        "runtime_tool_results_turn_count",
        0,
    )

    setattr(
        context,
        "runtime_search_result",
        "",
    )
    setattr(
        context,
        "runtime_search_result_id",
        "",
    )
    setattr(
        context,
        "runtime_deep_search_result",
        "",
    )
    setattr(
        context,
        "runtime_deep_search_result_id",
        "",
    )
    for attribute_name in RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES:
        results = getattr(
            context,
            attribute_name,
            None,
        )

        if isinstance(
            results,
            list,
        ):
            results.clear()
        else:
            setattr(
                context,
                attribute_name,
                [],
            )


def allocate_runtime_tool_id(context) -> str:
    """Never assign IDs to legacy entries or reuse a removed ID."""
    high_water = int(getattr(context, "runtime_tool_result_sequence", 0) or 0)
    for entry in get_runtime_tool_results(context):
        match = re.fullmatch(r"T([1-9][0-9]*)", str(entry.get("tool_id", "")))
        if match:
            high_water = max(high_water, int(match[1]))
    context.runtime_tool_result_sequence = high_water + 1
    return f"T{high_water + 1}"


def bind_tool_result_to_action(context, entry) -> None:
    result = entry.get("result")
    kind = entry.get("kind")
    name = str(result.get("runtime_action_name") or result.get("action") or "").lower() if isinstance(result, dict) else ""
    if kind == TOOL_RESULT_KIND_ASSET and name not in {"load_skill", "unload_skill", "list_skills"}:
        name = "asset_action"
    name = {TOOL_RESULT_KIND_SEARCH: "web_search", TOOL_RESULT_KIND_DEEP_SEARCH: "deep_web_search",
            TOOL_RESULT_KIND_LT: "update_lt_facts", TOOL_RESULT_KIND_FACT_CONTEXT: "recall_fact_context"}.get(kind, name)
    events = getattr(context, "runtime_action_events", []) or []
    turn_id = str(getattr(context, "runtime_current_turn_id", "") or "")
    result_id = entry.get("id")
    exact = [event for event in events if result_id and event.get("id") == result_id]
    if exact:
        events = exact
        turn_id = str(exact[0].get("runtime_turn_id", "") or "")
    for event in events:
        if name == "clean_tool_results" and event.get("payload", "") != result.get("payload", ""):
            continue
        if (event.get("name") == name and not event.get("tool_id")
                and (not turn_id or event.get("runtime_turn_id", "") == turn_id)):
            event["tool_id"] = entry["tool_id"]
            entry["action_payload"] = event.get("payload", "")
            entry["runtime_turn_id"] = turn_id
            if kind == TOOL_RESULT_KIND_FILES and result.get("ok") is False:
                event["status"] = "failed"
                event["failure_reason"] = str(result.get("detail") or result.get("error") or "action failed")
            break


def clean_runtime_tool_result(context, tool_id: str) -> bool:
    """Remove exactly one modern result; legacy entries never match."""
    if not re.fullmatch(r"T[1-9][0-9]*", tool_id):
        return False
    entries = get_runtime_tool_results(context)
    target = next((entry for entry in entries if entry.get("tool_id") == tool_id), None)
    if target is None:
        return False
    # Legacy mirrors must not resurrect the removed result when the list empties.
    kind, result = target.get("kind"), target.get("result")
    for attr in RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES:
        values = getattr(context, attr, None)
        if isinstance(values, list):
            values[:] = [value for value in values if value != result]
    for result_kind, prefix in ((TOOL_RESULT_KIND_SEARCH, "runtime_search"),
                                (TOOL_RESULT_KIND_DEEP_SEARCH, "runtime_deep_search")):
        if kind == result_kind and getattr(context, prefix + "_result", None) == result:
            setattr(context, prefix + "_result", "")
            setattr(context, prefix + "_result_id", "")
    current_start = len(entries) - int(getattr(context, "runtime_tool_results_turn_count", 0) or 0)
    was_current = entries.index(target) >= current_start
    remove_runtime_tool_results(context, lambda entry: entry is target)
    context.runtime_tool_results_generation = int(getattr(context, "runtime_tool_results_generation", 0) or 0) + 1
    if was_current:
        context.runtime_tool_results_turn_count = max(0, int(getattr(context, "runtime_tool_results_turn_count", 0) or 0) - 1)
    return True
