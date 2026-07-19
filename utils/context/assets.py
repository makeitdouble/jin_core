# Formats asset action and skill listing results for runtime context output.

from .formatting import (
    format_tool_result_payload,
)
from .skills import (
    format_list_skills_result,
    format_missing_skill_result,
)


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
    latest_list_skills_index = None

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
            == "list_skills"
        ):
            latest_list_skills_index = index

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
            == "append_skill"
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

        if (
            isinstance(
                result,
                dict,
            )
            and result.get(
                "action"
            )
            == "list_skills"
        ):
            if index != latest_list_skills_index:
                continue

            flush_pending_results()
            sections.append(
                (
                    "SKILLS",
                    format_list_skills_result(
                        result,
                        context,
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

