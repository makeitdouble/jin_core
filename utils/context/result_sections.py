# Formats non-asset recorded tool result sections such as active memory actions.
from .formatting import (
    format_tool_result_payload,
)


def format_active_memory_result_sections(
    payload,
) -> list[tuple[str, str]]:

    sections = []

    for result in payload:
        if not isinstance(
            result,
            dict,
        ):
            continue

        action = str(
            result.get(
                "action",
                "",
            )
            or ""
        )

        if action == "save_active_memory":
            sections.append(
                (
                    "SAVE_ACTIVE_MEMORY",
                    format_tool_result_payload(
                        result
                    ),
                )
            )
            continue

        if action == "update_active_memory":
            sections.append(
                (
                    "UPDATE_ACTIVE_MEMORY",
                    format_tool_result_payload(
                        result
                    ),
                )
            )
            continue

        if action == "resolve_active_memory":
            sections.append(
                (
                    "RESOLVE_ACTIVE_MEMORY",
                    format_tool_result_payload(
                        result
                    ),
                )
            )

    return [
        section
        for section in sections
        if section[1]
    ]
