# Formats delayed memory tool results and appended delayed memory context blocks.
from rules.runtime import (
    NO_ENTRIES_FOUND_MESSAGE,
)

from .formatting import (
    format_tool_result_payload,
)


def format_delayed_memory_list_result(
    result: dict,
) -> str:

    reports = [
        report
        for report in result.get(
            "reports",
            [],
        )
        or []
        if isinstance(
            report,
            dict,
        )
    ]

    if not reports:
        return NO_ENTRIES_FOUND_MESSAGE

    lines = []

    for index, report in enumerate(
        reports,
        start=1,
    ):
        title = str(
            report.get(
                "title",
                "",
            )
            or ""
        ).strip()

        if not title:
            title = "Untitled delayed memory"

        report_id = str(
            report.get(
                "id",
                "",
            )
            or ""
        ).strip()

        lines.append(
            f"{index}. {title} | id: {report_id}"
        )

    return "\n".join(
        lines
    )


def format_delayed_memory_report_result(
    result: dict,
) -> str:

    if result.get("ok") is False:
        return format_delayed_memory_failure_result(
            result
        )

    if result.get(
        "destination"
    ):
        return format_tool_result_payload(
            result
        )

    report = result.get(
        "report",
        {},
    )

    if not isinstance(
        report,
        dict,
    ):
        return format_tool_result_payload(
            result
        )

    return format_tool_result_payload(
        report
    )


def format_delayed_memory_failure_result(
    result: dict,
) -> str:

    failure = str(
        result.get(
            "failure",
            "",
        )
        or ""
    ).strip()

    if failure:
        return failure

    failure_followup_message = str(
        result.get(
            "failure_followup_message",
            "",
        )
        or ""
    ).strip()

    if failure_followup_message:
        return f"Failure: {failure_followup_message}"

    return format_tool_result_payload(
        result
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

        if action == "list_delayed_memory":
            sections.append(
                (
                    "LIST_DELAYED_MEMORY",
                    format_delayed_memory_list_result(
                        result
                    ),
                )
            )
            continue

        if action == "append_delayed_memory":
            if result.get("ok") is False:
                sections.append(
                    (
                        "APPEND_DELAYED_MEMORY",
                        format_delayed_memory_failure_result(
                            result
                        ),
                    )
                )
            continue

        if action == "remove_delayed_memory":
            sections.append(
                (
                    "REMOVE_DELAYED_MEMORY",
                    (
                        format_delayed_memory_failure_result
                        if result.get("ok") is False
                        else format_tool_result_payload
                    )(
                        result
                    ),
                )
            )
            continue

        if action == "save_delayed_memory_content":
            sections.append(
                (
                    "SAVE_DELAYED_MEMORY_CONTENT",
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


