# Builds the full tool results context from search, asset, memory, and session results.
from xml.sax.saxutils import escape

from utils.brain_client_utils import (
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
    format_asset_result_sections,
)
from .delayed_memory import (
    format_delayed_memory_result_sections,
)
from .formatting import (
    format_tool_result_payload,
)
from .result_sections import (
    format_active_memory_result_sections,
    format_session_result_sections,
)


def _append_tool_results(
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
        f"    <TOOL_RESULT {tool_result_attrs}>\n"
        f"{indent_xml(search_result)}\n"
        "    </TOOL_RESULT>"
    )


def _append_recorded_tool_results(
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
                f"    <TOOL_RESULT {attrs}>\n"
                f"{indent_xml(search_result)}\n"
                "    </TOOL_RESULT>"
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
            parts.extend(
                blocks
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
            parts.extend(
                blocks
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
            parts.extend(
                blocks
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
            parts.extend(
                blocks
            )
            appended = True

    return appended


def _append_appended_skills(
    parts: list[str],
    context=None,
) -> None:

    if context is None:
        return

    appended_skills = list(
        getattr(
            context,
            "runtime_appended_skills",
            [],
        )
        or []
    )

    if not appended_skills:
        return

    parts.append(
        "<APPENDED_SKILLS_CONTENT>\n"
        f"{indent_xml(escape(format_tool_result_payload(appended_skills)))}\n"
        "</APPENDED_SKILLS_CONTENT>"
    )


def _append_asset_results(
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


def _append_delayed_memory_results(
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

    parts.extend(
        tool_result_blocks
    )


def build_tool_results_context(
    context=None,
) -> str:

    tool_result_blocks = []
    extra_parts = []

    if _append_recorded_tool_results(
        tool_result_blocks,
        context,
    ):
        _append_appended_skills(
            extra_parts,
            context,
        )
    else:
        _append_tool_results(
            tool_result_blocks,
            context,
        )
        _append_asset_results(
            tool_result_blocks,
            context,
        )
        _append_delayed_memory_results(
            tool_result_blocks,
            context,
        )
        _append_appended_skills(
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
