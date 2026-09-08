# Builds the full tool results context from search, asset, memory, and session results.
import time
from xml.sax.saxutils import escape

from contracts.rules_assembler import (
    RUNTIME_ACTION_DEEP_WEB_SEARCH,
    RUNTIME_ACTION_UPDATE_LT_FACTS,
    RUNTIME_ACTION_RECALL_FACT_CONTEXT,
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
    TOOL_RESULT_KIND_FACT_CONTEXT,
    TOOL_RESULT_KIND_RUNTIME_ACTION,
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

from .runtime_action_result_text import (
    format_runtime_action_result,
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


def _escape_runtime_action_payload(payload) -> str:
    lines = []
    in_schema = False

    for line in str(payload or "").splitlines():
        stripped = line.strip()
        if stripped == "Correct action schema:":
            in_schema = True

        escaped_line = escape(line)
        if (
            in_schema
            and stripped.startswith("<")
            and stripped.endswith(">")
        ):
            escaped_line = (
                escaped_line
                .replace("&lt;", "<")
                .replace("&gt;", ">")
            )

        lines.append(escaped_line)

    return "\n".join(lines)


def _build_recorded_tool_result_block(
    attrs: str,
    payload: str,
    *,
    raw_blocks=None,
    created_at=None,
    now: float | None = None,
) -> str:
    """Build one TOOL_RESULT while allowing trusted nested source blocks."""
    body = []
    escaped_payload = _escape_runtime_action_payload(payload)
    if escaped_payload.strip():
        body.append(indent_xml(escaped_payload))
    for block in raw_blocks or ():
        if str(block or "").strip():
            body.append(indent_xml(str(block)))

    return (
        f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
        + "\n".join(body)
        + "\n    </TOOL_RESULT>"
    )


def _persistent_file_result_id(context, result) -> str:
    if not isinstance(result, dict):
        return ""
    if (
        result.get("action") != "attach_file_content"
        or result.get("source") == "project"
        or result.get("ok") is False
        or result.get("loaded") is False
    ):
        return ""
    file_id = str(result.get("id") or "").strip().lower()
    active = {
        str(value or "").strip().lower()
        for value in getattr(context, "runtime_attached_file_ids", []) or []
    }
    return file_id if file_id and file_id in active else ""


def _consume_persistent_text_budget(content: str, budget: dict | None) -> str:
    if budget is None:
        return str(content or "")
    try:
        remaining = max(0, int(budget.get("remaining", 0)))
    except (TypeError, ValueError):
        remaining = 0
    source = str(content or "")
    visible = source[:remaining]
    budget["remaining"] = max(0, remaining - len(visible))
    if len(visible) < len(source):
        visible += (
            f"\n[attachment text truncated: {len(source) - len(visible)} chars omitted]"
        )
    return visible


def _file_result_content_block(
    context,
    result,
    *,
    persistent_text_budget: dict | None = None,
) -> str:
    if not isinstance(result, dict) or result.get("ok") is False or result.get("loaded") is False:
        return ""

    from .files import (
        format_file_content,
        project_file_content_label,
        project_file_ref,
    )

    ref = project_file_ref(result)
    if ref:
        from .files import project_file_result_active
        if not project_file_result_active(context, result) or "content" not in result:
            return ""
        return format_file_content(
            project_file_content_label(result),
            result.get("content", ""),
        )

    file_id = _persistent_file_result_id(context, result)
    if not file_id:
        return ""

    from utils import attached_files_store as files

    record = files.get_file_record(file_id)
    if (
        not record
        or record.get("kind") != "text"
        or str(record.get("name") or "").lower().endswith(".jin-folder")
    ):
        return ""
    try:
        content = (files.FILES_DIR / record["stored_name"]).read_text(
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        content = ""
    return format_file_content(
        files.file_display_name(record.get("name") or file_id),
        _consume_persistent_text_budget(content, persistent_text_budget),
    )


def _append_unowned_attached_file_results(
    parts: list[str],
    context,
    *,
    represented_ids: set[str],
    persistent_text_budget: dict | None = None,
) -> None:
    """Keep user-attached text inside TOOLS_RESULTS even without a model action."""
    if context is None:
        return

    from utils import attached_files_store as files
    from .files import format_file_content

    for raw_id in getattr(context, "runtime_attached_file_ids", []) or []:
        file_id = str(raw_id or "").strip().lower()
        if not file_id or file_id in represented_ids:
            continue
        record = files.get_file_record(file_id)
        if (
            not record
            or record.get("kind") != "text"
            or str(record.get("name") or "").lower().endswith(".jin-folder")
        ):
            continue
        try:
            content = (files.FILES_DIR / record["stored_name"]).read_text(
                encoding="utf-8",
                errors="replace",
            )
        except OSError:
            content = ""
        content_block = format_file_content(
            files.file_display_name(record.get("name") or file_id),
            _consume_persistent_text_budget(content, persistent_text_budget),
        )
        attrs = f'name="ATTACHED_FILE" id="{escape(file_id)}"'
        payload = (
            f"File: {files.file_display_name(record.get('name') or file_id)}\n"
            f"ID: {file_id}"
        )
        parts.append(
            _build_recorded_tool_result_block(
                attrs,
                payload,
                raw_blocks=[content_block],
            )
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
    *,
    represented_attachment_ids: set[str] | None = None,
    embedded_project_refs: set[str] | None = None,
    persistent_text_budget: dict | None = None,
) -> bool:

    if context is None:
        return False

    from utils.project_context import project_tool_result_visible

    appended = False
    now = time.time()
    if represented_attachment_ids is None:
        represented_attachment_ids = set()
    if embedded_project_refs is None:
        embedded_project_refs = set()

    recorded_results = get_runtime_tool_results(context)
    turn_count = int(
        getattr(context, "runtime_tool_results_turn_count", 0) or 0
    )
    current_turn_start = len(recorded_results) - turn_count

    # Render newest first without mutating append order used by ids/restore.
    for index in range(len(recorded_results) - 1, -1, -1):
        entry = recorded_results[index]
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
        current_turn = index >= current_turn_start
        if not project_tool_result_visible(context, kind, result, current_turn=current_turn):
            # An intentionally filtered recorded result must not fall back to legacy slots.
            appended = True
            continue
        created_at = get_runtime_tool_result_created_at(
            context,
            index,
            entry,
        )

        tool_id_attr = f'tool_id="{escape(entry["tool_id"])}" ' if entry.get("tool_id") else ""

        if kind == TOOL_RESULT_KIND_SEARCH:
            search_result = strip_empty_results_xml(
                str(
                    result
                    or ""
                )
            )
            if not search_result:
                continue

            attrs = tool_id_attr + f'name="{escape(RUNTIME_ACTION_WEB_SEARCH)}"'
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

            attrs = tool_id_attr + f'name="{escape(RUNTIME_ACTION_DEEP_WEB_SEARCH)}"'
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

            from .files import project_file_load_key, project_file_ref
            project_ref = project_file_ref(result)
            project_load_key = project_file_load_key(result)
            content_block = ""
            if project_ref and project_load_key not in embedded_project_refs:
                content_block = _file_result_content_block(
                    context,
                    result,
                    persistent_text_budget=persistent_text_budget,
                )
                if content_block and project_load_key is not None:
                    embedded_project_refs.add(project_load_key)
            blocks = []
            for name, payload in sections:
                attrs = tool_id_attr + f'name="{escape(name)}"'
                blocks.append(
                    _build_recorded_tool_result_block(
                        attrs,
                        payload,
                        raw_blocks=[content_block] if content_block else None,
                        created_at=created_at,
                        now=now,
                    )
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
                attrs = tool_id_attr + f'name="{escape(name)}"'
                blocks.append(
                    f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                    f"{indent_xml(_escape_runtime_action_payload(payload))}\n"
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
            if result.get("action") != "list_files":
                from .files import format_file_result
                attrs = tool_id_attr + f'name="{escape(str(result.get("action", "file")).upper())}"'
                payload = format_file_result(result)
                persistent_id = _persistent_file_result_id(
                    context,
                    result,
                )
                persistent_already_represented = bool(
                    persistent_id
                    and persistent_id in represented_attachment_ids
                )
                if persistent_id:
                    represented_attachment_ids.add(persistent_id)
                from .files import project_file_load_key, project_file_ref
                project_ref = project_file_ref(result)
                project_load_key = project_file_load_key(result)
                content_block = ""
                if (
                    not persistent_already_represented
                    and (not project_ref or project_load_key not in embedded_project_refs)
                ):
                    content_block = _file_result_content_block(
                        context,
                        result,
                        persistent_text_budget=persistent_text_budget,
                    )
                    if content_block and project_load_key is not None:
                        embedded_project_refs.add(project_load_key)
                parts.append(
                    _build_recorded_tool_result_block(
                        attrs,
                        payload,
                        raw_blocks=[content_block] if content_block else None,
                        created_at=created_at,
                        now=now,
                    )
                )
                appended = True
                continue
            lines = result.get("lines", [])
            if not isinstance(lines, list):
                lines = []
            file_lines = "\n".join(
                str(line or "").strip()
                for line in lines
                if str(line or "").strip()
            )
            payload = (
                "Files:\n"
                + (
                    "\n".join(
                        f"  {line}"
                        for line in file_lines.splitlines()
                    )
                    if file_lines
                    else "  No files."
                )
            )
            attrs = tool_id_attr + 'name="LIST_FILES"'
            parts.append(
                f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                f"{indent_xml(_escape_runtime_action_payload(payload))}\n"
                "    </TOOL_RESULT>"
            )
            appended = True
            continue

        if kind in {TOOL_RESULT_KIND_LT, TOOL_RESULT_KIND_RUNTIME_ACTION}:
            if not isinstance(result, dict):
                continue

            runtime_action = (
                RUNTIME_ACTION_UPDATE_LT_FACTS
                if kind == TOOL_RESULT_KIND_LT
                else str(result.get("action") or "").upper()
            )
            payload = format_runtime_action_result(
                result,
                runtime_action=runtime_action,
            )
            if not payload:
                continue

            attrs = tool_id_attr + f'name="{escape(runtime_action)}"'
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
                f"{indent_xml(_escape_runtime_action_payload(payload))}\n"
                "    </TOOL_RESULT>"
            )
            appended = True
            continue

        if kind == TOOL_RESULT_KIND_FACT_CONTEXT:
            if not isinstance(result, dict):
                continue

            payload = format_runtime_action_result(
                result, runtime_action=RUNTIME_ACTION_RECALL_FACT_CONTEXT,
            )
            attrs = tool_id_attr + f'name="{escape(RUNTIME_ACTION_RECALL_FACT_CONTEXT)}"'
            result_id = str(entry.get("id", "") or "").strip()
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
                attrs = tool_id_attr + f'name="{escape(name)}"'
                blocks.append(
                    f"{_build_tool_result_open_tag(attrs, created_at=created_at, now=now)}\n"
                    f"{indent_xml(_escape_runtime_action_payload(payload))}\n"
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
    pending_results = []

    def flush_pending() -> None:
        if not pending_results:
            return
        for name, payload in format_asset_result_sections(
            list(pending_results),
            context,
        ):
            attrs = f'name="{escape(name)}"'
            tool_result_blocks.append(
                _build_recorded_tool_result_block(
                    attrs,
                    payload,
                )
            )
        pending_results.clear()

    from .files import project_file_ref
    embedded_project_refs = set()

    for result in reversed(asset_results[-5:]):
        project_ref = project_file_ref(result)
        if project_ref:
            flush_pending()
            for name, payload in format_asset_result_sections(
                [result],
                context,
            ):
                attrs = f'name="{escape(name)}"'
                content_block = ""
                if project_ref not in embedded_project_refs:
                    content_block = _file_result_content_block(
                        context,
                        result,
                    )
                    if content_block:
                        embedded_project_refs.add(project_ref)
                tool_result_blocks.append(
                    _build_recorded_tool_result_block(
                        attrs,
                        payload,
                        raw_blocks=[content_block] if content_block else None,
                    )
                )
            continue
        pending_results.append(result)

    flush_pending()

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

    from utils.project_context import project_tool_result_visible
    delayed_memory_results = [
        result for result in delayed_memory_results
        if project_tool_result_visible(context, TOOL_RESULT_KIND_DELAYED_MEMORY, result)
    ]
    if not delayed_memory_results:
        return

    tool_result_blocks = []

    for name, payload in format_delayed_memory_result_sections(
        list(reversed(delayed_memory_results[-5:])),
    ):
        attrs = f'name="{escape(name)}"'
        tool_result_blocks.append(
            f"{_build_tool_result_open_tag(attrs)}\n"
            f"{indent_xml(_escape_runtime_action_payload(payload))}\n"
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
    represented_attachment_ids = set()
    embedded_project_refs = set()
    try:
        from websocket.attachments import TEXT_ATTACHMENT_CONTEXT_MAX_CHARS
        persistent_text_budget = {
            "remaining": int(TEXT_ATTACHMENT_CONTEXT_MAX_CHARS)
        }
    except (ImportError, TypeError, ValueError):
        persistent_text_budget = {"remaining": 32000}

    if not _append_recorded_tool_results(
        tool_result_blocks,
        context,
        represented_attachment_ids=represented_attachment_ids,
        embedded_project_refs=embedded_project_refs,
        persistent_text_budget=persistent_text_budget,
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

    _append_unowned_attached_file_results(
        tool_result_blocks,
        context,
        represented_ids=represented_attachment_ids,
        persistent_text_budget=persistent_text_budget,
    )

    return build_tools_results_context(
        tool_result_blocks
    )
