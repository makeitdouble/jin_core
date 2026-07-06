from __future__ import annotations

import re
from copy import deepcopy
from xml.sax.saxutils import escape


RUNTIME_TODO_ACTIVE_STATUSES = {
    "pending",
    "resolved",
    "checking",
}
RUNTIME_TODO_TERMINAL_STATUSES = {
    "done",
    "blocked",
    "failed",
}
RUNTIME_TODO_ALLOWED_STATUSES = (
    "pending",
    "resolved",
    "checking",
    "done",
    "blocked",
    "failed",
)

TODO_LINE_RE = re.compile(
    r"^\s*(?P<id>\d+)\s*[\.)]\s*(?P<text>.+?)\s*$"
)
TODO_HEADING_RE = re.compile(
    r"^\s*(?:todo\s*id\b|todo\b|steps?\b|plan\b|items?\b)\s*:?.*$",
    re.IGNORECASE,
)
TODO_ID_RE = re.compile(r"(?<!\d)(\d+)(?!\d)")


def normalize_runtime_todo_status(status: str) -> str:
    normalized = str(status or "").strip().casefold()
    if normalized in RUNTIME_TODO_ALLOWED_STATUSES:
        return normalized
    return "pending"


def parse_runtime_todo_item_id(payload: str) -> int | None:
    match = TODO_ID_RE.search(str(payload or ""))
    if not match:
        return None

    try:
        return int(match.group(1))
    except (TypeError, ValueError):
        return None


def _has_unclosed_todo_delimiter(text: str) -> bool:
    value = str(text or "")
    pairs = (
        ("[", "]"),
        ("(", ")"),
        ("{", "}"),
    )
    for opener, closer in pairs:
        if value.count(opener) > value.count(closer):
            return True

    return (
        value.count('"') % 2 == 1
        or value.count("'") % 2 == 1
    )


def _looks_like_todo_continuation(
    raw_line: str,
    previous_text: str,
) -> bool:
    if not previous_text:
        return False

    line = str(raw_line or "")
    stripped = line.strip()
    if not stripped:
        return False

    if stripped.startswith("```"):
        return False

    if TODO_HEADING_RE.match(stripped):
        return False

    if stripped.startswith("<") and stripped.endswith(">"):
        return False

    if line[:1].isspace():
        return True

    previous = str(previous_text or "").rstrip()
    if _has_unclosed_todo_delimiter(previous):
        return True

    previous_lower = previous.casefold()
    continuation_suffixes = (
        ",",
        ";",
        ":",
        "-",
        "/",
        "\\",
        " and",
        " or",
        " with",
        " using",
        " in",
        " to",
        " for",
        " of",
    )
    return previous_lower.endswith(continuation_suffixes)


