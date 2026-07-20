import json
from copy import deepcopy


TOOL_RESULT_KIND_SEARCH = "search"
TOOL_RESULT_KIND_ASSET = "asset"
TOOL_RESULT_KIND_ACTIVE_MEMORY = "active_memory"
TOOL_RESULT_KIND_DELAYED_MEMORY = "delayed_memory"
TOOL_RESULT_KIND_SESSION = "session"


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
        "runtime_visible_skills_result",
        {},
    )

    for attribute_name in (
        "runtime_asset_results",
        "runtime_asset_retry_results",
        "runtime_asset_retry_context",
        "runtime_delayed_memory_results",
    ):
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
