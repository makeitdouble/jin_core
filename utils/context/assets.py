# Formats asset action and skill listing results for runtime context output.
from xml.sax.saxutils import escape

from clients.brain_client_utils import (
    indent_xml,
)

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


def append_asset_results(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    retry_context = list(
        getattr(
            context,
            "runtime_asset_retry_context",
            [],
        )
        or []
    )
    current_asset_results = list(
        getattr(
            context,
            "runtime_asset_results",
            [],
        )
        or []
    )
    visible_skills_result = getattr(
        context,
        "runtime_visible_skills_result",
        {},
    )
    has_current_skills_result = any(
        isinstance(
            result,
            dict,
        )
        and result.get(
            "action"
        ) == "list_skills"
        for result in current_asset_results
    )
    persistent_results = (
        [visible_skills_result]
        if (
            isinstance(
                visible_skills_result,
                dict,
            )
            and visible_skills_result.get(
                "action"
            ) == "list_skills"
            and not has_current_skills_result
        )
        else []
    )
    asset_results = (
        retry_context
        + persistent_results
        + current_asset_results
    )

    if not asset_results:
        return

    tool_result_blocks = []
    for name, payload in format_asset_result_sections(
        asset_results[-5:],
        context,
    ):
        tool_result_blocks.append(
            f'    <TOOL_RESULT name="{escape(name)}">\n'
            f"{indent_xml(escape(payload))}\n"
            "    </TOOL_RESULT>"
        )

    parts.extend(
        tool_result_blocks
    )
