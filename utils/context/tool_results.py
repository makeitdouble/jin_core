# Builds the full tool results context from search, asset, memory, and session results.
import json
import time
from xml.sax.saxutils import escape

from contracts.rules_assembler import (
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_WEB_SEARCH,
)
from utils.brain_client_utils import (
    indent_xml,
    strip_empty_results_xml,
)
from utils.tool_results import (
    TOOL_RESULT_KIND_ACTIVE_MEMORY,
    TOOL_RESULT_KIND_ASSET,
    TOOL_RESULT_KIND_DELAYED_MEMORY,
    TOOL_RESULT_KIND_DEEP_SEARCH,
    TOOL_RESULT_KIND_SEARCH,
    TOOL_RESULT_KIND_FILES,
    TOOL_RESULT_KIND_LT,
    get_runtime_tool_result_created_at,
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
)


def _format_tool_result_age(
    elapsed_seconds,
) -> str:

    seconds = max(
        1,
        int(
            elapsed_seconds
        ),
    )

    if seconds < 60:
        return f"{seconds}s"

    minutes, seconds = divmod(
        seconds,
        60,
    )
    if minutes < 60:
        if seconds:
            return f"{minutes}m {seconds}s"
        return f"{minutes}m"

    hours, minutes = divmod(
        minutes,
        60,
    )
    if hours < 24:
        if minutes:
            return f"{hours}h {minutes}m"
        return f"{hours}h"

    days, hours = divmod(
        hours,
        24,
    )
    if hours:
        return f"{days}d {hours}h"
    return f"{days}d"


def _format_tool_result_age_suffix(
    created_at,
    *,
    now: float | None = None,
) -> str:

    if created_at is None:
        return ""

    try:
        timestamp = float(
            created_at
        )
    except (
        TypeError,
        ValueError,
    ):
        return ""

    if timestamp <= 0:
        return ""

    if now is None:
        now = time.time()

    return (
        f" ( {_format_tool_result_age(now - timestamp)} ago )"
    )


def _build_tool_result_open_tag(
    attrs: str,
    *,
    created_at=None,
    now: float | None = None,
) -> str:

    age_suffix = _format_tool_result_age_suffix(
        created_at,
        now=now,
    )
    close = (
        " >"
        if age_suffix
        else ">"
    )

    return f"    <TOOL_RESULT {attrs}{age_suffix}{close}"


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
        f'name="{escape(RUNTIME_ACTION_WEB_SEARCH)}"'
    )

    if search_result_id:
        tool_result_attrs = (
            f'{tool_result_attrs} '
            f'id="{escape(search_result_id)}"'
        )

    parts.append(
        f"{_build_tool_result_open_tag(tool_result_attrs)}\n"
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
    now = time.time()

    for index, entry in enumerate(
        get_runtime_tool_results(
        context
        )
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
        created_at = get_runtime_tool_result_created_at(
            context,
            index,
            entry,
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

            attrs = f'name="{escape(RUNTIME_ACTION_WEB_SEARCH)}"'
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
                f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                f"{indent_xml(search_result)}\n"
                "    </TOOL_RESULT>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_DEEP_SEARCH:
            deep_result = str(
                result
                or ""
            ).strip()
            if not deep_result:
                continue

            attrs = f'name="{escape(RUNTIME_ACTION_DEEP_WEB_SEARCH)}"'
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
                f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                f"{indent_xml(escape(deep_result))}\n"
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

            blocks = []
            for name, payload in sections:
                attrs = f'name="{escape(name)}"'
                blocks.append(
                    f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                    f"{indent_xml(escape(payload))}\n"
                    "    </TOOL_RESULT>"
                )
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

            blocks = []
            for name, payload in sections:
                attrs = f'name="{escape(name)}"'
                blocks.append(
                    f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                    f"{indent_xml(escape(payload))}\n"
                    "    </TOOL_RESULT>"
                )
            parts.extend(
                blocks
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_FILES:
            if not isinstance(result, dict):
                continue
            lines = result.get("lines", [])
            if not isinstance(lines, list):
                lines = []
            payload = "\n".join(
                str(line or "").strip()
                for line in lines
                if str(line or "").strip()
            )
            if not payload:
                payload = "No files."
            attrs = 'name="LIST_FILES"'
            parts.append(
                f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                f"{indent_xml(escape(payload))}\n"
                "    </TOOL_RESULT>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_LT:
            if not isinstance(result, dict):
                continue

            payload = json.dumps(
                result,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
            if not payload:
                continue

            attrs = f'name="{escape(RUNTIME_ACTION_UPDATE_LT_FACTS)}"'
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
                f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                f"{indent_xml(escape(payload))}\n"
                "    </TOOL_RESULT>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_DELAYED_MEMORY:
            sections = format_delayed_memory_result_sections(
                [result]
            )
            if not sections:
                continue

            blocks = []
            for name, payload in sections:
                attrs = f'name="{escape(name)}"'
                blocks.append(
                    f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                    f"{indent_xml(escape(payload))}\n"
                    "    </TOOL_RESULT>"
                )
            parts.extend(
                blocks
            )
            appended = True

    return appended


def build_loaded_skills_content_context(
    context=None,
) -> str:

    if context is None:
        return ""

    loaded_skills = list(
        getattr(
            context,
            "runtime_loaded_skills",
            [],
        )
        or []
    )

    if not loaded_skills:
        return ""

    return (
        "<LOADED_SKILLS_CONTENT>\n"
        f"{indent_xml(escape(format_tool_result_payload(loaded_skills)))}\n"
        "</LOADED_SKILLS_CONTENT>"
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
    asset_results = (
        retry_context
        + current_asset_results
    )

    if not asset_results:
        return

    tool_result_blocks = []
    for name, payload in format_asset_result_sections(
        asset_results[-5:],
        context,
    ):
        attrs = f'name="{escape(name)}"'
        tool_result_blocks.append(
            f"{_build_tool_result_open_tag(attrs)}\n"
            f"{indent_xml(escape(payload))}\n"
            "    </TOOL_RESULT>"
        )

    parts.extend(
        tool_result_blocks
    )


def _load_delayed_memory_results(
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
        attrs = f'name="{escape(name)}"'
        tool_result_blocks.append(
            f"{_build_tool_result_open_tag(attrs)}\n"
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

    if not _append_recorded_tool_results(
        tool_result_blocks,
        context,
    ):
        _append_tool_results(
            tool_result_blocks,
            context,
        )
        _append_asset_results(
            tool_result_blocks,
            context,
        )
        _load_delayed_memory_results(
            tool_result_blocks,
            context,
        )

    return build_tools_results_context(
        tool_result_blocks
    )