def parse_runtime_todo_payload(payload: str) -> list[dict]:
    items: list[dict] = []
    used_ids: set[int] = set()
    next_id = 1

    for raw_line in str(payload or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.startswith("```"):
            continue

        match = TODO_LINE_RE.match(line)
        if not match:
            if (
                items
                and _looks_like_todo_continuation(
                    raw_line,
                    str(items[-1].get("text", "")),
                )
            ):
                items[-1]["text"] = (
                    str(items[-1].get("text", "")).rstrip()
                    + " "
                    + line
                ).strip()
            continue

        text = (match.group("text") or "").strip()
        if not text:
            continue

        explicit_id = match.group("id")
        item_id = None
        if explicit_id:
            try:
                item_id = int(explicit_id)
            except (TypeError, ValueError):
                item_id = None

        if item_id is None or item_id in used_ids:
            while next_id in used_ids:
                next_id += 1
            item_id = next_id

        used_ids.add(item_id)
        next_id = max(next_id, item_id + 1)
        items.append({
            "id": item_id,
            "text": text,
            "status": "pending",
        })

    return items


def get_runtime_todo(context) -> list[dict]:
    todo = getattr(context, "runtime_todo", None)
    if not isinstance(todo, list):
        todo = []
        if context is not None:
            setattr(context, "runtime_todo", todo)
    return todo


def runtime_todo_has_active_items(todo: list[dict] | None) -> bool:
    return any(
        normalize_runtime_todo_status(item.get("status", ""))
        in RUNTIME_TODO_ACTIVE_STATUSES
        for item in (todo or [])
        if isinstance(item, dict)
    )


def has_active_runtime_todo(context) -> bool:
    if context is None:
        return False
    return runtime_todo_has_active_items(get_runtime_todo(context))


def find_runtime_todo_item(todo: list[dict], item_id: int | None) -> dict | None:
    if item_id is None:
        return None

    for item in todo:
        if not isinstance(item, dict):
            continue
        try:
            current_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue
        if current_id == item_id:
            return item

    return None


def first_runtime_todo_item_by_status(
    todo: list[dict],
    statuses: set[str] | tuple[str, ...],
) -> dict | None:
    status_set = {
        normalize_runtime_todo_status(status)
        for status in statuses
    }

    for item in todo:
        if not isinstance(item, dict):
            continue
        if normalize_runtime_todo_status(item.get("status", "")) in status_set:
            return item

    return None


def current_runtime_todo_item(todo: list[dict]) -> dict | None:
    return (
        first_runtime_todo_item_by_status(todo, ("checking",))
        or first_runtime_todo_item_by_status(todo, ("resolved",))
        or first_runtime_todo_item_by_status(todo, ("pending",))
    )


def create_runtime_todo(context, payload: str) -> dict:
    todo = get_runtime_todo(context)
    if runtime_todo_has_active_items(todo):
        return {
            "ok": False,
            "action": "create_todo_list",
            "guard": "todo_already_exists",
            "message": "A runtime TODO already exists. Continue it instead of creating a new one.",
            "runtime_todo": deepcopy(todo),
        }

    items = parse_runtime_todo_payload(payload)
    if not items:
        return {
            "ok": False,
            "action": "create_todo_list",
            "error": "empty_todo",
        }

    setattr(context, "runtime_todo", items)
    return {
        "ok": True,
        "action": "create_todo_list",
        "count": len(items),
        "runtime_todo": deepcopy(items),
    }


def update_runtime_todo_item_status(
    context,
    item_id: int | None,
    status: str,
) -> dict:
    todo = get_runtime_todo(context)
    item = find_runtime_todo_item(todo, item_id)
    normalized_status = normalize_runtime_todo_status(status)

    if item is None:
        return {
            "ok": False,
            "action": f"{normalized_status}_todo",
            "error": "todo_item_not_found",
            "id": item_id,
            "runtime_todo": deepcopy(todo),
        }

    current_status = normalize_runtime_todo_status(item.get("status", ""))
    if current_status in RUNTIME_TODO_TERMINAL_STATUSES and normalized_status != current_status:
        return {
            "ok": False,
            "action": f"{normalized_status}_todo",
            "guard": "resolved_todo_action_repeat",
            "message": "This TODO item is already terminal. Continue from next pending item.",
            "id": item_id,
            "status": current_status,
            "runtime_todo": deepcopy(todo),
        }

    item["status"] = normalized_status
    return {
        "ok": True,
        "action": f"{normalized_status}_todo",
        "id": item_id,
        "status": normalized_status,
        "runtime_todo": deepcopy(todo),
    }


def check_runtime_todo_item(context, item_id: int | None) -> dict:
    return update_runtime_todo_item_status(
        context,
        item_id,
        "checking",
    )


def resolve_runtime_todo_item(context, item_id: int | None) -> dict:
    return update_runtime_todo_item_status(
        context,
        item_id,
        "done",
    )


def mark_next_runtime_todo_item_resolved(context) -> dict | None:
    if context is None:
        return None

    todo = get_runtime_todo(context)
    if not runtime_todo_has_active_items(todo):
        return None

    current_item = (
        first_runtime_todo_item_by_status(todo, ("checking",))
        or first_runtime_todo_item_by_status(todo, ("resolved",))
    )
    if current_item is not None:
        return current_item

    pending_item = first_runtime_todo_item_by_status(todo, ("pending",))
    if pending_item is None:
        return None

    pending_item["status"] = "resolved"
    return pending_item


def _extract_runtime_todo_result_paths(result: dict) -> list[str]:
    if not isinstance(result, dict):
        return []

    paths: list[str] = []

    path = str(
        result.get("path", "")
        or ""
    ).strip()
    if path:
        paths.append(path)

    missing = result.get("missing")
    if isinstance(missing, list):
        for item in missing:
            if not isinstance(item, dict):
                continue
            missing_path = str(
                item.get("path", "")
                or ""
            ).strip()
            if missing_path:
                paths.append(missing_path)

    child_results = result.get("results")
    if isinstance(child_results, list):
        for child in child_results:
            if isinstance(child, dict):
                paths.extend(
                    _extract_runtime_todo_result_paths(child)
                )

    deduped: list[str] = []
    seen: set[str] = set()
    for item in paths:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)

    return deduped


def _runtime_todo_result_ok(result: dict) -> bool:
    if not isinstance(result, dict):
        return False

    child_results = result.get("results")
    if isinstance(child_results, list):
        return all(
            _runtime_todo_result_ok(child)
            for child in child_results
            if isinstance(child, dict)
        )

    return bool(result.get("ok"))


