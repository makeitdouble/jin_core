# Formats delayed memory tool results and loaded delayed memory context blocks.
from .runtime_action_result_text import (
    format_runtime_action_result,
)


def format_delayed_memory_report_result(
    result: dict,
) -> str:

    return format_runtime_action_result(
        result,
        runtime_action="SAVE_DELAYED_MEMORY",
    )


def format_delayed_memory_failure_result(
    result: dict,
) -> str:

    action = str(
        result.get("action", "")
        or ""
    ).strip().upper()

    return format_runtime_action_result(
        result,
        runtime_action=action,
    )

def format_delayed_memory_result_sections(
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

        if action == "load_delayed_memory":
            if result.get("ok") is False:
                sections.append(
                    (
                        "LOAD_DELAYED_MEMORY",
                        format_delayed_memory_failure_result(
                            result
                        ),
                    )
                )
            continue

        if action == "unload_delayed_memory":
            sections.append(
                (
                    "UNLOAD_DELAYED_MEMORY",
                    format_runtime_action_result(
                        result,
                        runtime_action="UNLOAD_DELAYED_MEMORY",
                    ),
                )
            )
            continue

        if action == "save_delayed_memory":
            sections.append(
                (
                    "SAVE_DELAYED_MEMORY",
                    format_delayed_memory_report_result(
                        result
                    ),
                )
            )

    return [
        section
        for section in sections
        if section[1]
    ]


