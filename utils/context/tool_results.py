# Builds the full tool results context from search, asset, memory, and session results.
from xml.sax.saxutils import escape

from clients.brain_client_utils import (
    indent_xml,
    strip_empty_results_xml,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    TOOL_RESULT_KIND_SEARCH,
    TOOL_RESULT_KIND_SESSION,
    get_runtime_tool_results,
)
from utils.tool_results_context import (
    build_tools_results_context,
)

from .assets import (
    append_asset_results,
    format_asset_result_sections,
)
from .delayed_memory import (
    append_delayed_memory_results,
    format_delayed_memory_result_sections,
)
from .result_sections import (
    format_active_memory_result_sections,
    format_session_result_sections,
)
from .skills import (
    append_appended_skills,
)


def append_tool_results(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    search_result = getattr(
        context,
        "runtime_search_result",
        "",
    )

    if not search_result:
        return

    search_result = strip_empty_results_xml(
        search_result
    )
    search_result_id = getattr(
        context,
        "runtime_search_result_id",
        "",
    )

    tool_result_attrs = (
        'name="WEB_SEARCH"'
    )

    if search_result_id:
        tool_result_attrs = (
            f'{tool_result_attrs} '
            f'id="{escape(search_result_id)}"'
        )

    parts.append(
        '<TOOL_RESULTS type=\'external_untrusted_evidence\'>\n'
        f"    <TOOL_RESULT {tool_result_attrs}>\n"
        f"{indent_xml(search_result)}\n"
        "    </TOOL_RESULT>\n"
        "</TOOL_RESULTS>"
    )


def append_recorded_tool_results(
    parts: list[str],
    context=None,
) -> bool:

    if context is None:
        return False

    appended = False

    for entry in get_runtime_tool_results(
        context
    ):
        if not isinstance(
            entry,
            dict,
        ):
            continue

        kind = str(
            entry.get(
                "kind",
                "",
            )
            or ""
        ).strip()
        result = entry.get(
            "result"
        )

        if kind == TOOL_RESULT_KIND_SEARCH:
            search_result = strip_empty_results_xml(
                str(
                    result
                    or ""
                )
            )
            if not search_result:
                continue

            attrs = 'name="WEB_SEARCH"'
            result_id = str(
                entry.get(
                    "id",
                    "",
                )
                or ""
            ).strip()
            if result_id:
                attrs += f' id="{escape(result_id)}"'

            parts.append(
                "<TOOL_RESULTS type='external_untrusted_evidence'>\n"
                f"    <TOOL_RESULT {attrs}>\n"
                f"{indent_xml(search_result)}\n"
                "    </TOOL_RESULT>\n"
                "</TOOL_RESULTS>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_ASSET:
            sections = format_asset_result_sections(
                [result],
                context,
            )
            if not sections:
                continue

            blocks = [
                f'    <TOOL_RESULT name="{escape(name)}">\n'
                f"{indent_xml(escape(payload))}\n"
                "    </TOOL_RESULT>"
                for name, payload in sections
            ]
            parts.append(
                "<TOOL_RESULTS>\n"
                f"{chr(10).join(blocks)}\n"
                "</TOOL_RESULTS>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_ACTIVE_MEMORY:
            sections = format_active_memory_result_sections(
                [result]
            )
            if not sections:
                continue

            blocks = [
                f'    <TOOL_RESULT name="{escape(name)}">\n'
                f"{indent_xml(escape(payload))}\n"
                "    </TOOL_RESULT>"
                for name, payload in sections
            ]
            parts.append(
                "<TOOL_RESULTS type='active_memory'>\n"
                f"{chr(10).join(blocks)}\n"
                "</TOOL_RESULTS>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_SESSION:
            sections = format_session_result_sections(
                [result]
            )
            if not sections:
                continue

            blocks = [
                f'    <TOOL_RESULT name="{escape(name)}">\n'
                f"{indent_xml(escape(payload))}\n"
                "    </TOOL_RESULT>"
                for name, payload in sections
            ]
            parts.append(
                "<TOOL_RESULTS type='session'>\n"
                f"{chr(10).join(blocks)}\n"
                "</TOOL_RESULTS>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_DELAYED_MEMORY:
            sections = format_delayed_memory_result_sections(
                [result]
            )
            if not sections:
                continue

            blocks = [
                f'    <TOOL_RESULT name="{escape(name)}">\n'
                f"{indent_xml(escape(payload))}\n"
                "    </TOOL_RESULT>"
                for name, payload in sections
            ]
            parts.append(
                "<TOOL_RESULTS type='delayed_memory'>\n"
                f"{chr(10).join(blocks)}\n"
                "</TOOL_RESULTS>"
            )
            appended = True

    return appended


def build_tool_results_context(
    context=None,
) -> str:

    tool_result_blocks = []
    extra_parts = []

    if append_recorded_tool_results(
        tool_result_blocks,
        context,
    ):
        append_appended_skills(
            extra_parts,
            context,
        )
    else:
        append_tool_results(
            tool_result_blocks,
            context,
        )
        append_asset_results(
            tool_result_blocks,
            context,
        )
        append_delayed_memory_results(
            tool_result_blocks,
            context,
        )
        append_appended_skills(
            extra_parts,
            context,
        )

    parts = [
        build_tools_results_context(
            tool_result_blocks
        )
    ]
    parts.extend(
        extra_parts
    )

    return "\n".join(
        parts
    )
