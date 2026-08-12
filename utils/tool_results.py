import json
from copy import deepcopy


TOOL_RESULT_KIND_SEARCH = "search"
TOOL_RESULT_KIND_DEEP_SEARCH = "deep_search"
TOOL_RESULT_KIND_ASSET = "asset"
TOOL_RESULT_KIND_ACTIVE_MEMORY = "active_memory"
TOOL_RESULT_KIND_DELAYED_MEMORY = "delayed_memory"
TOOL_RESULT_KIND_SESSION = "session"

RUNTIME_TOOL_RESULT_LIST_ATTRIBUTES = (
    "runtime_asset_results",
    "runtime_asset_retry_results",
    "runtime_asset_retry_context",
    "runtime_delayed_memory_results",
)


def _failed_tool_result_dedupe_key(
    entry: dict,
) -> tuple | None:

    result = entry.get(
        "result"
    )
    if not isinstance(
        result,
        dict,
    ):
        return None

    if result.get(
        "ok"
    ) is not False:
        return None

    stable_result = {
        key: value
        for key, value in result.items()
        if key != "id"
    }

    return (
        entry.get(
            "kind",
            "",
        ),
        json.dumps(
            stable_result,
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        ),
    )


def begin_runtime_tool_results_turn(
    context,
) -> None:

    setattr(
        context,
        "runtime_tool_results_turn_count",
        0,
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
) -> None:

    tool_results = get_runtime_tool_results(
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

    dedupe_key = _failed_tool_result_dedupe_key(
        entry
    )
    if dedupe_key is not None:
        for existing_entry in tool_results:
            if not isinstance(
                existing_entry,
                dict,
            ):
                continue

            if (
                _failed_tool_result_dedupe_key(
                    existing_entry
                )
                == dedupe_key
            ):
                return False

    tool_results.append(
        entry
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
    tool_results[:] = [
        entry
        for entry in tool_results
        if not predicate(
            entry
        )
    ]


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
