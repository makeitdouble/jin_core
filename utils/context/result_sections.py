# Formats non-asset recorded tool result sections such as active memory and session saves.
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

        if action == "create_active_memory":
            sections.append(
                (
                    "CREATE_ACTIVE_MEMORY",
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


def format_session_result_sections(
    payload,
) -> list[tuple[str, str]]:

    sections = []

    for result in payload:
        if not isinstance(
            result,
            dict,
        ):
            continue

        if str(
            result.get(
                "action",
                "",
            )
            or ""
        ) != "save_session":
            continue

        sections.append((
            "SAVE_SESSION",
            format_tool_result_payload(
                result
            ),
        ))

    return [
        section
        for section in sections
        if section[1]
    ]
