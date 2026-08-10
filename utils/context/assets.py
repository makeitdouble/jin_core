# Formats asset action results for runtime context output.
import re

from .formatting import (
    format_tool_result_payload,
)
from .skills import (
    format_missing_skill_result,
)


def _format_action_result_name(
    result: dict,
) -> str:

    if not isinstance(
        result,
        dict,
    ):
        return ""

    raw_name = str(
        result.get(
            "runtime_action_name",
            "",
        )
        or result.get(
            "action",
            "",
        )
        or ""
    ).strip()

    if not raw_name:
        return ""

    name = re.sub(
        r"[^A-Za-z0-9]+",
        "_",
        raw_name,
    ).strip(
        "_"
    ).upper()
    name = re.sub(
        r"_+",
        "_",
        name,
    )

    return name


def format_asset_result_sections(
    payload,
    context=None,
) -> list[tuple[str, str]]:

    if not isinstance(
        payload,
        list,
    ):
        return [
            (
                "ASSETS",
                format_tool_result_payload(
                    payload
                ),
            ),
        ]

    sections = []
    pending_results = []
    def flush_pending_results() -> None:
        if not pending_results:
            return

        sections.append(
            (
                "ASSETS",
                format_tool_result_payload(
                    list(
                        pending_results
                    )
                ),
            )
        )
        pending_results.clear()

    for index, result in enumerate(
        payload,
    ):
        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            )
            == "load_skill"
            and result.get("ok") is False
            and result.get("error") == "skill_not_found"
        ):
            flush_pending_results()
            sections.append(
                (
                    "SKILL_ERROR",
                    format_missing_skill_result(
                        result
                    ),
                )
            )
            continue

        pending_results.append(
            result
        )

    flush_pending_results()

    return [
        section
        for section in sections
        if section[1]
    ]