def _copy_runtime_todo_result_fields(
    item: dict,
    result: dict,
) -> None:
    if not isinstance(item, dict) or not isinstance(result, dict):
        return

    action = str(
        result.get("action", "")
        or ""
    ).strip()
    if action:
        item["result_action"] = action

    paths = _extract_runtime_todo_result_paths(result)
    if paths:
        item["result_path"] = paths[0]
        if len(paths) > 1:
            item["result_paths"] = paths
        else:
            item.pop("result_paths", None)

    if result.get("status"):
        item["result_status"] = str(
            result.get("status", "")
            or ""
        ).strip()

    if result.get("error"):
        item["result_error"] = str(
            result.get("error", "")
            or ""
        ).strip()
    else:
        item.pop("result_error", None)


def apply_runtime_todo_action_result(
    context,
    todo_item: dict | None,
    result: dict,
) -> dict | None:
    if context is None or not isinstance(todo_item, dict):
        return None

    item_id = parse_runtime_todo_item_id(
        str(todo_item.get("id", "") or "")
    )
    item = find_runtime_todo_item(
        get_runtime_todo(context),
        item_id,
    )
    if item is None:
        return None

    _copy_runtime_todo_result_fields(
        item,
        result,
    )

    if _runtime_todo_result_ok(result):
        item["status"] = "resolved"
    elif result.get("guard"):
        item["status"] = "blocked"
    else:
        item["status"] = "failed"

    return item


def attach_runtime_todo_item_to_result(result: dict, todo_item: dict | None) -> dict:
    if not isinstance(result, dict) or not isinstance(todo_item, dict):
        return result

    updated = dict(result)
    snapshot = {
        "id": todo_item.get("id"),
        "text": todo_item.get("text", ""),
        "status": todo_item.get("status", ""),
    }

    for key in (
        "result_action",
        "result_path",
        "result_paths",
        "result_status",
        "result_error",
    ):
        if key in todo_item:
            snapshot[key] = todo_item.get(key)

    updated["runtime_todo_item"] = snapshot
    return updated


def normalize_file_exists_for_runtime_todo(result: dict, context=None) -> dict:
    if not isinstance(result, dict):
        return result

    active = has_active_runtime_todo(context)
    updated = dict(result)

    if isinstance(updated.get("results"), list):
        updated["results"] = [
            normalize_file_exists_for_runtime_todo(item, context)
            if isinstance(item, dict)
            else item
            for item in updated["results"]
        ]
        if active:
            updated["ok"] = all(
                bool(item.get("ok"))
                for item in updated["results"]
                if isinstance(item, dict)
            )
        return updated

    if (
        active
        and updated.get("error") == "file_exists"
        and not updated.get("ok")
    ):
        updated["ok"] = True
        updated["status"] = "noop_file_already_exists"
        updated["satisfies_todo"] = True
        updated.pop("error", None)

    return updated


def format_runtime_todo_xml(todo: list[dict] | None) -> str:
    items = [
        item
        for item in (todo or [])
        if isinstance(item, dict)
    ]
    if not items:
        return ""

    lines = ["<CURRENT_RUNTIME_TODO_LIST>"]
    for item in items:
        try:
            item_id = int(item.get("id"))
        except (TypeError, ValueError):
            continue

        text = escape(str(item.get("text", "")).strip())
        status = escape(normalize_runtime_todo_status(item.get("status", "")))
        attributes = [
            f'id="{item_id}"',
            f'status="{status}"',
        ]

        result_path = str(
            item.get("result_path", "")
            or ""
        ).strip()
        if result_path:
            attributes.append(
                f'actual_path="{escape(result_path)}"'
            )

        result_action = str(
            item.get("result_action", "")
            or ""
        ).strip()
        if result_action:
            attributes.append(
                f'result_action="{escape(result_action)}"'
            )

        result_status = str(
            item.get("result_status", "")
            or ""
        ).strip()
        if result_status:
            attributes.append(
                f'result_status="{escape(result_status)}"'
            )

        result_error = str(
            item.get("result_error", "")
            or ""
        ).strip()
        if result_error:
            attributes.append(
                f'result_error="{escape(result_error)}"'
            )

        lines.append(
            f'  <ITEM {" ".join(attributes)}>{text}</ITEM>'
        )

    lines.append("</CURRENT_RUNTIME_TODO_LIST>")
    return "\n".join(lines)


def build_runtime_todo_history_text(result: dict) -> str:
    if not isinstance(result, dict):
        return "Runtime TODO updated"

    action = str(result.get("action", "runtime_todo") or "runtime_todo")
    item_id = result.get("id")

    if action == "create_todo_list":
        if result.get("ok"):
            return f"Runtime TODO LIST created: {result.get('count', 0)} items"
        return f"Runtime TODO LIST create blocked: {result.get('guard') or result.get('error') or 'unknown'}"

    if action == "checking_todo":
        return f"Runtime TODO item #{item_id} checking"

    if action == "done_todo":
        return f"Runtime TODO item #{item_id} done"

    if result.get("guard"):
        return f"Runtime TODO guard: {result.get('guard')}"

    if result.get("error"):
        return f"Runtime TODO error: {result.get('error')}"

    return "Runtime TODO updated"
