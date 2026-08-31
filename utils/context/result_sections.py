# Formats non-asset recorded tool result sections such as active memory actions.
from .runtime_action_result_text import (
    format_runtime_action_result,
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
                    format_runtime_action_result(
                        result,
                        runtime_action="SAVE_ACTIVE_MEMORY",
                    ),
                )
            )
            continue

        if action == "update_active_memory":
            sections.append(
                (
                    "UPDATE_ACTIVE_MEMORY",
                    format_runtime_action_result(
                        result,
                        runtime_action="UPDATE_ACTIVE_MEMORY",
                    ),
                )
            )
            continue

        if action == "delete_active_memory":
            sections.append(
                (
                    "DELETE_ACTIVE_MEMORY",
                    format_runtime_action_result(
                        result,
                        runtime_action="DELETE_ACTIVE_MEMORY",
                    ),
                )
            )

    return [
        section
        for section in sections
        if section[1]
    ]
