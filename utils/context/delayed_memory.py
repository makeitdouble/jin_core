# Formats delayed memory tool results and appended delayed memory context blocks.
from xml.sax.saxutils import escape

from clients.brain_client_utils import (
    indent_xml,
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
        return "No delayed memory reports saved."

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
        return format_tool_result_payload(
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

        if action == "remove_delayed_memory":
            sections.append(
                (
                    "REMOVE_DELAYED_MEMORY",
                    format_tool_result_payload(
                        result
                    ),
                )
            )

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


def append_delayed_memory_results(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    delayed_memory_results = list(
        getattr(
            context,
            "runtime_delayed_memory_results",
            [],
        )
        or []
    )

    if not delayed_memory_results:
        return

    tool_result_blocks = []

    for name, payload in format_delayed_memory_result_sections(
        delayed_memory_results[-5:],
    ):
        tool_result_blocks.append(
            f'    <TOOL_RESULT name="{escape(name)}">\n'
            f"{indent_xml(escape(payload))}\n"
            "    </TOOL_RESULT>"
        )

    if not tool_result_blocks:
        return

    parts.append(
        '<TOOL_RESULTS type=\'delayed_memory\'>\n'
        f"{chr(10).join(tool_result_blocks)}\n"
        "</TOOL_RESULTS>"
    )


def build_appended_delayed_memory_context(
    context=None,
) -> str:

    if context is None:
        return ""

    appended_report = getattr(
        context,
        "runtime_appended_delayed_memory",
        {},
    )

    if not isinstance(
        appended_report,
        dict,
    ):
        return ""

    if not appended_report:
        return ""

    return (
        "<APPENDED_DELAYED_MEMORY>\n"
        f"{indent_xml(escape(format_tool_result_payload(appended_report)))}\n"
        "</APPENDED_DELAYED_MEMORY>"
    )


def append_appended_delayed_memory(
    parts: list[str],
    context=None,
) -> None:

    appended_delayed_memory_context = (
        build_appended_delayed_memory_context(
            context
        )
    )

    if appended_delayed_memory_context:
        parts.append(
            appended_delayed_memory_context
        )
